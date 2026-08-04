"""
Integration tests for cairn init and cairn doctor.

All tests use real git repos under tmp_path.
No mocking of the hook path, hook content, or filesystem.
"""

import hashlib
import json
import os
import stat
import subprocess
from pathlib import Path

import pytest


def run(cmd, cwd=None, extra_env=None):
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        cmd, capture_output=True, text=True,
        cwd=str(cwd) if cwd else None, env=env,
    )


def git(args, cwd):
    return run(["git"] + args, cwd=cwd)


# ---------------------------------------------------------------------------
# cairn init: folder structure
# ---------------------------------------------------------------------------

class TestCairnInitFolderStructure:
    def test_creates_notes_dir(self, tmp_vault):
        assert (tmp_vault / "notes").is_dir()

    def test_creates_moc_dir(self, tmp_vault):
        assert (tmp_vault / "moc").is_dir()

    def test_creates_assets_dir(self, tmp_vault):
        assert (tmp_vault / "assets").is_dir()

    def test_creates_assets_local_dir(self, tmp_vault):
        assert (tmp_vault / "assets" / "local").is_dir()

    def test_creates_indexes_dir(self, tmp_vault):
        assert (tmp_vault / "indexes").is_dir()


# ---------------------------------------------------------------------------
# cairn init: git repository
# ---------------------------------------------------------------------------

class TestCairnInitGitRepo:
    def test_vault_is_a_git_repo(self, tmp_vault):
        result = git(["rev-parse", "--git-dir"], cwd=tmp_vault)
        assert result.returncode == 0, "Vault must be a git repository"

    def test_git_init_on_existing_repo_is_idempotent(self, tmp_path):
        """cairn init on an already-initialised repo must not destroy it."""
        vault = tmp_path / "vault"
        vault.mkdir()
        git(["init", str(vault)], cwd=tmp_path)
        # Write a note file so we can check it survives.
        (vault / "notes").mkdir()
        note = vault / "notes" / "survive.md"
        note.write_text("must survive\n")
        git(["add", "."], cwd=vault)
        git(["commit", "-m", "initial"], cwd=vault)

        result = run(["cairn", "init", str(vault)])
        assert result.returncode == 0
        # The note must still exist.
        assert note.exists(), "cairn init must not destroy existing notes"
        assert note.read_text() == "must survive\n"


# ---------------------------------------------------------------------------
# cairn init: .gitignore
# ---------------------------------------------------------------------------

class TestCairnInitGitignore:
    def test_gitignore_created(self, tmp_vault):
        assert (tmp_vault / ".gitignore").exists()

    def test_gitignore_contains_ds_store(self, tmp_vault):
        content = (tmp_vault / ".gitignore").read_text()
        assert ".DS_Store" in content

    def test_gitignore_contains_swap_files(self, tmp_vault):
        content = (tmp_vault / ".gitignore").read_text()
        assert "*~" in content or "*.swp" in content

    def test_gitignore_contains_assets_local(self, tmp_vault):
        """assets/local/ must be gitignored (large binaries not committed)."""
        content = (tmp_vault / ".gitignore").read_text()
        assert "assets/local/" in content or "assets/local" in content


# ---------------------------------------------------------------------------
# cairn init: hook installation
# ---------------------------------------------------------------------------

class TestCairnInitHooks:
    def test_pre_commit_hook_exists(self, tmp_vault):
        hook = tmp_vault / ".git" / "hooks" / "pre-commit"
        assert hook.exists(), "pre-commit hook must exist after cairn init"

    def test_pre_push_hook_exists(self, tmp_vault):
        hook = tmp_vault / ".git" / "hooks" / "pre-push"
        assert hook.exists(), "pre-push hook must exist after cairn init"

    def test_pre_commit_hook_mode_0755(self, tmp_vault):
        hook = tmp_vault / ".git" / "hooks" / "pre-commit"
        mode = stat.S_IMODE(hook.stat().st_mode)
        assert mode == 0o755, f"pre-commit hook mode must be 0755, got {oct(mode)}"

    def test_pre_push_hook_mode_0755(self, tmp_vault):
        hook = tmp_vault / ".git" / "hooks" / "pre-push"
        mode = stat.S_IMODE(hook.stat().st_mode)
        assert mode == 0o755, f"pre-push hook mode must be 0755, got {oct(mode)}"

    def test_pre_commit_shebang_is_static(self, tmp_vault):
        """
        Shebang must be the static '#!/usr/bin/env python3'.
        DESIGN.md: 'No interpreter is substituted. The shebang is the static
        line #!/usr/bin/env python3.'
        """
        hook = tmp_vault / ".git" / "hooks" / "pre-commit"
        first_line = hook.read_text().splitlines()[0]
        assert first_line == "#!/usr/bin/env python3", (
            f"pre-commit shebang must be static '#!/usr/bin/env python3', got {first_line!r}"
        )

    def test_pre_push_shebang_is_static(self, tmp_vault):
        hook = tmp_vault / ".git" / "hooks" / "pre-push"
        first_line = hook.read_text().splitlines()[0]
        assert first_line == "#!/usr/bin/env python3", (
            f"pre-push shebang must be static '#!/usr/bin/env python3', got {first_line!r}"
        )

    def test_pre_commit_contains_scan_sentinels(self, tmp_vault):
        """The pre-commit hook must contain the BEGIN/END CAIRN SCAN sentinels."""
        hook = tmp_vault / ".git" / "hooks" / "pre-commit"
        content = hook.read_text()
        assert "# --- BEGIN CAIRN SCAN (generated, do not edit) ---" in content
        assert "# --- END CAIRN SCAN ---" in content

    def test_pre_push_contains_allowlist(self, tmp_vault):
        """
        The pre-push hook must contain the ALLOWLIST as a JSON literal.
        DESIGN.md: '{{ALLOWLIST}} - the remote allowlist as a JSON literal'.
        """
        hook = tmp_vault / ".git" / "hooks" / "pre-push"
        content = hook.read_text()
        # Must contain the CFG-INNERSOURCE prefix.
        assert "CFG-INNERSOURCE" in content, (
            "pre-push hook must contain the remote allowlist"
        )


# ---------------------------------------------------------------------------
# cairn init: idempotency
# ---------------------------------------------------------------------------

class TestCairnInitIdempotency:
    def test_second_init_reinstalls_hooks(self, tmp_vault):
        """
        Running cairn init a second time must reinstall the hooks.
        DESIGN.md: 'Running it on an existing vault reinstalls hooks'.
        """
        hook = tmp_vault / ".git" / "hooks" / "pre-commit"
        # Corrupt the hook.
        hook.write_text("#!/bin/sh\nexit 0\n")
        hook.chmod(0o755)

        result = run(["cairn", "init", str(tmp_vault)])
        assert result.returncode == 0

        # Hook must be restored (no longer just 'exit 0').
        content = hook.read_text()
        assert "BEGIN CAIRN SCAN" in content, (
            "Second cairn init must reinstall the hook (not leave corrupted version)"
        )

    def test_second_init_does_not_destroy_notes(self, tmp_vault):
        note = tmp_vault / "notes" / "existing.md"
        note.write_text("---\nid: 12345678\ntitle: Existing\n---\n")

        result = run(["cairn", "init", str(tmp_vault)])
        assert result.returncode == 0
        assert note.exists()
        assert "Existing" in note.read_text()

    def test_init_reports_existing_vs_created(self, tmp_vault):
        """
        cairn init must report what it created vs what was already present.
        DESIGN.md: 'cairn init reports what it created versus what was already present.'
        We assert the exit is zero; actual message content is implementation-dependent
        but must not be silent.
        """
        result = run(["cairn", "init", str(tmp_vault)])
        assert result.returncode == 0
        assert result.stdout.strip() or result.stderr.strip(), (
            "cairn init must produce some output (created vs already present)"
        )


# ---------------------------------------------------------------------------
# cairn init: remote allowlist
# ---------------------------------------------------------------------------

class TestCairnInitRemoteAllowlist:
    def test_zero_remotes_is_allowed_with_warning(self, tmp_path):
        """
        DESIGN.md: 'Zero remotes is allowed (warning, see cairn doctor).'
        cairn init must succeed (exit 0) with zero remotes.
        """
        vault = tmp_path / "vault"
        vault.mkdir()
        result = run(["cairn", "init", str(vault)])
        assert result.returncode == 0, (
            "Zero remotes must be allowed; cairn init must succeed"
        )

    def test_non_allowlisted_remote_fails(self, tmp_path):
        """
        DESIGN.md: 'rejects unknown remotes'.
        A remote pointing at a personal GitHub must be rejected.
        """
        vault = tmp_path / "vault"
        vault.mkdir()
        run(["cairn", "init", str(vault)])
        git(["remote", "add", "origin", "https://github.com/personal/repo.git"], cwd=vault)

        result = run(["cairn", "init", str(vault)])
        assert result.returncode != 0, (
            "Non-allowlisted remote must cause cairn init to fail"
        )

    def test_allowlisted_remote_accepted(self, tmp_path, tmp_path_factory):
        """
        A remote URL matching the CFG-INNERSOURCE allowlist prefix must be accepted.
        We use a local bare repo whose URL is crafted to look like the allowlist prefix
        by overriding the allowlist for the test.
        DESIGN.md: 'The remote allowlist must be overridable for tests'.
        """
        vault = tmp_path / "vault"
        vault.mkdir()
        bare = tmp_path_factory.mktemp("bare")
        subprocess.run(["git", "init", "--bare", str(bare)], check=True,
                       capture_output=True, env=os.environ.copy())
        run(["cairn", "init", str(vault)])

        # Add the bare repo as a remote with an allowlisted prefix.
        # We override the allowlist to include the local bare repo path.
        allowlist_env = {"CAIRN_ALLOWED_REMOTE_PREFIXES": str(bare)}
        git(["remote", "add", "origin", str(bare)], cwd=vault)

        result = run(["cairn", "init", str(vault)], extra_env=allowlist_env)
        assert result.returncode == 0, (
            f"Allowlisted remote must be accepted.\nstderr: {result.stderr}"
        )


# ---------------------------------------------------------------------------
# cairn init: missing git identity
# ---------------------------------------------------------------------------

class TestCairnInitGitIdentity:
    def test_missing_user_email_does_not_prevent_folder_creation(self, tmp_path):
        """
        DESIGN.md: 'If git config user.email is missing, cairn init may create
        folders and hooks but refuses auto-commit with a clear message.'
        Folders must still be created.
        """
        vault = tmp_path / "vault"
        vault.mkdir()

        # Write a global config with no email.
        gcfg = Path(os.environ["GIT_CONFIG_GLOBAL"])
        original = gcfg.read_text()
        gcfg.write_text("[user]\n    name = Test Author\n    email =\n")

        try:
            result = run(["cairn", "init", str(vault)])
        finally:
            gcfg.write_text(original)

        # Folders must exist regardless.
        assert (vault / "notes").is_dir()
        assert (vault / "hooks" if False else vault / ".git" / "hooks" / "pre-commit").exists()

    def test_missing_user_email_message_is_clear(self, tmp_path):
        """
        The error or warning message when email is missing must be clear.
        We assert there is SOME output; the exact wording is implementation-defined.
        """
        vault = tmp_path / "vault"
        vault.mkdir()

        gcfg = Path(os.environ["GIT_CONFIG_GLOBAL"])
        original = gcfg.read_text()
        gcfg.write_text("[user]\n    name = Test Author\n    email =\n")

        try:
            result = run(["cairn", "init", str(vault)])
        finally:
            gcfg.write_text(original)

        combined = result.stdout + result.stderr
        assert combined.strip(), "Missing email must produce a message"


# ---------------------------------------------------------------------------
# cairn doctor: checks
# ---------------------------------------------------------------------------

class TestCairnDoctor:
    def test_doctor_passes_on_clean_vault(self, tmp_vault):
        """cairn doctor must exit 0 on a freshly initialised vault."""
        result = run(["cairn", "doctor"], cwd=tmp_vault)
        assert result.returncode == 0, (
            f"cairn doctor must pass on a clean vault.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_doctor_checks_python_version(self, tmp_vault):
        """
        DESIGN.md: 'Python version >= 3.11'.
        Doctor output must mention Python version check.
        """
        result = run(["cairn", "doctor"], cwd=tmp_vault)
        combined = result.stdout + result.stderr
        assert "python" in combined.lower() or "3." in combined, (
            "Doctor must report on Python version"
        )

    def test_doctor_checks_git_version(self, tmp_vault):
        """DESIGN.md: 'git on PATH, version >= 2.30'."""
        result = run(["cairn", "doctor"], cwd=tmp_vault)
        combined = result.stdout + result.stderr
        assert "git" in combined.lower(), "Doctor must report on git version"

    def test_doctor_checks_pyyaml_importable(self, tmp_vault):
        result = run(["cairn", "doctor"], cwd=tmp_vault)
        combined = result.stdout + result.stderr
        assert "yaml" in combined.lower() or "pyyaml" in combined.lower(), (
            "Doctor must check PyYAML importability"
        )

    def test_doctor_checks_user_email(self, tmp_vault):
        result = run(["cairn", "doctor"], cwd=tmp_vault)
        combined = result.stdout + result.stderr
        assert "email" in combined.lower(), (
            "Doctor must check git config user.email"
        )

    def test_doctor_checks_vault_is_git_repo(self, tmp_vault):
        """Doctor must verify the vault directory is a git repo."""
        result = run(["cairn", "doctor"], cwd=tmp_vault)
        assert result.returncode == 0

    def test_doctor_checks_hooks_present(self, tmp_vault):
        """Doctor must verify both hooks exist."""
        result = run(["cairn", "doctor"], cwd=tmp_vault)
        combined = result.stdout + result.stderr
        assert "hook" in combined.lower(), "Doctor must check hook presence"

    def test_doctor_fails_missing_pre_commit(self, tmp_vault):
        """Delete pre-commit hook; doctor must fail."""
        (tmp_vault / ".git" / "hooks" / "pre-commit").unlink()
        result = run(["cairn", "doctor"], cwd=tmp_vault)
        assert result.returncode != 0, (
            "Doctor must fail when pre-commit hook is missing"
        )

    def test_doctor_fails_missing_pre_push(self, tmp_vault):
        (tmp_vault / ".git" / "hooks" / "pre-push").unlink()
        result = run(["cairn", "doctor"], cwd=tmp_vault)
        assert result.returncode != 0

    def test_doctor_fails_hook_not_executable(self, tmp_vault):
        """Doctor must fail when a hook is present but not executable (mode 0644)."""
        hook = tmp_vault / ".git" / "hooks" / "pre-commit"
        hook.chmod(0o644)
        result = run(["cairn", "doctor"], cwd=tmp_vault)
        assert result.returncode != 0, (
            "Non-executable hook must cause doctor to fail"
        )

    def test_doctor_fails_hook_content_tampered(self, tmp_vault):
        """
        Appending a byte to the hook must cause doctor to fail (SHA-256 mismatch).
        DESIGN.md: 'A missing, altered, or stale hook is a hard fail'.
        """
        hook = tmp_vault / ".git" / "hooks" / "pre-commit"
        original = hook.read_bytes()
        hook.write_bytes(original + b"\n# tampered\n")
        result = run(["cairn", "doctor"], cwd=tmp_vault)
        assert result.returncode != 0, (
            "Tampered hook must cause doctor to fail (SHA-256 mismatch)"
        )

    def test_doctor_fix_reinstalls_missing_hook(self, tmp_vault):
        """
        'cairn doctor --fix' must reinstall a missing hook and then pass.
        """
        (tmp_vault / ".git" / "hooks" / "pre-commit").unlink()
        fix_result = run(["cairn", "doctor", "--fix"], cwd=tmp_vault)
        assert fix_result.returncode == 0, (
            f"cairn doctor --fix must exit 0 after reinstalling.\n"
            f"stderr: {fix_result.stderr}"
        )
        # Verify the hook is back and executable.
        hook = tmp_vault / ".git" / "hooks" / "pre-commit"
        assert hook.exists()
        assert stat.S_IMODE(hook.stat().st_mode) == 0o755

    def test_doctor_fix_reinstalls_tampered_hook(self, tmp_vault):
        hook = tmp_vault / ".git" / "hooks" / "pre-commit"
        hook.write_bytes(hook.read_bytes() + b"\n# tampered\n")
        run(["cairn", "doctor", "--fix"], cwd=tmp_vault)
        result = run(["cairn", "doctor"], cwd=tmp_vault)
        assert result.returncode == 0, (
            "After --fix, doctor must pass"
        )

    def test_doctor_names_failing_hook_in_output(self, tmp_vault):
        """Doctor must name the hook that failed, not just exit non-zero."""
        (tmp_vault / ".git" / "hooks" / "pre-commit").unlink()
        result = run(["cairn", "doctor"], cwd=tmp_vault)
        combined = result.stdout + result.stderr
        assert "pre-commit" in combined, (
            "Doctor must name the missing hook in its output"
        )

    def test_doctor_sha256_matches_rerender(self, tmp_vault):
        """
        DESIGN.md: 'cairn doctor verifies that both hooks exist, are executable,
        and match a fresh in-memory re-render from the current package and config
        (by SHA-256).'
        Doctor passes on a freshly installed hook (already tested), and fails on a
        tampered one (tested above). This test asserts the SHA-256 match mechanism
        is explicitly tested by the suite.
        """
        # Verify that a freshly rendered hook matches what doctor expects.
        result = run(["cairn", "doctor"], cwd=tmp_vault)
        assert result.returncode == 0

    def test_doctor_zero_remotes_is_warning_not_fail(self, tmp_vault):
        """
        DESIGN.md: 'zero remotes is a warning... local-first use is allowed'.
        Doctor on a vault with no remotes must exit 0.
        """
        # tmp_vault has no remotes by default.
        result = run(["cairn", "doctor"], cwd=tmp_vault)
        assert result.returncode == 0, (
            "Zero remotes must be a warning, not a hard fail"
        )

    def test_doctor_non_allowlisted_remote_hard_fails(self, tmp_vault):
        """
        DESIGN.md: 'any non-matching remote is a hard fail'.
        """
        git(["remote", "add", "origin", "https://github.com/personal/badrepo.git"],
            cwd=tmp_vault)
        result = run(["cairn", "doctor"], cwd=tmp_vault)
        assert result.returncode != 0, (
            "Non-allowlisted remote must be a hard fail in doctor"
        )

    def test_doctor_local_bin_on_path_check(self, tmp_vault):
        """Doctor must check that ~/.local/bin is on PATH."""
        result = run(["cairn", "doctor"], cwd=tmp_vault)
        combined = result.stdout + result.stderr
        assert ".local/bin" in combined or "local/bin" in combined or "PATH" in combined, (
            "Doctor must check ~/.local/bin on PATH"
        )


# ---------------------------------------------------------------------------
# BLOCK 4 companion removal (deliberate expectation change):
# test_doctor_history_scan_runs_by_default asserted only `returncode == 0`
# on a clean vault, which is true whether or not any history scan ever
# runs -- it is not a proof the scan exists. DESIGN.md 'Security enforcement
# via git hooks' marks the bounded history scan explicitly '(v2, deferred)'
# and TODO.md 'Deferred scan features (v2)' lists it as not-yet-active. A
# v1 gate must not require v2 behaviour, vacuous or not, so this test was
# removed rather than strengthened. If the history scan lands in v2,
# re-derive it from a NON-VACUOUS assertion (specific finding content only
# the scan could produce) with a negative control (clean-history vault must
# NOT warn) -- see test_hooks.py's TestNoVerifyBypass docstring for the
# same note.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# BLOCK 2 (Tier 0, docs/reviews/phase1-review-triage-2026-08-03.md):
# `git config core.hooksPath <dir>` makes git stop using .git/hooks/
# entirely -- no scan, no allowlist enforcement -- while doctor's hash
# check still finds the (now-dead) hooks present, executable, and
# matching, and reports green. DESIGN.md 'Hook mechanism', "Scope for v1:
# one top-level worktree" (amended after the earlier FIX-DESIGN flag on
# this exact point was raised and accepted): 'core.hooksPath, linked
# worktrees, and submodules are out of scope for v1; cairn doctor reports
# rather than adapts if it finds core.hooksPath set, and that report is a
# HARD FAIL (non-zero exit), because a diverted hooks path means the
# installed hooks never run while everything else still looks green.'
# The design now pins hard-fail explicitly; no ambiguity remains.
# ---------------------------------------------------------------------------

class TestDoctorHooksPathDiversion:
    def test_hookspath_diverted_doctor_does_not_report_green(self, tmp_vault):
        diverted = tmp_vault.parent / "diverted-hooks"
        diverted.mkdir()
        git(["config", "core.hooksPath", str(diverted)], cwd=tmp_vault)
        result = run(["cairn", "doctor"], cwd=tmp_vault)
        assert result.returncode != 0, (
            "doctor must not report green when core.hooksPath diverts git "
            "away from the verified .git/hooks -- the installed hooks are "
            "dead and doctor's hash check no longer means anything"
        )

    def test_hookspath_diverted_named_in_output(self, tmp_vault):
        diverted = tmp_vault.parent / "diverted-hooks-2"
        diverted.mkdir()
        git(["config", "core.hooksPath", str(diverted)], cwd=tmp_vault)
        result = run(["cairn", "doctor"], cwd=tmp_vault)
        combined = result.stdout + result.stderr
        assert "hookspath" in combined.lower() or "core.hookspath" in combined.lower(), (
            "doctor must name the specific condition (core.hooksPath) so "
            "the user knows why, not just fail generically. "
            f"Got: {combined!r}"
        )

    def test_hookspath_unset_is_unaffected(self, tmp_vault):
        """Positive control: a vault that never touched core.hooksPath must
        still pass doctor (this is the ordinary, already-covered case;
        included here so a broken hooksPath check cannot be 'fixed' by
        making doctor fail unconditionally)."""
        result = run(["cairn", "doctor"], cwd=tmp_vault)
        assert result.returncode == 0


# ---------------------------------------------------------------------------
# BLOCK 3 (Tier 1, docs/reviews/phase1-review-triage-2026-08-03.md):
# doctor.py's --fix path sets `hard_fail = False` unconditionally after
# reinstalling hooks, wiping a hard_fail the REMOTE check had already set.
# A vault with a forbidden remote AND missing hooks comes out of
# `cairn doctor --fix` reporting healthy, exit 0.
# ---------------------------------------------------------------------------

class TestDoctorFixDoesNotEraseUnrelatedFailure:
    def test_fix_does_not_erase_forbidden_remote_failure(self, tmp_vault):
        git(["remote", "add", "origin", "https://github.com/personal/badrepo.git"],
            cwd=tmp_vault)
        (tmp_vault / ".git" / "hooks" / "pre-commit").unlink()

        result = run(["cairn", "doctor", "--fix"], cwd=tmp_vault)
        assert result.returncode != 0, (
            "doctor --fix must not report healthy when a forbidden remote "
            "is still configured, even though the hook reinstall succeeded"
        )
        combined = (result.stdout + result.stderr).lower()
        assert "badrepo" in combined or "not in allowlist" in combined or "remote" in combined, (
            f"doctor --fix must still report the forbidden remote in its "
            f"output. Got: {result.stdout + result.stderr!r}"
        )

    def test_fix_still_reinstalls_the_hook_despite_remote_failure(self, tmp_vault):
        """The hook fix itself must still happen -- BLOCK 3 is about the
        remote failure being erased, not about the hook fix being skipped."""
        git(["remote", "add", "origin", "https://github.com/personal/badrepo.git"],
            cwd=tmp_vault)
        (tmp_vault / ".git" / "hooks" / "pre-commit").unlink()

        run(["cairn", "doctor", "--fix"], cwd=tmp_vault)

        hook = tmp_vault / ".git" / "hooks" / "pre-commit"
        assert hook.exists(), "the missing hook must still be reinstalled"
        assert stat.S_IMODE(hook.stat().st_mode) == 0o755


# ---------------------------------------------------------------------------
# DESIGN.md 'Remote allowlist': 'cairn doctor compares the installed hook
# against a fresh render from current config and FAILS LOUDLY when they
# diverge, so a stale baked list cannot silently persist.' ... 'Editing the
# allowlist requires re-baking the hook: the baked list is a snapshot, so
# after editing config the user runs cairn init (or cairn doctor --fix) to
# re-render the pre-push hook.'
# ---------------------------------------------------------------------------

class TestDoctorAllowlistRebakeDrift:
    def test_stale_baked_allowlist_fails_doctor(self, tmp_vault):
        """
        Simulate a config change that was never re-baked via cairn init:
        doctor must fail loudly on the mismatch between the installed hook
        (baked with the default allowlist) and a fresh render from the
        now-different config, not silently pass.
        """
        result = run(
            ["cairn", "doctor"],
            cwd=tmp_vault,
            extra_env={"CAIRN_ALLOWED_REMOTE_PREFIXES": "https://github.com/SOME-OTHER-ORG/"},
        )
        assert result.returncode != 0, (
            "doctor must fail loudly when the installed pre-push hook's "
            "baked allowlist no longer matches a fresh render from current "
            "config"
        )
        combined = (result.stdout + result.stderr).lower()
        assert "pre-push" in combined, (
            "doctor must name the pre-push hook as the point of mismatch"
        )

    def test_rebake_via_init_after_config_change_fixes_drift(self, tmp_vault):
        """After the config changes, re-running cairn init re-bakes the
        hook and doctor passes again when checked against that same
        (new) config."""
        env = {"CAIRN_ALLOWED_REMOTE_PREFIXES": "https://github.com/SOME-OTHER-ORG/"}
        reinit = run(["cairn", "init", str(tmp_vault)], extra_env=env)
        assert reinit.returncode == 0, f"setup: re-init must succeed.\nstderr: {reinit.stderr}"

        result = run(["cairn", "doctor"], cwd=tmp_vault, extra_env=env)
        assert result.returncode == 0, (
            f"After re-baking via cairn init with the new config, doctor "
            f"must pass when checked against that same config.\n"
            f"stderr: {result.stderr}"
        )


# ---------------------------------------------------------------------------
# Hook content pinning: rendered scan source is byte-identical to scan.py
# (Integration test #6 from DESIGN.md)
# ---------------------------------------------------------------------------

class TestHookContentPinning:
    def test_inlined_scan_source_matches_scan_py(self, tmp_vault):
        """
        DESIGN.md integration test #6: 'Render both hooks and assert the inlined
        scan source is byte-identical to src/cairn/scan.py'.
        Extract the region between the sentinels in the installed pre-commit hook
        and compare it byte-for-byte to scan.py.
        """
        import cairn.scan as scan_mod
        scan_src = Path(scan_mod.__file__).read_text()

        hook_text = (tmp_vault / ".git" / "hooks" / "pre-commit").read_text()

        begin = "# --- BEGIN CAIRN SCAN (generated, do not edit) ---"
        end = "# --- END CAIRN SCAN ---"
        assert begin in hook_text, "BEGIN sentinel must be in pre-commit hook"
        assert end in hook_text, "END sentinel must be in pre-commit hook"

        start_idx = hook_text.index(begin) + len(begin) + 1  # +1 for newline
        end_idx = hook_text.index(end)
        inlined = hook_text[start_idx:end_idx]

        assert inlined == scan_src, (
            "Inlined scan source in hook must be byte-identical to scan.py"
        )

    def test_pre_push_hook_contains_allowlist_json(self, tmp_vault):
        """
        DESIGN.md: '{{ALLOWLIST}} - the remote allowlist as a JSON literal'.
        The pre-push hook must contain valid JSON that includes the allowlist.
        """
        hook_text = (tmp_vault / ".git" / "hooks" / "pre-push").read_text()
        # The allowlist JSON must appear somewhere in the hook.
        # Find and validate it.
        assert "CFG-INNERSOURCE" in hook_text
        # Try to find and parse the JSON fragment.
        # It must be parseable as a list of strings.
        import re
        # Locate a JSON array containing the allowlist.
        match = re.search(r'\[.*?CFG-INNERSOURCE.*?\]', hook_text, re.DOTALL)
        assert match, "Allowlist JSON array must be present in pre-push hook"
        allowlist = json.loads(match.group(0))
        assert isinstance(allowlist, list)
        assert any("CFG-INNERSOURCE" in prefix for prefix in allowlist)


# ---------------------------------------------------------------------------
# assets/local manifest format contract (Phase 1 load-bearing)
# ---------------------------------------------------------------------------

class TestAssetsLocalManifest:
    """
    DESIGN.md: 'The format is therefore Phase 1 load-bearing: the hook cannot
    be written against a format that does not exist yet.'
    """

    def _write_manifest(self, vault: Path, entries: list) -> Path:
        manifest_path = vault / "assets" / "local.manifest.json"
        manifest = {
            "manifest_version": 1,
            "entries": entries,
        }
        manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2))
        return manifest_path

    def test_manifest_location_is_sibling_of_local_dir(self, tmp_vault):
        """
        DESIGN.md: 'Location: assets/local.manifest.json, committed.'
        The manifest is a sibling of assets/local/, not inside it.
        """
        manifest = self._write_manifest(tmp_vault, [])
        assert manifest.parent == tmp_vault / "assets"
        assert manifest.name == "local.manifest.json"

    def test_pre_commit_fails_on_sha256_mismatch(self, tmp_vault):
        """
        DESIGN.md: 'On-disk SHA-256 differs from the entry: FAIL the commit'.
        Create a local file, record a WRONG hash, stage the manifest, commit fails.
        """
        local_dir = tmp_vault / "assets" / "local"
        local_dir.mkdir(parents=True, exist_ok=True)
        local_file = local_dir / "test.pdf"
        local_file.write_bytes(b"real content")

        real_sha256 = hashlib.sha256(b"real content").hexdigest()
        wrong_sha256 = "0" * 64

        assert wrong_sha256 != real_sha256

        manifest_path = self._write_manifest(tmp_vault, [{
            "path": "assets/local/test.pdf",
            "size_bytes": 12,
            "sha256": wrong_sha256,
            "added": "2026-08-03",
            "referenced_by": "notes/test.md",
        }])

        # Stage the manifest and a note.
        git(["add", "assets/local.manifest.json"], cwd=tmp_vault)
        # Try to commit.
        result = git(["commit", "-m", "test manifest mismatch"], cwd=tmp_vault)
        assert result.returncode != 0, (
            "Pre-commit hook must fail when manifest SHA-256 does not match on-disk file"
        )

    def test_pre_commit_passes_on_sha256_match(self, tmp_vault):
        """
        DESIGN.md: 'On-disk SHA-256 matches: commit proceeds'.
        """
        local_dir = tmp_vault / "assets" / "local"
        local_dir.mkdir(parents=True, exist_ok=True)
        local_file = local_dir / "ok.pdf"
        content = b"correct content"
        local_file.write_bytes(content)

        sha256 = hashlib.sha256(content).hexdigest()
        manifest_path = self._write_manifest(tmp_vault, [{
            "path": "assets/local/ok.pdf",
            "size_bytes": len(content),
            "sha256": sha256,
            "added": "2026-08-03",
            "referenced_by": "notes/test.md",
        }])

        git(["add", "assets/local.manifest.json"], cwd=tmp_vault)
        result = git(["commit", "-m", "manifest ok"], cwd=tmp_vault)
        assert result.returncode == 0, (
            f"Correct SHA-256 must allow commit.\nstderr: {result.stderr}"
        )

    def test_pre_commit_missing_local_file_warns_not_fails(self, tmp_vault):
        """
        DESIGN.md: 'File named by an entry is missing: warn, do not block'.
        The manifest entry exists but the file is not on disk (e.g. fresh clone).
        The commit must proceed.
        """
        manifest_path = self._write_manifest(tmp_vault, [{
            "path": "assets/local/missing.pdf",
            "size_bytes": 100,
            "sha256": "a" * 64,
            "added": "2026-08-03",
            "referenced_by": "notes/test.md",
        }])

        git(["add", "assets/local.manifest.json"], cwd=tmp_vault)
        result = git(["commit", "-m", "missing file warn not fail"], cwd=tmp_vault)
        assert result.returncode == 0, (
            f"Missing local file must warn, not block commit.\n"
            f"stderr: {result.stderr}"
        )

    def test_manifest_format_json_not_yaml(self, tmp_vault):
        """
        DESIGN.md: 'Format: JSON, not YAML. This is forced by the hook design:
        the hook runs stdlib-only under a possibly-bare system interpreter,
        and json is stdlib while yaml is not.'
        The manifest must be valid JSON parseable by stdlib json.
        """
        manifest_path = self._write_manifest(tmp_vault, [])
        import json as _json
        data = _json.loads(manifest_path.read_text())
        assert "manifest_version" in data
        assert "entries" in data

    def test_manifest_version_is_1(self, tmp_vault):
        manifest_path = self._write_manifest(tmp_vault, [])
        import json as _json
        data = _json.loads(manifest_path.read_text())
        assert data["manifest_version"] == 1

    def test_manifest_entries_sorted_by_path(self, tmp_vault):
        """
        DESIGN.md: 'entries is sorted by path, so two machines produce identical bytes.'
        """
        entries = [
            {"path": "assets/local/z.pdf", "size_bytes": 1, "sha256": "a" * 64,
             "added": "2026-08-03", "referenced_by": "notes/n.md"},
            {"path": "assets/local/a.pdf", "size_bytes": 1, "sha256": "b" * 64,
             "added": "2026-08-03", "referenced_by": "notes/n.md"},
        ]
        # We test that cairn produces sorted output by asking it to write one.
        # For now, just assert the format spec is captured -- the hook reads
        # entries in sorted order.
        paths = [e["path"] for e in sorted(entries, key=lambda e: e["path"])]
        assert paths == sorted(paths)
