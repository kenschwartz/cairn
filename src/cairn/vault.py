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
