"""The Library page: installed mods, their Owner ID status, and installing from ZIP files."""

from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import Callable, Dict, Optional

from PyQt5.QtCore import QRectF, Qt, QUrl
from PyQt5.QtGui import QColor, QDesktopServices, QFont, QFontMetrics, QPainter, QPixmap
from PyQt5.QtWidgets import (QAbstractItemView, QDialog, QFileDialog, QGridLayout, QHBoxLayout,
                             QHeaderView, QPushButton, QScrollArea, QSplitter, QStackedWidget,
                             QStyle, QStyledItemDelegate, QStyleOptionViewItem, QTableWidget,
                             QTableWidgetItem, QVBoxLayout, QWidget)

from ..app_state import AppState, OwnerIdResult, file_error_text
from ..archive import ExtractedMod, extract_mod
from ..tasks import run_task
from ..workshop import ModInfo, apply_owner_id, read_mod
from . import dialogs, theme
from .install_dialog import InstallPreviewDialog, pretty_type
from .text import format_bbcode
from .widgets import (Banner, BusyBar, CoverImage, EmptyState, PageHeader, Pill, ToastHost,
                      make_button, make_label)

COLUMNS = ('NAME', 'TYPE', 'FOLDER', 'OWNER ID', 'STATUS', '')
NAME, TYPE, FOLDER, OWNER, STATUS, ACTION = range(len(COLUMNS))
KIND_ROLE = Qt.UserRole + 1
PATH_ROLE = Qt.UserRole + 2


def mod_status(state: AppState, mod: ModInfo):
    """(text, pill kind) describing a mod's Owner ID status."""
    if mod.error:
        return 'Unreadable', 'danger'
    if not state.owner_id:
        return 'No target ID', 'neutral'
    if state.is_fixed(mod):
        return 'Fixed', 'success'
    return 'Needs Owner ID', 'warning'


def pick_game_folder(parent: QWidget, state: AppState) -> None:
    start = state.game_folder or ''
    if not start:
        steam = Path('C:/Program Files (x86)/Steam/steamapps/common/SovietRepublic')
        start = str(steam if steam.exists() else Path.home())
    folder = QFileDialog.getExistingDirectory(parent, 'Choose the Workers & Resources game folder', start)
    if folder:
        state.set_game_folder(folder)


class PillDelegate(QStyledItemDelegate):
    """Draws the status column as coloured pills."""

    def paint(self, painter: QPainter, option, index) -> None:
        background = QStyleOptionViewItem(option)
        self.initStyleOption(background, index)
        background.text = ''
        widget = option.widget
        widget.style().drawControl(QStyle.CE_ItemViewItem, background, painter, widget)

        text = index.data(Qt.DisplayRole) or ''
        fill, color = theme.PILL_COLORS[index.data(KIND_ROLE) or 'neutral']
        font = QFont(option.font)
        font.setPixelSize(11)
        font.setWeight(QFont.DemiBold)
        width = QFontMetrics(font).horizontalAdvance(text) + 18
        rect = QRectF(option.rect.left() + 12, option.rect.center().y() - 9, width, 20)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(fill)
        painter.drawRoundedRect(rect, 10, 10)
        painter.setPen(color)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignCenter, text)
        painter.restore()


class InstalledModPanel(QScrollArea):
    """Details of the selected mod, shown beside the table instead of in a pop-up."""

    def __init__(self, state: AppState, on_apply: Callable[[ModInfo], None]):
        super().__init__()
        self.state = state
        self.mod: Optional[ModInfo] = None
        self._on_apply = on_apply
        self.setWidgetResizable(True)
        self.setMinimumWidth(330)

        self._stack = QStackedWidget()
        self._stack.addWidget(EmptyState('library', 'Select a mod', 'Click a mod in the list to see its '
                                                                   'details and description.'))
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(4, 0, 8, 8)
        layout.setSpacing(12)
        self.cover = CoverImage()
        layout.addWidget(self.cover)
        self.title = make_label(role='heading', wrap=True, selectable=True)
        layout.addWidget(self.title)
        pills = QHBoxLayout()
        pills.setSpacing(6)
        self.type_pill = Pill()
        self.status_pill = Pill()
        pills.addWidget(self.type_pill)
        pills.addWidget(self.status_pill)
        pills.addStretch(1)
        layout.addLayout(pills)

        facts = QGridLayout()
        facts.setHorizontalSpacing(16)
        facts.setVerticalSpacing(6)
        self._facts = {}
        for row, (key, label) in enumerate((('folder', 'Folder'), ('item_id', 'Item ID'),
                                            ('owner_id', 'Owner ID'))):
            facts.addWidget(make_label(label, 'faint'), row, 0)
            value = make_label(selectable=True)
            facts.addWidget(value, row, 1)
            self._facts[key] = value
        facts.setColumnStretch(1, 1)
        layout.addLayout(facts)
        self.error = make_label(role='error', wrap=True)
        layout.addWidget(self.error)

        buttons = QHBoxLayout()
        self.apply_button = make_button('Apply Owner ID', 'key', variant='primary',
                                        on_click=lambda: self.mod and self._on_apply(self.mod))
        self.open_button = make_button('Open folder', 'folder', on_click=self._open_folder)
        buttons.addWidget(self.apply_button)
        buttons.addWidget(self.open_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        layout.addSpacing(4)
        layout.addWidget(make_label('DESCRIPTION', 'section'))
        self.description = make_label(wrap=True)
        self.description.setTextFormat(Qt.RichText)
        self.description.setOpenExternalLinks(True)
        self.description.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self.description.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        layout.addWidget(self.description)
        layout.addStretch(1)
        self._stack.addWidget(content)
        self.setWidget(self._stack)

    def show_mod(self, mod: Optional[ModInfo]) -> None:
        self.mod = mod
        if mod is None:
            self._stack.setCurrentIndex(0)
            return
        self._stack.setCurrentIndex(1)
        preview = mod.path / 'previewimage.png'
        self.cover.set_pixmap(QPixmap(str(preview)) if preview.exists() else None)
        self.title.setText(mod.display_name)
        self.type_pill.set(pretty_type(mod.item_type), 'neutral')
        status, kind = mod_status(self.state, mod)
        self.status_pill.set(status, kind)
        self._facts['folder'].setText(mod.folder)
        self._facts['item_id'].setText(mod.item_id or '—')
        self._facts['owner_id'].setText(mod.owner_id or 'Not set')
        self.error.setText(mod.error or '')
        self.error.setVisible(bool(mod.error))
        self.apply_button.setVisible(kind == 'warning')
        self.description.setText(format_bbcode(mod.item_desc) if mod.item_desc.strip()
                                 else '<span style="color:%s">No description.</span>' % theme.TEXT_FAINT)

    def _open_folder(self) -> None:
        if self.mod is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.mod.path)))


class LibraryPage(QWidget):
    def __init__(self, state: AppState, toasts: ToastHost, show_page: Callable[[str], None]):
        super().__init__()
        self.state = state
        self.toasts = toasts
        self.show_page = show_page
        self._apply_buttons: Dict[int, QPushButton] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 24)
        root.setSpacing(14)
        header = PageHeader('Library', 'Mods installed in your game’s workshop_wip folder.')
        self.refresh_button = header.add_action(make_button('Refresh', 'refresh', on_click=state.rescan))
        self.zip_button = header.add_action(make_button('Install ZIP…', 'archive', on_click=self.install_zip))
        self.apply_all_button = header.add_action(make_button('Apply Owner ID to all', 'key',
                                                              variant='primary', on_click=self.apply_to_all))
        root.addWidget(header)
        self.banner = Banner()
        root.addWidget(self.banner)
        self.stats = make_label(role='muted')
        root.addWidget(self.stats)
        self.busy = BusyBar()
        root.addWidget(self.busy)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(46)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setMouseTracking(True)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setFocusPolicy(Qt.NoFocus)
        self.table.setItemDelegateForColumn(STATUS, PillDelegate(self.table))
        header_view = self.table.horizontalHeader()
        header_view.setHighlightSections(False)
        header_view.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        header_view.setSectionResizeMode(NAME, QHeaderView.Stretch)
        for column in (TYPE, FOLDER, OWNER, STATUS):
            header_view.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        # Cell widgets don't count towards "resize to contents", so the button column is fixed.
        header_view.setSectionResizeMode(ACTION, QHeaderView.Fixed)
        self.table.setColumnWidth(ACTION, 92)
        self.table.itemSelectionChanged.connect(self._selection_changed)

        self.details = InstalledModPanel(state, self._apply_one)
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.table)
        splitter.addWidget(self.details)
        splitter.setHandleWidth(20)
        splitter.setChildrenCollapsible(False)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([700, 380])

        self.empty = EmptyState('library', 'No mods installed yet',
                                'Mods you download from Skymods or install from a ZIP file will show up here.',
                                'Browse Skymods', lambda: show_page('browse'))
        self.stack = QStackedWidget()
        self.stack.addWidget(splitter)
        self.stack.addWidget(self.empty)
        root.addWidget(self.stack, 1)

        state.mods_changed.connect(self.refresh)
        state.settings_changed.connect(self.refresh)
        state.scan_started.connect(self.refresh)
        state.scan_failed.connect(self._scan_failed)
        self.refresh()

    def _scan_failed(self, message: str) -> None:
        self.refresh()

    # --- helpers used by tests and the window --------------------------------

    def status_text(self, row: int) -> str:
        return self.table.item(row, STATUS).text()

    def apply_button(self, row: int) -> Optional[QPushButton]:
        return self._apply_buttons.get(row)

    # --- display -------------------------------------------------------------

    def refresh(self) -> None:
        state = self.state
        self.busy.setVisible(state.scanning)
        if not state.game_folder:
            self.banner.show_message('warning', 'Choose your Workers & Resources game folder to see your mods.',
                                     'Choose folder…', lambda: pick_game_folder(self, state))
        elif state.scan_error:
            self.banner.show_message('error', state.scan_error, 'Choose folder…',
                                     lambda: pick_game_folder(self, state))
        elif not state.owner_id:
            self.banner.show_message('info', 'Set your Owner ID in Settings so mods can be fixed.',
                                     'Open Settings', lambda: self.show_page('settings'))
        else:
            self.banner.hide()

        unfixed = state.unfixed_mods() if state.owner_id else []
        self.apply_all_button.setEnabled(bool(unfixed))
        self.apply_all_button.setText(f'Apply Owner ID to all ({len(unfixed)})' if unfixed
                                      else 'Apply Owner ID to all')
        self.zip_button.setEnabled(bool(state.game_folder) and not state.scan_error)
        self.refresh_button.setEnabled(bool(state.game_folder))
        self.stats.setText(self._stats_text(len(unfixed)))
        self._fill_table()
        no_mods = bool(state.game_folder) and not state.mods and not state.scanning and not state.scan_error
        self.stack.setCurrentIndex(1 if no_mods else 0)

    def _stats_text(self, unfixed: int) -> str:
        mods = self.state.mods
        if not mods:
            return ''
        text = f'{len(mods)} mod{"s" if len(mods) != 1 else ""}'
        if not self.state.owner_id:
            return text
        fixed = sum(1 for m in mods if self.state.is_fixed(m))
        return f'{text}   ·   {fixed} fixed   ·   {unfixed} need{"s" if unfixed == 1 else ""} Owner ID'

    def _fill_table(self) -> None:
        selected = self._selected_path()
        self.table.setRowCount(0)  # also deletes the old rows' Apply buttons
        self._apply_buttons.clear()
        mods = self.state.mods
        self.table.setRowCount(len(mods))
        bold = QFont(self.font())
        bold.setWeight(QFont.DemiBold)
        mono = QFont('Consolas')
        mono.setPointSizeF(self.font().pointSizeF() * 0.95)
        for row, mod in enumerate(mods):
            name = QTableWidgetItem(mod.display_name)
            name.setData(PATH_ROLE, str(mod.path))
            name.setFont(bold)
            name.setToolTip(mod.display_name)
            folder = QTableWidgetItem(mod.folder)
            folder.setForeground(QColor(theme.TEXT_FAINT))
            owner = QTableWidgetItem(mod.owner_id or '—')
            owner.setFont(mono)
            owner.setForeground(QColor(theme.TEXT_MUTED))
            text, kind = mod_status(self.state, mod)
            status = QTableWidgetItem(text)
            status.setData(KIND_ROLE, kind)
            for column, item in ((NAME, name), (TYPE, QTableWidgetItem(pretty_type(mod.item_type))),
                                 (FOLDER, folder), (OWNER, owner), (STATUS, status)):
                self.table.setItem(row, column, item)
            if kind == 'warning':
                self._add_apply_button(row, mod)
            if str(mod.path) == selected:
                self.table.selectRow(row)
        if selected is None or not any(str(m.path) == selected for m in mods):
            self.details.show_mod(None)

    def _add_apply_button(self, row: int, mod: ModInfo) -> None:
        button = make_button('Apply', size='small', tooltip=f'Write Owner ID {self.state.owner_id} into this mod',
                             on_click=partial(self._apply_one, mod))
        cell = QWidget()
        layout = QHBoxLayout(cell)
        layout.setContentsMargins(8, 0, 12, 0)
        layout.addWidget(button)
        self.table.setCellWidget(row, ACTION, cell)
        self._apply_buttons[row] = button

    def _selected_path(self) -> Optional[str]:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows:
            return None
        item = self.table.item(rows[0].row(), NAME)
        return item.data(PATH_ROLE) if item else None

    def _selection_changed(self) -> None:
        path = self._selected_path()
        mod = next((m for m in self.state.mods if str(m.path) == path), None)
        self.details.show_mod(mod)

    # --- actions -------------------------------------------------------------

    def _apply_one(self, mod: ModInfo) -> None:
        for button in self._apply_buttons.values():
            button.setEnabled(False)
        self.state.apply_owner_id([mod], self._report)

    def apply_to_all(self) -> None:
        mods = self.state.unfixed_mods()
        if not mods:
            return
        count = f'{len(mods)} mod{"s" if len(mods) != 1 else ""}'
        if not dialogs.confirm(self, 'Apply Owner ID',
                               f'Write Owner ID {self.state.owner_id} into {count}?\n\n'
                               'This edits the workshopconfig.ini file of each one.', 'Apply to all'):
            return
        self.apply_all_button.setEnabled(False)
        self.state.apply_owner_id(mods, self._report)

    def _report(self, result: OwnerIdResult) -> None:
        if not result.updated:
            self.refresh()  # nothing changed on disk, so no mods_changed re-enables the buttons
        if result.failed:
            name, reason = result.failed[0]
            more = f' (and {len(result.failed) - 1} more)' if len(result.failed) > 1 else ''
            prefix = f'Updated {len(result.updated)}, but ' if result.updated else ''
            self.toasts.show(f'{prefix}“{name}”{more} could not be updated: {reason}', 'error')
        elif len(result.updated) == 1:
            self.toasts.show(f'Owner ID applied to “{result.updated[0]}”.', 'success')
        elif result.updated:
            self.toasts.show(f'Owner ID applied to {len(result.updated)} mods.', 'success')

    def install_zip(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, 'Install a mod from a ZIP file',
                                              str(Path.home() / 'Downloads'),
                                              'ZIP archives (*.zip);;All files (*)')
        if not path:
            return
        self.busy.show()
        self.zip_button.setEnabled(False)
        run_task(lambda ctx: extract_mod(path, Path(path).stem),
                 on_result=self._confirm_install,
                 on_error=lambda e: self.toasts.show(f'Couldn’t open {Path(path).name}: {file_error_text(e)}',
                                                     'error'),
                 on_finished=self.refresh)

    def _confirm_install(self, extracted: ExtractedMod) -> None:
        dialog = InstallPreviewDialog(extracted, self.state, self)
        if dialog.exec_() != QDialog.Accepted:
            extracted.cleanup()
            return
        workshop, owner_id = self.state.workshop, self.state.owner_id
        apply = dialog.apply_owner_id

        def work(ctx):
            try:
                mod = read_mod(extracted.install(workshop, replace=True))
                if apply and owner_id and mod is not None:
                    mod = apply_owner_id(mod, owner_id)
                return mod
            finally:
                extracted.cleanup()

        def done(mod: Optional[ModInfo]) -> None:
            self.toasts.show(f'Installed “{mod.display_name if mod else extracted.folder_name}”.', 'success')
            self.state.rescan()

        run_task(work, on_result=done,
                 on_error=lambda e: self.toasts.show(f'Couldn’t install the mod: {file_error_text(e)}', 'error'))
