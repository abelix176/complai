from complai.llm import FakeLLM

SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}

def test_fake_returns_queued_responses_in_order():
    fake = FakeLLM([{"ok": True}, {"ok": False}])
    assert fake.structured(system="s", user="u", schema=SCHEMA, tool_name="t") == {"ok": True}
    assert fake.structured(system="s", user="u", schema=SCHEMA, tool_name="t") == {"ok": False}

def test_fake_records_calls_for_prompt_assertions():
    fake = FakeLLM([{"ok": True}])
    fake.structured(system="sys", user="usr", schema=SCHEMA, tool_name="verdict")
    assert fake.calls[0]["system"] == "sys"
    assert fake.calls[0]["user"] == "usr"
    assert fake.calls[0]["tool_name"] == "verdict"

def test_fake_raises_when_exhausted():
    fake = FakeLLM([])
    try:
        fake.structured(system="s", user="u", schema=SCHEMA, tool_name="t")
    except AssertionError as e:
        assert "exhausted" in str(e).lower()
    else:
        raise AssertionError("expected FakeLLM to raise when out of responses")
