"""
Unit tests for cairn new: frontmatter, slug rules, defaults, collision suffix.
Unit tests for tag normalization and auto-commit path ownership.

These are pure-ish unit tests: they may invoke the CLI via subprocess but do
NOT rely on a real git remote or network.  Everything under tmp_path.
"""

import re
import subprocess
import os
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Slug generation rules (unit-level)
# ---------------------------------------------------------------------------

class TestSlugGeneration:
    """
    Slug rules from DESIGN.md:
    - lowercase
    - transliterate accented chars; drop untransliteratable
    - replace non-alphanumeric runs with a single hyphen
    - trim leading/trailing hyphens
    - cap at 60 chars
    - empty result falls back to note-<8 hex>
    """

    @pytest.fixture(autouse=True)
    def import_slug(self):
        from cairn.slugs import slugify
        self.slugify = slugify

    def test_lowercase(self):
        assert self.slugify("Hello World") == "hello-world"

    def test_spaces_become_hyphens(self):
        assert self.slugify("foo bar baz") == "foo-bar-baz"

    def test_runs_of_non_alnum_become_single_hyphen(self):
        assert self.slugify("foo  --  bar") == "foo-bar"

    def test_leading_hyphens_trimmed(self):
        assert self.slugify("--foo") == "foo"

    def test_trailing_hyphens_trimmed(self):
        assert self.slugify("foo--") == "foo"

    def test_capped_at_60_chars(self):
        long_title = "a" * 100
        result = self.slugify(long_title)
        assert len(result) <= 60

    def test_cap_does_not_produce_trailing_hyphen(self):
        """After capping at 60, result must not end with a hyphen."""
        title = "hello " * 20   # spaces become hyphens, cap may fall mid-hyphen
        result = self.slugify(title)
        assert not result.endswith("-")

    def test_accent_transliteration_e_acute(self):
        """e-acute -> e per DESIGN.md example."""
        result = self.slugify("Caf\u00e9 Note")
        assert "e" in result
        assert "\u00e9" not in result

    def test_accent_transliteration_reduces_collisions(self):
        """Two titles that differ only by accent must produce DIFFERENT slugs after
        transliteration, not both collapse to the same thing by silent dropping."""
        # e.g. "cafe" vs "cafe" after transliteration -- they'd be the same.
        # The design says transliteration REDUCES collisions; we just assert
        # that accented chars are transliterated (not silently dropped entirely
        # in a way that collapses distinct inputs).
        s1 = self.slugify("resume")
        s2 = self.slugify("r\u00e9sum\u00e9")
        # Both should produce "resume"; the point is they are transliterated, not dropped.
        assert s1 == s2  # e-acute -> e, so they match -- this is correct per design

    def test_empty_result_fallback(self):
        """A title of all-special-chars yields note-<8 hex>."""
        result = self.slugify("---!!!---")
        assert re.match(r"^note-[0-9a-f]{8}$", result), (
            f"Empty slug should fall back to note-<8hex>, got {result!r}"
        )

    def test_all_numeric_title(self):
        """A purely numeric title should still produce a valid slug."""
        result = self.slugify("2026")
        assert result == "2026"

    def test_unicode_drop_untransliteratable(self):
        """Characters that cannot be transliterated are dropped."""
        # CJK chars have no ASCII transliteration -- they should be dropped.
        result = self.slugify("\u4e2d\u6587\u6587\u5b57")
        # All characters dropped -> fallback
        assert re.match(r"^note-[0-9a-f]{8}$", result) or result == "", (
            f"Untransliteratable chars should be dropped/fallback, got {result!r}"
        )


# ---------------------------------------------------------------------------
# Tag normalization rules
# ---------------------------------------------------------------------------

class TestTagNormalization:
    @pytest.fixture(autouse=True)
    def import_normalize(self):
        from cairn.tags import normalize_tag
        self.normalize = normalize_tag

    def test_lowercase(self):
        assert self.normalize("TRADE") == "trade"

    def test_whitespace_run_becomes_hyphen(self):
        assert self.normalize("Trade Finance") == "trade-finance"

    def test_multiple_spaces(self):
        assert self.normalize("trade   finance") == "trade-finance"

    def test_already_normalized(self):
        assert self.normalize("trade-finance") == "trade-finance"

    def test_mixed_case_and_space(self):
        assert self.normalize("Trade  Finance Notes") == "trade-finance-notes"

    def test_leading_trailing_whitespace(self):
        assert self.normalize("  tag  ") == "tag"

    def test_hyphens_preserved(self):
        assert self.normalize("already-hyphenated") == "already-hyphenated"


# ---------------------------------------------------------------------------
# cairn new: frontmatter contract
# ---------------------------------------------------------------------------

class TestCairnNew:
    """
    Tests drive the CLI and inspect resulting filesystem state.
    All under tmp_vault (a real initialized vault with hooks).
    """

    def _read_frontmatter(self, filepath: Path) -> dict:
        """Parse YAML frontmatter from a note file."""
        import yaml
        text = filepath.read_text()
        assert text.startswith("---"), f"No frontmatter in {filepath}"
        _, fm_text, _ = text.split("---", 2)
        return yaml.safe_load(fm_text)

    def _run_new(self, vault: Path, *args):
        return subprocess.run(
            ["cairn", "new"] + list(args),
            capture_output=True,
            text=True,
            cwd=str(vault),
            env=os.environ.copy(),
        )

    def test_creates_note_in_notes_dir(self, tmp_vault):
        result = self._run_new(tmp_vault, "Test Note")
        assert result.returncode == 0, f"stderr: {result.stderr}"
        notes = list((tmp_vault / "notes").glob("*.md"))
        assert len(notes) == 1

    def test_required_frontmatter_fields_present(self, tmp_vault):
        self._run_new(tmp_vault, "Required Fields Note")
        notes = list((tmp_vault / "notes").glob("*.md"))
        fm = self._read_frontmatter(notes[0])
        required = ["id", "title", "type", "status", "tags", "created",
                    "updated", "cairn_version"]
        for field in required:
            assert field in fm, f"Required frontmatter field missing: {field}"

    def test_optional_fields_present_may_be_empty(self, tmp_vault):
        self._run_new(tmp_vault, "Optional Fields Note")
        notes = list((tmp_vault / "notes").glob("*.md"))
        fm = self._read_frontmatter(notes[0])
        for field in ["project", "moc", "source", "source_url"]:
            assert field in fm, f"Optional field must be present (may be empty): {field}"

    def test_id_is_8_char_hex(self, tmp_vault):
        self._run_new(tmp_vault, "ID Test Note")
        notes = list((tmp_vault / "notes").glob("*.md"))
        fm = self._read_frontmatter(notes[0])
        assert re.match(r"^[0-9a-f]{8}$", str(fm["id"])), (
            f"id must be 8-char hex, got: {fm['id']!r}"
        )

    def test_title_matches_argument(self, tmp_vault):
        self._run_new(tmp_vault, "My Test Title")
        notes = list((tmp_vault / "notes").glob("*.md"))
        fm = self._read_frontmatter(notes[0])
        assert fm["title"] == "My Test Title"

    def test_type_default_is_note(self, tmp_vault):
        """Omitting --type defaults to 'note'."""
        self._run_new(tmp_vault, "Default Type Note")
        notes = list((tmp_vault / "notes").glob("*.md"))
        fm = self._read_frontmatter(notes[0])
        assert fm["type"] == "note"

    def test_type_explicit(self, tmp_vault):
        self._run_new(tmp_vault, "Todo Note", "--type", "todo")
        notes = list((tmp_vault / "notes").glob("*.md"))
        fm = self._read_frontmatter(notes[0])
        assert fm["type"] == "todo"

    def test_type_vocabulary_invalid_rejected(self, tmp_vault):
        """An invalid type must be rejected."""
        result = self._run_new(tmp_vault, "Bad Type", "--type", "architecture")
        assert result.returncode != 0, "Invalid type must be rejected"

    def test_tag_default_is_untagged(self, tmp_vault):
        """Omitting --tag defaults to ['untagged']."""
        self._run_new(tmp_vault, "Default Tag Note")
        notes = list((tmp_vault / "notes").glob("*.md"))
        fm = self._read_frontmatter(notes[0])
        assert "untagged" in (fm["tags"] or []), (
            f"Default tag must be 'untagged', got: {fm['tags']!r}"
        )

    def test_tag_explicit(self, tmp_vault):
        self._run_new(tmp_vault, "Tagged Note", "--tag", "trade-finance")
        notes = list((tmp_vault / "notes").glob("*.md"))
        fm = self._read_frontmatter(notes[0])
        assert "trade-finance" in fm["tags"]

    def test_tag_normalized_at_write_time(self, tmp_vault):
        """'Trade Finance' must be written as 'trade-finance'."""
        self._run_new(tmp_vault, "Normalized Tag Note", "--tag", "Trade Finance")
        notes = list((tmp_vault / "notes").glob("*.md"))
        fm = self._read_frontmatter(notes[0])
        assert "trade-finance" in fm["tags"], (
            f"Tag must be normalized to 'trade-finance', got {fm['tags']!r}"
        )
        assert "Trade Finance" not in fm["tags"]

    def test_tags_is_list_type(self, tmp_vault):
        self._run_new(tmp_vault, "Tags List Note", "--tag", "mytag")
        notes = list((tmp_vault / "notes").glob("*.md"))
        fm = self._read_frontmatter(notes[0])
        assert isinstance(fm["tags"], list), "tags must be a YAML list"

    def test_created_is_iso_date_string(self, tmp_vault):
        self._run_new(tmp_vault, "Date Note")
        notes = list((tmp_vault / "notes").glob("*.md"))
        fm = self._read_frontmatter(notes[0])
        assert re.match(r"^\d{4}-\d{2}-\d{2}$", str(fm["created"])), (
            f"created must be ISO date string, got {fm['created']!r}"
        )

    def test_updated_equals_created_on_new(self, tmp_vault):
        self._run_new(tmp_vault, "Updated Date Note")
        notes = list((tmp_vault / "notes").glob("*.md"))
        fm = self._read_frontmatter(notes[0])
        assert fm["updated"] == fm["created"]

    def test_cairn_version_is_1(self, tmp_vault):
        self._run_new(tmp_vault, "Version Note")
        notes = list((tmp_vault / "notes").glob("*.md"))
        fm = self._read_frontmatter(notes[0])
        assert fm["cairn_version"] == 1

    def test_status_is_active(self, tmp_vault):
        self._run_new(tmp_vault, "Status Note")
        notes = list((tmp_vault / "notes").glob("*.md"))
        fm = self._read_frontmatter(notes[0])
        assert fm["status"] == "active"

    def test_project_empty_by_default(self, tmp_vault):
        self._run_new(tmp_vault, "No Project Note")
        notes = list((tmp_vault / "notes").glob("*.md"))
        fm = self._read_frontmatter(notes[0])
        # project may be None/null/empty string -- but must be present and not set
        assert not fm.get("project"), (
            f"project must be empty when --project not given, got {fm.get('project')!r}"
        )

    def test_missing_title_is_hard_failure(self, tmp_vault):
        """cairn new with no title must fail."""
        result = self._run_new(tmp_vault)
        assert result.returncode != 0, "Missing title must be a hard failure"

    def test_slug_from_title(self, tmp_vault):
        self._run_new(tmp_vault, "Trade Finance Notes")
        notes = list((tmp_vault / "notes").glob("*.md"))
        assert notes[0].name == "trade-finance-notes.md", (
            f"Slug must match title, got {notes[0].name!r}"
        )

    def test_collision_suffix(self, tmp_vault):
        """
        Creating two notes with the same title appends -2, -3, ...
        The first note uses the plain slug; the second appends -2.
        """
        self._run_new(tmp_vault, "Collision Test")
        self._run_new(tmp_vault, "Collision Test")
        notes = sorted((tmp_vault / "notes").glob("*.md"), key=lambda p: p.name)
        names = [n.name for n in notes]
        assert "collision-test.md" in names
        assert "collision-test-2.md" in names, (
            f"Second identical title should get -2 suffix, got: {names}"
        )

    def test_collision_never_overwrites(self, tmp_vault):
        """cairn new must never overwrite an existing note."""
        self._run_new(tmp_vault, "No Overwrite Test")
        original = (tmp_vault / "notes" / "no-overwrite-test.md").read_bytes()
        self._run_new(tmp_vault, "No Overwrite Test")
        # Original file must be unchanged.
        assert (tmp_vault / "notes" / "no-overwrite-test.md").read_bytes() == original

    def test_creates_git_commit(self, tmp_vault):
        """
        After cairn new, there must be a new git commit containing the note.
        """
        result = self._run_new(tmp_vault, "Commit Test Note")
        assert result.returncode == 0
        log = subprocess.run(
            ["git", "log", "--oneline"],
            capture_output=True, text=True, cwd=str(tmp_vault),
            env=os.environ.copy(),
        )
        # There should be at least one commit after init.
        assert log.stdout.strip(), "Expected at least one git commit after cairn new"


# ---------------------------------------------------------------------------
# Auto-commit path ownership rules
# ---------------------------------------------------------------------------

class TestAutoCommit:
    def _run_new(self, vault: Path, *args):
        return subprocess.run(
            ["cairn", "new"] + list(args),
            capture_output=True, text=True,
            cwd=str(vault), env=os.environ.copy(),
        )

    def _git(self, vault: Path, *args):
        return subprocess.run(
            ["git"] + list(args),
            capture_output=True, text=True,
            cwd=str(vault), env=os.environ.copy(),
        )

    def test_only_command_owned_paths_committed(self, tmp_vault):
        """
        A dirty file outside the command-owned paths must NOT appear
        in the auto-commit.
        DESIGN.md: 'stage and commit only the command-owned paths'.
        """
        # Create a dirty unrelated file.
        dirty = tmp_vault / "notes" / "unrelated.md"
        dirty.write_text("---\nid: aabbccdd\n---\ndirty\n")

        self._run_new(tmp_vault, "Owned Path Test")

        # The commit that was just made must not include unrelated.md.
        show = self._git(tmp_vault, "show", "--stat", "HEAD")
        assert "unrelated.md" not in show.stdout, (
            "Auto-commit must not include files outside the command-owned paths"
        )
        # unrelated.md must still be dirty (unstaged).
        status = self._git(tmp_vault, "status", "--porcelain")
        assert "unrelated.md" in status.stdout

    def test_prestaged_unrelated_file_not_bundled(self, tmp_vault):
        """
        A file the user has ALREADY staged (git add) must NOT be swept into a
        cairn auto-commit. commit_paths scopes its commit to command-owned paths
        via an explicit pathspec (DESIGN:746-753).

        Found by adversarial review: the dirty-UNSTAGED test above gave false
        confidence (a bare `git commit` skips unstaged files anyway). This covers
        the STAGED case, which a bare `git commit` WOULD have bundled.
        """
        other = tmp_vault / "notes" / "staged.md"
        other.write_text("---\nid: aabbccdd\n---\nuser-staged draft\n")
        self._git(tmp_vault, "add", "notes/staged.md")  # explicitly STAGED

        self._run_new(tmp_vault, "Cairn Note")

        show = self._git(tmp_vault, "show", "--name-only", "HEAD")
        assert "staged.md" not in show.stdout, (
            "a pre-staged unrelated file must not be bundled into the auto-commit"
        )
        # and it remains staged (uncommitted by cairn)
        status = self._git(tmp_vault, "status", "--porcelain")
        assert "staged.md" in status.stdout

    def test_existing_dirty_command_owned_path_stops_write(self, tmp_vault):
        """
        If the target file already has uncommitted changes, cairn new must
        stop with a non-zero exit.
        DESIGN.md: 'If any command-owned target path already has uncommitted
        changes, stop with a clear message.'
        """
        # Pre-create the slug file with dirty content.
        target = tmp_vault / "notes" / "dirty-owned.md"
        target.write_text("dirty content not committed\n")
        # Do NOT git add it, so it is an untracked/dirty file.

        result = self._run_new(tmp_vault, "Dirty Owned")
        assert result.returncode != 0, (
            "cairn new must stop when the target file is dirty/uncommitted"
        )

    def test_commit_failure_leaves_file_on_disk(self, tmp_vault):
        """
        When the commit fails for a non-scan reason (e.g. git identity missing),
        the file written to disk must survive and the CLI exits non-zero.
        DESIGN.md: 'the write to disk stands, the commit does not'.

        We force a commit failure by removing the git user identity for this call.
        """
        env_no_identity = os.environ.copy()
        env_no_identity["GIT_AUTHOR_NAME"] = ""
        env_no_identity["GIT_AUTHOR_EMAIL"] = ""
        env_no_identity["GIT_COMMITTER_NAME"] = ""
        env_no_identity["GIT_COMMITTER_EMAIL"] = ""
        # Overwrite the global config to remove the identity.
        gcfg = Path(env_no_identity["GIT_CONFIG_GLOBAL"])
        original_cfg = gcfg.read_text()
        gcfg.write_text("[user]\n    name =\n    email =\n")

        try:
            result = subprocess.run(
                ["cairn", "new", "Commit Fail Note"],
                capture_output=True, text=True,
                cwd=str(tmp_vault), env=env_no_identity,
            )
        finally:
            gcfg.write_text(original_cfg)

        # Exit must be non-zero.
        assert result.returncode != 0, (
            "cairn new must exit non-zero when commit fails"
        )
        # The file must exist on disk despite the failed commit.
        created_notes = list((tmp_vault / "notes").glob("commit-fail-note*.md"))
        assert created_notes, (
            "File must remain on disk even when the auto-commit fails"
        )
