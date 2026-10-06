import threading
from pathlib import Path

import pytest
from PyQt5.QtCore import QThreadPool, Qt
from PyQt5.QtWidgets import QApplication

from wrsr_installer.app_state import AppState
from wrsr_installer.config import AppConfig, load_config
from wrsr_installer.download_queue import DownloadQueue
from wrsr_installer.skymods import CatalogueMod, SearchPage, parse_mod_page, parse_search_page
from wrsr_installer.ui import dialogs
from wrsr_installer.ui.main_window import MainWindow

FIXTURES = Path(__file__).parent / 'fixtures'


def add_mod(game, folder, text):
    mod_dir = game / 'media_soviet' / 'workshop_wip' / folder
    mod_dir.mkdir(parents=True)
    (mod_dir / 'workshopconfig.ini').write_text(text)
    return mod_dir


class FakeCatalogue:
    """Search results from the saved fixture page; individual searches can be held back."""

    def __init__(self):
        self.page = parse_search_page((FIXTURES / 'skymods_search.html').read_text(encoding='utf-8'))
        self.gates = {}
        self.detail_gates = {}
        self.started = set()
        self.by_url = {}
        self.saved = {}       # (term, page) -> (SearchPage, age in seconds)
        self.saved_mods = {}  # url -> (CatalogueMod, age in seconds)

    def saved_search(self, term, page=1):
        return self.saved.get((term, page))

    def saved_mod(self, url):
        return self.saved_mods.get(url)

    def search(self, term, page=1):
        self.started.add(term)
        gate = self.gates.get(term)
        if gate is not None:
            gate.wait(10)
        if term == 'nothing':
            return SearchPage(mods=[], has_next=False)
        # Distinct mods per search term, so results from one search can't pass for another's.
        mods = [CatalogueMod(**{**m.__dict__, 'name': f'{m.name} ({term})', 'steam_id': f'{m.steam_id}{term}',
                                'url': f'{m.url}?{term}'}) for m in self.page.mods]
        self.by_url.update({m.url: m for m in mods})
        return SearchPage(mods=mods, has_next=False)

    def fetch_mod(self, url):
        gate = self.detail_gates.get(url)
        if gate is not None:
            gate.wait(10)
        details = parse_mod_page((FIXTURES / 'skymods_mod.html').read_text(encoding='utf-8'), url)
        listed = self.by_url[url]
        details.name, details.steam_id = listed.name, listed.steam_id
        return details


@pytest.fixture(autouse=True)
def no_image_downloads(monkeypatch):
    monkeypatch.setattr('wrsr_installer.ui.widgets._fetch_image', lambda url: None)


@pytest.fixture(autouse=True)
def answer_questions_with_yes(monkeypatch):
    # Nobody can click a modal question in a headless test (e.g. "quit while downloading?").
    monkeypatch.setattr(dialogs, 'confirm', lambda *args, **kwargs: True)


class NoNetworkServices:
    """Queue services that never touch the network; downloads wait until released."""

    def __init__(self):
        self.release = threading.Event()

    def load_requirements(self, mod, cancel):
        mod.details_loaded = True
        return []

    def look_up(self, steam_id, cancel):
        return None

    def install(self, mod, progress, cancel):
        while not self.release.wait(0.02):
            cancel.check()
        return Path('workshop_wip') / (mod.steam_id or 'x')


@pytest.fixture
def game(tmp_path):
    folder = tmp_path / 'WRSR'
    add_mod(folder, '111', '$ITEM_ID 111\n$OWNER_ID 5\n$ITEM_TYPE WORKSHOP_ITEMTYPE_BUILDING\n'
                           '$ITEM_NAME "Fixed Mod"\n')
    add_mod(folder, '222', '$ITEM_ID 222\n$OWNER_ID 7\n$ITEM_TYPE WORKSHOP_ITEMTYPE_BUILDING\n'
                           '$ITEM_NAME "Unfixed Mod"\n')
    return folder


@pytest.fixture
def services():
    services = NoNetworkServices()
    yield services
    services.release.set()


@pytest.fixture
def window(qtbot, tmp_path, game, services):
    state = AppState(AppConfig(game_folder=str(game), target_owner_id='5'),
                     config_path=tmp_path / 'config.json')
    queue = DownloadQueue(install=services.install, load_requirements=services.load_requirements,
                          look_up=services.look_up)
    main = MainWindow(state, queue, catalogue=FakeCatalogue())

    def finish_background_work(widget):
        services.release.set()
        catalogue = widget.browse.catalogue
        for gate in list(catalogue.gates.values()) + list(catalogue.detail_gates.values()):
            gate.set()
        QThreadPool.globalInstance().waitForDone(5000)
        QApplication.processEvents()

    qtbot.addWidget(main, before_close_func=finish_background_work)
    main.show()
    qtbot.waitExposed(main)
    with qtbot.waitSignal(state.mods_changed, timeout=5000):
        state.rescan()
    return main


def table_text(table, row, column):
    item = table.item(row, column)
    return item.text() if item else ''


def test_library_lists_mods_with_their_status(window):
    table = window.library.table
    names = [table_text(table, row, 0) for row in range(table.rowCount())]
    assert names == ['Fixed Mod', 'Unfixed Mod']
    assert window.library.status_text(0) == 'Fixed'
    assert window.library.status_text(1) == 'Needs Owner ID'


def test_apply_button_writes_the_owner_id(qtbot, window, game):
    button = window.library.apply_button(1)

    with qtbot.waitSignal(window.state.mods_changed, timeout=5000):
        qtbot.mouseClick(button, Qt.LeftButton)

    config = (game / 'media_soviet' / 'workshop_wip' / '222' / 'workshopconfig.ini').read_text()
    assert '$OWNER_ID 5' in config
    assert window.library.status_text(1) == 'Fixed'


def test_apply_to_all_asks_first_then_updates(qtbot, window, game, monkeypatch):
    questions = []
    monkeypatch.setattr(dialogs, 'confirm', lambda *args, **kwargs: questions.append(args) or True)

    with qtbot.waitSignal(window.state.mods_changed, timeout=5000):
        qtbot.mouseClick(window.library.apply_all_button, Qt.LeftButton)

    assert len(questions) == 1
    assert window.state.unfixed_mods() == []


def search(qtbot, window, term):
    browse = window.browse
    browse.search_input.setText(term)
    qtbot.mouseClick(browse.search_button, Qt.LeftButton)


def test_search_shows_results(qtbot, window):
    search(qtbot, window, 'tram')
    qtbot.waitUntil(lambda: window.browse.model.rowCount() == 3, timeout=5000)
    assert window.browse.model.mod_at(0).name == 'Tram Depot – Large (tram)'


def test_double_clicking_a_result_adds_it_to_downloads(qtbot, window):
    # Bug 1: double-clicking used to pass the list item where a mod was expected and crash.
    search(qtbot, window, 'tram')
    qtbot.waitUntil(lambda: window.browse.model.rowCount() == 3, timeout=5000)
    view = window.browse.results
    rect = view.visualRect(window.browse.model.index(0))

    # A real double-click arrives as a click followed by a double-click event.
    qtbot.mouseClick(view.viewport(), Qt.LeftButton, pos=rect.center())
    qtbot.mouseDClick(view.viewport(), Qt.LeftButton, pos=rect.center())

    assert [i.mod.name for i in window.queue.items] == ['Tram Depot – Large (tram)']


def test_a_new_search_replaces_a_slow_one(qtbot, window):
    # Bug 6: starting a search used to block until the previous one finished all its pages.
    catalogue = window.browse.catalogue
    catalogue.gates['slow'] = threading.Event()

    search(qtbot, window, 'slow')
    qtbot.waitUntil(lambda: 'slow' in catalogue.started, timeout=5000)  # its request is in flight
    search(qtbot, window, 'fast')
    qtbot.waitUntil(lambda: window.browse.model.rowCount() == 3, timeout=5000)
    catalogue.gates['slow'].set()
    QThreadPool.globalInstance().waitForDone(5000)  # the slow search has now returned...
    qtbot.wait(100)  # ...and its result has been delivered

    names = [window.browse.model.mod_at(i).name for i in range(window.browse.model.rowCount())]
    assert len(names) == 3 and all(name.endswith('(fast)') for name in names)


def test_late_details_of_an_earlier_selection_do_not_replace_the_current_one(qtbot, window):
    # Bug 4: a slow details response could land after a newer one and show the wrong mod.
    catalogue = window.browse.catalogue
    search(qtbot, window, 'tram')
    qtbot.waitUntil(lambda: window.browse.model.rowCount() == 3, timeout=5000)
    first, second = window.browse.model.mod_at(0), window.browse.model.mod_at(1)
    catalogue.detail_gates[first.url] = threading.Event()

    window.browse.results.setCurrentIndex(window.browse.model.index(0))
    window.browse.results.setCurrentIndex(window.browse.model.index(1))
    qtbot.waitUntil(lambda: second.details_loaded, timeout=5000)
    catalogue.detail_gates[first.url].set()
    qtbot.waitUntil(lambda: first.details_loaded, timeout=5000)

    assert window.browse.details.mod is second
    assert window.browse.details.title.text() == second.name


def saved_listing(name='Saved Tram'):
    return CatalogueMod(name=name, url='https://catalogue.smods.ru/archives/900', steam_id='900',
                        download_url='https://modsbase.com/x/900.zip.html')


def result_names(window):
    model = window.browse.model
    return [model.mod_at(i).name for i in range(model.rowCount())]


def test_saved_results_appear_at_once_and_are_then_refreshed(qtbot, window):
    catalogue = window.browse.catalogue
    catalogue.saved[('tram', 1)] = (SearchPage(mods=[saved_listing()], has_next=False), 2 * 3600)
    catalogue.gates['tram'] = threading.Event()  # Skymods hasn't answered yet

    search(qtbot, window, 'tram')

    assert result_names(window) == ['Saved Tram']
    assert 'saved' in window.browse.status_label.text().lower()
    catalogue.gates['tram'].set()
    qtbot.waitUntil(lambda: len(result_names(window)) == 3, timeout=5000)
    assert result_names(window)[0] == 'Tram Depot – Large (tram)'


def test_recently_saved_results_are_not_fetched_again(qtbot, window):
    catalogue = window.browse.catalogue
    catalogue.saved[('tram', 1)] = (SearchPage(mods=[saved_listing()], has_next=False), 60)

    search(qtbot, window, 'tram')
    qtbot.wait(200)

    assert result_names(window) == ['Saved Tram']
    assert 'tram' not in catalogue.started


def test_saved_mod_details_show_at_once(qtbot, window):
    catalogue = window.browse.catalogue
    search(qtbot, window, 'tram')
    qtbot.waitUntil(lambda: len(result_names(window)) == 3, timeout=5000)
    first = window.browse.model.mod_at(0)
    catalogue.saved_mods[first.url] = (CatalogueMod(name=first.name, url=first.url,
                                                    description_html='<p>Saved words</p>',
                                                    details_loaded=True), 2 * 24 * 3600)
    catalogue.detail_gates[first.url] = threading.Event()  # the refresh is still on its way

    window.browse.results.setCurrentIndex(window.browse.model.index(0))

    assert 'Saved words' in window.browse.details.description.text()


def test_search_without_results_says_so(qtbot, window):
    search(qtbot, window, 'nothing')
    qtbot.waitUntil(lambda: 'No mods found' in window.browse.status_label.text(), timeout=5000)


def test_downloads_page_and_badge_follow_the_queue(qtbot, window):
    mod = CatalogueMod(name='Tram Depot', url='https://catalogue.smods.ru/archives/1', steam_id='1',
                       download_url='https://modsbase.com/x/1.zip.html')

    window.queue.add(mod)

    qtbot.waitUntil(lambda: window.downloads.row_count() == 1, timeout=5000)
    assert window.nav_badge('downloads') == '1'


def test_settings_rejects_an_invalid_owner_id(qtbot, window, tmp_path):
    settings = window.settings
    settings.owner_input.setText('12a')

    qtbot.mouseClick(settings.save_owner_button, Qt.LeftButton)

    assert settings.owner_error.isVisible() or settings.owner_error.text()
    assert window.state.owner_id == '5'
    assert load_config(tmp_path / 'config.json').target_owner_id is None
