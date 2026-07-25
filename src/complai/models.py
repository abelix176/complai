"""Typed boundaries between pipeline stages."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Category = Literal["mechanical", "judgment"]
Severity = Literal["high", "medium", "low"]
VerdictValue = Literal["compliant", "violation", "not_applicable", "needs_review"]
InputType = Literal[
    "marketing_communication", "client_communication", "product_description", "out_of_scope"
]

_CATEGORIES = {"mechanical", "judgment"}
_SEVERITIES = {"high", "medium", "low"}
_REQUIRED = (
    "id", "source_doc", "source_ref", "source_quote", "title",
    "requirement", "category", "applies_to", "check_guidance", "severity",
)


class InvalidRule(ValueError):
    """A rule dict failed validation. Loud, because silent bad rules are worse."""


@dataclass(frozen=True)
class Rule:
    id: str
    source_doc: str
    source_ref: str
    source_quote: str
    title: str
    requirement: str
    category: Category
    applies_to: list[str]
    check_guidance: str
    severity: Severity
    source_span: tuple[int, int] | None = None
    counter_example: str | None = None

    @property
    def is_mechanical(self) -> bool:
        return self.category == "mechanical"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Rule:
        for key in _REQUIRED:
            value = data.get(key)
            if value is None or (isinstance(value, str) and not value.strip()):
                raise InvalidRule(f"rule {data.get('id', '<no id>')}: missing or empty {key!r}")
        if data["category"] not in _CATEGORIES:
            raise InvalidRule(f"rule {data['id']}: category must be one of {sorted(_CATEGORIES)}")
        if data["severity"] not in _SEVERITIES:
            raise InvalidRule(f"rule {data['id']}: severity must be one of {sorted(_SEVERITIES)}")
        if not isinstance(data["applies_to"], list) or not data["applies_to"]:
            raise InvalidRule(f"rule {data['id']}: applies_to must be a non-empty list")
        span = data.get("source_span")
        return cls(
            id=data["id"], source_doc=data["source_doc"], source_ref=data["source_ref"],
            source_quote=data["source_quote"], title=data["title"],
            requirement=data["requirement"], category=data["category"],
            applies_to=list(data["applies_to"]), check_guidance=data["check_guidance"],
            severity=data["severity"],
            source_span=tuple(span) if span else None,
            counter_example=data.get("counter_example"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "source_doc": self.source_doc, "source_ref": self.source_ref,
            "source_quote": self.source_quote, "title": self.title,
            "requirement": self.requirement, "category": self.category,
            "applies_to": list(self.applies_to), "check_guidance": self.check_guidance,
            "severity": self.severity,
            "source_span": list(self.source_span) if self.source_span else None,
            "counter_example": self.counter_example,
        }


@dataclass
class Verdict:
    rule_id: str
    verdict: VerdictValue
    confidence: float
    reasoning: str
    evidence_span: str | None = None
    verified: bool = False
    verification_note: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Verdict:
        return cls(
            rule_id=data["rule_id"], verdict=data["verdict"],
            confidence=float(data.get("confidence", 0.0)),
            reasoning=data.get("reasoning", ""),
            evidence_span=data.get("evidence_span"),
        )


@dataclass
class GateResult:
    input_type: InputType
    reasoning: str
    proceed: bool


@dataclass
class CheckResult:
    input_type: str
    verdicts: list[Verdict]
    rules_considered: int
    fallback_used: bool

    @property
    def violations(self) -> list[Verdict]:
        return [v for v in self.verdicts if v.verdict == "violation"]

    @property
    def has_violations(self) -> bool:
        return bool(self.violations)


@dataclass
class Attempt:
    iteration: int
    text: str
    violation_count: int


@dataclass
class RevisionResult:
    original: str
    final_text: str
    attempts: list[Attempt] = field(default_factory=list)
    final_check: CheckResult | None = None
    converged: bool = False
