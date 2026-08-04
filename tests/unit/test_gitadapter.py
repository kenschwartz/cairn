"""
Unit tests for cairn.gitadapter.

Every git call Cairn makes goes through here. The properties that matter:
calls run in the given cwd (never the process cwd), is_dirty() is path-scoped
rather than repo-wide, and commit_paths() stages only the paths handed to it.

Hermeticity: real git against repos created under tmp_path. The session-scoped
hermetic_env fixture keeps git identity and config out of the real $HOME.
"""

import subprocess

import pytest

from cairn.gitadapter import commit_paths, is_dirty, run_git


def _init_repo(path):
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=str(path), capture_output=True, check=True)
    return path


@pytest.fixture()
def repo(tmp_path):
    path = _init_repo(tmp_path / "repo")
    (path / "seed.md").write_text("seed\n")
    subprocess.run(["git", "add", "seed.md"], cwd=str(path), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "seed"], cwd=str(path), capture_output=True, check=True)
    return path


class TestRunGit:
    def test_returns_stdout_as_text(self, repo):
        result = run_git(["rev-parse", "--is-inside-work-tree"], repo)
        assert result.returncode == 0
        assert result.stdout.strip() == "true"

    def test_runs_in_the_given_cwd_not_the_process_cwd(self, repo, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = run_git(["log", "--format=%s"], repo)
        assert result.stdout.strip() == "seed"

    def test_accepts_a_string_path_for_cwd(self, repo):
        assert run_git(["status", "--porcelain"], str(repo)).returncode == 0

    def test_failing_command_returns_nonzero_and_stderr(self, repo):
        result = run_git(["cat-file", "-e", "deadbeef" * 5], repo)
        assert result.returncode != 0

    def test_does_not_raise_on_failure(self, tmp_path):
        result = run_git(["status"], tmp_path)
        assert result.returncode != 0


class TestIsDirty:
    def test_clean_tracked_file_is_not_dirty(self, repo):
        assert is_dirty(repo / "seed.md", repo) is False

    def test_modified_tracked_file_is_dirty(self, repo):
        (repo / "seed.md").write_text("changed\n")
        assert is_dirty(repo / "seed.md", repo) is True

    def test_untracked_file_is_dirty(self, repo):
        (repo / "new.md").write_text("new\n")
        assert is_dirty(repo / "new.md", repo) is True

    def test_staged_but_uncommitted_file_is_dirty(self, repo):
        (repo / "new.md").write_text("new\n")
        subprocess.run(["git", "add", "new.md"], cwd=str(repo), capture_output=True, check=True)
        assert is_dirty(repo / "new.md", repo) is True

    def test_nonexistent_path_is_not_dirty(self, repo):
        assert is_dirty(repo / "absent.md", repo) is False

    def test_is_scoped_to_the_path_not_the_whole_repo(self, repo):
        (repo / "other.md").write_text("dirt\n")
        assert is_dirty(repo / "seed.md", repo) is False

    def test_directory_argument_reports_contents(self, repo):
        (repo / "notes").mkdir()
        (repo / "notes" / "a.md").write_text("a\n")
        assert is_dirty(repo / "notes", repo) is True

    def test_returns_a_bool(self, repo):
        assert isinstance(is_dirty(repo / "seed.md", repo), bool)


class TestCommitPaths:
    def _log_files(self, repo, rev="HEAD"):
        result = subprocess.run(
            ["git", "show", "--name-only", "--format=", rev],
            cwd=str(repo),
            capture_output=True,
            text=True,
            check=True,
        )
        return sorted(result.stdout.split())

    def test_commits_the_given_path(self, repo):
        target = repo / "note.md"
        target.write_text("body\n")
        result = commit_paths([target], repo, "cairn new: note")
        assert result.returncode == 0
        assert self._log_files(repo) == ["note.md"]

    def test_uses_the_given_message(self, repo):
        target = repo / "note.md"
        target.write_text("body\n")
        commit_paths([target], repo, "cairn new: note")
        log = subprocess.run(
            ["git", "log", "-1", "--format=%s"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            check=True,
        )
        assert log.stdout.strip() == "cairn new: note"

    def test_commits_multiple_paths_in_one_commit(self, repo):
        first, second = repo / "a.md", repo / "b.md"
        first.write_text("a\n")
        second.write_text("b\n")
        commit_paths([first, second], repo, "two notes")
        assert self._log_files(repo) == ["a.md", "b.md"]

    def test_does_not_commit_unrelated_dirty_paths(self, repo):
        target = repo / "note.md"
        target.write_text("body\n")
        (repo / "unrelated.md").write_text("not mine\n")
        commit_paths([target], repo, "only mine")
        assert self._log_files(repo) == ["note.md"]
        assert is_dirty(repo / "unrelated.md", repo) is True

    def test_nothing_to_commit_returns_nonzero(self, repo):
        result = commit_paths([repo / "seed.md"], repo, "no-op")
        assert result.returncode != 0

    def test_empty_path_list_returns_nonzero(self, repo):
        assert commit_paths([], repo, "empty").returncode != 0

    def test_failed_commit_leaves_the_file_on_disk(self, repo):
        target = repo / "note.md"
        target.write_text("body\n")
        subprocess.run(
            ["git", "config", "commit.gpgsign", "true"], cwd=str(repo), capture_output=True
        )
        subprocess.run(
            ["git", "config", "gpg.program", "/nonexistent/gpg"],
            cwd=str(repo),
            capture_output=True,
        )
        result = commit_paths([target], repo, "will fail")
        assert result.returncode != 0
        assert target.read_text() == "body\n"
