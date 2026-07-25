from complai.gate import classify
from complai.llm import FakeLLM


def test_marketing_copy_proceeds():
    fake = FakeLLM([{
        "input_type": "marketing_communication",
        "reasoning": "promotional call to action",
    }])
    result = classify("Install our app and get rich tomorrow", fake)
    assert result.input_type == "marketing_communication"
    assert result.proceed is True


def test_out_of_scope_input_does_not_proceed():
    fake = FakeLLM([{"input_type": "out_of_scope", "reasoning": "internal status update"}])
    result = classify("Sprint 14 retro: the deploy pipeline is flaky", fake)
    assert result.proceed is False
    assert "internal status update" in result.reasoning


def test_gate_prompt_lists_every_allowed_type():
    fake = FakeLLM([{"input_type": "product_description", "reasoning": "factual"}])
    classify("A CFD is a derivative instrument.", fake)
    system = fake.calls[0]["system"]
    for expected in (
        "marketing_communication", "client_communication",
        "product_description", "out_of_scope",
    ):
        assert expected in system
