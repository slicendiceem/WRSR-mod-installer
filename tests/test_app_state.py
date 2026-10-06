import os
import stat

import pytest

from wrsr_installer.app_state import AppState
from wrsr_installer.config import AppConfig, load_config
from wrsr_installer.skymods import CatalogueMod


def add_mod(game, folder, text):
    mod_dir = game / 'media_soviet' / 'workshop_wip' / folder
    mod_dir.mkdir(parents=True)
    (mod_dir / 'workshopconfig.ini').write_text(text)
    return mod_dir


@pytest.fixture
def game(tmp_path):
    folder = tmp_path / 'WRSR'
    (folder / 'media_soviet' / 'workshop_wip').mkdir(parents=True)
    return folder


def make_state(tmp_path, game=None, owner_id=None):
    return AppState(AppConfig(game_folder=str(game) if game else None, target_owner_id=owner_id),
                    config_path=tmp_path / 'config.json')


def scan(qtbot, state):
    with qtbot.waitSignal(state.mods_changed, timeout=5000):
        state.rescan()


def test_rescan_lists_installed_mods(qtbot, tmp_path, game):
    add_mod(game, '111', '$ITEM_ID 111\n$ITEM_NAME "Tram Depot"\n')
    state = make_state(tmp_path, game)

    scan(qtbot, state)

    assert [m.item_name for m in state.mods] == ['Tram Depot']
    assert state.is_installed(CatalogueMod(name='Other name', url='u', steam_id='111'))


def test_rescan_reports_a_missing_workshop_folder(qtbot, tmp_path):
    state = make_state(tmp_path, tmp_path / 'not-a-game')

    with qtbot.waitSignal(state.scan_failed, timeout=5000) as failed:
        state.rescan()

    assert 'workshop' in failed.args[0].lower()
    assert state.mods == []


def test_set_owner_id_saves_settings_and_rejects_bad_input(qtbot, tmp_path):
    state = make_state(tmp_path)

    state.set_owner_id('76561198000000001')
    with pytest.raises(ValueError):
        state.set_owner_id('not a number')

    assert load_config(tmp_path / 'config.json').target_owner_id == '76561198000000001'
    assert state.owner_id == '76561198000000001'


def test_set_game_folder_saves_settings_and_scans(qtbot, tmp_path, game):
    add_mod(game, 'a', '$ITEM_NAME "A"\n')
    state = make_state(tmp_path)

    with qtbot.waitSignal(state.mods_changed, timeout=5000):
        state.set_game_folder(str(game))

    assert load_config(tmp_path / 'config.json').game_folder == str(game)
    assert len(state.mods) == 1


def test_is_fixed_compares_against_the_target_owner_id(qtbot, tmp_path, game):
    add_mod(game, 'a', '$OWNER_ID 5\n$ITEM_NAME "A"\n')
    add_mod(game, 'b', '$OWNER_ID 7\n$ITEM_NAME "B"\n')
    state = make_state(tmp_path, game, owner_id='5')
    scan(qtbot, state)

    assert [state.is_fixed(m) for m in state.mods] == [True, False]
    assert [m.folder for m in state.unfixed_mods()] == ['b']


def test_apply_owner_id_updates_mods_and_reports_failures(qtbot, tmp_path, game):
    add_mod(game, 'a', '$OWNER_ID 1\n$ITEM_NAME "A"\n')
    locked = add_mod(game, 'b', '$OWNER_ID 1\n$ITEM_NAME "B"\n') / 'workshopconfig.ini'
    os.chmod(locked, stat.S_IREAD)
    state = make_state(tmp_path, game, owner_id='9')
    scan(qtbot, state)
    results = []

    try:
        with qtbot.waitSignal(state.mods_changed, timeout=5000):
            state.apply_owner_id(state.mods, results.append)
        qtbot.waitUntil(lambda: bool(results), timeout=5000)
    finally:
        os.chmod(locked, stat.S_IWRITE | stat.S_IREAD)

    result = results[0]
    assert result.updated == ['A']
    assert [name for name, _ in result.failed] == ['B']
    assert [m.owner_id for m in state.mods] == ['9', '1']
