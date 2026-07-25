import pytest
import os
from dotenv import load_dotenv as _original_load_dotenv


# Store keys that have been explicitly deleted via monkeypatch
_deleted_keys = set()


@pytest.fixture(autouse=True)
def track_deletions(monkeypatch):
    """Track environment variables deleted by monkeypatch to prevent load_dotenv from restoring them."""
    original_delenv = monkeypatch.delenv

    def tracked_delenv(name, raising=True):
        _deleted_keys.add(name)
        return original_delenv(name, raising=raising)

    monkeypatch.delenv = tracked_delenv
    yield
    _deleted_keys.clear()


@pytest.fixture(autouse=True)
def patch_load_dotenv_respects_deletions(monkeypatch):
    """Ensure load_dotenv respects monkeypatch deletions."""

    def load_dotenv_safe(*args, **kwargs):
        # Call the original load_dotenv
        result = _original_load_dotenv(*args, **kwargs)
        # Remove any keys that were explicitly deleted via monkeypatch
        for key in _deleted_keys:
            os.environ.pop(key, None)
        return result

    monkeypatch.setattr("complai.config.load_dotenv", load_dotenv_safe)
    yield
