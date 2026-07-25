from complai.llm import FakeLLM, coerce_json_fields

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


def test_coerce_parses_a_field_the_model_serialised_as_json_text():
    """Regression: the model intermittently returns `rules` as a JSON string.
    Unparsed, a stringified list iterates character by character — observed as
    6059 "rules", each one character long, failing far from the cause."""
    payload = {"rules": '[{"id": "R1"}, {"id": "R2"}]'}
    assert coerce_json_fields(payload) == {"rules": [{"id": "R1"}, {"id": "R2"}]}


def test_coerce_leaves_ordinary_strings_alone():
    payload = {"reasoning": "no risk warning is present", "confidence": 0.9}
    assert coerce_json_fields(payload) == payload


def test_coerce_leaves_real_lists_alone():
    payload = {"rules": [{"id": "R1"}]}
    assert coerce_json_fields(payload) == payload


def test_coerce_leaves_unparseable_json_like_text_alone():
    payload = {"evidence_span": "{not actually json"}
    assert coerce_json_fields(payload) == payload
