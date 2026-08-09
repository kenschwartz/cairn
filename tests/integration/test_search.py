"""
Gating tests for `cairn search` (Phase 3).

Per docs/decisions.md "Search sort + scope" + DESIGN:640-670:
- `cairn search "query"`: case-insensitive substring over body, title, source.
- Structured filters --tag/--type/--status/--project: exact normalized match,
  AND-combined. Multiple --tag require ALL. Tags compared through the write
  normalizer.
- No text query AND no filter -> fails clearly (does not dump the vault).
- Filter-only (>=1 filter, no text) works.
- Malformed-file rule (DESIGN:670): frontmatter filters never match a malformed
  note; a text query MAY match a malformed note's body, flagged with a warning.
- Read-only: never commits.
- Scope: notes/ + moc/. Results sorted by relative path ascending.
"""

import os
import subprocess
from pathlib import Path

from cairn.frontmatter import write_frontmatter


def _search(vault, args):
    return subprocess.run(
        ["cairn", "search"] + args,
        cwd=str(vault), capture_output=True, text=True, env=os.environ.copy(),
    )


def _note(vault, name, fm, body=""):
    (vault / "notes" / name).write_text(write_frontmatter(fm) + body)


BASE = {
    "id": "aaaa0000", "title": "T", "type": "note", "status": "active",
    "project": "", "tags": ["x"], "created": "2026-08-09", "updated": "2026-08-09",
    "cairn_version": 1, "moc": "", "source": "", "source_url": "",
}


class TestSearchText:
    def test_text_match_case_insensitive(self, tmp_vault):
        _note(tmp_vault, "a.md", dict(BASE, id="a1", title="Alpha"), "Contains BANANA text\n")
        r = _search(tmp_vault, ["banana"])
        assert r.returncode == 0
        assert "Alpha" in r.stdout

    def test_matches_title_and_source(self, tmp_vault):
        _note(tmp_vault, "t.md", dict(BASE, id="t1", title="Quarterly Review", source="Outlook 2026-08"), "body\n")
        r = _search(tmp_vault, ["quarterly"])
        assert "Quarterly Review" in r.stdout
        r2 = _search(tmp_vault, ["outlook"])
        assert "Quarterly Review" in r2.stdout

    def test_no_query_and_no_filter_fails(self, tmp_vault):
        _note(tmp_vault, "a.md", dict(BASE, id="a1", title="A"), "x\n")
        r = _search(tmp_vault, [])
        assert r.returncode != 0, "bare 'cairn search' must fail, not dump the vault"


class TestSearchFilters:
    def test_tag_filter_uses_normalizer(self, tmp_vault):
        _note(tmp_vault, "a.md", dict(BASE, id="a1", title="A", tags=["cfg/security"]), "x\n")
        _note(tmp_vault, "b.md", dict(BASE, id="b1", title="B", tags=["other"]), "x\n")
        r = _search(tmp_vault, ["--tag", "CFG/Security"])  # normalized to cfg/security
        assert r.returncode == 0
        assert "A" in r.stdout and "B" not in r.stdout

    def test_multiple_tags_all_required(self, tmp_vault):
        _note(tmp_vault, "a.md", dict(BASE, id="a1", title="A", tags=["alpha", "beta"]), "x\n")
        _note(tmp_vault, "b.md", dict(BASE, id="b1", title="B", tags=["alpha"]), "x\n")
        r = _search(tmp_vault, ["--tag", "alpha", "--tag", "beta"])
        assert "A" in r.stdout and "B" not in r.stdout

    def test_type_status_project_filters_and_combine(self, tmp_vault):
        _note(tmp_vault, "a.md", dict(BASE, id="a1", title="A", type="project", status="active", project="cfg"), "x\n")
        _note(tmp_vault, "b.md", dict(BASE, id="b1", title="B", type="note", status="active", project="cfg"), "x\n")
        r = _search(tmp_vault, ["--type", "project", "--status", "active", "--project", "cfg"])
        assert "A" in r.stdout and "B" not in r.stdout

    def test_filter_only_no_text_works(self, tmp_vault):
        _note(tmp_vault, "a.md", dict(BASE, id="a1", title="A", status="waiting"), "x\n")
        r = _search(tmp_vault, ["--status", "waiting"])
        assert "A" in r.stdout


class TestSearchReadonlyAndScope:
    def test_does_not_commit(self, tmp_vault):
        _note(tmp_vault, "a.md", dict(BASE, id="a1", title="A"), "findme\n")
        before = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(tmp_vault),
                                capture_output=True, text=True, env=os.environ.copy()).stdout.strip()
        _search(tmp_vault, ["findme"])
        after = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(tmp_vault),
                               capture_output=True, text=True, env=os.environ.copy()).stdout.strip()
        assert before == after
