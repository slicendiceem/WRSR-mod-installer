"""Downloading mod archives, including through modsbase.com's download pages."""

from __future__ import annotations

import math
import re
import time
import zipfile
from contextlib import suppress
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Dict, List, Optional
from urllib.parse import unquote, urljoin, urlparse

import requests

from .cancel import CancelToken

CHUNK_SIZE = 64 * 1024
TIMEOUT = (15, 60)
DEFAULT_COUNTDOWN = 5  # modsbase's usual wait, for pages that don't say
MAX_COUNTDOWN = 60


@dataclass(frozen=True)
class Progress:
    stage: str           # 'preparing' or 'downloading'
    percent: int = -1    # -1 when unknown
    detail: str = ''


ProgressCallback = Callable[[Progress], None]


class DownloadError(Exception):
    """The download failed; the message is meant for the user."""


class ManualDownloadRequired(DownloadError):
    """The download page didn't work as expected; the user can finish it in a browser."""

    def __init__(self, message: str, page_url: str):
        super().__init__(message)
        self.page_url = page_url


def is_modsbase_page(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.netloc.endswith('modsbase.com') and parsed.path.endswith('.html')


def format_size(size: int) -> str:
    if size < 1024 ** 2:
        return f'{size / 1024:.0f} KB'
    if size < 1024 ** 3:
        return f'{size / 1024 ** 2:.1f} MB'
    return f'{size / 1024 ** 3:.2f} GB'


def download_file(url: str, dest, progress: ProgressCallback, cancel: CancelToken) -> Path:
    """Download a mod archive to dest; removes dest again if anything goes wrong."""
    dest = Path(dest)
    progress = _Throttled(progress)
    try:
        with requests.Session() as session:
            if is_modsbase_page(url):
                download_from_modsbase(url, dest, progress, cancel, session)
            else:
                _save(_request(session, 'GET', url), dest, progress, cancel)
        _check_archive(dest)
    except BaseException:
        with suppress(OSError):
            dest.unlink()
        raise
    return dest


# --- modsbase.com -------------------------------------------------------------

def download_from_modsbase(page_url: str, dest, progress: ProgressCallback, cancel: CancelToken,
                           session: Optional[requests.Session] = None) -> None:
    """Do what a visitor does: open the page, wait out its countdown, press its Download
    button (which submits the page's form) and save the file that comes back."""
    dest = Path(dest)
    session = session or requests.Session()
    progress(Progress('preparing', 5, 'Opening the download page'))
    page = _request(session, 'GET', page_url, page_url=page_url)
    form = _download_form(page.text)
    if form is None:
        raise ManualDownloadRequired("modsbase's page didn't show its usual Download button. "
                                     'Open the page to download the mod yourself.', page_url)
    _wait_countdown(_countdown(page.text), progress, cancel)

    progress(Progress('preparing', 90, 'Asking modsbase for the file'))
    target = urljoin(page_url, form.action) if form.action else page_url
    headers = {'Referer': page_url}
    if form.method == 'post':
        answer = _request(session, 'POST', target, page_url=page_url, data=form.fields, headers=headers)
    else:
        answer = _request(session, 'GET', target, page_url=page_url, params=form.fields, headers=headers)
    if _is_file(answer):
        _save(answer, dest, progress, cancel)
        return
    link = _file_link(answer.text, answer.url)
    if link is None:
        raise ManualDownloadRequired("modsbase didn't give a download link. "
                                     'Open the page to download the mod yourself.', page_url)
    _save(_request(session, 'GET', link, page_url=page_url, headers=headers), dest, progress, cancel)


@dataclass
class _Form:
    action: str
    method: str
    fields: Dict[str, str] = field(default_factory=dict)
    name: str = ''


class _FormParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.forms: List[_Form] = []
        self._current: Optional[_Form] = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'form':
            self._current = _Form(action=attrs.get('action') or '', method=(attrs.get('method') or 'get').lower(),
                                  name=attrs.get('name') or '')
            self.forms.append(self._current)
        elif tag == 'input' and self._current is not None and attrs.get('name') \
                and (attrs.get('type') or 'text').lower() not in ('submit', 'button', 'image', 'reset'):
            self._current.fields[attrs['name']] = attrs.get('value') or ''

    def handle_endtag(self, tag):
        if tag == 'form':
            self._current = None


def _download_form(page_html: str) -> Optional[_Form]:
    """The form behind the Download button: the one modsbase names F1, or that carries op=download…"""
    parser = _FormParser()
    parser.feed(page_html)
    for form in parser.forms:
        if form.name == 'F1' or form.fields.get('op', '').startswith('download'):
            return form
    return None


def _countdown(page_html: str) -> int:
    match = re.search(r'data-total="(\d+)"', page_html) or re.search(r'id="seconds"[^>]*>\s*(\d+)', page_html)
    seconds = int(match.group(1)) if match else DEFAULT_COUNTDOWN
    return max(0, min(seconds, MAX_COUNTDOWN))


def _wait_countdown(seconds: int, progress: ProgressCallback, cancel: CancelToken) -> None:
    end = time.monotonic() + seconds
    while True:
        cancel.check()
        left = end - time.monotonic()
        if left <= 0:
            return
        done = (seconds - left) / seconds if seconds else 1
        progress(Progress('preparing', 10 + int(done * 75), f'Waiting {math.ceil(left)} s, as the page asks'))
        time.sleep(min(0.2, left))


def _is_file(response: requests.Response) -> bool:
    disposition = response.headers.get('Content-Disposition', '').lower()
    content_type = response.headers.get('Content-Type', '').lower()
    return 'attachment' in disposition or not content_type.startswith('text/html')


class _LinkParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: List[tuple] = []  # (href, set of classes)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'a' and attrs.get('href'):
            self.links.append((attrs['href'], set((attrs.get('class') or '').split())))


def _file_link(page_html: str, base_url: str) -> Optional[str]:
    """The link to the file on the page modsbase shows after the form.

    That's its "Download File" button (class dl2-btn): a signed storage link whose path has
    no file name, only its query does. Failing that, any link to a .zip.
    """
    parser = _LinkParser()
    parser.feed(page_html)
    links = [(urljoin(base_url, href), classes) for href, classes in parser.links]
    for url, classes in links:
        if 'dl2-btn' in classes:
            return url
    for url, _ in links:
        parsed = urlparse(url)
        if '.zip' in unquote(f'{parsed.path}?{parsed.query}').lower() and not parsed.path.lower().endswith('.html'):
            return url
    return None


# --- plain HTTP ---------------------------------------------------------------

def _request(session: requests.Session, method: str, url: str, page_url: Optional[str] = None,
             **kwargs) -> requests.Response:
    """Send a request; errors become messages for the user. Responses are streamed, so large
    files aren't read into memory."""
    try:
        response = session.request(method, url, stream=True, timeout=TIMEOUT, **kwargs)
    except requests.Timeout as e:
        raise DownloadError('The download server stopped responding.') from e
    except requests.RequestException as e:
        raise DownloadError("Couldn't connect to the download server.") from e
    if response.ok:
        return response
    if page_url is not None:  # an error page from modsbase, maybe a check meant for browsers
        raise ManualDownloadRequired(f'modsbase answered with an error ({response.status_code}). '
                                     'Open the page to download the mod yourself.', page_url)
    raise DownloadError(f'The download server returned an error ({response.status_code}).')


def _save(response: requests.Response, dest: Path, progress: ProgressCallback, cancel: CancelToken) -> None:
    progress(Progress('downloading', 0))
    total = int(response.headers.get('Content-Length') or 0) or None
    done = 0
    try:
        with open(dest, 'wb') as f:
            for chunk in response.iter_content(CHUNK_SIZE):
                cancel.check()
                f.write(chunk)
                done += len(chunk)
                progress(_download_progress(done, total))
    except requests.RequestException as e:
        raise DownloadError('The download was interrupted. Try again.') from e
    finally:
        response.close()
    progress(Progress('downloading', 100, format_size(done)))


def _check_archive(path: Path) -> None:
    if zipfile.is_zipfile(path):
        return
    with open(path, 'rb') as f:
        head = f.read(1024).lower()
    if b'<html' in head or b'<!doctype' in head:
        raise DownloadError('The server sent a web page instead of the mod archive. '
                            'The download link may have expired; try again.')
    raise DownloadError('The downloaded file is not a ZIP archive, and only ZIP mods can be installed.')


def _download_progress(done: int, total: Optional[int]) -> Progress:
    if not total:
        return Progress('downloading', -1, format_size(done))
    return Progress('downloading', min(100, done * 100 // total), f'{format_size(done)} of {format_size(total)}')


class _Throttled:
    """Passes progress on when the stage or percentage changes, at most every 0.2 s otherwise."""

    def __init__(self, callback: ProgressCallback, interval: float = 0.2):
        self._callback = callback
        self._interval = interval
        self._last = None
        self._last_time = 0.0

    def __call__(self, progress: Progress) -> None:
        now = time.monotonic()
        last = self._last
        if last is None or (progress.stage, progress.percent) != (last.stage, last.percent) \
                or now - self._last_time >= self._interval:
            self._last, self._last_time = progress, now
            self._callback(progress)
