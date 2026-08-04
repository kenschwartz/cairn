"""
Regression tests for error propagation.

Every test here covers a path that previously reported success, or reported
nothing at all, while the operation it describes had failed. The rule under
test is the same in each case: a check that could not run is not a check that
passed, and a failed step is never reported as a completed one.
"""

import json
import os
import shutil
import subprocess


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


REAL_GIT = shutil.which("git")


class TestInitReportsFailures:
    def test_init_fails_when_hooks_cannot_be_installed(self, tmp_path):
        """
        A vault whose .git is a regular file cannot hold hooks. init must fail
        loudly instead of printing 'Installed git hooks'.
        """
        vault = tmp_path / "vault"
        vault.mkdir()
        (vault / ".git").write_text("not a git dir\n")

        result = run(["cairn", "init", str(vault)])
        combined = result.stdout + result.stderr
        assert result.returncode != 0
        assert "Installed git hooks" not in combined
        assert "hook" in combined.lower()

    def test_init_fails_when_git_init_fails(self, tmp_path):
        """
        A failing `git init` must abort init, not be logged and walked past.
        """
        vault = tmp_path / "vault"
        vault.mkdir()
        # A stub git that always fails, ahead of the real git on PATH.
        stub_dir = tmp_path / "stub"
        stub_dir.mkdir()
        stub = stub_dir / "git"
        stub.write_text("#!/bin/sh\necho 'stub git failure' >&2\nexit 1\n")
        stub.chmod(0o755)

        result = run(
            ["cairn", "init", str(vault)],
            extra_env={"PATH": f"{stub_dir}:{os.environ['PATH']}"},
        )
        combined = result.stdout + result.stderr
        assert result.returncode != 0
        assert "git init failed" in combined
        assert "Installed git hooks" not in combined

    def test_init_reports_unreadable_remotes_as_failure(self, tmp_vault, tmp_path):
        """
        If the remote list cannot be read, the allowlist was not checked. That
        is a failure, not an implicit pass.
        """
        stub_dir = tmp_path / "stub_remote"
        stub_dir.mkdir()
        stub = stub_dir / "git"
        # Succeed for everything except `git remote`.
        stub.write_text(
            "#!/bin/sh\n"
            'if [ "$1" = "remote" ]; then echo "remote exploded" >&2; exit 1; fi\n'
            f'exec {REAL_GIT} "$@"\n'
        )
        stub.chmod(0o755)

        result = run(
            ["cairn", "init", str(tmp_vault)],
            extra_env={"PATH": f"{stub_dir}:{os.environ['PATH']}"},
        )
        combined = result.stdout + result.stderr
        assert result.returncode != 0
        assert "remote" in combined.lower()


class TestNewReportsGitFailures:
    def test_new_outside_a_git_repo_fails_clearly(self, tmp_path):
        """
        `git status` failing must not read as 'the path is clean'. It must be
        reported, with no traceback.
        """
        plain_dir = tmp_path / "not_a_repo"
        plain_dir.mkdir()

        result = run(["cairn", "new", "Some Note"], cwd=plain_dir)
        combined = result.stdout + result.stderr
        assert result.returncode != 0
        assert "Traceback" not in combined
        assert "git" in combined.lower()

    def test_failed_staging_is_reported_and_file_survives(self, tmp_vault):
        """
        A `git add` that fails must surface, rather than being discarded and
        followed by a commit of whatever else happened to be staged.
        DESIGN.md: 'the write to disk stands, the commit does not, and the CLI
        says so explicitly.'
        """
        gitignore = tmp_vault / ".gitignore"
        gitignore.write_text(gitignore.read_text() + "notes/\n")

        result = run(["cairn", "new", "Ignored Note"], cwd=tmp_vault)
        combined = result.stdout + result.stderr
        assert result.returncode != 0
        assert "Traceback" not in combined
        # The note is on disk even though it could not be committed.
        assert (tmp_vault / "notes" / "ignored-note.md").exists()
        # And nothing was committed for it.
        log = git(["log", "--oneline", "--", "notes/ignored-note.md"], cwd=tmp_vault)
        assert not log.stdout.strip()


class TestDoctorReportsFailures:
    def test_fix_does_not_mask_unrelated_failures(self, tmp_vault):
        """
        `--fix` repairs hooks only. It must not clear an unrelated hard failure
        such as a non-allowlisted remote.
        """
        git(["remote", "add", "origin", "https://github.com/personal/badrepo.git"],
            cwd=tmp_vault)
        (tmp_vault / ".git" / "hooks" / "pre-commit").unlink()

        result = run(["cairn", "doctor", "--fix"], cwd=tmp_vault)
        combined = result.stdout + result.stderr
        assert result.returncode != 0, (
            "--fix must not turn an unrelated remote failure into a pass"
        )
        assert "allowlist" in combined.lower()

    def test_history_scan_reports_unreadable_file(self, tmp_vault):
        """
        A tracked file the scan cannot read must be reported as unscanned, not
        silently treated as clean.
        """
        note = tmp_vault / "notes" / "unreadable.md"
        note.write_text("plain content\n")
        git(["add", "notes/unreadable.md"], cwd=tmp_vault)
        git(["commit", "-m", "add note"], cwd=tmp_vault)
        note.chmod(0o000)

        try:
            result = run(["cairn", "doctor"], cwd=tmp_vault)
        finally:
            note.chmod(0o644)

        combined = result.stdout + result.stderr
        assert "history scan incomplete" in combined
        assert "unreadable.md" in combined

    def test_git_check_names_the_reason_it_failed(self, tmp_path):
        """
        Doctor must distinguish 'git is unusable' from a bare FAIL.
        """
        vault = tmp_path / "vault"
        vault.mkdir()
        result = run(["cairn", "init", str(vault)])
        assert result.returncode == 0

        stub_dir = tmp_path / "stub_version"
        stub_dir.mkdir()
        stub = stub_dir / "git"
        stub.write_text(
            "#!/bin/sh\n"
            'if [ "$1" = "--version" ]; then echo "git version banana"; exit 0; fi\n'
            f'exec {REAL_GIT} "$@"\n'
        )
        stub.chmod(0o755)

        result = run(
            ["cairn", "doctor"], cwd=vault,
            extra_env={"PATH": f"{stub_dir}:{os.environ['PATH']}"},
        )
        combined = result.stdout + result.stderr
        assert result.returncode != 0
        assert "unrecognised git version" in combined


class TestPreCommitHookFailsClosed:
    def test_staged_deletion_does_not_crash_the_hook(self, tmp_vault):
        """
        A staged deletion has no staged content. The hook must not ask git for
        it and die on the resulting error.
        """
        note = tmp_vault / "notes" / "todelete.md"
        note.write_text("content\n")
        git(["add", "notes/todelete.md"], cwd=tmp_vault)
        assert git(["commit", "-m", "add"], cwd=tmp_vault).returncode == 0

        git(["rm", "notes/todelete.md"], cwd=tmp_vault)
        result = run(["git", "commit", "-m", "delete the note"], cwd=tmp_vault)
        combined = result.stdout + result.stderr
        assert result.returncode == 0, (
            f"Committing a deletion must succeed.\n{combined}"
        )
        assert "Traceback" not in combined

    def test_unparseable_manifest_blocks_the_commit(self, tmp_vault):
        """
        A manifest that cannot be parsed means its entries were not verified.
        The hook must fail closed rather than skip the check.
        """
        manifest = tmp_vault / "assets" / "local.manifest.json"
        manifest.write_text("{ this is not json ")
        git(["add", "assets/local.manifest.json"], cwd=tmp_vault)

        result = run(["git", "commit", "-m", "broken manifest"], cwd=tmp_vault)
        combined = result.stdout + result.stderr
        assert result.returncode != 0, (
            "An unparseable manifest must block the commit"
        )
        assert "json" in combined.lower()

    def test_unreadable_manifest_entry_blocks_the_commit(self, tmp_vault):
        """
        A manifest entry whose file exists but cannot be read is an unverified
        entry, which must block rather than pass.
        """
        local_dir = tmp_vault / "assets" / "local"
        local_dir.mkdir(parents=True, exist_ok=True)
        asset = local_dir / "locked.bin"
        asset.write_bytes(b"content")
        asset.chmod(0o000)

        manifest = tmp_vault / "assets" / "local.manifest.json"
        manifest.write_text(json.dumps({
            "manifest_version": 1,
            "entries": [{
                "path": "assets/local/locked.bin",
                "size_bytes": 7,
                "sha256": "a" * 64,
                "added": "2026-08-04",
                "referenced_by": "notes/n.md",
            }],
        }))
        git(["add", "assets/local.manifest.json"], cwd=tmp_vault)

        try:
            result = run(["git", "commit", "-m", "unreadable entry"], cwd=tmp_vault)
        finally:
            asset.chmod(0o644)

        combined = result.stdout + result.stderr
        assert result.returncode != 0
        assert "locked.bin" in combined
