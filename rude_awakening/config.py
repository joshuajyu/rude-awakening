"""Settings, read from environment variables (see .env.example)."""

import mimetypes
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from None


def _str(name: str, default: str = "") -> str:
    return os.environ.get(name, "").strip() or default


@dataclass(frozen=True)
class Settings:
    webhook_token: str
    nest_ip: str = ""
    nest_name: str = ""
    alarm_volume: int = 90
    alarm_timeout: int = 600
    test_volume: int = 40
    test_duration: int = 15
    alarm_file: Path = ROOT / "sounds" / "alarm.mp3"
    listen_host: str = "127.0.0.1"
    listen_port: int = 8080
    media_host: str = "10.0.0.2"
    media_port: int = 8081

    @classmethod
    def from_env(cls) -> "Settings":
        alarm_file = Path(_str("ALARM_FILE", "sounds/alarm.mp3"))
        settings = cls(
            webhook_token=_str("WEBHOOK_TOKEN"),
            nest_ip=_str("NEST_IP"),
            nest_name=_str("NEST_NAME"),
            alarm_volume=_int("ALARM_VOLUME", 90),
            alarm_timeout=_int("ALARM_TIMEOUT_SECONDS", 600),
            test_volume=_int("TEST_VOLUME", 40),
            test_duration=_int("TEST_DURATION_SECONDS", 15),
            alarm_file=alarm_file if alarm_file.is_absolute() else ROOT / alarm_file,
            listen_host=_str("LISTEN_HOST", "127.0.0.1"),
            listen_port=_int("LISTEN_PORT", 8080),
            media_host=_str("MEDIA_HOST", "10.0.0.2"),
            media_port=_int("MEDIA_PORT", 8081),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if len(self.webhook_token) < 16:
            raise ValueError("WEBHOOK_TOKEN must be set (at least 16 characters)")
        if not (self.nest_ip or self.nest_name):
            raise ValueError("Set NEST_IP and/or NEST_NAME")
        for name in ("alarm_volume", "test_volume"):
            if not 0 <= getattr(self, name) <= 100:
                raise ValueError(f"{name.upper()} must be between 0 and 100")
        if not self.alarm_file.is_file():
            raise ValueError(f"ALARM_FILE not found: {self.alarm_file}")

    @property
    def media_url(self) -> str:
        return f"http://{self.media_host}:{self.media_port}/{quote(self.alarm_file.name)}"

    @property
    def media_type(self) -> str:
        return mimetypes.guess_type(self.alarm_file.name)[0] or "audio/mpeg"
