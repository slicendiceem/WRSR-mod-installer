import os
import time

from wrsr_installer.cache import PageCache

DAY = 24 * 3600


class Clock:
    def __init__(self, now=1_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


def test_cache_returns_a_saved_page_with_its_age(tmp_path):
    clock = Clock()
    cache = PageCache(tmp_path, clock=clock)
    cache.put('https://catalogue.smods.ru/?s=tram', '<html>tram</html>')
    clock.now += 90

    hit = cache.get('https://catalogue.smods.ru/?s=tram')

    assert (hit.text, hit.age) == ('<html>tram</html>', 90)


def test_cache_misses_pages_it_never_saved(tmp_path):
    assert PageCache(tmp_path).get('https://catalogue.smods.ru/?s=bus') is None


def test_cache_keeps_pages_apart(tmp_path):
    cache = PageCache(tmp_path)
    cache.put('https://a.example/', 'A')
    cache.put('https://b.example/', 'B')

    assert cache.get('https://a.example/').text == 'A'
    assert cache.get('https://b.example/').text == 'B'


def test_cache_forgets_pages_older_than_its_limit(tmp_path):
    clock = Clock()
    cache = PageCache(tmp_path, max_age=7 * DAY, clock=clock)
    cache.put('https://a.example/', 'A')
    clock.now += 8 * DAY

    assert cache.get('https://a.example/') is None


def test_cache_treats_damaged_files_as_missing(tmp_path):
    cache = PageCache(tmp_path)
    cache.put('https://a.example/', 'A')
    [saved] = [p for p in tmp_path.rglob('*') if p.is_file()]
    saved.write_bytes(b'not what was written')

    assert cache.get('https://a.example/') is None


def test_cache_survives_a_folder_it_cannot_create(tmp_path):
    blocker = tmp_path / 'file'
    blocker.write_text('x')
    cache = PageCache(blocker / 'cache')

    cache.put('https://a.example/', 'A')  # must not raise

    assert cache.get('https://a.example/') is None


def test_prune_removes_expired_pages_and_keeps_only_the_newest(tmp_path):
    cache = PageCache(tmp_path, max_age=7 * DAY, max_entries=2)
    now = time.time()
    ages = {'https://e1/': 9 * DAY, 'https://e2/': 8 * DAY, 'https://n1/': 300, 'https://n2/': 200, 'https://n3/': 100}
    for key, age in ages.items():
        cache.put(key, key)
        [newest] = sorted((p for p in tmp_path.rglob('*') if p.is_file()), key=os.path.getmtime)[-1:]
        os.utime(newest, (now - age, now - age))

    cache.prune()

    assert len([p for p in tmp_path.rglob('*') if p.is_file()]) == 2
    assert cache.get('https://n3/') is not None and cache.get('https://n2/') is not None
