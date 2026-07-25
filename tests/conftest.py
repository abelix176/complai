"""Shared test fixtures.

`load_settings()` calls `load_dotenv()`, so a real `.env` in the working tree would
re-populate a variable a test had just deleted — silently defeating the missing-key
test. Tests own the environment, so dotenv is neutralised for the whole suite.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("complai.config.load_dotenv", lambda *args, **kwargs: False)
