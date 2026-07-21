import pytest

from hadar_tracker.config import Config, ConfigError, load_config


def test_load_config_uses_defaults_when_only_required_present():
    env = {"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_CHAT_ID": "123"}
    config = load_config(env)
    assert isinstance(config, Config)
    assert config.db_path == "data/hadar.sqlite3"
    assert config.images_dir == "data/images"
    assert config.user_id == 5609
    assert config.forum_id == 1


def test_load_config_honors_overrides():
    env = {
        "TELEGRAM_BOT_TOKEN": "tok",
        "TELEGRAM_CHAT_ID": "123",
        "DB_PATH": "/tmp/x.sqlite3",
        "IMAGES_DIR": "/tmp/images",
        "USER_ID": "42",
        "FORUM_ID": "7",
    }
    config = load_config(env)
    assert config.db_path == "/tmp/x.sqlite3"
    assert config.images_dir == "/tmp/images"
    assert config.user_id == 42
    assert config.forum_id == 7


def test_load_config_raises_when_required_missing():
    with pytest.raises(ConfigError) as exc:
        load_config({"TELEGRAM_BOT_TOKEN": "tok"})
    assert "TELEGRAM_CHAT_ID" in str(exc.value)
