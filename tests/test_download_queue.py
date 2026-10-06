import threading
import time
from pathlib import Path

from wrsr_installer.download_queue import ACTIVE, CANCELLED, DONE, FAILED, RESOLVING, DownloadQueue
from wrsr_installer.downloader import DownloadError, ManualDownloadRequired, Progress
from wrsr_installer.skymods import CatalogueMod, Prerequisite, SkymodsError


def listing(steam_id, requires=(), download=True):
    """A mod as a Skymods search lists it: whether it needs other mods, but not which."""
    return CatalogueMod(name=f'Mod {steam_id}', url=f'https://catalogue.smods.ru/archives/{steam_id}',
                        steam_id=steam_id,
                        download_url=f'https://modsbase.com/x/{steam_id}.zip.html' if download else None,
                        has_requirements=bool(requires))


def opened(steam_id, requires=(), download=True):
    """A mod whose page has been loaded, so the mods it needs are known."""
    mod = listing(steam_id, requires, download)
    mod.prerequisites = [Prerequisite(f'Mod {r}', r) for r in requires]
    mod.details_loaded = True
    return mod


class FakeCatalogue:
    """Stands in for Skymods: what each mod needs, and which mods it has. Page loads and
    lookups can be held back or made to fail."""

    def __init__(self, requires=None, missing=(), no_download=()):
        self.requires = requires or {}       # steam id -> steam ids it needs
        self.missing = set(missing)          # steam ids Skymods doesn't have
        self.no_download = set(no_download)  # steam ids whose page has no download link
        self.page_gates, self.lookup_gates = {}, {}
        self.page_errors, self.lookup_errors = {}, {}
        self.pages_loaded, self.lookups = [], []
        self.on_lookup = None
        self.lock = threading.Lock()

    def load_requirements(self, mod, cancel):
        if not mod.url:  # like the real thing: a mod that hasn't been found yet has no page to load
            raise SkymodsError('That mod has no Skymods page address.')
        gate = self.page_gates.get(mod.steam_id)
        if gate is not None:
            gate.wait(10)
        if mod.steam_id in self.page_errors:
            raise self.page_errors.pop(mod.steam_id)
        with self.lock:
            self.pages_loaded.append(mod.steam_id)
        mod.merge_details(opened(mod.steam_id, self.requires.get(mod.steam_id, ()),
                                 download=mod.steam_id not in self.no_download))
        return list(mod.prerequisites)

    def look_up(self, steam_id, cancel):
        if self.on_lookup is not None:
            self.on_lookup(steam_id)
        gate = self.lookup_gates.get(steam_id)
        if gate is not None:
            gate.wait(10)
        if steam_id in self.lookup_errors:
            raise self.lookup_errors.pop(steam_id)
        with self.lock:
            self.lookups.append(steam_id)
        return None if steam_id in self.missing else listing(steam_id, self.requires.get(steam_id, ()))


class FakeInstaller:
    """Installs instantly unless told to fail or to be slow."""

    def __init__(self, fail=(), slow=(), errors=None):
        self.fail = set(fail)
        self.slow = set(slow)
        self.errors = errors or {}
        self.installed = []
        self.running = 0
        self.max_running = 0
        self.lock = threading.Lock()

    def install(self, target, progress, cancel):
        with self.lock:
            self.running += 1
            self.max_running = max(self.max_running, self.running)
        try:
            progress(Progress('downloading', 50, '1 MB of 2 MB'))
            if target.steam_id in self.slow:
                for _ in range(100):
                    cancel.check()
                    time.sleep(0.01)
            if target.steam_id in self.errors:
                raise self.errors.pop(target.steam_id)
            if target.steam_id in self.fail:
                raise DownloadError('The server said no.')
            with self.lock:
                self.installed.append(target.steam_id)
            return Path('workshop_wip') / target.steam_id
        finally:
            with self.lock:
                self.running -= 1


def make_queue(catalogue=None, installer=None, installed=()):
    catalogue = catalogue or FakeCatalogue()
    installer = installer or FakeInstaller()
    return DownloadQueue(install=installer.install, load_requirements=catalogue.load_requirements,
                         look_up=catalogue.look_up, is_installed=lambda name, steam_id: steam_id in installed)


def ids(queue):
    return [item.mod.steam_id for item in queue.items]


# --- required mods ------------------------------------------------------------

def test_required_mods_appear_in_the_queue_as_soon_as_they_are_known(qtbot):
    catalogue = FakeCatalogue()
    catalogue.lookup_gates['2'] = threading.Event()  # Skymods is slow to find it
    installer = FakeInstaller()
    queue = make_queue(catalogue, installer)

    with qtbot.waitSignal(queue.finished, timeout=10000):
        queue.add(opened('1', ['2']))
        required = next(i for i in queue.items if i.mod.steam_id == '2')
        assert (required.state, required.mod.name, required.required_by) == (RESOLVING, 'Mod 2', 'Mod 1')
        catalogue.lookup_gates['2'].set()

    assert sorted(installer.installed) == ['1', '2']


def test_required_mods_appear_once_the_page_loads_without_waiting_for_their_lookups(qtbot):
    catalogue = FakeCatalogue(requires={'1': ['2']})
    catalogue.lookup_gates['2'] = threading.Event()
    queue = make_queue(catalogue)

    with qtbot.waitSignal(queue.finished, timeout=10000):
        queue.add(listing('1', ['2']))
        qtbot.waitUntil(lambda: '2' in ids(queue), timeout=5000)
        assert catalogue.lookups == []
        catalogue.lookup_gates['2'].set()


def test_required_mods_are_downloaded_too(qtbot):
    installer = FakeInstaller()
    queue = make_queue(FakeCatalogue(requires={'1': ['2']}), installer)

    with qtbot.waitSignal(queue.finished, timeout=10000):
        queue.add(listing('1', ['2']))

    assert sorted(installer.installed) == ['1', '2']


def test_a_mod_whose_listing_says_it_needs_nothing_is_not_looked_into(qtbot):
    catalogue = FakeCatalogue()
    queue = make_queue(catalogue)

    with qtbot.waitSignal(queue.finished, timeout=10000):
        queue.add(listing('1'))

    assert (catalogue.pages_loaded, catalogue.lookups) == ([], [])


def test_only_required_mods_that_need_others_have_their_page_loaded(qtbot):
    # 1 needs 2 and 3; of those, only 2 needs anything else (4).
    catalogue = FakeCatalogue(requires={'1': ['2', '3'], '2': ['4']})
    installer = FakeInstaller()
    queue = make_queue(catalogue, installer)

    with qtbot.waitSignal(queue.finished, timeout=10000):
        queue.add(opened('1', ['2', '3']))

    assert catalogue.pages_loaded == ['2']
    assert sorted(installer.installed) == ['1', '2', '3', '4']


def test_required_mods_are_looked_up_at_the_same_time(qtbot):
    catalogue = FakeCatalogue()
    # Each lookup waits until all three are in progress, which only happens if they run in parallel.
    barrier = threading.Barrier(3, timeout=5)
    catalogue.on_lookup = lambda steam_id: barrier.wait()
    installer = FakeInstaller()
    queue = make_queue(catalogue, installer)

    with qtbot.waitSignal(queue.finished, timeout=10000):
        queue.add(opened('1', ['2', '3', '4']))

    assert sorted(installer.installed) == ['1', '2', '3', '4']


def test_a_required_mod_missing_from_skymods_shows_as_failed(qtbot):
    installer = FakeInstaller()
    queue = make_queue(FakeCatalogue(missing={'2'}), installer)

    with qtbot.waitSignal(queue.finished, timeout=10000):
        queue.add(opened('1', ['2']))

    required = next(i for i in queue.items if i.mod.steam_id == '2')
    assert required.state == FAILED and 'Steam Workshop' in required.message
    assert installer.installed == ['1']


def test_installed_requirements_are_noted_instead_of_queued(qtbot):
    queue = make_queue(installed={'2'})

    with qtbot.waitSignal(queue.finished, timeout=10000):
        item = queue.add(opened('1', ['2']))

    assert ids(queue) == ['1']
    assert item.installed_requirements == ['Mod 2']


def test_a_requirement_already_in_the_queue_is_not_added_twice(qtbot):
    queue = make_queue(installer=FakeInstaller(slow={'2'}))

    with qtbot.waitSignal(queue.finished, timeout=10000):
        queue.add(listing('2'))
        queue.add(opened('1', ['2']))

    assert ids(queue).count('2') == 1


def test_a_requirement_shared_by_two_mods_is_queued_once(qtbot):
    installer = FakeInstaller()
    queue = make_queue(FakeCatalogue(requires={'1': ['2', '3'], '2': ['4'], '3': ['4']}), installer)

    with qtbot.waitSignal(queue.finished, timeout=10000):
        queue.add(opened('1', ['2', '3']))

    assert sorted(installer.installed) == ['1', '2', '3', '4']


def test_requirement_cycles_end(qtbot):
    installer = FakeInstaller()
    queue = make_queue(FakeCatalogue(requires={'1': ['2'], '2': ['1']}), installer)

    with qtbot.waitSignal(queue.finished, timeout=10000):
        queue.add(opened('1', ['2']))

    assert sorted(installer.installed) == ['1', '2']


def test_requirements_without_a_steam_id_are_noted(qtbot):
    mod = opened('1')
    mod.prerequisites = [Prerequisite('Some mod', None)]
    queue = make_queue()

    with qtbot.waitSignal(queue.finished, timeout=10000):
        item = queue.add(mod)

    assert item.missing == [Prerequisite('Some mod', None)]


def test_a_mod_starts_downloading_without_waiting_for_its_requirements(qtbot):
    catalogue = FakeCatalogue(requires={'1': ['2']})
    catalogue.page_gates['1'] = threading.Event()  # Skymods is slow to say what it needs
    installer = FakeInstaller()
    queue = make_queue(catalogue, installer)

    with qtbot.waitSignal(queue.finished, timeout=10000):
        queue.add(listing('1', ['2']))
        qtbot.waitUntil(lambda: installer.installed == ['1'], timeout=5000)
        catalogue.page_gates['1'].set()

    assert installer.installed == ['1', '2']


def test_requirements_found_while_a_mod_still_waits_go_ahead_of_it(qtbot):
    installer = FakeInstaller(slow={'0'})
    queue = make_queue(FakeCatalogue(requires={'1': ['2']}), installer)

    with qtbot.waitSignal(queue.finished, timeout=10000):
        queue.add(listing('0'))
        queue.add(listing('1', ['2']))

    assert installer.installed == ['0', '2', '1']


def test_the_queue_is_not_finished_while_requirements_are_still_being_checked(qtbot):
    catalogue = FakeCatalogue(requires={'1': ['2']})
    catalogue.page_gates['1'] = threading.Event()
    installer = FakeInstaller()
    queue = make_queue(catalogue, installer)
    finished = []
    queue.finished.connect(finished.append)

    queue.add(listing('1', ['2']))
    qtbot.waitUntil(lambda: installer.installed == ['1'], timeout=5000)
    qtbot.wait(200)
    assert finished == []
    catalogue.page_gates['1'].set()
    qtbot.waitUntil(lambda: len(finished) == 1, timeout=5000)

    assert installer.installed == ['1', '2']


def test_a_failed_requirement_check_does_not_stop_the_download(qtbot):
    catalogue = FakeCatalogue()
    catalogue.page_errors['1'] = SkymodsError('Skymods took too long to respond.')
    queue = make_queue(catalogue)

    with qtbot.waitSignal(queue.finished, timeout=10000):
        item = queue.add(listing('1', ['2']))

    assert item.state == DONE
    assert 'too long' in item.check_error


def test_a_failed_lookup_shows_on_the_required_mods_row_and_can_be_retried(qtbot):
    catalogue = FakeCatalogue()
    catalogue.lookup_errors['2'] = SkymodsError('Skymods took too long to respond.')
    installer = FakeInstaller()
    queue = make_queue(catalogue, installer)
    with qtbot.waitSignal(queue.finished, timeout=10000):
        queue.add(opened('1', ['2']))
    required = next(i for i in queue.items if i.mod.steam_id == '2')
    assert required.state == FAILED and 'too long' in required.message

    with qtbot.waitSignal(queue.finished, timeout=10000):
        queue.retry(required)

    assert sorted(installer.installed) == ['1', '2']


def test_cancelling_a_mod_also_drops_its_requirements(qtbot):
    catalogue = FakeCatalogue(requires={'1': ['2']})
    catalogue.page_gates['1'] = threading.Event()
    installer = FakeInstaller(slow={'1'})
    queue = make_queue(catalogue, installer)

    with qtbot.waitSignal(queue.finished, timeout=10000):
        item = queue.add(listing('1', ['2']))
        qtbot.waitUntil(lambda: item.state == ACTIVE, timeout=5000)
        queue.cancel(item)
        catalogue.page_gates['1'].set()

    assert installer.installed == []
    assert ids(queue) == ['1']


def test_clearing_finished_downloads_keeps_their_requirements_coming(qtbot):
    # The mod itself finished before Skymods said what it needs; clearing it used to drop those.
    catalogue = FakeCatalogue(requires={'1': ['2']})
    catalogue.page_gates['1'] = threading.Event()
    installer = FakeInstaller()
    queue = make_queue(catalogue, installer)

    with qtbot.waitSignal(queue.finished, timeout=10000):
        item = queue.add(listing('1', ['2']))
        qtbot.waitUntil(lambda: item.state == DONE, timeout=5000)
        queue.clear_finished()
        catalogue.page_gates['1'].set()

    assert installer.installed == ['1', '2']


# --- the queue itself -------------------------------------------------------------

def test_downloads_run_one_at_a_time(qtbot):
    installer = FakeInstaller(slow={'1'})
    queue = make_queue(installer=installer)

    with qtbot.waitSignal(queue.finished, timeout=10000):
        for steam_id in ('1', '2', '3'):
            queue.add(listing(steam_id))

    assert installer.installed == ['1', '2', '3']
    assert installer.max_running == 1


def test_failed_download_does_not_stop_the_queue(qtbot):
    queue = make_queue(installer=FakeInstaller(fail={'1'}))

    with qtbot.waitSignal(queue.finished, timeout=10000) as finished:
        queue.add(listing('1'))
        queue.add(listing('2'))

    first, second = queue.items
    assert (first.state, first.message) == (FAILED, 'The server said no.')
    assert second.state == DONE
    summary = finished.args[0]
    assert (summary.installed, summary.failed) == (['Mod 2'], ['Mod 1'])


def test_cancelling_a_waiting_mod_skips_it(qtbot):
    installer = FakeInstaller(slow={'1'})
    queue = make_queue(installer=installer)

    with qtbot.waitSignal(queue.finished, timeout=10000):
        queue.add(listing('1'))
        second = queue.add(listing('2'))
        queue.add(listing('3'))
        qtbot.waitUntil(lambda: queue.items[0].state == ACTIVE, timeout=5000)
        queue.cancel(second)

    assert installer.installed == ['1', '3']
    assert second.state == CANCELLED


def test_cancelling_the_active_download_moves_on(qtbot):
    installer = FakeInstaller(slow={'1'})
    queue = make_queue(installer=installer)

    with qtbot.waitSignal(queue.finished, timeout=10000):
        first = queue.add(listing('1'))
        queue.add(listing('2'))
        qtbot.waitUntil(lambda: first.state == ACTIVE, timeout=5000)
        queue.cancel(first)

    assert first.state == CANCELLED
    assert installer.installed == ['2']


def test_adding_a_mod_that_is_already_queued_is_ignored(qtbot):
    queue = make_queue(installer=FakeInstaller(slow={'1'}))

    with qtbot.waitSignal(queue.finished, timeout=10000):
        assert queue.add(listing('1')) is not None
        assert queue.add(listing('1')) is None

    assert len(queue.items) == 1


def test_mod_without_download_link_fails_with_a_reason(qtbot):
    installer = FakeInstaller()
    queue = make_queue(FakeCatalogue(no_download={'1'}), installer)

    with qtbot.waitSignal(queue.finished, timeout=10000):
        item = queue.add(listing('1', download=False))

    assert item.state == FAILED
    assert 'download' in item.message.lower()
    assert installer.installed == []


def test_progress_is_shown_on_the_item(qtbot):
    queue = make_queue(installer=FakeInstaller(slow={'1'}))

    with qtbot.waitSignal(queue.finished, timeout=10000):
        item = queue.add(listing('1'))
        qtbot.waitUntil(lambda: item.progress == 50, timeout=5000)

    assert item.state == DONE and item.progress == 100


def test_retry_runs_a_failed_mod_again(qtbot):
    installer = FakeInstaller(errors={'1': DownloadError('Temporary hiccup.')})
    queue = make_queue(installer=installer)
    with qtbot.waitSignal(queue.finished, timeout=10000):
        item = queue.add(listing('1'))
    assert item.state == FAILED

    with qtbot.waitSignal(queue.finished, timeout=10000):
        queue.retry(item)

    assert item.state == DONE
    assert installer.installed == ['1']


def test_manual_download_keeps_the_page_to_open(qtbot):
    page = 'https://modsbase.com/x/1.zip.html'
    installer = FakeInstaller(errors={'1': ManualDownloadRequired('Open the page to download it.', page)})
    queue = make_queue(installer=installer)

    with qtbot.waitSignal(queue.finished, timeout=10000):
        item = queue.add(listing('1'))

    assert (item.state, item.manual_url) == (FAILED, page)


def test_clear_finished_keeps_unfinished_items(qtbot):
    queue = make_queue(installer=FakeInstaller(slow={'2'}))
    with qtbot.waitSignal(queue.finished, timeout=10000):
        queue.add(listing('1'))
        second = queue.add(listing('2'))
        qtbot.waitUntil(lambda: second.state == ACTIVE, timeout=5000)
        queue.clear_finished()
        assert ids(queue) == ['2']
