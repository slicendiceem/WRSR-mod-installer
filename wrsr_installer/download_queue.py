"""The download queue: downloads and installs one mod at a time, and adds the mods they need."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Callable, List, Optional

from PyQt5.QtCore import QObject, pyqtSignal

from .archive import ArchiveError
from .cancel import CancelToken
from .downloader import DownloadError, Progress
from .skymods import CatalogueMod, Prerequisite, SkymodsError
from .tasks import Task, TaskContext, run_task

RESOLVING, WAITING, ACTIVE, DONE, FAILED, CANCELLED = (
    'resolving', 'waiting', 'active', 'done', 'failed', 'cancelled')
UNFINISHED = {RESOLVING, WAITING, ACTIVE}

InstallFn = Callable[[CatalogueMod, Callable[[Progress], None], CancelToken], Path]
LoadRequirementsFn = Callable[[CatalogueMod, CancelToken], List[Prerequisite]]  # loads the mod's page
LookUpFn = Callable[[str, CancelToken], Optional[CatalogueMod]]                 # finds a mod by Steam ID
IsInstalledFn = Callable[[str, Optional[str]], bool]


@dataclass(eq=False)
class DownloadItem:
    mod: CatalogueMod
    state: str = WAITING          # RESOLVING while the mod's download link is still unknown
    progress: int = -1            # percent; -1 while unknown
    message: str = 'Waiting'
    required_by: Optional[str] = None
    placeholder: bool = False     # a required mod that hasn't been found on Skymods yet
    missing: List[Prerequisite] = field(default_factory=list)  # required, but Skymods gives no Steam ID
    installed_requirements: List[str] = field(default_factory=list)
    requirements_known: bool = False
    check_error: str = ''         # why its requirements couldn't be found out
    manual_url: Optional[str] = None  # set when the user has to download it in a browser
    installed_path: Optional[Path] = None
    task: Optional[Task] = field(default=None, repr=False)          # the download
    checks: List[Task] = field(default_factory=list, repr=False)    # page loads and lookups
    _cancel_requested: bool = field(default=False, repr=False)

    @property
    def key(self) -> str:
        return self.mod.key

    @property
    def finished(self) -> bool:
        return self.state not in UNFINISHED

    @property
    def checking(self) -> bool:
        return bool(self.checks)


@dataclass
class QueueSummary:
    installed: List[str] = field(default_factory=list)
    failed: List[str] = field(default_factory=list)
    cancelled: List[str] = field(default_factory=list)


def error_text(error: Exception) -> str:
    if isinstance(error, (DownloadError, SkymodsError, ArchiveError)):
        return str(error)
    if isinstance(error, PermissionError):
        return 'Windows refused access to a file. Close the game if it is running, then retry.'
    if isinstance(error, OSError):
        return f'File error: {error.strerror or error}'
    return f'Unexpected error: {error!r}'


class DownloadQueue(QObject):
    """Downloads one mod at a time, and queues the mods each one needs.

    A required mod gets its row as soon as its name is known: at once if the mod's page was
    already loaded, otherwise when it loads. The row then fills in when the mod is found on
    Skymods. Skymods can take a minute per page, so none of this holds up the mod's own
    download, and the lookups run side by side.
    """

    item_added = pyqtSignal(object)      # DownloadItem
    item_changed = pyqtSignal(object)    # DownloadItem
    item_removed = pyqtSignal(object)    # DownloadItem
    mod_installed = pyqtSignal(object)   # DownloadItem
    finished = pyqtSignal(object)        # QueueSummary, once nothing is left to do

    def __init__(self, install: InstallFn, load_requirements: LoadRequirementsFn, look_up: LookUpFn,
                 is_installed: IsInstalledFn = lambda name, steam_id: False,
                 parent: Optional[QObject] = None):
        super().__init__(parent)
        self._install = install
        self._load_requirements = load_requirements
        self._look_up = look_up
        self._is_installed = is_installed
        self.items: List[DownloadItem] = []
        self._summary = QueueSummary()
        self._busy = False
        self._checks_running = 0  # including those of items no longer in the list

    # --- queries -----------------------------------------------------------

    def is_queued(self, key: str) -> bool:
        return any(item.key == key and not item.finished for item in self.items)

    @property
    def active_count(self) -> int:
        return sum(1 for item in self.items if not item.finished)

    def _covers(self, key: str) -> bool:
        """Is this mod queued, being downloaded, or already downloaded?"""
        return any(item.key == key and item.state not in (FAILED, CANCELLED) for item in self.items)

    # --- commands ----------------------------------------------------------

    def add(self, mod: CatalogueMod) -> Optional[DownloadItem]:
        """Queue mod, and the mods it needs. None if it's already queued."""
        if self.is_queued(mod.key):
            return None
        item = DownloadItem(mod)
        if not mod.download_url:
            item.state, item.message = RESOLVING, 'Looking up the mod'
        self.items.append(item)
        self._busy = True
        self.item_added.emit(item)
        self._find_requirements(item)
        self._pump()
        return item

    def cancel(self, item: DownloadItem) -> None:
        for check in item.checks:
            check.cancel()
        if item.finished:
            return
        if item.state == ACTIVE:
            # The download stops at its next checkpoint; _on_cancelled finishes the job.
            item._cancel_requested = True
            item.message = 'Cancelling'
            item.task.cancel()
            self.item_changed.emit(item)
            return
        self._set(item, CANCELLED, 'Cancelled')
        self._pump()

    def cancel_all(self) -> None:
        for item in list(self.items):
            self.cancel(item)

    def remove(self, item: DownloadItem) -> None:
        """Take an item off the list. Unfinished ones are cancelled; a finished one may still
        be finding the mods it needs, and they're still queued when found."""
        if item.state == ACTIVE:
            return
        if not item.finished:
            self.cancel(item)
        if item in self.items:
            self.items.remove(item)
            self.item_removed.emit(item)
            self._pump()

    def retry(self, item: DownloadItem) -> None:
        if item.state not in (FAILED, CANCELLED):
            return
        item.manual_url = None
        item.progress = -1
        self._busy = True
        if item.placeholder:
            self._set(item, RESOLVING, 'Looking up its download')
            self._check(item, partial(self._look_up_task, item.mod.steam_id), self._on_found)
        elif not item.mod.download_url:
            self._set(item, RESOLVING, 'Looking up the mod')
            self._find_requirements(item)
        else:
            self._set(item, WAITING, 'Waiting')
            if not item.requirements_known and not item.checking:
                self._find_requirements(item)
        self._pump()

    def clear_finished(self) -> None:
        for item in [i for i in self.items if i.finished]:
            self.items.remove(item)
            self.item_removed.emit(item)

    # --- finding the mods a mod needs --------------------------------------

    def _find_requirements(self, item: DownloadItem) -> None:
        mod = item.mod
        if mod.details_loaded:
            self._on_requirements(item, list(mod.prerequisites))
        elif mod.has_requirements or not mod.download_url:
            self._check(item, partial(self._load_requirements_task, mod), self._on_requirements)
        else:
            item.requirements_known = True  # its listing says it needs nothing else

    def _load_requirements_task(self, mod: CatalogueMod, ctx: TaskContext) -> List[Prerequisite]:
        return self._load_requirements(mod, ctx.cancel)

    def _look_up_task(self, steam_id: str, ctx: TaskContext) -> Optional[CatalogueMod]:
        return self._look_up(steam_id, ctx.cancel)

    def _check(self, item: DownloadItem, work, on_result) -> None:
        item.check_error = ''
        self._checks_running += 1
        started = []
        # Callbacks run on this (GUI) thread, so started is filled in before any of them can run.
        task = run_task(work, on_result=partial(on_result, item),
                        on_error=partial(self._on_check_failed, item),
                        on_finished=lambda: self._on_check_done(item, started[0]))
        started.append(task)
        item.checks.append(task)

    def _dropped(self, item: DownloadItem) -> bool:
        return item.state == CANCELLED or item._cancel_requested

    def _on_requirements(self, item: DownloadItem, prerequisites: List[Prerequisite]) -> None:
        if self._dropped(item):
            return
        item.requirements_known = True
        if item.state == RESOLVING and not item.placeholder:  # its page says if it has a download
            if not item.mod.download_url:
                self._set(item, FAILED, "Skymods doesn't offer a download for this mod.")
                return
            self._set(item, WAITING, 'Waiting')
        if item in self.items:
            index = self.items.index(item)
            if item.state not in (RESOLVING, WAITING):
                index += 1  # it's already downloading (or done): the mods it needs come next
        else:
            index = len(self.items)  # cleared from the list, but its requirements still count
        for prereq in prerequisites:
            if not prereq.steam_id:
                item.missing.append(prereq)
            elif self._is_installed(prereq.name, prereq.steam_id):
                item.installed_requirements.append(prereq.name)
            elif not self._covers(prereq.steam_id):
                required = DownloadItem(CatalogueMod(name=prereq.name, url='', steam_id=prereq.steam_id),
                                        state=RESOLVING, message='Looking up its download',
                                        required_by=item.mod.name, placeholder=True)
                self.items.insert(index, required)
                index += 1
                self._busy = True
                self.item_added.emit(required)
                self._check(required, partial(self._look_up_task, prereq.steam_id), self._on_found)
        self.item_changed.emit(item)

    def _on_found(self, item: DownloadItem, listed: Optional[CatalogueMod]) -> None:
        if self._dropped(item):
            return
        if listed is None:
            self._set(item, FAILED, 'Not on Skymods. You may have to get it from the Steam Workshop.')
            return
        item.mod = listed
        item.placeholder = False
        if listed.download_url:
            self._set(item, WAITING, 'Waiting')
        else:
            item.message = 'Looking up the mod'
            self.item_changed.emit(item)
        self._find_requirements(item)

    def _on_check_failed(self, item: DownloadItem, error: Exception) -> None:
        if self._dropped(item):
            return
        if item.state == RESOLVING:  # without its listing or page there's nothing to download
            item.manual_url = getattr(error, 'page_url', None)
            self._set(item, FAILED, error_text(error), progress=-1)
        else:
            item.check_error = error_text(error)
            self.item_changed.emit(item)

    def _on_check_done(self, item: DownloadItem, task: Task) -> None:
        if task in item.checks:
            item.checks.remove(task)
        self._checks_running -= 1
        if item in self.items:
            self.item_changed.emit(item)
        self._pump()

    # --- downloading -------------------------------------------------------

    def _set(self, item: DownloadItem, state: str, message: str, progress: Optional[int] = None) -> None:
        item.state = state
        item.message = message
        if progress is not None:
            item.progress = progress
        if state == DONE:
            self._summary.installed.append(item.mod.name)
        elif state == FAILED:
            self._summary.failed.append(item.mod.name)
        elif state == CANCELLED:
            self._summary.cancelled.append(item.mod.name)
        self.item_changed.emit(item)

    def _pump(self) -> None:
        """Start the next download, or announce that the queue is done."""
        if any(item.state == ACTIVE for item in self.items):
            return
        waiting = next((item for item in self.items if item.state == WAITING), None)
        if waiting is not None:
            self._start_download(waiting)
        elif self._busy and not self._checks_running and not any(i.state == RESOLVING for i in self.items):
            summary, self._summary = self._summary, QueueSummary()
            self._busy = False
            self.finished.emit(summary)

    def _start_download(self, item: DownloadItem) -> None:
        item._cancel_requested = False
        self._set(item, ACTIVE, 'Starting', progress=-1)
        mod = item.mod
        item.task = run_task(lambda ctx: self._install(mod, ctx.progress, ctx.cancel),
                             on_progress=partial(self._on_progress, item),
                             on_result=partial(self._on_installed, item),
                             on_error=partial(self._on_failed, item),
                             on_cancelled=partial(self._on_cancelled, item),
                             on_finished=self._pump)

    def _on_progress(self, item: DownloadItem, progress: Progress) -> None:
        if item.state != ACTIVE:
            return
        item.progress = progress.percent
        if not item._cancel_requested:
            if progress.stage == 'downloading':
                item.message = f'Downloading · {progress.detail}' if progress.detail else 'Downloading'
            elif progress.stage == 'installing':
                item.message = 'Installing'
            else:
                item.message = progress.detail or 'Preparing download'
        self.item_changed.emit(item)

    def _on_installed(self, item: DownloadItem, path: Path) -> None:
        item.installed_path = path
        self._set(item, DONE, 'Installed', progress=100)
        self.mod_installed.emit(item)

    def _on_failed(self, item: DownloadItem, error: Exception) -> None:
        if item.state == CANCELLED:
            return
        item.manual_url = getattr(error, 'page_url', None)
        self._set(item, FAILED, error_text(error), progress=-1)

    def _on_cancelled(self, item: DownloadItem) -> None:
        self._set(item, CANCELLED, 'Cancelled', progress=-1)
