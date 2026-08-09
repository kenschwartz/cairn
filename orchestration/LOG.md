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
