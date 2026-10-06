import io
import zipfile

import pytest

from conftest import Route
from wrsr_installer.cancel import CancelToken
from wrsr_installer.downloader import DownloadError
from wrsr_installer.services import make_installer
from wrsr_installer.skymods import CatalogueMod


def zip_bytes(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buffer.getvalue()


@pytest.fixture
def workshop(tmp_path):
    return tmp_path / 'game' / 'media_soviet' / 'workshop_wip'


def catalogue_mod(url):
    return CatalogueMod(name='Tram: Depot?', url='https://catalogue.smods.ru/archives/1',
                        steam_id='3100000001', download_url=url, file_size='1 KB')


def test_install_downloads_extracts_and_installs_into_workshop(web, workshop):
    web.route('/mod.zip', Route(body=zip_bytes({
        'Pack/workshopconfig.ini': '$ITEM_ID 3100000001\n$ITEM_NAME "Tram"\n',
        'Pack/model.nmf': 'model',
    }), headers={'Content-Type': 'application/zip'}))
    events = []

    path = make_installer(lambda: workshop)(catalogue_mod(web.url('/mod.zip')), events.append, CancelToken())

    assert path == workshop / '3100000001'
    assert (path / 'model.nmf').read_text() == 'model'
    assert [e.stage for e in events][-1] == 'installing'


def test_install_replaces_an_older_copy_of_the_same_mod(web, workshop):
    old = workshop / '3100000001'
    old.mkdir(parents=True)
    (old / 'obsolete.dds').write_text('old')
    web.route('/mod.zip', Route(body=zip_bytes({
        'Pack/workshopconfig.ini': '$ITEM_ID 3100000001\n', 'Pack/model.nmf': 'new'}),
        headers={'Content-Type': 'application/zip'}))

    make_installer(lambda: workshop)(catalogue_mod(web.url('/mod.zip')), lambda p: None, CancelToken())

    assert sorted(p.name for p in old.iterdir()) == ['model.nmf', 'workshopconfig.ini']


def test_install_without_download_link_fails_clearly(workshop):
    with pytest.raises(DownloadError):
        make_installer(lambda: workshop)(catalogue_mod(None), lambda p: None, CancelToken())
