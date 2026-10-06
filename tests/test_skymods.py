from pathlib import Path

import pytest
import requests

from conftest import Route
from wrsr_installer import skymods
from wrsr_installer.cache import PageCache
from wrsr_installer.skymods import (
    CatalogueMod,
    Prerequisite,
    SearchPage,
    SkymodsError,
    fetch_mod,
    get_html,
    parse_mod_page,
    parse_search_page,
    pick_by_steam_id,
    sanitize_description,
    saved_mod,
    saved_search,
    search,
    search_request,
)

FIXTURES = Path(__file__).parent / 'fixtures'


def counted(*bodies):
    """A response that records each request and answers with the next body (the last one repeats)."""
    hits = []

    def body():
        hits.append(1)
        return [bodies[min(len(hits), len(bodies)) - 1].encode('utf-8')]
    return body, hits


@pytest.fixture
def saved_pages(tmp_path, monkeypatch):
    cache = PageCache(tmp_path / 'cache')
    monkeypatch.setattr(skymods, '_cache', cache)
    return cache


@pytest.fixture
def local_skymods(web, monkeypatch):
    monkeypatch.setattr(skymods, 'BASE_URL', web.url('').rstrip('/'))
    return web


def load(name):
    return (FIXTURES / name).read_text(encoding='utf-8')


def prepared_url(term, page):
    url, params = search_request(term, page)
    return requests.Request('GET', url, params=params).prepare().url


# --- search requests --------------------------------------------------------

def test_search_request_encodes_special_characters():
    # Bug 7: "&" used to split the query string.
    assert prepared_url('Roads & Rails', 1) == \
        'https://catalogue.smods.ru/?s=Roads+%26+Rails&app=784150'


def test_search_request_uses_page_path_after_first_page():
    assert prepared_url('tram', 3) == 'https://catalogue.smods.ru/page/3?s=tram&app=784150'


# --- search results ---------------------------------------------------------

def test_parse_search_page_reads_result_fields():
    first = parse_search_page(load('skymods_search.html')).mods[0]

    assert first.name == 'Tram Depot – Large'
    assert first.url == 'https://catalogue.smods.ru/archives/500001'
    assert first.post_id == '500001'
    assert first.steam_id == '3100000001'
    assert first.download_url == 'https://modsbase.com/abc123/3100000001_Tram_Depot.zip.html'
    assert first.image_url == ('https://steamuserimages-a.akamaihd.net/ugc/111/AAA/'
                               '?imw=5000&imh=5000&ima=fit&output-format=jpeg')
    assert first.categories == ['Building', 'Citizen facility']
    assert first.author == 'Example Author'
    assert first.file_size == '38.09 MB'
    assert first.details_loaded is False


def test_parse_search_page_handles_result_without_download_or_image():
    second = parse_search_page(load('skymods_search.html')).mods[1]
    assert (second.name, second.download_url, second.image_url, second.steam_id) == \
        ('Tram Stop', None, None, '3100000002')


def test_parse_search_page_reads_download_of_mod_with_requirements():
    mods = parse_search_page(load('skymods_search.html')).mods
    assert mods[2].download_url == 'https://modsbase.com/ghi789/3100000006_Tram_Depot_Skins.zip.html'
    assert mods[2].has_requirements is True
    assert mods[0].has_requirements is False


def test_parse_mod_page_flags_requirements():
    mod = parse_mod_page(load('skymods_mod.html'), 'https://catalogue.smods.ru/archives/500003')
    assert mod.has_requirements is True


def test_parse_search_page_detects_next_page():
    assert parse_search_page(load('skymods_search.html')).has_next is True


def test_parse_search_page_last_page_has_no_next():
    html = load('skymods_search.html').replace(
        '<a href="https://catalogue.smods.ru/page/2?s=tram&#038;app=784150" >Next Page &raquo;</a>', '')
    assert parse_search_page(html).has_next is False


def test_parse_search_page_without_results():
    html = ('<div class="notebox">For the term "<span>zz</span>". Please try another search:'
            '</div><nav class="pagination group"><ul class="group"></ul></nav>')
    assert parse_search_page(html) == SearchPage(mods=[], has_next=False)


# --- mod pages --------------------------------------------------------------

def test_parse_mod_page_reads_details():
    mod = parse_mod_page(load('skymods_mod.html'), 'https://catalogue.smods.ru/archives/500003')

    assert mod.name == 'Panel Housing Skins & Extras'
    assert mod.url == 'https://catalogue.smods.ru/archives/500003'
    assert mod.post_id == '500003'
    assert mod.steam_id == '3100000003'
    assert mod.image_url == 'https://steamuserimages-a.akamaihd.net/ugc/333/CCC/?imw=5000&imh=5000'
    assert mod.download_url == 'https://modsbase.com/def456/3100000003_Panel_Housing_Skins.zip.html'
    assert mod.author == 'Comrade Builder'
    assert mod.file_size == '3.29 MB'
    assert mod.updated == '17 Oct, 2021 at 13:43 UTC'
    assert mod.details_loaded is True


def test_parse_mod_page_lists_required_items():
    mod = parse_mod_page(load('skymods_mod.html'), 'https://catalogue.smods.ru/archives/500003')
    assert mod.prerequisites == [
        Prerequisite('Panel Housing Base', '3100000004'),
        Prerequisite('Shared Textures', '3100000005'),
    ]


def test_parse_mod_page_keeps_description_formatting_but_drops_page_chrome():
    # The old parser stripped all formatting and swallowed the "Download" button text.
    mod = parse_mod_page(load('skymods_mod.html'), 'https://catalogue.smods.ru/archives/500003')
    assert mod.description_html == (
        '<p>New skins for the panel housing blocks.</p>'
        '<h3>Contents</h3>'
        '<p>Five skins<br>Two colour variants &amp; a '
        '<a href="https://example.com/guide">guide</a></p>'
    )


# --- sanitize_description ---------------------------------------------------

def test_sanitize_description_drops_unsafe_links_but_keeps_text():
    assert sanitize_description('<p><a href="javascript:alert(1)">click</a></p>') == '<p>click</p>'


def test_sanitize_description_unwraps_encoded_steam_link_filter():
    html = '<p><a href="https://steamcommunity.com/linkfilter/?u=https%3A%2F%2Fko-fi.com%2Fexample">tips</a></p>'
    assert sanitize_description(html) == '<p><a href="https://ko-fi.com/example">tips</a></p>'


def test_sanitize_description_drops_links_left_empty_by_removed_images():
    html = '<p><a href="https://example.com"><img src="https://i.example/banner.png" /></a></p><p>Text</p>'
    assert sanitize_description(html) == '<p>Text</p>'


def test_sanitize_description_escapes_text():
    assert sanitize_description('<p>1 &lt; 2 &amp; <i>x</i></p>') == '<p>1 &lt; 2 &amp; <i>x</i></p>'


# --- prerequisite lookup ----------------------------------------------------

def test_pick_by_steam_id_requires_exact_match():
    page = parse_search_page(load('skymods_search.html'))
    assert pick_by_steam_id(page, '3100000002').name == 'Tram Stop'
    assert pick_by_steam_id(page, '999') is None


# --- merging details into a search result -----------------------------------

def test_merge_details_fills_in_page_data_and_keeps_search_only_fields():
    result = CatalogueMod(name='Tram', url='u', steam_id='1', image_url='thumb.jpg',
                          categories=['Road'])
    details = CatalogueMod(name='Tram', url='u', steam_id='1', description_html='<p>d</p>',
                           prerequisites=[Prerequisite('Base', '2')], details_loaded=True)

    result.merge_details(details)

    assert result.description_html == '<p>d</p>'
    assert result.prerequisites == [Prerequisite('Base', '2')]
    assert result.image_url == 'thumb.jpg'
    assert result.categories == ['Road']
    assert result.details_loaded is True


def test_fill_from_only_fills_gaps_so_fresh_listing_data_wins():
    listing = CatalogueMod(name='Tram', url='u', steam_id='1', download_url='https://modsbase.com/new.zip.html')
    saved = CatalogueMod(name='Tram', url='u', steam_id='1', download_url='https://modsbase.com/old.zip.html',
                         description_html='<p>d</p>', prerequisites=[Prerequisite('Base', '2')],
                         details_loaded=True)

    listing.fill_from(saved)

    assert listing.download_url == 'https://modsbase.com/new.zip.html'
    assert listing.description_html == '<p>d</p>'
    assert listing.prerequisites == [Prerequisite('Base', '2')]
    assert listing.details_loaded is True


# --- HTTP errors ------------------------------------------------------------

def test_get_html_returns_page_text(web):
    web.route('/', Route(body='<p>Привет</p>'))
    assert get_html(web.url('/')) == '<p>Привет</p>'


def test_get_html_turns_timeouts_into_readable_errors(web, monkeypatch):
    monkeypatch.setattr(skymods, 'TIMEOUT', (2, 0.2))
    web.route('/', Route(body='late', delay=1.0))
    with pytest.raises(SkymodsError, match='too long'):
        get_html(web.url('/'))


def test_get_html_explains_cloudflares_browser_check(web):
    web.route('/', Route(body='<html><title>Just a moment...</title></html>', status=403,
                         headers={'Content-Type': 'text/html', 'cf-mitigated': 'challenge'}))
    with pytest.raises(SkymodsError, match='browser check'):
        get_html(web.url('/'))


def test_get_html_reports_http_status(web):
    web.route('/', Route(body='missing', status=404))
    with pytest.raises(SkymodsError, match='404'):
        get_html(web.url('/'))


# --- saved pages ------------------------------------------------------------

def test_get_html_reuses_a_recently_saved_page(web, saved_pages):
    body, hits = counted('<p>hi</p>')
    web.route('/page', Route(body=body))

    assert get_html(web.url('/page'), fresh_for=60) == '<p>hi</p>'
    assert get_html(web.url('/page'), fresh_for=60) == '<p>hi</p>'
    assert len(hits) == 1


def test_get_html_without_fresh_for_asks_again_and_saves_the_new_page(web, saved_pages):
    body, hits = counted('<p>one</p>', '<p>two</p>')
    web.route('/page', Route(body=body))

    assert get_html(web.url('/page')) == '<p>one</p>'
    assert get_html(web.url('/page')) == '<p>two</p>'
    assert get_html(web.url('/page'), fresh_for=60) == '<p>two</p>'
    assert len(hits) == 2


def test_saved_search_reads_the_saved_results_without_asking(local_skymods, saved_pages):
    body, hits = counted(load('skymods_search.html'))
    local_skymods.route('/', Route(body=body))
    search('tram')

    page, age = saved_search('tram')

    assert [m.name for m in page.mods][:1] == ['Tram Depot – Large']
    assert age < 60
    assert saved_search('bus') is None
    assert len(hits) == 1


def test_fetch_mod_reuses_a_mod_page_saved_today(local_skymods, saved_pages):
    body, hits = counted(load('skymods_mod.html'))
    local_skymods.route('/archives/500003', Route(body=body))
    url = local_skymods.url('/archives/500003')

    fetch_mod(url)
    details, age = saved_mod(url)
    again = fetch_mod(url)

    assert details.name == again.name == 'Panel Housing Skins & Extras'
    assert len(hits) == 1


def test_without_a_cache_nothing_is_saved(local_skymods, monkeypatch):
    monkeypatch.setattr(skymods, '_cache', None)
    body, hits = counted(load('skymods_search.html'))
    local_skymods.route('/', Route(body=body))

    search('tram')

    assert saved_search('tram') is None
