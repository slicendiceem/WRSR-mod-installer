import errno
import os
import zipfile
from pathlib import Path

import pytest

from wrsr_installer import archive
from wrsr_installer.archive import (
    ArchiveError,
    ModExistsError,
    extract_mod,
    install_mod_folder,
    safe_filename,
)


def make_zip(path, files):
    with zipfile.ZipFile(path, 'w') as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return path


def make_folder(path, files):
    path.mkdir(parents=True)
    for name, content in files.items():
        (path / name).write_text(content)
    return path


@pytest.fixture
def workshop(tmp_path):
    path = tmp_path / 'game' / 'media_soviet' / 'workshop_wip'
    path.mkdir(parents=True)
    return path


# --- extract_mod ------------------------------------------------------------

def test_extract_mod_finds_config_in_subfolder(tmp_path):
    zip_path = make_zip(tmp_path / 'm.zip', {
        'TheMod/workshopconfig.ini': '$ITEM_NAME "The Mod"\n',
        'TheMod/model.nmf': 'x',
    })
    with extract_mod(zip_path, 'fallback') as em:
        assert em.root.name == 'TheMod'
        assert em.folder_name == 'TheMod'
        assert em.info.item_name == 'The Mod'


def test_extract_mod_skips_folders_without_config(tmp_path):
    # The old code took the first folder in the archive, here "Docs".
    zip_path = make_zip(tmp_path / 'm.zip', {
        'Docs/readme.txt': 'read me',
        'TheMod/workshopconfig.ini': '$ITEM_NAME "The Mod"\n',
    })
    with extract_mod(zip_path, 'fallback') as em:
        assert em.root.name == 'TheMod'


def test_extract_mod_names_folder_after_item_id(tmp_path):
    zip_path = make_zip(tmp_path / 'm.zip', {
        'TheMod/workshopconfig.ini': '$ITEM_ID 3043462563\n$ITEM_NAME "The Mod"\n',
    })
    with extract_mod(zip_path, 'fallback') as em:
        assert em.folder_name == '3043462563'


def test_extract_mod_handles_config_at_archive_root(tmp_path):
    zip_path = make_zip(tmp_path / 'm.zip', {
        'workshopconfig.ini': '$ITEM_NAME "Loose"\n',
        'model.nmf': 'x',
    })
    with extract_mod(zip_path, 'My Mod: v2') as em:
        assert em.folder_name == 'My Mod_ v2'
        assert (em.root / 'model.nmf').read_text() == 'x'


def test_extract_mod_finds_nested_mod(tmp_path):
    zip_path = make_zip(tmp_path / 'm.zip', {
        'Pack/TheMod/workshopconfig.ini': '$ITEM_NAME "Nested"\n',
    })
    with extract_mod(zip_path, 'fallback') as em:
        assert em.root.name == 'TheMod'


def test_extract_mod_rejects_archive_without_config(tmp_path):
    zip_path = make_zip(tmp_path / 'm.zip', {'TheMod/model.nmf': 'x'})
    with pytest.raises(ArchiveError):
        extract_mod(zip_path, 'fallback')


def test_extract_mod_rejects_non_zip_file(tmp_path):
    page = tmp_path / 'm.zip'
    page.write_text('<!DOCTYPE html><html>No file</html>')
    with pytest.raises(ArchiveError):
        extract_mod(page, 'fallback')


def test_extract_mod_cleanup_removes_extracted_files(tmp_path):
    zip_path = make_zip(tmp_path / 'm.zip', {'TheMod/workshopconfig.ini': '$END\n'})
    em = extract_mod(zip_path, 'fallback')
    root = em.root
    em.cleanup()
    assert not root.exists()


# --- install_mod_folder -----------------------------------------------------

def test_install_moves_mod_into_workshop(tmp_path, workshop):
    src = make_folder(tmp_path / 'src' / 'TheMod', {'workshopconfig.ini': 'new'})

    dest = install_mod_folder(src, workshop, 'TheMod')

    assert dest == workshop / 'TheMod'
    assert (dest / 'workshopconfig.ini').read_text() == 'new'
    assert not src.exists()
    assert sorted(p.name for p in workshop.parent.iterdir()) == ['workshop_wip']


def test_install_refuses_to_overwrite_without_replace(tmp_path, workshop):
    make_folder(workshop / 'TheMod', {'workshopconfig.ini': 'old'})
    src = make_folder(tmp_path / 'src' / 'TheMod', {'workshopconfig.ini': 'new'})

    with pytest.raises(ModExistsError):
        install_mod_folder(src, workshop, 'TheMod')

    assert (workshop / 'TheMod' / 'workshopconfig.ini').read_text() == 'old'
    assert src.exists()


def test_install_replace_swaps_in_new_version(tmp_path, workshop):
    make_folder(workshop / 'TheMod', {'workshopconfig.ini': 'old', 'removed.dds': 'x'})
    src = make_folder(tmp_path / 'src' / 'TheMod', {'workshopconfig.ini': 'new'})

    install_mod_folder(src, workshop, 'TheMod', replace=True)

    assert sorted(p.name for p in (workshop / 'TheMod').iterdir()) == ['workshopconfig.ini']
    assert (workshop / 'TheMod' / 'workshopconfig.ini').read_text() == 'new'
    assert sorted(p.name for p in workshop.parent.iterdir()) == ['workshop_wip']


def test_install_failure_restores_previous_version(tmp_path, workshop, monkeypatch):
    # Bug 3: the old code deleted the installed mod before the new one was in place.
    make_folder(workshop / 'TheMod', {'workshopconfig.ini': 'old'})
    src = make_folder(tmp_path / 'src' / 'TheMod', {'workshopconfig.ini': 'new'})

    def failing_move(source, destination):
        Path(destination).mkdir()
        (Path(destination) / 'partial.bin').write_text('half')
        raise OSError(errno.ENOSPC, 'No space left on device')

    monkeypatch.setattr(archive.shutil, 'move', failing_move)

    with pytest.raises(OSError):
        install_mod_folder(src, workshop, 'TheMod', replace=True)

    assert sorted(p.name for p in (workshop / 'TheMod').iterdir()) == ['workshopconfig.ini']
    assert (workshop / 'TheMod' / 'workshopconfig.ini').read_text() == 'old'
    assert sorted(p.name for p in workshop.parent.iterdir()) == ['workshop_wip']


def test_install_works_across_drives(tmp_path, workshop, monkeypatch):
    # Bug 2: Path.rename cannot move a folder from the temp drive to the game drive.
    temp_drive = tmp_path / 'src'
    src = make_folder(temp_drive / 'TheMod', {'workshopconfig.ini': 'new'})
    real_rename = os.rename

    def rename_same_drive_only(a, b):
        if Path(a).is_relative_to(temp_drive) != Path(b).is_relative_to(temp_drive):
            raise OSError(errno.EXDEV, 'Invalid cross-device link')
        real_rename(a, b)

    monkeypatch.setattr(os, 'rename', rename_same_drive_only)

    dest = install_mod_folder(src, workshop, 'TheMod')

    assert (dest / 'workshopconfig.ini').read_text() == 'new'


# --- safe_filename ----------------------------------------------------------

@pytest.mark.parametrize('name, expected', [
    ('Old: Town?*', 'Old_ Town__'),
    ('a/b\\c', 'a_b_c'),
    ('Trailing dot. ', 'Trailing dot'),
    ('CON', '_CON'),
    ('   ', 'mod'),
    ('Хрущёвка', 'Хрущёвка'),
])
def test_safe_filename(name, expected):
    assert safe_filename(name) == expected
