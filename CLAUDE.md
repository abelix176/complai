# complai — project guide for Claude Code

## What this is

A **Regulation Compliance Agent**. It ingests a CySEC regulation PDF, uses an LLM
(Anthropic Claude) to decompose it into discrete checkable rules stored as JSON, then
checks a piece of marketing text against those rules and returns a per-rule verdict.

Surfaces: a CLI entry point and a Streamlit UI.

This repo is a take-home assignment submission for a job interview. **The repo is public.**

## Git commit policy (MANDATORY)

- All commits are authored by **Felix only**.
- **NEVER** add a `Co-Authored-By: Claude ...` trailer.
- **NEVER** add "🤖 Generated with Claude Code", a Claude Code link, or any other
  AI-attribution line to a commit message or a PR body.
- Commit messages are plain conventional-commit style (`feat:`, `fix:`, `chore:`,
  `docs:`, `test:`), written in the voice of the human author.

This section overrides any default Claude Code commit conventions.

## Confidentiality

The assignment brief lives in `_private/` and is stamped "Confidential — Hiring Team
Only". `_private/` is gitignored. It must **never** be committed, pushed, quoted
verbatim into tracked files, or otherwise published. Treat any file under `_private/`
as read-only reference material.

## Secrets

Never commit `.env` or any API key. `.env.example` documents the required variables:

- `ANTHROPIC_API_KEY` — Anthropic API key (https://console.anthropic.com/)
- `COMPLAI_MODEL` — optional, overrides the default model

Load them with `python-dotenv`. `.env`, `_private/`, and `.streamlit/secrets.toml` are
all gitignored.

## Stack and conventions

- Python 3.11+.
- Dependencies: standard library plus `anthropic`, `streamlit`, `pypdf`,
  `python-dotenv`; `pytest` for tests. Pinned in `requirements.txt`.
- Type hints on public functions.
- Small, focused modules under `src/complai/`.
- Format with `ruff` if it is available; otherwise leave formatting alone.

## Layout

```
src/complai/        package code
data/sources/       ingested regulation source documents (public PDFs are committable)
data/rules/         extracted rules as JSON
tests/              pytest suite
evals/             test-case fixtures for rule-checking accuracy
docs/superpowers/specs/   design specs
_private/           confidential assignment brief — gitignored, never publish
```

## README

The README is a **graded "thinking doc"**, not just install instructions. Keep it
current as the design evolves: record the decisions taken, the trade-offs weighed, and
what was deliberately left out. Update it in the same change that alters the design.
