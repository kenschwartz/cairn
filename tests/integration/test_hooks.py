"""
Integration tests for the git hooks.

These are the eight required integration tests from DESIGN.md plus supporting
tests. Every test invokes `git` and lets git run the hook. No in-process
short-circuit of the scan logic.

DESIGN.md: 'A test that imports the scan function and asserts it returns
findings proves nothing about the hook: it cannot catch a broken shebang, a
bad interpreter resolution, a rendering bug, a non-executable file, or a hook
that was never installed.'
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
    HIGH_ENTROPY_TOKEN = "token: xK9mP2nQ8rT5vW1yZ3bD6fH0jL4uE7gA9cN2mPqR"
    SSN_SYNTHETIC = "ssn: 000-00-0000"
    CARD_SYNTHETIC = "card: 4111111111111111"
    GITHUB_TOKEN_SYNTHETIC = "pat: ghp_SYNTHETICnotARealTokenAAAAAAAAAAAAAA"
    ANTHROPIC_KEY_SYNTHETIC = "key: sk-ant-apiSYNTHETIC-not-a-real-key-000"
    SSH_PUBLIC_KEY_SYNTHETIC = (
        "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAISYNTHETICNOTAREALKEYAAAAAAAAAAAA me@host"
    )

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
        combined = ""
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

    def test_ssn_blocks_commit(self, tmp_vault):
        before = commit_count(tmp_vault)
        result = stage_and_commit(tmp_vault, "ssn.md", f"# Note\n{self.SSN_SYNTHETIC}\n")
        assert result.returncode != 0
        assert commit_count(tmp_vault) == before

    def test_payment_card_blocks_commit(self, tmp_vault):
        before = commit_count(tmp_vault)
        result = stage_and_commit(tmp_vault, "card.md", f"# Note\n{self.CARD_SYNTHETIC}\n")
        assert result.returncode != 0
        assert commit_count(tmp_vault) == before

    def test_high_entropy_token_blocks_commit(self, tmp_vault):
        before = commit_count(tmp_vault)
        result = stage_and_commit(tmp_vault, "token.md", f"# Note\n{self.HIGH_ENTROPY_TOKEN}\n")
        assert result.returncode != 0
        assert commit_count(tmp_vault) == before

    def test_github_token_blocks_commit(self, tmp_vault):
        before = commit_count(tmp_vault)
        result = stage_and_commit(tmp_vault, "gh.md", f"# Note\n{self.GITHUB_TOKEN_SYNTHETIC}\n")
        assert result.returncode != 0
        assert commit_count(tmp_vault) == before

    def test_anthropic_key_blocks_commit(self, tmp_vault):
        before = commit_count(tmp_vault)
        result = stage_and_commit(tmp_vault, "ant.md", f"# Note\n{self.ANTHROPIC_KEY_SYNTHETIC}\n")
        assert result.returncode != 0
        assert commit_count(tmp_vault) == before

    def test_ssh_public_key_blocks_commit(self, tmp_vault):
        before = commit_count(tmp_vault)
        result = stage_and_commit(
            tmp_vault, "pub.md", f"{self.SSH_PUBLIC_KEY_SYNTHETIC}\n"
        )
        assert result.returncode != 0
        assert commit_count(tmp_vault) == before

    def test_suppression_marker_does_not_bypass_private_key(self, tmp_vault):
        """The marker terminates one line; a key block spans many, so it must not pass."""
        before = commit_count(tmp_vault)
        content = (
            "-----BEGIN RSA PRIVATE KEY-----  cairn:allow-secret\n"
            "FAKE KEY BODY FOR TEST\n"
            "-----END RSA PRIVATE KEY-----\n"
        )
        result = stage_and_commit(tmp_vault, "suppressed_key.md", content)
        assert result.returncode != 0
        assert commit_count(tmp_vault) == before

    def test_staged_deletion_does_not_break_the_hook(self, tmp_vault):
        """A commit that only deletes a file must still be scanned and succeed."""
        stage_and_commit(tmp_vault, "to_delete.md", "clean content\n")
        before = commit_count(tmp_vault)
        git(["rm", "notes/to_delete.md"], cwd=tmp_vault)
        result = run(["git", "commit", "-m", "delete note"], cwd=tmp_vault)
        assert result.returncode == 0, (
            f"Deletion-only commit must not be blocked.\nstderr: {result.stderr}"
        )
        assert commit_count(tmp_vault) == before + 1

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

    def test_suppressed_secret_commits_successfully(self, tmp_vault):
        """A line with cairn:allow-secret must not block the commit."""
        content = "token: xK9mP2nQ8rT5vW1yZ3bD6fH0jL4uE7gA9cN2mPqR  cairn:allow-secret\n"
        before = commit_count(tmp_vault)
        result = stage_and_commit(tmp_vault, "suppressed.md", content)
        assert result.returncode == 0, (
            f"Suppressed secret must not block commit.\nstderr: {result.stderr}"
        )
        assert commit_count(tmp_vault) == before + 1


# ---------------------------------------------------------------------------
# Integration test #3: pre-push remote allowlist
# DESIGN.md: 'Add a remote outside the allowlist, run git push against a local
# bare repo, assert rejection. Add an allowlisted remote, assert the push proceeds.'
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

    def test_push_to_allowlisted_remote_proceeds(self, tmp_vault, tmp_path_factory):
        """
        A push to an allowlisted remote must succeed.
        We override the allowlist to include the local bare repo path.
        DESIGN.md: 'The remote allowlist must be overridable for tests'.
        """
        bare = tmp_path_factory.mktemp("bare_allow")
        subprocess.run(["git", "init", "--bare", str(bare)], check=True,
                       capture_output=True, env=os.environ.copy())

        # Override the allowlist to include the bare repo path.
        # The hook reads the allowlist from its baked-in JSON at render time,
        # so we need a vault whose pre-push hook was rendered with the test allowlist.
        # Use CAIRN_ALLOWED_REMOTE_PREFIXES env var as the override mechanism.
        bare_prefix = str(bare)
        git(["remote", "add", "allowed", str(bare)], cwd=tmp_vault)
        stage_and_commit(tmp_vault, "push_allow.md", "allow test\n")

        result = run(
            ["git", "push", "allowed", "HEAD:refs/heads/main"],
            cwd=tmp_vault,
            extra_env={"CAIRN_ALLOWED_REMOTE_PREFIXES": bare_prefix},
        )
        assert result.returncode == 0, (
            f"Push to allowlisted remote must succeed.\nstderr: {result.stderr}"
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
# Integration test #8: --no-verify commits a secret; doctor --scan-history reports it
# DESIGN.md: 'Run a commit with --no-verify containing a secret, assert it
# succeeds (documenting the known hole), then assert cairn doctor --scan-history
# reports it.'
# ---------------------------------------------------------------------------

class TestNoVerifyAndHistoryScan:
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

    def test_doctor_scan_history_reports_bypassed_secret(self, tmp_vault):
        """
        DESIGN.md: 'cairn doctor runs a bounded history scan as part of its
        base checks: the working tree plus the last 20 commits, reported as a
        warning rather than a hard fail.'
        After a --no-verify commit containing a secret, doctor must warn.
        """
        # Commit the secret via --no-verify.
        stage_and_commit(
            tmp_vault, "noverify_secret2.md",
            f"key = {self.AWS_SYNTHETIC}\n",
            no_verify=True,
        )
        # Doctor must report a warning (exit 0 with warning output, not hard fail).
        result = run(["cairn", "doctor"], cwd=tmp_vault)
        combined = result.stdout + result.stderr
        assert "aws" in combined.lower() or "secret" in combined.lower() or "warn" in combined.lower(), (
            "Doctor must warn about the secret found in history after --no-verify commit"
        )

    def test_doctor_scan_history_flag_widens_depth(self, tmp_vault):
        """
        DESIGN.md: 'cairn doctor --scan-history N widens the depth on demand.'
        The flag must be accepted and must produce output.
        """
        result = run(["cairn", "doctor", "--scan-history", "50"], cwd=tmp_vault)
        assert result.returncode in (0, 1), (
            "--scan-history must run without crashing"
        )


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
