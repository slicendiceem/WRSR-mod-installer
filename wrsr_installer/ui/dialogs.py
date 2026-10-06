"""Confirmation questions and the dark Windows title bar."""

from __future__ import annotations

import ctypes
import sys

from PyQt5.QtGui import QGuiApplication
from PyQt5.QtWidgets import QMessageBox, QWidget

from . import theme


def apply_dark_title_bar(window: QWidget) -> None:
    """Ask Windows 10/11 to draw this window's title bar dark, matching the app."""
    if sys.platform != 'win32' or QGuiApplication.platformName() != 'windows':
        return
    try:
        hwnd = int(window.winId())
        dwm = ctypes.windll.dwmapi
        enabled = ctypes.c_int(1)
        for attribute in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (newer, then older builds)
            if dwm.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(enabled), ctypes.sizeof(enabled)) == 0:
                break
        red, green, blue = (int(theme.BG[i:i + 2], 16) for i in (1, 3, 5))
        caption = ctypes.c_int(red | green << 8 | blue << 16)
        dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(caption), ctypes.sizeof(caption))  # Windows 11
    except (AttributeError, OSError):
        pass


def confirm(parent: QWidget, title: str, text: str, ok_text: str = 'OK') -> bool:
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    box.setIcon(QMessageBox.NoIcon)
    ok = box.addButton(ok_text, QMessageBox.AcceptRole)
    ok.setProperty('variant', 'primary')
    box.addButton('Cancel', QMessageBox.RejectRole)
    box.setDefaultButton(ok)
    apply_dark_title_bar(box)
    box.exec_()
    return box.clickedButton() is ok
