"""The Settings page: the game folder and the Owner ID to apply."""

from __future__ import annotations

from PyQt5.QtCore import QRegularExpression, Qt
from PyQt5.QtGui import QRegularExpressionValidator
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLineEdit, QScrollArea, QVBoxLayout, QWidget

from .. import __version__
from ..app_state import AppState
from .library_page import pick_game_folder
from .widgets import PageHeader, ToastHost, make_button, make_label, repolish

REPO_URL = 'https://github.com/slicendiceem/WRSR-mod-installer'


def card(title: str, description: str) -> tuple:
    frame = QFrame()
    frame.setProperty('card', True)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(22, 20, 22, 20)
    layout.setSpacing(10)
    layout.addWidget(make_label(title, 'subheading'))
    if description:
        layout.addWidget(make_label(description, 'muted', wrap=True))
    return frame, layout


class SettingsPage(QWidget):
    def __init__(self, state: AppState, toasts: ToastHost):
        super().__init__()
        self.state = state
        self.toasts = toasts

        content = QWidget()
        root = QVBoxLayout(content)
        root.setContentsMargins(32, 28, 32, 24)
        root.setSpacing(16)
        root.addWidget(PageHeader('Settings', 'Where the game is installed, and which Owner ID to write '
                                              'into your mods.'))

        folder_card, layout = card('Game folder', 'The folder where Workers & Resources: Soviet Republic is '
                                                  'installed. It contains the media_soviet folder.')
        row = QHBoxLayout()
        self.folder_input = QLineEdit()
        self.folder_input.setReadOnly(True)
        self.folder_input.setPlaceholderText('Not chosen yet')
        row.addWidget(self.folder_input, 1)
        row.addWidget(make_button('Browse…', 'folder', on_click=lambda: pick_game_folder(self, state)))
        layout.addLayout(row)
        self.folder_status = make_label(wrap=True)
        layout.addWidget(self.folder_status)
        root.addWidget(folder_card)

        owner_card, layout = card('Owner ID', 'Written into each mod’s workshopconfig.ini as $OWNER_ID. '
                                              'This is normally your 17-digit Steam ID.')
        row = QHBoxLayout()
        self.owner_input = QLineEdit()
        self.owner_input.setPlaceholderText('e.g. 76561198012345678')
        self.owner_input.setValidator(QRegularExpressionValidator(QRegularExpression('[0-9]{0,20}')))
        self.owner_input.setFixedWidth(280)
        self.owner_input.returnPressed.connect(self.save_owner_id)
        self.owner_input.textEdited.connect(lambda text: self.owner_error.hide())
        self.save_owner_button = make_button('Save', variant='primary', on_click=self.save_owner_id)
        row.addWidget(self.owner_input)
        row.addWidget(self.save_owner_button)
        row.addStretch(1)
        layout.addLayout(row)
        self.owner_error = make_label(role='error', wrap=True)
        self.owner_error.hide()
        layout.addWidget(self.owner_error)
        root.addWidget(owner_card)

        about_card, layout = card(f'About  ·  version {__version__}', '')
        about = make_label(
            'Mods are found on the <a href="https://catalogue.smods.ru/?app=784150">Skymods catalogue</a> '
            'and downloaded from modsbase.com. Like any visitor, the app waits out modsbase’s short countdown '
            'before each download. If a download page doesn’t behave as usual, you’ll get a button to open '
            'it in your browser instead.<br><br>'
            f'Source code and issues: <a href="{REPO_URL}">{REPO_URL}</a>', 'muted', wrap=True)
        about.setTextFormat(Qt.RichText)
        about.setOpenExternalLinks(True)
        layout.addWidget(about)
        root.addWidget(about_card)
        root.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        state.settings_changed.connect(self.refresh)
        state.mods_changed.connect(self.refresh)
        state.scan_failed.connect(self._scan_failed)
        self.refresh()

    def _scan_failed(self, message: str) -> None:
        self.refresh()

    def refresh(self) -> None:
        state = self.state
        self.folder_input.setText(state.game_folder or '')
        if not self.owner_input.hasFocus():
            self.owner_input.setText(state.owner_id or '')
        if not state.game_folder:
            text, role = 'Choose a folder to see and install mods.', 'muted'
        elif state.scan_error:
            text, role = state.scan_error, 'error'
        elif state.scanning:
            text, role = 'Looking for mods…', 'muted'
        else:
            count = len(state.mods)
            text, role = f'✓  Found the workshop folder with {count} mod{"s" if count != 1 else ""}.', 'success'
        self.folder_status.setText(text)
        self.folder_status.setProperty('role', role)
        repolish(self.folder_status)

    def save_owner_id(self) -> None:
        try:
            self.state.set_owner_id(self.owner_input.text())
        except ValueError as e:
            self.owner_error.setText(str(e))
            self.owner_error.show()
            return
        self.owner_error.hide()
        self.toasts.show('Owner ID saved.', 'success')
