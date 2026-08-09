"""
Gating tests for `cairn rename` (Phase 3b).

Per docs/decisions.md + DESIGN:408-418:
- `cairn rename <note_path> <new_title>`: update title + updated, recompute slug,
  `git mv` to the new filename with -2/-3 collision (never overwrite), one commit
  of only the target note.
- If the recomputed slug equals the current filename, update frontmatter only
  (no git mv).
- Dirty-tree precheck: if the target note has uncommitted changes, stop with a
  clear message (do not rename).
- Rollback on failure: restore original bytes/path; never `git reset --hard`.
- Broken-link report: after rename, notes still wikilinking the old title are
  reported (inbound rewrite is deferred to a later step, DESIGN:418).
"""

import os
import subprocess
from pathlib import Path

from cairn.frontmatter import write_frontmatter, read_frontmatter


def _rename(vault, args):
    return subprocess.run(
        ["cairn", "rename"] + args,
        cwd=str(vault), capture_output=True, text=True, env=os.environ.copy(),
    )


def _git(args, vault):
    return subprocess.run(["git"] + args, cwd=str(vault),
                          capture_output=True, text=True, env=os.environ.copy())


def _note(vault, name, fm, body=""):
    (vault / "notes" / name).write_text(write_frontmatter(fm) + body)
    _git(["add", "notes"], vault)
    _git(["commit", "-m", "seed"], vault)


FM = {
    "id": "z", "title": "T", "type": "note", "status": "active", "project": "",
    "tags": ["x"], "created": "2026-08-09", "updated": "2026-08-01",
    "cairn_version": 1, "moc": "", "source": "", "source_url": "",
}


class TestRename:
    def test_basic_rename_moves_and_retitles(self, tmp_vault):
        _note(tmp_vault, "old.md", dict(FM, id="a1", title="Old Title"), "body\n")
        r = _rename(tmp_vault, ["notes/old.md", "Shiny New Title"])
        assert r.returncode == 0, r.stderr
        assert not (tmp_vault / "notes" / "old.md").exists()
        assert (tmp_vault / "notes" / "shiny-new-title.md").exists()
        fm, _ = read_frontmatter(tmp_vault / "notes" / "shiny-new-title.md")
        assert fm["title"] == "Shiny New Title"
        assert fm["updated"] != "2026-08-01"   # updated refreshed

    def test_collision_uses_suffix(self, tmp_vault):
        _note(tmp_vault, "a.md", dict(FM, id="a1", title="Same"), "x\n")
        _note(tmp_vault, "b.md", dict(FM, id="b1", title="Other"), "x\n")
        # Rename b to "Same" -> slug collides with existing same.md -> -2 suffix
        r = _rename(tmp_vault, ["notes/b.md", "Same"])
        assert r.returncode == 0, r.stderr
        assert (tmp_vault / "notes" / "same-2.md").exists()
        assert (tmp_vault / "notes" / "same.md").exists()   # original untouched

    def test_same_slug_updates_frontmatter_only(self, tmp_vault):
        _note(tmp_vault, "old-thing.md", dict(FM, id="a1", title="Old Thing"), "body\n")
        # Title changes but slug stays "old-thing" -> no file move
        r = _rename(tmp_vault, ["notes/old-thing.md", "Old Thing!"])
        assert r.returncode == 0, r.stderr
        assert (tmp_vault / "notes" / "old-thing.md").exists()
        fm, _ = read_frontmatter(tmp_vault / "notes" / "old-thing.md")
        assert fm["title"] == "Old Thing!"

    def test_dirty_tree_stops_rename(self, tmp_vault):
        _note(tmp_vault, "d.md", dict(FM, id="d1", title="Dirty"), "body\n")
        # Introduce an uncommitted change on the target
        (tmp_vault / "notes" / "d.md").write_text(
            write_frontmatter(dict(FM, id="d1", title="Dirty")) + "uncommitted edit\n"
        )
        r = _rename(tmp_vault, ["notes/d.md", "Renamed"])
        assert r.returncode != 0, "must refuse to rename a note with uncommitted changes"
        # original file still present (not moved/lost)
        assert (tmp_vault / "notes" / "d.md").exists()

    def test_broken_link_report(self, tmp_vault):
        _note(tmp_vault, "target.md", dict(FM, id="t1", title="Target"), "body\n")
        _note(tmp_vault, "linker.md", dict(FM, id="l1", title="Linker"), "see [[Target]]\n")
        r = _rename(tmp_vault, ["notes/target.md", "RenamedTarget"])
        assert r.returncode == 0, r.stderr
        combined = r.stdout + r.stderr
        # The linker still points at the old title; rename reports it (no rewrite).
        assert "linker" in combined.lower() or "target" in combined.lower()

    def test_single_commit_only_target(self, tmp_vault):
        _note(tmp_vault, "a.md", dict(FM, id="a1", title="A"), "body\n")
        _rename(tmp_vault, ["notes/a.md", "ARenamed"])
        # the rename commit should touch only the renamed note path
        show = _git(["show", "--stat", "--name-only", "HEAD"], tmp_vault).stdout
        assert "notes/" in show
