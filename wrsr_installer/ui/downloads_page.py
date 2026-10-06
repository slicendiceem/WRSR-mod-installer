"""The Downloads page: the queue, with live progress for every mod."""

from __future__ import annotations

import html
from typing import Callable, Dict

from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (QFrame, QHBoxLayout, QLabel, QProgressBar, QScrollArea,
                             QStackedWidget, QVBoxLayout, QWidget)

from ..download_queue import (ACTIVE, CANCELLED, DONE, FAILED, RESOLVING, WAITING, DownloadItem,
                              DownloadQueue)
from . import icons, theme
from .widgets import EmptyState, PageHeader, ToastHost, make_button, make_label

_STATE_ICONS = {
    RESOLVING: ('clock', theme.TEXT_FAINT), WAITING: ('clock', theme.TEXT_FAINT),
    ACTIVE: ('download', theme.ACCENT), DONE: ('check-circle', theme.SUCCESS),
    FAILED: ('error', theme.DANGER), CANCELLED: ('close', theme.TEXT_FAINT),
}


class DownloadRow(QFrame):
    def __init__(self, item: DownloadItem, queue: DownloadQueue):
        super().__init__()
        self.item = item
        self.queue = queue
        self.setObjectName('DownloadRow')
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 14, 12, 14)
        layout.setSpacing(14)
        self._icon = QLabel()
        self._icon.setFixedSize(20, 20)
        layout.addWidget(self._icon, 0, Qt.AlignTop)

        text = QVBoxLayout()
        text.setSpacing(4)
        self._name = make_label(role='subheading')
        self._name.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._origin = make_label(role='faint', wrap=True)
        self._status = make_label(role='muted', wrap=True)
        for label in (self._name, self._origin, self._status):
            label.setTextFormat(Qt.PlainText)  # mod names come from Skymods; never read them as HTML
        self._progress = QProgressBar()
        self._progress.setTextVisible(False)
        self._missing = make_label(role='warning', wrap=True)
        self._missing.setTextFormat(Qt.RichText)
        for widget in (self._name, self._origin, self._status, self._progress, self._missing):
            text.addWidget(widget)
        layout.addLayout(text, 1)

        self._buttons = QHBoxLayout()
        self._buttons.setSpacing(6)
        self._cancel = make_button('Cancel', size='small', on_click=lambda: queue.cancel(item))
        self._open_page = make_button('Open download page', 'external', variant='primary', size='small',
                                      on_click=lambda: QDesktopServices.openUrl(QUrl(item.manual_url)))
        self._retry = make_button('Retry', 'refresh', size='small', on_click=lambda: queue.retry(item))
        self._open_folder = make_button('Open folder', 'folder', size='small',
                                        on_click=lambda: QDesktopServices.openUrl(
                                            QUrl.fromLocalFile(str(item.installed_path))))
        self._remove = make_button(icon='close', variant='ghost', size='small', tooltip='Remove from list',
                                   on_click=lambda: queue.remove(item))
        for button in (self._cancel, self._open_page, self._retry, self._open_folder, self._remove):
            self._buttons.addWidget(button, 0, Qt.AlignTop)
        layout.addLayout(self._buttons)
        self.update_view()

    def update_view(self) -> None:
        item = self.item
        name, color = _STATE_ICONS[item.state]
        self._icon.setPixmap(icons.pixmap(name, color, 20))
        self._name.setText(item.mod.name)
        installed = ', '.join(f'“{name}”' for name in item.installed_requirements)
        origin = [f'Required by “{item.required_by}”' if item.required_by else '', item.mod.file_size,
                  f'Also needs {installed} (already installed)' if installed else '',
                  'Checking which other mods it needs…' if item.checking and not item.placeholder else '']
        self._origin.setText('  ·  '.join(o for o in origin if o))
        self._origin.setVisible(any(origin))
        status = item.message or item.state.capitalize()
        self._status.setText(status)
        self._status.setProperty('role', 'error' if item.state == FAILED else 'muted')
        self._status.style().unpolish(self._status)
        self._status.style().polish(self._status)

        busy = item.state in (RESOLVING, ACTIVE)
        self._progress.setVisible(busy)
        if busy:
            if item.progress < 0 or item.state == RESOLVING:
                self._progress.setRange(0, 0)
            else:
                self._progress.setRange(0, 100)
                self._progress.setValue(item.progress)

        warnings = []
        if item.missing:
            names = ', '.join(f'“{html.escape(p.name)}”' for p in item.missing)
            warnings.append(f'Also needs {names}, but Skymods doesn’t say which mod that is. Look for it on '
                            'the Steam Workshop.')
        if item.check_error:
            warnings.append(f'Couldn’t check which other mods it needs: {html.escape(item.check_error)}')
        self._missing.setText('<br>'.join(warnings))
        self._missing.setVisible(bool(warnings))

        unfinished = not item.finished
        self._cancel.setVisible(unfinished)
        self._open_page.setVisible(item.state == FAILED and bool(item.manual_url))
        self._retry.setVisible(item.state in (FAILED, CANCELLED))
        self._open_folder.setVisible(item.state == DONE and item.installed_path is not None
                                     and item.installed_path.exists())
        self._remove.setVisible(item.finished)


class DownloadsPage(QWidget):
    def __init__(self, queue: DownloadQueue, toasts: ToastHost, show_page: Callable[[str], None]):
        super().__init__()
        self.queue = queue
        self._rows: Dict[int, DownloadRow] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 24)
        root.setSpacing(14)
        header = PageHeader('Downloads', 'Mods download one at a time. The other mods they need are '
                                         'found and added automatically.')
        self.clear_button = header.add_action(make_button('Clear finished', 'trash', variant='ghost',
                                                          on_click=queue.clear_finished))
        self.cancel_all_button = header.add_action(make_button('Cancel all', 'stop', on_click=queue.cancel_all))
        root.addWidget(header)

        self._list = QWidget()
        self._list_layout = QVBoxLayout(self._list)
        self._list_layout.setContentsMargins(0, 0, 8, 0)
        self._list_layout.setSpacing(8)
        self._list_layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._list)

        self.empty = EmptyState('download', 'No downloads yet',
                                'Find mods on the Browse page and add them here.',
                                'Browse Skymods', lambda: show_page('browse'))
        self.stack = QStackedWidget()
        self.stack.addWidget(self.empty)
        self.stack.addWidget(scroll)
        root.addWidget(self.stack, 1)

        queue.item_added.connect(self._added)
        queue.item_changed.connect(self._changed)
        queue.item_removed.connect(self._removed)
        self._update_actions()

    def row_count(self) -> int:
        return len(self._rows)

    def _added(self, item: DownloadItem) -> None:
        row = DownloadRow(item, self.queue)
        self._rows[id(item)] = row
        self._list_layout.insertWidget(self.queue.items.index(item), row)
        self._update_actions()

    def _changed(self, item: DownloadItem) -> None:
        row = self._rows.get(id(item))
        if row is not None:
            row.update_view()
        self._update_actions()

    def _removed(self, item: DownloadItem) -> None:
        row = self._rows.pop(id(item), None)
        if row is not None:
            row.setParent(None)
            row.deleteLater()
        self._update_actions()

    def _update_actions(self) -> None:
        items = self.queue.items
        self.stack.setCurrentIndex(1 if items else 0)
        self.clear_button.setEnabled(any(i.finished for i in items))
        self.cancel_all_button.setEnabled(any(not i.finished for i in items))
