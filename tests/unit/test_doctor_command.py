"""
In-process unit tests for run_doctor (cairn.commands.doctor).

doctor's contract is its exit code and its report lines: hard failures must exit
1, warnings must not, and --fix must repair the hooks and relabel the lines it
repaired. Each of these is driven here by breaking exactly one thing.

Hermeticity: runs against a vault under tmp_path, entered with monkeypatch.chdir.
"""

import argparse
import stat
import subprocess

import pytest

from cairn.commands import doctor
from cairn.commands.init import run_init

ENV_VAR = "CAIRN_ALLOWED_REMOTE_PREFIXES"


@pytest.fixture(autouse=True)
def default_allowlist(monkeypatch):
    monkeypatch.setenv(ENV_VAR, "https://github.com/ORG/")


@pytest.fixture()
def vault(tmp_path, monkeypatch, capsys):
    path = tmp_path / "vault"
    run_init(argparse.Namespace(path=str(path)))
    capsys.readouterr()
    monkeypatch.chdir(path)
    return path


def run(fix=False, scan_history=20):
    return doctor.run_doctor(argparse.Namespace(fix=fix, scan_history=scan_history))


class TestHealthyVault:
    def test_exits_zero(self, vault, capsys):
        assert run() == 0

    def test_reports_every_check(self, vault, capsys):
        run()
        out = capsys.readouterr().out
        for line in (
            "PyYAML: OK",
            "git: OK",
            "vault is git repo: OK",
            "pre-commit hook: OK",
            "pre-push hook: OK",
        ):
            assert line in out

    def test_reports_the_python_version(self, vault, capsys):
        run()
        assert "Python version:" in capsys.readouterr().out

    def test_no_remotes_is_a_warning_not_a_failure(self, vault, capsys):
        assert run() == 0
        assert "warning: no remotes configured" in capsys.readouterr().out

    def test_local_bin_off_path_is_a_warning_not_a_failure(self, vault, capsys, monkeypatch):
        monkeypatch.setenv("PATH", "/usr/bin:/bin")
        assert run() == 0
        assert "warning: ~/.local/bin is not on PATH" in capsys.readouterr().out


class TestHardFailures:
    def test_missing_hook(self, vault, capsys):
        (vault / ".git" / "hooks" / "pre-commit").unlink()
        assert run() == 1
        assert "pre-commit hook: pre-commit missing FAIL" in capsys.readouterr().out

    def test_hook_content_drift(self, vault, capsys):
        (vault / ".git" / "hooks" / "pre-push").write_text("#!/bin/sh\nexit 0\n")
        assert run() == 1
        assert "pre-push hook: pre-push content mismatch (SHA-256) FAIL" in capsys.readouterr().out

    def test_hook_mode_drift(self, vault, capsys):
        (vault / ".git" / "hooks" / "pre-commit").chmod(0o644)
        assert run() == 1
        assert "mode is 0o644" in capsys.readouterr().out

    def test_non_allowlisted_remote(self, vault, capsys):
        subprocess.run(
            ["git", "remote", "add", "origin", "https://github.com/other/vault.git"],
            cwd=str(vault),
            capture_output=True,
            check=True,
        )
        assert run() == 1
        assert "not in allowlist" in capsys.readouterr().out

    def test_missing_git_user_email(self, vault, capsys, tmp_path, monkeypatch):
        empty_cfg = tmp_path / "empty.gitconfig"
        empty_cfg.write_text("")
        monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty_cfg))
        assert run() == 1
        assert "git user.email: not set FAIL" in capsys.readouterr().out

    def test_not_a_git_repo(self, tmp_path, monkeypatch, capsys):
        plain = tmp_path / "plain"
        plain.mkdir()
        monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
        monkeypatch.chdir(plain)
        assert run() == 1
        assert "vault is git repo: FAIL" in capsys.readouterr().out

    def test_missing_pyyaml(self, vault, capsys, monkeypatch):
        monkeypatch.setattr(doctor, "_pyyaml_ok", lambda: False)
        assert run() == 1
        assert "PyYAML: FAIL" in capsys.readouterr().out

    def test_unusable_git(self, vault, capsys, monkeypatch):
        monkeypatch.setattr(doctor, "_git_version_ok", lambda: False)
        assert run() == 1
        assert "git: FAIL" in capsys.readouterr().out


class TestHistoryReport:
    def test_warns_about_a_committed_secret_without_failing(self, vault, capsys):
        (vault / "notes" / "leak.md").write_text("AKIAIOSFODNN7EXAMPLE\n")
        subprocess.run(
            ["git", "add", "-f", "notes/leak.md"], cwd=str(vault), capture_output=True, check=True
        )
        subprocess.run(
            ["git", "commit", "--no-verify", "-m", "leak"],
            cwd=str(vault),
            capture_output=True,
            check=True,
        )
        assert run() == 0
        out = capsys.readouterr().out
        assert "history scan found" in out
        assert "aws_access_key_id: notes/leak.md:1" in out

    def test_masks_the_secret_in_the_report(self, vault, capsys):
        secret = "AKIAIOSFODNN7EXAMPLE"
        (vault / "notes" / "leak.md").write_text(f"{secret}\n")
        subprocess.run(
            ["git", "add", "-f", "notes/leak.md"], cwd=str(vault), capture_output=True, check=True
        )
        subprocess.run(
            ["git", "commit", "--no-verify", "-m", "leak"],
            cwd=str(vault),
            capture_output=True,
            check=True,
        )
        run()
        assert secret not in capsys.readouterr().out

    def test_clean_vault_reports_no_history_warning(self, vault, capsys):
        run()
        assert "history scan found" not in capsys.readouterr().out

    def test_scan_history_depth_is_honoured(self, vault, capsys, monkeypatch):
        seen = {}

        def fake_history_scan(path, depth):
            seen["depth"] = depth
            return []

        monkeypatch.setattr(doctor, "_history_scan", fake_history_scan)
        run(scan_history=3)
        assert seen["depth"] == 3

    def test_depth_defaults_to_20_when_unset(self, vault, capsys, monkeypatch):
        seen = {}
        monkeypatch.setattr(doctor, "_history_scan", lambda p, d: seen.setdefault("depth", d) and [])
        doctor.run_doctor(argparse.Namespace(fix=False, scan_history=None))
        assert seen["depth"] == 20


class TestFix:
    def test_reinstalls_a_missing_hook_and_exits_zero(self, vault, capsys):
        (vault / ".git" / "hooks" / "pre-commit").unlink()
        assert run(fix=True) == 0
        out = capsys.readouterr().out
        assert "--fix: reinstalled hooks" in out
        assert (vault / ".git" / "hooks" / "pre-commit").is_file()

    def test_repaired_hook_lines_are_relabelled_fixed(self, vault, capsys):
        (vault / ".git" / "hooks" / "pre-push").write_text("tampered\n")
        run(fix=True)
        out = capsys.readouterr().out
        assert "FIXED" in out
        assert "pre-push hook" in out

    def test_restores_hook_mode(self, vault, capsys):
        hook = vault / ".git" / "hooks" / "pre-commit"
        hook.chmod(0o644)
        run(fix=True)
        assert stat.S_IMODE(hook.stat().st_mode) == 0o755

    def test_repaired_hook_passes_a_later_plain_run(self, vault, capsys):
        (vault / ".git" / "hooks" / "pre-commit").write_text("tampered\n")
        run(fix=True)
        capsys.readouterr()
        assert run() == 0

    @pytest.mark.xfail(
        strict=True,
        reason="known defect: a successful --fix clears hard_fail wholesale, so an "
        "unrelated hard failure (here: missing PyYAML) is reported as FAIL but "
        "doctor still exits 0",
    )
    def test_does_not_mask_an_unrelated_hard_failure(self, vault, capsys, monkeypatch):
        (vault / ".git" / "hooks" / "pre-commit").unlink()
        monkeypatch.setattr(doctor, "_pyyaml_ok", lambda: False)
        assert run(fix=True) == 1

    def test_is_a_no_op_when_hooks_are_healthy(self, vault, capsys):
        before = (vault / ".git" / "hooks" / "pre-commit").read_bytes()
        assert run(fix=True) == 0
        out = capsys.readouterr().out
        assert "reinstalled hooks" not in out
        assert (vault / ".git" / "hooks" / "pre-commit").read_bytes() == before
