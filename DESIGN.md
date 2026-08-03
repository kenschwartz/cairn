---
title: Cairn design
status: draft
project: cairn
---
> **Canonical design document.** Cairn is built and developed HERE, on Ken's own Mac with the
> Hermes agent fleet (decided 2026-08-03). It is deployed to a locked-down work Mac, which is the
> reason it exists, not a classification of this document.
>
> **Why Cairn exists:** Ken cannot use [Obsidian](https://obsidian.md/) at work and needs an
> alternative. Citizens does not permit it and
> [OneNote for Mac](https://support.microsoft.com/en-us/onenote/onenote-for-mac-help-and-learning/frequently-asked-questions-about-onenote-for-mac)
> is inadequate, so Cairn is his own Obsidian-equivalent: a deterministic
> [Python](https://www.python.org/) CLI over a Markdown vault. That is the whole idea.
>
> Cairn contains nothing proprietary: no bank data, no customer data, no PII. See [README](./README.md).
>
> History: drafted with Copilot 2026-07-24, then revised the same day after a cross-family
> adversarial review (verdict DESIGN-FIX-FIRST; safety controls moved from CLI-only to git-hook
> enforcement). The companion `REVIEW.md` and `decisions.md` D027-D042 from that review are not
> currently on this machine; recovering them is tracked in the vault note `Cairn`.

# Cairn design

> **Status of this document:** revised 2026-07-24 after an adversarial cross-family design review (verdict DESIGN-FIX-FIRST). The review's six BLOCK findings were all one class: safety controls that lived inside the CLI and were bypassable by raw git, Copilot, or any non-CLI writer. The fix is structural: enforce at the git-hook layer, owned by `cairn init`, verified by `cairn doctor`. Those changes are integrated below. See `REVIEW.md` for the finding-by-finding rationale and `decisions.md` D027+ for the locked decisions.
>
> **Naming:** the CLI command is **`cairn`** (renamed from `vault` to avoid clashing with the word "vault" used throughout for the note repository itself). Package `src/cairn/`, entry point `cairn = cairn.cli:main`. Where prose says "the vault" it means the note repository; where it says `cairn <cmd>` it means the command.

## Purpose

Build a personal Markdown vault to replace the useful parts of OneNote on Ken's work Mac:

- fast note capture
- todos
- links between notes
- searchable tags and metadata
- lightweight references to Outlook items
- copied assets such as PDFs and images
- local git history

The system is for one user only and runs on one Mac only.

## Strong recommendation

Build the local Markdown vault first. Do not build version 1 around OneNote, Outlook, Microsoft Graph, Hexo, or Obsidian as required dependencies.

Those tools should be treated as adapters or future conveniences. The core system should still work if none of them is available.

## Version 1 goals

Version 1 is successful when Ken can:

1. Create a note from the command line.
2. Capture messy content into an inbox.
3. Normalize content into a Markdown note with standard frontmatter.
4. Add Markdown checkbox todos.
5. Link notes together.
6. Search notes by text, title, tag, type, status, and project.
7. Generate a dashboard focused first on todos.
8. Generate and maintain a tag index.
9. Copy PDFs, images, and source files into `assets/`.
10. Automatically create local git commits after successful write commands.

## Explicit non-goals for version 1

- Automated OneNote import.
- Microsoft Graph integration.
- Direct Outlook email or meeting import.
- Reliable deep links back to Outlook items.
- Obsidian-specific behavior beyond portable Markdown and simple wiki-style links.
- Hexo/static-site publishing.
- HTML export.
- Multi-user support.
- Sync service. Backup is via manual `git push` to corporate GitHub Enterprise only.
- CLI calls to an LLM API.

## Operating assumptions

- The vault lives in a local folder under `$HOME`, including company-managed folders available on the work Mac.
- Git is used for version history in the vault itself.
- Backup is a manual `git push` to a private repository on **corporate GitHub Enterprise**. No personal, external, or third-party remotes are permitted.
- Automatic git behavior is local commits only. Pushes to the corporate remote are always manual and explicit.
- `cairn` (the CLI) is deterministic and never sends note contents to a remote service on its own.
- The work Mac is locked down, so avoid dependencies that require admin rights or special enterprise approval.
- File writes happen against the local filesystem. For Markdown and generated files, the CLI should write a temporary file in the same directory and then atomically replace the target after the write succeeds.

### Data-handling constraints (hard)

- **Nothing leaves the bank via the vault tooling.** No personal GitHub, no personal cloud storage, no third-party sync, no external backup service, no LLM API uploads of note contents. This is enforced at the git-hook layer (see "Security enforcement via git hooks"), not only inside the CLI.
- **Cloud assistants are out of scope of the tooling's enforcement.** Copilot, Outlook, OneNote, and any other cloud-connected tool are not controlled by Cairn. Pasting note content into a cloud assistant is a separate, human risk decision: do not paste into Copilot anything you would not put in an email. "Nothing leaves the bank" is a guarantee about the vault tooling, not a guarantee about every tool Ken touches.
- Assume the corporate Mac is subject to endpoint monitoring and that the corporate GitHub Enterprise repo is subject to admin review, audit, and retention. Treat everything written to the vault as observable by the employer.
- Do not store customer PII, account numbers, credentials, MNPI, or any restricted data. These notes are personal working notes only.
- A pre-commit content scan is required as defense in depth even though corporate GitHub also enforces server-side scanning. It is better to be blocked locally than to trip a security event. The scan covers **secret patterns and structured identifiers only**: v1 ships private keys, AWS keys, Luhn-valid card numbers, and SSN patterns; high-entropy-token detection is deferred to v2 (server-side scanning backstops it). Unstructured PII and MNPI (names, addresses, free text) cannot be caught by regex; those are governed by policy and by Ken, with server-side scanning as backstop. Do not imply the scan covers all PII.

## Security enforcement via git hooks

This is the most important section in the design. A control enforced only inside the CLI is a **soft control**: raw `git commit`, raw `git push`, Copilot-assisted edits committed by hand, or any other writer bypasses it. At a bank the controls are the whole point, so the hard enforcement lives in git hooks, which fire on every commit and every push regardless of how they are invoked.

`cairn init` owns hook installation. No other component can, because the hooks must exist before the first commit and must survive clones. The hooks are:

- **`.git/hooks/pre-commit`** (fires on every commit):
  - Runs the content scan (secret patterns + structured identifiers) on the staged files.
  - Checks that no staged file under `assets/` exceeds the size cap.
  - Verifies the `assets/local/` manifest: for every manifest entry, the on-disk file's SHA-256 must match the recorded hash. A mismatch (file replaced outside Cairn) fails the commit with a clear message.
- **`.git/hooks/pre-push`** (fires on every push):
  - For every push target, resolves the remote URL and rejects it unless it matches the corporate allowlist. This is the real enforcement of "no personal remotes"; the `cairn init` / `cairn doctor` check is a convenience preview, not the gate.

Properties the hook layer must satisfy:

- Hooks are content-pinned. `cairn doctor` verifies that both hooks exist, are executable, and match a fresh in-memory re-render from the current package and config (by SHA-256). A missing, altered, or stale hook fails doctor. See "Hook mechanism" below for how the re-render works.
- Hooks do not survive `git clone`. `cairn init` is idempotent and reinstalls hooks, so the documented first step on any fresh clone is `cairn init` (or `cairn doctor --fix`).
- Hooks must not depend on the install venv being active at hook time. The pre-commit hook inlines `scan.py` verbatim (see "Hook mechanism") under the static `#!/usr/bin/env python3` shebang, so it needs no interpreter resolution and no vendored third_party. (An earlier draft described resolving a vendored copy or the installed entry point; that was superseded by the inlining design.)
- Hooks are local only and can be removed by a determined user with filesystem access. That is acknowledged: the hooks raise the bar and make accidents fail loudly, they are not a defense against deliberate circumvention by the repo owner. Server-side corporate GitHub scanning is the backstop for the residual risk.

### Hook mechanism (implementation contract)

The properties above say what the hooks guarantee. This section says how, and it is binding: an implementation that satisfies the properties by another mechanism is not conforming, because `cairn doctor` verifies the mechanism itself.

**Hooks are RENDERED, not copied.** The package ships templates at `src/cairn/hooks/pre_commit.py.tmpl` and `src/cairn/hooks/pre_push.py.tmpl`. `cairn init` renders each template into a single self-contained script and writes it to `.git/hooks/pre-commit` and `.git/hooks/pre-push` (mode `0o755`). Rendering substitutes exactly two things:

1. `{{SCAN_SOURCE}}` - the full source text of `src/cairn/scan.py`, inlined.
2. `{{ALLOWLIST}}` - the remote allowlist as a JSON literal (pre-push only).

Inlining the scan source is deliberate and it is what removes the drift risk. There is exactly ONE authored copy of the scan logic (`src/cairn/scan.py`); the hook copy is generated from it and is never edited by hand.

**Embedding scheme.** The inlined source is placed verbatim between two sentinel comment lines:

```python
# --- BEGIN CAIRN SCAN (generated, do not edit) ---
<verbatim contents of scan.py>
# --- END CAIRN SCAN ---
```

Verbatim, at module level, not wrapped in a string. This avoids every quoting and escaping failure mode: a `"""` or a `\` inside `scan.py` is just source code. The byte-identity test extracts the region between the sentinels and compares it to `scan.py` on disk. `scan.py` must therefore never contain either sentinel line, which a test asserts.

**`scan.py` interface (the hook calls this, so it is a contract):**

```python
def scan_bytes(data: bytes, path: str) -> list[Finding]
```

`Finding` is a dataclass with `rule: str`, `path: str`, `line: int`, `excerpt: str`. `excerpt` is masked INSIDE `scan_bytes` (see "Failure behaviour") so it never holds a full secret for any consumer. An empty list means clean. The function never raises for malformed input and never performs I/O, which keeps it trivially testable. v1 scope: the private-key and AWS-key rules plus the binary null-byte skip. The card, SSN, and entropy-token rules and the `cairn:allow-secret` suppression are not v1 and live inside scan_bytes when added (the hook inlines scan_bytes with no wrapper, so any scan behavior must live inside it).

**No interpreter is substituted.** The shebang is the static line `#!/usr/bin/env python3`. This is a correction to an earlier draft of this section, which baked the resolved interpreter path into the hook at init time and broke content pinning: `sys.executable` changes on every `pipx upgrade`, so a re-render would mismatch the installed hook and `cairn doctor` would fail after every upgrade despite the hooks working fine. Removing the field is better than exempting it from the comparison, because it deletes the failure mode instead of carving out an exception.

This is safe on the target platform specifically: macOS with Xcode Command Line Tools always provides `/usr/bin/python3`, and `/usr/bin` is on `PATH` even in the reduced environments that GUI git clients hand to hooks. The hook checks `sys.version_info >= (3, 8)` and exits with a clear message otherwise. Note that floor is the SCAN's requirement, deliberately lower than the CLI's 3.11, because the hook may run under the system interpreter rather than the one Cairn was installed with.

**Therefore: `src/cairn/scan.py` MUST import only the Python standard library.** No PyYAML, no third-party package, no import of the rest of `cairn`. The scan reads bytes and applies regexes; it never parses YAML, so this costs nothing. This constraint is load-bearing for the whole hook design and a test enforces it by importing `scan.py` with the rest of the package hidden from `sys.path`.

**Content pinning is re-render-and-compare, not a stored hash.** `cairn doctor` renders the templates again, in memory, from the current package and current config, and compares the SHA-256 of the result against the SHA-256 of the installed hook file. There is no hash constant to keep in sync, and one check catches three real failure modes with one remedy (`cairn doctor --fix`): a hand-edited hook, a hook left behind by an older Cairn version, and a hook whose baked-in allowlist no longer matches the configured one. Because both substituted fields are pure functions of package and config, this comparison has no false-positive class.

**Doctor also verifies the mode is `0o755`.** A content hash covers bytes, not permissions, and a hook that is not executable is silently skipped by git. Content-correct plus non-executable is the worst state available: it passes the pin and enforces nothing.

**Scope for v1: one top-level worktree.** The hooks resolve vault-relative paths from the working directory git hands them, which is the worktree root for a normal repository. `core.hooksPath`, linked worktrees, and submodules are out of scope for v1; `cairn doctor` reports rather than adapts if it finds `core.hooksPath` set.

**`--no-verify` is one bypass among several, which is why prevention is not attempted.** `git commit --no-verify` and `git push --no-verify` skip hooks entirely. Cairn cannot prevent this and must not claim to. Nor is the flag the actual gap: anyone who can pass it can equally delete the hook, `chmod -x` it, edit it to `exit 0`, or repoint `core.hooksPath`. The hook is a file in the user's own working directory and there is no privilege boundary. Git puts real enforcement server-side for exactly this reason, and corporate GitHub Enterprise scanning is that boundary here.

So the preventive control is paired with a DETECTIVE one, and the detective control must FIRE ON ITS OWN:

- (v2, deferred) `cairn doctor` will run a bounded history scan as part of its base checks: the working tree plus the last 20 commits, reported as a warning rather than a hard fail, with `cairn doctor --scan-history N` to widen depth. Deferred from v1 because corporate GitHub scans server-side and backstops a `--no-verify` bypass; the v1 scan is the staged-content pre-commit hook only.
- Making it a base check rather than an opt-in flag is the whole point. A detective control nobody remembers to invoke is decorative, and `cairn doctor` already runs before write commands, so the accident case (a hurried `--no-verify` past an unrelated hook failure) surfaces on its own within one working session.

## Prerequisites and installation

### Required on the Mac

- **Python 3.11+**, no admin required (`python3 --version` must report 3.11 or later). Verified 2026-08-03: the target work Mac runs Python 3.14.6, so the floor is met with headroom. NOTE: 3.14.6 is NOT from Xcode Command Line Tools (CLT ships Python 3.9); confirm the actual source on the work Mac (likely Homebrew or a python.org installer) and record it. A Homebrew Python is acceptable since brew needs no sudo; avoid pyenv or any interpreter that itself requires admin to install.
- **git 2.30+**, provided by Xcode Command Line Tools.
- **PyPI reachable** from the corporate network for the user-scoped pipx install. If PyPI is blocked, the Homebrew path works ONLY if public github.com is also reachable (brew fetches the tap and release archive from github.com; locked bank networks that block pypi.org commonly block github.com too, so verify on the work Mac). If both are blocked, the offline bundle below is the only guaranteed path. Treat the offline path as co-primary, not rare.
- **Not required:** `git-lfs`, admin rights, pyenv, virtualenvwrapper, Docker. Homebrew is not required either, but it IS available on the work Mac; the Homebrew install path below is co-primary with pipx.

### Install path (per-user, no admin)

The CLI is packaged as a normal Python distribution with a console entry point (`cairn = cairn.cli:main`) declared in `pyproject.toml`. Installation uses `pipx` so the CLI runs in an isolated virtualenv and its dependencies (PyYAML, and whatever else v1 pulls in) never pollute user site-packages.

Bootstrap steps for a fresh Mac:

```bash
python3 -m pip install --user pipx
python3 -m pipx ensurepath        # adds ~/.local/bin to PATH via shell rc
# open a new shell so PATH is refreshed
pipx install /path/to/cairn-repo  # or: pipx install -e /path/to/cairn-repo for dev
cairn --version
```

The `cairn` entry point ends up at `~/.local/bin/cairn`. Do not use `~/bin`; `~/.local/bin` is the standard `pipx` target.

### Install via Homebrew (co-primary)

Homebrew is available on the work Mac and installs public packages with **no sudo**, so a public Homebrew tap is the cleanest path and the one that gets updates for free (`brew upgrade cairn`). It is co-primary with pipx; pipx and the offline bundle remain as fallbacks for machines without brew or PyPI.

```bash
brew tap kenschwartz/cairn        # public tap repo: github.com/kenschwartz/homebrew-cairn
brew install cairn
cairn --version
```

**Prerequisites (both required, both tracked gates):**
1. The tap and the release source are public so brew can fetch them. This gates on open-sourcing Cairn, a tracked pre-deploy step (see the open-source to-do in the vault Inbox), not an assumption; until the repo and a release archive are public, this path does not work and pipx/offline are the only functional paths.
2. Public github.com is reachable from the work Mac. This is NOT guaranteed on a locked bank network (PyPI and github.com are often blocked together); verify before relying on brew as a PyPI fallback.

The formula builds from a public release archive, installs the `cairn` entry point into brew's prefix, performs no sudo steps, and the no-admin invariant is unchanged: no system daemon, no root, no writes outside user space.

### `cairn init`

`cairn init` creates the vault and owns all the safety infrastructure. It is idempotent. On a fresh or existing vault it:

1. Creates the folder structure (`notes/`, `moc/`, `assets/`, `assets/local/`, `indexes/`).
2. `git init` the vault if it is not already a repository.
3. Writes `.gitignore` (`.DS_Store`, `*~`, `*.swp`, `*.swo`, `assets/local/`).
4. Installs `.git/hooks/pre-commit` and `.git/hooks/pre-push` (content-pinned; overwrites stale hooks).
5. Verifies any configured remote against the allowlist; rejects unknown remotes. Zero remotes is allowed (warning, see `cairn doctor`).
6. Checks `git config user.email`; if missing, creates folders and hooks but refuses auto-commit with a clear message.

`cairn init` reports what it created versus what was already present. Running it on an existing vault reinstalls hooks and rechecks remotes; it does not destroy notes.

### `cairn doctor`

`cairn doctor` must verify, and refuse to run write commands until all pass:

- Python version >= 3.11.
- PyYAML importable at expected version.
- `git` on PATH, version >= 2.30.
- `git config user.email` set (auto-commit fails without it).
- Vault directory exists and is a git repo.
- **Both git hooks present, mode `0o755`, and SHA-256-matching a fresh re-render** from the current package and config. A missing, non-executable, altered, or stale hook is a hard fail; `cairn doctor --fix` reinstalls them.
- (v2, deferred) A bounded history scan (working tree plus the last 20 commits) reported as a warning, which catches a commit made with `--no-verify`. Deferred from v1; server-side scanning backstops `--no-verify` until v2.
- Remote policy: zero remotes is a **warning** (you cannot back up until you add one, but local-first use is allowed). One or more remotes: every remote URL must match the allowlist; any non-matching remote is a hard fail.
- The directory of the running `cairn` executable is on PATH (so hooks and sub-processes can invoke it). This is install-method agnostic: do NOT hardcode `~/.local/bin`, which is pipx-only and false-fails under brew (`$(brew --prefix)/bin`), the offline zipapp shim, a dev venv (`.venv/bin`), and hermetic tests where HOME is a temp dir.

### Offline install fallback

If neither Homebrew nor PyPI is usable from the corporate network, skip both and install offline. The complete alternative is:

1. Vendor PyYAML (and any other pure-Python dependencies) into `third_party/` inside the repo, committed.
2. Build the CLI as a `zipapp` (`python3 -m zipapp`) producing `cairn.pyz`, or run directly from the repo with system Python and `PYTHONPATH` pointing at `third_party/`.
3. Install a `cairn` shim on PATH. The zipapp alone is `cairn.pyz`, not the bare `cairn` command, so a one-line wrapper is required: place the `.pyz` at a stable path (e.g. `~/.local/share/cairn/cairn.pyz`) and write a shim at `~/.local/bin/cairn` whose body is `exec python3 "$HOME/.local/share/cairn/cairn.pyz" "$@"` under a `#!/bin/sh` shebang, then `chmod +x` it. The executable now resolves under the install-method-agnostic PATH check (see `cairn doctor`).
4. Document the exact commands in the repo README.

This is a standalone install path with no pipx and no network. Because many bank Macs block PyPI, test this path early; do not treat it as a rare edge case. See "Testing the offline install path": co-primary means there is a test, not just this paragraph.

### Development environment (Ken's own Mac, where Cairn is built)

Everything above describes installing Cairn on the DEPLOYMENT target. Development happens here, on Ken's own Mac, with the agent fleet. That environment has none of the corporate constraints and should not pretend to:

```bash
cd ~/docker/hermes/sessions/cairn
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

Once the public tap exists, the dev-to-deploy loop is: build here, push, tag a release, then `brew upgrade cairn` on the work Mac. No personal data crosses over; it is a public package install.

Three rules that keep the two environments from contaminating each other:

- **A dev-only dependency must never become a runtime dependency.** Runtime deps for v1 are PyYAML and nothing else, because every runtime dep has to survive the offline install. `pytest` and friends live in the `dev` extra only. A test asserting that `src/cairn/` imports nothing outside the standard library plus PyYAML enforces this.
- **The deployment paths are tested here, not assumed.** Both the pipx install and the zipapp offline path are exercised by tests on this machine. The work Mac is not a debugging environment; anything that fails there costs a round trip measured in days.
- **The remote allowlist must be overridable for tests, and defaults to empty.** A test vault has zero remotes, which `cairn doctor` treats as a warning rather than a failure, so the suite runs clean. Tests that exercise allowlist enforcement set the allowlist explicitly against a local bare repo. The allowlist is read from config at `cairn init` time and baked into the rendered pre-push hook; the test override goes through that same config path so the tests exercise the real mechanism.

## Architecture

Cairn is a Python command-line application that manages a Markdown-first vault.

The CLI owns the structure. That is important because manual maintenance of frontmatter, tags, MOCs, and indexes will drift over time. The CLI should enforce the minimum schema and regenerate derived files.

### Core components

| Component | Responsibility |
| --- | --- |
| CLI | User-facing commands such as `new`, `capture`, `search`, `tag`, and `dashboard` |
| Vault paths | Locate and validate folders such as `notes/`, `moc/`, `assets/`, and `indexes/` |
| Frontmatter parser | Read, validate, and write YAML frontmatter |
| Note writer | Create and update Markdown notes safely |
| Search | Search content and frontmatter using local files |
| Index generator | Generate tag index, dashboard, and later MOC indexes |
| Asset manager | Copy files into `assets/` and record optional source metadata |
| Git adapter | Commit successful write operations locally |
| Hook installer | `cairn init` writes and `cairn doctor` verifies the pre-commit and pre-push hooks |

## Vault structure

Recommended initial structure:

This is the structure of a USER'S note vault, which is what `cairn init` creates. It is not the structure of this source repository. Cairn's own design documents live in the Cairn repo and are never written into a user's vault.

```text
<vault>/
  notes/
  moc/
  assets/
    local/              # gitignored large binaries
    local.manifest.json # committed; tracks the above
  indexes/
    tags.md
  dashboard.md
```

### Folder rules

- `notes/` contains all Markdown notes, both durable and rough captures. Rough captures are identified by the `inbox` tag, not by folder.
- `moc/` contains map-of-content notes.
- `assets/` contains copied PDFs, images, and other source files under the size cap.
- `indexes/` contains generated indexes.
- `dashboard.md` is generated.

Avoid deep topic folders. Organization comes from frontmatter, tags, links, and MOCs.

## Note model

Every durable item should become a Markdown file.

Frontmatter must be parsed and written with `PyYAML`. Do not hand-roll YAML parsing in version 1.

### Required frontmatter fields

All notes should contain these fields:

```yaml
---
id: a1b2c3d4
title: Example Title
type: note
status: active
project:
tags:
  - example
created: 2026-07-21
updated: 2026-07-21
cairn_version: 1
moc:
source:
source_url:
---
```

### Field rules

| Field | Rule |
| --- | --- |
| `id` | Required, 8-character hex, generated at creation, never changed |
| `title` | Required, human-friendly. Authoritative for wiki-link resolution; there is no filename fallback because validation requires this field |
| `type` | Required, fixed vocabulary |
| `status` | Required, fixed vocabulary |
| `project` | Optional. For version 1 core commands, leave empty unless `--project` is provided |
| `tags` | Required, at least one tag, normalized at write time (see Tags) |
| `created` | Required, ISO date, set at creation and never changed |
| `updated` | Required, ISO date, refreshed by the CLI on every write |
| `cairn_version` | Required, integer schema version. `1` for this version. Reserved for forward migration |
| `moc` | Optional, may contain one or more MOC links |
| `source` | Optional plain source reference, such as Outlook subject/date/person |
| `source_url` | Optional URL or company-managed source path |

The canonical field for map-of-content links is `moc`. Do not use `maps` as a frontmatter field in this vault.

Interactive project suggestions may be added later, but version 1 core commands should not prompt for `project`. Capture must stay fast and non-interactive commands must remain scriptable.

### Type vocabulary

Keep `type` small and structural:

- `note`
- `todo`
- `meeting`
- `reference`
- `project`
- `moc`

Do not add topic-like types such as `architecture`, `research`, `email`, `capability-map`, or `trade-finance`. Those belong in tags or MOCs.

### Status vocabulary

- `active`
- `waiting`
- `done`
- `archived`

## Links and MOCs

Both standard Markdown links and wiki-links are first-class in this vault. Use whichever is more convenient.

### Accepted link forms

- Standard Markdown: `[text](relative/path.md)`, `[text](relative/path.md#heading)`, external URLs (`http:`, `https:`, `mailto:`).
- Wiki-link: `[[Title]]`, `[[Title|display text]]`, `[[Title#heading]]`, `[[Title#heading|display]]`.

### Wiki-link resolution

- Wiki-link targets are matched against every note's `title:` frontmatter field. `title` is required, so there is always a value to match.
- Both sides are normalized before comparison: lowercase, whitespace runs collapsed to a single space, trimmed.
- Exact normalized match wins. No fuzzy or substring matching.
- **Ambiguity** (two or more notes with the same normalized title) is a `cairn validate` error. Resolve by renaming one of the notes. Path-based disambiguation is not supported because the folder layout is flat.

### Heading anchors

- The `#heading` suffix on either link form is preserved verbatim.
- v1 validates only that the target note exists. Heading text is not validated.

### Stable `id` field

- Every note has an `id:` frontmatter field, an 8-character hex string generated at creation and never changed.
- `id` is **not** used for wiki-link resolution (Obsidian does not support it), so wiki-link portability is preserved.
- `id` is reserved for future backlinks and rename-tolerant deep links.

### Rename

Version 1 `cairn rename <path> "New Title"` is scoped narrowly so it works in a less-than-clean tree:

1. Update `title:` and `updated:` in the target note.
2. Recompute the slug and `git mv` the file to the new filename. **Collision uses the same `-2`, `-3` suffix rule as note creation**, and rename never overwrites an existing file. If the recomputed slug equals the current filename, skip the `git mv` and update frontmatter only.
3. Commit once (only the target note is in this commit). Any failure rolls back and skips the commit.

Rollback is concrete, because "rolls back" is otherwise an intention rather than a behaviour. The command captures the original file path and original file bytes before step 1. On any failure it restores the original bytes at the original path, removes the new path if a `git mv` had already happened, and runs `git reset` on the paths it staged. It never runs `git checkout` or `git reset --hard`, because those can destroy unrelated user edits elsewhere in the tree.

Rewriting every inbound `[[Old Title]]` reference across the vault is **deferred to a later phase**, because it can touch many files and would block on any uncommitted edit anywhere in the tree. When the link index is built and scoped, inbound-link rewriting ships as a separate, optional step (and a separate commit). Until then, renamed notes leave stale inbound links, which `cairn validate` reports as broken links to triage.

### Link index

The CLI maintains a link index at `~/.cache/cairn/links.json`, keyed per file by `(sha256, mtime, size)` and rebuilt lazily when any of the three changes. Adding the content hash avoids a stale-cache race on filesystems with coarse mtime resolution. It backs `cairn rename`, `cairn validate`, and future backlink features. It is not committed.

### MOCs

MOCs are optional on individual notes. Tags are required.

MOCs may link to:

- notes
- other MOCs
- project notes
- reference notes

Do not force a complete MOC taxonomy on day one. Create MOCs incrementally as notes accumulate.

## Tags

Tags are required on every note and tracked in a generated tag index.

Tags are **normalized at write time** following the slug rule (lowercase; every run of non-alphanumeric characters collapsed to a single hyphen) with one deliberate difference: the slash `/` is preserved so tag hierarchies work (`cfg/security`, `project/cairn`). So `cairn new --tag "Trade Finance"` writes `trade-finance`, `--tag "CFG/Security"` writes `cfg/security`, and `--tag "A & B"` writes `a-b`. The slash is the only non-alphanumeric a tag may contain. Filenames cannot contain a slash, which is why the slug rule (no slash) and the tag rule (slash preserved) differ on purpose. This makes search normalization a consistency check rather than a correction, and keeps tag rename/match behavior well-defined.

New tags do not require confirmation during capture. That keeps capture fast. The CLI must provide cleanup commands so mistaken tags can be fixed later.

Required Phase 4 tag operations:

- list tags
- show notes for a tag
- rename a tag across all notes
- remove a tag from selected notes
- regenerate the tag index

The exact Phase 4 command surface, `indexes/tags.md` format, tag normalization, mutation semantics, and multi-file write safety rules are not decided yet. `T004-implementation` is blocked until the `Q004-*` decisions in `TODO.md` are resolved and this section is updated with the accepted rules.

## Todos

Use Markdown checkboxes:

```markdown
- [ ] Follow up with Jane
- [x] Review architecture note
```

The dashboard initially focuses on open todos. Dashboard todo scanning semantics are defined in "Dashboard" below.

## Capture workflow

Support two capture paths.

### Structured note creation

Use this when Ken knows the title/type/tags up front:

```text
cairn new "Trade Finance Notes" --type note --tag trade-finance
```

This creates a valid note directly under `notes/`.

Defaults when a flag is omitted. `type` and `tags` are required frontmatter fields, so `cairn new` must either default them or fail; it defaults, and does not prompt:

| Flag omitted | Behaviour |
| --- | --- |
| `--type` | defaults to `note` |
| `--tag` | defaults to a single tag `untagged` |
| `--project` | left empty |

`untagged` rather than failing keeps `cairn new "Title"` a one-liner, which is the whole point of the command, and `cairn search --tag untagged` then becomes the cleanup queue. A missing title is still a hard failure: there is nothing sensible to invent.

### Messy capture

Use this for copied OneNote content, meeting fragments, copied web text, or rough thoughts:

```text
cairn capture "Raw copied content..."
cairn capture --file path/to/paste.txt
pbpaste | cairn capture --title "Meeting fragment"
```

Capture writes to `notes/` (the same folder as durable notes; there is no separate `inbox/` folder) and must never prompt.

Frontmatter written by `cairn capture`:

| Field | Value |
| --- | --- |
| `title` | `--title` if given; else the first non-empty line of the input, truncated to 80 characters; else `note-<8 hex chars>` |
| `type` | `note` |
| `status` | `active` |
| `tags` | `[inbox]` plus any `--tag` values, deduplicated, normalized |
| `created` | today, ISO date |
| `updated` | same as `created` |
| `cairn_version` | `1` |
| `project`, `moc`, `source`, `source_url` | empty unless a corresponding flag is provided |

The `inbox` tag is the "not yet triaged" marker. To triage a captured note, edit it, remove the `inbox` tag, and fill in real fields. There is no separate `promote` command; triaging is just editing.

Input sources: positional string, `--file <path>`, or stdin. Multi-line paste from the clipboard is expected to work via `pbpaste | cairn capture`.

### Filename rules

Both `cairn new` and `cairn capture` derive the filename from the title using the same slug rule:

- lowercase
- transliterate via `unicodedata.normalize("NFKD", s)` then drop combining marks (characters whose `unicodedata.category()` is `Mn`); this turns e-acute into e and ñ into n. Characters that do not decompose and have no combining form (ß, CJK, emoji) are KEPT as-is rather than dropped, so the slug keeps its meaning and stays unique (dropping them would lose information and risk collisions)
- replace every run of non-alphanumeric characters with a single hyphen
- trim leading and trailing hyphens
- cap at 60 characters
- if the result is empty, fall back to `note-<8 hex chars>` derived from a random UUID

Files always live directly under `notes/`. On collision, append `-2`, `-3`, ... until a free filename is found. The CLI never overwrites an existing note file. Transliteration (not silent dropping) reduces collisions between names that differ only by accents.

## OneNote handling

OneNote import is out of scope for version 1.

Current understanding:

- the notebook is in a corporate SharePoint/work account
- OneNote for Mac does not provide full notebook export
- `.onepkg` export is not available from the Mac client
- Microsoft Graph is possible but too heavy for version 1

Version 1 path:

1. Copy/paste important OneNote content manually.
2. Format it into Markdown. Do this by hand, or with Copilot **only if the content is non-sensitive and your use of Copilot is sanctioned**. Cairn cannot enforce what you paste into a cloud assistant; treat that paste as sending the content outside the bank.
3. Use the CLI to add or validate frontmatter, tags, and optional MOC links.

## Outlook handling

Outlook is not central to version 1.

Do not build direct email import, meeting import, or deep-link integration first.

For version 1, store a plain source reference:

```yaml
source: "Outlook email: Quarterly planning from Jane Doe, 2026-07-21"
source_url:
```

The goal is to help Ken search Outlook manually later, not to make the vault an Outlook archive.

## Assets

Assets are expected to be small and rare. The default keeps the git repo lean and predictable.

### Default behavior

- Copy source files into `assets/` inside the vault.
- Commit them to git along with the note that references them.
- Enforce a per-file size limit (default: **1 MB**), checked both at `cairn asset add` time and by the pre-commit hook for any staged file under `assets/`.
- Record the original location, if any, in `source_url` using a portable token (see "Path portability" below).

### Large file handling

Large binaries (over the size limit) should be rare. Git LFS is explicitly **not** used. When a large file must be added, in order of preference:

1. **Reconsider whether the file belongs in the vault at all.** A link to the file's canonical company-managed location, ticket system, or other approved internal system is almost always better than committing the binary.
2. **Explicit override** (`cairn asset add --large path/to/file`). The CLI warns about repo size impact, records the file size in the commit message, and commits the file to git normally. Acceptable for the occasional important binary. No LFS involvement.
3. **Local-only under `assets/local/` (gitignored) with a tracked manifest.** The file lives in the working tree but is not committed. A manifest entry (relative path, size, SHA-256, added-on date, referencing note) is committed so that a missing file is detectable. The pre-commit hook verifies each manifest entry's SHA-256 against the on-disk file, so a file replaced outside Cairn fails the commit. The file is **not backed up** by the corporate GitHub push; that tradeoff must be acknowledged interactively at add time.

The CLI must never silently drop or exclude a file. Both option 2 and option 3 require interactive confirmation.

### The `assets/local` manifest (Phase 1 contract, not Phase 5)

**Read this even though assets are Phase 5.** Phase 1 ships the pre-commit hook, and that hook verifies this manifest. The format is therefore Phase 1 load-bearing: the hook cannot be written against a format that does not exist yet.

**Location: `assets/local.manifest.json`**, committed. Note it is a sibling of the gitignored `assets/local/` directory, not inside it, so no `.gitignore` negation is needed.

**Format: JSON, not YAML.** This is forced by the hook design above: the hook runs stdlib-only under a possibly-bare system interpreter, and `json` is stdlib while `yaml` is not. Written with sorted keys and a two-space indent so diffs stay readable and the file is byte-stable.

```json
{
  "manifest_version": 1,
  "entries": [
    {
      "path": "assets/local/2026-08-quarterly-deck.pdf",
      "size_bytes": 4718592,
      "sha256": "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
      "added": "2026-08-03",
      "referenced_by": "notes/quarterly-planning.md"
    }
  ]
}
```

- `path` is relative to the vault root and always begins `assets/local/`.
- `entries` is sorted by `path`, so two machines produce identical bytes.

**Verification rules, and they differ by caller on purpose:**

| Condition | pre-commit hook | `cairn validate` |
| --- | --- | --- |
| On-disk SHA-256 differs from the entry | **FAIL the commit** | error |
| File named by an entry is missing | warn, do not block | **warn, not error** |
| File in `assets/local/` with no entry | warn, do not block | warn |

Only a content mismatch is an error, and only it blocks. A mismatch means a tracked file was replaced outside Cairn, which is the exact integrity failure the manifest exists to catch.

**A missing file must NOT be an error, and the reason is structural rather than a matter of taste.** `assets/local/` is gitignored and never pushed, while the manifest IS committed. So every clone of the vault has a complete manifest and zero local files. Cairn is explicitly built on one Mac and deployed to another, and `cairn init` on a fresh clone is the documented first step, which means an errors-on-missing rule would put every non-origin machine into permanent validation failure on day one. A warning with a count carries the same information without that outcome.

There is no way to distinguish "missing because this is a clone" from "missing because it was deleted" without tracking machine identity per entry, which is more machinery than a single-user v1 should carry. The warning is the honest answer.

**Cost.** The hook hashes every entry on every commit. The design already states that large local assets are rare, so this is a small number. If it ever becomes slow, that is a signal the vault holds too many local binaries, and the remedy is fewer binaries, not a weaker check.

### Path portability (forward-looking, likely v2)

- Do not store raw absolute paths in `source_url`. Absolute paths embed the current username and environment-specific path details; both are brittle across machine changes and tenant renames.
- Use tokens resolved at read time from `~/.config/cairn/config.toml`, for example:

  ```yaml
  source_url: "$ONEDRIVE/Documents/cairn-sources/2026-07/deck.pdf"
  ```

- `cairn validate` flags raw absolute paths in `source_url` and asks the user to tokenize them.

This is forward-looking and may slip to v2; it is not required for a single-machine v1.

## Search

Version 1 search should be local and deterministic.

Search dimensions:

- full text
- title
- tag
- type
- status
- project
- source

Implementation should prefer simple file scanning first. A persisted search index is not required until the vault grows enough to justify it.

Search semantics:

- `cairn search "query"` performs case-insensitive substring search across note body text, `title`, and `source`.
- `cairn search` may run with only structured filters and no text query when at least one filter is present.
- `cairn search` with neither a text query nor any filters fails clearly instead of listing the whole vault.
- Structured filters use exact normalized matches:
  - `--tag tag-name`
  - `--type note`
  - `--status active`
  - `--project project-name`
- Multiple filters are combined with `AND`.
- Multiple `--tag` values require all listed tags to be present.
- Tag, type, status, and project comparisons should normalize surrounding whitespace and case.
- Search results should show path, title, type, status, project, tags, and a short matching excerpt when available.
- **Malformed-file semantics (decided):** frontmatter filters never match a malformed file (it is excluded by any `--tag`/`--type`/`--status`/`--project` filter). A text query can still match a malformed file's body, and when it does the result carries a warning marker. The text query and the frontmatter filters combine with AND at the result level: a malformed file can appear only via a text match, never via a filter, and always flagged.

## Dashboard

Start with todos.

Initial dashboard sections:

1. Open todos grouped by note.
2. Recently created notes.
3. Active projects, if project notes exist.

Dashboard generation semantics:

- `cairn dashboard` writes `dashboard.md` and auto-commits it as a generated output.
- If the generated content is byte-identical to the existing `dashboard.md`, the CLI skips the write and the commit (no empty commits).
- Dashboard source files are limited to `notes/*.md` and `moc/*.md`; generated files such as `dashboard.md` and `indexes/*.md` are not scanned.
- Open todos are unchecked Markdown task-list items using `- [ ]` or `* [ ]`, with optional leading whitespace.
- Open todos are grouped by note and sorted deterministically by note path and task order within the note.
- Recently created notes shows the 10 newest notes by `created` date descending, then relative path ascending.
- Active projects are notes with `type: project` and `status: active`, sorted deterministically by relative path.

Later dashboard sections:

- tags
- MOCs
- waiting items
- notes missing optional metadata

One of these is not optional if `cairn new` defaults `--tag` to `untagged`: the dashboard must show a **count of `untagged` notes**. Without it the default is a silent leak, because an `untagged` note passes validation and nothing ever surfaces the backlog unless Ken remembers to search for it. The count is the forcing function that makes the convenient default safe.

## Git behavior

After successful write commands, automatically create a local git commit.

The vault is a normal git repository at the vault root. Backup is via manual `git push` to a private repository on the corporate GitHub organization `CFG-INNERSOURCE` at `github.com`. No personal, external, or third-party remotes are permitted.

### Remote allowlist

`cairn init` and `cairn doctor` verify configured remote URLs against the version 1 allowlist. The hard enforcement is the pre-push hook (see "Security enforcement via git hooks"); the init/doctor check is a preview that fails fast before a push is attempted.

```toml
[remote]
allowed_prefixes = [
  "https://github.com/CFG-INNERSOURCE/",
  "git@github.com:CFG-INNERSOURCE/",
]
```

Any remote URL not matching an allowed prefix is rejected by the pre-push hook. Use `cairn remote add <url>` (accepts only allowed URLs) so the user never touches `git remote` directly. If Citizens later provides a better-scoped organization or host, update this allowlist, the hook, and the implementation together.

**Config source:** the allowlist lives at `~/.config/cairn/config.toml` under `[remote] allowed_prefixes`, per-user (not per-vault). When the file or key is absent, it defaults to the two CFG-INNERSOURCE prefixes above. `cairn init` reads it and bakes the resolved list into the rendered pre-push hook; tests override it through that same config path. **Editing the allowlist requires re-baking the hook:** the baked list is a snapshot, so after editing config the user runs `cairn init` (or `cairn doctor --fix`) to re-render the pre-push hook. `cairn doctor` compares the installed hook against a fresh render from current config and FAILS LOUDLY when they diverge, so a stale baked list cannot silently persist. The fail direction to watch: tightening config without re-baking leaves the hook enforcing the old, looser list - doctor's drift check catches it before the next push, which is why the check is a hard fail, not a warning.

### Visibility tradeoff (documented decision)

`CFG-INNERSOURCE` is an innersource organization. Even for a repository marked Private, org admins and org-wide tooling may have visibility into repository contents for governance purposes, and org-level discovery mechanisms exist. The vault contains personal working notes; this location was chosen for v1 because no more-scoped alternative is currently available. If Citizens later provides a personal or sandbox org, migrate the repo there and update `allowed_prefixes` accordingly.

Corollary: the "no PII/MNPI/secrets" policy in "Data-handling constraints" is not optional. Assume every commit is readable by other Citizens engineers.

Write commands include:

- creating notes
- capturing inbox items
- editing frontmatter
- copying assets
- renaming tags
- regenerating indexes
- regenerating dashboard

Read-only commands such as search must not commit.

If there are uncommitted changes before a write command, the CLI must not silently mix unrelated user edits into an auto-commit. It should either:

1. commit only files it changed, or
2. stop with a clear message.

The version 1 default is:

1. Before writing, determine the command-owned target paths.
2. If any command-owned target path already has uncommitted changes, stop with a clear message.
3. After a successful write, stage and commit only the command-owned paths that the command intentionally changed.
4. Ignore unrelated dirty files outside the command-owned path set.

This keeps auto-commit useful without silently bundling unrelated user edits or overwriting in-progress work.

**When the commit itself fails** for a reason other than the content scan (missing git identity, index lock held by another process, a hook error, a full disk), the rule is: **the write to disk stands, the commit does not, and the CLI says so explicitly.** It exits non-zero, names the file it wrote, prints git's own error, and states that the change is on disk but uncommitted. It does not retry, does not `git reset`, and does not delete the file it just wrote. Losing a note to tidy up after a failed commit would be a far worse outcome than an uncommitted note, and the next successful write command commits it.

## Pre-commit content scan

Before each auto-commit, the CLI runs a local content scan on the files it is about to commit. The same scan also runs from the `.git/hooks/pre-commit` hook on every commit, so raw `git commit` and Copilot-assisted commits are scanned too. This is defense in depth; corporate GitHub Enterprise also scans server-side, but blocking locally avoids tripping security events.

**v1 scope (decided 2026-08-03, "go lighter"):** v1 ships only the two credential rules that are both high-value for this vault and zero-false-positive: **private keys and AWS key ids**, plus binary-skip and block-on-fail. The payment-card and SSN rules are DROPPED for this vault (Ken never has access to card or SSN data and would never put it in a note, so they were pure false-positive friction; their patterns stay documented below as optional for users who do handle that data). The labelled-high-entropy-token rule, its entropy gate, the `cairn:allow-secret` suppression marker, and the bounded history scan are DEFERRED to v2. Net effect: v1 has no false-positive-prone rule, so it needs no suppression marker and cannot block a legitimate commit. Corporate GitHub Enterprise scans server-side and backstops the deferred and dropped classes until v2.

### Scan input

The scan reads the **full staged content** of each staged file (`git show :<path>`), not the diff hunks. Scanning hunks would miss a secret that sits in unchanged context in a file being committed for the first time. Files whose staged content contains a null byte in the first 8192 bytes are treated as binary and skipped. Everything under `.git/` is out of scope by construction.

### Scan rules

v1 ships the **private key** and **AWS access key id** rules only (the first two rows of the table): an implementation ships these and no fewer, and the test suite pins each with a positive and a negative case. The **payment-card**, **SSN**, and **labelled-high-entropy-token** rows are NOT v1: card and SSN are dropped for this vault (see the v1 scope note), and the entropy-token rule and its gate are v2 (specified here so v2 is add-not-design).

| Rule | Pattern | Notes |
| --- | --- | --- |
| Private key block | `-----BEGIN (?:RSA \|EC \|DSA \|OPENSSH \|PGP )?PRIVATE KEY-----` | Highest confidence, effectively zero false positives |
| AWS access key id | `\b(?:AKIA\|ASIA\|AGPA\|AIDA\|AROA\|AIPA\|ANPA\|ANVA\|ABIA)[0-9A-Z]{16}\b` | The documented AWS key-id prefixes |
| Labelled high-entropy token | `(?i)\b(?:secret\|token\|api[_-]?key\|apikey\|password\|passwd\|access[_-]?key)\b\s*[:=]\s*["']?([A-Za-z0-9+/=_\-]{32,})` | Capture group 1 must ALSO clear the entropy gate below |
| Payment card | 13-19 digit run after stripping spaces and hyphens, passing the Luhn checksum | See false-positive rule below |
| US SSN | `\b\d{3}-\d{2}-\d{4}\b` | Hyphenated form only; bare 9-digit runs are too noisy |

**Entropy gate.** The labelled-token rule alone would fire on a long repeated placeholder such as `token: abcabcabcabcabcabcabcabcabcabcabcab`. The captured value must also have Shannon entropy, computed in bits per character over the captured string, of at least **3.0**. That threshold admits realistic base64 and hex secrets while rejecting literal repeats and near-dictionary filler.

The constant lives in `scan.py` under a named symbol and the test suite pins it from both sides. Changing it is legitimate, but it requires updating the fixtures in the same commit, which is what keeps it honest rather than a knob to nudge when the scan is annoying.

Know what this gate does and does not buy. At 3.0 bits per character roughly ten distinct symbols already clear it, so the gate's real job is narrow: reject placeholders that the `{32,}` length rule alone would let through. Real secrets are high-entropy and clear it easily, so false negatives are largely theoretical. The live risk is the opposite: benign base64 clears it too (`token: dGhpcyBpcyBhIHRlc3Qgb2YgY2Fpcm4=` is harmless text and will fire). That is precisely what the suppression pragma below exists for.

**Payment-card false positives are the known weak spot.** A Luhn-valid 16-digit run appears in ordinary text more often than intuition suggests, and this vault will contain technical notes full of identifiers. Two mitigations: a candidate is ignored when the surrounding 40 characters match `(?i)(commit|sha|hash|uuid|guid|ticket|jira|version|build)`, and the finding message names the rule so a false positive is obviously a false positive rather than a mystery.

**Suppression.** A line whose trailing content, after stripping whitespace, ends with the exact marker `cairn:allow-secret` is skipped by every rule. It is a line-suffix marker, not a substring match anywhere on the line: a plain substring rule would mean a sentence such as "see the cairn:allow-secret docs below" silently suppresses its own line, and any prose about the feature disables the scan wherever it appears. The marker suppresses only the line it terminates; it is not a block or file directive.

This escape hatch exists because a scanner with no way out gets disabled wholesale the first time it blocks something legitimate, which is a far worse outcome than a reviewable exception. Suppressions are visible in the diff, and `cairn validate` reports a count of them in the vault so they cannot accumulate silently.

**Failure behaviour.** Failure exits non-zero and prints, for each finding, the rule name, the file path, the line number, and a masked excerpt. Masking happens INSIDE `scan_bytes`, so `Finding.excerpt` is safe for every consumer (hook output, `cairn validate`, tests), never holding the full match. The rule: for a match of 8 characters or fewer, emit only its first and last character with the middle replaced by a placeholder; for a longer match, emit first-4 + placeholder + last-4. The full secret is never printed, even for short values, because hook output can land in terminal scrollback, a CI log, or a screenshot. The write to disk still happened; the commit did not. The user resolves by editing and rerunning.

Scope and limits:

- The scan covers secret patterns and structured identifiers only. It does **not** detect unstructured PII (names, addresses), free-text MNPI, or employer-specific reference formats. Those are governed by policy and by Ken; server-side corporate scanning is the backstop.
- Scan implementation should be a small set of regexes shipped with the CLI and embedded in the hook. No third-party service, no network calls.

```text
cairn init
cairn doctor [--fix]
cairn new "Title" --type note --tag tag-name [--project project-name]
cairn capture [--title title] [--tag tag-name] [--file path]
cairn rename path/to/note.md "New Title"
cairn search "query"
cairn dashboard
cairn tags
cairn tag rename old-tag new-tag          # Phase 4 (provisional, design pending)
cairn tag remove tag-name path/to/note.md  # Phase 4 (provisional, design pending)
cairn validate
cairn reindex
cairn remote add <url>
```

`cairn reindex` regenerates all generated outputs: `dashboard.md`, everything under `indexes/`, and the link cache.

## Validation rules

Full `cairn validate` eventually reports:

- missing frontmatter
- missing required fields
- invalid `type`
- invalid `status`
- missing tags
- malformed dates
- missing linked asset files
- broken wiki-link (no matching title)
- ambiguous wiki-link (multiple matching titles)
- broken relative Markdown link (target `.md` or asset does not exist)
- duplicate note filenames
- generated files that are stale

Validation scope:

- `notes/` is strict by default. Files must have parseable frontmatter, all required fields, valid `type`, valid `status`, at least one tag, valid `created`/`updated` dates, and valid asset links.
- Notes tagged `inbox` are treated as **relaxed**: frontmatter must parse and all required fields must exist with non-empty values, but `type`/`status` vocabulary checks and asset-link checks are skipped. This lets rough captures live alongside durable notes without failing validation.
- `moc/` is strict.
- `indexes/` and `dashboard.md` are generated outputs. Validation should report when they are stale relative to the source notes.
- `assets/` validation is reference-based: report missing linked asset files from notes, but do not require every asset file to be linked on day one.

Phase 2 `cairn validate` is intentionally schema-only. It validates missing frontmatter, missing schema fields, required non-empty fields, invalid `type`/`status`, missing tags, malformed dates, inbox relaxed validation, and duplicate filenames. Wiki-link validation, Markdown-link validation, asset-link validation, and generated-file staleness checks are deferred to the phases that implement that infrastructure.

Validation exit code: validation errors exit non-zero; warnings-only exits zero; output always includes a summary.

All schema fields must exist. Only `id`, `title`, `type`, `status`, `tags`, `created`, `updated`, and `cairn_version` must be non-empty. Optional fields `project`, `moc`, `source`, and `source_url` may be empty.

`cairn capture` accepts exactly one content source: positional text, `--file`, or piped stdin. If more than one source is provided, it fails clearly.

`cairn init` does not invent a git identity. If `git config user.email` is missing, `cairn init` may create folders and hooks but refuses auto-commit with a clear message; `cairn doctor` remains the gate for write commands.

## Testing

Cairn is built by coding agents behind a review gate, so the test suite is the contract that gate checks. A phase is not done because the code exists; it is done when the tests below pass and a reviewer can see WHICH behaviour each one pins.

### Framework and layout

`pytest`, no other test dependency. Declared under `[project.optional-dependencies] dev`.

```text
tests/
  conftest.py           # fixtures
  unit/                 # pure functions, no filesystem, no git
  integration/          # real vault, real git repo, real hooks
  fixtures/
    secrets/            # synthetic scanner inputs (see below)
```

### Hermeticity (non-negotiable)

Every test that touches git or the filesystem runs against `tmp_path`. No test may read or write the real vault, the real `$HOME`, or the user's git config. `conftest.py` sets, for the whole session: `HOME` to a temp dir, `GIT_CONFIG_GLOBAL` and `GIT_CONFIG_SYSTEM` to temp files, and `GIT_AUTHOR_*`/`GIT_COMMITTER_*` to fixed values so commits are reproducible. A test that passes only because of the developer's ambient git config is a false green, and this project cannot afford one in the safety layer.

### The `tmp_vault` fixture

The core fixture: creates a directory under `tmp_path`, runs the real `cairn init` against it, and yields the path. Tests get a real git repo with really installed hooks. Nothing about the hook path is mocked.

### Testing the hooks (the part that is easy to fake and must not be)

**The hook tests must invoke `git` and let git run the hook.** A test that imports the scan function and asserts it returns findings proves nothing about the hook: it cannot catch a broken shebang, a bad interpreter resolution, a rendering bug, a non-executable file, or a hook that was never installed. Those are the failure modes that matter, and they are exactly the ones a cooperative in-process test hides.

Required integration tests:

1. Stage a file containing a synthetic secret, run `git commit`, assert non-zero exit and the rule name in stderr, and assert `git log` gained no commit.
2. Stage a clean file, run `git commit`, assert exit zero and one new commit. **This is the positive control**: without it, a hook that rejects everything looks identical to a hook that works.
3. Add a remote outside the allowlist, run `git push` against a local bare repo, assert rejection. Add an allowlisted remote, assert the push proceeds.
4. Corrupt an installed hook by appending a byte; assert `cairn doctor` fails and names it; assert `cairn doctor --fix` restores it and doctor then passes.
5. Delete `.git/hooks/pre-commit`; assert doctor fails and `--fix` reinstalls.
6. Render both hooks and assert the inlined scan source is byte-identical to `src/cairn/scan.py`.
7. Import `src/cairn/scan.py` with the rest of the package removed from `sys.path` and assert it imports and runs. This enforces the stdlib-only constraint the whole hook design rests on.
8. Run a commit with `--no-verify` containing a secret, assert it succeeds (documenting the known hole), then assert `cairn doctor --scan-history` reports it.

### Testing the scanner

Fixtures live in `tests/fixtures/secrets/` and are **synthetic values that match the patterns without being live credentials**: an `AKIA` prefix followed by sixteen arbitrary uppercase characters, the industry test card number `4111111111111111`, an SSN-shaped `000-00-0000`, a generated PEM header with non-key body text. Never commit a real credential to test a secret scanner.

Both directions are required for every rule, per the positive/negative discipline this project already uses elsewhere:

- **Positive:** the rule fires on its fixture.
- **Negative:** the rule does NOT fire on a near-miss (`AKIA` followed by fifteen characters; a 16-digit run that fails Luhn).
- **Entropy threshold pinned from both sides**, so a future tweak to the constant breaks a test rather than silently weakening the scan. The below-gate fixture must be **long enough to reach the gate**: use `token: abcabcabcabcabcabcabcabcabcabcabcab` (35 characters, three distinct symbols, entropy 1.58). A shorter string is rejected by the `{32,}` length rule before the entropy code ever executes, so it would pass the test while proving nothing about the gate. That trap is not hypothetical: the first draft of this section used a 29-character fixture whose entropy was also 3.11, so it failed the length rule AND would have cleared the gate, and the test would have been green and meaningless in both directions.
- **Suppression:** `cairn:allow-secret` on the line suppresses; on the adjacent line it does not.
- **Masking:** assert the finding output does not contain the full matched string.

### Testing determinism

- `cairn dashboard` run twice on an unchanged vault produces byte-identical output and creates exactly one commit, not two. This pins the no-empty-commit rule.
- Slug generation, tag normalization, and wiki-link resolution are unit-tested directly against the rules stated in this document, including the ambiguity error and the accent transliteration case.

### Testing the offline install path

The design states the offline path is co-primary because many bank Macs block PyPI. Co-primary means tested, not documented: a test builds the zipapp and runs `cairn --version` from it with no network and no pipx. A documented fallback that has never been executed is not a fallback.

The Homebrew path makes the same co-primary claim and carries the same obligation. A full brew test needs a published tap, so it is a manual pre-release integration gate rather than a unit test in this suite: build the formula locally (`brew install --formula ./cairn.rb` from a scratch tap), run `cairn --version`, and confirm `cairn doctor` passes with the executable at `$(brew --prefix)/bin`. Until the tap exists this is a documented manual gate, not an automated test.

### No skipped tests

No test in this suite may be skipped by default. A default-skipped test is zero coverage wearing the costume of coverage. If a test cannot run in an environment, it fails there rather than skipping, or it does not exist.

### Per-phase definition of done

A phase is complete when: its commands work end to end against a real vault; every rule it introduced has a test that pins it from both directions; the full suite passes from a clean checkout with no network; and an adversarial review has run against the diff.

## Implementation phases

### Phase 1: Skeleton, safety infrastructure, and note creation

- Python package skeleton (`src/cairn/`, entry point `cairn = cairn.cli:main`)
- `cairn init`: folder creation, `git init`, `.gitignore`, hook installation (pre-commit + pre-push), remote allowlist check, identity check
- `cairn doctor`: all checks including hook presence/content verification; `--fix` reinstalls hooks
- pre-commit content scan (the scan logic, callable both from the CLI and from the installed hook)
- frontmatter writing
- `cairn new`
- **only after** the scan and hooks are in place: local git auto-commit for successful writes

The scan and hooks must exist before the first auto-commit, so Phase 1 lands them first.

### Phase 2: Capture and validation

- `cairn capture`
- `cairn validate` (schema-only scope, per "Validation rules")
- inbox support
- schema checks
- `cairn remote add` (allowlist-checked; pairs with the pre-push hook already shipped in Phase 1)

### Phase 3: Search and dashboard

- text search
- frontmatter search
- todo scanning
- dashboard generation
- the link index at `~/.cache/cairn/links.json`
- `cairn rename` (depends on the link index for the broken-link report)
- `cairn reindex` (regenerates dashboard, indexes, and the link cache; needs the generators from this phase to exist)

### Phase 4: Tags and indexes

- tag index generation
- tag listing
- tag rename
- tag removal

### Phase 5: Assets

- copy files into `assets/`
- add asset links to notes
- store optional `source_url`

## Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| Capture becomes too slow | Allow inbox capture with minimal required prompts |
| Metadata drifts | CLI validation and generated indexes |
| Tags become messy | Tag rename/remove commands; write-time normalization |
| Auto-commit captures unrelated edits | Commit only files changed by the command |
| Sensitive data leaks into git history | Pre-commit hook content scan (every commit, not just CLI); no PII/MNPI by policy; corporate GitHub server-side scanning as backstop |
| Controls bypassed by raw git or Copilot | Hard enforcement at the git-hook layer, installed by `cairn init`, verified by `cairn doctor` |
| Hooks vanish after clone or deletion | `cairn init` idempotent reinstall; `cairn doctor` verifies hook content by hash; documented first step on any clone |
| Large binaries bloat corporate repo | Per-file size cap enforced at add and in the pre-commit hook; no LFS; explicit `--large` override or gitignored-with-manifest for the rare case |
| Brittle absolute paths in `source_url` | Store `$ONEDRIVE`-style tokens resolved from config, not raw absolute paths (forward-looking) |
| Outlook integration wastes time | Store plain references only in version 1 |
| Obsidian compatibility overcomplicates design | Use portable Markdown first |
| Stale link cache on coarse-mtime filesystems | Cache key includes content SHA-256, not just mtime and size |
| PII/MNPI not detectable by regex | State the scan's limits explicitly; policy + human + server-side backstop |

## Adversarial review workflow

Each new implementation phase requires an adversarial review gate before implementation. Use the current workflow in `working-agreement.md`: review `DESIGN.md`, `decisions.md`, `TODO.md`, current implementation, and relevant tests; convert only current blockers or required Ken decisions into `TODO.md`; keep long review transcripts out of working documents. This design itself passed a cross-family adversarial review on 2026-07-24 (verdict DESIGN-FIX-FIRST, fixes applied); see `REVIEW.md`.
