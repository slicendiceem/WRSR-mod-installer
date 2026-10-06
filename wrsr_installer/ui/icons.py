"""Small line icons, drawn as SVG and tinted to any colour."""

from __future__ import annotations

from functools import lru_cache

from PyQt5.QtCore import QByteArray, QRectF, Qt
from PyQt5.QtGui import QIcon, QPainter, QPixmap
from PyQt5.QtSvg import QSvgRenderer

from . import theme

_SHAPES = {
    'library': '<rect x="3.5" y="3.5" width="7" height="7" rx="1.5"/><rect x="13.5" y="3.5" width="7" '
               'height="7" rx="1.5"/><rect x="3.5" y="13.5" width="7" height="7" rx="1.5"/>'
               '<rect x="13.5" y="13.5" width="7" height="7" rx="1.5"/>',
    'search': '<circle cx="11" cy="11" r="6.5"/><line x1="16" y1="16" x2="20.5" y2="20.5"/>',
    'download': '<line x1="12" y1="3.5" x2="12" y2="14.5"/><polyline points="7.5 10 12 14.5 16.5 10"/>'
                '<path d="M4 16.5v2.5a1.5 1.5 0 0 0 1.5 1.5h13a1.5 1.5 0 0 0 1.5-1.5v-2.5"/>',
    'settings': '<line x1="4" y1="6.5" x2="7" y2="6.5"/><circle cx="9.5" cy="6.5" r="2.2"/>'
                '<line x1="12" y1="6.5" x2="20" y2="6.5"/><line x1="4" y1="12" x2="12.5" y2="12"/>'
                '<circle cx="15" cy="12" r="2.2"/><line x1="17.5" y1="12" x2="20" y2="12"/>'
                '<line x1="4" y1="17.5" x2="5" y2="17.5"/><circle cx="7.5" cy="17.5" r="2.2"/>'
                '<line x1="10" y1="17.5" x2="20" y2="17.5"/>',
    'refresh': '<path d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3"/><polyline points="19.5 4.5 19.5 8.5 15.5 8.5"/>',
    'folder': '<path d="M3.5 7a1.5 1.5 0 0 1 1.5-1.5h4.2l2 2h7.8a1.5 1.5 0 0 1 1.5 1.5v8.5a1.5 1.5 0 0 1-1.5 '
              '1.5H5a1.5 1.5 0 0 1-1.5-1.5z"/>',
    'archive': '<rect x="3.5" y="4" width="17" height="4.5" rx="1"/><path d="M5 8.5v10a1.5 1.5 0 0 0 1.5 '
               '1.5h11a1.5 1.5 0 0 0 1.5-1.5v-10"/><line x1="10" y1="12.5" x2="14" y2="12.5"/>',
    'check': '<polyline points="5 12.5 10 17.5 19 7"/>',
    'check-circle': '<circle cx="12" cy="12" r="8.5"/><polyline points="8 12.3 11 15.2 16.2 9.5"/>',
    'close': '<line x1="6.5" y1="6.5" x2="17.5" y2="17.5"/><line x1="17.5" y1="6.5" x2="6.5" y2="17.5"/>',
    'alert': '<path d="M12 4 3 19.5h18z"/><line x1="12" y1="10" x2="12" y2="14"/>'
             '<line x1="12" y1="16.8" x2="12" y2="16.9"/>',
    'error': '<circle cx="12" cy="12" r="8.5"/><line x1="12" y1="7.8" x2="12" y2="12.8"/>'
             '<line x1="12" y1="16" x2="12" y2="16.1"/>',
    'info': '<circle cx="12" cy="12" r="8.5"/><line x1="12" y1="11" x2="12" y2="16"/>'
            '<line x1="12" y1="8" x2="12" y2="8.1"/>',
    'external': '<path d="M14 4.5h5.5V10"/><line x1="19.5" y1="4.5" x2="11" y2="13"/>'
                '<path d="M17.5 14v4.5a1 1 0 0 1-1 1h-11a1 1 0 0 1-1-1v-11a1 1 0 0 1 1-1H10"/>',
    'stop': '<rect x="6.5" y="6.5" width="11" height="11" rx="2"/>',
    'trash': '<line x1="4.5" y1="7" x2="19.5" y2="7"/><path d="M6.5 7l1 12.5h9l1-12.5"/>'
             '<path d="M9.5 7V4.5h5V7"/>',
    'layers': '<polygon points="12 3.5 20.5 8 12 12.5 3.5 8"/><polyline points="3.5 12 12 16.5 20.5 12"/>'
              '<polyline points="3.5 16 12 20.5 20.5 16"/>',
    'key': '<circle cx="8" cy="15.5" r="3.5"/><line x1="10.5" y1="13" x2="19.5" y2="4"/>'
           '<line x1="16.5" y1="7" x2="19" y2="9.5"/><line x1="14" y1="9.5" x2="16" y2="11.5"/>',
    'image': '<rect x="3.5" y="5" width="17" height="14" rx="2"/><circle cx="9" cy="10" r="1.6"/>'
             '<polyline points="20.5 16 15.5 11 6 19"/>',
    'clock': '<circle cx="12" cy="12" r="8.5"/><polyline points="12 7.5 12 12 15 14"/>',
}

_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
        'stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round">{shape}</svg>')


@lru_cache(maxsize=256)
def pixmap(name: str, color: str = theme.TEXT_MUTED, size: int = 18, scale: float = 2.0,
           stroke: float = 1.8) -> QPixmap:
    svg = _SVG.format(color=color, width=stroke, shape=_SHAPES[name])
    renderer = QSvgRenderer(QByteArray(svg.encode('utf-8')))
    result = QPixmap(int(size * scale), int(size * scale))
    result.fill(Qt.transparent)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.Antialiasing)
    renderer.render(painter, QRectF(0, 0, size * scale, size * scale))
    painter.end()
    result.setDevicePixelRatio(scale)
    return result


def icon(name: str, color: str = theme.TEXT, size: int = 18) -> QIcon:
    result = QIcon()
    result.addPixmap(pixmap(name, color, size), QIcon.Normal)
    result.addPixmap(pixmap(name, theme.TEXT_FAINT, size), QIcon.Disabled)
    return result
