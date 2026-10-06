import pytest

from pathlib import Path

from wrsr_installer.workshop import (
    InstalledIndex,
    apply_owner_id,
    decode_config,
    find_config_file,
    game_folder_from,
    is_valid_owner_id,
    parse_config,
    read_mod,
    scan_mods,
    set_owner_id,
)

SAMPLE = (
    '$ITEM_ID 3043462563\n'
    '$OWNER_ID 76561198000000001\n'
    '$ITEM_TYPE WORKSHOP_ITEMTYPE_BUILDING\n'
    '$VISIBILITY 0\n'
    '$ITEM_NAME "Old town squares"\n'
    '$ITEM_DESC "First line\nSecond line"\n'
    '$END\n'
)


def write_mod(workshop, folder, text, encoding='utf-8'):
    mod_dir = workshop / folder
    mod_dir.mkdir(parents=True)
    (mod_dir / 'workshopconfig.ini').write_bytes(text.encode(encoding))
    return mod_dir


# --- parse_config -----------------------------------------------------------

def test_parse_config_reads_all_fields():
    cfg = parse_config(SAMPLE)
    assert cfg.item_id == '3043462563'
    assert cfg.owner_id == '76561198000000001'
    assert cfg.item_type == 'BUILDING'
    assert cfg.item_name == 'Old town squares'
    assert cfg.item_desc == 'First line\nSecond line'


def test_parse_config_accepts_equals_sign_owner_id():
    assert parse_config('$OWNER_ID=123\n').owner_id == '123'


def test_parse_config_defaults_for_missing_fields():
    cfg = parse_config('$VISIBILITY 0\n$END\n')
    assert cfg.owner_id is None
    assert cfg.item_id is None
    assert cfg.item_type == 'Unknown'
    assert cfg.item_name == ''
    assert cfg.item_desc == ''


def test_parse_config_ignores_owner_id_text_inside_description():
    text = '$ITEM_DESC "remember to set $OWNER_ID 999 yourself"\n$END\n'
    assert parse_config(text).owner_id is None


# --- set_owner_id -----------------------------------------------------------

def test_set_owner_id_replaces_space_form():
    assert set_owner_id('$ITEM_ID 1\n$OWNER_ID 111\n$END\n', '222') == \
        '$ITEM_ID 1\n$OWNER_ID 222\n$END\n'


def test_set_owner_id_replaces_equals_form():
    assert set_owner_id('$OWNER_ID=111\n$END\n', '222') == '$OWNER_ID 222\n$END\n'


def test_set_owner_id_replaces_line_without_value():
    # Bug 9: a bare "$OWNER_ID" line used to be left untouched.
    assert set_owner_id('$ITEM_ID 1\n$OWNER_ID\n$END\n', '222') == \
        '$ITEM_ID 1\n$OWNER_ID 222\n$END\n'


def test_set_owner_id_keeps_crlf_line_endings():
    assert set_owner_id('$ITEM_ID 1\r\n$OWNER_ID 5\r\n$END\r\n', '7') == \
        '$ITEM_ID 1\r\n$OWNER_ID 7\r\n$END\r\n'


def test_set_owner_id_inserts_at_top_with_file_newline_style():
    assert set_owner_id('$ITEM_ID 1\r\n$END\r\n', '222') == \
        '$OWNER_ID 222\r\n$ITEM_ID 1\r\n$END\r\n'


def test_set_owner_id_leaves_description_text_alone():
    text = '$OWNER_ID 1\n$ITEM_DESC "set $OWNER_ID 5 first"\n'
    assert set_owner_id(text, '9') == '$OWNER_ID 9\n$ITEM_DESC "set $OWNER_ID 5 first"\n'


def test_set_owner_id_handles_cr_only_line_endings():
    assert set_owner_id('$ITEM_ID 1\r$OWNER_ID 5\r$END\r', '7') == \
        '$ITEM_ID 1\r$OWNER_ID 7\r$END\r'


# --- decode_config ----------------------------------------------------------

@pytest.mark.parametrize('raw, text, encoding', [
    (b'\xef\xbb\xbf$ITEM_NAME "A"\n', '$ITEM_NAME "A"\n', 'utf-8-sig'),
    ('$ITEM_NAME "Хрущёвка"\n'.encode('utf-8'), '$ITEM_NAME "Хрущёвка"\n', 'utf-8'),
    ('$ITEM_NAME "Хрущёвка"\n'.encode('cp1251'), '$ITEM_NAME "Хрущёвка"\n', 'cp1251'),
    (b'$ITEM_NAME "\x98"\n', '$ITEM_NAME "\x98"\n', 'latin-1'),
])
def test_decode_config_detects_encoding_and_round_trips(raw, text, encoding):
    decoded, detected = decode_config(raw)
    assert (decoded, detected) == (text, encoding)
    assert decoded.encode(detected) == raw


# --- files and folders ------------------------------------------------------

def test_find_config_file_matches_any_case(tmp_path):
    (tmp_path / 'WorkshopConfig.ini').write_text('$END\n')
    found = find_config_file(tmp_path)
    assert found is not None and found.name == 'WorkshopConfig.ini'


def test_find_config_file_returns_none_without_config(tmp_path):
    (tmp_path / 'readme.txt').write_text('hi')
    assert find_config_file(tmp_path) is None


def test_read_mod_returns_none_for_folder_without_config(tmp_path):
    assert read_mod(tmp_path) is None


def test_scan_mods_lists_mods_sorted_by_type_then_folder(tmp_path):
    write_mod(tmp_path, 'zeta', '$ITEM_TYPE WORKSHOP_ITEMTYPE_BUILDING\n$ITEM_NAME "Z"\n')
    write_mod(tmp_path, 'Alpha', '$ITEM_TYPE WORKSHOP_ITEMTYPE_BUILDING\n$ITEM_NAME "A"\n')
    write_mod(tmp_path, 'road1', '$ITEM_TYPE WORKSHOP_ITEMTYPE_ROAD\n$ITEM_NAME "R"\n')
    (tmp_path / 'no_config').mkdir()
    (tmp_path / 'stray.txt').write_text('x')

    mods = scan_mods(tmp_path)

    assert [m.folder for m in mods] == ['Alpha', 'zeta', 'road1']


def test_scan_mods_reads_cp1251_names(tmp_path):
    # Bug 10: non-UTF-8 configs used to make the mod vanish from the list.
    write_mod(tmp_path, 'm1', '$ITEM_NAME "Хрущёвка"\n', encoding='cp1251')
    assert [m.item_name for m in scan_mods(tmp_path)] == ['Хрущёвка']


def test_scan_mods_raises_when_workshop_folder_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        scan_mods(tmp_path / 'missing')


# --- apply_owner_id ---------------------------------------------------------

def test_apply_owner_id_rewrites_only_the_owner_line(tmp_path):
    original = '$ITEM_ID 1\r\n$OWNER_ID 5\r\n$ITEM_NAME "Хрущёвка"\r\n'
    mod_dir = write_mod(tmp_path, 'm1', original, encoding='cp1251')

    updated = apply_owner_id(read_mod(mod_dir), '7')

    expected = '$ITEM_ID 1\r\n$OWNER_ID 7\r\n$ITEM_NAME "Хрущёвка"\r\n'.encode('cp1251')
    assert (mod_dir / 'workshopconfig.ini').read_bytes() == expected
    assert updated.owner_id == '7'


def test_apply_owner_id_rejects_non_numeric_id(tmp_path):
    mod_dir = write_mod(tmp_path, 'm1', '$OWNER_ID 5\n')
    with pytest.raises(ValueError):
        apply_owner_id(read_mod(mod_dir), '12a')
    assert (mod_dir / 'workshopconfig.ini').read_bytes() == b'$OWNER_ID 5\n'


@pytest.mark.parametrize('value, valid', [
    ('76561198000000001', True),
    ('1', True),
    ('', False),
    ('12a', False),
    (' 123', False),
    ('1' * 21, False),
])
def test_is_valid_owner_id(value, valid):
    assert is_valid_owner_id(value) is valid


# --- game_folder_from -------------------------------------------------------

@pytest.mark.parametrize('chosen, expected', [
    ('D:/Games/SovietRepublic', 'D:/Games/SovietRepublic'),
    ('D:/Games/SovietRepublic/media_soviet', 'D:/Games/SovietRepublic'),
    ('D:/Games/SovietRepublic/media_soviet/workshop_wip', 'D:/Games/SovietRepublic'),
    ('D:/Games/SovietRepublic/Media_Soviet/Workshop_WIP', 'D:/Games/SovietRepublic'),
    ('D:/Mods/workshop_wip', 'D:/Mods/workshop_wip'),
])
def test_game_folder_from_steps_up_from_inner_game_folders(chosen, expected):
    assert Path(game_folder_from(chosen)) == Path(expected)


# --- InstalledIndex ---------------------------------------------------------

def installed(tmp_path, folder, text):
    return read_mod(write_mod(tmp_path, folder, text))


def test_installed_index_matches_names_ignoring_case_and_punctuation(tmp_path):
    index = InstalledIndex([installed(tmp_path, 'a', '$ITEM_NAME "old_town-pack"\n')])
    assert index.contains(name='Old Town Pack')


def test_installed_index_does_not_match_partial_names(tmp_path):
    # Bug 8: "Old Town" used to count as installed because it is a substring.
    index = InstalledIndex([installed(tmp_path, 'a', '$ITEM_NAME "Old Town Pack"\n')])
    assert not index.contains(name='Old Town')


def test_installed_index_matches_steam_id_against_item_id(tmp_path):
    index = InstalledIndex([installed(tmp_path, 'a', '$ITEM_ID 3043462563\n$ITEM_NAME "X"\n')])
    assert index.contains(name='Something else', steam_id='3043462563')


def test_installed_index_matches_steam_id_against_folder_name(tmp_path):
    index = InstalledIndex([installed(tmp_path, '3043462563', '$ITEM_NAME "X"\n')])
    assert index.contains(name='Other', steam_id='3043462563')


def test_installed_index_never_matches_blank_names(tmp_path):
    index = InstalledIndex([installed(tmp_path, 'a', '$ITEM_NAME "---"\n')])
    assert not index.contains(name='***')
