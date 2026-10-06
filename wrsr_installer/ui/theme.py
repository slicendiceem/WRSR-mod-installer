"""Colours, fonts and the stylesheet for the app's dark, WRSR-red look."""

from __future__ import annotations

import tempfile
from pathlib import Path

from PyQt5.QtGui import QColor, QFont, QFontDatabase, QPalette
from PyQt5.QtWidgets import QApplication, QStyleFactory

BG = '#111214'
SIDEBAR = '#0b0c0e'
SURFACE = '#17181b'
SURFACE_2 = '#1e2024'
SURFACE_3 = '#272a30'
BORDER = '#2a2d33'
BORDER_STRONG = '#3a3e46'
TEXT = '#ecebe8'
TEXT_MUTED = '#a3a6ae'
TEXT_FAINT = '#6f737c'
ACCENT = '#c8372b'          # the red of the game's star
ACCENT_HOVER = '#d64538'
ACCENT_PRESSED = '#a82c22'
ACCENT_SOFT = 'rgba(200, 55, 43, 0.18)'
GOLD = '#e2a646'
SUCCESS = '#4cc27a'
WARNING = '#e2a646'
DANGER = '#f0645a'
INFO = '#5aa7ea'

# (background, text) for status pills and badges, by kind.
PILL_COLORS = {
    'success': (QColor(76, 194, 122, 36), QColor('#72d69a')),
    'warning': (QColor(226, 166, 70, 36), QColor('#f0bd6b')),
    'danger': (QColor(240, 100, 90, 36), QColor('#f58a82')),
    'info': (QColor(90, 167, 234, 36), QColor('#8cc3f3')),
    'neutral': (QColor(SURFACE_3), QColor(TEXT_MUTED)),
}
KIND_COLORS = {'success': SUCCESS, 'warning': WARNING, 'danger': DANGER, 'error': DANGER,
               'info': INFO, 'neutral': TEXT_MUTED}

STYLESHEET = f"""
* {{ outline: none; }}
QWidget {{ color: {TEXT}; }}
QMainWindow, QDialog, QStackedWidget#Pages {{ background: {BG}; }}
QWidget#Sidebar {{ background: {SIDEBAR}; border-right: 1px solid {BORDER}; }}
QToolTip {{ background: {SURFACE_3}; color: {TEXT}; border: 1px solid {BORDER_STRONG};
            border-radius: 6px; padding: 6px 8px; }}

QLabel {{ background: transparent; }}
QLabel[role="title"] {{ font-size: 24px; font-weight: 600; }}
QLabel[role="heading"] {{ font-size: 17px; font-weight: 600; }}
QLabel[role="subheading"] {{ font-size: 14px; font-weight: 600; }}
QLabel[role="section"] {{ color: {TEXT_FAINT}; font-size: 11px; font-weight: 700; }}
QLabel[role="muted"] {{ color: {TEXT_MUTED}; }}
QLabel[role="faint"] {{ color: {TEXT_FAINT}; font-size: 12px; }}
QLabel[role="error"] {{ color: {DANGER}; }}
QLabel[role="success"] {{ color: {SUCCESS}; }}
QLabel[role="warning"] {{ color: {WARNING}; }}
QLabel#AppName {{ font-size: 15px; font-weight: 700; }}
QLabel#AppTagline {{ color: {TEXT_FAINT}; font-size: 11px; }}
QLabel#NavText {{ color: {TEXT_MUTED}; font-size: 13px; font-weight: 500; }}
QLabel#NavText[active="true"] {{ color: {TEXT}; font-weight: 600; }}
QLabel#NavBadge {{ background: {ACCENT}; color: white; border-radius: 9px; padding: 1px 7px;
                   font-size: 11px; font-weight: 700; }}
QLabel[pill] {{ border-radius: 10px; padding: 2px 9px; font-size: 11px; font-weight: 600; }}
QLabel[pill="success"] {{ background: rgba(76, 194, 122, 0.14); color: #72d69a; }}
QLabel[pill="warning"] {{ background: rgba(226, 166, 70, 0.14); color: #f0bd6b; }}
QLabel[pill="danger"] {{ background: rgba(240, 100, 90, 0.14); color: #f58a82; }}
QLabel[pill="info"] {{ background: rgba(90, 167, 234, 0.14); color: #8cc3f3; }}
QLabel[pill="neutral"] {{ background: {SURFACE_3}; color: {TEXT_MUTED}; }}

QPushButton {{ background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 8px;
               padding: 7px 14px; color: {TEXT}; font-weight: 500; }}
QPushButton:hover {{ background: {SURFACE_3}; border-color: {BORDER_STRONG}; }}
QPushButton:pressed {{ background: {BORDER}; }}
QPushButton:disabled {{ color: {TEXT_FAINT}; background: {SURFACE}; border-color: {SURFACE_2}; }}
QPushButton[variant="primary"] {{ background: {ACCENT}; border-color: {ACCENT}; color: white;
                                  font-weight: 600; }}
QPushButton[variant="primary"]:hover {{ background: {ACCENT_HOVER}; border-color: {ACCENT_HOVER}; }}
QPushButton[variant="primary"]:pressed {{ background: {ACCENT_PRESSED}; border-color: {ACCENT_PRESSED}; }}
QPushButton[variant="primary"]:disabled {{ background: #3a1f1c; border-color: #3a1f1c; color: #9a7470; }}
QPushButton[variant="ghost"] {{ background: transparent; border-color: transparent; color: {TEXT_MUTED}; }}
QPushButton[variant="ghost"]:hover {{ background: {SURFACE_2}; color: {TEXT}; }}
QPushButton[variant="link"] {{ background: transparent; border: none; color: {INFO}; padding: 2px 4px;
                               font-weight: 600; }}
QPushButton[variant="link"]:hover {{ color: #8cc3f3; }}
QPushButton[sizing="small"] {{ padding: 4px 10px; border-radius: 6px; font-size: 12px; }}
QPushButton#NavButton {{ background: transparent; border: none; border-radius: 8px; padding: 0; }}
QPushButton#NavButton:hover {{ background: {SURFACE_2}; }}
QPushButton#NavButton:checked {{ background: {ACCENT_SOFT}; }}

QLineEdit {{ background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 8px;
             padding: 8px 12px; selection-background-color: {ACCENT}; color: {TEXT}; }}
QLineEdit:hover {{ border-color: {BORDER_STRONG}; }}
QLineEdit:focus {{ border-color: {ACCENT}; }}
QLineEdit:read-only {{ color: {TEXT_MUTED}; }}
QLineEdit[sizing="large"] {{ padding: 10px 14px; font-size: 14px; border-radius: 10px; }}

QFrame[card="true"] {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px; }}
QFrame[banner="warning"] {{ background: rgba(226, 166, 70, 0.08); border: 1px solid rgba(226, 166, 70, 0.32);
                            border-radius: 10px; }}
QFrame[banner="error"] {{ background: rgba(240, 100, 90, 0.08); border: 1px solid rgba(240, 100, 90, 0.32);
                          border-radius: 10px; }}
QFrame[banner="info"] {{ background: rgba(90, 167, 234, 0.08); border: 1px solid rgba(90, 167, 234, 0.30);
                         border-radius: 10px; }}
QFrame#Toast {{ background: {SURFACE_3}; border: 1px solid {BORDER_STRONG}; border-radius: 10px; }}
QFrame#DownloadRow {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px; }}

QTableWidget, QListView {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px;
                           gridline-color: transparent; selection-background-color: {ACCENT_SOFT};
                           selection-color: {TEXT}; }}
QTableWidget::item {{ padding-left: 12px; border-bottom: 1px solid #202227; }}
QTableWidget::item:selected {{ background: {ACCENT_SOFT}; color: {TEXT}; }}
QTableWidget::item:hover {{ background: {SURFACE_2}; }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{ background: {SURFACE}; color: {TEXT_FAINT}; border: none;
                        border-bottom: 1px solid {BORDER}; padding: 10px 12px; font-size: 11px;
                        font-weight: 700; }}
QHeaderView::section:first {{ border-top-left-radius: 12px; }}
QHeaderView::section:last {{ border-top-right-radius: 12px; }}
QTableCornerButton::section {{ background: {SURFACE}; border: none; }}

QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 4px 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px 4px; }}
QScrollBar::handle:vertical {{ background: {SURFACE_3}; border-radius: 3px; min-height: 32px; }}
QScrollBar::handle:horizontal {{ background: {SURFACE_3}; border-radius: 3px; min-width: 32px; }}
QScrollBar::handle:hover {{ background: {BORDER_STRONG}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QProgressBar {{ background: {SURFACE_3}; border: none; border-radius: 3px; min-height: 6px;
                max-height: 6px; color: transparent; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}
QProgressBar[thin="true"] {{ min-height: 2px; max-height: 2px; border-radius: 0; background: transparent; }}
QProgressBar[thin="true"]::chunk {{ border-radius: 0; }}

QSplitter::handle {{ background: transparent; }}
QCheckBox {{ spacing: 8px; }}
QMessageBox {{ background: {SURFACE}; }}
QMessageBox QLabel {{ color: {TEXT}; }}
"""


def font_family() -> str:
    # Not "Segoe UI Variable": Qt 5 renders that variable font with broken spacing and drops
    # some punctuation, so the classic Segoe UI is the right choice on Windows.
    available = set(QFontDatabase().families())
    for family in ('Segoe UI', 'Inter', 'Helvetica Neue', 'Arial'):
        if family in available:
            return family
    return QApplication.font().family()


def _check_mark_file() -> str:
    """The tick image for checkboxes; stylesheets can only use images from files."""
    from . import icons
    path = Path(tempfile.gettempdir()) / 'wrsr-mod-installer' / 'check.png'
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        icons.pixmap('check', '#ffffff', 14, stroke=2.6).save(str(path))
    return path.as_posix()


def apply_theme(app: QApplication) -> None:
    app.setStyle(QStyleFactory.create('Fusion'))
    palette = QPalette()
    roles = {
        QPalette.Window: BG, QPalette.WindowText: TEXT, QPalette.Base: SURFACE_2,
        QPalette.AlternateBase: SURFACE, QPalette.ToolTipBase: SURFACE_3, QPalette.ToolTipText: TEXT,
        QPalette.Text: TEXT, QPalette.Button: SURFACE_2, QPalette.ButtonText: TEXT,
        QPalette.BrightText: '#ffffff', QPalette.Highlight: ACCENT, QPalette.HighlightedText: '#ffffff',
        QPalette.Link: INFO, QPalette.PlaceholderText: TEXT_FAINT, QPalette.Mid: BORDER,
        QPalette.Dark: SIDEBAR, QPalette.Shadow: '#000000',
    }
    for role, color in roles.items():
        palette.setColor(role, QColor(color))
    for role in (QPalette.Text, QPalette.ButtonText, QPalette.WindowText):
        palette.setColor(QPalette.Disabled, role, QColor(TEXT_FAINT))
    app.setPalette(palette)
    app.setFont(QFont(font_family(), 10))
    checkbox = f"""
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px; border: 1px solid {BORDER_STRONG};
                        background: {SURFACE_2}; }}
QCheckBox::indicator:hover {{ border-color: {TEXT_FAINT}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; image: url("{_check_mark_file()}"); }}
QCheckBox::indicator:disabled {{ background: {SURFACE}; border-color: {SURFACE_3}; }}
"""
    app.setStyleSheet(STYLESHEET + checkbox)
