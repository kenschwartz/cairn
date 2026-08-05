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
import shutil
import stat
import subprocess
import textwrap
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


def make_failing_git_stub(tmp_path_factory, fail_subcommand: str) -> Path:
    """
    Build a directory containing a `git` script that transparently execs
    the REAL git for every subcommand EXCEPT `fail_subcommand`, which it
    fails immediately with a distinctive nonzero exit and stderr message.
    This is a genuine subprocess-level fault injection -- not a mock of
    the hook, not a monkeypatch of scan_bytes. The hook under test still
    runs as a real subprocess and really shells out to `git`; only that
    one specific git subcommand is made to fail.

    Mechanism note (verified by hand, not assumed): a plain PATH-prepend
    is NOT sufficient to intercept a hook's internal `git` calls, because
    git itself prepends its own git-core exec directory to PATH before
    invoking hooks (confirmed by dumping $PATH from inside a hand-written
    test hook: the real git-core path appears ahead of anything the
    invoking shell had on PATH). Setting GIT_EXEC_PATH to this stub
    directory (in addition to prepending it to PATH) is what makes git
    place the stub ahead of its own git-core directory, so the hook's
    internal `subprocess.run(["git", ...])` calls actually resolve to the
    stub. Callers must pass BOTH `GIT_EXEC_PATH` and a PATH with this
    directory prepended as extra_env on the outer `git` invocation that
    triggers the hook.
    """
    real_git = shutil.which("git")
    assert real_git, "setup: a real git must be resolvable on PATH to build the stub"
    stub_dir = tmp_path_factory.mktemp("git_stub")
    stub = stub_dir / "git"
    stub.write_text(textwrap.dedent(f"""\
        #!/bin/sh
        if [ "$1" = "{fail_subcommand}" ]; then
            echo "INJECTED-TEST-FAILURE: {fail_subcommand} stubbed to fail" >&2
            exit 111
        fi
        exec "{real_git}" "$@"
        """))
    stub.chmod(0o755)
    return stub_dir


def stub_env(stub_dir: Path) -> dict:
    """extra_env that makes git prefer the stub over its own git-core."""
    return {
        "GIT_EXEC_PATH": str(stub_dir),
        "PATH": f"{stub_dir}{os.pathsep}{os.environ.get('PATH', '')}",
    }


def write_allowlist_config(config_home: Path, prefixes) -> None:
    """
    Write a minimal `<config_home>/cairn/config.toml` with a [remote]
    allowed_prefixes list, matching DESIGN.md's config source exactly:
    '~/.config/cairn/config.toml' under '[remote] allowed_prefixes', with
    the '~/.config' segment resolved via $XDG_CONFIG_HOME when set --
    'which is also the seam the test suite uses to inject a temporary
    config; the runtime environment carries no allowlist values of its
    own.' Callers point XDG_CONFIG_HOME at config_home for the `cairn
    init` call only, so the allowlist is baked at render time through the
    real config path, never through an environment variable.
    """
    cairn_dir = config_home / "cairn"
    cairn_dir.mkdir(parents=True, exist_ok=True)
    lines = ["[remote]", "allowed_prefixes = ["]
    for p in prefixes:
        lines.append(f'  "{p}",')
    lines.append("]")
    (cairn_dir / "config.toml").write_text("\n".join(lines) + "\n")


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
    ANTHROPIC_KEY_SYNTHETIC = "sk-ant-api03-EXAMPLE0000000000"

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

    def test_anthropic_key_blocks_commit(self, tmp_vault):
        """
        (spec-QA review, RAISE, accepted): mirrors test_github_token_blocks_commit
        for the other v1 rule the old gate lacked. Verified by hand first
        (not assumed): `scan_bytes(b"key = sk-ant-api03-EXAMPLE0000000000",
        "f.md")` returns `[]` against the current scan.py -- no rule fires
        at all for this line today (not even the stale labelled_token
        rule, since a bare 'key' label is not one of its recognized
        labels), so this is a clean red proof with no wrong-reason-pass
        risk.
        """
        before = commit_count(tmp_vault)
        result = stage_and_commit(
            tmp_vault, "anthropic_key.md",
            f"# Note\n\nkey = {self.ANTHROPIC_KEY_SYNTHETIC}\n"
        )
        assert result.returncode != 0, (
            "Commit containing synthetic Anthropic API key must be blocked by pre-commit hook"
        )
        assert commit_count(tmp_vault) == before
        combined = result.stdout + result.stderr
        assert "anthropic_api_key" in combined, (
            f"Commit must be blocked specifically by the anthropic_api_key "
            f"rule, not merely by some other rule that happens to also "
            f"match. Got: {combined!r}"
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
# doctor's re-render-and-compare pinning.
#
# DESIGN.md "Remote allowlist" / "Config source" (amended after a
# spec-QA review, BLOCK, confirmed the earlier version of this section
# was still wrong): 'the allowlist lives at ~/.config/cairn/config.toml
# under [remote] allowed_prefixes ... The ~/.config segment is resolved
# via $XDG_CONFIG_HOME when set (standard XDG behavior), which is also
# the seam the test suite uses to inject a temporary config; the runtime
# environment carries no allowlist values of its own.' The override
# belongs in a CONFIG FILE read at cairn init (render) time -- not in any
# environment variable, at init time OR push time.
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
        at cairn init (render) time, through the CONFIG FILE, per
        DESIGN.md's config source. This writes a temp config.toml naming
        the bare repo's path under [remote] allowed_prefixes, points
        XDG_CONFIG_HOME at it ONLY for the cairn init call (so the
        allowlist gets baked into the pre-push hook through the real
        config path), then pushes with a completely clean environment --
        no XDG_CONFIG_HOME, no CAIRN_ALLOWED_REMOTE_PREFIXES anywhere --
        to prove the baked value alone is what authorizes the push.
        """
        bare = tmp_path_factory.mktemp("bare_allow")
        subprocess.run(["git", "init", "--bare", str(bare)], check=True,
                       capture_output=True, env=os.environ.copy())

        config_home = tmp_path_factory.mktemp("xdg_config_allow")
        write_allowlist_config(config_home, [str(bare)])

        vault = tmp_path / "vault"
        vault.mkdir()
        init_result = run(
            ["cairn", "init", str(vault)],
            extra_env={"XDG_CONFIG_HOME": str(config_home)},
        )
        assert init_result.returncode == 0, (
            f"setup: cairn init with the test config.toml must succeed.\n"
            f"stderr: {init_result.stderr}"
        )

        git(["remote", "add", "allowed", str(bare)], cwd=vault)
        stage_and_commit(vault, "push_allow.md", "allow test\n")

        # No XDG_CONFIG_HOME, no env override at push time: the allowlist
        # baked via config.toml at init time alone must allow this.
        result = git(["push", "allowed", "HEAD:refs/heads/main"], cwd=vault)
        assert result.returncode == 0, (
            f"Push to a remote baked into the allowlist via config.toml at "
            f"cairn init time must succeed with no further override.\n"
            f"stderr: {result.stderr}"
        )

    def test_env_override_at_push_time_has_no_effect(self, tmp_vault, tmp_path_factory):
        """
        BLOCK 1 (Tier 0) negative control. tmp_vault was initialised with
        the DEFAULT allowlist (no config.toml, no env override at init
        time), so its pre-push hook has the CFG-INNERSOURCE prefixes
        baked in. Setting CAIRN_ALLOWED_REMOTE_PREFIXES at PUSH time to a
        permissive value must NOT change the rendered hook's behaviour:
        per DESIGN.md, 'the runtime environment carries no allowlist
        values of its own' -- not at push time, not ever.
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
            "at push time -- only by re-rendering via cairn init with a "
            "different config.toml."
        )

    def test_env_override_at_init_time_has_no_effect(self, tmp_path, tmp_path_factory):
        """
        (spec-QA review, BLOCK, item 4 addition) The init-time negative
        control DESIGN.md's config-source rewrite requires: 'the runtime
        environment carries no allowlist values of its own.'
        CAIRN_ALLOWED_REMOTE_PREFIXES set during `cairn init` must NOT
        influence the baked allowlist at all -- only config.toml
        (resolved via XDG_CONFIG_HOME) may. A vault initialised with the
        env var set to a permissive value, and NO config.toml, must still
        bake the DEFAULT (CFG-INNERSOURCE-only) allowlist, so a push to
        the env-named remote must still be rejected.
        """
        bare = tmp_path_factory.mktemp("bare_init_env_bypass")
        subprocess.run(["git", "init", "--bare", str(bare)], check=True,
                       capture_output=True, env=os.environ.copy())

        vault = tmp_path / "vault"
        vault.mkdir()
        init_result = run(
            ["cairn", "init", str(vault)],
            extra_env={"CAIRN_ALLOWED_REMOTE_PREFIXES": str(bare)},
        )
        assert init_result.returncode == 0, (
            f"setup: cairn init must succeed even with the env var set "
            f"(it must simply be ignored, not error).\n"
            f"stderr: {init_result.stderr}"
        )

        git(["remote", "add", "initenvbypass", str(bare)], cwd=vault)
        stage_and_commit(vault, "init_env_bypass.md", "clean content\n")

        result = git(["push", "initenvbypass", "HEAD:refs/heads/main"], cwd=vault)
        assert result.returncode != 0, (
            "CAIRN_ALLOWED_REMOTE_PREFIXES set during cairn init must NOT "
            "influence the baked allowlist -- only config.toml may. The "
            "push must still be rejected because no config.toml granted "
            "this remote."
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
# RAISE fix, now also codified directly in DESIGN.md "Scan input" (amended):
# 'Staged deletions are exempt from the scan and from the asset size cap:
# a path staged for deletion (`git diff --cached --name-only
# --diff-filter=D`) has no new content to scan, `git show :<path>` on it
# raises, and blocking the deletion of an oversized asset would trap the
# user with no way to remove it. The exemption is deletion-only; a read
# failure on any path NOT staged for deletion stays fail-closed and blocks
# the commit.' That last sentence is exactly what
# TestFailClosedOnUnexpectedHookErrors (below) pins on the non-deletion
# side.
#
# Reproduced by hand against the current pre-commit hook: get_staged_content
# uses `git show :<path>` with check=True, and for a staged DELETION that
# path no longer exists in the index at all, so git show exits 128 and the
# hook CRASHES with an uncaught CalledProcessError (not merely "fires on
# the old blob" as originally described in the review triage) -- confirmed
# for BOTH an oversized asset deletion and a plain clean-file deletion. The
# observable effect the user sees is the same either way: a deletion
# commit that should succeed is blocked. Both cases are pinned below.
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


# ---------------------------------------------------------------------------
# (spec-QA review, convergent BLOCK): fail-closed on unexpected hook errors
# was untested anywhere. DESIGN.md "Scan input" (amended): 'The exemption
# is deletion-only; a read failure on any path NOT staged for deletion
# stays fail-closed and blocks the commit.' These are real subprocess-level
# injections via a PATH + GIT_EXEC_PATH-stubbed `git` (see
# make_failing_git_stub above for why a plain PATH-prepend does not work)
# -- NOT a mock of the hook itself. The stub transparently execs the real
# git for every subcommand except the one under test, which it fails
# immediately with a distinctive message.
# ---------------------------------------------------------------------------

class TestFailClosedOnUnexpectedHookErrors:
    def test_pre_commit_blocks_when_internal_git_show_fails(self, tmp_vault, tmp_path_factory):
        """
        get_staged_content() in the rendered pre-commit hook shells out to
        `git show :<path>` for every NON-deleted staged file's content.
        If that call fails unexpectedly (stubbed here) on a path that is
        NOT staged for deletion, the commit must be BLOCKED, not silently
        treated as "no findings, proceed".

        Currently GREEN: get_staged_content uses subprocess.run(...,
        check=True), so a failed `git show` raises CalledProcessError,
        which is uncaught, which crashes the hook with a nonzero exit --
        git then aborts the commit (verified by hand with this exact
        stub mechanism before writing this assertion; the crash surfaces
        as a Python traceback ending in
        'subprocess.CalledProcessError: ... git show ... returned
        non-zero exit status 111', the injected code). This test WOULD
        FAIL if a future change wrapped that call in a try/except that
        swallowed the error and returned empty/no-findings instead of
        re-raising or exiting non-zero -- a "fail open on error"
        regression that DESIGN.md's amended "Scan input" section now
        explicitly forbids outside the deletion carve-out.
        """
        stub_dir = make_failing_git_stub(tmp_path_factory, fail_subcommand="show")

        (tmp_vault / "notes" / "inject_show.md").write_text("clean content, nothing to scan\n")
        git(["add", "notes/inject_show.md"], cwd=tmp_vault)

        before = commit_count(tmp_vault)
        result = run(
            ["git", "commit", "-m", "inject show failure"],
            cwd=tmp_vault,
            extra_env=stub_env(stub_dir),
        )
        assert result.returncode != 0, (
            f"An unexpected internal git failure inside the pre-commit "
            f"hook must BLOCK the commit, never wave it through.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert commit_count(tmp_vault) == before, (
            "No commit must be created when the hook fails unexpectedly"
        )

    def test_pre_commit_injection_actually_reached_the_hook(self, tmp_vault, tmp_path_factory):
        """
        Guards against the injection silently no-op'ing (e.g. if a future
        git version changes how it exposes git-core to hooks and the stub
        stops being consulted): the DISTINCTIVE injected exit code (111,
        not a code any real git error would coincidentally produce) must
        appear in the crash output. Without this, a broken stub and a
        genuinely fixed hook would look identical (both green).

        FIXTURE VALIDATION CATCH: an earlier version of this test asserted
        the stub's stderr TEXT ("INJECTED-TEST-FAILURE") appears in the
        commit output, and that assertion was WRONG -- verified by hand.
        get_staged_content calls `subprocess.run(..., capture_output=True,
        check=True)` (no `text=True`); the stub's stderr IS captured into
        the resulting CalledProcessError's `.stderr` attribute, but
        nothing in the hook ever prints that attribute before the
        exception propagates and Python's default traceback handler takes
        over -- the traceback shows the command and exit code, not the
        captured output. The actually-visible, actually-distinctive
        signal is the exit code itself: the traceback ends with
        'returned non-zero exit status 111'.
        """
        stub_dir = make_failing_git_stub(tmp_path_factory, fail_subcommand="show")
        (tmp_vault / "notes" / "inject_show2.md").write_text("clean content\n")
        git(["add", "notes/inject_show2.md"], cwd=tmp_vault)

        result = run(
            ["git", "commit", "-m", "inject show failure 2"],
            cwd=tmp_vault,
            extra_env=stub_env(stub_dir),
        )
        combined = result.stdout + result.stderr
        assert "111" in combined, (
            f"The stub's distinctive injected exit code (111) must "
            f"actually reach the crash output; if it never appears, this "
            f"test proves nothing about fail-closed behaviour (it might "
            f"be passing because the commit failed for some unrelated "
            f"reason). Got: {combined!r}"
        )

    def test_pre_push_reject_unaffected_by_internal_remote_lookup_failure(
        self, tmp_vault, tmp_path_factory
    ):
        """
        The rendered pre-push hook shells out to `git remote get-url
        <name>` (no check=True) as a best-effort enrichment step ONLY
        when the URL git already handed it as argv[2] doesn't look like a
        URL (e.g. a local bare-repo filesystem path, which is exactly
        what this test suite's local push targets are). Verified by hand:
        stubbing `remote` to fail does NOT change the outcome for a
        non-allowlisted push, because remote_url already holds the
        correct value from argv[2] and the code only OVERWRITES it on
        subprocess success (`if result.returncode == 0: remote_url =
        ...`), never on failure. This is a genuinely safe-by-construction
        path, not a fault we can trigger with this seam -- included as a
        confirming regression pin, not a red proof. It WOULD fail if the
        hook were changed to require `git remote get-url` to succeed
        before evaluating the allowlist (e.g. `remote_url =
        result.stdout.strip()` unconditionally, dropping the argv[2]
        fallback), which would make the reject path SILENTLY DEPEND on an
        optional subprocess.
        """
        stub_dir = make_failing_git_stub(tmp_path_factory, fail_subcommand="remote")
        bare = tmp_path_factory.mktemp("bare_pp_inject_reject")
        subprocess.run(["git", "init", "--bare", str(bare)], check=True,
                       capture_output=True, env=os.environ.copy())
        git(["remote", "add", "disallowed", str(bare)], cwd=tmp_vault)
        stage_and_commit(tmp_vault, "pp_inject_reject.md", "clean content\n")

        result = run(
            ["git", "push", "disallowed", "HEAD:refs/heads/main"],
            cwd=tmp_vault,
            extra_env=stub_env(stub_dir),
        )
        assert result.returncode != 0, (
            "A push to a non-allowlisted remote must still be rejected "
            "even when the hook's internal 'git remote get-url' "
            "enrichment call fails"
        )

    def test_pre_push_allow_unaffected_by_internal_remote_lookup_failure(
        self, tmp_path, tmp_path_factory
    ):
        """
        The other direction of the same confirming pin: a push to a
        remote that genuinely IS allowlisted (baked via config.toml at
        cairn init time, per DESIGN.md's config source) must still
        succeed even when the enrichment subprocess fails, because
        argv[2] already carried the correct, already-allowlisted URL.

        ENTANGLED WITH ITEM 4, NOT ITEM 2 (documented honestly, not
        mis-predicted): this test necessarily depends on config.toml
        actually being able to bake an allowlist entry at all, which is
        item 4's still-open gap (current code has no config.toml support
        and ignores it). So THIS specific test is currently RED, but for
        item 4's reason (the push is rejected because the remote was
        never actually allowlisted), not because the fault injection
        broke anything. Once item 4 lands, this test starts exercising
        what it is actually meant to prove: that the ALLOW outcome
        specifically is unaffected by the enrichment subprocess failing.
        The REJECT-side sibling test above is not entangled with item 4
        and is a clean, already-green confirming pin today.
        """
        stub_dir = make_failing_git_stub(tmp_path_factory, fail_subcommand="remote")
        bare = tmp_path_factory.mktemp("bare_pp_inject_allow")
        subprocess.run(["git", "init", "--bare", str(bare)], check=True,
                       capture_output=True, env=os.environ.copy())

        config_home = tmp_path_factory.mktemp("xdg_config_pp_inject")
        write_allowlist_config(config_home, [str(bare)])

        vault = tmp_path / "vault"
        vault.mkdir()
        init_result = run(
            ["cairn", "init", str(vault)],
            extra_env={"XDG_CONFIG_HOME": str(config_home)},
        )
        assert init_result.returncode == 0, (
            f"setup: cairn init with the test config.toml must succeed.\n"
            f"stderr: {init_result.stderr}"
        )
        git(["remote", "add", "allowed", str(bare)], cwd=vault)
        stage_and_commit(vault, "pp_inject_allow.md", "clean content\n")

        result = run(
            ["git", "push", "allowed", "HEAD:refs/heads/main"],
            cwd=vault,
            extra_env=stub_env(stub_dir),
        )
        assert result.returncode == 0, (
            f"A push to an allowlisted remote must still succeed even "
            f"when the hook's internal 'git remote get-url' enrichment "
            f"call fails.\nstderr: {result.stderr}"
        )
