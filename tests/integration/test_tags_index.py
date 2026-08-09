"""
Gating tests for the tags index (Phase 4).

Per docs/decisions.md Q004-2: `cairn reindex` generates `indexes/tags.md` -
committed, one `## tag` section per tag (alpha-sorted), each with bulleted
backlinks to the notes carrying it. Built by reindex (the extensible generator
list from Phase 3b gets tags.md added).
"""

import os
import subprocess
from pathlib import Path

from cairn.frontmatter import write_frontmatter


def _reindex(vault):
    return subprocess.run(["cairn", "reindex"], cwd=str(vault),
                          capture_output=True, text=True, env=os.environ.copy())


def _git(args, vault):
    return subprocess.run(["git"] + args, cwd=str(vault),
                          capture_output=True, text=True, env=os.environ.copy())


def _note(vault, name, fm, body=""):
    (vault / "notes" / name).write_text(write_frontmatter(fm) + body)
    _git(["add", "notes"], vault)
    _git(["commit", "-m", "seed"], vault)


FM = {
    "id": "z", "title": "T", "type": "note", "status": "active", "project": "",
    "tags": ["x"], "created": "2026-08-09", "updated": "2026-08-09",
    "cairn_version": 1, "moc": "", "source": "", "source_url": "",
}


class TestTagsIndex:
    def test_reindex_generates_tags_index(self, tmp_vault):
        _note(tmp_vault, "a.md", dict(FM, id="a1", title="Alpha Note", tags=["beta", "alpha"]), "x\n")
        _note(tmp_vault, "b.md", dict(FM, id="b1", title="Bravo Note", tags=["alpha"]), "x\n")
        r = _reindex(tmp_vault)
        assert r.returncode == 0, r.stderr
        idx = tmp_vault / "indexes" / "tags.md"
        assert idx.exists()
        text = idx.read_text()
        # one section per tag, alpha-sorted: alpha before beta
        assert "## alpha" in text
        assert "## beta" in text
        assert text.index("## alpha") < text.index("## beta")
        # backlinks to carrying notes
        assert "Alpha Note" in text
        assert "Bravo Note" in text

    def test_tags_index_is_committed(self, tmp_vault):
        _note(tmp_vault, "a.md", dict(FM, id="a1", title="A", tags=["t"]), "x\n")
        _reindex(tmp_vault)
        show = _git(["show", "--name-only", "HEAD"], tmp_vault).stdout
        assert "indexes/tags.md" in show
