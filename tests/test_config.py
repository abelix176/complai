import pytest
from complai.config import load_settings, MissingAPIKey

def test_load_settings_reads_key_and_default_model(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.delenv("COMPLAI_MODEL", raising=False)
    s = load_settings()
    assert s.api_key == "sk-ant-test"
    assert s.model == "claude-sonnet-5"

def test_model_is_overridable(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("COMPLAI_MODEL", "claude-opus-5")
    assert load_settings().model == "claude-opus-5"

def test_missing_key_fails_fast_and_names_the_example_file(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(MissingAPIKey) as exc:
        load_settings()
    assert ".env.example" in str(exc.value)
