"""Reading and editing mods in the game's media_soviet/workshop_wip folder."""

from __future__ import annotations

import codecs
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

CONFIG_FILENAME = 'workshopconfig.ini'

# A setting only counts at the start of a line ("\r", "\n" or start of file), so text
# inside a description is never mistaken for a setting.
_LINE_START = r'(?:(?<=[\r\n])|\A)[ \t]*'
_OWNER_ID_LINE = re.compile(r'(?:(?<=[\r\n])|\A)([ \t]*)\$OWNER_ID\b[^\r\n]*')
_OWNER_ID = re.compile(_LINE_START + r'\$OWNER_ID[ \t]*=?[ \t]*(\d+)')
_ITEM_ID = re.compile(_LINE_START + r'\$ITEM_ID[ \t]*=?[ \t]*(\d+)')
_ITEM_TYPE = re.compile(_LINE_START + r'\$ITEM_TYPE[ \t]*WORKSHOP_ITEMTYPE_(\w+)')
_ITEM_NAME = re.compile(_LINE_START + r'\$ITEM_NAME[ \t]+"([^"]*)"')
_ITEM_DESC = re.compile(_LINE_START + r'\$ITEM_DESC[ \t]+"([\s\S]*?)"\s*(?=\$|\Z)')
_OWNER_ID_FORMAT = re.compile(r'[0-9]{1,20}')


@dataclass
class ConfigFields:
    owner_id: Optional[str] = None
    item_id: Optional[str] = None
    item_type: str = 'Unknown'
    item_name: str = ''
    item_desc: str = ''


@dataclass
class ModInfo:
    folder: str
    path: Path
    config_path: Path
    owner_id: Optional[str] = None
    item_id: Optional[str] = None
    item_type: str = 'Unknown'
    item_name: str = ''
    item_desc: str = ''
    error: Optional[str] = None

    @property
    def display_name(self) -> str:
        return self.item_name or self.folder


def workshop_dir(game_folder) -> Path:
    return Path(game_folder) / 'media_soviet' / 'workshop_wip'


def game_folder_from(chosen: str) -> str:
    """The game folder, even if the user picked its media_soviet or workshop_wip folder."""
    path = Path(chosen)
    if path.name.lower() == 'workshop_wip' and path.parent.name.lower() == 'media_soviet':
        return str(path.parent.parent)
    if path.name.lower() == 'media_soviet':
        return str(path.parent)
    return chosen


def parse_config(text: str) -> ConfigFields:
    def first(pattern):
        match = pattern.search(text)
        return match.group(1) if match else None

    return ConfigFields(
        owner_id=first(_OWNER_ID),
        item_id=first(_ITEM_ID),
        item_type=first(_ITEM_TYPE) or 'Unknown',
        item_name=first(_ITEM_NAME) or '',
        item_desc=first(_ITEM_DESC) or '',
    )


def set_owner_id(text: str, owner_id: str) -> str:
    """Return text with every $OWNER_ID line set to owner_id (added at the top if missing)."""
    line = f'$OWNER_ID {owner_id}'
    new_text, count = _OWNER_ID_LINE.subn(lambda m: m.group(1) + line, text)
    if count:
        return new_text
    if '\r\n' in text:
        newline = '\r\n'
    elif '\r' in text:
        newline = '\r'
    else:
        newline = '\n'
    return line + newline + text


def decode_config(raw: bytes) -> Tuple[str, str]:
    """Decode a config file, returning (text, encoding) such that text.encode(encoding) == raw."""
    if raw.startswith(codecs.BOM_UTF8):
        try:
            return raw.decode('utf-8-sig'), 'utf-8-sig'
        except UnicodeDecodeError:
            pass
    for encoding in ('utf-8', 'cp1251'):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return raw.decode('latin-1'), 'latin-1'


def is_valid_owner_id(value: str) -> bool:
    return bool(_OWNER_ID_FORMAT.fullmatch(value))


def find_config_file(folder: Path) -> Optional[Path]:
    try:
        with os.scandir(folder) as entries:
            for entry in entries:
                if entry.name.lower() == CONFIG_FILENAME and entry.is_file():
                    return Path(entry.path)
    except OSError:
        pass
    return None


def read_mod(folder: Path) -> Optional[ModInfo]:
    """Read the mod in folder, or return None if it has no workshopconfig.ini."""
    folder = Path(folder)
    config_path = find_config_file(folder)
    if config_path is None:
        return None
    try:
        text, _ = decode_config(config_path.read_bytes())
    except OSError as e:
        return ModInfo(folder.name, folder, config_path,
                       error=f'Could not read {config_path.name}: {e.strerror or e}')
    return ModInfo(folder.name, folder, config_path, **asdict(parse_config(text)))


def scan_mods(workshop: Path) -> List[ModInfo]:
    workshop = Path(workshop)
    if not workshop.is_dir():
        raise FileNotFoundError(f'Workshop folder not found: {workshop}')
    mods = []
    for entry in workshop.iterdir():
        if entry.is_dir():
            mod = read_mod(entry)
            if mod is not None:
                mods.append(mod)
    mods.sort(key=lambda m: (m.item_type.lower(), m.folder.lower()))
    return mods


def apply_owner_id(mod: ModInfo, owner_id: str) -> ModInfo:
    """Write owner_id into the mod's config and return the mod as it now is on disk."""
    if not is_valid_owner_id(owner_id):
        raise ValueError(f'Owner ID must contain only digits, got {owner_id!r}')
    raw = mod.config_path.read_bytes()
    text, encoding = decode_config(raw)
    new_text = set_owner_id(text, owner_id)
    if new_text != text:
        mod.config_path.write_bytes(new_text.encode(encoding))
    updated = read_mod(mod.path)
    if updated is None:
        raise FileNotFoundError(f'{CONFIG_FILENAME} disappeared from {mod.path}')
    return updated


def normalize_name(name: str) -> str:
    return re.sub(r'[\W_]+', '', name.casefold())


class InstalledIndex:
    """Answers "is this catalogue mod already installed?" by Steam ID or exact name."""

    def __init__(self, mods: Iterable[ModInfo]):
        self._names = set()
        self._ids = set()
        for mod in mods:
            name = normalize_name(mod.item_name)
            if name:
                self._names.add(name)
            if mod.item_id:
                self._ids.add(mod.item_id)
            if mod.folder.isdigit():
                self._ids.add(mod.folder)

    def contains(self, name: str = '', steam_id: Optional[str] = None) -> bool:
        if steam_id and steam_id in self._ids:
            return True
        normalized = normalize_name(name or '')
        return bool(normalized) and normalized in self._names
