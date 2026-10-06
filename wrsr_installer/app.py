"""Starting the application."""

from __future__ import annotations

import ctypes
import logging
import os
import sys

from PyQt5.QtCore import QThreadPool, Qt
from PyQt5.QtGui import QGuiApplication
from PyQt5.QtWidgets import QApplication

from . import skymods
from .app_state import AppState
from .cache import PageCache
from .config import load_config
from .download_queue import DownloadQueue
from .paths import cache_dir
from .services import load_requirements, look_up, make_installer
from .tasks import run_task
from .ui.main_window import MainWindow
from .ui.theme import apply_theme


def _prepare_qt() -> None:
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    if hasattr(QGuiApplication, 'setHighDpiScaleFactorRoundingPolicy'):
        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    if sys.platform == 'win32':
        try:  # show the app's own icon in the taskbar instead of Python's
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('WRSR.ModInstaller')
        except (AttributeError, OSError):
            pass


def main() -> None:
    if sys.stderr is not None:  # the windowed exe has no console to log to
        logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    _prepare_qt()
    app = QApplication(sys.argv)
    app.setApplicationName('WRSR Mod Installer')
    apply_theme(app)
    pool = QThreadPool.globalInstance()
    pool.setMaxThreadCount(max(8, pool.maxThreadCount()))  # the work is mostly waiting on the network

    # Skymods can take a minute per page, so pages are kept on disk and reused.
    pages = PageCache(cache_dir() / 'skymods')
    skymods.use_cache(pages)
    run_task(lambda ctx: pages.prune())

    state = AppState(load_config())
    queue = DownloadQueue(install=make_installer(state.require_workshop),
                          load_requirements=load_requirements, look_up=look_up,
                          is_installed=lambda name, steam_id: state.index.contains(name, steam_id))
    window = MainWindow(state, queue)
    window.show()
    state.rescan()
    exit_code = app.exec_()

    # Requests can't be interrupted mid-way; don't let one hold the closed app open.
    pool.clear()
    if not pool.waitForDone(3000):
        os._exit(exit_code)
    sys.exit(exit_code)
