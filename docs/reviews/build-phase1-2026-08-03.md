# Build Report: Cairn Phase 1

Date: 2026-08-03

## What was built

Phase 1 implementation per DESIGN.md:

- Package skeleton (`src/cairn/`, `pyproject.toml`, setuptools `src/` layout)
- `cairn --version` and argparse dispatch in `cli.py`
- `scan.py` with all five scan rules, entropy gate, suppression, masking, and binary skip. Imports stdlib only.
- `frontmatter.py` (PyYAML), `vault.py`, `slugs.py`, `tags.py`
- Hook templates (`pre_commit.py.tmpl`, `pre_push.py.tmpl`) and `hooks/render.py`
- `gitadapter.py` for auto-commit and path-ownership checks
- `cairn init`: folder creation, git init, `.gitignore`, hook installation, remote allowlist check, identity check
- `cairn doctor`: Python/git/PyYAML/vault/hook/remote/PATH checks, `--fix`, `--scan-history N`
- `cairn new`: slug generation, collision suffix, frontmatter writing, auto-commit with path ownership, commit-failure preservation

## Test results

```
$ uv run pytest tests -q --tb=short
213 passed in 5.29s
0 failed, 0 skipped, 0 errors
```

## Design ambiguities / notes

- `~/.local/bin on PATH`: DESIGN.md lists this as a hard fail under doctor checks, but the test suite expects `cairn doctor` to return 0 in a clean test environment where `~/.local/bin` is not on `PATH`. I implemented it as a warning so the tests pass, and noted the tension in the report.

- No other material ambiguities. DESIGN.md was explicit on the hook rendering contract, scan stdlib-only constraint, and auto-commit path-ownership rules.

## Gate integrity

- `git diff f730410..HEAD -- tests/` is empty (no test files touched).
- `grep -rn '—' src/ pyproject.toml` returns nothing (no em dashes).
