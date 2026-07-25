"""Stage 3 — decide what kind of text this is before judging it."""
from __future__ import annotations

from complai.llm import LLMClient
from complai.models import GateResult
from complai.prompts import GATE_SYSTEM

GATE_SCHEMA = {
    "type": "object",
    "properties": {
        "input_type": {
            "type": "string",
            "enum": [
                "marketing_communication", "client_communication",
                "product_description", "out_of_scope",
            ],
        },
        "reasoning": {"type": "string"},
    },
    "required": ["input_type", "reasoning"],
}


def classify(text: str, llm: LLMClient) -> GateResult:
    payload = llm.structured(
        system=GATE_SYSTEM,
        user=f"Classify this text:\n\n---\n{text}\n---",
        schema=GATE_SCHEMA,
        tool_name="classification",
        max_tokens=512,
    )
    return GateResult(
        input_type=payload["input_type"],
        reasoning=payload["reasoning"],
        proceed=payload["input_type"] != "out_of_scope",
    )
