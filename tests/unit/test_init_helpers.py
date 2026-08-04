"""
Unit tests for the helpers behind `cairn init` (cairn.commands.init).

The integration suite runs the real command; these tests pin the individual
decisions in isolation: how the remote allowlist is resolved, how remote URLs
are judged against it, and what install_hooks() puts on disk.

Hermeticity: filesystem and git use tmp_path only. The env override is applied
with monkeypatch so it never leaks between tests.
"""

import shutil
import stat
import subprocess
from pathlib import Path

import pytest

import cairn.scan as scan_mod
from cairn.commands import init
from cairn.hooks import render

ENV_VAR = "CAIRN_ALLOWED_REMOTE_PREFIXES"


@pytest.fixture()
def repo(tmp_path):
    path = tmp_path / "vault"
    path.mkdir()
    subprocess.run(["git", "init"], cwd=str(path), capture_output=True, check=True)
    return path


class TestGetAllowlist:
    def test_defaults_when_env_is_unset(self, monkeypatch):
        monkeypatch.delenv(ENV_VAR, raising=False)
        assert init.get_allowlist() == init.DEFAULT_ALLOWLIST

    def test_returns_a_copy_of_the_default(self, monkeypatch):
        monkeypatch.delenv(ENV_VAR, raising=False)
        init.get_allowlist().append("https://evil.example/")
        assert "https://evil.example/" not in init.DEFAULT_ALLOWLIST

    def test_env_override_replaces_the_default(self, monkeypatch):
        monkeypatch.setenv(ENV_VAR, "https://example.com/")
        assert init.get_allowlist() == ["https://example.com/"]

    def test_env_override_splits_on_commas_and_strips_whitespace(self, monkeypatch):
        monkeypatch.setenv(ENV_VAR, " https://a.example/ , https://b.example/ ")
        assert init.get_allowlist() == ["https://a.example/", "https://b.example/"]

    def test_empty_entries_are_dropped(self, monkeypatch):
        monkeypatch.setenv(ENV_VAR, "https://a.example/,,")
        assert init.get_allowlist() == ["https://a.example/"]

    def test_empty_env_falls_back_to_the_default(self, monkeypatch):
        monkeypatch.setenv(ENV_VAR, "")
        assert init.get_allowlist() == init.DEFAULT_ALLOWLIST

    def test_whitespace_only_env_yields_no_prefixes(self, monkeypatch):
        monkeypatch.setenv(ENV_VAR, " , ")
        assert init.get_allowlist() == []


class TestCheckRemotes:
    def test_no_remotes_is_a_warning_not_a_failure(self, repo):
        ok, message = init.check_remotes(repo, ["https://github.com/ORG/"])
        assert ok is True
        assert "warning" in message.lower()

    def test_allowlisted_remote_passes_silently(self, repo):
        subprocess.run(
            ["git", "remote", "add", "origin", "https://github.com/ORG/vault.git"],
            cwd=str(repo),
            capture_output=True,
            check=True,
        )
        assert init.check_remotes(repo, ["https://github.com/ORG/"]) == (True, "")

    def test_non_allowlisted_remote_fails_and_names_the_url(self, repo):
        subprocess.run(
            ["git", "remote", "add", "origin", "https://github.com/other/vault.git"],
            cwd=str(repo),
            capture_output=True,
            check=True,
        )
        ok, message = init.check_remotes(repo, ["https://github.com/ORG/"])
        assert ok is False
        assert "https://github.com/other/vault.git" in message

    def test_one_bad_remote_among_good_ones_fails(self, repo):
        for name, url in (
            ("origin", "https://github.com/ORG/vault.git"),
            ("mirror", "https://elsewhere.example/vault.git"),
        ):
            subprocess.run(
                ["git", "remote", "add", name, url],
                cwd=str(repo),
                capture_output=True,
                check=True,
            )
        ok, message = init.check_remotes(repo, ["https://github.com/ORG/"])
        assert ok is False
        assert "elsewhere.example" in message

    def test_prefix_match_is_not_a_substring_match(self, repo):
        subprocess.run(
            ["git", "remote", "add", "origin", "https://evil.example/https://github.com/ORG/x.git"],
            cwd=str(repo),
            capture_output=True,
            check=True,
        )
        ok, _ = init.check_remotes(repo, ["https://github.com/ORG/"])
        assert ok is False

    def test_empty_allowlist_rejects_any_remote(self, repo):
        subprocess.run(
            ["git", "remote", "add", "origin", "https://github.com/ORG/vault.git"],
            cwd=str(repo),
            capture_output=True,
            check=True,
        )
        ok, _ = init.check_remotes(repo, [])
        assert ok is False

    def test_non_git_directory_is_not_a_failure(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
        plain = tmp_path / "not-a-repo"
        plain.mkdir()
        assert init.check_remotes(plain, ["https://github.com/ORG/"]) == (True, "")


class TestInstallHooks:
    @pytest.fixture()
    def installed(self, repo):
        init.install_hooks(repo, ["https://github.com/ORG/"])
        return repo / ".git" / "hooks"

    def test_writes_both_hooks(self, installed):
        assert (installed / "pre-commit").is_file()
        assert (installed / "pre-push").is_file()

    def test_hooks_are_executable_0755(self, installed):
        for name in ("pre-commit", "pre-push"):
            mode = stat.S_IMODE((installed / name).stat().st_mode)
            assert mode == 0o755

    def test_pre_commit_matches_a_fresh_render(self, installed):
        expected = render.render_pre_commit(Path(scan_mod.__file__).read_text())
        assert (installed / "pre-commit").read_text() == expected

    def test_pre_push_embeds_the_given_allowlist(self, installed):
        assert 'ALLOWLIST = ["https://github.com/ORG/"]' in (installed / "pre-push").read_text()

    def test_creates_the_hooks_dir_when_missing(self, repo):
        shutil.rmtree(repo / ".git" / "hooks")
        init.install_hooks(repo, [])
        assert (repo / ".git" / "hooks" / "pre-commit").is_file()

    def test_overwrites_a_tampered_hook(self, installed):
        (installed / "pre-commit").write_text("#!/bin/sh\nexit 0\n")
        init.install_hooks(installed.parent.parent, ["https://github.com/ORG/"])
        assert "CAIRN SCAN" in (installed / "pre-commit").read_text()
