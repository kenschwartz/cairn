"""
Gating tests for `cairn reindex` (Phase 3b).

Per docs/decisions.md "reindex is extensible" + DESIGN:818, 956: regenerate the
dashboard, the link cache, and (later) indexes via a pluggable generator list.
Auto-commits generated outputs that changed. Phase 4 adds indexes/tags.md to the
generator list; here we pin dashboard + link cache.
"""

import os
import subprocess
from pathlib import Path

from cairn.frontmatter import write_frontmatter


def _reindex(vault):
    return subprocess.run(
        ["cairn", "reindex"], cwd=str(vault),
        capture_output=True, text=True, env=os.environ.copy(),
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
    "tags": ["x"], "created": "2026-08-09", "updated": "2026-08-09",
    "cairn_version": 1, "moc": "", "source": "", "source_url": "",
}


class TestReindex:
    def test_generates_dashboard(self, tmp_vault):
        _note(tmp_vault, "a.md", dict(FM, id="a1", title="Indexed Note"), "x\n")
        r = _reindex(tmp_vault)
        assert r.returncode == 0, r.stderr
        assert (tmp_vault / "dashboard.md").exists()
        assert "Indexed Note" in (tmp_vault / "dashboard.md").read_text()

    def test_rebuilds_link_cache(self, tmp_vault):
        _note(tmp_vault, "a.md", dict(FM, id="a1", title="A"), "[[B]]\n")
        _note(tmp_vault, "b.md", dict(FM, id="b1", title="B"), "x\n")
        _reindex(tmp_vault)
        cache = Path(os.environ["XDG_CACHE_HOME"]) / "cairn" / "links.json"
        assert cache.exists()

    def test_commits_generated_dashboard(self, tmp_vault):
        _note(tmp_vault, "a.md", dict(FM, id="a1", title="Commit Me"), "x\n")
        _reindex(tmp_vault)
        log = _git(["log", "--oneline"], tmp_vault).stdout
        assert "dashboard" in log.lower() or "reindex" in log.lower() or "regenerate" in log.lower()
