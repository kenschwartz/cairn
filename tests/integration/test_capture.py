"""
Gating tests for `cairn capture` (Phase 2).

Per docs/decisions.md "cairn capture" + DESIGN:466-531, 851:
- accepts exactly one content source (positional / --file / stdin); >1 fails.
- never prompts.
- title: --title, else first non-empty line of input truncated to 80, else
  note-<8hex>. body: the full input content.
- frontmatter: type=note, status=active, tags=[inbox] + any --tag (normalized),
  created/updated today, cairn_version 1.
- writes notes/<slug>.md via the shared slug rule + -2/-3 collision; never
  overwrites.
- auto-commits; message "cairn capture: <path>".
"""

import os
import subprocess
import sys
from pathlib import Path

import yaml

from cairn.frontmatter import read_frontmatter


def _capture(vault, args, input_text=None):
    """Run `cairn capture` in vault; return CompletedProcess."""
    env = os.environ.copy()
    return subprocess.run(
        ["cairn", "capture"] + args,
        cwd=str(vault),
        input=input_text,
        text=True,
        capture_output=True,
        env=env,
    )


def _read_note(vault, name):
    return read_frontmatter(vault / "notes" / name)


class TestCaptureSources:
    def test_positional_text_creates_inbox_note(self, tmp_vault):
        r = _capture(tmp_vault, ["First line of thought\nsecond line"])
        assert r.returncode == 0, r.stderr
        notes = list((tmp_vault / "notes").glob("*.md"))
        assert len(notes) == 1
        fm, body = read_frontmatter(notes[0])
        assert fm["title"] == "First line of thought"
        assert fm["type"] == "note"
        assert fm["status"] == "active"
        assert fm["tags"] == ["inbox"]
        assert fm["cairn_version"] == 1
        assert "second line" in body

    def test_title_flag_overrides_derived_title(self, tmp_vault):
        r = _capture(tmp_vault, ["some body text", "--title", "My Title"])
        assert r.returncode == 0, r.stderr
        notes = list((tmp_vault / "notes").glob("*.md"))
        fm, _ = read_frontmatter(notes[0])
        assert fm["title"] == "My Title"

    def test_file_source(self, tmp_vault):
        src = tmp_vault.parent / "paste.txt"
        src.write_text("From a file\nline two\n")
        r = _capture(tmp_vault, ["--file", str(src)])
        assert r.returncode == 0, r.stderr
        notes = list((tmp_vault / "notes").glob("*.md"))
        assert len(notes) == 1
        fm, body = read_frontmatter(notes[0])
        assert fm["title"] == "From a file"
        assert "line two" in body

    def test_stdin_source(self, tmp_vault):
        r = _capture(tmp_vault, ["--title", "Piped"], input_text="piped body\n")
        assert r.returncode == 0, r.stderr
        notes = list((tmp_vault / "notes").glob("*.md"))
        assert len(notes) == 1
        fm, body = read_frontmatter(notes[0])
        assert fm["title"] == "Piped"
        assert "piped body" in body

    def test_more_than_one_source_fails(self, tmp_vault):
        src = tmp_vault.parent / "p.txt"
        src.write_text("file content\n")
        # positional + --file
        r = _capture(tmp_vault, ["positional text", "--file", str(src)])
        assert r.returncode != 0, "two sources must fail"
        assert (tmp_vault / "notes").glob("*.md") is not None
        assert not list((tmp_vault / "notes").glob("*.md")), "no note on failure"

    def test_stdin_and_positional_fails(self, tmp_vault):
        r = _capture(tmp_vault, ["positional"], input_text="from stdin\n")
        assert r.returncode != 0, "stdin + positional must fail"
        assert not list((tmp_vault / "notes").glob("*.md"))


class TestCaptureFrontmatterAndTags:
    def test_extra_tag_added_and_normalized(self, tmp_vault):
        r = _capture(tmp_vault, ["body", "--tag", "CFG/Security", "--tag", "raw tag"])
        assert r.returncode == 0, r.stderr
        fm, _ = read_frontmatter(list((tmp_vault / "notes").glob("*.md"))[0])
        assert "inbox" in fm["tags"]
        assert "cfg/security" in fm["tags"]   # normalized, slash preserved
        assert "raw-tag" in fm["tags"]         # normalized

    def test_long_first_line_title_truncated_to_80(self, tmp_vault):
        long_line = "x" * 200
        r = _capture(tmp_vault, [long_line])
        assert r.returncode == 0, r.stderr
        fm, _ = read_frontmatter(list((tmp_vault / "notes").glob("*.md"))[0])
        assert len(fm["title"]) == 80
        assert fm["title"] == "x" * 80

    def test_collision_suffix_does_not_overwrite(self, tmp_vault):
        # Two captures whose first line slugifies the same -> -2 suffix, both kept.
        _capture(tmp_vault, ["Same title\none"])
        _capture(tmp_vault, ["Same title\ntwo"])
        names = sorted(p.name for p in (tmp_vault / "notes").glob("*.md"))
        assert len(names) == 2
        assert any("-2" in n for n in names), names


class TestCaptureCommit:
    def test_auto_commits_with_cairn_capture_message(self, tmp_vault):
        _capture(tmp_vault, ["Captured thought"])
        log = subprocess.run(
            ["git", "log", "--oneline"],
            cwd=str(tmp_vault), capture_output=True, text=True, env=os.environ.copy(),
        )
        assert "cairn capture:" in log.stdout
