"""Extracting mod archives and installing mod folders into workshop_wip."""

from __future__ import annotations

import os
import re
import shutil
import tempfile
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import List

from .workshop import ModInfo, find_config_file, read_mod

MAX_SEARCH_DEPTH = 4
# Backups of replaced mods live next to workshop_wip (same drive, so moves are instant)
# but outside it, so the game never sees them.
_TMP_DIR_NAME = '.wrsr-mod-installer-tmp'
_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED_NAMES = {'CON', 'PRN', 'AUX', 'NUL',
                   *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}


class ArchiveError(Exception):
    """The archive can't be read or doesn't contain a WRSR mod."""


class ModExistsError(Exception):
    def __init__(self, path: Path):
        super().__init__(f'A mod is already installed at {path}')
        self.path = path


def safe_filename(name: str, fallback: str = 'mod') -> str:
    """Make name usable as a Windows file or folder name."""
    cleaned = _INVALID_CHARS.sub('_', name).strip().rstrip('. ')
    if not cleaned:
        return fallback
    if cleaned.split('.')[0].upper() in _RESERVED_NAMES:
        cleaned = '_' + cleaned
    return cleaned


@dataclass
class ExtractedMod:
    """A mod unpacked into a temporary folder, ready to preview and install."""
    root: Path
    folder_name: str
    info: ModInfo
    _temp: tempfile.TemporaryDirectory

    def install(self, workshop: Path, replace: bool = False) -> Path:
        return install_mod_folder(self.root, workshop, self.folder_name, replace)

    def cleanup(self) -> None:
        try:
            self._temp.cleanup()
        except OSError:
            pass

    def __enter__(self) -> 'ExtractedMod':
        return self

    def __exit__(self, *exc_info) -> None:
        self.cleanup()


def extract_mod(archive_path, fallback_name: str) -> ExtractedMod:
    """Unpack a ZIP archive and locate the mod inside it.

    The install folder is named after the mod's $ITEM_ID when it has one, like the
    game does; otherwise after the mod's folder, or fallback_name for archives that
    keep their files at the top level.
    """
    archive_path = Path(archive_path)
    temp = tempfile.TemporaryDirectory(prefix='wrsr-mod-')
    try:
        extracted = Path(temp.name) / 'extracted'
        _extract_zip(archive_path, extracted)
        root = find_mod_root(extracted)
        info = read_mod(root)
        default_name = safe_filename(fallback_name) if root == extracted else root.name
        return ExtractedMod(root, info.item_id or default_name, info, temp)
    except BaseException:
        temp.cleanup()
        raise


def find_mod_root(extracted: Path) -> Path:
    """Return the shallowest folder that contains a workshopconfig.ini."""
    level = [extracted]
    for _ in range(MAX_SEARCH_DEPTH + 1):
        with_config = [d for d in level if find_config_file(d) is not None]
        if with_config:
            return min(with_config, key=lambda d: d.name.lower())
        level = [child for d in level for child in _subfolders(d)]
        if not level:
            break
    raise ArchiveError("The archive has no workshopconfig.ini, so it doesn't look like a WRSR mod")


def install_mod_folder(src, workshop, folder_name: str, replace: bool = False) -> Path:
    """Move the mod folder src to workshop/folder_name.

    An existing mod is only touched when replace is True, and it is kept as a backup
    until the new copy is fully in place, so a failed install never loses it.
    """
    src, workshop = Path(src), Path(workshop)
    workshop.mkdir(parents=True, exist_ok=True)
    dest = workshop / folder_name
    if dest.exists() and not replace:
        raise ModExistsError(dest)

    tmp_root = workshop.parent / _TMP_DIR_NAME
    backup = None
    try:
        if dest.exists():
            tmp_root.mkdir(exist_ok=True)
            backup = tmp_root / f'{folder_name}.{uuid.uuid4().hex[:8]}.old'
            os.replace(dest, backup)
        try:
            # shutil.move copies when src is on another drive (Path.rename can't).
            shutil.move(str(src), str(dest))
        except BaseException:
            shutil.rmtree(dest, ignore_errors=True)
            if backup is not None:
                os.replace(backup, dest)
                backup = None
            raise
        if backup is not None:
            shutil.rmtree(backup, ignore_errors=True)
    finally:
        _remove_if_empty(tmp_root)
    return dest


def _extract_zip(archive_path: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(archive_path) as zf:
            zf.extractall(dest)
    except zipfile.BadZipFile as e:
        raise ArchiveError(f'{archive_path.name} is not a valid ZIP archive') from e
    except NotImplementedError as e:
        raise ArchiveError(f'{archive_path.name} uses a compression method that is not supported') from e


def _subfolders(folder: Path) -> List[Path]:
    return sorted((p for p in folder.iterdir() if p.is_dir()), key=lambda p: p.name.lower())


def _remove_if_empty(folder: Path) -> None:
    try:
        folder.rmdir()
    except OSError:
        pass
