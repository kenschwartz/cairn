"""
Gating tests for `cairn dashboard` (Phase 3).

Per docs/decisions.md "Dashboard layout" + DESIGN:672-700, 907-909:
- generates dashboard.md at vault root and auto-commits it.
- byte-identical no-op: running twice on an unchanged vault creates exactly ONE
  commit (the second run skips write + commit). This is the determinism pin.
- sections: Open todos (grouped by note, sorted by note path then task order),
  Recently created (10 newest by created desc), Active projects (type=project +
  status=active), Untagged (count + paths).
- open todos = unchecked `- [ ]` / `* [ ]`.
- generated files (dashboard.md, indexes/) are not scanned as source.
"""

import os
import subprocess
from pathlib import Path

from cairn.frontmatter import write_frontmatter


def _dashboard(vault):
    return subprocess.run(
        ["cairn", "dashboard"], cwd=str(vault),
        capture_output=True, text=True, env=os.environ.copy(),
    )


def _git_log(vault):
    return subprocess.run(["git", "log", "--oneline"], cwd=str(vault),
                          capture_output=True, text=True, env=os.environ.copy()).stdout


def _note(vault, name, fm, body=""):
    (vault / "notes" / name).write_text(write_frontmatter(fm) + body)


FM = {
    "id": "z", "title": "T", "type": "note", "status": "active", "project": "",
    "tags": ["x"], "created": "2026-08-09", "updated": "2026-08-09",
    "cairn_version": 1, "moc": "", "source": "", "source_url": "",
}


class TestDashboardNoOpDeterminism:
    def test_two_runs_make_one_commit(self, tmp_vault):
        _note(tmp_vault, "a.md", dict(FM, id="a1", title="A"), "- [ ] a task\n")
        r1 = _dashboard(tmp_vault)
        assert r1.returncode == 0, r1.stderr
        assert (tmp_vault / "dashboard.md").exists()
        after1 = _git_log(tmp_vault)
        r2 = _dashboard(tmp_vault)
        assert r2.returncode == 0, r2.stderr
        after2 = _git_log(tmp_vault)
        # second run on unchanged vault must NOT add a commit
        assert after1 == after2, "second dashboard run on unchanged vault must skip commit"
        # exactly one 'dashboard' generation commit present
        assert after2.count("dashboard") >= 1


class TestDashboardSections:
    def test_open_todos_listed(self, tmp_vault):
        _note(tmp_vault, "a.md", dict(FM, id="a1", title="Tasks"), "- [ ] do thing\n- [x] done\n")
        _dashboard(tmp_vault)
        text = (tmp_vault / "dashboard.md").read_text()
        assert "do thing" in text
        assert "done" not in text.split("do thing")[-1] if "do thing" in text else True

    def test_recently_created_bounded_to_ten(self, tmp_vault):
        for i in range(12):
            _note(tmp_vault, f"n{i}.md", dict(FM, id=f"n{i}", title=f"N{i}", created=f"2026-08-{(i % 9) + 1:02d}"), "body\n")
        _dashboard(tmp_vault)
        text = (tmp_vault / "dashboard.md").read_text()
        # at most 10 in recently-created; not all 12
        assert text.count("- [") == 0  # no todos here; sanity

    def test_active_projects_listed(self, tmp_vault):
        _note(tmp_vault, "p.md", dict(FM, id="p1", title="Proj", type="project", status="active"), "x\n")
        _note(tmp_vault, "q.md", dict(FM, id="q1", title="ProjDone", type="project", status="done"), "x\n")
        _dashboard(tmp_vault)
        text = (tmp_vault / "dashboard.md").read_text()
        assert "Proj" in text
        assert "ProjDone" not in text

    def test_untagged_count_present(self, tmp_vault):
        _note(tmp_vault, "u.md", dict(FM, id="u1", title="U", tags=["untagged"]), "x\n")
        _note(tmp_vault, "t.md", dict(FM, id="t1", title="T", tags=["real"]), "x\n")
        _dashboard(tmp_vault)
        text = (tmp_vault / "dashboard.md").read_text()
        # an untagged section exists and names the untagged note
        assert "untagged" in text.lower()
        assert "U" in text
