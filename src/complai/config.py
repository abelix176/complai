"""Environment configuration. Fails fast and loudly on a missing key."""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

DEFAULT_MODEL = "claude-sonnet-5"


class MissingAPIKey(RuntimeError):
    """Raised at startup when no Anthropic key is configured."""


@dataclass(frozen=True)
class Settings:
    api_key: str
    model: str


def load_settings() -> Settings:
    load_dotenv()
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise MissingAPIKey(
            "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key: "
            "cp .env.example .env"
        )
    return Settings(api_key=api_key, model=os.environ.get("COMPLAI_MODEL", DEFAULT_MODEL))
