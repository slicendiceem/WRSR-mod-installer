"""The one confirmation step when installing a mod from a ZIP file."""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QCheckBox, QDialog, QHBoxLayout, QScrollArea, QVBoxLayout

from ..app_state import AppState
from ..archive import ExtractedMod
from .dialogs import apply_dark_title_bar
from .text import format_bbcode
from .widgets import Banner, CoverImage, make_button, make_label


def pretty_type(item_type: str) -> str:
    """"BUILDINGSKIN" -> "Building skin", "ROAD" -> "Road"."""
    words = item_type.replace('_', ' ').lower()
    if words.endswith('skin') and len(words) > 4 and not words.endswith(' skin'):
        words = words[:-4] + ' skin'
    return words.capitalize()


class InstallPreviewDialog(QDialog):
    def __init__(self, extracted: ExtractedMod, state: AppState, parent=None):
        super().__init__(parent)
        info = extracted.info
        self.setWindowTitle('Install mod')
        self.setMinimumWidth(540)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 20)
        layout.setSpacing(12)

        preview = extracted.root / 'previewimage.png'
        if preview.exists():
            cover = CoverImage()
            cover.set_pixmap(QPixmap(str(preview)))
            layout.addWidget(cover)

        layout.addWidget(make_label(info.display_name, 'heading', wrap=True))
        layout.addWidget(make_label(f'{pretty_type(info.item_type)}  ·  installs to '
                                    f'workshop_wip\\{extracted.folder_name}', 'muted', wrap=True))

        replacing = state.workshop is not None and (state.workshop / extracted.folder_name).exists()
        if replacing:
            notice = Banner()
            notice.show_message('warning', f'A mod is already installed in “{extracted.folder_name}”. '
                                           'Installing replaces it. The old copy is only removed once '
                                           'the new one is in place.')
            layout.addWidget(notice)

        if info.item_desc.strip():
            description = make_label(format_bbcode(info.item_desc), wrap=True)
            description.setTextFormat(Qt.RichText)
            description.setOpenExternalLinks(True)
            description.setAlignment(Qt.AlignTop | Qt.AlignLeft)
            if len(info.item_desc) > 400:  # long descriptions scroll instead of stretching the dialog
                scroll = QScrollArea()
                scroll.setWidgetResizable(True)
                scroll.setWidget(description)
                scroll.setFixedHeight(180)
                layout.addWidget(scroll)
            else:
                layout.addWidget(description)

        self._apply = QCheckBox()
        if state.owner_id:
            self._apply.setText(f'Apply my Owner ID ({state.owner_id}) after installing')
            self._apply.setChecked(True)
        else:
            self._apply.setText('Apply my Owner ID after installing (set one in Settings first)')
            self._apply.setEnabled(False)
        layout.addWidget(self._apply)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(make_button('Cancel', variant='ghost', on_click=self.reject))
        install = make_button('Replace' if replacing else 'Install', 'download', variant='primary',
                              on_click=self.accept)
        install.setDefault(True)
        buttons.addWidget(install)
        layout.addSpacing(4)
        layout.addLayout(buttons)

    @property
    def apply_owner_id(self) -> bool:
        return self._apply.isEnabled() and self._apply.isChecked()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        apply_dark_title_bar(self)
