# Cairn build decisions

Locked mechanisms for the Phases 2-5 build. Each resolves a point DESIGN.md
leaves unspecified, so a builder implements the decision rather than inventing
one. Authored 2026-08-09; flag to Ken to revisit. Line cites are DESIGN.md.

These survive the build: after Phases 2-5 land, DESIGN.md is updated in one pass
to absorb the accepted answers, and this file becomes the rationale record.

## Commit-message format (all write commands)

Existing Phase-1 code already uses `cairn new: <title>` (commands/new.py). The
convention is therefore `cairn <command>: <subject>` (lowercase command, colon),
not `cairn: <verb> <subject>`. Examples:
- `cairn capture: notes/inbox-abc.md`
- `cairn regenerate: dashboard`
- `cairn tag rename: old -> new (7 notes)`
- `cairn asset add: assets/deck.pdf` (+ ` (N MB, --large)` when --large)

DESIGN only pins that `--large` records the file size; the rest is this decision.

## tags.normalize_tag (the DESIGN:441 rule, made precise)

DESIGN:441 says: lowercase; every run of non-alphanumeric characters collapsed
to a single hyphen; the slash `/` preserved (so hierarchical tags like
`cfg/security` work). Today's Phase-1 `normalize_tag` only lowercases and
collapses whitespace, which contradicts the spec. This is the corrected rule:

1. `unicodedata.normalize("NFKD", s)` then drop combining marks (accents
   transliterate: `cafe` not `cafe + combining acute`). Same unicode handling as
   `slugs.slugify` (DESIGN:524-528), so a tag and its slug agree on accents.
2. lowercase.
3. Split on `/`. For each segment: replace every run of non-alphanumeric
   characters with a single hyphen, strip leading/trailing hyphens.
4. Rejoin segments with `/`. Empty result -> the original is returned unchanged
   (do not produce an empty tag).

Pinned cases (the gating test):
- `Trade Finance` -> `trade-finance`
- `CFG/Security` -> `cfg/security` (slash preserved)
- `A & B` -> `a-b`
- `foo   bar` -> `foo-bar`
- `foo--bar` -> `foo-bar` (runs collapse)
- ` leading ` -> `leading`
- `café` -> `cafe` (NFKD)
- `a / b` -> `a/b` (spaces around a slash do not survive)
- `a/b/c` -> `a/b/c`
- `UPPER` -> `upper`
- `already-clean` -> `already-clean`

Behaviour change to shipped Phase-1 code: notes whose tags were written by the
old weak normalizer re-normalize to this form on the next write (e.g. a Phase-4
tag mutation). One-time migration cost, not a bug.

## read_frontmatter (frontmatter.py)

`read_frontmatter(path: Path) -> tuple[dict, str]`. Splits a note into
(frontmatter_dict, body_str). Rules:
- A note is `---\n<yaml>\n---\n<rest>`. The leading `---` must be the first
  bytes (allow a leading BOM? no: BOM is a malformation, surface it).
- frontmatter parsed with `yaml.safe_load`. `None` (empty block) -> `{}`.
- body is everything after the closing `---\n`, with no leading newline retained
  beyond what the file has. (Mirror `write_frontmatter`, which emits
  `---\n{dumped}---\n`, so read+write round-trips byte-identically for the
  cairn schema.)
- No frontmatter block (file does not start with `---`) -> raise
  `ValueError` with the path. (Callers like `validate` catch and report
  "missing frontmatter".) Do NOT return a silent empty dict; that hides
  malformed notes.

Round-trip test: `write_frontmatter(d)` then `read_frontmatter` recovers `d`
and the body, for the cairn field set.

## iter_notes / iter_notes_and_moc (vault.py)

- `iter_notes(vault: Path) -> list[Path]`: all `*.md` directly under `notes/`,
  sorted by relative path (POSIX). Not recursive (DESIGN:304 says notes live
  directly under notes/; no deep topic folders).
- `iter_notes_and_moc(vault: Path) -> list[Path]`: union of `notes/*.md` and
  `moc/*.md`, sorted by relative path. (Dashboard and search scan both per
  DESIGN:686 and Decision below.)
- Return absolute paths. Sorted = deterministic output for dashboard/search.
- Exclude generated files? In notes/ and moc/ there are none generated; the
  generated files (dashboard.md, indexes/*) live elsewhere. So no exclusion
  needed here.

## links.json record schema (Phase 3)

Keyed by file path (relative to vault). Each record:
`{title, title_norm, outbound_wikilinks:[raw], outbound_mdlinks:[raw], headings:[]}`,
plus a validity tuple `(sha256, mtime, size)` stored alongside for the lazy
rebuild. **Inbound links are derived** (reverse map over all files' outbound
targets) at query time, not stored; needed for `cairn rename`'s broken-link
report. Scope: `notes/` + `moc/`. (Tag rename in Phase 4 does not touch
inter-note links and never needs inbound.)

## Search sort + scope (Phase 3)

Results sorted by relative path ascending (deterministic; no relevance
scoring). Scope: `notes/` + `moc/`. Excerpt: first 80 chars around the first
body match.

## Dashboard layout (Phase 3)

H1 `# Dashboard`. H2 sections in order: `Open todos`, `Recently created`,
`Active projects`, `Untagged`.
- Open todos: grouped by note, sorted by note path then task order in the note
  (DESIGN:688). Unchecked `- [ ]` / `* [ ]`.
- Recently created: 10 newest by `created` desc then path asc (DESIGN:689).
- Active projects: `type: project` AND `status: active`, sorted by path
  (DESIGN:690).
- Untagged: count + note paths (DESIGN:699 mandatory).
Generated, committed, byte-identical no-op skip (one commit, not two; DESIGN:685,
test at 909). NOT hash-pinned by `cairn doctor`.

## Inline #tag handling

v1 ignores inline `#tag` everywhere (reads and Phase-4 mutations). Tags are the
frontmatter `tags:` list only. Single source of truth.

## Phase 4 (Q004-1..4)

- Q004-1 surface: `cairn tags` (list + counts, frequency-desc then alpha;
  read-only); `cairn tag rename <old> <new>`; `cairn tag remove <tag>`. No
  merge/delete in v1.
- Q004-2 `indexes/tags.md`: generated, committed, content-pinned. One `## tag`
  section per tag, alpha-sorted, bulleted backlinks to carrying notes. Built by
  `cairn reindex`.
- Q004-3 mutation: rewrite `tags:` frontmatter only (not inline `#old`).
  Collision (new name exists) -> refuse, exit non-zero. Zero matches -> exit
  non-zero "no such tag". One auto-commit: `cairn tag rename: old -> new (N notes)`.
- Q004-4 multi-file write safety (the seam): per-file atomic write (temp +
  `os.replace`, same dir). Cross-file best-effort, not all-or-nothing: a failed
  write stops further writes and reports `rewrote K/N notes; <file> failed:
  <reason>`; the single auto-commit covers only successfully-rewritten files.
  Every write still passes the pre-commit scan + auto-commit.

## cairn asset add surface (Phase 5)

`cairn asset add <path> [--note <path>] [--large] [--source-url <...>]`.
Copy into `assets/`, sha256 it. >1 MB without `--large` -> refuse. With
`--large` -> warn + interactive confirm, record size in the message. `--note`
appends a relative markdown link `[name](assets/<name>)` to that note and sets
the manifest `referenced_by`. 1 MB cap fixed for v1 (not config-driven).
Manifest entries conform to the Phase-1 hook contract (DESIGN:585-625).

## cairn remote add (Phase 2)

`cairn remote add <url> [--name <name>]`. Default name `origin`. Refuse if the
name exists (no overwrite). Validate URL against `config.get_allowlist()` before
adding. Non-interactive. Pairs with the Phase-1 pre-push hook.

## cairn new flags (Phase 2)

Add `--moc`, `--source`, `--source_url` for symmetry with `capture`.

## --tag parser

Repeatable flag (`--tag a --tag b`), not comma-separated (commas clash with
slash-hierarchies). Normalized at write via `normalize_tag`.

## Date validation

`YYYY-MM-DD` only. Time-bearing values are malformed (error in the strict
scope; inbox-relaxed still requires the field present and non-empty but skips
vocab checks, not date format - so a malformed date in an inbox note is still
an error).

## "Duplicate note filenames"

Basename collision across `notes/` (literal), reported by `validate`.

## validate / search output

validate: `path: SEVERITY: message` per finding + summary `N errors, M
warnings`. search: one block per result (path, title, type/status, excerpt) +
summary.

## type: todo

No special semantics in v1 beyond being a valid type. Todos = checkbox scan
only.

## Subcommand-group pattern (for `cairn tag`, `cairn remote`)

argparse nested subparsers. Pattern, established once in the prereq:
- A command group `cairn <group>` gets its own subparser:
  `group_parser = subparsers.add_parser("tag"); group_sub = group_parser.add_subparsers(dest="tag_command")`.
- Each subcommand: `group_sub.add_parser("rename")...`.
- Dispatch: a `run_tag(args)` that switches on `args.tag_command`.
- `cairn remote add` follows the same shape (`remote` group, `add` subcommand).
- `dest` naming: `<group>_command` to avoid collisions.

## Hermeticity: XDG redirects (conftest)

Add session-wide (autouse) redirects alongside the existing HOME redirect:
- `XDG_CONFIG_HOME` -> a temp dir (Phase-2 `remote add` reads config.toml; tests
  inject allowlists without touching the real config).
- `XDG_CACHE_HOME` -> a temp dir (Phase-3 link cache at `~/.cache/cairn`).
Existing per-test XDG overrides still win. Keep `env=os.environ.copy()` on every
subprocess so hermeticity propagates.

## validate scope gate (Phase 2 DoD)

Phase-2 `validate` is schema-only (DESIGN:845). It must run clean with NO link
index present: no link-validation code paths ship in Phase 2. Wiki-link,
markdown-link, asset-link, and generated-file-staleness checks are deferred to
the phases that build that infrastructure.

## reindex is extensible

`cairn reindex` (Phase 3) regenerates {dashboard, link cache} via a pluggable
generator list. Phase 4 adds `indexes/tags.md` to that list. No circular
dependency.
