from pathlib import Path


VAULT_DIRS = ["notes", "moc", "assets", "assets/local", "indexes"]


def ensure_structure(vault_root: Path) -> None:
    for name in VAULT_DIRS:
        (vault_root / name).mkdir(parents=True, exist_ok=True)


def write_gitignore(vault_root: Path) -> None:
    content = (
        ".DS_Store\n"
        "*~\n"
        "*.swp\n"
        "*.swo\n"
        "assets/local/\n"
    )
    (vault_root / ".gitignore").write_text(content)


def iter_notes(vault: Path) -> list[Path]:
    """
    All `*.md` directly under `notes/`, sorted by relative path (POSIX).

    Not recursive per DESIGN:304 - notes live directly under notes/.
    Returns absolute paths.
    """
    notes_dir = vault / "notes"
    if not notes_dir.is_dir():
        return []

    paths = list(notes_dir.glob("*.md"))
    # Sort by relative POSIX path for deterministic output
    paths.sort(key=lambda p: p.relative_to(vault).as_posix())
    return paths


def iter_notes_and_moc(vault: Path) -> list[Path]:
    """
    Union of `notes/*.md` and `moc/*.md`, sorted by relative path.

    Returns absolute paths, sorted by relative POSIX path for deterministic
    output (dashboard and search per DESIGN:686).
    """
    notes_dir = vault / "notes"
    moc_dir = vault / "moc"

    paths = []
    if notes_dir.is_dir():
        paths.extend(notes_dir.glob("*.md"))
    if moc_dir.is_dir():
        paths.extend(moc_dir.glob("*.md"))

    # Sort by relative POSIX path for deterministic output
    paths.sort(key=lambda p: p.relative_to(vault).as_posix())
    return paths
