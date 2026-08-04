"""
In-process unit tests for run_init (cairn.commands.init).

The integration suite asserts the end state of a real `cairn init`; these tests
call run_init() directly to pin its report lines and its exit code, including
the re-run case where everything already exists.

Hermeticity: writes only under tmp_path; the allowlist env override is applied
with monkeypatch.
"""

import argparse
import stat
import subprocess

import pytest

from cairn.commands.init import run_init

ENV_VAR = "CAIRN_ALLOWED_REMOTE_PREFIXES"


@pytest.fixture(autouse=True)
def default_allowlist(monkeypatch):
    monkeypatch.setenv(ENV_VAR, "https://github.com/ORG/")


def init(path, capsys):
    code = run_init(argparse.Namespace(path=str(path)))
    return code, capsys.readouterr().out


class TestFreshVault:
    def test_succeeds(self, tmp_path, capsys):
        code, _ = init(tmp_path / "vault", capsys)
        assert code == 0

    def test_creates_the_vault_dir_itself(self, tmp_path, capsys):
        vault = tmp_path / "nested" / "vault"
        init(vault, capsys)
        assert vault.is_dir()

    def test_creates_the_skeleton_and_reports_it(self, tmp_path, capsys):
        vault = tmp_path / "vault"
        _, out = init(vault, capsys)
        for name in ("notes", "moc", "assets", "assets/local", "indexes"):
            assert (vault / name).is_dir()
            assert f"Created {name}/" in out

    def test_initializes_git_and_reports_it(self, tmp_path, capsys):
        vault = tmp_path / "vault"
        _, out = init(vault, capsys)
        assert (vault / ".git").is_dir()
        assert "Initialized git repository" in out

    def test_writes_gitignore(self, tmp_path, capsys):
        vault = tmp_path / "vault"
        _, out = init(vault, capsys)
        assert "assets/local/" in (vault / ".gitignore").read_text()
        assert "Created .gitignore" in out

    def test_installs_executable_hooks(self, tmp_path, capsys):
        vault = tmp_path / "vault"
        _, out = init(vault, capsys)
        assert "Installed git hooks" in out
        for name in ("pre-commit", "pre-push"):
            hook = vault / ".git" / "hooks" / name
            assert stat.S_IMODE(hook.stat().st_mode) == 0o755

    def test_pre_push_embeds_the_resolved_allowlist(self, tmp_path, capsys):
        vault = tmp_path / "vault"
        init(vault, capsys)
        hook = (vault / ".git" / "hooks" / "pre-push").read_text()
        assert 'ALLOWLIST = ["https://github.com/ORG/"]' in hook

    def test_no_remotes_is_reported_as_a_warning_and_still_succeeds(self, tmp_path, capsys):
        code, out = init(tmp_path / "vault", capsys)
        assert code == 0
        assert "warning: no remotes configured" in out

    def test_accepts_a_relative_path(self, tmp_path, capsys, monkeypatch):
        monkeypatch.chdir(tmp_path)
        code, _ = init("vault", capsys)
        assert code == 0
        assert (tmp_path / "vault" / "notes").is_dir()


class TestRerun:
    def test_is_idempotent_and_reports_existing_state(self, tmp_path, capsys):
        vault = tmp_path / "vault"
        init(vault, capsys)
        code, out = init(vault, capsys)
        assert code == 0
        assert "notes/ already exists" in out
        assert "git repository already exists" in out
        assert ".gitignore already exists" in out

    def test_preserves_existing_notes(self, tmp_path, capsys):
        vault = tmp_path / "vault"
        init(vault, capsys)
        note = vault / "notes" / "keep.md"
        note.write_text("keep me\n")
        init(vault, capsys)
        assert note.read_text() == "keep me\n"


class TestRemoteEnforcement:
    def _with_remote(self, tmp_path, capsys, url):
        vault = tmp_path / "vault"
        init(vault, capsys)
        subprocess.run(
            ["git", "remote", "add", "origin", url],
            cwd=str(vault),
            capture_output=True,
            check=True,
        )
        return vault

    def test_allowlisted_remote_succeeds_without_a_remote_message(self, tmp_path, capsys):
        vault = self._with_remote(tmp_path, capsys, "https://github.com/ORG/vault.git")
        code, out = init(vault, capsys)
        assert code == 0
        assert "not in allowlist" not in out

    def test_non_allowlisted_remote_hard_fails_and_names_the_url(self, tmp_path, capsys):
        vault = self._with_remote(tmp_path, capsys, "https://github.com/other/vault.git")
        code, out = init(vault, capsys)
        assert code == 1
        assert "https://github.com/other/vault.git" in out

    def test_hooks_are_still_installed_when_the_remote_check_fails(self, tmp_path, capsys):
        vault = self._with_remote(tmp_path, capsys, "https://github.com/other/vault.git")
        init(vault, capsys)
        assert (vault / ".git" / "hooks" / "pre-commit").is_file()


class TestGitIdentity:
    def test_missing_user_email_is_warned_about_not_fatal(self, tmp_path, capsys, monkeypatch):
        empty_cfg = tmp_path / "empty.gitconfig"
        empty_cfg.write_text("")
        monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty_cfg))
        code, out = init(tmp_path / "vault", capsys)
        assert code == 0
        assert "warning: git user.email is not set" in out
