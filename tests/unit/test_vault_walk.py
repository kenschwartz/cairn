"""
Gating tests for cairn.vault.iter_notes / iter_notes_and_moc (Track B prereq).

The shared notes walker every read-side command needs. Phase 1 has no walker;
each read command would otherwise re-glob. Contract per docs/decisions.md
"iter_notes / iter_notes_and_moc": notes live directly under notes/ (not
recursive), sorted by relative path for deterministic output.
"""

from pathlib import Path

from cairn.vault import iter_notes, iter_notes_and_moc


class TestIterNotes:
    def test_lists_markdown_under_notes_sorted(self, tmp_path):
        v = tmp_path / "vault"
        (v / "notes").mkdir(parents=True)
        for name in ["c.md", "a.md", "b.md"]:
            (v / "notes" / name).write_text("x")
        result = iter_notes(v)
        rels = [p.relative_to(v).as_posix() for p in result]
        assert rels == ["notes/a.md", "notes/b.md", "notes/c.md"]

    def test_excludes_non_markdown(self, tmp_path):
        v = tmp_path / "vault"
        (v / "notes").mkdir(parents=True)
        (v / "notes" / "keep.md").write_text("x")
        (v / "notes" / "drop.txt").write_text("x")
        (v / "notes" / "also_drop").write_text("x")
        result = iter_notes(v)
        rels = [p.relative_to(v).as_posix() for p in result]
        assert rels == ["notes/keep.md"]

    def test_empty_notes_dir_returns_empty(self, tmp_path):
        v = tmp_path / "vault"
        (v / "notes").mkdir(parents=True)
        assert iter_notes(v) == []

    def test_not_recursive(self, tmp_path):
        # DESIGN:304 - notes live directly under notes/, no deep topic folders.
        v = tmp_path / "vault"
        (v / "notes" / "topic").mkdir(parents=True)
        (v / "notes" / "top.md").write_text("x")
        (v / "notes" / "topic" / "nested.md").write_text("x")
        result = iter_notes(v)
        rels = [p.relative_to(v).as_posix() for p in result]
        assert rels == ["notes/top.md"]


class TestIterNotesAndMoc:
    def test_union_of_notes_and_moc_sorted(self, tmp_path):
        v = tmp_path / "vault"
        (v / "notes").mkdir(parents=True)
        (v / "moc").mkdir(parents=True)
        (v / "notes" / "n1.md").write_text("x")
        (v / "moc" / "m1.md").write_text("x")
        (v / "notes" / "n2.md").write_text("x")
        result = iter_notes_and_moc(v)
        rels = [p.relative_to(v).as_posix() for p in result]
        # moc/ sorts before notes/
        assert rels == ["moc/m1.md", "notes/n1.md", "notes/n2.md"]

    def test_empty_when_both_empty(self, tmp_path):
        v = tmp_path / "vault"
        (v / "notes").mkdir(parents=True)
        (v / "moc").mkdir(parents=True)
        assert iter_notes_and_moc(v) == []
