"""Connects the download queue to Skymods and to the game's workshop folder."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Callable, List, Optional

from . import skymods
from .archive import extract_mod
from .cancel import CancelToken
from .download_queue import InstallFn
from .downloader import DownloadError, Progress, download_file
from .skymods import CatalogueMod, Prerequisite


def make_installer(get_workshop: Callable[[], Path]) -> InstallFn:
    """Download a catalogue mod, unpack it and install it, replacing any older copy."""
    def install(mod, progress, cancel) -> Path:
        if not mod.download_url:
            raise DownloadError("Skymods doesn't offer a download for this mod.")
        workshop = get_workshop()
        with tempfile.TemporaryDirectory(prefix='wrsr-download-') as temp:
            archive_path = Path(temp) / 'mod.zip'
            download_file(mod.download_url, archive_path, progress, cancel)
            cancel.check()
            progress(Progress('installing'))
            with extract_mod(archive_path, mod.steam_id or mod.name) as extracted:
                cancel.check()
                return extracted.install(workshop, replace=True)
    return install


def load_requirements(mod: CatalogueMod, cancel: CancelToken) -> List[Prerequisite]:
    """Load the mod's Skymods page (or a saved copy) and return the mods it needs."""
    cancel.check()
    mod.merge_details(skymods.fetch_mod(mod.url))
    return list(mod.prerequisites)


def look_up(steam_id: str, cancel: CancelToken) -> Optional[CatalogueMod]:
    """Find a mod on Skymods by its Steam ID."""
    cancel.check()
    return skymods.find_by_steam_id(steam_id)
