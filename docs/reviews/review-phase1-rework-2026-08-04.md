# Phase 1 rework review (2026-08-04, cross-family)

Two leased rev-pool seats reviewed phase-1-rework-build vs phase-1-rework. Verdicts: rev1 MERGE WITH FOLLOWS; rev2 REWORK, rejected at triage (its sole BLOCK was the pre-existing warning-only PATH check, not introduced by the diff; fixed anyway per DESIGN.md:231). Convergent RAISE (v2 history scan in v1) stripped at triage, c427d90. Follows recorded in TODO.md.

## rev1
```
Good. scan.py ends with exactly one `\n`, no template placeholders. Now I have everything. Here is the review.

---

## CODE REVIEW: phase-1-rework-build vs phase-1-rework

Reviewer: hermes-jen (Docker/Honcho specialist, independent review)
Authority: DESIGN.md on phase-1-rework-build (sections "Pre-commit content scan", "Security enforcement via git hooks", doctor section, "Config source")
Build commit: b5b845a
Gate: 229 passed, 0 failed, 0 skipped, 0 errors (host-verified, taken as given)

---

### BLOCKER CONFIRMATIONS

**Blocker 1: Pre-push allowlist runtime override**
DEAD. Evidence:
- pre_push.py.tmpl:25 -- `allowed = any(remote_url.startswith(prefix) for prefix in ALLOWLIST)` consults ONLY the baked constant. No env consultation anywhere in the hook.
- init.py:8 -- imports `get_allowlist` from `cairn.config`, no longer defines its own.
- config.py:12-50 -- `get_allowlist()` reads `$XDG_CONFIG_HOME/cairn/config.toml` at BAKE time (init/doctor), never at push time.
- The `CAIRN_ALLOWED_REMOTE_PREFIXES` env read is excised from both init.py (was lines 15-18) and pre_push.py.tmpl (was lines 15-19).

**Blocker 2: core.hooksPath**
DEAD. Evidence:
- doctor.py:139-148 -- `git config --get core.hooksPath` runs, sets `hookspath_fail = True` on non-empty result, messages include "core.hooksPath diverted to {diverted} FAIL".
- doctor.py:239-250 -- `hookspath_fail` is included in the `hard_fail = any([...])` computation.
- doctor.py:221 -- `--fix` condition is `if args.fix and (pc_fail or pp_fail):` -- hookspath_fail is never gated by this block and is never cleared. The hooks get reinstalled to `.git/hooks/` but the diverted hooksPath means they still won't run, and `hookspath_fail` stays `True`.

**Blocker 3: doctor --fix must not erase non-hook failures**
DEAD. Evidence:
- doctor.py:123-148 -- per-check booleans (`py_fail`, `yaml_fail`, `git_fail`, `email_fail`, `repo_fail`, `hookspath_fail`, `remote_fail`, `pc_fail`, `pp_fail`) independently tracked.
- doctor.py:221-236 -- `--fix` block only touches `pc_fail`/`pp_fail` (re-verifies after reinstall). Never touches `hookspath_fail`, `remote_fail`, or any other boolean.
- doctor.py:239-250 -- `hard_fail = any([...])` includes ALL booleans. The old `hard_fail = False` reset (was line 218, "if pc_ok and pp_ok: hard_fail = False") is gone.

**Blocker 4: v1 scan ships exactly six DESIGN.md rules**
DEAD. Evidence:
- scan.py:19-35 -- six regexes: `_PRIVATE_KEY_RE`, `_AWS_RE`, `_PUBLIC_KEY_RE`, `_SSH_PUB_RE`, `_GITHUB_RE`, `_ANTHROPIC_RE`. Rule identifiers: `private_key`, `aws_access_key_id`, `public_key`, `ssh_public_key`, `github_token`, `anthropic_api_key`.
- GONE from scan.py: `ENTROPY_THRESHOLD`, `_shannon_entropy()`, `_luhn_valid()`, `_TOKEN_LABEL_RE`, `_SSN_RE`, `_FP_RE`, `math` import, `cairn:allow-secret` suppression line check, `payment_card` loop, `us_ssn` rule, `labelled_token` rule.
- tests/unit/test_scan.py TestV1ScopeExcludesDroppedAndDeferredRules -- four ABSENCE tests that assert card/SSN/labelled-token/suppression marker yield ZERO findings. Gate proves property, not just pattern-match.

---

### FINDINGS TABLE

| # | DEFECT | EVIDENCE (file:line) | TIER | DISPOSITION |
|---|--------|---------------------|------|-------------|
| 1 | Path-traversal remote URL bypass: `https://github.com/CFG-INNERSOURCE/../evil/repo.git` passes `startswith` check because the prefix match is purely string-level. git does not normalize `../` in HTTP remote URLs; whether the remote actually resolves depends on server behavior. The practical threat is low (it is the repo owner adding their own remote, and `cairn doctor` also checks with the same `startswith` logic), but the defense is string-only with no URL normalization. | pre_push.py.tmpl:25, DESIGN.md:106-107 | 1 | NOTE |
| 2 | Manifest source decode/read failures are fail-open: `except Exception: pass` on both the staged-content decode path and the disk read path silently skip manifest verification. A corrupt or unreadable manifest means no asset integrity check, and the commit proceeds. File-list failures are correctly fail-closed (`except OSError: sys.exit(1)`), but the manifest ITSELF has no fail-closed protection. | pre_commit.py.tmpl:82-88 | 1 | NOTE |
| 3 | `template.replace("{{SCAN_SOURCE}}\n", scan_source)` in render.py uses `str.replace` which matches ALL occurrences. If scan.py ever contained the literal string `{{SCAN_SOURCE}}\n` (e.g. inside a docstring), the replacement would fire twice, corrupting the inlined region. Currently impossible (scan.py has no template placeholders -- verified), but the mechanism has no guard against content/delimiter collision. The sentinel-not-in-scan.py test pins the sentinel lines but not the placeholder string. | render.py:11, scan.py (verified clean) | 2 | NOTE |
| 4 | `_history_scan` runs by default (depth 20) on every `cairn doctor` invocation. DESIGN.md lines 160-161 and 229 explicitly defer the bounded history scan to v2: "(v2, deferred) A bounded history scan... Deferred from v1; server-side scanning backstops `--no-verify` until v2." The code ships it in v1 as detection-only (warning, not hard fail). This is scope creep against the design document. | doctor.py:81-113, 196-208, DESIGN.md:160-161, 229 | 2 | RAISE |
| 5 | If `scan.py` ever ships with no trailing newline, `render_pre_commit` produces a hook where `# --- END CAIRN SCAN ---` sits on the same line as the last statement of scan.py. This is syntactically valid Python (the sentinel becomes a trailing comment) but breaks the visual contract of the sentinel-on-its-own-line convention. The render test `test_source_with_no_trailing_newline_round_trips` proves the extraction still works. Real scan.py ends with `\n` so this is theoretical. | render.py:11, test_render.py:75-88 | 2 | NOTE |

---

### TIER 0-1 DETAILED ATTACK ANALYSIS (non-findings, confirmed safe)

- **Org-name prefix attack** (`CFG-INNERSOURCE-evil`): CONFIRMED BLOCKED. The trailing `/` on both prefixes is load-bearing: `startswith("https://github.com/CFG-INNERSOURCE/")` requires a `/` at position 35, but `CFG-INNERSOURCE-evil` has `-` at that position. The SSH variant (`git@github.com:CFG-INNERSOURCE-evil/`) fails identically.

- **XDG_CONFIG_HOME as runtime override**: SAFE. `get_allowlist()` in config.py reads `XDG_CONFIG_HOME` only at BAKE time (called by `cairn init` and `cairn doctor`). The rendered pre-push hook has `ALLOWLIST = [...]` as a baked JSON literal with zero env reads. The design explicitly calls XDG_CONFIG_HOME "the seam the test suite uses" (DESIGN.md:721).

- **Masking leak on error paths**: NONE FOUND. Every `Finding` construction goes through `_mask()`. No code path constructs a Finding with an unmasked value. The old mask leaked up to 12 characters from a 40-char token; the new mask leaks exactly 8 (first 4 + last 4) for tokens over 8 chars. The 1-2 and 3-8 char tiers exist in the code but are unreachable by any v1 rule (shortest match is 20-char AWS key id). This is documented in test_scan.py's TestMasking docstring as a FIX-DESIGN gap (masking helper not part of public contract).

- **Encoding tricks**: NO PRACTICAL BYPASS. `decode("utf-8", errors="replace")` converts invalid bytes to U+FFFD. All six regex patterns match ASCII substrings, which survive UTF-8 decode intact. A null byte in the first 8192 bytes triggers binary skip (returning `[]`). The threat model is accidental inclusion, not adversarial encoding, and the replace-error strategy catches all normal accident cases.

- **Staged-deletion carve-out**: SAFE. `get_staged_deletions()` uses `--diff-filter=D`. Renames: the old path gets status D (caught by deletions set) AND the new path gets status A (NOT in deletions, content scanned). A file cannot be both staged-for-deletion and staged-with-content in git's index. The deletion exemption is narrow and correct. As a side effect, binary files now pass through `scan_bytes` (which returns `[]` for them) but are still subject to the asset size cap -- this is a bug fix, not a regression.

- **Manifest missing-file-is-warning contract**: MAINTAINED. `os.path.exists(p)` failure produces a warning and `continue`, not `sys.exit(1)`. Only `OSError` on read (file exists but cannot be read) is fail-closed.

---

### TIER 2: DEAD CODE / DUPLICATION / OVER-ABSTRACTION

- `DEFAULT_ALLOWLIST` lives only in `config.py:6-9`. init.py no longer carries a duplicate. No other module defines or imports the old init.get_allowlist. Clean extraction.
- `check_remotes` still lives in `init.py` and is imported by `doctor.py`. Minor coupling (init and doctor import from each other transitively), below materiality threshold for a personal CLI.
- No dead imports, no unused functions, no over-abstraction detected in the diff.

---

### OPEN QUESTION: _history_scan (FINDING #4, expanded)

The code ships `_history_scan` with default depth 20, running on every `cairn doctor`. DESIGN.md explicitly defers this to v2 at lines 160-161: "(v2, deferred) cairn doctor will run a bounded history scan as part of its base checks... Deferred from v1 because corporate GitHub scans server-side." And again at line 229 in the doctor spec.

Recommendation: **STRIP IT.** The design deferred it for a reason (v1 scope is staged-content pre-commit scan only; v2 adds history scan when server-side backstop analysis is more complete). Shipping it now is undocumented scope creep. It is detection-only (warning, not hard fail), so it is not a security regression, but it violates the design contract. If Ken wants it in v1, update DESIGN.md to bring it forward and re-review. Stripping it is a 10-line deletion in doctor.py (remove `_history_scan` function, the `depth` computation, and the history_findings display block).

---

### VERDICT

No BLOCK findings. Two NOTE items (path-traversal prefix check, manifest fail-open on decode error), two minor NOTES (placeholder collision risk, trailing-newline edge case), one RAISE (history scan in v1 against DESIGN.md). The four original blockers are DEAD with clear evidence.

**Review verdict: MERGE WITH FOLLOWS**

Follows:
1. Strip `_history_scan` from doctor.py to conform to DESIGN.md v1 scope (or update DESIGN.md to bring it forward).
2. Tighten manifest source read failures from `except Exception: pass` to fail-closed (or document the fail-open decision in DESIGN.md).
3. Consider URL normalization in the allowlist check to close the path-traversal string-bypass (low priority, defense-in-depth).
```

## rev2
```
Findings

| # | DEFECT | EVIDENCE (file:line verified) | TIER | DISPOSITION |
|---|---|---|---|---|
| 1 | `doctor` still hardcodes `~/.local/bin` in `_local_bin_on_path()`, which contradicts the design’s install-method agnostic PATH check and can false-fail brew, offline shim, and hermetic test installs. | `src/cairn/commands/doctor.py:40-44`; DESIGN.md:231 | Tier 1 | BLOCK |
| 2 | Remote inspection still fails open if `git remote -v` errors, because `check_remotes()` returns success on nonzero exit. That is a fail-open path in the remote policy preview and should be closed if the command cannot inspect remotes. | `src/cairn/commands/init.py:11-14` | Tier 1 | NOTE |
| 3 | `_history_scan` is still active by default with depth 20, even though DESIGN.md defers bounded history scanning to v2. This is not a hard fail, but it is out of scope for v1 and should be stripped or explicitly hidden as a preview. | `src/cairn/commands/doctor.py:71-113`, `src/cairn/commands/doctor.py:200-205`; DESIGN.md:160, 229 | Tier 2 | RAISE |

Blocker confirmations

1. DEAD: No runtime env override remains in the rendered pre-push hook path. The hook uses baked `ALLOWLIST`, and render time sources it from config only. Evidence: `src/cairn/hooks/pre_push.py.tmpl:7, 27-33`, `src/cairn/hooks/render.py:14-16`, `src/cairn/config.py:11-50`.

2. DEAD: `doctor` detects diverted `core.hooksPath` and includes it in the final hard fail set. Evidence: `src/cairn/commands/doctor.py:149-160`, `src/cairn/commands/doctor.py:229-240`.

3. DEAD: `doctor --fix` no longer clears unrelated failures. It only reinstalls hooks, then recomputes all failure flags, so remote, hooksPath, repo, email, and version failures persist. Evidence: `src/cairn/commands/doctor.py:213-241`.

4. DEAD: The v1 scan now contains exactly the six design rules, with no `card`, `us_ssn`, `labelled_token`, `entropy`, or suppression code left in `src/cairn/scan.py`. Evidence: `src/cairn/scan.py:45-103`; `git grep` over `src/cairn` returned no matches for those removed rule names.

Review verdict: REWORK
```
