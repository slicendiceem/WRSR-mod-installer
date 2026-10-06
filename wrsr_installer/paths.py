"""Where the app finds its bundled files and keeps its cache."""

import os
import sys
from pathlib import Path


def resource_path(relative: str) -> Path:
    """A file bundled with the app, both from source and inside the PyInstaller exe."""
    base = getattr(sys, '_MEIPASS', None)
    root = Path(base) if base else Path(__file__).resolve().parent.parent
    return root / relative


def cache_dir() -> Path:
    if sys.platform == 'win32':
        base = os.environ.get('LOCALAPPDATA') or str(Path.home() / 'AppData' / 'Local')
        return Path(base) / 'WRSR Mod Installer' / 'cache'
    base = os.environ.get('XDG_CACHE_HOME') or str(Path.home() / '.cache')
    return Path(base) / 'wrsr-mod-installer'
