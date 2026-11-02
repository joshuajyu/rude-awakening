import threading
import time
from types import SimpleNamespace

import pytest

from rude_awakening import alarm
from rude_awakening.alarm import AlarmController, NestUnavailable, Ringer, connect_nest
from rude_awakening.config import Settings


class FakeStatus:
    def __init__(self, state, idle_reason=None):
        self.player_state = state
        self.idle_reason = idle_reason

    player_is_idle = property(lambda self: self.player_state == "IDLE")
    player_is_paused = property(lambda self: self.player_state == "PAUSED")


class FakeMedia:
    """Each play 'lasts' two status polls, then ends the given way."""

    def __init__(self, ends_with=("IDLE", "FINISHED")):
        self.ends_with = ends_with
        self.plays = []
        self.polls = 0
        self.stopped = False

    def play_media(self, url, content_type, **kwargs):
        self.plays.append((url, content_type))
        self.polls = 0

    @property
    def status(self):
        self.polls += 1
        return FakeStatus("PLAYING") if self.polls <= 2 else FakeStatus(*self.ends_with)

    def stop(self):
        self.stopped = True


class FakeCast:
    def __init__(self, media):
        self.status = SimpleNamespace(volume_level=0.3, volume_muted=True)
        self.media_controller = media
        self.volumes, self.mutes = [], []
        self.quit = self.disconnected = False

    def set_volume(self, v):
        self.volumes.append(v)

    def set_volume_muted(self, m):
        self.mutes.append(m)

    def quit_app(self):
        self.quit = True

    def disconnect(self, timeout=None):
        self.disconnected = True


@pytest.fixture
def settings():
    return Settings(webhook_token="x" * 20, nest_ip="10.0.0.50")


def make_ringer(settings, cast):
    return Ringer(settings, connect=lambda ip, name: cast, poll_interval=0.01)


def test_ring_loops_until_timeout_then_restores_volume(settings):
    cast = FakeCast(FakeMedia())
    make_ringer(settings, cast).ring(90, 0.2, threading.Event())

    media = cast.media_controller
    assert len(media.plays) >= 2
    assert media.plays[0] == ("http://10.0.0.2:8081/alarm.mp3", "audio/mpeg")
    assert cast.volumes == [0.9, 0.3]
    assert cast.mutes == [False, True]
    assert media.stopped and cast.quit and cast.disconnected


@pytest.mark.parametrize("ends_with", [("IDLE", "CANCELLED"), ("IDLE", "INTERRUPTED"), ("PAUSED",)])
def test_ring_ends_when_stopped_on_the_speaker(settings, ends_with):
    cast = FakeCast(FakeMedia(ends_with))
    make_ringer(settings, cast).ring(90, 5, threading.Event())
    assert len(cast.media_controller.plays) == 1
    assert cast.volumes == [0.9, 0.3]


def test_ring_ends_on_stop_event(settings):
    cast = FakeCast(FakeMedia())
    stop = threading.Event()
    threading.Timer(0.05, stop.set).start()
    start = time.monotonic()
    make_ringer(settings, cast).ring(90, 5, stop)
    assert time.monotonic() - start < 1
    assert cast.volumes == [0.9, 0.3]


def test_ring_gives_up_quietly_when_nest_unreachable(settings):
    def connect(ip, name):
        raise NestUnavailable("nope")

    stop = threading.Event()
    stop.set()  # skip the retry waits
    Ringer(settings, connect=connect).ring(90, 5, stop)


def test_connect_falls_back_to_discovery(monkeypatch):
    cast = SimpleNamespace(wait=lambda timeout: None)
    browser = SimpleNamespace(stop_discovery=lambda: None)

    def unreachable(*args, **kwargs):
        raise OSError("timed out")

    monkeypatch.setattr(alarm.pychromecast, "get_chromecast_from_host", unreachable)
    monkeypatch.setattr(alarm.pychromecast, "get_listed_chromecasts",
                        lambda friendly_names, **kw: ([cast], browser) if friendly_names == ["Bedroom"] else ([], browser))

    assert connect_nest("10.0.0.50", "Bedroom") is cast
    with pytest.raises(NestUnavailable):
        connect_nest("10.0.0.50", "Kitchen")
    with pytest.raises(NestUnavailable):
        connect_nest("10.0.0.50", "")


def test_connect_prefers_ip(monkeypatch):
    cast = SimpleNamespace(wait=lambda timeout: None)
    monkeypatch.setattr(alarm.pychromecast, "get_chromecast_from_host", lambda host, **kw: cast)
    monkeypatch.setattr(alarm.pychromecast, "get_listed_chromecasts",
                        lambda **kw: pytest.fail("should not discover"))
    assert connect_nest("10.0.0.50", "Bedroom") is cast


def blocking_ring(volume, duration, stop):
    stop.wait(5)


def test_controller_runs_one_alarm_at_a_time():
    c = AlarmController(blocking_ring)
    assert c.start("page", 90, 600) is True
    assert c.start("page", 90, 600) is False
    assert c.start("test", 40, 15) is False
    assert c.stop() is True
    assert not c.active
    assert c.stop() is False
    assert c.start("page", 90, 600) is True
    c.stop()


def test_controller_page_preempts_test():
    c = AlarmController(blocking_ring)
    c.start("test", 40, 15)
    assert c.start("page", 90, 600) is True
    assert c.mode == "page"
    c.stop()


def test_controller_survives_ring_errors():
    def broken(volume, duration, stop):
        raise RuntimeError("boom")

    c = AlarmController(broken)
    assert c.start("page", 90, 600) is True
    time.sleep(0.05)
    assert not c.active
