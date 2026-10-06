"""Turning mod descriptions into safe rich text for Qt labels."""

from __future__ import annotations

import html
import re
from urllib.parse import urlparse

_FLAGS = re.S | re.I
_INLINE_TAGS = {'b': 'b', 'i': 'i', 'u': 'u', 'strike': 's'}
_HEADING_TAGS = {'h1': 'h3', 'h2': 'h4', 'h3': 'h4'}
# Steam tags without a useful rich-text equivalent: keep their text, drop the tag.
_UNWRAPPED_TAGS = r'quote|spoiler|code|noparse|table|tr|td|th|hr|previewyoutube'


def _link(href: str, label: str) -> str:
    target = html.unescape(href).strip()
    parsed = urlparse(target)
    if parsed.scheme in ('http', 'https') and parsed.netloc:
        return f'<a href="{html.escape(target, quote=True)}">{label}</a>'
    return label


def _list(match: re.Match, tag: str) -> str:
    items = [item.strip() for item in re.split(r'\[\*\]', match.group(1)) if item.strip()]
    return f'<{tag}>' + ''.join(f'<li>{item}</li>' for item in items) + f'</{tag}>'


def ago(seconds: float) -> str:
    """How long ago, in words: "just now", "5 minutes ago", "2 days ago"."""
    for unit, size in (('day', 86400), ('hour', 3600), ('minute', 60)):
        count = int(seconds // size)
        if count:
            return f'{count} {unit}{"s" if count != 1 else ""} ago'
    return 'just now'


def format_bbcode(text: str) -> str:
    """Convert Steam-style BBCode (as used in workshopconfig.ini) into simple, safe HTML."""
    out = html.escape(text, quote=True).replace('\r\n', '\n').replace('\r', '\n')
    out = re.sub(r'\[img\].*?\[/img\]', '', out, flags=_FLAGS)
    out = re.sub(r'\[url=([^\]]+)\](.*?)\[/url\]', lambda m: _link(m.group(1), m.group(2)), out, flags=_FLAGS)
    out = re.sub(r'\[url\](.*?)\[/url\]', lambda m: _link(m.group(1), m.group(1)), out, flags=_FLAGS)
    for tag, html_tag in _HEADING_TAGS.items():
        out = re.sub(rf'\s*\[{tag}\](.*?)\[/{tag}\]\s*', rf'<{html_tag}>\1</{html_tag}>', out, flags=_FLAGS)
    for tag, html_tag in _INLINE_TAGS.items():
        out = re.sub(rf'\[{tag}\](.*?)\[/{tag}\]', rf'<{html_tag}>\1</{html_tag}>', out, flags=_FLAGS)
    out = re.sub(r'\s*\[list\](.*?)\[/list\]\s*', lambda m: _list(m, 'ul'), out, flags=_FLAGS)
    out = re.sub(r'\s*\[olist\](.*?)\[/olist\]\s*', lambda m: _list(m, 'ol'), out, flags=_FLAGS)
    out = re.sub(rf'\[/?(?:{_UNWRAPPED_TAGS})(?:=[^\]]*)?\]', '', out, flags=re.I)
    return out.strip().replace('\n', '<br>')
