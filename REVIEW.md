# REVIEW.md - Cairn design review log

Per-finding review rationale for [DESIGN.md](./DESIGN.md). DESIGN.md integrates the decisions; this file holds the reasoning behind them.

**Note on history:** the 2026-07-24 cross-family adversarial review (GLM brain + DeepSeek; verdict DESIGN-FIX-FIRST; six BLOCK findings, all the safety-control-bypass class) produced a REVIEW.md that was lost in a `/tmp` wipe before this repo stood up. Its decisions survive, integrated into DESIGN.md (and the locked decisions as D027-D042); the per-finding rationale does not. This file therefore begins at the 2026-08-03 review below.

---

## 2026-08-03 - Opus completeness pass

Reviewer: Opus (Claude family), deliberately cross-family from the GLM/zai models that authored and reviewed most of the design, so the gate is independent. Mandate: read the current full DESIGN.md (post gap-closure) and find what is MISSING, AMBIGUOUS, or UNIMPLEMENTABLE so nothing has to be invented at build time. Adversarial; a rubber-stamp is worthless.

**Status after this review (same day):** Addressed in DESIGN.md: B1, B2, G1, G3, G4, G5, G6, G7, G8, G9, G10. G2 scoped to v1 (known-pattern rules; the entropy token, entropy gate, and suppression marker are deferred to v2). G13 deferred to v2 (history scan). Still open: G11 (Phase 2/3 validate error/warning classification), G12 (Phase 4 tag design, punted to a nonexistent TODO.md), and the 14 NITs.

### BLOCKERS (block Phase 1)

**B1 - `cairn doctor` PATH check is incompatible with every install method except pipx.** The check "`~/.local/bin` on PATH" is pipx-specific. Under brew, cairn lives at `$(brew --prefix)/bin`; under the offline zipapp the shim is unspecified; under the dev venv it is `.venv/bin`; under the hermeticity rule (HOME to a temp dir) `~/.local/bin` is not on PATH, so doctor cannot pass inside its own test suite. The check is also near-tautological: if doctor is running, cairn is already resolvable. Implementer must invent whether to drop it, detect the install method, or replace it with "is the running interpreter's bin dir on PATH."

**B2 - Allowlist config source is unspecified.** Path, defaults, and precedence (per-vault vs per-user) are all unstated. Load-bearing: `cairn init` bakes the allowlist into the pre-push hook in Phase 1. Implementer must invent the config file location and whether init fails when no config is present.

### GAPs (must resolve before the affected phase)

**G1 - Stale hook-resolution text contradicts the inlining design, specifically for brew.** Line 112 ("the hook resolves the interpreter... vendored/third_party copy or the installed entry point") describes a superseded mechanism; the Hook mechanism section inlines scan.py under a static shebang. An implementer would build the resolution, then find the contradiction. For brew, this answers "does the formula need to vendor third_party?" both YES and NO.

**G2 - `scan_bytes` interface contract omits four behaviors the prose assigns to it.** The contract (signature + Finding fields, "never raises, never does I/O") omits: suppression via the `cairn:allow-secret` marker; masking of Finding.excerpt; the Shannon-entropy gate; and the binary null-byte skip (and whether it lives inside scan_bytes or the caller). All four must live inside scan_bytes (the hook inlines it with no wrapper), so a builder using the contract ships a scanner missing all four.

**G3 - Tag normalization rule is inconsistent with the slug rule.** Tags collapse whitespace only; slugs collapse all non-alphanumerics. Slash/ampersand/punctuation in tags is unresolved. Affects `cairn new` (Phase 1) and the tag-normalization test.

**G4 - Slug transliteration algorithm is named but not defined.** "Transliterate accented characters where possible" names no algorithm/library. NFKD does not handle ß or CJK. The determinism test cannot be written until expected outputs are fixed.

**G5 - Python 3.11+ from Xcode CLT is an unverified claim.** Recent CLT ships 3.9, not 3.11. If so, pipx and the bare-python path break and the "avoid pyenv" rule leaves only brew to get 3.11. (Resolved 2026-08-03: the target work Mac has 3.14.6, so the floor is met; source is not CLT and needs recording.)

**G6 - Offline install puts nothing named `cairn` on PATH; the shim is unspecified.** A zipapp yields `cairn.pyz`; nothing says how the bare `cairn` command becomes callable. Interacts with B1.

**G7 - Brew install path has no test, contradicting the doc's own co-primary rule.** "Co-primary means tested"; brew has no test specified.

**G8 - Public-source prerequisite for brew is not sequenced or tracked.** Open-sourcing Cairn appears in no phase or TODO, yet brew is non-functional until it happens, undercutting "co-primary."

**G9 - Brew-as-PyPI-fallback assumes github.com is reachable when pypi.org is not; unstated and commonly false.** Locked bank networks that block PyPI commonly block public github.com too. Brew may be a paper fallback; the offline bundle may be the only real one.

**G10 - README contradicts DESIGN on Homebrew and on the completeness pass.** README still says "no Homebrew" / "pipx-installed" and lists the completeness pass as future. (Resolved 2026-08-03: README synced.)

**G11 - `cairn validate` does not classify stale generated files or duplicate filenames as error vs warning.** The exit-code classification is unspecified.

**G12 - Phase 4 tag design is punted to a TODO.md that does not exist, while the README claims the design is complete.** "Tag normalization and mutation semantics" are undecided, and they spill into Phase 1's write-time tag normalization (G3).

**G13 - History-scan mechanism is unspecified.** Full-tree-per-commit vs diff, the git invocation, and binary handling are all unstated. Full-tree-per-commit is O(20 * vault) and wasteful; diff-per-commit must handle "secret in unchanged context added in this commit's parent."

### NITs

- N1 - Status block points to REVIEW.md and decisions.md as present; the header says they are gone. Same for working-agreement.md. Four cited files do not exist.
- N2 - Manifest `referenced_by` is a single string; multi-note reference is unstated. State the v1 single-owner assumption.
- N3 - Manifest `path` "always begins assets/local/" is a rule but the hook verifies only SHA-256; the prefix invariant is unenforced.
- N4 - `cairn tags` is listed without a phase annotation; its siblings are Phase 4. Annotate it.
- N5 - Doctor checks "PyYAML importable at expected version"; no version is pinned anywhere.
- N6 - `cairn capture` title truncation (80 chars): hard cut vs word-boundary unstated; matters for CJK.
- N7 - Doctor check ordering (all-at-once vs fail-fast) unstated.
- N8 - "Duplicate note filenames" validate check: the slug-collision rule prevents duplicates by CLI construction, so state the trigger (the check only catches manual edits).
- N9 - `cairn new` does not check title collision, only filename collision; two "Foo" notes yield ambiguous wiki-links. State the intended gate.
- N10 - Payment-card Finding excerpt: stripped run vs original line unstated.
- N11 - `id` field generation method + uniqueness check unstated; a collision is a latent bug.
- N12 - Brew formula's PyYAML dependency mechanism (`resource` vs `depends_on`) unstated.
- N13 - `cairn capture --file <path>`: relative to CWD or vault? Unstated.
- N14 - History-scan as "warning" names no remedy; remediation is git history surgery, which Cairn does not provide. State "manual, out of scope."

### Verdict

BUILD-READY-WITH-GAPS. Phase 1 cannot start until B1 (doctor PATH check) and B2 (allowlist config) are resolved; G1, G2, G3, G4, G12, and G13 land inside Phase 1 itself.

---

## 2026-08-03 - Opus confirmation re-review

Same Opus critic, re-run after the fixes above, to verify they landed and to catch new issues the edits introduced. **Verdict: NOT-READY** (a downgrade - the "go lighter" scan-scope cut introduced a blocker).

**Confirmed resolved:** B2, G1, G4, G5, G6, G7, G8, G9. **Partially resolved:** B1 (the check is correct, but its parenthetical justification is wrong - hooks do not invoke `cairn`); G3 (slash rule is clear, but leading/trailing/double-slash edge cases are undefined); G10 (README Homebrew synced, but "PII scan" wording and a stale completeness-pass status remained).

**New findings:**
- **NEW-1 (BLOCKER, introduced by the scan cut):** v1 shipped the payment-card rule with the suppression marker deferred to v2, leaving no escape for its admitted false positives - the exact "scanner with no way out gets disabled wholesale" state the design argues against. **Resolved same day:** card and SSN rules dropped from v1 (Ken never has access to that data and would never note it), so v1 is private-key + AWS-key only - no false-positive-prone rule, no suppression needed. Entropy-token, entropy gate, suppression, and history scan stay deferred to v2.
- **NEW-2 (GAP):** README called it a "PII scan" and listed the completeness pass as future. **Resolved.**
- **NEW-3 / NEW-4 (GAP):** the v1/v2 boundary was stated once and not propagated to the rules table or the required-tests list. **Resolved** (inline v1/v2 markers added).
- **NEW-5 (GAP, security):** the "truncate to 12 chars" masking printed an 11-char SSN in full and violated "never print the full secret"; masking location was unclear. **Resolved:** masking happens inside `scan_bytes` (every consumer safe); first/last-character scheme, full match never emitted.
- **NEW-6 (GAP):** search tag-query normalization (whitespace + case) diverges from tag-write normalization (slug + slash). **Open** (Phase 3 search).
- **NEW-7 (GAP, security):** the baked allowlist was fail-open on config tightening. **Resolved:** re-bake-on-edit is documented and `cairn doctor` fails loudly on hook-vs-config drift.
- **NEW-8 (GAP):** the "binding" hook contract specifies the embedding but not the hook's own logic (staged-file enumeration, `git show`, output formatting, exit code). **Open** (address as the hooks are built in Phase 1).
- **NEW-9 to NEW-12 (NITs):** PyYAML version floor; missing-doc references; "co-primary" terminology muddled across three paths; hook vs CLI may run different Python versions.

**Verdict after these re-review fixes:** BUILD-READY-WITH-GAPS for Phase 1. The blocker (NEW-1) is resolved; remaining items (NEW-6, NEW-8) are later-phase or resolve naturally as the hooks are built. The card/SSN drop and "v1 = private key + AWS" decision is the load-bearing change.
