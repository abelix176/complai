"""Command surface. `python -m complai <command>`."""
from __future__ import annotations

import argparse
from pathlib import Path

from complai.check import check
from complai.config import load_settings
from complai.extract import RULES_PATH, extract_rules, load_rules, save_rules
from complai.gate import classify
from complai.ingest import SOURCES_DIR, ingest_primary
from complai.llm import AnthropicClient
from complai.report import render_terminal, to_json
from complai.revise import revise


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


def _cmd_check(args: argparse.Namespace) -> int:
    text = _read_text(args)
    llm = AnthropicClient(load_settings())
    rules = load_rules()
    input_type = _gate_or_exit(text, llm)
    result = check(text, rules, llm, input_type, verify_violations=not args.no_verify)
    print(to_json(result) if args.json else render_terminal(result, rules))
    return 1 if result.has_violations else 0


def _cmd_revise(args: argparse.Namespace) -> int:
    text = _read_text(args)
    llm = AnthropicClient(load_settings())
    rules = load_rules()
    input_type = _gate_or_exit(text, llm)
    result = revise(text, rules, llm, input_type, max_iterations=args.max_iterations)
    for attempt in result.attempts:
        print(f"attempt {attempt.iteration}: {attempt.violation_count} violation(s)")
    print(f"\nConverged: {result.converged}\n\n--- REVISED ---\n{result.final_text}")
    return 0 if result.converged else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="complai")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("ingest", help="fetch and normalise regulation sources").set_defaults(
        fn=_cmd_ingest
    )
    sub.add_parser("extract", help="regenerate the rulebook").set_defaults(fn=_cmd_extract)

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

    args = parser.parse_args(argv)
    return args.fn(args)
