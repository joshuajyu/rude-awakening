"""Talking to the Nest, and making sure only one alarm rings at a time."""

import logging
import threading
import time
from typing import Callable

import pychromecast

from .config import Settings

log = logging.getLogger(__name__)

CONNECT_TIMEOUT = 10
# How long the Nest gets to start playing before we ask again.
START_TIMEOUT = 15


class NestUnavailable(Exception):
    pass


def connect_nest(ip: str, name: str, timeout: float = CONNECT_TIMEOUT):
    """Connect by IP if configured, otherwise (or on failure) discover by name."""
    if ip:
        try:
            cast = pychromecast.get_chromecast_from_host(
                (ip, 8009, None, None, None), tries=1, timeout=timeout
            )
            cast.wait(timeout=timeout)
            return cast
        except Exception as e:
            log.warning("Could not reach Nest at %s: %s", ip, e)
    if name:
        casts, browser = pychromecast.get_listed_chromecasts(
            friendly_names=[name], discovery_timeout=timeout
        )
        browser.stop_discovery()
        if casts:
            cast = casts[0]
            cast.wait(timeout=timeout)
            return cast
        log.warning("No Nest named %r found on the network", name)
    raise NestUnavailable(f"Nest not reachable (ip={ip or '-'}, name={name or '-'})")


class Ringer:
    """Plays the alarm on the Nest in a loop, then puts its volume back."""

    def __init__(self, settings: Settings, connect: Callable = connect_nest, poll_interval: float = 1.0):
        self.settings = settings
        self._connect = lambda: connect(settings.nest_ip, settings.nest_name)
        self.poll_interval = poll_interval

    def check(self) -> bool:
        try:
            self._connect().disconnect(timeout=5)
            return True
        except Exception:
            return False

    def ring(self, volume: int, duration: float, stop: threading.Event) -> None:
        cast = self._connect_with_retries(stop)
        if cast is None:
            return
        prev_volume, prev_muted = cast.status.volume_level, cast.status.volume_muted
        mc = cast.media_controller
        log.info("Ringing at %d%% for up to %ds (was %d%%%s)",
                 volume, duration, round(prev_volume * 100), ", muted" if prev_muted else "")
        try:
            cast.set_volume_muted(False)
            cast.set_volume(volume / 100)
            self._play_until_done(mc, time.monotonic() + duration, stop)
        finally:
            for step in (mc.stop,
                         lambda: cast.set_volume(prev_volume),
                         lambda: cast.set_volume_muted(prev_muted),
                         cast.quit_app):
                try:
                    step()
                except Exception as e:
                    log.warning("Cleanup step failed: %s", e)
            cast.disconnect(timeout=5)
            log.info("Alarm finished; volume restored to %d%%", round(prev_volume * 100))

    def _connect_with_retries(self, stop: threading.Event, attempts: int = 3):
        for attempt in range(1, attempts + 1):
            try:
                return self._connect()
            except Exception as e:
                log.error("Connecting to Nest failed (attempt %d/%d): %s", attempt, attempts, e)
            if stop.wait(5):
                break
        return None

    def _play_until_done(self, mc, deadline: float, stop: threading.Event) -> None:
        while not stop.is_set() and time.monotonic() < deadline:
            mc.play_media(self.settings.media_url, self.settings.media_type,
                          title="Rude Awakening", stream_type="BUFFERED")
            if self._wait_for_track(mc, deadline, stop) == "stopped_on_device":
                log.info("Alarm stopped on the speaker itself")
                return
        if not stop.is_set():
            log.info("Alarm timed out")

    def _wait_for_track(self, mc, deadline: float, stop: threading.Event) -> str:
        """Wait for one playthrough. Returns why it ended."""
        started = False
        start_by = time.monotonic() + START_TIMEOUT
        while not stop.wait(self.poll_interval) and time.monotonic() < deadline:
            status = mc.status
            if status.player_state in ("PLAYING", "BUFFERING"):
                started = True
            elif started and status.player_is_paused:
                return "stopped_on_device"  # someone tapped the Nest
            elif started and status.player_is_idle:
                if status.idle_reason in ("CANCELLED", "INTERRUPTED"):
                    return "stopped_on_device"  # "Hey Google, stop" or another cast
                return "finished"
            elif not started and time.monotonic() > start_by:
                log.warning("Nest did not start playback; retrying")
                return "retry"
        return "done"


class AlarmController:
    """Runs one alarm at a time in a background thread."""

    def __init__(self, ring: Callable[[int, float, threading.Event], None]):
        self._ring = ring
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.mode: str | None = None

    @property
    def active(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, mode: str, volume: int, duration: float) -> bool:
        """Start an alarm. Returns False if one is already ringing.

        A real page takes over from a test; anything else is ignored.
        """
        with self._lock:
            if self.active:
                if not (mode == "page" and self.mode == "test"):
                    return False
                self._stop_and_wait()
            self._stop = threading.Event()
            self.mode = mode
            self._thread = threading.Thread(
                target=self._run, args=(volume, duration, self._stop), name=f"alarm-{mode}", daemon=True
            )
            self._thread.start()
            return True

    def stop(self) -> bool:
        """Stop the alarm and wait for the volume to be restored."""
        with self._lock:
            if not self.active:
                return False
            self._stop_and_wait()
            return True

    def _stop_and_wait(self) -> None:
        self._stop.set()
        self._thread.join(timeout=30)

    def _run(self, volume: int, duration: float, stop: threading.Event) -> None:
        try:
            self._ring(volume, duration, stop)
        except Exception:
            log.exception("Alarm failed")
