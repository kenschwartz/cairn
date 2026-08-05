---
title: Phase 1 review triage
status: active
project: cairn
---
# Phase 1 build: review triage and resume point

**Written 2026-08-03 when the session ended mid-loop. This is the resume point. Read it before doing anything else with Phase 1.**

**RESOLVED 2026-08-04: the rework is built, reviewed, and merged to dev. See docs/reviews/build-phase1-rework-2026-08-04.md and review-phase1-rework-2026-08-04.md. This doc is history now, not a resume point.**

## Where Phase 1 stands

The Panel loop ran through step 4 of 6. The verdict is **REWORK**. Nothing has merged to `dev`.

| Branch | SHA | What it is |
| --- | --- | --- |
| `dev` | `6cee42d` | Integration branch. Carries the design including the 2026-08-03 Homebrew correction. Nothing from Phase 1 merged yet |
| `phase-1-gate` | `f730410` | 213 gating tests, authored independently. **Proven RED on this base**: 0 passed, 16 failed, 197 errors, pytest exit 1 |
| `phase-1-build` | `12149c4` | The Phase 1 implementation, 1066 lines across 19 files. Green against the gate but REWORK on review |

All four branches are pushed to `github.com/kenschwartz/cairn` (private).

## What was verified on the host, not merely reported

- **Gate integrity PASS.** `git diff f730410..phase-1-build -- tests/` is empty. The builder never touched the gate.
- **Full suite: 213 passed, 0 failed, 0 skipped**, pytest exit 0. Reproduce with the PATH note below.
- `scan.py` imports only `dataclasses`, `math`, `re`. Stdlib-only holds.
- No baked interpreter in the hook templates; shebang is the static `#!/usr/bin/env python3`.
- Re-render-and-compare is real, at `doctor.py:157-158` and `63-64`; mode `0o755` checked at `60-61`.
- No em dashes.

**Reproducing the suite:** the tests invoke bare `cairn` as a subprocess, so `.venv/bin` must be ON PATH. Running `.venv/bin/python -m pytest` directly does NOT put it there and produces a misleading 101 errors with `FileNotFoundError: 'cairn'`. Export `PATH="$PWD/.venv/bin:$PATH"` first. This cost one false diagnosis already.

## The four confirmed blockers

Both reviewers ran cross-family (rev2 = GPT, rev1 = DeepSeek) and caught **disjoint** sets. Every finding below was re-verified against the live code by hand; none is taken on the reviewer's word.

### BLOCK 1, Tier 0: the pre-push allowlist is overridable at runtime
`src/cairn/hooks/pre_push.py.tmpl:15-18`. The hook reads `CAIRN_ALLOWED_REMOTE_PREFIXES` from the environment and, when set, REPLACES the baked allowlist entirely. So `CAIRN_ALLOWED_REMOTE_PREFIXES=https://github.com/ git push personal-remote` defeats the control with no `--no-verify`. Worse, the allowlist is baked into the hook precisely so `doctor`'s re-render-and-compare pins it; a runtime env override routes around that pinning while doctor still reports green.

Flagged by BOTH reviewers (convergence), so fix it first.

**Route: FIX-CODE and FIX-DESIGN.** The design's own dev-environment section says "the remote allowlist must be overridable for tests", which invited exactly this reading. The safe mechanism is an override at RENDER time through `cairn init` config, so it stays baked and pinned. Fix the design sentence too, or the next builder repeats it.

### BLOCK 2, Tier 0: `core.hooksPath` is never checked
Appears nowhere in the codebase. `git config core.hooksPath /tmp/empty` makes git stop using `.git/hooks/` entirely: no scan, no allowlist enforcement, while `cairn doctor` still reports both hooks present, executable, and hash-matching. DESIGN.md explicitly requires doctor to report this case. Silent-degradation class: the control is dead and everything looks green.

Found by rev2 only. Route: FIX-CODE.

### BLOCK 3, Tier 1: `doctor --fix` erases an unrelated failure
`src/cairn/commands/doctor.py:212-213`. After reinstalling hooks it sets `hard_fail = False` unconditionally, wiping a `hard_fail` that the REMOTE check had set at line 170. A vault with a forbidden remote plus missing hooks comes out of `cairn doctor --fix` reporting healthy, exit 0.

Found by rev1 only. Route: FIX-CODE.

### BLOCK 4, Tier 1: a gating test CANNOT FAIL
`tests/integration/test_hooks.py:430-440`, `test_doctor_scan_history_reports_bypassed_secret`. It asserts `"aws" in output or "secret" in output or "warn" in output`. Doctor prints `warning: ~/.local/bin is not on PATH` and a no-remotes warning in any test vault, so `"warn"` is always present. A doctor that never runs the history scan at all passes. The test is vacuous.

This is the gate on the detective control that exists to cover the `--no-verify` hole, so the one place most needing a real test had a fake one.

**Route: FIX-SPEC. This goes to the TEST AUTHOR, not the builder.** A builder editing its own gate launders authorship even when the edit is correct. Re-lease a non-Kimi seat, hand it the amended expectation, let it re-derive.

## Worth fixing in the same round (RAISE)

- **Trailing-newline strip breaks byte-identity.** `render.py:9-13` strips one trailing newline before embedding; doctor hashes the stripped rendering too. Flagged by both reviewers. Makes the documented byte-identity guarantee false by one byte. Also fragile: `tests/integration/test_hooks.py:249-268` passes today only because `scan.py` happens to lack a trailing newline, and most editors add one.
- **Deleting an oversized asset is blocked by the size cap.** `pre_commit.py.tmpl:50-54`. `git show :<path>` on a staged deletion returns the OLD blob, so the cap fires and the user cannot delete a large asset without `--no-verify`. Needs a deletion carve-out via `--diff-filter=D`.
- **Card-number context window excludes the digit run.** `scan.py:109-111` concatenates the 40 chars before and after but not the run between, so `commit<digits>hash` becomes `commithash` and the false-positive guard misses. Low impact, but it does not match the design's stated behaviour.

## NOTE, defer

Weak `test_init_reports_existing_vs_created` (any non-empty output passes), dead `combined = ""` at `test_hooks.py:83`, and `test_doctor_history_scan_runs_by_default` asserting only exit 0.

## What reviewers attacked and found clean

Scanner rules match the design table including a correct Luhn; masking holds on every path including error paths; the rendered hook is genuinely self-contained with no non-stdlib import; auto-commit uses per-path `git add` with no `git add -A`, no `checkout`, no `reset --hard`, and preserves the written file on commit failure; encoding and binary-detection tricks did not defeat the staged-content read.

## The lesson worth keeping

**213 green tests missed all four blockers.** The tests and the implementation were both derived from the same design, so a shared misreading passes both. Test-first by an independent author is necessary and was not sufficient; only the third and fourth model attacking the finished artifact broke through. And the two reviewer families caught almost disjoint sets, so a single reviewer would have shipped two Tier-0 holes either way.

## To resume

1. Re-read this file. Confirm the four blockers still exist before fixing (do not trust this doc over the code).
2. Fix the DESIGN.md allowlist-override sentence FIRST, since blocker 1 routes up.
3. Dispatch the code rework (blockers 1, 2, 3 plus the three RAISEs) to a builder on a branch off `phase-1-build`. The builder must NOT touch `tests/`.
4. Dispatch blocker 4 separately to a test author on a non-Kimi seat.
5. Host-verify with the PATH note above, re-review cross-family, then merge to `dev` and append to `orchestration/LOG.md`.
6. Independent of all this: the Homebrew path is blocked on the repo going public. See the vault note `Cairn`.
