import pytest

from hadar_tracker.config import Config, ConfigError, DEFAULT_FORUM_URL, load_config


def test_load_config_uses_defaults_when_only_required_present():
    env = {"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_CHAT_ID": "123"}
    config = load_config(env)
    assert isinstance(config, Config)
    assert config.forum_url == DEFAULT_FORUM_URL
    assert config.db_path == "data/hadar.sqlite3"
    assert config.charts_dir == "data/charts"
    assert config.headless is True


def test_load_config_honors_overrides():
    env = {
        "TELEGRAM_BOT_TOKEN": "tok",
        "TELEGRAM_CHAT_ID": "123",
        "FORUM_URL": "https://example.test/x",
        "DB_PATH": "/tmp/x.sqlite3",
        "CHARTS_DIR": "/tmp/charts",
        "HEADLESS": "0",
    }
    config = load_config(env)
    assert config.forum_url == "https://example.test/x"
    assert config.db_path == "/tmp/x.sqlite3"
    assert config.charts_dir == "/tmp/charts"
    assert config.headless is False


def test_load_config_raises_when_required_missing():
    with pytest.raises(ConfigError) as exc:
        load_config({"TELEGRAM_BOT_TOKEN": "tok"})
    assert "TELEGRAM_CHAT_ID" in str(exc.value)
