import pytest

from server.config import ROOT, Settings

VALID = {"WEBHOOK_TOKEN": "t" * 32, "NEST_NAME": "Bedroom speaker"}


@pytest.fixture
def env(monkeypatch):
    for key in ("WEBHOOK_TOKEN", "NEST_IP", "NEST_NAME", "ALARM_VOLUME", "TEST_VOLUME", "ALARM_FILE"):
        monkeypatch.delenv(key, raising=False)

    def set_env(**values):
        for key, value in values.items():
            monkeypatch.setenv(key, value)

    return set_env


def test_defaults(env):
    env(**VALID)
    s = Settings.from_env()
    assert (s.alarm_volume, s.alarm_timeout, s.listen_host, s.listen_port) == (90, 600, "127.0.0.1", 8080)
    assert s.alarm_file == ROOT / "sounds" / "alarm.mp3"
    assert s.media_url == "http://10.0.0.2:8081/alarm.mp3"


@pytest.mark.parametrize("overrides", [
    {"WEBHOOK_TOKEN": ""},
    {"WEBHOOK_TOKEN": "short"},
    {"NEST_NAME": ""},
    {"ALARM_VOLUME": "150"},
    {"ALARM_VOLUME": "loud"},
    {"ALARM_FILE": "sounds/missing.mp3"},
])
def test_invalid_settings_fail_fast(env, overrides):
    env(**{**VALID, **overrides})
    with pytest.raises(ValueError):
        Settings.from_env()
