"""The Browse page: searching Skymods and adding mods to the download queue."""

from __future__ import annotations

import html
import time
from functools import partial
from typing import Callable, Dict, List, Optional, Set, Tuple

from PyQt5.QtCore import QAbstractListModel, QModelIndex, QRect, QRectF, QSize, Qt, QTimer, QUrl
from PyQt5.QtGui import QColor, QDesktopServices, QFont, QFontMetrics, QPainter
from PyQt5.QtWidgets import (QAbstractItemView, QHBoxLayout, QLineEdit, QListView, QScrollArea,
                             QSplitter, QStackedWidget, QStyle, QStyledItemDelegate, QVBoxLayout,
                             QWidget)

from .. import skymods
from ..app_state import AppState
from ..download_queue import DownloadQueue
from ..skymods import CatalogueMod, SearchPage
from ..tasks import Task, run_task
from . import theme
from .text import ago
from .widgets import (BusyBar, CoverImage, EmptyState, PageHeader, Pill, ToastHost, make_button,
                      make_label)

MOD_ROLE = Qt.UserRole + 1
SLOW_AFTER_SECONDS = 4


class ResultsModel(QAbstractListModel):
    def __init__(self):
        super().__init__()
        self._mods: List[CatalogueMod] = []

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._mods)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid():
            return None
        mod = self._mods[index.row()]
        if role in (Qt.DisplayRole, Qt.ToolTipRole):
            return mod.name
        if role == MOD_ROLE:
            return mod
        return None

    def mod_at(self, row: int) -> CatalogueMod:
        return self._mods[row]

    def clear(self) -> None:
        self.set_mods([])

    def set_mods(self, mods: List[CatalogueMod]) -> None:
        unique = {}
        for mod in mods:
            unique.setdefault(mod.key, mod)  # a mod can appear on two pages if the site changed
        self.beginResetModel()
        self._mods = list(unique.values())
        self.endResetModel()

    def refresh(self) -> None:
        if self._mods:
            self.dataChanged.emit(self.index(0), self.index(len(self._mods) - 1))


class ResultDelegate(QStyledItemDelegate):
    """Draws a search result as a two-line row with status badges."""

    def __init__(self, badges: Callable[[CatalogueMod], List[Tuple[str, str]]], parent=None):
        super().__init__(parent)
        self._badges = badges

    def sizeHint(self, option, index) -> QSize:
        return QSize(200, 64)

    def paint(self, painter: QPainter, option, index) -> None:
        mod: CatalogueMod = index.data(MOD_ROLE)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        rect = option.rect.adjusted(6, 3, -6, -3)
        if option.state & QStyle.State_Selected:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(200, 55, 43, 46))
            painter.drawRoundedRect(QRectF(rect), 8, 8)
        elif option.state & QStyle.State_MouseOver:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(theme.SURFACE_2))
            painter.drawRoundedRect(QRectF(rect), 8, 8)

        badge_font = QFont(option.font)
        badge_font.setPixelSize(11)
        badge_font.setWeight(QFont.DemiBold)
        metrics = QFontMetrics(badge_font)
        right = rect.right() - 12
        painter.setFont(badge_font)
        for text, kind in reversed(self._badges(mod)):
            width = metrics.horizontalAdvance(text) + 18
            badge = QRectF(right - width, rect.center().y() - 10, width, 20)
            fill, color = theme.PILL_COLORS[kind]
            painter.setPen(Qt.NoPen)
            painter.setBrush(fill)
            painter.drawRoundedRect(badge, 10, 10)
            painter.setPen(color)
            painter.drawText(badge, Qt.AlignCenter, text)
            right -= int(width) + 6

        text_width = right - rect.left() - 26
        name_font = QFont(option.font)
        name_font.setWeight(QFont.DemiBold)
        painter.setFont(name_font)
        painter.setPen(QColor(theme.TEXT))
        name = QFontMetrics(name_font).elidedText(mod.name, Qt.ElideRight, text_width)
        painter.drawText(QRect(rect.left() + 14, rect.top() + 11, text_width, 20),
                         Qt.AlignLeft | Qt.AlignVCenter, name)

        details = [', '.join(mod.categories), mod.file_size, f'by {mod.author}' if mod.author else '']
        meta_font = QFont(option.font)
        meta_font.setPixelSize(12)
        painter.setFont(meta_font)
        painter.setPen(QColor(theme.TEXT_MUTED))
        meta = QFontMetrics(meta_font).elidedText('  ·  '.join(d for d in details if d), Qt.ElideRight,
                                                  text_width)
        painter.drawText(QRect(rect.left() + 14, rect.top() + 32, text_width, 18),
                         Qt.AlignLeft | Qt.AlignVCenter, meta)
        painter.restore()


class CatalogueDetails(QScrollArea):
    """Everything known about the selected search result, with the actions for it."""

    def __init__(self, state: AppState, queue: DownloadQueue, on_add: Callable[[CatalogueMod], None]):
        super().__init__()
        self.state = state
        self.queue = queue
        self.mod: Optional[CatalogueMod] = None
        self._on_add = on_add
        self._loading = False
        self._error = ''
        self.setWidgetResizable(True)
        self.setMinimumWidth(340)

        self._stack = QStackedWidget()
        self._stack.addWidget(EmptyState('search', 'Pick a mod', 'Select a search result to see its '
                                                                'description and what it needs.'))
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(4, 0, 8, 8)
        layout.setSpacing(12)
        self.cover = CoverImage()
        layout.addWidget(self.cover)
        self.title = make_label(role='heading', wrap=True, selectable=True)
        layout.addWidget(self.title)
        self.meta = make_label(role='muted', wrap=True)
        layout.addWidget(self.meta)
        pills = QHBoxLayout()
        pills.setSpacing(6)
        self._pills = [Pill(), Pill(), Pill()]
        for pill in self._pills:
            pills.addWidget(pill)
        pills.addStretch(1)
        layout.addLayout(pills)

        buttons = QHBoxLayout()
        self.add_button = make_button('Add to downloads', 'download', variant='primary',
                                      on_click=lambda: self.mod and self._on_add(self.mod))
        self.open_button = make_button('Open on Skymods', 'external', variant='ghost',
                                       on_click=lambda: self.mod and QDesktopServices.openUrl(QUrl(self.mod.url)))
        buttons.addWidget(self.add_button)
        buttons.addWidget(self.open_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self.requirements_title = make_label('REQUIRED MODS', 'section')
        self.requirements = make_label(wrap=True)
        self.requirements.setTextFormat(Qt.RichText)
        layout.addWidget(self.requirements_title)
        layout.addWidget(self.requirements)

        layout.addWidget(make_label('DESCRIPTION', 'section'))
        self.details_busy = BusyBar()
        layout.addWidget(self.details_busy)
        self.description = make_label(wrap=True)
        self.description.setTextFormat(Qt.RichText)
        self.description.setOpenExternalLinks(True)
        self.description.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self.description.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        layout.addWidget(self.description)
        layout.addStretch(1)
        self._stack.addWidget(content)
        self.setWidget(self._stack)

    def show_mod(self, mod: Optional[CatalogueMod], loading: bool = False, error: str = '') -> None:
        self.mod = mod
        self._loading = loading
        self._error = error
        if mod is None:
            self._stack.setCurrentIndex(0)
            return
        self._stack.setCurrentIndex(1)
        self.cover.set_url(mod.image_url)
        self.refresh()

    def refresh(self) -> None:
        mod = self.mod
        if mod is None:
            return
        self.title.setText(mod.name)
        facts = [', '.join(mod.categories), mod.file_size, f'by {mod.author}' if mod.author else '',
                 f'updated {mod.updated}' if mod.updated else '']
        self.meta.setText('  ·  '.join(f for f in facts if f))

        installed = self.state.is_installed(mod)
        queued = self.queue.is_queued(mod.key)
        pills = []
        if installed:
            pills.append(('Installed', 'success'))
        if queued:
            pills.append(('In downloads', 'info'))
        if mod.has_requirements:
            pills.append(('Needs other mods', 'warning'))
        for pill, value in zip(self._pills, pills + [None] * len(self._pills)):
            pill.setVisible(value is not None)
            if value is not None:
                pill.set(*value)

        no_download = mod.details_loaded and not mod.download_url
        self.add_button.setEnabled(not queued and not no_download)
        self.add_button.setText('In downloads' if queued else 'No download available' if no_download
                                else 'Reinstall' if installed else 'Add to downloads')

        self.details_busy.setVisible(self._loading)
        if self._error:
            self.description.setText(f'<span style="color:{theme.DANGER}">{html.escape(self._error)}</span>')
        elif mod.details_loaded:
            self.description.setText(mod.description_html or
                                     f'<span style="color:{theme.TEXT_FAINT}">No description.</span>')
        else:
            self.description.setText(f'<span style="color:{theme.TEXT_FAINT}">Loading the description from '
                                     'Skymods… This can take a while when the site is busy.</span>')
        self._show_requirements(mod)

    def _show_requirements(self, mod: CatalogueMod) -> None:
        shown = bool(mod.prerequisites) or (mod.has_requirements and not mod.details_loaded)
        self.requirements_title.setVisible(shown)
        self.requirements.setVisible(shown)
        if not mod.prerequisites:
            self.requirements.setText(f'<span style="color:{theme.TEXT_FAINT}">Checking…</span>')
            return
        lines = []
        for prereq in mod.prerequisites:
            if self.state.index.contains(prereq.name, prereq.steam_id):
                status, color = 'installed', theme.SUCCESS
            elif prereq.steam_id and self.queue.is_queued(prereq.steam_id):
                status, color = 'in downloads', theme.INFO
            else:
                status, color = 'downloaded with it', theme.TEXT_FAINT
            lines.append(f'• {html.escape(prereq.name)} <span style="color:{color}">— {status}</span>')
        self.requirements.setText('<br>'.join(lines))


class BrowsePage(QWidget):
    def __init__(self, state: AppState, queue: DownloadQueue, toasts: ToastHost, catalogue,
                 show_page: Callable[[str], None]):
        super().__init__()
        self.state = state
        self.queue = queue
        self.toasts = toasts
        self.catalogue = catalogue
        self.show_page = show_page
        self._search_id = 0
        self._term = ''
        self._page = 0
        self._pages: Dict[int, List[CatalogueMod]] = {}  # results by page number
        self._has_next = False
        self._saved_age: Optional[float] = None  # set while saved (not fresh) results are shown
        self._task: Optional[Task] = None
        self._started = 0.0
        self._loading_details: Set[str] = set()

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 24)
        root.setSpacing(14)
        root.addWidget(PageHeader('Browse Skymods', 'Search the Skymods catalogue for Workers & '
                                                     'Resources mods. Required mods are added for you.'))

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.search_input = QLineEdit()
        self.search_input.setProperty('sizing', 'large')
        self.search_input.setPlaceholderText('Search mods, e.g. “tram depot”, or paste a Steam ID')
        self.search_input.setClearButtonEnabled(True)
        self.search_input.returnPressed.connect(self.search)
        self.search_button = make_button('Search', 'search', variant='primary', on_click=self.search)
        self.search_button.setMinimumHeight(40)
        self.stop_button = make_button('Stop', 'stop', on_click=self.stop)
        self.stop_button.setMinimumHeight(40)
        self.stop_button.hide()
        bar.addWidget(self.search_input, 1)
        bar.addWidget(self.search_button)
        bar.addWidget(self.stop_button)
        root.addLayout(bar)

        self.status_label = make_label(role='muted', wrap=True)
        root.addWidget(self.status_label)
        self.busy = BusyBar()
        root.addWidget(self.busy)

        self.model = ResultsModel()
        self.results = QListView()
        self.results.setModel(self.model)
        self.results.setItemDelegate(ResultDelegate(self._badges, self.results))
        self.results.setUniformItemSizes(True)
        self.results.setMouseTracking(True)
        self.results.setSelectionMode(QAbstractItemView.SingleSelection)
        self.results.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.results.activated.connect(lambda index: self.add_to_downloads(self.model.mod_at(index.row())))
        self.results.selectionModel().currentChanged.connect(self._current_changed)
        self.load_more_button = make_button('Load more results', on_click=self.load_more)
        self.load_more_button.hide()

        list_column = QWidget()
        list_layout = QVBoxLayout(list_column)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(8)
        list_layout.addWidget(self.results, 1)
        list_layout.addWidget(self.load_more_button, 0, Qt.AlignHCenter)

        self.details = CatalogueDetails(state, queue, self.add_to_downloads)
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(list_column)
        splitter.addWidget(self.details)
        splitter.setHandleWidth(20)
        splitter.setChildrenCollapsible(False)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([640, 420])

        self.empty = EmptyState('search', 'Find mods on Skymods',
                                'Type a name above and press Enter. Double-click a result to add it to your '
                                'downloads.')
        self.stack = QStackedWidget()
        self.stack.addWidget(self.empty)
        self.stack.addWidget(splitter)
        root.addWidget(self.stack, 1)

        self._clock = QTimer(self)
        self._clock.setInterval(1000)
        self._clock.timeout.connect(self._update_waiting_text)

        # Bound methods (not lambdas), so Qt drops these connections if the page goes away.
        state.mods_changed.connect(self._statuses_changed)
        queue.item_added.connect(self._queue_changed)
        queue.item_removed.connect(self._queue_changed)
        queue.item_changed.connect(self._queue_item_changed)

    # --- searching -----------------------------------------------------------

    def search(self) -> None:
        term = self.search_input.text().strip()
        if not term:
            return
        self._abandon_search()
        self._search_id += 1
        self._term = term
        self._page = 0
        self._pages = {}
        self._has_next = False
        self._saved_age = None
        self.model.clear()
        self.details.show_mod(None)
        self.stack.setCurrentIndex(1)
        self._fetch_page(1)

    def load_more(self) -> None:
        self._fetch_page(self._page + 1)

    def stop(self) -> None:
        self._abandon_search()
        self._search_id += 1
        self._end_loading()
        count = self.model.rowCount()
        if self._saved_age is not None:
            self.status_label.setText(f'Stopped. Showing results saved {ago(self._saved_age)}.')
        else:
            self.status_label.setText(f'Stopped. Showing {count} result{"s" if count != 1 else ""}.'
                                      if count else 'Search stopped.')

    def _abandon_search(self) -> None:
        # The request can't be interrupted mid-way, but its results will be ignored.
        if self._task is not None:
            self._task.cancel()
            self._task = None

    def _fetch_page(self, page: int) -> None:
        search_id, term = self._search_id, self._term
        saved = self.catalogue.saved_search(term, page)
        if saved is not None:
            # Show what was found last time straight away; Skymods can take a minute.
            result, age = saved
            self._saved_age = age
            self._show_page(page, result)
            if age <= skymods.SEARCH_FRESH:
                self._describe_results()
                return
        self._started = time.monotonic()
        self._clock.start()
        self.busy.show()
        self.stop_button.show()
        self.load_more_button.setEnabled(False)
        if saved is not None:
            self.status_label.setText(f'Showing results saved {ago(saved[1])}. Checking Skymods for changes…')
        else:
            self.status_label.setText(f'Searching Skymods for “{term}”…' if page == 1
                                      else 'Loading more results…')
        self._task = run_task(lambda ctx: self.catalogue.search(term, page),
                              on_result=partial(self._page_loaded, search_id, page),
                              on_error=partial(self._search_failed, search_id))

    def _page_loaded(self, search_id: int, page: int, result: SearchPage) -> None:
        if search_id != self._search_id:
            return  # a newer search replaced this one
        self._end_loading()
        self._saved_age = None
        self._show_page(page, result)
        self._describe_results()

    def _show_page(self, page: int, result: SearchPage) -> None:
        """Put one page of results on screen, replacing an earlier copy of that page."""
        earlier = {mod.key: mod for mod in self._pages.get(page, [])}
        for mod in result.mods:
            if mod.key in earlier:
                mod.fill_from(earlier[mod.key])  # keep details already loaded for it
        self._pages[page] = list(result.mods)
        self._page = max(self._page, page)
        if page == max(self._pages):
            self._has_next = result.has_next
        selected = self._selected_key()
        self.model.set_mods([mod for number in sorted(self._pages) for mod in self._pages[number]])
        if selected is not None:
            self._select(selected)
        self.load_more_button.setVisible(self._has_next)
        self.load_more_button.setEnabled(True)

    def _describe_results(self) -> None:
        count = self.model.rowCount()
        if not count:
            text = f'No mods found for “{self._term}”. Try fewer or different words.'
        else:
            text = f'{count} result{"s" if count != 1 else ""} for “{self._term}”.'
            if self._has_next:
                text += ' More are available.'
            if self._saved_age is not None:
                text += f' Saved {ago(self._saved_age)}.'
        self.status_label.setText(text)

    def _selected_key(self) -> Optional[str]:
        index = self.results.currentIndex()
        return self.model.mod_at(index.row()).key if index.isValid() else None

    def _select(self, key: str) -> None:
        for row in range(self.model.rowCount()):
            if self.model.mod_at(row).key == key:
                self.results.setCurrentIndex(self.model.index(row))
                return

    def _search_failed(self, search_id: int, error: Exception) -> None:
        if search_id != self._search_id:
            return
        self._end_loading()
        message = html.escape(str(error))
        if self._saved_age is not None:
            self.status_label.setText(f'<span style="color:{theme.WARNING}">Showing results saved '
                                      f'{ago(self._saved_age)}, because Skymods didn’t answer: {message}</span>')
        else:
            self.status_label.setText(f'<span style="color:{theme.DANGER}">{message}</span>')
        self.load_more_button.setEnabled(True)

    def _end_loading(self) -> None:
        self._task = None
        self._clock.stop()
        self.busy.hide()
        self.stop_button.hide()

    def _update_waiting_text(self) -> None:
        elapsed = int(time.monotonic() - self._started)
        if elapsed >= SLOW_AFTER_SECONDS:
            self.status_label.setText(f'Still waiting for Skymods… {elapsed} s. Pages the site hasn’t '
                                      'served recently can take about a minute.')

    # --- details and adding --------------------------------------------------

    def _current_changed(self, current: QModelIndex, previous: QModelIndex) -> None:
        if not current.isValid():
            self.details.show_mod(None)
            return
        mod = self.model.mod_at(current.row())
        loading = not mod.details_loaded
        if loading:
            saved = self.catalogue.saved_mod(mod.url)
            if saved is not None:  # show the saved page now, and refresh it only if it's old
                details, age = saved
                mod.fill_from(details)
                loading = age > skymods.DETAILS_FRESH
        self.details.show_mod(mod, loading=loading)
        if loading and mod.key not in self._loading_details:
            self._loading_details.add(mod.key)
            run_task(lambda ctx: self.catalogue.fetch_mod(mod.url),
                     on_result=partial(self._details_loaded, mod),
                     on_error=partial(self._details_failed, mod),
                     on_finished=lambda: self._loading_details.discard(mod.key))

    def _details_loaded(self, mod: CatalogueMod, details: CatalogueMod) -> None:
        mod.merge_details(details)
        self.model.refresh()
        if self.details.mod is mod:
            self.details.show_mod(mod)

    def _details_failed(self, mod: CatalogueMod, error: Exception) -> None:
        if self.details.mod is mod:
            self.details.show_mod(mod, error=f'Couldn’t load the details: {error}')

    def add_to_downloads(self, mod: CatalogueMod) -> None:
        if not self.state.game_folder:
            self.toasts.show('Choose your game folder first, so downloads have somewhere to go.', 'warning',
                             'Open Settings', lambda: self.show_page('settings'))
            return
        view = lambda: self.show_page('downloads')
        if self.queue.add(mod) is None:
            self.toasts.show(f'“{mod.name}” is already in your downloads.', 'info', 'View', view)
        else:
            self.toasts.show(f'Added “{mod.name}” to downloads.', 'success', 'View', view)

    def _badges(self, mod: CatalogueMod) -> List[Tuple[str, str]]:
        badges = []
        if self.state.is_installed(mod):
            badges.append(('Installed', 'success'))
        if self.queue.is_queued(mod.key):
            badges.append(('In downloads', 'info'))
        if mod.has_requirements:
            badges.append(('Needs other mods', 'warning'))
        return badges

    def _statuses_changed(self) -> None:
        self.results.viewport().update()
        self.details.refresh()

    def _queue_changed(self, item) -> None:
        self._statuses_changed()

    def _queue_item_changed(self, item) -> None:
        if item.finished:  # progress updates don't change any badge
            self._statuses_changed()
