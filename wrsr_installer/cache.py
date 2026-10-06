"""Pages saved on disk, so the slow catalogue isn't asked for the same page twice."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import time
import uuid
import zlib
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

DAY = 24 * 3600


@dataclass(frozen=True)
class CachedPage:
    text: str
    age: float  # seconds since the page was saved


class PageCache:
    """A folder of saved pages, keyed by URL. Every failure just means "not saved"."""

    def __init__(self, folder, max_age: float = 7 * DAY, max_entries: int = 400,
                 clock: Callable[[], float] = time.time):
        self.folder = Path(folder)
        self.max_age = max_age
        self.max_entries = max_entries
        self._clock = clock

    def _path(self, key: str) -> Path:
        return self.folder / (hashlib.sha1(key.encode('utf-8')).hexdigest() + '.json.gz')

    def get(self, key: str) -> Optional[CachedPage]:
        try:
            with gzip.open(self._path(key), 'rt', encoding='utf-8') as f:
                saved = json.load(f)
            if saved['key'] != key:
                return None
            age = max(0.0, self._clock() - float(saved['saved']))
            text = saved['text']
        except (OSError, EOFError, ValueError, KeyError, TypeError, zlib.error):
            return None
        return CachedPage(text, age) if age <= self.max_age and isinstance(text, str) else None

    def put(self, key: str, text: str) -> None:
        path = self._path(key)
        temp = path.with_name(f'.{uuid.uuid4().hex}.tmp')
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            with gzip.open(temp, 'wt', encoding='utf-8') as f:
                json.dump({'key': key, 'saved': self._clock(), 'text': text}, f)
            os.replace(temp, path)  # readers never see a half-written page
        except OSError:
            with suppress(OSError):
                temp.unlink()

    def prune(self) -> None:
        """Delete pages past max_age, and all but the newest max_entries."""
        now = time.time()  # file times are real times, whatever clock saved the pages
        try:
            files = list(self.folder.glob('*.json.gz')) + list(self.folder.glob('.*.tmp'))
        except OSError:
            return
        entries = []
        for path in files:
            with suppress(OSError):
                entries.append((path.stat().st_mtime, path))
        entries.sort(reverse=True)
        kept = 0
        for mtime, path in entries:
            keep = path.suffix == '.gz' and now - mtime <= self.max_age and kept < self.max_entries
            if keep:
                kept += 1
            elif path.suffix == '.gz' or now - mtime > DAY:  # leave fresh temp files to their writer
                with suppress(OSError):
                    path.unlink()
