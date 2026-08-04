from pathlib import Path


VAULT_DIRS = ["notes", "moc", "assets", "assets/local", "indexes"]

GITIGNORE_RULES = [".DS_Store", "*~", "*.swp", "*.swo", "assets/local/"]


def ensure_structure(vault_root: Path) -> None:
    for name in VAULT_DIRS:
        (vault_root / name).mkdir(parents=True, exist_ok=True)


def write_gitignore(vault_root: Path) -> None:
    content = "".join(f"{rule}\n" for rule in GITIGNORE_RULES)
    (vault_root / ".gitignore").write_text(content)


def merge_gitignore(vault_root: Path) -> list[str]:
    """Append any missing rule to an existing .gitignore, preserving user rules."""
    path = vault_root / ".gitignore"
    existing = path.read_text()
    present = {line.strip() for line in existing.splitlines()}
    missing = [rule for rule in GITIGNORE_RULES if rule not in present]
    if missing:
        prefix = "" if existing.endswith("\n") or not existing else "\n"
        path.write_text(existing + prefix + "".join(f"{rule}\n" for rule in missing))
    return missing
