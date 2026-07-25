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
    sub.add_parser("ingest", help="fetch and normalise regulation sources").set_defaults(
        fn=_cmd_ingest
    )
    sub.add_parser("extract", help="regenerate the rulebook").set_defaults(fn=_cmd_extract)
    args = parser.parse_args(argv)
    return args.fn(args)
