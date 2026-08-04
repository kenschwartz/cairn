"""
Unit tests for the helpers behind `cairn doctor` (cairn.commands.doctor).

doctor's value is entirely in these checks, and each one has a failure mode the
end-to-end run cannot easily produce: an unparseable `git --version`, a hook
with the right bytes but the wrong mode, a secret that exists only in history.

Hermeticity: filesystem and git use tmp_path only. Environment probes are
monkeypatched rather than mutated globally.
"""

import builtins
import subprocess
import sys
import types

import pytest

from cairn.commands import doctor


def _completed(stdout="", returncode=0):
    return types.SimpleNamespace(stdout=stdout, stderr="", returncode=returncode)


@pytest.fixture()
def repo(tmp_path):
    path = tmp_path / "vault"
    path.mkdir()
    subprocess.run(["git", "init"], cwd=str(path), capture_output=True, check=True)
    return path


class TestGitVersionOk:
    @pytest.mark.parametrize(
        "output,expected",
        [
            ("git version 2.30.0", True),
            ("git version 2.45.2", True),
            ("git version 3.0.0", True),
            ("git version 2.29.9", False),
            ("git version 1.9.5", False),
        ],
    )
    def test_version_threshold(self, monkeypatch, output, expected):
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: _completed(output))
        assert doctor._git_version_ok() is expected

    def test_apple_style_suffix_is_accepted(self, monkeypatch):
        monkeypatch.setattr(
            subprocess, "run", lambda *a, **k: _completed("git version 2.39.3 (Apple Git-146)")
        )
        assert doctor._git_version_ok() is True

    def test_unparseable_output_is_a_failure(self, monkeypatch):
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: _completed("git version banana"))
        assert doctor._git_version_ok() is False

    def test_short_output_is_a_failure(self, monkeypatch):
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: _completed("git"))
        assert doctor._git_version_ok() is False

    def test_nonzero_exit_is_a_failure(self, monkeypatch):
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: _completed("", returncode=127))
        assert doctor._git_version_ok() is False

    def test_real_git_on_this_machine_passes(self):
        assert doctor._git_version_ok() is True


class TestPyYamlOk:
    def test_true_when_importable(self):
        assert doctor._pyyaml_ok() is True

    def test_false_when_import_fails(self, monkeypatch):
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "yaml":
                raise ImportError("no yaml")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        monkeypatch.delitem(sys.modules, "yaml", raising=False)
        assert doctor._pyyaml_ok() is False


class TestLocalBinOnPath:
    def test_true_when_present(self, monkeypatch, tmp_path):
        monkeypatch.setattr(doctor.Path, "home", classmethod(lambda cls: tmp_path))
        monkeypatch.setenv("PATH", f"/usr/bin:{tmp_path}/.local/bin")
        assert doctor._local_bin_on_path() is True

    def test_false_when_absent(self, monkeypatch, tmp_path):
        monkeypatch.setattr(doctor.Path, "home", classmethod(lambda cls: tmp_path))
        monkeypatch.setenv("PATH", "/usr/bin:/bin")
        assert doctor._local_bin_on_path() is False

    def test_false_when_path_is_empty(self, monkeypatch, tmp_path):
        monkeypatch.setattr(doctor.Path, "home", classmethod(lambda cls: tmp_path))
        monkeypatch.setenv("PATH", "")
        assert doctor._local_bin_on_path() is False


class TestIsGitRepo:
    def test_true_for_a_repo(self, repo):
        assert doctor._is_git_repo(repo) is True

    def test_true_for_a_subdirectory_of_a_repo(self, repo):
        sub = repo / "notes"
        sub.mkdir()
        assert doctor._is_git_repo(sub) is True

    def test_false_outside_any_repo(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
        plain = tmp_path / "plain"
        plain.mkdir()
        assert doctor._is_git_repo(plain) is False


class TestVerifyHook:
    def _write(self, path, content, mode=0o755):
        path.write_text(content)
        path.chmod(mode)
        return path

    def test_matching_content_and_mode_passes(self, tmp_path):
        hook = self._write(tmp_path / "pre-commit", "#!/usr/bin/env python3\n")
        assert doctor._verify_hook(hook, "#!/usr/bin/env python3\n") == (True, "")

    def test_missing_hook_is_reported(self, tmp_path):
        ok, message = doctor._verify_hook(tmp_path / "pre-commit", "anything")
        assert ok is False
        assert "missing" in message

    def test_wrong_mode_is_reported_even_when_content_matches(self, tmp_path):
        hook = self._write(tmp_path / "pre-commit", "body", mode=0o644)
        ok, message = doctor._verify_hook(hook, "body")
        assert ok is False
        assert "mode" in message
        assert "0o644" in message

    def test_content_drift_is_reported_as_a_sha256_mismatch(self, tmp_path):
        hook = self._write(tmp_path / "pre-commit", "tampered")
        ok, message = doctor._verify_hook(hook, "expected")
        assert ok is False
        assert "SHA-256" in message

    def test_a_single_byte_of_drift_is_caught(self, tmp_path):
        hook = self._write(tmp_path / "pre-commit", "body\n")
        assert doctor._verify_hook(hook, "body")[0] is False

    def test_message_names_the_hook(self, tmp_path):
        ok, message = doctor._verify_hook(tmp_path / "pre-push", "x")
        assert message.startswith("pre-push")


class TestHistoryScan:
    def _commit(self, repo, name, body):
        (repo / name).write_text(body)
        subprocess.run(["git", "add", name], cwd=str(repo), capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", f"add {name}"], cwd=str(repo), capture_output=True, check=True
        )

    def test_clean_repo_yields_no_findings(self, repo):
        self._commit(repo, "note.md", "# Just a note\n")
        assert doctor._history_scan(repo, 20) == []

    def test_finds_a_secret_in_a_tracked_file(self, repo):
        self._commit(repo, "leak.md", "aws_key: AKIAIOSFODNN7EXAMPLE\n")
        rules = {f.rule for f in doctor._history_scan(repo, 20)}
        assert "aws_access_key_id" in rules

    def test_finds_a_secret_that_only_exists_in_history(self, repo):
        self._commit(repo, "note.md", "# note\n")
        self._commit(repo, "leak.md", "AKIAIOSFODNN7EXAMPLE\n")
        subprocess.run(["git", "rm", "-q", "leak.md"], cwd=str(repo), capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "remove leak"], cwd=str(repo), capture_output=True, check=True
        )
        findings = doctor._history_scan(repo, 20)
        assert [f for f in findings if f.rule == "aws_access_key_id"]

    def test_findings_carry_path_and_line(self, repo):
        self._commit(repo, "leak.md", "intro\nAKIAIOSFODNN7EXAMPLE\n")
        finding = next(f for f in doctor._history_scan(repo, 20) if f.rule == "aws_access_key_id")
        assert finding.path == "leak.md"
        assert finding.line == 2

    def test_excerpts_are_masked(self, repo):
        secret = "AKIAIOSFODNN7EXAMPLE"
        self._commit(repo, "leak.md", f"{secret}\n")
        for finding in doctor._history_scan(repo, 20):
            assert secret not in finding.excerpt

    def test_depth_zero_scans_the_worktree_only(self, repo):
        self._commit(repo, "note.md", "# note\n")
        self._commit(repo, "leak.md", "AKIAIOSFODNN7EXAMPLE\n")
        subprocess.run(["git", "rm", "-q", "leak.md"], cwd=str(repo), capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "remove leak"], cwd=str(repo), capture_output=True, check=True
        )
        assert doctor._history_scan(repo, 0) == []

    def test_unreadable_file_is_skipped_without_raising(self, repo, monkeypatch):
        self._commit(repo, "note.md", "# note\n")

        real_read_bytes = doctor.Path.read_bytes

        def flaky_read_bytes(self):
            if self.name == "note.md":
                raise OSError("permission denied")
            return real_read_bytes(self)

        monkeypatch.setattr(doctor.Path, "read_bytes", flaky_read_bytes)
        assert doctor._history_scan(repo, 20) == []

    def test_empty_repo_with_no_commits_yields_no_findings(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        subprocess.run(["git", "init"], cwd=str(empty), capture_output=True, check=True)
        assert doctor._history_scan(empty, 20) == []
