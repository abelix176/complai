# Regulation Compliance Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an LLM-powered compliance agent that ingests CySEC PS-04-2019, decomposes it into checkable rules, and evaluates marketing copy rule-by-rule with source-verified verdicts and an optional compliant-rewrite loop.

**Architecture:** Four separable stages — ingest → extract → gate → check — with a revision loop wrapped around the checker. Rules are extracted once by an LLM and committed as JSON. Checking is two-pass: one screening call across all rules, then adversarial verification of each alleged violation against its verbatim source passage. All LLM access goes through one narrow `LLMClient` protocol so every module is testable with a fake and zero API calls.

**Tech Stack:** Python 3.11+, `anthropic` (tool-use structured output), `pypdf`, `streamlit`, `python-dotenv`, `pytest`, `PyYAML`.

**Spec:** `docs/superpowers/specs/2026-07-25-regulation-compliance-agent-design.md`

## Global Constraints

- Python 3.11+. Type hints on all public functions.
- Default model `claude-sonnet-5`, overridable via `COMPLAI_MODEL`. API key from `ANTHROPIC_API_KEY` via `.env`.
- **Structured output is always via forced tool-use** (`tool_choice={"type": "tool", "name": ...}`) with an explicit `input_schema`. Never parse JSON out of prose.
- **No unit test may make a network call.** LLM-dependent behaviour is covered by the eval harness, not by mocked assertions about model judgement.
- `MAX_ITERATIONS = 3` for the revision loop.
- Commits are authored by Felix. **Never** add `Co-Authored-By: Claude`, "Generated with Claude Code", or any AI attribution. Conventional-commit prefixes (`feat:`, `fix:`, `test:`, `docs:`, `chore:`).
- Nothing from `_private/` is ever committed, quoted verbatim into tracked files, or pushed. No API keys in git.
- Every rule carries a verbatim `source_quote`. No quote, no rule.

**Deviation from spec §2, to be recorded in the README:** the secondary source (MiFID II Art. 24(3) + Delegated Regulation 2017/565 Art. 44) is committed as a hand-curated extract with a provenance header rather than fetched and trimmed programmatically. Reliably trimming EUR-Lex HTML to two articles is not worth budget that belongs to prompts and evals. The primary source (PS-04-2019) *is* fetched and extracted programmatically.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/complai/config.py` | Env loading, model selection, `Settings` |
| `src/complai/llm.py` | `LLMClient` protocol, `AnthropicClient`, `FakeLLM` |
| `src/complai/models.py` | `Rule`, `Verdict`, `GateResult`, `CheckResult`, `Attempt`, `RevisionResult` |
| `src/complai/ingest.py` | PDF fetch/extract, text normalisation |
| `src/complai/extract.py` | Source text → rules (LLM) |
| `src/complai/gate.py` | Input classification |
| `src/complai/check.py` | Rule selection, screening pass, verification pass |
| `src/complai/revise.py` | Rewrite-and-recheck loop |
| `src/complai/report.py` | Terminal / markdown / JSON rendering |
| `src/complai/cli.py` | `python -m complai` command surface |
| `app.py` | Streamlit UI |
| `evals/cases.yaml` | Hand-labelled ground truth |
| `evals/run_eval.py` | Scorer |
| `data/samples/showcase.yaml` | Subagent-generated demo corpus (unlabelled) |

---

## Task 1: Config and LLM client

**Files:**
- Create: `src/complai/config.py`, `src/complai/llm.py`
- Test: `tests/test_config.py`, `tests/test_llm.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Settings(api_key: str, model: str)`, `load_settings() -> Settings`, `MissingAPIKey`; `LLMClient` protocol with `structured(system: str, user: str, schema: dict, tool_name: str, max_tokens: int = 4096) -> dict`; `FakeLLM(responses: list[dict])` recording `.calls`; `AnthropicClient(settings)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_config.py
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
```

```python
# tests/test_llm.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_config.py tests/test_llm.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'complai.config'`

- [ ] **Step 3: Implement**

```python
# src/complai/config.py
"""Environment configuration. Fails fast and loudly on a missing key."""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

DEFAULT_MODEL = "claude-sonnet-5"


class MissingAPIKey(RuntimeError):
    """Raised at startup when no Anthropic key is configured."""


@dataclass(frozen=True)
class Settings:
    api_key: str
    model: str


def load_settings() -> Settings:
    load_dotenv()
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise MissingAPIKey(
            "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key: "
            "cp .env.example .env"
        )
    return Settings(api_key=api_key, model=os.environ.get("COMPLAI_MODEL", DEFAULT_MODEL))
```

```python
# src/complai/llm.py
"""The single narrow seam through which all model access happens.

Structured output is obtained by forcing a tool call with an explicit schema,
never by parsing JSON out of prose. Reliability comes from the schema.
"""
from __future__ import annotations

from typing import Any, Protocol

from complai.config import Settings


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
        for block in response.content:
            if block.type == "tool_use":
                return dict(block.input)
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_config.py tests/test_llm.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add src/complai/config.py src/complai/llm.py tests/test_config.py tests/test_llm.py
git commit -m "feat: add config loading and LLM client seam"
```

---

## Task 2: Domain models

**Files:**
- Create: `src/complai/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Rule`, `Verdict`, `GateResult`, `CheckResult`, `Attempt`, `RevisionResult`, `InvalidRule`. `Rule.from_dict`/`to_dict`, `Verdict.from_dict`, `Rule.is_mechanical`, `CheckResult.violations`, `CheckResult.has_violations`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_models.py
import pytest
from complai.models import Rule, Verdict, CheckResult, InvalidRule

RULE_DICT = {
    "id": "CYSEC-PS0419-RW-001",
    "source_doc": "PS-04-2019",
    "source_ref": "§3.5.12",
    "source_quote": "the CFD provider should not send directly or indirectly a communication",
    "title": "Risk warning must be present",
    "requirement": "Any communication marketing a CFD to retail clients must include the risk warning.",
    "category": "mechanical",
    "applies_to": ["marketing_communication", "client_communication"],
    "check_guidance": "Look for the mandated warning text. Absence is a violation.",
    "severity": "high",
}

def test_rule_round_trips():
    rule = Rule.from_dict(RULE_DICT)
    assert rule.id == "CYSEC-PS0419-RW-001"
    assert rule.is_mechanical
    assert rule.to_dict() == {**RULE_DICT, "source_span": None, "counter_example": None}

def test_rule_without_source_quote_is_rejected():
    bad = {**RULE_DICT, "source_quote": "  "}
    with pytest.raises(InvalidRule) as exc:
        Rule.from_dict(bad)
    assert "source_quote" in str(exc.value)

def test_rule_with_unknown_category_is_rejected():
    with pytest.raises(InvalidRule):
        Rule.from_dict({**RULE_DICT, "category": "vibes"})

def test_not_applicable_is_not_a_violation():
    result = CheckResult(
        input_type="marketing_communication",
        verdicts=[
            Verdict(rule_id="a", verdict="not_applicable", confidence=0.9, reasoning="n/a"),
            Verdict(rule_id="b", verdict="compliant", confidence=0.9, reasoning="fine"),
        ],
        rules_considered=2,
        fallback_used=False,
    )
    assert result.violations == []
    assert result.has_violations is False

def test_violations_are_extracted():
    v = Verdict(rule_id="c", verdict="violation", confidence=0.8, reasoning="no warning")
    result = CheckResult("marketing_communication", [v], rules_considered=1, fallback_used=False)
    assert result.violations == [v]
    assert result.has_violations is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'complai.models'`

- [ ] **Step 3: Implement**

```python
# src/complai/models.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_models.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add src/complai/models.py tests/test_models.py
git commit -m "feat: add typed domain models with loud rule validation"
```

---

## Task 3: Ingestion

**Files:**
- Create: `src/complai/ingest.py`, `data/sources/mifid-fair-clear.txt`
- Test: `tests/test_ingest.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `normalise(raw: str) -> str`, `extract_pdf_text(path: Path) -> str`, `fetch_pdf(url: str, dest: Path) -> Path`, `ingest_primary(dest_dir: Path) -> Path`, `PS04_URL`, `SOURCES_DIR`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ingest.py
from complai.ingest import normalise

def test_dehyphenates_across_line_breaks():
    assert normalise("commu-\nnication") == "communication"

def test_collapses_whitespace_but_keeps_paragraphs():
    assert normalise("a   b\n\n\n\nc") == "a b\n\nc"

def test_strips_bare_page_numbers():
    assert normalise("end of section\n\n27\n\nSECTION G") == "end of section\n\nSECTION G"

def test_preserves_mandated_warning_text_verbatim():
    raw = "The vast majority of retail investor  accounts lose money\nwhen trading CFDs."
    assert normalise(raw) == "The vast majority of retail investor accounts lose money when trading CFDs."
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ingest.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'complai.ingest'`

- [ ] **Step 3: Implement**

```python
# src/complai/ingest.py
"""Stage 1 — regulation source documents into normalised, committed text."""
from __future__ import annotations

import re
import urllib.request
from pathlib import Path

PS04_URL = (
    "https://www.cysec.gov.cy/CMSPages/GetFile.aspx"
    "?guid=2489c262-ffc6-4f64-ab57-90667c953d45"
)
SOURCES_DIR = Path("data/sources")

_HYPHEN_BREAK = re.compile(r"(\w)-\n(\w)")
_PAGE_NUMBER = re.compile(r"\n\s*\d{1,3}\s*\n")
_MULTI_BLANK = re.compile(r"\n{3,}")
_INLINE_WS = re.compile(r"[ \t]+")


def normalise(raw: str) -> str:
    """Repair PDF text extraction artefacts without altering wording.

    Mandated warning text is quoted verbatim in rules, so this must not
    rewrite words — only rejoin hyphenated breaks and collapse whitespace.
    """
    text = _HYPHEN_BREAK.sub(r"\1\2", raw)
    text = _PAGE_NUMBER.sub("\n\n", text)
    text = _MULTI_BLANK.sub("\n\n", text)
    paragraphs = [
        _INLINE_WS.sub(" ", para.replace("\n", " ")).strip()
        for para in text.split("\n\n")
    ]
    return "\n\n".join(p for p in paragraphs if p)


def extract_pdf_text(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    return normalise("\n\n".join(page.extract_text() or "" for page in reader.pages))


def fetch_pdf(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url) as response:
        dest.write_bytes(response.read())
    return dest


def ingest_primary(dest_dir: Path = SOURCES_DIR) -> Path:
    """Fetch PS-04-2019 and write normalised text beside the PDF."""
    pdf_path = dest_dir / "PS-04-2019.pdf"
    if not pdf_path.exists():
        fetch_pdf(PS04_URL, pdf_path)
    text_path = dest_dir / "PS-04-2019.txt"
    text_path.write_text(extract_pdf_text(pdf_path), encoding="utf-8")
    return text_path
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_ingest.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Run the real ingestion and eyeball the output**

```bash
python -c "from complai.ingest import ingest_primary; print(ingest_primary())"
grep -c "vast majority of retail investor accounts lose money" data/sources/PS-04-2019.txt
```

Expected: at least one match. If the Section B–G warning boxes came out mangled, hand-correct them in the text file and note the correction in the README — the spec requires disclosing this.

- [ ] **Step 6: Author the secondary source**

Create `data/sources/mifid-fair-clear.txt` with a provenance header naming the EUR-Lex URLs and retrieval date, then the verbatim text of MiFID II Article 24(3) and Delegated Regulation (EU) 2017/565 Article 44(2)(a)–(b). Keep it under 60 lines; this is a curated extract, not a dump.

- [ ] **Step 7: Commit**

```bash
git add src/complai/ingest.py tests/test_ingest.py data/sources/
git commit -m "feat: add regulation ingestion and commit source texts"
```

---

## Task 4: Rule extraction

**Files:**
- Create: `src/complai/extract.py`, `src/complai/prompts.py`
- Test: `tests/test_extract.py`

**Interfaces:**
- Consumes: `Rule`, `InvalidRule` (Task 2); `LLMClient` (Task 1).
- Produces: `RULE_SCHEMA`, `extract_rules(text: str, source_doc: str, llm: LLMClient) -> list[Rule]`, `save_rules(rules, path)`, `load_rules(path) -> list[Rule]`, `RULES_PATH`. In `prompts.py`: `EXTRACTION_SYSTEM`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_extract.py
import pytest
from complai.extract import extract_rules, save_rules, load_rules
from complai.llm import FakeLLM
from complai.models import InvalidRule

def _rule(rid, **over):
    base = {
        "id": rid, "source_doc": "PS-04-2019", "source_ref": "§3.5.12",
        "source_quote": "quoted passage", "title": "t", "requirement": "r",
        "category": "mechanical", "applies_to": ["marketing_communication"],
        "check_guidance": "g", "severity": "high",
    }
    return {**base, **over}

def test_extract_returns_typed_rules():
    fake = FakeLLM([{"rules": [_rule("R1"), _rule("R2", category="judgment")]}])
    rules = extract_rules("source text", "PS-04-2019", fake)
    assert [r.id for r in rules] == ["R1", "R2"]
    assert rules[0].is_mechanical and not rules[1].is_mechanical

def test_extraction_prompt_demands_checkability_and_quotes():
    fake = FakeLLM([{"rules": [_rule("R1")]}])
    extract_rules("source text", "PS-04-2019", fake)
    system = fake.calls[0]["system"].lower()
    assert "checkable" in system
    assert "verbatim" in system
    assert "source text" in fake.calls[0]["user"]

def test_rule_without_quote_is_rejected_loudly():
    fake = FakeLLM([{"rules": [_rule("R1", source_quote="")]}])
    with pytest.raises(InvalidRule):
        extract_rules("source text", "PS-04-2019", fake)

def test_rules_round_trip_through_disk(tmp_path):
    fake = FakeLLM([{"rules": [_rule("R1")]}])
    rules = extract_rules("source text", "PS-04-2019", fake)
    path = tmp_path / "rules.json"
    save_rules(rules, path)
    assert [r.id for r in load_rules(path)] == ["R1"]

def test_source_span_is_located_when_quote_appears_in_text():
    quote = "the appropriate risk warning"
    text = f"prefix prefix {quote} suffix"
    fake = FakeLLM([{"rules": [_rule("R1", source_quote=quote)]}])
    rules = extract_rules(text, "PS-04-2019", fake)
    start, end = rules[0].source_span
    assert text[start:end] == quote
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_extract.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'complai.extract'`

- [ ] **Step 3: Implement the prompt**

```python
# src/complai/prompts.py
"""Prompts live together so they can be read, diffed and argued about as a set."""

EXTRACTION_SYSTEM = """\
You are a regulatory analyst decomposing a financial-services policy document into an \
auditable compliance checklist.

Your output is used to check a single piece of marketing copy by reading it. Therefore:

1. CHECKABILITY IS MANDATORY. Only produce a rule if a reviewer could decide it by reading \
the marketing text alone. Requirements that depend on the firm's internal systems — actual \
leverage applied, margin close-out implementation, negative balance protection, the quarterly \
recalculation of a loss percentage — are NOT checkable from text. Omit them. Do not restate \
paragraphs as rules; a rule that cannot be violated by a piece of copy is not a rule here.

2. GROUND EVERY RULE. Each rule carries `source_quote`: a verbatim span copied exactly from \
the source document. No quote, no rule. Never paraphrase into the quote field.

3. CLASSIFY THE RULE FAMILY.
   - "mechanical": decidable by inspection — is the mandated wording present, is the correct \
format used, is a prohibited offer being made.
   - "judgment": requires interpretation — is this misleading, does this emphasise benefit \
over risk, is this pressuring.

4. RECORD CARVE-OUTS. If the document explicitly states that something is NOT caught by a \
prohibition, put that in `counter_example` on the relevant rule. Over-flagging is a failure \
mode as serious as under-flagging.

5. SCOPE `applies_to` HONESTLY. Use only: marketing_communication, client_communication, \
product_description. A rule binding any communication that markets, distributes or sells the \
product applies to all three.

Write `requirement` in imperative voice. Write `check_guidance` so it tells the checker what \
evidence to look for and what would count as compliance.
"""
```

- [ ] **Step 4: Implement extraction**

```python
# src/complai/extract.py
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_extract.py -v`
Expected: PASS (5 passed)

- [ ] **Step 6: Commit the code**

```bash
git add src/complai/extract.py src/complai/prompts.py tests/test_extract.py
git commit -m "feat: add LLM rule extraction with checkability constraint"
```

---

## Task 5: Generate and hand-review the rulebook

This is the one task with a real API call and a human judgement step. It produces the committed artifact the whole demo rests on.

**Files:**
- Create: `data/rules/rules.json`
- Modify: `src/complai/cli.py` (created here, extended in Task 10)

- [ ] **Step 1: Add a minimal `extract` command**

```python
# src/complai/cli.py
"""Command surface. `python -m complai <command>`."""
from __future__ import annotations

import argparse
from pathlib import Path

from complai.config import load_settings
from complai.extract import RULES_PATH, extract_rules, save_rules
from complai.ingest import SOURCES_DIR, ingest_primary
from complai.llm import AnthropicClient


def _cmd_ingest(_: argparse.Namespace) -> int:
    print(f"wrote {ingest_primary()}")
    return 0


def _cmd_extract(_: argparse.Namespace) -> int:
    llm = AnthropicClient(load_settings())
    rules = []
    for source in sorted(SOURCES_DIR.glob("*.txt")):
        text = source.read_text(encoding="utf-8")
        found = extract_rules(text, source.stem, llm)
        print(f"{source.stem}: {len(found)} rules")
        rules.extend(found)
    save_rules(rules, RULES_PATH)
    print(f"wrote {RULES_PATH} ({len(rules)} rules)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="complai")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("ingest", help="fetch and normalise regulation sources").set_defaults(fn=_cmd_ingest)
    sub.add_parser("extract", help="regenerate the rulebook").set_defaults(fn=_cmd_extract)
    args = parser.parse_args(argv)
    return args.fn(args)
```

```python
# src/complai/__main__.py
import sys

from complai.cli import main

sys.exit(main())
```

- [ ] **Step 2: Run extraction for real**

Run: `python -m complai extract`
Expected: prints a rule count per source and writes `data/rules/rules.json`. Expect roughly 15–30 rules total.

- [ ] **Step 3: Hand-review the rulebook — do not skip this**

Read `data/rules/rules.json` end to end and check:
- Every `source_quote` actually appears in the corresponding `data/sources/*.txt` (spans that failed to locate are `null` — investigate each one; a null span usually means the model paraphrased).
- No rule requires access to firm-internal systems. Delete any that do.
- The §3.4.10 tiered fee/spread carve-out appears as a `counter_example` on the incentives rule. **If it is missing, add it by hand** — it is load-bearing for eval case 4.
- The mandated warning texts (Sections B, C, D, E, F, G) are quoted accurately.

Record any hand-corrections; they go in the README. Hand-correcting a generated artifact is legitimate and worth disclosing — it is how this would work in production.

- [ ] **Step 4: Commit**

```bash
git add src/complai/cli.py src/complai/__main__.py data/rules/rules.json
git commit -m "feat: add ingest/extract commands and generate reviewed rulebook"
```

---

## Task 6: Input gate

**Files:**
- Create: `src/complai/gate.py`
- Modify: `src/complai/prompts.py` (append `GATE_SYSTEM`)
- Test: `tests/test_gate.py`

**Interfaces:**
- Consumes: `GateResult` (Task 2), `LLMClient` (Task 1).
- Produces: `GATE_SCHEMA`, `classify(text: str, llm: LLMClient) -> GateResult`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_gate.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_gate.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'complai.gate'`

- [ ] **Step 3: Append the prompt**

```python
# append to src/complai/prompts.py
GATE_SYSTEM = """\
You classify a submitted piece of text before it is checked for regulatory compliance.

Return exactly one input_type:
- "marketing_communication": promotes a product or firm — ads, social posts, landing page \
copy, push notifications, affiliate content, calls to action.
- "client_communication": addressed to an existing client about their account — margin \
calls, statements, service notices.
- "product_description": neutral factual explanation of an instrument or feature, with no \
promotional intent.
- "out_of_scope": anything else — internal engineering notes, meeting minutes, code, \
unrelated prose.

This tool checks marketing materials against financial regulation. If the text is not a \
communication to actual or prospective clients, say out_of_scope rather than straining to \
find a category. Give one sentence of reasoning naming the signal you used.
"""
```

- [ ] **Step 4: Implement**

```python
# src/complai/gate.py
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_gate.py -v`
Expected: PASS (3 passed)

- [ ] **Step 6: Commit**

```bash
git add src/complai/gate.py src/complai/prompts.py tests/test_gate.py
git commit -m "feat: add input gate so non-marketing text is declined"
```

---

## Task 7: Two-pass compliance check

**Files:**
- Create: `src/complai/check.py`
- Modify: `src/complai/prompts.py` (append `SCREEN_SYSTEM`, `VERIFY_SYSTEM`)
- Test: `tests/test_check.py`

**Interfaces:**
- Consumes: `Rule`, `Verdict`, `CheckResult` (Task 2), `LLMClient` (Task 1).
- Produces: `select_rules(rules, input_type, min_rules=3) -> tuple[list[Rule], bool]`, `screen(text, rules, llm) -> list[Verdict]`, `verify(text, verdict, rule, llm) -> Verdict`, `check(text, rules, llm, input_type, verify_violations=True) -> CheckResult`, `SCREEN_SCHEMA`, `VERIFY_SCHEMA`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_check.py
from complai.check import check, screen, select_rules, verify
from complai.llm import FakeLLM
from complai.models import Rule, Verdict

def _rule(rid, applies_to=None, **over):
    return Rule.from_dict({
        "id": rid, "source_doc": "PS-04-2019", "source_ref": "§3.5.12",
        "source_quote": "verbatim passage", "title": "t", "requirement": "r",
        "category": "mechanical",
        "applies_to": applies_to or ["marketing_communication"],
        "check_guidance": "g", "severity": "high", **over,
    })

MARKETING = ["marketing_communication"]
BOTH = ["marketing_communication", "client_communication"]

def test_select_rules_filters_by_input_type():
    rules = [_rule(f"R{i}", MARKETING) for i in range(4)] + [_rule("C1", ["client_communication"])]
    selected, fallback = select_rules(rules, "marketing_communication")
    assert [r.id for r in selected] == ["R0", "R1", "R2", "R3"]
    assert fallback is False

def test_select_rules_falls_back_to_full_book_when_filter_is_too_narrow():
    rules = [_rule("R0", MARKETING), _rule("C1", ["client_communication"])]
    selected, fallback = select_rules(rules, "client_communication")
    assert len(selected) == 2
    assert fallback is True

def test_screen_makes_one_call_for_all_rules():
    rules = [_rule("R1"), _rule("R2")]
    fake = FakeLLM([{"verdicts": [
        {"rule_id": "R1", "verdict": "violation", "confidence": 0.9,
         "reasoning": "no warning", "evidence_span": "get rich"},
        {"rule_id": "R2", "verdict": "compliant", "confidence": 0.8, "reasoning": "fine"},
    ]}])
    verdicts = screen("get rich tomorrow", rules, fake)
    assert len(fake.calls) == 1
    assert [v.verdict for v in verdicts] == ["violation", "compliant"]

def test_screen_prompt_includes_counter_examples():
    rules = [_rule("R1", counter_example="tiered fee discounts are not caught")]
    fake = FakeLLM([{"verdicts": []}])
    screen("text", rules, fake)
    assert "tiered fee discounts are not caught" in fake.calls[0]["user"]

def test_verify_confirms_a_violation():
    rule = _rule("R1")
    v = Verdict(rule_id="R1", verdict="violation", confidence=0.9, reasoning="no warning")
    fake = FakeLLM([{"confirmed": True, "note": "no warning text present"}])
    out = verify("text", v, rule, fake)
    assert out.verdict == "violation"
    assert out.verified is True
    assert out.verification_note == "no warning text present"

def test_verify_overturns_and_downgrades_to_needs_review():
    rule = _rule("R1")
    v = Verdict(rule_id="R1", verdict="violation", confidence=0.9, reasoning="looks like a bonus")
    fake = FakeLLM([{"confirmed": False, "note": "this is a tiered spread, expressly carved out"}])
    out = verify("text", v, rule, fake)
    assert out.verdict == "needs_review"
    assert out.verified is True
    assert "carved out" in out.verification_note

def test_verify_prompt_carries_the_verbatim_source_quote():
    rule = _rule("R1")
    v = Verdict(rule_id="R1", verdict="violation", confidence=0.9, reasoning="r")
    fake = FakeLLM([{"confirmed": True, "note": "n"}])
    verify("text", v, rule, fake)
    assert "verbatim passage" in fake.calls[0]["user"]

def test_check_verifies_only_violations():
    rules = [_rule("R1"), _rule("R2"), _rule("R3")]
    fake = FakeLLM([
        {"verdicts": [
            {"rule_id": "R1", "verdict": "violation", "confidence": 0.9, "reasoning": "a"},
            {"rule_id": "R2", "verdict": "compliant", "confidence": 0.9, "reasoning": "b"},
            {"rule_id": "R3", "verdict": "not_applicable", "confidence": 0.9, "reasoning": "c"},
        ]},
        {"confirmed": True, "note": "confirmed"},
    ])
    result = check("text", rules, fake, "marketing_communication")
    assert len(fake.calls) == 2  # one screen + one verification
    assert result.has_violations
    assert result.violations[0].verified is True

def test_check_can_skip_verification():
    rules = [_rule("R1"), _rule("R2"), _rule("R3")]
    fake = FakeLLM([{"verdicts": [
        {"rule_id": "R1", "verdict": "violation", "confidence": 0.9, "reasoning": "a"},
    ]}])
    result = check("text", rules, fake, "marketing_communication", verify_violations=False)
    assert len(fake.calls) == 1
    assert result.violations[0].verified is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_check.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'complai.check'`

- [ ] **Step 3: Append the prompts**

```python
# append to src/complai/prompts.py
SCREEN_SYSTEM = """\
You are a compliance officer reviewing a communication against a fixed rulebook. You will \
receive the full rulebook and one piece of text. Return exactly one verdict per rule, in the \
order given.

Verdicts:
- "violation": the text breaches this rule.
- "compliant": the rule applies to this text and the text satisfies it.
- "not_applicable": the rule cannot bind this text at all (e.g. a rule about \
character-limited third-party formats, for a long webpage). Never use this to avoid a \
judgement call.
- "needs_review": genuinely ambiguous; a human should decide.

Rules:
1. QUOTE YOUR EVIDENCE. Set evidence_span to the exact substring of the submitted text that \
drives your verdict. If the violation is an ABSENCE (a required warning is missing), leave \
evidence_span empty and say so in reasoning.
2. RESPECT CARVE-OUTS. Where a rule carries a counter-example, check it before flagging. \
Flagging conduct the regulator expressly permits is as much a failure as missing a breach.
3. MECHANICAL rules are decided by inspection — is the required wording present, is the \
format right. Do not reason around them; look.
4. JUDGMENT rules require interpretation. Say which words create the impression, and why a \
retail reader would be misled or pressured.
5. Confidence is your honest probability that a compliance officer would agree with you.
"""

VERIFY_SYSTEM = """\
You are a skeptical reviewer auditing a colleague's alleged compliance violation. You are \
shown the regulation's verbatim text, the submitted communication, and the alleged breach.

Your job is to try to OVERTURN the finding. Confirm it only if the verbatim regulatory text \
actually prohibits what the communication actually does.

Overturn when: the quoted regulation does not say what the finding claims; the conduct falls \
within an express carve-out; the rule does not bind this kind of communication; or the \
finding rests on text that is not present in the submission.

Be honest rather than contrarian — a correct finding should be confirmed. Give one sentence \
of reasoning either way.
"""
```

- [ ] **Step 4: Implement**

```python
# src/complai/check.py
"""Stage 4 — screen every rule in one call, then verify each hit against source."""
from __future__ import annotations

from complai.llm import LLMClient
from complai.models import CheckResult, Rule, Verdict
from complai.prompts import SCREEN_SYSTEM, VERIFY_SYSTEM

SCREEN_SCHEMA = {
    "type": "object",
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "rule_id": {"type": "string"},
                    "verdict": {
                        "type": "string",
                        "enum": ["compliant", "violation", "not_applicable", "needs_review"],
                    },
                    "confidence": {"type": "number"},
                    "reasoning": {"type": "string"},
                    "evidence_span": {"type": "string"},
                },
                "required": ["rule_id", "verdict", "confidence", "reasoning"],
            },
        }
    },
    "required": ["verdicts"],
}

VERIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "confirmed": {"type": "boolean"},
        "note": {"type": "string"},
    },
    "required": ["confirmed", "note"],
}


def _render_rule(rule: Rule) -> str:
    lines = [
        f"### {rule.id} [{rule.category}, severity={rule.severity}]",
        f"Title: {rule.title}",
        f"Requirement: {rule.requirement}",
        f"Source: {rule.source_doc} {rule.source_ref}",
        f"How to check: {rule.check_guidance}",
    ]
    if rule.counter_example:
        lines.append(f"NOT a violation: {rule.counter_example}")
    return "\n".join(lines)


def select_rules(
    rules: list[Rule], input_type: str, min_rules: int = 3
) -> tuple[list[Rule], bool]:
    """Narrow the rulebook to the input type.

    A gate misfire must degrade to over-checking, never to a silent all-clear,
    so too-narrow a selection falls back to the whole book.
    """
    filtered = [r for r in rules if input_type in r.applies_to]
    if len(filtered) < min_rules:
        return rules, True
    return filtered, False


def screen(text: str, rules: list[Rule], llm: LLMClient) -> list[Verdict]:
    rulebook = "\n\n".join(_render_rule(r) for r in rules)
    payload = llm.structured(
        system=SCREEN_SYSTEM,
        user=(
            f"# RULEBOOK ({len(rules)} rules)\n\n{rulebook}\n\n"
            f"# SUBMITTED COMMUNICATION\n\n---\n{text}\n---\n\n"
            f"Return one verdict per rule, {len(rules)} in total."
        ),
        schema=SCREEN_SCHEMA,
        tool_name="verdicts",
        max_tokens=8192,
    )
    return [Verdict.from_dict(d) for d in payload["verdicts"]]


def verify(text: str, verdict: Verdict, rule: Rule, llm: LLMClient) -> Verdict:
    payload = llm.structured(
        system=VERIFY_SYSTEM,
        user=(
            f"# REGULATION (verbatim, {rule.source_doc} {rule.source_ref})\n"
            f"{rule.source_quote}\n\n"
            f"# RULE AS RECORDED\n{rule.requirement}\n\n"
            f"# SUBMITTED COMMUNICATION\n---\n{text}\n---\n\n"
            f"# ALLEGED VIOLATION\n{verdict.reasoning}\n"
            f"Cited evidence: {verdict.evidence_span or '(none — alleged absence)'}"
        ),
        schema=VERIFY_SCHEMA,
        tool_name="verification",
        max_tokens=1024,
    )
    verdict.verified = True
    verdict.verification_note = payload["note"]
    if not payload["confirmed"]:
        verdict.verdict = "needs_review"
    return verdict


def check(
    text: str,
    rules: list[Rule],
    llm: LLMClient,
    input_type: str,
    verify_violations: bool = True,
) -> CheckResult:
    selected, fallback = select_rules(rules, input_type)
    verdicts = screen(text, selected, llm)
    if verify_violations:
        by_id = {r.id: r for r in selected}
        for verdict in verdicts:
            if verdict.verdict == "violation" and verdict.rule_id in by_id:
                verify(text, verdict, by_id[verdict.rule_id], llm)
    return CheckResult(
        input_type=input_type,
        verdicts=verdicts,
        rules_considered=len(selected),
        fallback_used=fallback,
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_check.py -v`
Expected: PASS (9 passed)

- [ ] **Step 6: Commit**

```bash
git add src/complai/check.py src/complai/prompts.py tests/test_check.py
git commit -m "feat: add two-pass compliance check with adversarial verification"
```

---

## Task 8: Reporting

**Files:**
- Create: `src/complai/report.py`
- Test: `tests/test_report.py`

**Interfaces:**
- Consumes: `CheckResult`, `Rule`, `Verdict` (Task 2).
- Produces: `sort_verdicts(verdicts, rules) -> list[Verdict]`, `render_terminal(result, rules) -> str`, `render_markdown(result, rules) -> str`, `to_json(result) -> str`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_report.py
import json

from complai.models import CheckResult, Rule, Verdict
from complai.report import render_markdown, render_terminal, sort_verdicts, to_json

def _rule(rid, severity="high"):
    return Rule.from_dict({
        "id": rid, "source_doc": "PS-04-2019", "source_ref": "§3.5.12",
        "source_quote": "verbatim passage", "title": f"Title {rid}", "requirement": "r",
        "category": "mechanical", "applies_to": ["marketing_communication"],
        "check_guidance": "g", "severity": severity,
    })

def test_violations_sort_first_then_by_severity():
    rules = [_rule("A", "low"), _rule("B", "high"), _rule("C", "high")]
    verdicts = [
        Verdict("A", "violation", 0.9, "low sev violation"),
        Verdict("C", "compliant", 0.9, "fine"),
        Verdict("B", "violation", 0.9, "high sev violation"),
    ]
    ordered = sort_verdicts(verdicts, rules)
    assert [v.rule_id for v in ordered] == ["B", "A", "C"]

def test_terminal_report_names_every_rule_and_shows_the_citation():
    rules = [_rule("A")]
    result = CheckResult("marketing_communication", [Verdict("A", "violation", 0.9, "no warning")], 1, False)
    out = render_terminal(result, rules)
    assert "Title A" in out
    assert "§3.5.12" in out
    assert "no warning" in out

def test_report_discloses_the_fallback():
    rules = [_rule("A")]
    result = CheckResult("client_communication", [Verdict("A", "compliant", 0.9, "ok")], 1, True)
    assert "full rulebook" in render_terminal(result, rules).lower()

def test_markdown_report_has_a_verdict_table():
    rules = [_rule("A")]
    result = CheckResult("marketing_communication", [Verdict("A", "violation", 0.9, "x")], 1, False)
    md = render_markdown(result, rules)
    assert "| Rule |" in md
    assert "VIOLATION" in md.upper()

def test_json_output_round_trips():
    rules = [_rule("A")]
    result = CheckResult("marketing_communication", [Verdict("A", "violation", 0.9, "x")], 1, False)
    parsed = json.loads(to_json(result))
    assert parsed["input_type"] == "marketing_communication"
    assert parsed["verdicts"][0]["rule_id"] == "A"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_report.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'complai.report'`

- [ ] **Step 3: Implement**

```python
# src/complai/report.py
"""Rendering only. Never calls the API, never touches the filesystem."""
from __future__ import annotations

import json
from dataclasses import asdict

from complai.models import CheckResult, Rule, Verdict

_VERDICT_ORDER = {"violation": 0, "needs_review": 1, "compliant": 2, "not_applicable": 3}
_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
_MARK = {
    "violation": "✗", "needs_review": "?", "compliant": "✓", "not_applicable": "–",
}


def sort_verdicts(verdicts: list[Verdict], rules: list[Rule]) -> list[Verdict]:
    severity = {r.id: r.severity for r in rules}
    return sorted(
        verdicts,
        key=lambda v: (
            _VERDICT_ORDER.get(v.verdict, 9),
            _SEVERITY_ORDER.get(severity.get(v.rule_id, "low"), 9),
            v.rule_id,
        ),
    )


def _header(result: CheckResult) -> list[str]:
    lines = [
        f"Input classified as: {result.input_type}",
        f"Rules considered: {result.rules_considered}",
    ]
    if result.fallback_used:
        lines.append(
            "Note: rule filtering was too narrow, so the full rulebook was applied."
        )
    violations = len(result.violations)
    lines.append(
        f"Result: {violations} violation(s)" if violations else "Result: no violations found"
    )
    return lines


def render_terminal(result: CheckResult, rules: list[Rule]) -> str:
    by_id = {r.id: r for r in rules}
    lines = _header(result) + [""]
    for verdict in sort_verdicts(result.verdicts, rules):
        rule = by_id.get(verdict.rule_id)
        title = rule.title if rule else verdict.rule_id
        ref = f"{rule.source_doc} {rule.source_ref}" if rule else "unknown source"
        mark = _MARK.get(verdict.verdict, "?")
        lines.append(f"{mark} [{verdict.verdict.upper()}] {title}  ({ref})")
        lines.append(f"    {verdict.reasoning}")
        if verdict.evidence_span:
            lines.append(f"    evidence: “{verdict.evidence_span}”")
        if verdict.verified:
            lines.append(f"    verified against source: {verdict.verification_note}")
        lines.append(f"    confidence: {verdict.confidence:.0%}")
        lines.append("")
    return "\n".join(lines)


def render_markdown(result: CheckResult, rules: list[Rule]) -> str:
    by_id = {r.id: r for r in rules}
    lines = ["# Compliance report", ""] + _header(result)
    lines += ["", "| Rule | Verdict | Severity | Source | Reasoning |", "|---|---|---|---|---|"]
    for verdict in sort_verdicts(result.verdicts, rules):
        rule = by_id.get(verdict.rule_id)
        title = rule.title if rule else verdict.rule_id
        severity = rule.severity if rule else "?"
        ref = f"{rule.source_doc} {rule.source_ref}" if rule else "?"
        reasoning = verdict.reasoning.replace("|", "\\|")
        lines.append(
            f"| {title} | **{verdict.verdict.upper()}** | {severity} | {ref} | {reasoning} |"
        )
    return "\n".join(lines) + "\n"


def to_json(result: CheckResult) -> str:
    return json.dumps(asdict(result), indent=2, ensure_ascii=False)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_report.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add src/complai/report.py tests/test_report.py
git commit -m "feat: add terminal, markdown and json reporting"
```

---

## Task 9: Revision loop

**Files:**
- Create: `src/complai/revise.py`
- Modify: `src/complai/prompts.py` (append `REVISE_SYSTEM`)
- Test: `tests/test_revise.py`

**Interfaces:**
- Consumes: `check` (Task 7), `Rule`, `Attempt`, `RevisionResult` (Task 2).
- Produces: `MAX_ITERATIONS`, `REVISE_SCHEMA`, `propose(text, violations, rules, llm) -> str`, `revise(text, rules, llm, input_type, max_iterations=MAX_ITERATIONS) -> RevisionResult`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_revise.py
from complai.llm import FakeLLM
from complai.models import Rule
from complai.revise import MAX_ITERATIONS, revise

def _rule(rid):
    return Rule.from_dict({
        "id": rid, "source_doc": "PS-04-2019", "source_ref": "§3.5.12",
        "source_quote": "verbatim passage", "title": "t", "requirement": "r",
        "category": "mechanical", "applies_to": ["marketing_communication"],
        "check_guidance": "g", "severity": "high",
    })

RULES = [_rule("R1"), _rule("R2"), _rule("R3")]

def _screen(*verdicts):
    return {"verdicts": [
        {"rule_id": rid, "verdict": v, "confidence": 0.9, "reasoning": "r"}
        for rid, v in verdicts
    ]}

def test_clean_text_is_never_rewritten():
    fake = FakeLLM([
        _screen(("R1", "compliant")),          # inner fast check
        _screen(("R1", "compliant")),          # final verified check
    ])
    result = revise("already compliant copy", RULES, fake, "marketing_communication")
    assert result.final_text == "already compliant copy"
    assert result.converged is True
    assert len(result.attempts) == 1
    assert result.attempts[0].violation_count == 0

def test_loop_rewrites_until_clean_and_records_the_trajectory():
    fake = FakeLLM([
        _screen(("R1", "violation"), ("R2", "violation")),   # attempt 1: 2 violations
        {"revised_text": "better copy"},
        _screen(("R1", "violation")),                        # attempt 2: 1 violation
        {"revised_text": "compliant copy"},
        _screen(("R1", "compliant")),                        # attempt 3: clean
        _screen(("R1", "compliant")),                        # final verified check
    ])
    result = revise("get rich tomorrow", RULES, fake, "marketing_communication")
    assert result.final_text == "compliant copy"
    assert result.converged is True
    assert [a.violation_count for a in result.attempts] == [2, 1, 0]

def test_loop_stops_at_max_iterations_without_converging():
    responses = []
    for _ in range(MAX_ITERATIONS):
        responses.append(_screen(("R1", "violation")))   # inner fast check
        responses.append({"revised_text": "still bad"})  # rewrite
    responses.append(_screen(("R1", "violation")))       # final check, still failing
    responses.append({"confirmed": True, "note": "still no warning"})  # its verification
    fake = FakeLLM(responses)
    result = revise("hopeless", RULES, fake, "marketing_communication")
    assert result.converged is False
    assert len(result.attempts) == MAX_ITERATIONS
    assert result.final_check.violations[0].verified is True

def test_revision_prompt_demands_verbatim_warning_insertion():
    fake = FakeLLM([
        _screen(("R1", "violation")),
        {"revised_text": "fixed"},
        _screen(("R1", "compliant")),
        _screen(("R1", "compliant")),
    ])
    revise("bad copy", RULES, fake, "marketing_communication")
    revise_call = [c for c in fake.calls if c["tool_name"] == "revision"][0]
    assert "verbatim" in revise_call["system"].lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_revise.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'complai.revise'`

- [ ] **Step 3: Append the prompt**

```python
# append to src/complai/prompts.py
REVISE_SYSTEM = """\
You rewrite non-compliant marketing copy so that it satisfies the regulation while keeping as \
much of its marketing intent and voice as the rules allow.

Rules for the rewrite:
1. Where a regulation mandates specific wording, insert that wording VERBATIM. Do not \
paraphrase mandated risk warnings — the exact text is the requirement.
2. Where a claim cannot be made compliantly, DELETE it. A hedged version of a prohibited \
promise is still a prohibited promise, and hedging into meaninglessness is worse copy than \
cutting.
3. Do not add claims, figures, or percentages that were not in the original. If a rule \
requires a provider-specific number you do not have, use the standard variant of the warning \
that does not require one.
4. Keep the format and length plausible for the original medium.

Return only the rewritten text.
"""
```

- [ ] **Step 4: Implement**

```python
# src/complai/revise.py
"""Stage 5 — propose a compliant rewrite, then re-check it. Cheap inner loop,
verified outer verdict.

Known weakness: the same model writes and judges. The trajectory is recorded so a
reviewer can see the work rather than trust a suspiciously clean result.
"""
from __future__ import annotations

from complai.check import check
from complai.llm import LLMClient
from complai.models import Attempt, Rule, RevisionResult, Verdict
from complai.prompts import REVISE_SYSTEM

MAX_ITERATIONS = 3

REVISE_SCHEMA = {
    "type": "object",
    "properties": {"revised_text": {"type": "string"}},
    "required": ["revised_text"],
}


def propose(text: str, violations: list[Verdict], rules: list[Rule], llm: LLMClient) -> str:
    by_id = {r.id: r for r in rules}
    findings = []
    for v in violations:
        rule = by_id.get(v.rule_id)
        findings.append(
            f"- {rule.title if rule else v.rule_id}: {v.reasoning}\n"
            f"  Requirement: {rule.requirement if rule else '(unknown)'}\n"
            f"  Mandated source text: {rule.source_quote if rule else '(unknown)'}"
        )
    payload = llm.structured(
        system=REVISE_SYSTEM,
        user=(
            f"# ORIGINAL COPY\n---\n{text}\n---\n\n"
            f"# VIOLATIONS TO FIX\n" + "\n".join(findings)
        ),
        schema=REVISE_SCHEMA,
        tool_name="revision",
        max_tokens=2048,
    )
    return payload["revised_text"]


def revise(
    text: str,
    rules: list[Rule],
    llm: LLMClient,
    input_type: str,
    max_iterations: int = MAX_ITERATIONS,
) -> RevisionResult:
    current = text
    attempts: list[Attempt] = []
    converged = False

    for iteration in range(1, max_iterations + 1):
        fast = check(current, rules, llm, input_type, verify_violations=False)
        attempts.append(Attempt(iteration, current, len(fast.violations)))
        if not fast.has_violations:
            converged = True
            break
        current = propose(current, fast.violations, rules, llm)

    final = check(current, rules, llm, input_type, verify_violations=True)
    return RevisionResult(
        original=text,
        final_text=current,
        attempts=attempts,
        final_check=final,
        converged=converged and not final.has_violations,
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_revise.py -v`
Expected: PASS (4 passed)

- [ ] **Step 6: Commit**

```bash
git add src/complai/revise.py src/complai/prompts.py tests/test_revise.py
git commit -m "feat: add rewrite-and-recheck revision loop"
```

---

## Task 10: Complete the CLI

**Files:**
- Modify: `src/complai/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `complai check`, `complai revise` commands; `_read_text(args) -> str`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli.py
import pytest
from complai.cli import _read_text

def test_reads_text_from_positional_argument():
    class Args:
        text = "inline copy"
        file = None
    assert _read_text(Args()) == "inline copy"

def test_reads_text_from_file(tmp_path):
    path = tmp_path / "copy.txt"
    path.write_text("copy from disk", encoding="utf-8")
    class Args:
        text = None
        file = str(path)
    assert _read_text(Args()) == "copy from disk"

def test_missing_input_is_an_error():
    class Args:
        text = None
        file = None
    with pytest.raises(SystemExit):
        _read_text(Args())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli.py -v`
Expected: FAIL — `ImportError: cannot import name '_read_text'`

- [ ] **Step 3: Implement**

Add to `src/complai/cli.py`:

```python
import json
import sys

from complai.check import check
from complai.extract import load_rules
from complai.gate import classify
from complai.report import render_terminal, to_json
from complai.revise import revise


def _read_text(args) -> str:
    if getattr(args, "text", None):
        return args.text
    if getattr(args, "file", None):
        return Path(args.file).read_text(encoding="utf-8")
    raise SystemExit("Provide text as an argument or use --file")


def _gate_or_exit(text: str, llm) -> str:
    gate = classify(text, llm)
    if not gate.proceed:
        print(
            f"Declined: this does not look like a communication to clients "
            f"({gate.input_type}).\nReason: {gate.reasoning}\n"
            f"This tool checks marketing materials against CySEC rules."
        )
        raise SystemExit(2)
    print(f"Input type: {gate.input_type} — {gate.reasoning}\n")
    return gate.input_type


def _cmd_check(args) -> int:
    text = _read_text(args)
    llm = AnthropicClient(load_settings())
    rules = load_rules()
    input_type = _gate_or_exit(text, llm)
    result = check(text, rules, llm, input_type, verify_violations=not args.no_verify)
    print(to_json(result) if args.json else render_terminal(result, rules))
    return 1 if result.has_violations else 0


def _cmd_revise(args) -> int:
    text = _read_text(args)
    llm = AnthropicClient(load_settings())
    rules = load_rules()
    input_type = _gate_or_exit(text, llm)
    result = revise(text, rules, llm, input_type, max_iterations=args.max_iterations)
    for attempt in result.attempts:
        print(f"attempt {attempt.iteration}: {attempt.violation_count} violation(s)")
    print(f"\nConverged: {result.converged}\n\n--- REVISED ---\n{result.final_text}")
    return 0 if result.converged else 1
```

Register them in `main()`:

```python
    check_parser = sub.add_parser("check", help="check a communication for compliance")
    check_parser.add_argument("text", nargs="?")
    check_parser.add_argument("--file")
    check_parser.add_argument("--json", action="store_true")
    check_parser.add_argument("--no-verify", action="store_true")
    check_parser.set_defaults(fn=_cmd_check)

    revise_parser = sub.add_parser("revise", help="propose a compliant rewrite")
    revise_parser.add_argument("text", nargs="?")
    revise_parser.add_argument("--file")
    revise_parser.add_argument("--max-iterations", type=int, default=3)
    revise_parser.set_defaults(fn=_cmd_revise)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_cli.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Smoke-test against the real API**

```bash
python -m complai check "Install our app and get rich tomorrow 🚀🚀🚀"
python -m complai check "Sprint 14 retro: the deploy pipeline is flaky"
```

Expected: the first flags a missing risk warning plus misleading-promise findings; the second is declined by the gate with exit code 2.

- [ ] **Step 6: Commit**

```bash
git add src/complai/cli.py tests/test_cli.py
git commit -m "feat: add check and revise CLI commands"
```

---

## Task 11: Eval harness and generated showcase corpus

Two corpora with different trust levels, and the distinction matters:

- `evals/cases.yaml` — **ground truth**. Hand-authored labels. A generated label is not evidence, so a subagent must not write these.
- `data/samples/showcase.yaml` — **demo material**. Unlabelled marketing snippets for the UI to sample from. Volume and variety matter more than correctness, so a subagent generates these.

**Files:**
- Create: `evals/cases.yaml`, `evals/run_eval.py`, `evals/results.md`, `data/samples/showcase.yaml`
- Test: `tests/test_eval.py`

**Interfaces:**
- Consumes: `check` (Task 7), `classify` (Task 6), `load_rules` (Task 4).
- Produces: `score(expected: dict, actual: CheckResult, rule_titles: dict[str, str]) -> dict` returning `{"true_positives", "false_positives", "false_negatives"}`; `_tag_matches(tag: str, title: str) -> bool`; `main() -> int`.

- [ ] **Step 1: Dispatch a subagent to generate the showcase corpus**

Do this first — it runs in the background while the harness is built. Dispatch a `general-purpose` subagent with this brief:

> Write `data/samples/showcase.yaml`: 18 short marketing snippets for a CFD/retail-trading broker, as they would plausibly appear in the wild. YAML list, each entry `{id, medium, text, note}` where `medium` is one of `social_post`, `push_notification`, `landing_page`, `email`, `affiliate_banner`, and `note` is one sentence on what makes the snippet interesting. Spread them across: obviously non-compliant (hype, guaranteed returns, urgency, emoji), subtly non-compliant (risk warning present but buried or the wrong variant, benefits emphasised over risk), plausibly compliant (sober copy with the full mandated warning), bonus/incentive offers, and tiered-spread offers which are NOT prohibited. Two entries must be non-marketing text (an internal engineering note, a factual margin-call notice) to exercise the input gate. Do NOT include expected verdicts or compliance labels — these are demo inputs, not ground truth. Do not read anything in `_private/`. The mandated CySEC warning text, where you use it, is exactly: "CFDs are complex instruments and come with a high risk of losing money rapidly due to leverage." followed by the loss-percentage or standard-variant sentence.

- [ ] **Step 2: Hand-author the ground-truth cases**

Create `evals/cases.yaml` with the eight cases from spec §7. Structure:

```yaml
- id: brief-example
  text: "Install our app and get rich tomorrow 🚀🚀🚀"
  expect_input_type: marketing_communication
  expect_violations: [risk_warning_missing, misleading_return_promise, urgency_pressure]
  expect_clean: false
  note: The brief's own example. Must flag all three dimensions.

- id: compliant-banner
  text: |
    Trade CFDs on 3,000+ markets with tight spreads.
    CFDs are complex instruments and come with a high risk of losing money rapidly due to leverage.
    76% of retail investor accounts lose money when trading CFDs with this provider.
    You should consider whether you understand how CFDs work and whether you can afford to take the high risk of losing your money.
  expect_input_type: marketing_communication
  expect_violations: []
  expect_clean: true
  note: Guards against a checker that flags everything.

- id: tiered-spread-carveout
  text: |
    Trade more, pay less — spreads drop to 0.6 pts once you pass 50 lots a month.
    CFDs are complex instruments and come with a high risk of losing money rapidly due to leverage.
    76% of retail investor accounts lose money when trading CFDs with this provider.
    You should consider whether you understand how CFDs work and whether you can afford to take the high risk of losing your money.
  expect_input_type: marketing_communication
  expect_violations: []
  expect_clean: true
  note: PS-04-2019 §3.4.10 expressly excludes tiered fee-spreads. False-positive probe.
```

Add the remaining five: `bonus-offer` (expects an incentives violation), `buried-warning` (expects prominence + obscuring violations), `wrong-warning-variant` (abbreviated warning where the full one is required), `out-of-scope-engineering-note` (gate declines), `client-margin-notice` (gate says `client_communication`).

`expect_violations` entries are **semantic tags, not rule ids** — rule ids come from a generated rulebook and would make the eval brittle. `run_eval.py` matches a tag against a violated rule by substring-matching the tag's words against the rule title and requirement.

- [ ] **Step 3: Write the failing test**

```python
# tests/test_eval.py
from evals.run_eval import score
from complai.models import CheckResult, Verdict

def _result(*pairs):
    return CheckResult(
        "marketing_communication",
        [Verdict(rid, v, 0.9, "r") for rid, v in pairs],
        rules_considered=3, fallback_used=False,
    )

RULE_TITLES = {
    "R1": "Risk warning missing from communication",
    "R2": "Misleading return promise",
    "R3": "Urgency pressure tactics",
}

def test_perfect_match_scores_one():
    expected = {"expect_violations": ["risk_warning_missing"], "expect_clean": False}
    actual = _result(("R1", "violation"), ("R2", "compliant"))
    s = score(expected, actual, RULE_TITLES)
    assert s["true_positives"] == 1
    assert s["false_positives"] == 0
    assert s["false_negatives"] == 0

def test_false_positive_on_a_clean_case_is_counted():
    expected = {"expect_violations": [], "expect_clean": True}
    actual = _result(("R1", "violation"))
    s = score(expected, actual, RULE_TITLES)
    assert s["false_positives"] == 1

def test_missed_violation_is_counted():
    expected = {"expect_violations": ["misleading_return_promise"], "expect_clean": False}
    actual = _result(("R2", "compliant"))
    s = score(expected, actual, RULE_TITLES)
    assert s["false_negatives"] == 1
```

- [ ] **Step 4: Run test to verify it fails**

Run: `pytest tests/test_eval.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'evals.run_eval'`

- [ ] **Step 5: Implement the scorer**

```python
# evals/run_eval.py
"""Regression harness. Eight to ten cases is not a statistically meaningful eval —
it is a guard against prompt changes silently making things worse."""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

from complai.check import check
from complai.config import load_settings
from complai.extract import load_rules
from complai.gate import classify
from complai.llm import AnthropicClient
from complai.models import CheckResult

CASES_PATH = Path("evals/cases.yaml")


def _tag_matches(tag: str, title: str) -> bool:
    words = [w for w in tag.replace("-", "_").split("_") if len(w) > 3]
    haystack = title.lower()
    return sum(w in haystack for w in words) >= max(1, len(words) - 1)


def score(expected: dict, actual: CheckResult, rule_titles: dict[str, str]) -> dict:
    violated_titles = [rule_titles.get(v.rule_id, v.rule_id) for v in actual.violations]
    expected_tags = list(expected.get("expect_violations", []))

    matched_tags, unmatched_titles = set(), list(violated_titles)
    for tag in expected_tags:
        for title in list(unmatched_titles):
            if _tag_matches(tag, title):
                matched_tags.add(tag)
                unmatched_titles.remove(title)
                break

    return {
        "true_positives": len(matched_tags),
        "false_negatives": len(expected_tags) - len(matched_tags),
        "false_positives": len(unmatched_titles),
    }


def main() -> int:
    cases = yaml.safe_load(CASES_PATH.read_text(encoding="utf-8"))
    rules = load_rules()
    rule_titles = {r.id: f"{r.title} {r.requirement}" for r in rules}
    families = {r.id: r.category for r in rules}
    llm = AnthropicClient(load_settings())

    totals = {"true_positives": 0, "false_positives": 0, "false_negatives": 0}
    rows, gate_correct = [], 0

    for case in cases:
        gate = classify(case["text"], llm)
        gate_ok = gate.input_type == case["expect_input_type"]
        gate_correct += gate_ok

        if not gate.proceed:
            rows.append((case["id"], "gate declined", "ok" if gate_ok else "GATE WRONG"))
            continue

        result = check(case["text"], rules, llm, gate.input_type)
        s = score(case, result, rule_titles)
        for key in totals:
            totals[key] += s[key]
        mechanical = sum(
            1 for v in result.violations if families.get(v.rule_id) == "mechanical"
        )
        rows.append((
            case["id"],
            f"tp={s['true_positives']} fp={s['false_positives']} fn={s['false_negatives']}",
            f"{mechanical} mechanical / {len(result.violations) - mechanical} judgment"
            + ("" if gate_ok else "  GATE WRONG"),
        ))

    tp, fp, fn = totals["true_positives"], totals["false_positives"], totals["false_negatives"]
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0

    print(f"{'case':<32} {'score':<28} notes")
    for row in rows:
        print(f"{row[0]:<32} {row[1]:<28} {row[2]}")
    print(f"\ngate accuracy: {gate_correct}/{len(cases)}")
    print(f"precision: {precision:.2f}   recall: {recall:.2f}   (tp={tp} fp={fp} fn={fn})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Create empty `evals/__init__.py` so the test can import it.

- [ ] **Step 6: Run tests, then run the real eval**

Run: `pytest tests/test_eval.py -v` → PASS (3 passed)
Run: `python -m evals.run_eval | tee evals/results.md`

Read the disagreements. If precision is poor, the fix is usually a missing `counter_example`; if recall is poor, tighten `check_guidance` on the rules that were missed. Iterate the prompt, not the eval — moving the goalposts to make the score look good is the failure mode this harness exists to prevent.

- [ ] **Step 7: Commit**

```bash
git add evals/ data/samples/ tests/test_eval.py
git commit -m "feat: add eval harness, labelled cases and showcase corpus"
```

---

## Task 12: Streamlit UI

**Files:**
- Create: `app.py`, `.streamlit/config.toml`
- Test: manual (Streamlit UI is not unit-tested; the logic beneath it already is)

**Interfaces:**
- Consumes: `classify`, `check`, `revise`, `load_rules`, `sort_verdicts`.
- Produces: nothing consumed elsewhere.

- [ ] **Step 1: Implement the app**

```python
# app.py
"""Streamlit front end. Deliberately thin — all logic lives in src/complai."""
from __future__ import annotations

import random
from pathlib import Path

import streamlit as st
import yaml

from complai.check import check
from complai.config import MissingAPIKey, load_settings
from complai.extract import load_rules
from complai.gate import classify
from complai.llm import AnthropicClient
from complai.report import sort_verdicts
from complai.revise import revise

SHOWCASE = Path("data/samples/showcase.yaml")
BADGE = {
    "violation": ("🔴", "Violation"),
    "needs_review": ("🟡", "Needs review"),
    "compliant": ("🟢", "Compliant"),
    "not_applicable": ("⚪", "Not applicable"),
}

st.set_page_config(page_title="complai — Regulation Compliance Agent", layout="wide")
st.title("complai")
st.caption(
    "Checks marketing communications against CySEC PS-04-2019 and the MiFID II "
    "fair-clear-not-misleading standard, rule by rule."
)


@st.cache_data
def _samples() -> list[dict]:
    if not SHOWCASE.exists():
        return []
    return yaml.safe_load(SHOWCASE.read_text(encoding="utf-8")) or []


@st.cache_resource
def _rules():
    return load_rules()


def _client():
    try:
        return AnthropicClient(load_settings())
    except MissingAPIKey as exc:
        st.error(str(exc))
        st.stop()


if "text" not in st.session_state:
    st.session_state.text = ""
if "picks" not in st.session_state:
    pool = _samples()
    st.session_state.picks = random.sample(pool, min(3, len(pool)))

with st.sidebar:
    st.subheader("Try an example")
    st.caption("Three drawn at random from the sample corpus.")
    for sample in st.session_state.picks:
        if st.button(sample["text"][:60] + "…", key=sample["id"], use_container_width=True):
            st.session_state.text = sample["text"]
    if st.button("Shuffle examples", use_container_width=True):
        pool = _samples()
        st.session_state.picks = random.sample(pool, min(3, len(pool)))
        st.rerun()
    st.divider()
    st.metric("Rules in force", len(_rules()))

text = st.text_area("Marketing communication", value=st.session_state.text, height=180)
col_check, col_revise = st.columns(2)
run_check = col_check.button("Check compliance", type="primary", use_container_width=True)
run_revise = col_revise.button("Propose compliant rewrite", use_container_width=True)

if run_check or run_revise:
    if not text.strip():
        st.warning("Paste some marketing copy first.")
        st.stop()

    llm, rules = _client(), _rules()

    with st.spinner("Classifying input…"):
        gate = classify(text, llm)

    if not gate.proceed:
        st.error(f"Declined — this is not a client-facing communication ({gate.input_type}).")
        st.caption(gate.reasoning)
        st.stop()

    st.info(f"Classified as **{gate.input_type}** — {gate.reasoning}")

    if run_check:
        with st.spinner("Checking rule by rule, then verifying findings against source…"):
            result = check(text, rules, llm, gate.input_type)

        if result.fallback_used:
            st.warning("Rule filtering was too narrow, so the full rulebook was applied.")

        violations = len(result.violations)
        st.subheader(f"{violations} violation(s)" if violations else "No violations found")

        by_id = {r.id: r for r in rules}
        for verdict in sort_verdicts(result.verdicts, rules):
            rule = by_id.get(verdict.rule_id)
            icon, label = BADGE.get(verdict.verdict, ("⚪", verdict.verdict))
            title = rule.title if rule else verdict.rule_id
            with st.container(border=True):
                st.markdown(f"{icon} **{label}** — {title}")
                st.write(verdict.reasoning)
                if verdict.evidence_span:
                    st.markdown(f"> {verdict.evidence_span}")
                st.caption(f"Confidence {verdict.confidence:.0%}")
                if verdict.verified:
                    st.caption(f"✓ Verified against source — {verdict.verification_note}")
                if rule:
                    with st.expander(f"Source — {rule.source_doc} {rule.source_ref}"):
                        st.markdown(f"> {rule.source_quote}")
                        st.caption(f"Requirement: {rule.requirement}")
                        if rule.counter_example:
                            st.caption(f"Expressly not a violation: {rule.counter_example}")

    if run_revise:
        with st.spinner("Rewriting and re-checking…"):
            result = revise(text, rules, llm, gate.input_type)

        st.subheader("Revision trajectory")
        for attempt in result.attempts:
            st.write(f"Attempt {attempt.iteration}: **{attempt.violation_count}** violation(s)")
        if result.converged:
            st.success("Converged to a compliant version.")
        else:
            st.warning(
                f"Did not fully converge in {len(result.attempts)} attempts. "
                "Best effort shown below."
            )
        st.caption(
            "Note: the same model writes and judges these rewrites. The trajectory is shown "
            "so you can see the work rather than trust the final label."
        )
        col_a, col_b = st.columns(2)
        col_a.text_area("Original", value=result.original, height=260, disabled=True)
        col_b.text_area("Revised", value=result.final_text, height=260)
```

```toml
# .streamlit/config.toml
[theme]
base = "dark"
primaryColor = "#22c55e"
```

- [ ] **Step 2: Run it and click through**

Run: `streamlit run app.py`

Check: examples load into the box; shuffle changes them; the brief's example produces violation cards; the source expander shows the verbatim quote; an out-of-scope sample is declined; the rewrite button shows a trajectory.

- [ ] **Step 3: Commit**

```bash
git add app.py .streamlit/config.toml
git commit -m "feat: add Streamlit UI with provenance and revision trajectory"
```

---

## Task 13: README — the thinking doc

Weighted equally with the code. Reserve the time; do not compress it.

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Write it**

Sections, in this order:

1. **What this is** — two sentences, plus one screenshot of the UI.
2. **Quickstart** — `pip install -r requirements.txt`, `cp .env.example .env`, add key, `python -m complai check "..."`, `streamlit run app.py`. State that `data/rules/rules.json` is committed, so no extraction call is needed to try it.
3. **How it works** — the pipeline diagram from spec §3, one paragraph per stage.
4. **Key decisions** — one short subsection each, with the reasoning:
   - Rules extracted once and committed, not extracted at runtime.
   - No RAG: compliance is a recall problem, and 20–30 rules fit in context.
   - Two-pass checking: one cheap screen, adversarial verification only on hits.
   - The input gate, and the line in the brief that prompted it.
   - Streamlit over a bespoke frontend: brief in the morning, demoable by lunch; the UI is thin and swappable, the pipeline is what matters.
5. **Prompt design** — the four prompts and the single instruction that mattered most in each. Quote the checkability constraint from the extraction prompt; it is the difference between checkable rules and restated paragraphs.
6. **Evaluation** — what the harness measures, the current numbers from `evals/results.md`, and the explicit caveat that eight to ten cases is a regression guard, not a statistically meaningful eval.
7. **What I cut, and why** — the full list from spec §13.
8. **Known limitations** — prominence and font size are regulated but not text-checkable; the revision loop judges its own work; rule extraction was hand-corrected in N places (list them).
9. **What I'd do differently with more time** — independent judge model for the loop, HITL triage on `needs_review`, multi-jurisdiction rules, layout-aware ingestion.
10. **One thing that surprised me** — PS-04-2019 §3.4.10 expressly carves tiered fee/spread discounts *out* of the incentives ban, even though they look like the bonuses that are banned. It reframed the build: an over-flagging compliance agent is not "safely cautious", it is wrong in a way that erodes trust and trains people to ignore it. That carve-out became a false-positive probe in the eval set and a `counter_example` field on every rule.
11. **AI-native workflow** — how this was built: spec and plan committed under `docs/superpowers/`, TDD throughout, a subagent for the showcase corpus while the harness was written by hand, and the deliberate line that generated labels are not evidence, so ground-truth eval cases were hand-authored.

- [ ] **Step 2: Verify the quickstart from a clean clone**

```bash
cd /tmp && rm -rf complai-verify && git clone https://github.com/abelix176/complai complai-verify
cd complai-verify && python -m venv .venv && .venv/bin/pip install -q -r requirements.txt
cp .env.example .env   # then add a real key
.venv/bin/python -m complai check "Install our app and get rich tomorrow 🚀🚀🚀"
```

Expected: runs end to end with only a key added. If it does not, fix the README or the code — this is the reviewer's first five minutes.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: write thinking doc covering decisions, evals and limitations"
```

---

## Task 14: Deployment (bonus — cut this first)

- [ ] **Step 1: Deploy to Streamlit Community Cloud**

Point it at `abelix176/complai`, main branch, `app.py`. Add `ANTHROPIC_API_KEY` under Secrets. The committed rulebook means no build-time API calls.

- [ ] **Step 2: Add the URL to the README quickstart**

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: add hosted demo link"
```

---

## Final verification

- [ ] `pytest -v` — all tests pass, no network calls.
- [ ] `python -m evals.run_eval` — runs, numbers recorded in `evals/results.md`.
- [ ] `git ls-files | grep -i etoro` — returns nothing.
- [ ] `git log --format='%an %s' | grep -iE 'claude|co-authored|generated with'` — returns nothing.
- [ ] `grep -r "sk-ant-" --include="*.py" --include="*.json" --include="*.yaml" .` — only `.env.example`'s placeholder.
- [ ] Clean clone + key → `complai check` works.
