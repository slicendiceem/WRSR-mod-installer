"""Saved settings: the game folder and the Owner ID to apply to mods."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

# Same file and keys as earlier versions, so existing settings carry over.
CONFIG_FILE = Path.home() / '.wrsr_mod_installer_config.json'


@dataclass
class AppConfig:
    game_folder: Optional[str] = None
    target_owner_id: Optional[str] = None


def _text(value) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def load_config(path: Path = CONFIG_FILE) -> AppConfig:
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return AppConfig()
    if not isinstance(data, dict):
        return AppConfig()
    return AppConfig(game_folder=_text(data.get('game_folder')),
                     target_owner_id=_text(data.get('target_owner_id')))


def save_config(config: AppConfig, path: Path = CONFIG_FILE) -> None:
    # json.dumps escapes non-ASCII characters, so any folder name is stored safely.
    Path(path).write_text(json.dumps(asdict(config), indent=2), encoding='utf-8')
