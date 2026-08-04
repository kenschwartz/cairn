"""
In-process unit tests for run_new (cairn.commands.new).

test_new_and_autocommit.py drives `cairn new` through the installed executable;
these tests call run_new() directly so its return codes, stderr text, and
frontmatter values are pinned without a subprocess in the way.

Hermeticity: run_new() writes into the vault at the process cwd, so every test
chdirs into a throwaway git repo under tmp_path.
"""

import argparse
import datetime
import subprocess

import pytest
import yaml

from cairn.commands.new import run_new


def args(title="A note", **overrides):
    ns = argparse.Namespace(title=title, type="note", tag=None, project="")
    for key, value in overrides.items():
        setattr(ns, key, value)
    return ns


def read_frontmatter(path):
    body = path.read_text()
    assert body.startswith("---\n")
    return yaml.safe_load(body.split("---\n")[1])


@pytest.fixture()
def vault(tmp_path, monkeypatch):
    path = tmp_path / "vault"
    path.mkdir()
    subprocess.run(["git", "init"], cwd=str(path), capture_output=True, check=True)
    (path / "README.md").write_text("seed\n")
    subprocess.run(["git", "add", "README.md"], cwd=str(path), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "seed"], cwd=str(path), capture_output=True, check=True)
    monkeypatch.chdir(path)
    return path


class TestValidation:
    def test_missing_title_fails(self, vault, capsys):
        assert run_new(args(title=None)) == 1
        assert "title is required" in capsys.readouterr().err

    def test_empty_title_fails(self, vault, capsys):
        assert run_new(args(title="")) == 1
        assert "title is required" in capsys.readouterr().err

    def test_invalid_type_fails_and_names_the_type(self, vault, capsys):
        assert run_new(args(type="bogus")) == 1
        assert "bogus" in capsys.readouterr().err

    def test_invalid_type_writes_nothing(self, vault):
        run_new(args(type="bogus"))
        assert not (vault / "notes").exists()

    @pytest.mark.parametrize(
        "note_type", ["note", "todo", "meeting", "reference", "project", "moc"]
    )
    def test_every_vocabulary_type_is_accepted(self, vault, note_type):
        assert run_new(args(title=f"Title {note_type}", type=note_type)) == 0


class TestWrittenNote:
    def test_writes_into_notes_dir_and_commits(self, vault):
        assert run_new(args(title="Quarterly Review")) == 0
        assert (vault / "notes" / "quarterly-review.md").is_file()

    def test_creates_the_notes_dir_when_missing(self, vault):
        run_new(args())
        assert (vault / "notes").is_dir()

    def test_body_has_the_title_as_an_h1(self, vault):
        run_new(args(title="Quarterly Review"))
        assert (vault / "notes" / "quarterly-review.md").read_text().endswith(
            "# Quarterly Review\n\n"
        )

    def test_no_temp_file_is_left_behind(self, vault):
        run_new(args())
        assert list((vault / "notes").glob("*.tmp")) == []

    def test_frontmatter_defaults(self, vault):
        run_new(args(title="Quarterly Review"))
        fm = read_frontmatter(vault / "notes" / "quarterly-review.md")
        assert fm["title"] == "Quarterly Review"
        assert fm["type"] == "note"
        assert fm["status"] == "active"
        assert fm["project"] == ""
        assert fm["tags"] == ["untagged"]
        assert fm["cairn_version"] == 1

    def test_id_is_eight_hex_chars(self, vault):
        run_new(args())
        note_id = read_frontmatter(vault / "notes" / "a-note.md")["id"]
        assert len(note_id) == 8
        assert all(ch in "0123456789abcdef" for ch in note_id)

    def test_created_equals_updated_and_is_today(self, vault):
        run_new(args())
        fm = read_frontmatter(vault / "notes" / "a-note.md")
        assert fm["created"] == fm["updated"] == datetime.date.today().isoformat()

    def test_tags_are_normalized(self, vault):
        run_new(args(tag=["Work Notes", "OPS"]))
        assert read_frontmatter(vault / "notes" / "a-note.md")["tags"] == ["work-notes", "ops"]

    def test_project_is_passed_through(self, vault):
        run_new(args(project="cairn"))
        assert read_frontmatter(vault / "notes" / "a-note.md")["project"] == "cairn"

    def test_optional_fields_are_present_but_empty(self, vault):
        run_new(args())
        fm = read_frontmatter(vault / "notes" / "a-note.md")
        assert fm["moc"] == fm["source"] == fm["source_url"] == ""

    def test_commits_only_the_new_note(self, vault):
        (vault / "unrelated.md").write_text("not mine\n")
        run_new(args(title="Quarterly Review"))
        shown = subprocess.run(
            ["git", "show", "--name-only", "--format=", "HEAD"],
            cwd=str(vault),
            capture_output=True,
            text=True,
            check=True,
        )
        assert shown.stdout.split() == ["notes/quarterly-review.md"]

    def test_commit_message_names_the_title(self, vault):
        run_new(args(title="Quarterly Review"))
        log = subprocess.run(
            ["git", "log", "-1", "--format=%s"],
            cwd=str(vault),
            capture_output=True,
            text=True,
            check=True,
        )
        assert log.stdout.strip() == "cairn new: Quarterly Review"


class TestCollisions:
    def test_second_note_with_the_same_title_gets_a_suffix(self, vault):
        run_new(args(title="Quarterly Review"))
        assert run_new(args(title="Quarterly Review")) == 0
        assert (vault / "notes" / "quarterly-review-2.md").is_file()

    def test_suffix_increments(self, vault):
        for _ in range(3):
            run_new(args(title="Quarterly Review"))
        assert (vault / "notes" / "quarterly-review-3.md").is_file()

    def test_existing_note_is_never_overwritten(self, vault):
        run_new(args(title="Quarterly Review"))
        first = vault / "notes" / "quarterly-review.md"
        before = first.read_text()
        run_new(args(title="Quarterly Review"))
        assert first.read_text() == before


class TestDirtyGuard:
    def test_dirty_target_stops_the_write(self, vault, capsys):
        notes = vault / "notes"
        notes.mkdir()
        existing = notes / "a-note.md"
        existing.write_text("uncommitted\n")
        assert run_new(args()) == 1
        assert "uncommitted changes" in capsys.readouterr().err
        assert existing.read_text() == "uncommitted\n"

    def test_dirty_target_creates_no_sibling_note(self, vault):
        notes = vault / "notes"
        notes.mkdir()
        (notes / "a-note.md").write_text("uncommitted\n")
        run_new(args())
        assert sorted(p.name for p in notes.iterdir()) == ["a-note.md"]


class TestCommitFailure:
    def test_file_is_kept_and_error_reported(self, vault, capsys):
        subprocess.run(
            ["git", "config", "commit.gpgsign", "true"], cwd=str(vault), capture_output=True
        )
        subprocess.run(
            ["git", "config", "gpg.program", "/nonexistent/gpg"],
            cwd=str(vault),
            capture_output=True,
        )
        assert run_new(args(title="Quarterly Review")) == 1
        assert "commit failed" in capsys.readouterr().err
        assert (vault / "notes" / "quarterly-review.md").is_file()
