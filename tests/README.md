# Tests Guide

## Purpose

This directory contains focused automated tests for `picho`.

Before adding a new test, confirm that it protects meaningful behavior:
- New public components
- Behavior changes
- Regression fixes
- Config parsing and validation
- Tool or runner edge cases

Docs-only changes usually do not need tests.

## Run Tests

Use `uv` commands only:

```bash
uv run pytest
```

If imports fail because the project package is not available in the active environment yet, install the repo in editable mode first:

```bash
uv pip install -e .
```

Run a single file:

```bash
uv run pytest tests/test_read_tool.py
```

Run a single test:

```bash
uv run pytest tests/test_read_tool.py -k csv
```

## File Naming

- Test files should use `test_<subject>.py`
- Test functions should use `test_<behavior>()`
- Group related behavior in the same file when it improves readability

## Test Style

- Prefer small, deterministic tests
- Keep one behavioral assertion path per test when practical
- Use Arrange / Act / Assert structure
- Use clear fixture setup and avoid hidden coupling
- Keep comments minimal; if needed, keep them in English

## Isolation Rules

- Do not depend on external network access
- Do not depend on real model providers or real credentials
- Do not read `.env` or other secret files
- Do not depend on machine-specific paths outside temporary directories
- Prefer `tmp_path`, `monkeypatch`, and lightweight fakes over real services

## When to Add Tests

Add or update tests when:
- A new component or module is introduced
- A bug fix changes observable behavior
- A configuration branch or extension point is added
- A tool contract, output shape, or error path changes

Document the reason when you intentionally skip tests for a non-trivial change.

## Review Checklist

Before finishing a change, verify:
- The test names describe behavior clearly
- The assertions match user-visible behavior
- The test is stable across machines
- The test is runnable with `uv run pytest`
- The setup does not rely on `sys.path` injection headers in tests or helper scripts
