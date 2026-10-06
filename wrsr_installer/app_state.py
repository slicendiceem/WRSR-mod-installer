"""State the pages share: settings, the installed mods, and Owner ID changes."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Tuple

from PyQt5.QtCore import QObject, pyqtSignal

from .config import CONFIG_FILE, AppConfig, save_config
from .downloader import DownloadError
from .skymods import CatalogueMod
from .tasks import run_task
from .workshop import (InstalledIndex, ModInfo, apply_owner_id, game_folder_from, is_valid_owner_id,
                       scan_mods, workshop_dir)

log = logging.getLogger(__name__)


@dataclass
class OwnerIdResult:
    updated: List[str] = field(default_factory=list)
    failed: List[Tuple[str, str]] = field(default_factory=list)  # (mod name, reason)


def file_error_text(error: Exception) -> str:
    if isinstance(error, PermissionError):
        return "Access denied. Close the game, and check the file isn't read-only."
    if isinstance(error, OSError):
        return error.strerror or str(error)
    return str(error)


class AppState(QObject):
    settings_changed = pyqtSignal()
    mods_changed = pyqtSignal()
    scan_started = pyqtSignal()
    scan_failed = pyqtSignal(str)

    def __init__(self, config: AppConfig, config_path: Path = CONFIG_FILE,
                 parent: Optional[QObject] = None):
        super().__init__(parent)
        self._config = config
        self._config_path = config_path
        self.mods: List[ModInfo] = []
        self.index = InstalledIndex([])
        self.scanning = False
        self.scan_error: Optional[str] = None
        self._scan_id = 0

    # --- settings ----------------------------------------------------------

    @property
    def game_folder(self) -> Optional[str]:
        return self._config.game_folder

    @property
    def owner_id(self) -> Optional[str]:
        return self._config.target_owner_id

    @property
    def workshop(self) -> Optional[Path]:
        return workshop_dir(self.game_folder) if self.game_folder else None

    def require_workshop(self) -> Path:
        if self.workshop is None:
            raise DownloadError('Choose your game folder in Settings first.')
        return self.workshop

    def set_game_folder(self, folder: str) -> None:
        self._config.game_folder = game_folder_from(folder)
        self._save()
        self.settings_changed.emit()
        self.rescan()

    def set_owner_id(self, owner_id: str) -> None:
        owner_id = owner_id.strip()
        if not is_valid_owner_id(owner_id):
            raise ValueError('The Owner ID must be a number, like 76561198012345678.')
        self._config.target_owner_id = owner_id
        self._save()
        self.settings_changed.emit()
        self.mods_changed.emit()  # which mods count as fixed depends on it

    def _save(self) -> None:
        try:
            save_config(self._config, self._config_path)
        except OSError:
            log.exception('Could not save settings to %s', self._config_path)

    # --- installed mods ----------------------------------------------------

    def rescan(self) -> None:
        workshop = self.workshop
        if workshop is None:
            return
        self._scan_id += 1
        scan_id = self._scan_id
        self.scanning = True
        self.scan_started.emit()

        def done(mods: List[ModInfo]) -> None:
            if scan_id == self._scan_id:  # ignore scans overtaken by a newer one
                self.scanning = False
                self.scan_error = None
                self._set_mods(mods)

        def failed(error: Exception) -> None:
            if scan_id != self._scan_id:
                return
            self.scanning = False
            if isinstance(error, FileNotFoundError):
                self.scan_error = (f"There's no media_soviet\\workshop_wip folder in {self.game_folder}. "
                                   'Choose the folder where Workers & Resources is installed.')
            else:
                self.scan_error = f"Couldn't read the workshop folder: {file_error_text(error)}"
            self._set_mods([])
            self.scan_failed.emit(self.scan_error)

        run_task(lambda ctx: scan_mods(workshop), on_result=done, on_error=failed)

    def _set_mods(self, mods: List[ModInfo]) -> None:
        self.mods = mods
        self.index = InstalledIndex(mods)
        self.mods_changed.emit()

    def is_installed(self, mod: CatalogueMod) -> bool:
        return self.index.contains(mod.name, mod.steam_id)

    def is_fixed(self, mod: ModInfo) -> bool:
        return bool(self.owner_id) and mod.owner_id == self.owner_id

    def unfixed_mods(self) -> List[ModInfo]:
        return [m for m in self.mods if m.error is None and not self.is_fixed(m)]

    def apply_owner_id(self, mods: Iterable[ModInfo], on_done: Callable[[OwnerIdResult], None]) -> None:
        """Write the target Owner ID into each mod's config in the background."""
        owner_id = self.owner_id
        if not owner_id:
            raise ValueError('Set your Owner ID in Settings first.')
        targets = list(mods)

        def work(ctx):
            result, updated = OwnerIdResult(), {}
            for mod in targets:
                try:
                    updated[mod.path] = apply_owner_id(mod, owner_id)
                    result.updated.append(mod.display_name)
                except (OSError, ValueError) as e:
                    result.failed.append((mod.display_name, file_error_text(e)))
            return result, updated

        def done(value) -> None:
            result, updated = value
            self._set_mods([updated.get(m.path, m) for m in self.mods])
            on_done(result)

        run_task(work, on_result=done,
                 on_error=lambda e: on_done(OwnerIdResult(failed=[('Mods', file_error_text(e))])))
