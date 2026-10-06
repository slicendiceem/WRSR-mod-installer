import json

from wrsr_installer.config import AppConfig, load_config, save_config


def test_load_config_reads_the_existing_settings_file_format(tmp_path):
    path = tmp_path / 'config.json'
    path.write_text(json.dumps({'game_folder': 'D:/Games/WRSR', 'target_owner_id': '76561198000000001'}))

    assert load_config(path) == AppConfig(game_folder='D:/Games/WRSR', target_owner_id='76561198000000001')


def test_load_config_turns_numeric_owner_id_into_text(tmp_path):
    path = tmp_path / 'config.json'
    path.write_text(json.dumps({'game_folder': None, 'target_owner_id': 76561198000000001}))

    assert load_config(path).target_owner_id == '76561198000000001'


def test_load_config_falls_back_to_defaults(tmp_path):
    corrupt = tmp_path / 'corrupt.json'
    corrupt.write_text('{not json')

    assert load_config(tmp_path / 'missing.json') == AppConfig()
    assert load_config(corrupt) == AppConfig()


def test_save_config_round_trips(tmp_path):
    path = tmp_path / 'config.json'
    save_config(AppConfig(game_folder='C:/WRSR', target_owner_id='42'), path)

    assert json.loads(path.read_text()) == {'game_folder': 'C:/WRSR', 'target_owner_id': '42'}
    assert load_config(path) == AppConfig(game_folder='C:/WRSR', target_owner_id='42')
