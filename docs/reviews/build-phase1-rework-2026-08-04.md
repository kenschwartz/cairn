# Build Report: Cairn Phase 1 Rework

**Date:** 2026-08-04  
**Branch:** `phase-1-rework-build`  
**Suite result:** 229 collected, 229 passed, 0 failed, 0 skipped, 0 errors

## Changed files

| File | Change |
| --- | --- |
| `src/cairn/config.py` | **New module.** Resolves the per-user config file at `$XDG_CONFIG_HOME/cairn/config.toml` (defaulting to `~/.config/cairn/config.toml`), parses it with stdlib `tomllib`, and exposes `[remote] allowed_prefixes`. Defaults to the two CFG-INNERSOURCE prefixes when the file or key is absent. A present but malformed config fails loudly with a clear message and non-zero exit. |
| `src/cairn/scan.py` | **Re-scoped to v1 rules.** Removed payment-card, SSN, labelled-token, entropy gate, suppression handling, and the `math` import. Added the six v1 rules with exact DESIGN.md patterns: `private_key` (amended with `ENCRYPTED` and `BLOCK` suffixes), `aws_access_key_id`, `public_key`, `ssh_public_key`, `github_token`, `anthropic_api_key`. Implemented the three-tier masking contract inside `scan_bytes` (1-2 chars -> `[...]`; 3-8 chars -> `x[...]y`; longer -> `abcd[...]wxyz`). Binary null-byte skip remains inside `scan_bytes` as part of its contract. |
| `src/cairn/hooks/render.py` | **Fixed byte-identity.** Removed the unconditional one-newline strip from `render_pre_commit`. The template newline after `{{SCAN_SOURCE}}` is now consumed as part of the placeholder substitution, so the inlined region is byte-identical to `scan.py` regardless of trailing-newline count. |
| `src/cairn/hooks/pre_push.py.tmpl` | **Removed env-override branch.** Deleted the `CAIRN_ALLOWED_REMOTE_PREFIXES` environment read. The rendered hook consults ONLY the baked `ALLOWLIST` constant. |
| `src/cairn/hooks/pre_commit.py.tmpl` | **Staged-deletion carve-out.** Added `get_staged_deletions()` and excludes deletions from both the content scan and the asset size cap. Removed the duplicate binary-skip filter (now handled inside `scan_bytes`). Manifest verification changed from `except OSError: continue` to `sys.exit(1)` so an existing but unreadable manifest-listed file blocks the commit (fail-closed). |
| `src/cairn/commands/init.py` | **Switched to config resolver.** Removed `DEFAULT_ALLOWLIST` and `get_allowlist()`; now imports `get_allowlist` from `cairn.config`. Deleted the `CAIRN_ALLOWED_REMOTE_PREFIXES` env read entirely. |
| `src/cairn/commands/doctor.py` | **Two coordinated fixes.** (1) Added `core.hooksPath` check: runs `git config --get core.hooksPath`; a non-empty value is a HARD FAIL naming the diverted path. (2) Restructured fail-state tracking from a single `hard_fail` boolean to per-check booleans (`py_fail`, `yaml_fail`, `git_fail`, `email_fail`, `repo_fail`, `hookspath_fail`, `pc_fail`, `pp_fail`, `remote_fail`). The `--fix` path reinstalls hooks and can only clear the hook-verification failures it fixed; remote and hooksPath failures persist in the exit code. Doctor's re-render-and-compare now sources its expected allowlist through the same `config.py` resolver, so a config edit without re-bake surfaces as drift. |

## Acceptance verification

- `PATH="$PWD/.venv/bin:$PATH" python -m pytest -q` -> 229 collected, 229 passed, 0 failed, 0 skipped, 0 errors.
- `python -c "import ast,sys; [print(n.names[0].name) for n in ast.walk(ast.parse(open('src/cairn/scan.py').read())) if isinstance(n,ast.Import)]"` -> only stdlib modules (`dataclasses`, `re`), no `math`.
- `git diff phase-1-rework-build -- tests/` -> EMPTY.

## Full final pytest tail

```
........................................................................ [ 31%]
........................................................................ [ 62%]
........................................................................ [ 94%]
.............                                                            [100%]
229 passed in 4.85s
```
