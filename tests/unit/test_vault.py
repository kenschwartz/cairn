"""
Unit tests for cairn.vault.

ensure_structure() and write_gitignore() are the only writers of the vault
skeleton. Both must be idempotent: `cairn init` on an existing vault runs them
again and must not destroy anything.

Hermeticity: filesystem I/O is confined to tmp_path. No git, no subprocess.
"""

from cairn import vault


class TestVaultDirs:
    def test_declared_dirs(self):
        assert vault.VAULT_DIRS == ["notes", "moc", "assets", "assets/local", "indexes"]


class TestEnsureStructure:
    def test_creates_every_declared_dir(self, tmp_path):
        vault.ensure_structure(tmp_path)
        for name in vault.VAULT_DIRS:
            assert (tmp_path / name).is_dir()

    def test_creates_missing_vault_root(self, tmp_path):
        root = tmp_path / "does" / "not" / "exist"
        vault.ensure_structure(root)
        assert (root / "notes").is_dir()

    def test_is_idempotent(self, tmp_path):
        vault.ensure_structure(tmp_path)
        vault.ensure_structure(tmp_path)
        for name in vault.VAULT_DIRS:
            assert (tmp_path / name).is_dir()

    def test_preserves_existing_files(self, tmp_path):
        (tmp_path / "notes").mkdir()
        note = tmp_path / "notes" / "keep.md"
        note.write_text("keep me")
        vault.ensure_structure(tmp_path)
        assert note.read_text() == "keep me"

    def test_creates_no_undeclared_entries(self, tmp_path):
        vault.ensure_structure(tmp_path)
        top_level = sorted(p.name for p in tmp_path.iterdir())
        assert top_level == ["assets", "indexes", "moc", "notes"]


class TestWriteGitignore:
    def _lines(self, tmp_path):
        vault.write_gitignore(tmp_path)
        return (tmp_path / ".gitignore").read_text().splitlines()

    def test_creates_gitignore(self, tmp_path):
        vault.write_gitignore(tmp_path)
        assert (tmp_path / ".gitignore").is_file()

    def test_ignores_local_assets_dir(self, tmp_path):
        assert "assets/local/" in self._lines(tmp_path)

    def test_ignores_editor_and_os_cruft(self, tmp_path):
        lines = self._lines(tmp_path)
        for pattern in (".DS_Store", "*~", "*.swp", "*.swo"):
            assert pattern in lines

    def test_does_not_ignore_markdown_or_shared_assets(self, tmp_path):
        content = "\n".join(self._lines(tmp_path))
        assert "*.md" not in content
        assert "\nassets/\n" not in f"\n{content}\n"

    def test_ends_with_newline(self, tmp_path):
        vault.write_gitignore(tmp_path)
        assert (tmp_path / ".gitignore").read_text().endswith("\n")

    def test_is_idempotent(self, tmp_path):
        vault.write_gitignore(tmp_path)
        first = (tmp_path / ".gitignore").read_text()
        vault.write_gitignore(tmp_path)
        assert (tmp_path / ".gitignore").read_text() == first

    def test_overwrites_a_hand_edited_file(self, tmp_path):
        (tmp_path / ".gitignore").write_text("# hand edited\n")
        vault.write_gitignore(tmp_path)
        assert "assets/local/" in (tmp_path / ".gitignore").read_text()
