"""Reusable widgets: buttons, pills, banners, toasts and images that load in the background."""

from __future__ import annotations

from collections import OrderedDict
from functools import partial
from typing import Callable, Dict, List, Optional

import requests
from PyQt5.QtCore import (QEasingCurve, QEvent, QObject, QPropertyAnimation, QRectF, QSize, Qt,
                          QTimer, pyqtSignal)
from PyQt5.QtGui import QColor, QPainter, QPainterPath, QPixmap
from PyQt5.QtWidgets import (QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QProgressBar,
                             QPushButton, QSizePolicy, QVBoxLayout, QWidget)

from ..tasks import run_task
from . import icons, theme


def repolish(widget: QWidget) -> None:
    """Re-apply the stylesheet after changing a property it selects on."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def make_button(text: str = '', icon: Optional[str] = None, variant: Optional[str] = None,
                size: Optional[str] = None, tooltip: Optional[str] = None,
                on_click: Optional[Callable[[], None]] = None) -> QPushButton:
    button = QPushButton(text)
    button.setCursor(Qt.PointingHandCursor)
    if variant:
        button.setProperty('variant', variant)
    if size:
        button.setProperty('sizing', size)  # not 'size': QWidget already has a size property
    if icon:
        color = '#ffffff' if variant == 'primary' else theme.TEXT
        button.setIcon(icons.icon(icon, color, 16))
        button.setIconSize(QSize(16, 16))
    if tooltip:
        button.setToolTip(tooltip)
    if on_click is not None:
        button.clicked.connect(lambda checked=False: on_click())
    return button


def make_label(text: str = '', role: Optional[str] = None, wrap: bool = False,
               selectable: bool = False) -> QLabel:
    label = QLabel(text)
    if role:
        label.setProperty('role', role)
    label.setWordWrap(wrap)
    if selectable:
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return label


def icon_label(name: str, color: str, size: int = 18) -> QLabel:
    label = QLabel()
    label.setPixmap(icons.pixmap(name, color, size))
    label.setFixedSize(size, size)
    return label


class Pill(QLabel):
    """A small rounded status label."""

    def __init__(self, text: str = '', kind: str = 'neutral'):
        super().__init__(text)
        self.setAlignment(Qt.AlignCenter)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.set(text, kind)

    def set(self, text: str, kind: str) -> None:
        self.setText(text)
        self.setProperty('pill', kind)
        repolish(self)


class PageHeader(QWidget):
    def __init__(self, title: str, subtitle: str = ''):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        text = QVBoxLayout()
        text.setSpacing(2)
        self.title = make_label(title, 'title')
        self.subtitle = make_label(subtitle, 'muted', wrap=True)
        text.addWidget(self.title)
        text.addWidget(self.subtitle)
        layout.addLayout(text, 1)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        layout.addLayout(self.actions)

    def add_action(self, widget: QWidget) -> QWidget:
        self.actions.addWidget(widget, 0, Qt.AlignBottom)
        return widget


class Banner(QFrame):
    """An inline notice with an optional action, used instead of pop-up message boxes."""

    _ICONS = {'warning': ('alert', theme.WARNING), 'error': ('error', theme.DANGER),
              'info': ('info', theme.INFO)}

    def __init__(self):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 10, 10)
        layout.setSpacing(10)
        self._icon = QLabel()
        self._icon.setFixedSize(18, 18)
        self._text = make_label(wrap=True)
        self._button = make_button(variant=None, size='small')
        self._button.clicked.connect(self._run_action)
        self._action: Optional[Callable[[], None]] = None
        layout.addWidget(self._icon, 0, Qt.AlignTop)
        layout.addWidget(self._text, 1)
        layout.addWidget(self._button, 0, Qt.AlignVCenter)
        self.hide()

    def show_message(self, kind: str, text: str, action_text: Optional[str] = None,
                     action: Optional[Callable[[], None]] = None) -> None:
        name, color = self._ICONS[kind]
        self.setProperty('banner', kind)
        repolish(self)
        self._icon.setPixmap(icons.pixmap(name, color, 18))
        self._text.setText(text)
        self._action = action
        self._button.setText(action_text or '')
        self._button.setVisible(bool(action_text and action))
        self.show()

    def _run_action(self) -> None:
        if self._action is not None:
            self._action()


class BusyBar(QProgressBar):
    """A thin, indeterminate progress line."""

    def __init__(self):
        super().__init__()
        self.setRange(0, 0)
        self.setProperty('thin', True)
        self.setTextVisible(False)
        self.hide()


class EmptyState(QWidget):
    def __init__(self, icon_name: str, title: str, text: str = '', action_text: Optional[str] = None,
                 action: Optional[Callable[[], None]] = None):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(8)
        picture = icon_label(icon_name, theme.TEXT_FAINT, 44)
        layout.addWidget(picture, 0, Qt.AlignHCenter)
        layout.addSpacing(6)
        self.title = make_label(title, 'heading')
        self.title.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.title)
        self.text = make_label(text, 'muted', wrap=True)
        self.text.setAlignment(Qt.AlignCenter)
        self.text.setMaximumWidth(420)
        layout.addWidget(self.text, 0, Qt.AlignHCenter)
        if action_text and action:
            layout.addSpacing(8)
            layout.addWidget(make_button(action_text, variant='primary', on_click=action), 0, Qt.AlignHCenter)


class NavButton(QPushButton):
    """A sidebar entry with an icon, a label and an optional count badge."""

    def __init__(self, text: str, icon_name: str):
        super().__init__()
        self.setObjectName('NavButton')
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(40)
        self._icon_name = icon_name
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 10, 0)
        layout.setSpacing(12)
        self._icon = QLabel()
        self._text = QLabel(text)
        self._text.setObjectName('NavText')
        self.badge = QLabel()
        self.badge.setObjectName('NavBadge')
        self.badge.hide()
        for child in (self._icon, self._text, self.badge):
            child.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout.addWidget(self._icon)
        layout.addWidget(self._text)
        layout.addStretch(1)
        layout.addWidget(self.badge)
        self.toggled.connect(self._update_look)
        self._update_look(False)

    def set_badge(self, text: str) -> None:
        self.badge.setText(text)
        self.badge.setVisible(bool(text))

    def _update_look(self, checked: bool) -> None:
        self._icon.setPixmap(icons.pixmap(self._icon_name, theme.ACCENT if checked else theme.TEXT_MUTED, 18))
        self._text.setProperty('active', checked)
        repolish(self._text)


# --- toasts -------------------------------------------------------------------

class Toast(QFrame):
    closed = pyqtSignal(object)

    _ICONS = {'success': ('check-circle', theme.SUCCESS), 'error': ('error', theme.DANGER),
              'warning': ('alert', theme.WARNING), 'info': ('info', theme.INFO)}

    def __init__(self, parent: QWidget, text: str, kind: str, action_text: Optional[str],
                 action: Optional[Callable[[], None]], timeout: int):
        super().__init__(parent)
        self.setObjectName('Toast')
        self.setFixedWidth(380)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 12, 8, 12)
        layout.setSpacing(10)
        name, color = self._ICONS.get(kind, self._ICONS['info'])
        layout.addWidget(icon_label(name, color, 18), 0, Qt.AlignTop)
        message = make_label(text, wrap=True)
        layout.addWidget(message, 1)
        if action_text and action:
            button = make_button(action_text, variant='link')
            button.clicked.connect(lambda: (action(), self.dismiss()))
            layout.addWidget(button, 0, Qt.AlignTop)
        close = make_button(icon='close', variant='ghost', size='small', tooltip='Dismiss')
        close.setFixedSize(26, 26)
        close.clicked.connect(self.dismiss)
        layout.addWidget(close, 0, Qt.AlignTop)

        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(0.0)
        self.setGraphicsEffect(self._effect)
        self._fade = QPropertyAnimation(self._effect, b'opacity', self)
        self._fade.setDuration(180)
        self._fade.setEasingCurve(QEasingCurve.OutCubic)
        self._closing = False
        if timeout > 0:
            QTimer.singleShot(timeout, self.dismiss)

    def appear(self) -> None:
        self.show()
        self.raise_()
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.start()

    def dismiss(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._fade.stop()
        self._fade.setStartValue(self._effect.opacity())
        self._fade.setEndValue(0.0)
        self._fade.finished.connect(self._finish)
        self._fade.start()

    def _finish(self) -> None:
        self.hide()
        self.closed.emit(self)
        self.deleteLater()


class ToastHost(QObject):
    """Shows short notifications stacked in the bottom-right corner of a widget."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self._parent = parent
        self._toasts: List[Toast] = []
        parent.installEventFilter(self)

    def show(self, text: str, kind: str = 'info', action_text: Optional[str] = None,
             action: Optional[Callable[[], None]] = None, timeout: Optional[int] = None) -> Toast:
        if timeout is None:
            timeout = 8000 if kind in ('error', 'warning') or action else 4500
        toast = Toast(self._parent, text, kind, action_text, action, timeout)
        toast.closed.connect(self._remove)
        toast.adjustSize()
        self._toasts.append(toast)
        if len(self._toasts) > 4:
            self._toasts[0].dismiss()
        self._layout()
        toast.appear()
        return toast

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self._parent and event.type() == QEvent.Resize:
            self._layout()
        return False

    def _remove(self, toast: Toast) -> None:
        if toast in self._toasts:
            self._toasts.remove(toast)
        self._layout()

    def _layout(self) -> None:
        y = self._parent.height() - 24
        for toast in reversed(self._toasts):
            toast.adjustSize()
            y -= toast.height()
            toast.move(self._parent.width() - toast.width() - 24, y)
            y -= 10


# --- images -------------------------------------------------------------------

def _fetch_image(url: str) -> Optional[bytes]:
    """The image's bytes, or None if it can't be fetched (missing previews are common)."""
    try:
        response = requests.get(url, timeout=(10, 30))
        response.raise_for_status()
    except requests.RequestException:
        return None
    return response.content


class ImageLoader(QObject):
    """Downloads images in the background and keeps recent ones in memory."""

    _instance: Optional['ImageLoader'] = None
    MAX_CACHED = 80

    @classmethod
    def instance(cls) -> 'ImageLoader':
        if cls._instance is None:
            cls._instance = ImageLoader()
        return cls._instance

    def __init__(self):
        super().__init__()
        self._cache: 'OrderedDict[str, QPixmap]' = OrderedDict()
        self._waiting: Dict[str, List[Callable[[Optional[QPixmap]], None]]] = {}

    def load(self, url: str, callback: Callable[[Optional[QPixmap]], None]) -> None:
        if url in self._cache:
            self._cache.move_to_end(url)
            callback(self._cache[url])
            return
        if url in self._waiting:
            self._waiting[url].append(callback)
            return
        self._waiting[url] = [callback]
        run_task(lambda ctx: _fetch_image(url), on_result=partial(self._loaded, url),
                 on_error=lambda error: self._loaded(url, None))

    def _loaded(self, url: str, data: Optional[bytes]) -> None:
        image = None
        if data:
            image = QPixmap()
            if not image.loadFromData(data):
                image = None
        if image is not None:
            self._cache[url] = image
            while len(self._cache) > self.MAX_CACHED:
                self._cache.popitem(last=False)
        for callback in self._waiting.pop(url, []):
            callback(image)


class CoverImage(QWidget):
    """A picture cropped to fill a rounded 16:9 box, with a placeholder while it loads."""

    def __init__(self, ratio: float = 16 / 9, radius: int = 10):
        super().__init__()
        self._ratio = ratio
        self._radius = radius
        self._pixmap: Optional[QPixmap] = None
        self._url: Optional[str] = None
        self._loading = False
        policy = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self.setMinimumHeight(120)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return int(width / self._ratio)

    def sizeHint(self) -> QSize:
        return QSize(360, int(360 / self._ratio))

    def clear(self) -> None:
        self._url = None
        self._pixmap = None
        self._loading = False
        self.update()

    def set_pixmap(self, image: Optional[QPixmap]) -> None:
        self._url = None
        self._loading = False
        self._pixmap = image if image is not None and not image.isNull() else None
        self.update()

    def set_url(self, url: Optional[str]) -> None:
        if url == self._url and (self._pixmap is not None or self._loading):
            return
        self._url = url
        self._pixmap = None
        self._loading = bool(url)
        self.update()
        if url:
            ImageLoader.instance().load(url, partial(self._loaded, url))

    def _loaded(self, url: str, image: Optional[QPixmap]) -> None:
        if url != self._url:
            return  # a different picture was requested meanwhile
        self._loading = False
        self._pixmap = image
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        rect = QRectF(self.rect())
        path = QPainterPath()
        path.addRoundedRect(rect, self._radius, self._radius)
        painter.setClipPath(path)
        if self._pixmap is not None:
            scaled = self._pixmap.scaled(self.size() * self.devicePixelRatioF(),
                                         Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            scaled.setDevicePixelRatio(self.devicePixelRatioF())
            logical = scaled.size() / self.devicePixelRatioF()
            x = (self.width() - logical.width()) / 2
            y = (self.height() - logical.height()) / 2
            painter.drawPixmap(int(x), int(y), scaled)
        else:
            painter.fillRect(rect, QColor(theme.SURFACE_2))
            name = 'clock' if self._loading else 'image'
            mark = icons.pixmap(name, theme.TEXT_FAINT, 32)
            painter.drawPixmap(int(rect.center().x() - 16), int(rect.center().y() - 16), mark)
        painter.end()
