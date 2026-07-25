"""Stage 2 — decomposition. Run once; the output is a committed artifact."""
from __future__ import annotations

import json
from pathlib import Path

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


def _locate(quote: str, text: str) -> tuple[int, int] | None:
    index = text.find(quote)
    return (index, index + len(quote)) if index >= 0 else None


def extract_rules(text: str, source_doc: str, llm: LLMClient) -> list[Rule]:
    payload = llm.structured(
        system=EXTRACTION_SYSTEM,
        user=f"Source document: {source_doc}\n\n---\n\n{text}",
        schema=RULE_SCHEMA,
        tool_name="rules",
        max_tokens=8192,
    )
    rules: list[Rule] = []
    for raw in payload["rules"]:
        rule = Rule.from_dict({**raw, "source_doc": raw.get("source_doc") or source_doc})
        span = _locate(rule.source_quote, text)
        rules.append(rule if span is None else Rule.from_dict({**rule.to_dict(), "source_span": list(span)}))
    return rules


def save_rules(rules: list[Rule], path: Path = RULES_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([r.to_dict() for r in rules], indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def load_rules(path: Path = RULES_PATH) -> list[Rule]:
    return [Rule.from_dict(d) for d in json.loads(path.read_text(encoding="utf-8"))]
