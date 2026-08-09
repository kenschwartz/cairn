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
