"""
Gating tests for `cairn validate` (Phase 2, schema-only scope per DESIGN:845).

Per docs/decisions.md "validate / search output" + "validate scope gate":
- schema-only: missing frontmatter, missing/empty required fields, invalid
  type, invalid status, missing tags, malformed dates, inbox-relaxed.
- DEFERRED (not Phase 2): wiki-link, markdown-link, asset-link, generated-file
  staleness. validate must run with NO link index and contain no link code paths.
- exit code: errors -> non-zero; warnings-only -> zero; always a summary.

Required non-empty fields (DESIGN:849): id, title, type, status, tags,
created, updated, cairn_version. Optional (may be empty): project, moc, source,
source_url.

NOTE: "duplicate note filenames" (DESIGN:834) is NOT pinned here. In the flat
notes/ layout filenames are unique by construction, so the rule's meaning is
ambiguous (likely related to the deferred Phase-3 ambiguity check). Deferred.
"""

import os
import subprocess
from pathlib import Path

from cairn.frontmatter import write_frontmatter


def _validate(vault):
    return subprocess.run(
        ["cairn", "validate"],
        cwd=str(vault), capture_output=True, text=True, env=os.environ.copy(),
    )


def _write_note(vault, name, fm, body="body\n"):
    (vault / "notes" / name).write_text(write_frontmatter(fm) + body)


VALID_FM = {
    "id": "abc12345", "title": "Valid", "type": "note", "status": "active",
    "project": "", "tags": ["x"], "created": "2026-08-09", "updated": "2026-08-09",
    "cairn_version": 1, "moc": "", "source": "", "source_url": "",
}


class TestValidateClean:
    def test_clean_vault_passes_with_summary(self, tmp_vault):
        _write_note(tmp_vault, "ok.md", VALID_FM)
        r = _validate(tmp_vault)
        assert r.returncode == 0, r.stderr
        assert "0 error" in r.stdout.lower() or "no error" in r.stdout.lower()


class TestValidateSchemaErrors:
    def test_missing_frontmatter_is_error(self, tmp_vault):
        (tmp_vault / "notes" / "bare.md").write_text("no frontmatter here\n")
        r = _validate(tmp_vault)
        assert r.returncode != 0

    def test_missing_required_field_is_error(self, tmp_vault):
        fm = dict(VALID_FM)
        del fm["title"]
        _write_note(tmp_vault, "notitle.md", fm)
        r = _validate(tmp_vault)
        assert r.returncode != 0

    def test_empty_required_field_is_error(self, tmp_vault):
        fm = dict(VALID_FM)
        fm["status"] = ""          # required-non-empty
        _write_note(tmp_vault, "emptystatus.md", fm)
        r = _validate(tmp_vault)
        assert r.returncode != 0

    def test_invalid_type_is_error(self, tmp_vault):
        fm = dict(VALID_FM)
        fm["type"] = "bogus"
        _write_note(tmp_vault, "badtype.md", fm)
        r = _validate(tmp_vault)
        assert r.returncode != 0

    def test_invalid_status_is_error(self, tmp_vault):
        fm = dict(VALID_FM)
        fm["status"] = "frozen"
        _write_note(tmp_vault, "badstatus.md", fm)
        r = _validate(tmp_vault)
        assert r.returncode != 0

    def test_missing_tags_is_error(self, tmp_vault):
        fm = dict(VALID_FM)
        fm["tags"] = []
        _write_note(tmp_vault, "notags.md", fm)
        r = _validate(tmp_vault)
        assert r.returncode != 0

    def test_malformed_date_is_error(self, tmp_vault):
        fm = dict(VALID_FM)
        fm["created"] = "2026/08/09"      # not YYYY-MM-DD
        _write_note(tmp_vault, "baddate.md", fm)
        r = _validate(tmp_vault)
        assert r.returncode != 0

    def test_optional_field_empty_is_not_error(self, tmp_vault):
        # project/moc/source/source_url may be empty.
        _write_note(tmp_vault, "opt.md", VALID_FM)
        r = _validate(tmp_vault)
        assert r.returncode == 0, r.stderr


class TestValidateInboxRelaxed:
    def test_inbox_note_skips_type_and_status_checks(self, tmp_vault):
        fm = dict(VALID_FM)
        fm["tags"] = ["inbox"]
        fm["type"] = "bogus"          # would fail strict; relaxed skips it
        fm["status"] = "frozen"       # would fail strict; relaxed skips it
        _write_note(tmp_vault, "inbox.md", fm)
        r = _validate(tmp_vault)
        assert r.returncode == 0, r.stderr

    def test_inbox_note_still_requires_nonempty_fields(self, tmp_vault):
        fm = dict(VALID_FM)
        fm["tags"] = ["inbox"]
        fm["title"] = ""              # required-non-empty even when relaxed
        _write_note(tmp_vault, "inboxempty.md", fm)
        r = _validate(tmp_vault)
        assert r.returncode != 0


class TestValidateOutput:
    def test_duplicate_filename_across_notes_and_moc_is_error(self, tmp_vault):
        # DESIGN:834 - same basename in notes/ and moc/ is an ambiguous collision.
        (tmp_vault / "moc").mkdir(exist_ok=True)
        _write_note(tmp_vault, "dup.md", VALID_FM)
        moc_fm = dict(VALID_FM, id="moc00001")
        (tmp_vault / "moc" / "dup.md").write_text(write_frontmatter(moc_fm) + "x\n")
        r = _validate(tmp_vault)
        assert r.returncode != 0
        assert "duplicate note filename" in r.stdout.lower()

    def test_summary_counts_present(self, tmp_vault):
        _write_note(tmp_vault, "ok.md", VALID_FM)
        r = _validate(tmp_vault)
        # summary line names error and warning counts
        assert "error" in r.stdout.lower()

    def test_read_only_does_not_commit(self, tmp_vault):
        before = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(tmp_vault),
            capture_output=True, text=True, env=os.environ.copy(),
        ).stdout.strip()
        _write_note(tmp_vault, "ok.md", VALID_FM)
        _validate(tmp_vault)
        after = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(tmp_vault),
            capture_output=True, text=True, env=os.environ.copy(),
        ).stdout.strip()
        assert before == after, "validate must not create a commit"
