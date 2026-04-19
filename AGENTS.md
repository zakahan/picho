# AGENTS.md

This file defines repository-wide working rules for coding agents and contributors operating in `picho`.

## Documentation Sync

- When a change materially affects behavior, configuration, CLI usage, public APIs, module structure, or user workflows, inspect the relevant `README.md` and `README_zh.md`.
- If the change should be documented, update both language versions in the same task.
- Do not leave English and Chinese READMEs out of sync.
- For large changes, also check the top-level `README.md` and `README_zh.md` in addition to any touched module README files.

## Dependency Management

- Use `uv` as the default package and environment manager for this repository.
- Prefer `uv sync`, `uv sync --group extra`, `uv run`, `uv add`, and `uv remove`.
- Do not introduce or recommend raw `pip install` commands in code, docs, scripts, or examples unless the user explicitly asks for migration analysis.
- Do not solve import problems by adding `sys.path` bootstrap headers or similar path-injection snippets at the top of scripts or tests.
- Prefer proper package installation and execution flows such as `uv sync` or `uv pip install -e .`.

## Sensitive Files

- Never directly read `.env`, `.env.*`, secret files, key stores, or credential dumps.
- If environment-related debugging is needed, ask the user to provide the exact non-sensitive values they want to share, or inspect configuration files that reference env loading behavior without opening the secret files themselves.

## Tests

- Every new component, public feature, or behavior-changing refactor must include an explicit evaluation of whether tests are needed.
- If the change introduces meaningful regression risk, add or update focused tests under `tests/`.
- Follow the conventions in `tests/README.md`.
- Prefer deterministic tests that do not depend on external network access, real model providers, or machine-specific state.

## Code Hygiene

- Keep code comments and log messages in English.
- Prefer targeted, minimal changes over broad rewrites when possible.
- After substantive edits, run diagnostics or focused verification for the touched files.

## Code Quality

- When all tasks are complete, run `pre-commit run --all-files` to check for linting or formatting issues.
