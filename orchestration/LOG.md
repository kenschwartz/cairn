## 2026-08-04T00:12Z phase1-rework -> dev
what:   Phase 1 REWORK resolved: 4 blockers fixed, v1 scan re-scoped to current design, config.toml allowlist source, masking/render/deletion fixes
why:    vault to-do 06303 (Panel step 4 verdict REWORK, 2026-08-03)
review: rev1 MERGE WITH FOLLOWS + rev2 REWORK rejected on misread; convergent history-scan RAISE stripped at triage
verify: 229 passed / 0 skipped / 0 failed, deps up, gate diff empty | sha a2726e1 | pushed origin/dev (pending)

## 2026-08-09T16:56Z zipapp-package-data-fix -> main
what:   init/doctor/render read scan.py + hook templates via importlib.resources instead of Path(__file__).read_text(); + regression test (zipapp init+doctor) in test_offline_install.py
why:    v1.0.0 release smoke: the offline zipapp crashed in install_hooks with NotADirectoryError because __file__ points inside the archive. The shipped test_offline_install only ran --version, so it never imported the hook-render path and missed it. Brew/pip installs were unaffected (real files on disk); only the zipapp path was broken.
review: found by release smoke (Track A), not a code-review pass; the regression test pins it both ways (old code crashes, new code passes). 230 passed (+1).
verify: rebuilt zipapp from fixed src + bundled pure-python PyYAML; ran init/new/doctor + a secret-block under a yaml-free venv python (no PyPI) - all green, hook still blocks aws_access_key_id

## 2026-08-09T17:15Z trackb-prereq -> main
what:   shared read infra - frontmatter.read_frontmatter, vault.iter_notes/iter_notes_and_moc, tags.normalize_tag fixed to DESIGN:441; + docs/decisions.md; + conftest XDG_CONFIG_HOME/XDG_CACHE_HOME session redirects
why:    Track B prerequisite; every read-side command (validate/search/dashboard/rename/tags) needs the reader + walker; normalize_tag under-implemented DESIGN:441 (latent false-green). Cross-family test-first: GLM-authored gate (b02bde3), Fable build (a0ae90a), GLM review fix (dba0080).
review: GLM reviewed the diff; confirmed normalize_tag matches slugs.slugify's ascii-ignore (Agent A's "keeps non-ASCII" summary was wrong - checked the real code, avoided a divergent "fix"). One review fix: read_frontmatter encoding=utf-8 to match the write path.
verify: 260 passed / 0 skipped / 0 failed (230 existing + 30 new gating), host-verified in the builder worktree

## 2026-08-09T17:26Z phase-2 -> main
what:   cairn capture (one-source rule + inbox tagging + title derivation), cairn validate (schema-only DESIGN:845, inbox-relaxed, real-date check, read-only), cairn remote add (nested subparser, allowlist-checked via config.get_allowlist, default origin, refuse-on-existing)
why:    Track B Phase 2. Cross-family test-first: GLM-authored gate (ca1dd1f, 27 tests), Fable build, GLM review.
review: GLM reviewed capture/validate/remote. Accepted the fcntl non-blocking stdin peek in capture - it is the only way to satisfy BOTH 'positional + inherited-empty-stdin works' and 'positional + piped-stdin fails' (DESIGN:851) without PTY plumbing in tests; correct in production (TTY skipped, pipe-with-data=source, empty pipe=not). Noted as the one fragile spot if Cairn ever targets non-Mac/Linux. validate deferred duplicate-basename (ambiguous in flat notes/). Minor nits (unused body binding, dead OPTIONAL_FIELDS) left.
verify: 287 passed / 0 skipped / 0 failed (260 + 27), host-verified in builder worktree

## 2026-08-09T17:39Z phase-3a -> main
what:   cairn.links (build_index, inbound_links + cache), cairn search (text+filters, normalizer, malformed rule, read-only), cairn dashboard (sections, byte-identical no-op skip, untagged count)
why:    Track B Phase 3a (read/generate side; rename+reindex follow in 3b). Cross-family: GLM gate (45c1721), Fable build (70d3e53), GLM review.
review: GLM caught THREE dashboard spec-divergences the builder introduced/followed: projects excluded from recently-created (DESIGN:689 says all notes), todo regex missing leading-whitespace (DESIGN:687), sort tiebreak direction (DESIGN:689 path-asc). Also found my OWN gate test had encoded the same wrong 'projects excluded' assumption - corrected it to check the section. The builder's honest disclosure of its interpretation is what clued the review in. No repo pollution this round (builder heeded the tmp-dir warning).
verify: 308 passed / 0 skipped / 0 failed (287 + 21), host-verified in worktree

## 2026-08-09T17:47Z phase-3b -> main
what:   cairn rename (title+updated, slug recompute, git mv + -2/-3 collision, dirty-tree precheck, original-bytes rollback, broken-link report via inbound_links), cairn reindex (regenerate dashboard + link cache; extensible generator list)
why:    Track B Phase 3b (mutation/orchestration side; completes Phase 3). Cross-family: GLM gate (2eda383), Fable build (de22293), GLM review.
review: The builder correctly REFUSED to edit a buggy gate test (test_collision seeded a.md titled 'Same' but collision is on filename same.md) and reported it - exactly the discipline. GLM fixed the gate test (seed a real same.md). rename safety reviewed: dirty-tree precheck, original-bytes capture before mutate, rollback on git-mv failure (restore + git reset, never --hard), commit-failure leaves write (DESIGN:755), non-fatal broken-link report. No repo pollution.
verify: 317 passed / 0 skipped / 0 failed (308 + 9), host-verified in worktree
## 2026-08-09T17:54Z phase-4 -> main
what:   cairn tags (list+counts, freq-desc, read-only, frontmatter-only), cairn tag rename/remove (multi-file frontmatter rewrite: normalize, zero-match refuse, collision-before-write refuse, per-file atomic, best-effort partial-failure report, single commit of successes), indexes/tags.md generator wired into reindex
why:    Track B Phase 4 - the multi-file-write SAFETY SEAM. Cross-family: GLM gate (4d84cd9), Fable build (dca948a), GLM review.
review: GLM reviewed tag.py on the seam: collision-before-write, zero-match, partial-failure, single-commit, and scan-still-applies (the commit triggers the pre-commit hook, so no rewrite lands a secret) - all correct. One edge-case bug: a note with BOTH old and new produced [new,new]; fixed with a dedup + pin. No contested finding -> no GLM-fleet escalation needed. No pollution.
verify: 331 passed / 0 skipped / 0 failed (317 + 14), host-verified in worktree
## 2026-08-09T17:59Z phase-5 -> main  (ALL PHASES COMPLETE)
what:   cairn asset add (normal <=1MB -> assets/ + commit; >1MB without --large refuse; --large -> gitignored assets/local/ + tracked assets/local.manifest.json entry [sha256/size/added/referenced_by, sorted], manifest committed not binary); --note appends relative link + sets source_url
why:    Track B Phase 5 (final). Cross-family: GLM gate (d106a1e), Fable build (c674b2a), GLM review.
review: GLM reviewed asset.py. Manifest format matches DESIGN:593-625 (manifest_version, entries sorted by path, sorted keys + 2-space indent for byte-stability). The corruption test PROVES the Phase-1 hook verifies the manifest sha against the on-disk file live (corrupt file -> next commit blocked). Resolved the decisions.md oversimplification: --large cannot use assets/ (hook caps it at 1MB), so it uses assets/local/ + manifest (DESIGN option 3). Assets pass the credential scan on commit. No pollution.
verify: 336 passed / 0 skipped / 0 failed (331 + 5), host-verified in worktree
## 2026-08-09T20:45Z v1.1-adversarial-review -> main
what:   fixed real findings from 3 independent Fable reviewers (Phase 2/3/4-5) + offline suite (sandbox network-denied) + real-TTY capture + dup-filenames check
why:    Ken: 'did you cut corners?' - yes, the adversarial cross-review + spec-QA-of-gate + offline + TTY steps had been skipped or self-reviewed. Ran them for real.
review: 3 Fable reviewers, findings adjudicated vs code. REAL fixes: commit_paths pathspec (bundled pre-staged files - latent across all write commands; existing test gave false confidence), normalize_tag stray-slash on dropped-char segment, search type/status normalization, tag old==new no-op, validate dup-filenames + dead-branch removal, dead test assertion. FALSE positives dropped (inbound_links dup - the break already prevents it; manifest 'history destroyed' - re-add-update is correct; TOCTOU 'BLOCKs' - single-user, documented). Deferred to TODO: lazy rebuild, no-concurrency model, manifest re-add warning, fm type-checks.
verify: 340 passed / 0 skipped offline (sandbox-exec deny network*) AND online; TTY capture proven via pty; 336->340 (+4 regression tests)
