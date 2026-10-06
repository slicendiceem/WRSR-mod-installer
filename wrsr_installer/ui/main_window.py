"""The main window: a sidebar with the pages, and notifications in the corner."""

from __future__ import annotations

from functools import partial
from typing import Dict, Optional

from PyQt5.QtCore import QRect, Qt
from PyQt5.QtGui import QBitmap, QIcon, QImage, QPainter, QPainterPath, QPixmap, QRegion
from PyQt5.QtWidgets import (QButtonGroup, QHBoxLayout, QLabel, QMainWindow, QStackedWidget,
                             QVBoxLayout, QWidget)

from .. import __version__, skymods
from ..app_state import AppState
from ..download_queue import DownloadQueue, QueueSummary
from ..paths import resource_path
from . import dialogs
from .browse_page import BrowsePage
from .downloads_page import DownloadsPage
from .library_page import LibraryPage
from .settings_page import SettingsPage
from .widgets import NavButton, ToastHost, make_label


def _rounded(pixmap: QPixmap, radius: float) -> QPixmap:
    result = QPixmap(pixmap.size())
    result.fill(Qt.transparent)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(0, 0, pixmap.width(), pixmap.height(), radius, radius)
    painter.setClipPath(path)
    painter.drawPixmap(0, 0, pixmap)
    painter.end()
    return result


def logo_pixmap(size: int, scale: float = 2.0) -> Optional[QPixmap]:
    image = QPixmap(str(resource_path('logos/wrsrlogo.jfif')))
    if image.isNull():
        return None
    scaled = image.scaled(int(size * scale), int(size * scale), Qt.KeepAspectRatioByExpanding,
                          Qt.SmoothTransformation)
    result = _rounded(scaled, 8 * scale)
    result.setDevicePixelRatio(scale)
    return result


_GLOW_CUTOFF = 96
_ALPHA_RAMP = bytes(0 if a < _GLOW_CUTOFF else round((a - _GLOW_CUTOFF) * 255 / (255 - _GLOW_CUTOFF))
                    for a in range(256))


def banner_pixmap(width: int, scale: float = 2.0) -> Optional[QPixmap]:
    """The game's logo artwork, trimmed to its visible part."""
    image = QImage(str(resource_path('logos/wrsrbanner.png')))
    if image.isNull():
        return None
    # The artwork has a faint white glow meant for light backgrounds, which shows as a grey
    # box on the dark sidebar. Fade out the faint pixels; the artwork itself is opaque.
    image = image.convertToFormat(QImage.Format_ARGB32)
    bits = image.constBits()
    bits.setsize(image.sizeInBytes())
    pixels = bytearray(bytes(bits))
    pixels[3::4] = pixels[3::4].translate(_ALPHA_RAMP)  # ARGB32 is stored as B, G, R, A
    image = QImage(bytes(pixels), image.width(), image.height(), image.bytesPerLine(),
                   QImage.Format_ARGB32).copy()
    visible = QRegion(QBitmap.fromImage(image.createAlphaMask())).boundingRect()
    if not visible.isEmpty():
        image = image.copy(visible.adjusted(-4, -4, 4, 4) & QRect(0, 0, image.width(), image.height()))
    result = QPixmap.fromImage(image.scaledToWidth(int(width * scale), Qt.SmoothTransformation))
    result.setDevicePixelRatio(scale)
    return result


class MainWindow(QMainWindow):
    def __init__(self, state: AppState, queue: DownloadQueue, catalogue=None):
        super().__init__()
        self.state = state
        self.queue = queue
        self._chrome_applied = False
        self.setWindowTitle('WRSR Mod Installer')
        icon = QIcon(str(resource_path('logos/wrsrlogo.jfif')))
        if not icon.isNull():
            self.setWindowIcon(icon)
        self.resize(1280, 800)
        self.setMinimumSize(1040, 660)

        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_sidebar())
        self.pages = QStackedWidget()
        self.pages.setObjectName('Pages')
        root.addWidget(self.pages, 1)
        self.setCentralWidget(central)

        self.toasts = ToastHost(self.pages)
        self.library = LibraryPage(state, self.toasts, self.show_page)
        self.browse = BrowsePage(state, queue, self.toasts, catalogue if catalogue is not None else skymods,
                                 self.show_page)
        self.downloads = DownloadsPage(queue, self.toasts, self.show_page)
        self.settings = SettingsPage(state, self.toasts)
        self._pages: Dict[str, QWidget] = {'library': self.library, 'browse': self.browse,
                                           'downloads': self.downloads, 'settings': self.settings}
        for page in self._pages.values():
            self.pages.addWidget(page)

        for signal in (queue.item_added, queue.item_changed, queue.item_removed):
            signal.connect(self._update_badge)
        queue.mod_installed.connect(self._mod_installed)
        queue.finished.connect(self._downloads_finished)
        self.show_page('library' if state.game_folder else 'settings')

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName('Sidebar')
        sidebar.setFixedWidth(240)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(14, 20, 14, 16)
        layout.setSpacing(4)

        brand = QHBoxLayout()
        brand.setSpacing(10)
        logo = QLabel()
        picture = logo_pixmap(36)
        if picture is not None:
            logo.setPixmap(picture)
        logo.setFixedSize(36, 36)
        brand.addWidget(logo)
        names = QVBoxLayout()
        names.setSpacing(0)
        title = make_label('WRSR Mod Installer')
        title.setObjectName('AppName')
        tagline = make_label('Workers & Resources: SR')
        tagline.setObjectName('AppTagline')
        names.addWidget(title)
        names.addWidget(tagline)
        brand.addLayout(names, 1)
        layout.addLayout(brand)
        layout.addSpacing(26)

        self.nav: Dict[str, NavButton] = {}
        group = QButtonGroup(self)
        group.setExclusive(True)
        entries = (('library', 'Library', 'library'), ('browse', 'Browse', 'search'),
                   ('downloads', 'Downloads', 'download'), (None, None, None),
                   ('settings', 'Settings', 'settings'))
        for name, text, icon_name in entries:
            if name is None:
                layout.addStretch(1)
                art = banner_pixmap(200)
                if art is not None:
                    banner = QLabel()
                    banner.setPixmap(art)
                    banner.setAlignment(Qt.AlignCenter)
                    layout.addWidget(banner)
                    layout.addSpacing(14)
                continue
            button = NavButton(text, icon_name)
            button.clicked.connect(partial(self.show_page, name))
            group.addButton(button)
            layout.addWidget(button)
            self.nav[name] = button
        version = make_label(f'Version {__version__}', 'faint')
        version.setContentsMargins(12, 8, 0, 0)
        layout.addWidget(version)
        return sidebar

    def show_page(self, name: str) -> None:
        self.pages.setCurrentWidget(self._pages[name])
        self.nav[name].setChecked(True)

    def nav_badge(self, name: str) -> str:
        badge = self.nav[name].badge
        return badge.text() if not badge.isHidden() else ''

    def _update_badge(self, item=None) -> None:
        count = self.queue.active_count
        self.nav['downloads'].set_badge(str(count) if count else '')

    def _mod_installed(self, item) -> None:
        self.state.rescan()

    def _downloads_finished(self, summary: QueueSummary) -> None:
        go = partial(self.show_page, 'downloads')
        if summary.failed:
            failed = len(summary.failed)
            installed = f'{len(summary.installed)} installed, ' if summary.installed else ''
            self.toasts.show(f'Downloads finished: {installed}{failed} failed.', 'error', 'View', go)
        elif summary.installed:
            count = len(summary.installed)
            what = f'“{summary.installed[0]}”' if count == 1 else f'{count} mods'
            if self.state.owner_id:
                self.toasts.show(f'Installed {what}. Apply your Owner ID in the Library when you’re ready.',
                                 'success', 'Open Library', partial(self.show_page, 'library'))
            else:
                self.toasts.show(f'Installed {what}.', 'success')

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._chrome_applied:
            self._chrome_applied = True
            dialogs.apply_dark_title_bar(self)

    def closeEvent(self, event) -> None:
        if self.queue.active_count and not dialogs.confirm(
                self, 'Quit WRSR Mod Installer?',
                'Downloads are still running. Quit anyway and cancel them?', 'Quit'):
            event.ignore()
            return
        self.queue.cancel_all()
        event.accept()
