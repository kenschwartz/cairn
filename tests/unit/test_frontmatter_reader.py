"""
Gating tests for cairn.frontmatter.read_frontmatter (Track B prerequisite).

read_frontmatter(path) -> (frontmatter_dict, body_str) is the shared reader every
read-side command (validate, search, dashboard, rename, tags) needs. Phase 1
shipped only a writer. The contract is pinned here before the implementation
lands, per docs/decisions.md "read_frontmatter".
"""

from pathlib import Path

import pytest

from cairn.frontmatter import read_frontmatter, write_frontmatter


class TestReadFrontmatter:
    def test_reads_frontmatter_and_body(self, tmp_path):
        note = tmp_path / "n.md"
        note.write_text(
            "---\n"
            "title: Hello\n"
            "type: note\n"
            "---\n"
            "This is the body.\n"
        )
        fm, body = read_frontmatter(note)
        assert fm["title"] == "Hello"
        assert fm["type"] == "note"
        assert body == "This is the body.\n"

    def test_round_trips_with_write_frontmatter(self, tmp_path):
        data = {
            "id": "abc12345",
            "title": "Round trip",
            "type": "note",
            "status": "active",
            "project": "",
            "tags": ["cfg/security", "onboard"],
            "created": "2026-08-09",
            "updated": "2026-08-09",
            "cairn_version": 1,
            "moc": "",
            "source": "",
            "source_url": "",
        }
        note = tmp_path / "rt.md"
        note.write_text(write_frontmatter(data) + "Body line.\n")
        fm, body = read_frontmatter(note)
        assert fm == data
        assert body == "Body line.\n"

    def test_body_with_multiple_paragraphs_preserved(self, tmp_path):
        note = tmp_path / "p.md"
        note.write_text(
            "---\n"
            "title: Multi\n"
            "---\n"
            "First paragraph.\n"
            "\n"
            "Second paragraph.\n"
        )
        fm, body = read_frontmatter(note)
        assert fm["title"] == "Multi"
        assert body == "First paragraph.\n\nSecond paragraph.\n"

    def test_empty_frontmatter_block_returns_empty_dict(self, tmp_path):
        note = tmp_path / "e.md"
        note.write_text("---\n" "---\n" "body only\n")
        fm, body = read_frontmatter(note)
        assert fm == {}
        assert body == "body only\n"

    def test_no_frontmatter_raises(self, tmp_path):
        # A note without a frontmatter block is malformed for cairn; surface it,
        # do not silently return an empty dict (that hides broken notes).
        note = tmp_path / "bad.md"
        note.write_text("Just a body with no frontmatter.\n")
        with pytest.raises(ValueError):
            read_frontmatter(note)

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises((FileNotFoundError, OSError, ValueError)):
            read_frontmatter(tmp_path / "nope.md")

    def test_tags_list_preserved_as_list(self, tmp_path):
        note = tmp_path / "t.md"
        note.write_text(
            "---\n"
            "title: T\n"
            "tags:\n"
            "- alpha\n"
            "- beta\n"
            "---\n"
            "body\n"
        )
        fm, body = read_frontmatter(note)
        assert fm["tags"] == ["alpha", "beta"]
