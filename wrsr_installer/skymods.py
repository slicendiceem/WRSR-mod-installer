"""Searching the Skymods catalogue (catalogue.smods.ru) and reading its mod pages."""

from __future__ import annotations

import html as html_lib
import re
import threading
from dataclasses import dataclass, field, fields
from html.parser import HTMLParser
from typing import List, Optional, Tuple
from urllib.parse import unquote, urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .cache import CachedPage, PageCache

BASE_URL = 'https://catalogue.smods.ru'
APP_ID = '784150'  # Workers & Resources: Soviet Republic on Steam
# (connect, read) seconds. Pages the site hasn't cached can take about a minute.
TIMEOUT = (15, 120)


@dataclass
class Prerequisite:
    name: str
    steam_id: Optional[str]


@dataclass
class CatalogueMod:
    name: str
    url: str
    post_id: Optional[str] = None
    steam_id: Optional[str] = None
    download_url: Optional[str] = None
    image_url: Optional[str] = None
    categories: List[str] = field(default_factory=list)
    author: str = ''
    file_size: str = ''
    updated: str = ''
    description_html: str = ''
    prerequisites: List[Prerequisite] = field(default_factory=list)
    has_requirements: bool = False
    details_loaded: bool = False

    @property
    def key(self) -> str:
        """Identifies the mod across search results, queue entries and prerequisites."""
        return self.steam_id or self.url

    def merge_details(self, details: 'CatalogueMod') -> None:
        """Copy everything the mod page knows onto this search result."""
        for f in fields(self):
            value = getattr(details, f.name)
            if value:
                setattr(self, f.name, value)
        self.details_loaded = True

    def fill_from(self, other: 'CatalogueMod') -> None:
        """Copy only what this mod lacks, e.g. an older saved mod page onto a fresh listing."""
        for f in fields(self):
            value = getattr(other, f.name)
            if value and not getattr(self, f.name):
                setattr(self, f.name, value)


@dataclass
class SearchPage:
    mods: List[CatalogueMod]
    has_next: bool


class SkymodsError(Exception):
    """A request to Skymods failed; the message is meant for the user."""


# --- requests ---------------------------------------------------------------

def search_request(term: str, page: int = 1) -> Tuple[str, dict]:
    """URL and query parameters for one page of search results."""
    url = f'{BASE_URL}/' if page <= 1 else f'{BASE_URL}/page/{page}'
    return url, {'s': term, 'app': APP_ID}


_local = threading.local()


def _session() -> requests.Session:
    # One session per thread: requests doesn't promise sessions are thread-safe.
    session = getattr(_local, 'session', None)
    if session is None:
        session = requests.Session()
        # read=False: never re-request after a slow read (the page may just be slow), and
        # let the timeout surface as a Timeout rather than a generic connection error.
        retry = Retry(total=2, connect=2, read=False, status=2, backoff_factor=1.0,
                      status_forcelist=(502, 503, 504), allowed_methods=frozenset({'GET'}))
        session.mount('https://', HTTPAdapter(max_retries=retry))
        session.mount('http://', HTTPAdapter(max_retries=retry))
        _local.session = session
    return session


# Skymods can take a minute per page, so pages are kept on disk (see use_cache). These say
# how old a saved page may be before it is fetched again; older ones can still be shown
# straight away while a fresh copy loads (see saved_search and saved_mod).
SEARCH_FRESH = 10 * 60     # search results; the site's own cache keeps them for 5 minutes
DETAILS_FRESH = 24 * 3600  # mod pages and Steam ID lookups, which rarely change

_cache: Optional[PageCache] = None


def use_cache(cache: Optional[PageCache]) -> None:
    global _cache
    _cache = cache


def page_key(url: str, params: Optional[dict] = None) -> str:
    return requests.Request('GET', url, params=params).prepare().url


def get_html(url: str, params: Optional[dict] = None, fresh_for: float = 0) -> str:
    """The page's HTML; a saved copy younger than fresh_for seconds is used without asking."""
    key = page_key(url, params)
    if _cache is not None and fresh_for > 0:
        saved = _cache.get(key)
        if saved is not None and saved.age <= fresh_for:
            return saved.text
    try:
        response = _session().get(url, params=params, timeout=TIMEOUT)
        response.raise_for_status()
    except requests.Timeout as e:
        raise SkymodsError('Skymods took too long to respond. The site is often slow; '
                           'try again in a minute.') from e
    except requests.HTTPError as e:
        if e.response.headers.get('cf-mitigated') == 'challenge':
            raise SkymodsError("Skymods is putting the app through a browser check right now, so it can't "
                               "load new pages. Searches and mods you've seen before still work. Try again "
                               'later, or browse catalogue.smods.ru in your web browser.') from e
        raise SkymodsError(f'Skymods returned an error ({e.response.status_code}).') from e
    except requests.RequestException as e:
        raise SkymodsError("Couldn't reach Skymods. Check your internet connection.") from e
    if _cache is not None:
        _cache.put(key, response.text)
    return response.text


def _saved_html(url: str, params: Optional[dict] = None) -> Optional[CachedPage]:
    return _cache.get(page_key(url, params)) if _cache is not None else None


def search(term: str, page: int = 1, fresh_for: float = 0) -> SearchPage:
    url, params = search_request(term, page)
    return parse_search_page(get_html(url, params, fresh_for))


def saved_search(term: str, page: int = 1) -> Optional[Tuple[SearchPage, float]]:
    """Saved results for this search and their age in seconds, without asking Skymods."""
    saved = _saved_html(*search_request(term, page))
    return (parse_search_page(saved.text), saved.age) if saved is not None else None


def fetch_mod(url: str, fresh_for: float = DETAILS_FRESH) -> CatalogueMod:
    return parse_mod_page(get_html(url, fresh_for=fresh_for), url)


def saved_mod(url: str) -> Optional[Tuple[CatalogueMod, float]]:
    """A saved copy of the mod page and its age in seconds, without asking Skymods."""
    saved = _saved_html(url)
    return (parse_mod_page(saved.text, url), saved.age) if saved is not None else None


def find_by_steam_id(steam_id: str, fresh_for: float = DETAILS_FRESH) -> Optional[CatalogueMod]:
    return pick_by_steam_id(search(steam_id, fresh_for=fresh_for), steam_id)


def pick_by_steam_id(page: SearchPage, steam_id: str) -> Optional[CatalogueMod]:
    # Searching for an ID can return loosely related mods, so only an exact match counts.
    return next((mod for mod in page.mods if mod.steam_id == steam_id), None)


# --- parsing ----------------------------------------------------------------

_FLAGS = re.S | re.I
_ARTICLE = re.compile(r'<article\b([^>]*)>(.*?)</article>', _FLAGS)
_POST_ID = re.compile(r'\bpost-(\d+)\b')
_TITLE_LINK = re.compile(
    r'class="[^"]*\bpost-title\b[^"]*"[^>]*>\s*<a\s[^>]*?href="([^"]+)"[^>]*>(.*?)</a>', _FLAGS)
_THUMBNAIL = re.compile(r'class="post-thumbnail"[^>]*>.*?<img\s[^>]*?src="([^"]+)"', _FLAGS)
_CATEGORY = re.compile(r'rel="category tag"[^>]*>(.*?)</a>', _FLAGS)
_DOWNLOAD = re.compile(
    r'<a\s[^>]*class="[^"]*\bskymods-excerpt-btn\b[^"]*"[^>]*href="([^"]+)"[^>]*>\s*Download\s*</a>',
    _FLAGS)
_REQUIRED_WARNING = re.compile(r'\bskymods-required-warning\b|#required-items"', re.I)
_STEAM_ID = re.compile(r'steamcommunity\.com/(?:sharedfiles|workshop)/filedetails/\?id=(\d+)', re.I)
_AUTHOR = re.compile(r'Author:\s*(?:</strong>)?\s*<a\s[^>]*>(.*?)</a>', _FLAGS)
_FILE_SIZE = re.compile(r'class="skymods-item-file-size"[^>]*>(.*?)</span>', _FLAGS)
_UPDATED = re.compile(r'class="skymods-item-date"[^>]*>(.*?)</span>', _FLAGS)
_NEXT_PAGE = re.compile(r'<li\s+class="next\b[^"]*"[^>]*>\s*<a\s', re.I)
_PAGE_TITLE = re.compile(r'<h1\s[^>]*class="[^"]*\bpost-title\b[^"]*"[^>]*>(.*?)</h1>', _FLAGS)
_PREVIEW_IMAGE = re.compile(
    r'class="skymods-single-preview-wrap"[^>]*>\s*<img\s[^>]*?src="([^"]+)"', _FLAGS)
_DESCRIPTION_START = re.compile(r'<h5>\s*Description:\s*</h5>', re.I)
_DESCRIPTION_END = re.compile(r'<div\s+class="skymods-single-after"', re.I)
_REQUIRED_SECTION = re.compile(r'<h5>\s*Required items:\s*</h5>(.*?)</div>', _FLAGS)
_REQUIRED_LINK = re.compile(
    r'<a\s[^>]*href="https?://catalogue\.smods\.ru/\?s=(\d+)"[^>]*>(.*?)</a>', _FLAGS)
_TAG = re.compile(r'<[^>]+>')


def _text(fragment: str) -> str:
    return re.sub(r'\s+', ' ', html_lib.unescape(_TAG.sub('', fragment))).strip()


def _first(pattern: re.Pattern, text: str) -> Optional[str]:
    match = pattern.search(text)
    return match.group(1) if match else None


def _first_text(pattern: re.Pattern, text: str) -> str:
    value = _first(pattern, text)
    return _text(value) if value else ''


def _first_url(pattern: re.Pattern, text: str) -> Optional[str]:
    value = _first(pattern, text)
    return html_lib.unescape(value) if value else None


def parse_search_page(page_html: str) -> SearchPage:
    mods = []
    for match in _ARTICLE.finditer(page_html):
        attrs, body = match.groups()
        title = _TITLE_LINK.search(body)
        if not title:
            continue
        mods.append(CatalogueMod(
            name=_text(title.group(2)),
            url=html_lib.unescape(title.group(1)),
            post_id=_first(_POST_ID, attrs),
            steam_id=_first(_STEAM_ID, body),
            download_url=_first_url(_DOWNLOAD, body),
            image_url=_first_url(_THUMBNAIL, body),
            categories=[_text(c) for c in _CATEGORY.findall(body)],
            author=_first_text(_AUTHOR, body),
            file_size=_first_text(_FILE_SIZE, body),
            updated=_first_text(_UPDATED, body),
            has_requirements=bool(_REQUIRED_WARNING.search(body)),
        ))
    return SearchPage(mods=mods, has_next=bool(_NEXT_PAGE.search(page_html)))


def parse_mod_page(page_html: str, url: str) -> CatalogueMod:
    article = _ARTICLE.search(page_html)
    attrs, body = article.groups() if article else ('', page_html)

    desc_start = _DESCRIPTION_START.search(body)
    desc_end = _DESCRIPTION_END.search(body, desc_start.end()) if desc_start else None
    header = body[:desc_start.start()] if desc_start else body
    description = body[desc_start.end():desc_end.start()] if desc_start and desc_end else ''

    required = _REQUIRED_SECTION.search(body)
    prerequisites = [Prerequisite(_text(name), steam_id)
                     for steam_id, name in _REQUIRED_LINK.findall(required.group(1))] if required else []

    return CatalogueMod(
        name=_first_text(_PAGE_TITLE, body),
        url=url,
        post_id=_first(_POST_ID, attrs),
        steam_id=_first(_STEAM_ID, header),
        download_url=_first_url(_DOWNLOAD, body),
        image_url=_first_url(_PREVIEW_IMAGE, body),
        categories=[_text(c) for c in _CATEGORY.findall(body)],
        author=_first_text(_AUTHOR, body),
        file_size=_first_text(_FILE_SIZE, body),
        updated=_first_text(_UPDATED, body),
        description_html=sanitize_description(description),
        prerequisites=prerequisites,
        has_requirements=bool(prerequisites),
        details_loaded=True,
    )


# --- description sanitizing -------------------------------------------------

_VOID_TAGS = {'br', 'img', 'hr', 'input', 'meta', 'link', 'wbr', 'source', 'area', 'col', 'embed'}
_DROP_WITH_CONTENT = {'script', 'style', 'iframe', 'object', 'noscript', 'template', 'form', 'select'}
_DROP_CLASSES = {'bb_link_host'}  # the "[example.com]" note Steam puts after links
_TAG_MAP = {
    'p': 'p', 'blockquote': 'blockquote', 'ul': 'ul', 'ol': 'ol', 'li': 'li',
    'h1': 'h3', 'h2': 'h3', 'h3': 'h4', 'h4': 'h4', 'h5': 'h4', 'h6': 'h4',
    'b': 'b', 'strong': 'b', 'i': 'i', 'em': 'i', 'u': 'u',
}
_DIV_CLASS_MAP = {'bb_h1': 'h3', 'bb_h2': 'h4', 'bb_h3': 'h4'}
_BLOCK_TAGS = {'p', 'blockquote', 'ul', 'ol', 'li', 'h3', 'h4'}
_SKIP = object()


def _safe_href(href: Optional[str]) -> Optional[str]:
    if not href:
        return None
    href = href.strip()
    parsed = urlparse(href)
    if parsed.netloc.endswith('steamcommunity.com') and parsed.path.startswith('/linkfilter'):
        # Steam wraps outside links as /linkfilter/?url=<plain> or ?u=<percent-encoded>.
        for key in ('url=', 'u='):
            if parsed.query.startswith(key):
                href = unquote(parsed.query[len(key):])
                parsed = urlparse(href)
                break
    return href if parsed.scheme in ('http', 'https') and parsed.netloc else None


class _DescriptionSanitizer(HTMLParser):
    """Keeps a small allowlist of formatting tags and plain http(s) links."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: List[str] = []
        self.stack: list = []  # (source tag, emitted tag name, None, or _SKIP)
        self.skipping = 0
        self.blocks = 0

    def handle_starttag(self, tag, attrs):
        if tag in _VOID_TAGS:
            self._void(tag)
            return
        attrs = dict(attrs)
        classes = set((attrs.get('class') or '').split())
        if tag in _DROP_WITH_CONTENT or classes & _DROP_CLASSES:
            self.stack.append((tag, _SKIP))
            self.skipping += 1
            return
        name, markup = self._translate(tag, attrs, classes)
        self.stack.append((tag, name))
        if name and not self.skipping:
            self.out.append(markup)
            if name in _BLOCK_TAGS:
                self.blocks += 1

    def handle_startendtag(self, tag, attrs):
        if tag in _VOID_TAGS:
            self._void(tag)
        else:
            self.handle_starttag(tag, attrs)
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        index = next((i for i in range(len(self.stack) - 1, -1, -1) if self.stack[i][0] == tag), None)
        if index is None:
            return  # stray closing tag
        while len(self.stack) > index:
            _, name = self.stack.pop()
            if name is _SKIP:
                self.skipping -= 1
            elif name and not self.skipping:
                self.out.append(f'</{name}>')
                if name in _BLOCK_TAGS:
                    self.blocks -= 1

    def handle_data(self, data):
        if self.skipping or (not data.strip() and not self.blocks):
            return
        self.out.append(html_lib.escape(re.sub(r'\s+', ' ', data), quote=False))

    def _void(self, tag):
        if tag == 'br' and not self.skipping:
            self.out.append('<br>')

    @staticmethod
    def _translate(tag, attrs, classes):
        if tag == 'a':
            href = _safe_href(attrs.get('href'))
            return ('a', f'<a href="{html_lib.escape(href)}">') if href else (None, None)
        if tag == 'div':
            name = next((_DIV_CLASS_MAP[c] for c in classes if c in _DIV_CLASS_MAP), 'p')
            return name, f'<{name}>'
        name = _TAG_MAP.get(tag)
        return (name, f'<{name}>') if name else (None, None)


def sanitize_description(fragment: str) -> str:
    """Turn a mod description from a Skymods page into safe, simple rich text."""
    parser = _DescriptionSanitizer()
    parser.feed(fragment)
    parser.close()
    result = ''.join(parser.out)
    # Links that only wrapped an image, and blocks left empty, would show as stray gaps.
    empty = re.compile(r'<a href="[^"]*">\s*</a>|<(p|blockquote|ul|ol|li|h3|h4|b|i|u)>\s*</\1>')
    while True:
        cleaned = empty.sub('', result)
        if cleaned == result:
            return cleaned.strip()
        result = cleaned
