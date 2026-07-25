"""The single narrow seam through which all model access happens.

Structured output is obtained by forcing a tool call with an explicit schema,
never by parsing JSON out of prose. Reliability comes from the schema.
"""
from __future__ import annotations

import json
from typing import Any, Protocol

from complai.config import Settings


class TruncatedResponse(RuntimeError):
    """The model ran out of output tokens mid-answer. Fail loudly rather than
    hand back a half-built rulebook that looks complete."""


def coerce_json_fields(payload: dict[str, Any]) -> dict[str, Any]:
    """Parse top-level values the model serialised as JSON text.

    Forced tool-use usually yields real arrays and objects, but the model
    intermittently returns a field as a JSON *string* instead. Left alone,
    a stringified list iterates character by character and fails far from
    the cause — observed as 6059 "rules", each one character long.
    """
    out: dict[str, Any] = {}
    for key, value in payload.items():
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith(("[", "{")):
                try:
                    out[key] = json.loads(stripped)
                    continue
                except json.JSONDecodeError:
                    pass
        out[key] = value
    return out


class LLMClient(Protocol):
    def structured(
        self, *, system: str, user: str, schema: dict[str, Any],
        tool_name: str, max_tokens: int = 4096,
    ) -> dict[str, Any]: ...


class AnthropicClient:
    def __init__(self, settings: Settings) -> None:
        from anthropic import Anthropic

        self._client = Anthropic(api_key=settings.api_key)
        self._model = settings.model

    def structured(
        self, *, system: str, user: str, schema: dict[str, Any],
        tool_name: str, max_tokens: int = 4096,
    ) -> dict[str, Any]:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            tools=[{
                "name": tool_name,
                "description": f"Return the structured result as {tool_name}.",
                "input_schema": schema,
            }],
            tool_choice={"type": "tool", "name": tool_name},
        )
        if response.stop_reason == "max_tokens":
            raise TruncatedResponse(
                f"{tool_name!r} response hit the {max_tokens}-token limit and was cut off. "
                "Raise max_tokens or split the input; a truncated rulebook is worse than none."
            )
        for block in response.content:
            if block.type == "tool_use":
                return coerce_json_fields(dict(block.input))
        raise RuntimeError(f"Model returned no tool_use block for {tool_name!r}")


class FakeLLM:
    """Test double. Returns queued responses and records every call."""

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def structured(
        self, *, system: str, user: str, schema: dict[str, Any],
        tool_name: str, max_tokens: int = 4096,
    ) -> dict[str, Any]:
        self.calls.append(
            {"system": system, "user": user, "schema": schema, "tool_name": tool_name}
        )
        assert self._responses, f"FakeLLM exhausted: unexpected call to {tool_name!r}"
        return self._responses.pop(0)
