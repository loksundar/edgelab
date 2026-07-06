"""Central configuration: settings.yaml + credentials from .ENV."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SETTINGS_FILE = PROJECT_ROOT / "config" / "settings.yaml"


@dataclass(frozen=True)
class Credentials:
    api_key: str
    client_code: str
    pin: str
    totp_secret: str

    def validate(self) -> None:
        missing = [
            name
            for name, value in (
                ("ANGEL_API_KEY", self.api_key),
                ("ANGEL_CLIENT_CODE", self.client_code),
                ("ANGEL_PIN", self.pin),
                ("ANGEL_TOTP_SECRET", self.totp_secret),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(
                f"Missing credentials in .ENV: {', '.join(missing)}. "
                f"Edit {PROJECT_ROOT / '.ENV'} and fill them in."
            )


@lru_cache(maxsize=1)
def settings() -> dict:
    with open(SETTINGS_FILE, encoding="utf-8") as f:
        return yaml.safe_load(f)


@lru_cache(maxsize=1)
def credentials() -> Credentials:
    load_dotenv(PROJECT_ROOT / ".ENV")
    return Credentials(
        api_key=os.getenv("ANGEL_API_KEY", ""),
        client_code=os.getenv("ANGEL_CLIENT_CODE", ""),
        pin=os.getenv("ANGEL_PIN", ""),
        totp_secret=os.getenv("ANGEL_TOTP_SECRET", ""),
    )


def data_dir() -> Path:
    d = Path(settings()["data"]["dir"])
    d.mkdir(parents=True, exist_ok=True)
    return d
