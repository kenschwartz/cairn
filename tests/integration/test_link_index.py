"""
Gating tests for the link index (Phase 3, internal infra for rename + future
backlinks). Per docs/decisions.md "links.json record schema".

Public API (GLM-defined; builder implements in a new `cairn.links` module):
- build_index(vault: Path) -> dict : scan notes/ + moc/, return
  {rel_path: {title, title_norm, outbound_wikilinks:[targets], outbound_mdlinks:[targets], headings:[]}}.
  Persists to the cache file at $XDG_CACHE_HOME/cairn/links.json.
- inbound_links(index: dict, title: str) -> list[str] : rel_paths of notes whose
  outbound wikilinks normalize-match the given title (the reverse map; backs the
  rename broken-link report).

Wiki-link target extraction: `[[Target]]` and `[[Other|display]]` -> targets
"Target", "Other" (the part before `|`, before `#`).
"""

import os
from pathlib import Path

import pytest

from cairn.frontmatter import write_frontmatter
from cairn.links import build_index, inbound_links


FM = {
    "id": "z", "title": "T", "type": "note", "status": "active", "project": "",
    "tags": ["x"], "created": "2026-08-09", "updated": "2026-08-09",
    "cairn_version": 1, "moc": "", "source": "", "source_url": "",
}


def _note(vault, folder, name, fm, body):
    d = vault / folder
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(write_frontmatter(fm) + body)


class TestBuildIndex:
    def test_extracts_outbound_wikilinks(self, tmp_path):
        v = tmp_path / "vault"
        _note(v, "notes", "src.md", dict(FM, id="s1", title="Source"),
              "See [[Target]] and [[Other|display name]].\n")
        idx = build_index(v)
        rec = idx["notes/src.md"]
        assert "Target" in rec["outbound_wikilinks"]
        assert "Other" in rec["outbound_wikilinks"]

    def test_records_title_and_normalized_title(self, tmp_path):
        v = tmp_path / "vault"
        _note(v, "notes", "a.md", dict(FM, id="a1", title="Trade Finance"), "x\n")
        idx = build_index(v)
        rec = idx["notes/a.md"]
        assert rec["title"] == "Trade Finance"
        # title_norm lowercases and collapses whitespace per the resolver rule
        assert rec["title_norm"] == "trade finance"

    def test_scope_includes_moc(self, tmp_path):
        v = tmp_path / "vault"
        _note(v, "notes", "n.md", dict(FM, id="n1", title="Note"), "x\n")
        _note(v, "moc", "m.md", dict(FM, id="m1", title="Map"), "[[Note]]\n")
        idx = build_index(v)
        assert "moc/m.md" in idx
        assert "notes/n.md" in idx

    def test_persists_cache_file(self, tmp_path):
        v = tmp_path / "vault"
        _note(v, "notes", "a.md", dict(FM, id="a1", title="A"), "[[B]]\n")
        build_index(v)
        cache = Path(os.environ["XDG_CACHE_HOME"]) / "cairn" / "links.json"
        assert cache.exists(), "index must persist to $XDG_CACHE_HOME/cairn/links.json"


class TestInboundLinks:
    def test_reverse_map_finds_linkers(self, tmp_path):
        v = tmp_path / "vault"
        _note(v, "notes", "target.md", dict(FM, id="t1", title="Target"), "body\n")
        _note(v, "notes", "linker.md", dict(FM, id="l1", title="Linker"), "refs [[Target]]\n")
        idx = build_index(v)
        linkers = inbound_links(idx, "Target")
        assert "notes/linker.md" in linkers
        assert "notes/target.md" not in linkers

    def test_inbound_normalizes_case_and_whitespace(self, tmp_path):
        v = tmp_path / "vault"
        _note(v, "notes", "t.md", dict(FM, id="t1", title="Trade Finance"), "x\n")
        _note(v, "notes", "l.md", dict(FM, id="l1", title="L"), "see [[trade finance]]\n")
        idx = build_index(v)
        assert "notes/l.md" in inbound_links(idx, "Trade Finance")
