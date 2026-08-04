"""
Integration tests for the git hooks.

These are the eight required integration tests from DESIGN.md plus supporting
tests. Every test invokes `git` and lets git run the hook. No in-process
short-circuit of the scan logic.

DESIGN.md: 'A test that imports the scan function and asserts it returns
findings proves nothing about the hook: it cannot catch a broken shebang, a
bad interpreter resolution, a rendering bug, a non-executable file, or a hook
that was never installed.'

v1 scope note: SSN, payment-card, and labelled-high-entropy-token fixtures
(and the cairn:allow-secret suppression positive control) were removed from
this file along with their rules -- see test_scan.py's module docstring for
the full rationale. Doctor's hooksPath-diversion check (BLOCK 2), the
--fix/remote-failure interaction (BLOCK 3), and the allowlist re-bake/
fail-loud drift check live in tests/integration/test_init_doctor.py
alongside the rest of the `cairn doctor` coverage.
"""

import hashlib
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


def git(args, cwd, extra_env=None):
    return run(["git"] + args, cwd=cwd, extra_env=extra_env)


def stage_and_commit(vault: Path, filename: str, content: str,
                     commit_msg: str = "test commit",
                     no_verify: bool = False) -> subprocess.CompletedProcess:
    """Write a file, stage it, and attempt a commit."""
    filepath = vault / "notes" / filename
    filepath.write_text(content)
    git(["add", f"notes/{filename}"], cwd=vault)
    cmd = ["git", "commit", "-m", commit_msg]
    if no_verify:
        cmd.append("--no-verify")
    return run(cmd, cwd=vault)


def commit_count(vault: Path) -> int:
    result = git(["rev-list", "--count", "HEAD"], cwd=vault)
    if result.returncode != 0:
        return 0
    return int(result.stdout.strip())


# ---------------------------------------------------------------------------
# Integration test #1: secret triggers hook rejection
# DESIGN.md: 'Stage a file containing a synthetic secret, run git commit,
# assert non-zero exit and the rule name in stderr, and assert git log gained
# no commit.'
# ---------------------------------------------------------------------------

class TestHookBlocksSecret:
    # Synthetic secrets that match rules without being live credentials.
    AWS_SYNTHETIC = "AKIAIOSFODNN7EXAMPLE"
    PRIVATE_KEY_SYNTHETIC = "-----BEGIN RSA PRIVATE KEY-----\nFAKE KEY BODY FOR TEST\n-----END RSA PRIVATE KEY-----\n"
    GITHUB_TOKEN_SYNTHETIC = "ghp_" + ("EXAMPLE0" * 4) + "EXAM"

    def test_aws_key_blocks_commit(self, tmp_vault):
        before = commit_count(tmp_vault)
        result = stage_and_commit(
            tmp_vault, "aws_secret.md",
            f"# Note\n\nkey = {self.AWS_SYNTHETIC}\n"
        )
        assert result.returncode != 0, (
            "Commit containing synthetic AWS key must be blocked by pre-commit hook"
        )
        assert commit_count(tmp_vault) == before, "No new commit must be created"

    def test_aws_key_rule_name_in_output(self, tmp_vault):
        """Rule name must appear in the output so the user knows what fired."""
        stage_and_commit(tmp_vault, "aws_name.md",
                         f"key = {self.AWS_SYNTHETIC}\n")
        # The finding is already in place from the failed commit above;
        # re-stage and try again.
        (tmp_vault / "notes" / "aws_name2.md").write_text(
            f"key = {self.AWS_SYNTHETIC}\n"
        )
        git(["add", "notes/aws_name2.md"], cwd=tmp_vault)
        result = run(["git", "commit", "-m", "aws test"], cwd=tmp_vault)
        combined = result.stdout + result.stderr
        assert "aws" in combined.lower() or "access_key" in combined.lower(), (
            f"Rule name must appear in output. Got: {combined!r}"
        )

    def test_private_key_blocks_commit(self, tmp_vault):
        before = commit_count(tmp_vault)
        filepath = tmp_vault / "notes" / "key.pem"
        filepath.write_text(self.PRIVATE_KEY_SYNTHETIC)
        git(["add", "notes/key.pem"], cwd=tmp_vault)
        result = run(["git", "commit", "-m", "add key"], cwd=tmp_vault)
        assert result.returncode != 0
        assert commit_count(tmp_vault) == before

    def test_github_token_blocks_commit(self, tmp_vault):
        """
        End-to-end wiring check for a v1 rule the old gate lacked: proves
        the RENDERED hook (not just the unit-level scan_bytes) rejects it,
        and specifically via the github_token rule.

        FIXTURE VALIDATION CATCH: an earlier version of this test asserted
        only `returncode != 0` and passed today for the WRONG reason -- the
        current (pre-rework) scan.py still carries the v2-deferred
        labelled_token rule, which also matches a line shaped like
        'token = ghp_...' and blocks the commit on its own. Reproduced by
        hand: `git commit` on this exact fixture currently prints
        'labelled_token: notes/gh.md:1 ghp_EXAMPLE0', not 'github_token'.
        Asserting the rule name specifically (matching the precedent set by
        test_aws_key_rule_name_in_output) makes this a genuine red proof
        that the github_token rule itself is wired end to end, not just
        that *some* rule happens to block the line today.
        """
        before = commit_count(tmp_vault)
        result = stage_and_commit(
            tmp_vault, "gh_token.md",
            f"# Note\n\ntoken = {self.GITHUB_TOKEN_SYNTHETIC}\n"
        )
        assert result.returncode != 0, (
            "Commit containing synthetic GitHub token must be blocked by pre-commit hook"
        )
        assert commit_count(tmp_vault) == before
        combined = result.stdout + result.stderr
        assert "github_token" in combined, (
            f"Commit must be blocked specifically by the github_token rule, "
            f"not merely by some other rule that happens to also match. "
            f"Got: {combined!r}"
        )

    def test_finding_output_does_not_contain_full_secret(self, tmp_vault):
        """
        DESIGN.md: 'Never print the full matched secret'.
        The hook output must not contain the full AWS key.
        """
        (tmp_vault / "notes" / "aws_mask.md").write_text(
            f"key = {self.AWS_SYNTHETIC}\n"
        )
        git(["add", "notes/aws_mask.md"], cwd=tmp_vault)
        result = run(["git", "commit", "-m", "mask test"], cwd=tmp_vault)
        combined = result.stdout + result.stderr
        assert self.AWS_SYNTHETIC not in combined, (
            "Hook output must not contain the full matched secret"
        )

    def test_finding_output_contains_file_path(self, tmp_vault):
        """DESIGN.md: 'prints for each finding the rule name, the file path, the line number'."""
        (tmp_vault / "notes" / "aws_path.md").write_text(
            f"key = {self.AWS_SYNTHETIC}\n"
        )
        git(["add", "notes/aws_path.md"], cwd=tmp_vault)
        result = run(["git", "commit", "-m", "path test"], cwd=tmp_vault)
        combined = result.stdout + result.stderr
        assert "aws_path.md" in combined, (
            "Hook output must include the file path"
        )


# ---------------------------------------------------------------------------
# Integration test #2: clean file passes -- positive control
# DESIGN.md: 'Stage a clean file, run git commit, assert exit zero and one
# new commit. This is the positive control.'
# ---------------------------------------------------------------------------

class TestHookAllowsCleanCommit:
    def test_clean_file_commits_successfully(self, tmp_vault):
        before = commit_count(tmp_vault)
        result = stage_and_commit(
            tmp_vault, "clean_note.md",
            "---\nid: aabbccdd\ntitle: Clean Note\ntype: note\n---\n# Clean\n\nNo secrets here.\n"
        )
        assert result.returncode == 0, (
            f"Clean file must commit successfully.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert commit_count(tmp_vault) == before + 1

    def test_multiple_clean_files_commit_together(self, tmp_vault):
        before = commit_count(tmp_vault)
        (tmp_vault / "notes" / "a.md").write_text("clean a\n")
        (tmp_vault / "notes" / "b.md").write_text("clean b\n")
        git(["add", "notes/a.md", "notes/b.md"], cwd=tmp_vault)
        result = run(["git", "commit", "-m", "two clean files"], cwd=tmp_vault)
        assert result.returncode == 0
        assert commit_count(tmp_vault) == before + 1


# ---------------------------------------------------------------------------
# Integration test #3: pre-push remote allowlist
# DESIGN.md: 'Add a remote outside the allowlist, run git push against a local
# bare repo, assert rejection. Add an allowlisted remote, assert the push
# proceeds.'
#
# BLOCK 1 (Tier 0, docs/reviews/phase1-review-triage-2026-08-03.md): the
# pre-push hook read CAIRN_ALLOWED_REMOTE_PREFIXES from the environment AT
# PUSH TIME and let it fully replace the baked allowlist -- defeating
# doctor's re-render-and-compare pinning. DESIGN.md's "Development
# environment" section (fixed 2026-08-03): 'The allowlist is read from
# config at cairn init time and baked into the rendered pre-push hook;
# tests override it through that same config path.' The override belongs
# at cairn init / render time, not at push time.
# ---------------------------------------------------------------------------

class TestPrePushAllowlist:
    def test_push_to_non_allowlisted_remote_rejected(self, tmp_vault, tmp_path_factory):
        """
        A push to a remote URL not in the allowlist must be rejected by the
        pre-push hook.  We use a local bare repo as the push target.
        """
        bare = tmp_path_factory.mktemp("bare_disallow")
        subprocess.run(["git", "init", "--bare", str(bare)], check=True,
                       capture_output=True, env=os.environ.copy())

        # Add bare as a remote with a non-allowlisted URL.
        git(["remote", "add", "disallowed", str(bare)], cwd=tmp_vault)

        # Stage and commit a clean file so there is something to push.
        stage_and_commit(tmp_vault, "push_clean.md", "clean content\n")

        result = git(["push", "disallowed", "HEAD:refs/heads/main"], cwd=tmp_vault)
        assert result.returncode != 0, (
            "Push to non-allowlisted remote must be rejected by pre-push hook"
        )

    def test_push_to_allowlisted_remote_proceeds(self, tmp_path, tmp_path_factory):
        """
        A push to an allowlisted remote must succeed. The override happens
        at cairn init (render) time, per DESIGN.md's config-at-init path --
        NOT at push time. This bakes the bare repo's path into the
        pre-push hook's ALLOWLIST constant, then pushes with a CLEAN
        environment (no override at push time) to prove the baked value
        alone is what authorizes the push.
        """
        bare = tmp_path_factory.mktemp("bare_allow")
        subprocess.run(["git", "init", "--bare", str(bare)], check=True,
                       capture_output=True, env=os.environ.copy())

        vault = tmp_path / "vault"
        vault.mkdir()
        init_result = run(
            ["cairn", "init", str(vault)],
            extra_env={"CAIRN_ALLOWED_REMOTE_PREFIXES": str(bare)},
        )
        assert init_result.returncode == 0, (
            f"setup: cairn init with the test allowlist must succeed.\n"
            f"stderr: {init_result.stderr}"
        )

        git(["remote", "add", "allowed", str(bare)], cwd=vault)
        stage_and_commit(vault, "push_allow.md", "allow test\n")

        # No env override at push time: the baked allowlist alone must allow this.
        result = git(["push", "allowed", "HEAD:refs/heads/main"], cwd=vault)
        assert result.returncode == 0, (
            f"Push to a remote baked into the allowlist at cairn init time "
            f"must succeed with no further override.\nstderr: {result.stderr}"
        )

    def test_env_override_at_push_time_has_no_effect(self, tmp_vault, tmp_path_factory):
        """
        BLOCK 1 (Tier 0) negative control. tmp_vault was initialised with
        the DEFAULT allowlist (no env override at init time), so its
        pre-push hook has the CFG-INNERSOURCE prefixes baked in. Setting
        CAIRN_ALLOWED_REMOTE_PREFIXES at PUSH time to a permissive value
        must NOT change the rendered hook's behaviour: a rendered hook's
        enforcement is immutable at runtime by design (see DESIGN.md
        'Content pinning is re-render-and-compare, not a stored hash' --
        an env override that bypasses the bake defeats the very thing that
        comparison is meant to pin).
        """
        bare = tmp_path_factory.mktemp("bare_env_bypass")
        subprocess.run(["git", "init", "--bare", str(bare)], check=True,
                       capture_output=True, env=os.environ.copy())
        git(["remote", "add", "envbypass", str(bare)], cwd=tmp_vault)
        stage_and_commit(tmp_vault, "env_bypass.md", "clean content\n")

        result = run(
            ["git", "push", "envbypass", "HEAD:refs/heads/main"],
            cwd=tmp_vault,
            extra_env={"CAIRN_ALLOWED_REMOTE_PREFIXES": str(bare)},
        )
        assert result.returncode != 0, (
            "Setting CAIRN_ALLOWED_REMOTE_PREFIXES at push time must NOT "
            "override the baked allowlist (BLOCK 1). The rendered hook's "
            "enforcement must not be alterable by an environment variable "
            "at push time -- only by re-rendering via cairn init."
        )


# ---------------------------------------------------------------------------
# Integration test #4: doctor detects tampered hook; --fix restores
# DESIGN.md: 'Corrupt an installed hook by appending a byte; assert cairn doctor
# fails and names it; assert cairn doctor --fix restores it and doctor then passes.'
# ---------------------------------------------------------------------------

class TestDoctorHookTamperAndFix:
    def test_tampered_hook_fails_doctor(self, tmp_vault):
        hook = tmp_vault / ".git" / "hooks" / "pre-commit"
        hook.write_bytes(hook.read_bytes() + b"\n# appended byte\n")
        result = run(["cairn", "doctor"], cwd=tmp_vault)
        assert result.returncode != 0, "Tampered hook must fail doctor"
        combined = result.stdout + result.stderr
        assert "pre-commit" in combined, "Doctor must name the failing hook"

    def test_tampered_hook_fix_restores(self, tmp_vault):
        hook = tmp_vault / ".git" / "hooks" / "pre-commit"
        hook.write_bytes(hook.read_bytes() + b"\n# appended byte\n")
        run(["cairn", "doctor", "--fix"], cwd=tmp_vault)
        result = run(["cairn", "doctor"], cwd=tmp_vault)
        assert result.returncode == 0, "Doctor must pass after --fix restores hook"

    def test_fix_restores_executable_mode(self, tmp_vault):
        """--fix must also restore mode 0755 if it was wrong."""
        hook = tmp_vault / ".git" / "hooks" / "pre-commit"
        hook.chmod(0o644)
        run(["cairn", "doctor", "--fix"], cwd=tmp_vault)
        mode = stat.S_IMODE(hook.stat().st_mode)
        assert mode == 0o755, f"--fix must restore mode 0755, got {oct(mode)}"


# ---------------------------------------------------------------------------
# Integration test #5: deleted hook; doctor fails; --fix reinstalls
# DESIGN.md: 'Delete .git/hooks/pre-commit; assert doctor fails and --fix reinstalls.'
# ---------------------------------------------------------------------------

class TestDoctorMissingHook:
    def test_delete_pre_commit_fails_doctor(self, tmp_vault):
        (tmp_vault / ".git" / "hooks" / "pre-commit").unlink()
        result = run(["cairn", "doctor"], cwd=tmp_vault)
        assert result.returncode != 0

    def test_delete_pre_push_fails_doctor(self, tmp_vault):
        (tmp_vault / ".git" / "hooks" / "pre-push").unlink()
        result = run(["cairn", "doctor"], cwd=tmp_vault)
        assert result.returncode != 0

    def test_fix_after_delete_reinstalls(self, tmp_vault):
        (tmp_vault / ".git" / "hooks" / "pre-commit").unlink()
        run(["cairn", "doctor", "--fix"], cwd=tmp_vault)
        hook = tmp_vault / ".git" / "hooks" / "pre-commit"
        assert hook.exists()
        assert stat.S_IMODE(hook.stat().st_mode) == 0o755

    def test_after_fix_commit_is_functional(self, tmp_vault):
        """After --fix, the hook must actually work (not just be present)."""
        (tmp_vault / ".git" / "hooks" / "pre-commit").unlink()
        run(["cairn", "doctor", "--fix"], cwd=tmp_vault)
        # Clean commit must succeed.
        before = commit_count(tmp_vault)
        result = stage_and_commit(tmp_vault, "after_fix.md", "clean content\n")
        assert result.returncode == 0
        assert commit_count(tmp_vault) == before + 1


# ---------------------------------------------------------------------------
# Integration test #6: scan source byte-identity
# DESIGN.md: 'Render both hooks and assert the inlined scan source is
# byte-identical to src/cairn/scan.py.'
# ---------------------------------------------------------------------------

class TestScanSourceByteIdentity:
    def test_pre_commit_inlined_scan_matches_scan_py(self, tmp_vault):
        import cairn.scan as scan_mod
        scan_src = Path(scan_mod.__file__).read_text()

        hook_text = (tmp_vault / ".git" / "hooks" / "pre-commit").read_text()
        begin = "# --- BEGIN CAIRN SCAN (generated, do not edit) ---"
        end = "# --- END CAIRN SCAN ---"

        assert begin in hook_text
        assert end in hook_text

        start = hook_text.index(begin) + len(begin)
        # skip the newline right after the sentinel
        if hook_text[start] == "\n":
            start += 1
        end_idx = hook_text.index(end)
        inlined = hook_text[start:end_idx]

        assert inlined == scan_src, (
            "Inlined scan source in pre-commit hook must be byte-identical to scan.py.\n"
            f"First diff at char {next((i for i, (a, b) in enumerate(zip(inlined, scan_src)) if a != b), len(inlined))}"
        )


# ---------------------------------------------------------------------------
# Integration test #7: stdlib-only import
# DESIGN.md: 'Import src/cairn/scan.py with the rest of the package removed
# from sys.path and assert it imports and runs.'
# ---------------------------------------------------------------------------

class TestScanStdlibOnlyViaHook:
    def test_scan_py_imports_without_cairn_package(self):
        """
        Import scan.py in complete isolation from the cairn package.
        Any non-stdlib import inside scan.py will raise ImportError here.
        This enforces the constraint the whole hook design rests on.
        """
        import importlib.util
        import sys
        import cairn.scan as scan_mod
        scan_file = Path(scan_mod.__file__).resolve()

        saved_path = sys.path[:]
        saved_modules = {k: v for k, v in sys.modules.items()}

        # Only include scan.py's own directory, not the cairn package parent.
        sys.path = [str(scan_file.parent)]
        for key in list(sys.modules.keys()):
            if key.startswith("cairn"):
                del sys.modules[key]

        try:
            spec = importlib.util.spec_from_file_location("_scan_isolated", scan_file)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            # Must be callable and return a list.
            result = mod.scan_bytes(b"hello", "f.md")
            assert isinstance(result, list)
        finally:
            sys.path = saved_path
            sys.modules.update(saved_modules)

    def test_hook_check_version_line_present(self, tmp_vault):
        """
        DESIGN.md: 'The hook checks sys.version_info >= (3, 8) and exits with
        a clear message otherwise.'
        The pre-commit hook must contain a version check.
        """
        hook_text = (tmp_vault / ".git" / "hooks" / "pre-commit").read_text()
        assert "sys.version_info" in hook_text or "version_info" in hook_text, (
            "pre-commit hook must contain a Python version check"
        )
        assert "(3, 8)" in hook_text or "3, 8" in hook_text, (
            "Version check floor must be (3, 8) per DESIGN.md"
        )


# ---------------------------------------------------------------------------
# Integration test #8: --no-verify commits a secret
# DESIGN.md: 'Run a commit with --no-verify containing a secret, assert it
# succeeds (documenting the known hole).' The bounded history scan half of
# this test ('doctor --scan-history reports it') is v2, deferred -- see
# TODO.md 'Deferred scan features (v2)'. BLOCK 4
# (docs/reviews/phase1-review-triage-2026-08-03.md): the old
# test_doctor_scan_history_reports_bypassed_secret was vacuous (asserted
# "warn" appears anywhere in doctor's output, which is always true because
# of the unrelated ~/.local/bin-not-on-PATH warning) and has been removed,
# along with test_doctor_scan_history_flag_widens_depth, which asserted a
# v2 CLI surface. Do not re-add a v1 test for the history scan; if it is
# reintroduced, re-derive it from a NON-VACUOUS assertion (specific finding
# content only the history scan could have produced) plus a negative
# control (a clean-history vault that must NOT warn).
# ---------------------------------------------------------------------------

class TestNoVerifyBypass:
    AWS_SYNTHETIC = "AKIAIOSFODNN7EXAMPLE"

    def test_no_verify_commit_succeeds(self, tmp_vault):
        """
        DESIGN.md acknowledges --no-verify as a known bypass.
        The commit must succeed (this is not a bug, it is documented behaviour).
        """
        before = commit_count(tmp_vault)
        result = stage_and_commit(
            tmp_vault, "noverify_secret.md",
            f"key = {self.AWS_SYNTHETIC}\n",
            no_verify=True,
        )
        assert result.returncode == 0, (
            "git commit --no-verify must succeed even with a secret (known bypass)"
        )
        assert commit_count(tmp_vault) == before + 1


# ---------------------------------------------------------------------------
# Additional: asset size cap in pre-commit hook
# ---------------------------------------------------------------------------

class TestAssetSizeCap:
    def test_oversized_asset_blocks_commit(self, tmp_vault):
        """
        DESIGN.md: 'Checks that no staged file under assets/ exceeds the size cap
        (default: 1 MB).'
        """
        big_file = tmp_vault / "assets" / "big.pdf"
        big_file.write_bytes(b"x" * (1024 * 1024 + 1))  # 1 MB + 1 byte
        git(["add", "assets/big.pdf"], cwd=tmp_vault)
        result = run(["git", "commit", "-m", "oversized asset"], cwd=tmp_vault)
        assert result.returncode != 0, (
            "Pre-commit hook must reject assets exceeding the 1 MB size cap"
        )

    def test_asset_within_size_cap_passes(self, tmp_vault):
        """An asset under the 1 MB cap must not be blocked."""
        small_file = tmp_vault / "assets" / "small.pdf"
        small_file.write_bytes(b"x" * 1024)  # 1 KB
        git(["add", "assets/small.pdf"], cwd=tmp_vault)
        result = run(["git", "commit", "-m", "small asset"], cwd=tmp_vault)
        assert result.returncode == 0, (
            f"Small asset must not be blocked.\nstderr: {result.stderr}"
        )


# ---------------------------------------------------------------------------
# RAISE fix: deleting an oversized asset must not be blocked by the size cap
# (docs/reviews/phase1-review-triage-2026-08-03.md, "Worth fixing in the
# same round"): 'git show :<path> on a staged deletion returns the OLD
# blob, so the cap fires and the user cannot delete a large asset without
# --no-verify. Needs a deletion carve-out via --diff-filter=D.'
#
# Reproduced by hand against the current pre-commit hook: get_staged_content
# uses `git show :<path>` with check=True, and for a staged DELETION that
# path no longer exists in the index at all, so git show exits 128 and the
# hook CRASHES with an uncaught CalledProcessError (not merely "fires on
# the old blob" as literally described) -- confirmed for BOTH an oversized
# asset deletion and a plain clean-file deletion. The observable effect the
# user sees is the same either way: a deletion commit that should succeed
# is blocked. Both cases are pinned below.
# ---------------------------------------------------------------------------

class TestAssetDeletionCarveOut:
    def test_deleting_oversized_asset_is_not_blocked_by_size_cap(self, tmp_vault):
        big = tmp_vault / "assets" / "big_to_delete.pdf"
        big.write_bytes(b"x" * (1024 * 1024 + 1))
        git(["add", "assets/big_to_delete.pdf"], cwd=tmp_vault)
        # Seed the oversized asset into history via --no-verify. This is the
        # only way Phase 1 can get an oversized non-local asset committed at
        # all, since the hook blocks it on ADD; it documents a pre-existing
        # commit (e.g. from before the cap existed, or a fresh clone of a
        # history that already has one), not a normal Phase 1 workflow.
        seed = run(["git", "commit", "--no-verify", "-m", "seed oversized asset"], cwd=tmp_vault)
        assert seed.returncode == 0, "setup: seeding the oversized asset must succeed"

        git(["rm", "assets/big_to_delete.pdf"], cwd=tmp_vault)
        result = run(["git", "commit", "-m", "delete oversized asset"], cwd=tmp_vault)
        assert result.returncode == 0, (
            f"Deleting an oversized asset must NOT be blocked by the size cap "
            f"(the file is leaving the repo, not entering it).\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_deleting_a_clean_tracked_file_does_not_crash_the_hook(self, tmp_vault):
        """
        Broader case discovered while validating the asset-deletion carve-
        out: get_staged_content's `git show :<path>` (check=True) is called
        for EVERY staged path, so staging a deletion of ANY tracked file --
        not only an oversized asset -- currently crashes the pre-commit
        hook with an unhandled CalledProcessError. A vault where deleting a
        plain note crashes the safety hook is a worse outcome than the
        oversized-asset case alone; pin the general property too.
        """
        note = tmp_vault / "notes" / "to_delete.md"
        note.write_text("clean content, nothing to scan\n")
        git(["add", "notes/to_delete.md"], cwd=tmp_vault)
        seed = run(["git", "commit", "-m", "add note"], cwd=tmp_vault)
        assert seed.returncode == 0, "setup: adding the note must succeed"

        git(["rm", "notes/to_delete.md"], cwd=tmp_vault)
        result = run(["git", "commit", "-m", "delete note"], cwd=tmp_vault)
        assert result.returncode == 0, (
            f"Deleting a clean tracked file must not crash or be blocked by "
            f"the pre-commit hook.\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "CalledProcessError" not in (result.stdout + result.stderr), (
            "The hook must not crash with an unhandled subprocess error on "
            "a staged deletion"
        )
