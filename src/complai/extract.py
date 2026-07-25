"""Stage 2 — decomposition. Run once; the output is a committed artifact."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from complai.llm import LLMClient
from complai.models import Rule
from complai.prompts import EXTRACTION_SYSTEM

RULES_PATH = Path("data/rules/rules.json")

RULE_SCHEMA = {
    "type": "object",
    "properties": {
        "rules": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "Stable id, e.g. CYSEC-PS0419-RW-001"},
                    "source_doc": {"type": "string"},
                    "source_ref": {"type": "string", "description": "Section or paragraph reference"},
                    "source_quote": {"type": "string", "description": "Verbatim span from the source"},
                    "title": {"type": "string"},
                    "requirement": {"type": "string"},
                    "category": {"type": "string", "enum": ["mechanical", "judgment"]},
                    "applies_to": {"type": "array", "items": {"type": "string"}},
                    "check_guidance": {"type": "string"},
                    "severity": {"type": "string", "enum": ["high", "medium", "low"]},
                    "counter_example": {
                        "type": "string",
                        "description": "Something explicitly NOT caught by this rule, if stated",
                    },
                },
                "required": [
                    "id", "source_doc", "source_ref", "source_quote", "title",
                    "requirement", "category", "applies_to", "check_guidance", "severity",
                ],
            },
        }
    },
    "required": ["rules"],
}


def locate(quote: str, text: str) -> tuple[int, int] | None:
    """Find a quote in the source, tolerating whitespace differences.

    The model reflows what it quotes — table columns lose their padding, wrapped
    lines get joined — so an exact `find` misses passages that are genuinely
    present. Matching with runs of whitespace treated as equivalent recovers the
    true span, which callers use to snap the quote back to the source's own text.
    """
    if not quote.strip():
        return None
    pattern = r"\s+".join(re.escape(part) for part in quote.split())
    match = re.search(pattern, text)
    return match.span() if match else None


def rule_dicts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Find the list of rule objects, tolerating the wrappers the model adds.

    Forced tool-use does not guarantee the exact shape: the same prompt has
    returned `{"rules": [...]}`, a JSON string, and a double-nested
    `{"rules": {"rules": [...]}}`. Unwrap rather than crash, but refuse
    anything that is not ultimately a list of objects — a silently empty
    rulebook is the failure this must not produce.
    """
    node: Any = payload
    for _ in range(4):
        if isinstance(node, list):
            if all(isinstance(item, dict) for item in node):
                return node
            raise ValueError(f"expected rule objects, got {type(node[0]).__name__} items")
        if isinstance(node, dict):
            node = node.get("rules", node) if "rules" in node else None
            if node is None:
                break
            continue
        break
    raise ValueError(f"could not find a list of rules in payload keys {list(payload)}")


def extract_rules(text: str, source_doc: str, llm: LLMClient) -> list[Rule]:
    payload = llm.structured(
        system=EXTRACTION_SYSTEM,
        user=f"Source document: {source_doc}\n\n---\n\n{text}",
        schema=RULE_SCHEMA,
        tool_name="rules",
        max_tokens=16384,
    )
    rules: list[Rule] = []
    for raw in rule_dicts(payload):
        rule = Rule.from_dict({**raw, "source_doc": raw.get("source_doc") or source_doc})
        rules.append(ground(rule, text))
    return rules


def ground(rule: Rule, text: str) -> Rule:
    """Snap a rule's quote to the source's own wording and record its span.

    Storing the matched substring rather than the model's rendering means
    `source_quote` is verbatim by construction, which is what the verification
    pass and the UI's provenance view both depend on.
    """
    span = locate(rule.source_quote, text)
    if span is None:
        return rule
    return Rule.from_dict(
        {**rule.to_dict(), "source_quote": text[span[0]:span[1]], "source_span": list(span)}
    )


def save_rules(rules: list[Rule], path: Path = RULES_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([r.to_dict() for r in rules], indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def load_rules(path: Path = RULES_PATH) -> list[Rule]:
    return [Rule.from_dict(d) for d in json.loads(path.read_text(encoding="utf-8"))]
