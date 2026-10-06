import io
import time
import zipfile
from urllib.parse import parse_qs

import pytest

from conftest import Route
from wrsr_installer.cancel import Cancelled, CancelToken
from wrsr_installer.downloader import (
    DownloadError,
    ManualDownloadRequired,
    download_file,
    download_from_modsbase,
    is_modsbase_page,
)


def zip_bytes(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buffer.getvalue()


MOD_ZIP = zip_bytes({'Mod/workshopconfig.ini': '$ITEM_NAME "Mod"\n' + 'x' * 300_000})
ZIP_HEADERS = {'Content-Type': 'application/zip',
               'Content-Disposition': 'attachment; filename="3100000001_Mod.zip"'}


# --- direct downloads -------------------------------------------------------

def test_download_file_saves_archive_and_finishes_at_100_percent(web, tmp_path):
    web.route('/mod.zip', Route(body=MOD_ZIP, headers=ZIP_HEADERS))
    events = []

    dest = download_file(web.url('/mod.zip'), tmp_path / 'download.zip', events.append, CancelToken())

    assert dest.read_bytes() == MOD_ZIP
    assert (events[-1].stage, events[-1].percent) == ('downloading', 100)


def test_download_file_rejects_web_page_instead_of_archive(web, tmp_path):
    web.route('/mod.zip', Route(body='<!DOCTYPE html><html><body>Link expired</body></html>'))
    dest = tmp_path / 'download.zip'

    with pytest.raises(DownloadError, match='web page'):
        download_file(web.url('/mod.zip'), dest, lambda p: None, CancelToken())

    assert not dest.exists()


def test_download_file_reports_http_errors(web, tmp_path):
    web.route('/mod.zip', Route(body='gone', status=404))
    with pytest.raises(DownloadError, match='404'):
        download_file(web.url('/mod.zip'), tmp_path / 'download.zip', lambda p: None, CancelToken())


def test_download_file_can_be_cancelled_midway(web, tmp_path):
    def slow_body():
        for _ in range(200):
            yield b'x' * 65536
            time.sleep(0.02)

    web.route('/big.zip', Route(body=slow_body, headers={'Content-Type': 'application/zip',
                                                         'Content-Length': str(200 * 65536)}))
    token = CancelToken()
    dest = tmp_path / 'download.zip'

    def cancel_once_started(progress):
        if progress.percent > 0:
            token.cancel()

    with pytest.raises(Cancelled):
        download_file(web.url('/big.zip'), dest, cancel_once_started, token)

    assert not dest.exists()


@pytest.mark.parametrize('url, expected', [
    ('https://modsbase.com/el1fnzkuuerz/3043462563_Old_town_squares.zip.html', True),
    ('https://modsbase.com/files/abc/3043462563_Old_town_squares.zip', False),
    ('https://example.com/mod.zip', False),
])
def test_is_modsbase_page(url, expected):
    assert is_modsbase_page(url) is expected


# --- modsbase.com download pages (a local imitation of the real flow) -------

def modsbase_page(countdown):
    """Mirrors modsbase's markup: a form named F1, a countdown, and a button that a script
    reveals when the countdown ends and that submits the form."""
    return f'''<!DOCTYPE html><html><head><title>Download 3100000001 Mod zip</title></head><body>
<form name="F1" method="POST" action="">
  <input type="hidden" name="op" value="download2">
  <input type="hidden" name="id" value="abc123">
  <input type="hidden" name="rand" value="">
  <input type="hidden" name="referer" value="">
  <div id="countdown" class="dl-countdown" data-total="{countdown}">
    <div class="dl-countdown-text">Wait <b id="seconds">{countdown}</b> seconds</div>
  </div>
  <button id="downloadbtn" class="btn btn-primary download-btn downloadbtn dl-waiting">Download File</button>
</form>
<script>$('#downloadbtn').click(function() {{ this.form.submit(); }});</script>
</body></html>'''


# Mirrors modsbase's answer to the form: a signed storage link whose path has no ".zip";
# the file name is only in the query string.
FILE_PAGE = '''<!DOCTYPE html><html><head><title>Modsbase.com - Easy way to share your files</title></head><body>
<a href="/upload/" class="logo">Upload</a>
<a class="dropdown-item" href="/change_lang?lang=german">Deutsch</a>
<a href="/abc123/Mod.zip.html">Back to the file page</a>
<a href="/report_file?file=3100000001_Mod.zip&amp;id=abc123">Report this file</a>
<div class="dl2-zone">
  <h2>File Download Link Generated</h2>
  <div class="dl2-file-info"><b>3100000001_Mod.zip</b> — <span class="dl2-fsize">1.0 MB</span></div>
  <div class="dl2-expire">This direct link will be available for your IP next 2 hours</div>
  <a class="dl2-btn" href="/uploads/00292/abc123?response-content-disposition=attachment%3B%20filename%3D%223100000001_Mod.zip%22&amp;X-Amz-Expires=7200&amp;X-Amz-Signature=0123abcd">
    <span class="dl2-btn-text"><span class="dl2-btn-label">Download File</span></span></a>
</div>
<a class="nav-link" href="/pages/faq/">FAQ</a>
</body></html>'''

# An older layout, where the file link has the name in its path.
PLAIN_FILE_PAGE = '''<html><body><a href="/abc123/Mod.zip.html">Back</a>
<a class="btn" href="/uploads/00292/abc123/3100000001_Mod.zip">DOWNLOAD FILE</a></body></html>'''

PAGE_PATH = '/abc123/Mod.zip.html'
FILE_PATH = '/uploads/00292/abc123'


def serve_modsbase(web, countdown=1, after_form=FILE_PAGE):
    web.route(PAGE_PATH, Route(body=modsbase_page(countdown)), method='GET')
    web.route(PAGE_PATH, Route(body=after_form) if isinstance(after_form, str) else after_form, method='POST')
    web.route(FILE_PATH, Route(body=MOD_ZIP, headers=ZIP_HEADERS))
    web.route(FILE_PATH + '/3100000001_Mod.zip', Route(body=MOD_ZIP, headers=ZIP_HEADERS))
    return web.url(PAGE_PATH)


def test_modsbase_download_waits_out_the_countdown_then_submits_the_form(web, tmp_path):
    page_url = serve_modsbase(web, countdown=1)
    events = []

    download_from_modsbase(page_url, tmp_path / 'download.zip', events.append, CancelToken())

    assert (tmp_path / 'download.zip').read_bytes() == MOD_ZIP
    opened, submitted = [r for r in web.requests if r.path == PAGE_PATH]
    assert submitted.method == 'POST'
    assert parse_qs(submitted.body, keep_blank_values=True) == \
        {'op': ['download2'], 'id': ['abc123'], 'rand': [''], 'referer': ['']}
    assert submitted.time - opened.time >= 1.0
    assert (events[-1].stage, events[-1].percent) == ('downloading', 100)


def test_modsbase_download_finds_the_storage_link_even_if_the_button_is_renamed(web, tmp_path):
    renamed = FILE_PAGE.replace('class="dl2-btn"', 'class="download-button"').replace(
        '<a href="/report_file?file=3100000001_Mod.zip&amp;id=abc123">Report this file</a>', '')
    page_url = serve_modsbase(web, countdown=0, after_form=renamed)

    download_from_modsbase(page_url, tmp_path / 'download.zip', lambda p: None, CancelToken())

    assert (tmp_path / 'download.zip').read_bytes() == MOD_ZIP


def test_modsbase_download_also_follows_links_with_the_file_name_in_the_path(web, tmp_path):
    page_url = serve_modsbase(web, countdown=0, after_form=PLAIN_FILE_PAGE)

    download_from_modsbase(page_url, tmp_path / 'download.zip', lambda p: None, CancelToken())

    assert (tmp_path / 'download.zip').read_bytes() == MOD_ZIP


def test_modsbase_file_sent_straight_back_after_the_form_is_saved(web, tmp_path):
    page_url = serve_modsbase(web, countdown=0, after_form=Route(body=MOD_ZIP, headers=ZIP_HEADERS))

    download_from_modsbase(page_url, tmp_path / 'download.zip', lambda p: None, CancelToken())

    assert (tmp_path / 'download.zip').read_bytes() == MOD_ZIP


def test_modsbase_download_can_be_cancelled_during_the_countdown(web, tmp_path):
    page_url = serve_modsbase(web, countdown=30)
    token = CancelToken()
    started = time.monotonic()

    def cancel_while_waiting(progress):
        if 'Wait' in progress.detail:
            token.cancel()

    with pytest.raises(Cancelled):
        download_from_modsbase(page_url, tmp_path / 'download.zip', cancel_while_waiting, token)

    assert time.monotonic() - started < 5
    assert [r.method for r in web.requests] == ['GET']


def test_modsbase_browser_check_is_handed_to_the_user(web, tmp_path):
    web.route(PAGE_PATH, Route(body='<html><title>Just a moment...</title></html>', status=403,
                               headers={'Content-Type': 'text/html', 'cf-mitigated': 'challenge'}))
    page_url = web.url(PAGE_PATH)

    with pytest.raises(ManualDownloadRequired) as raised:
        download_from_modsbase(page_url, tmp_path / 'download.zip', lambda p: None, CancelToken())

    assert raised.value.page_url == page_url


def test_modsbase_page_without_its_download_form_is_handed_to_the_user(web, tmp_path):
    web.route(PAGE_PATH, Route(body='<html><title>Download</title><body>File is being processed</body></html>'))
    page_url = web.url(PAGE_PATH)

    with pytest.raises(ManualDownloadRequired) as raised:
        download_from_modsbase(page_url, tmp_path / 'download.zip', lambda p: None, CancelToken())

    assert raised.value.page_url == page_url
    assert 'captcha' not in str(raised.value).lower()


def test_modsbase_answer_without_a_file_link_is_handed_to_the_user(web, tmp_path):
    page_url = serve_modsbase(web, countdown=0, after_form='<html><body>Wrong IP</body></html>')

    with pytest.raises(ManualDownloadRequired) as raised:
        download_from_modsbase(page_url, tmp_path / 'download.zip', lambda p: None, CancelToken())

    assert raised.value.page_url == page_url
