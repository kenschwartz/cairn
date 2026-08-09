"""Tags list command for Cairn (Phase 4)."""

from pathlib import Path

from cairn import frontmatter, gitadapter, vault


def run_tags(args):
    """
    List all tags with their note counts.

    Per docs/decisions.md Q004-1:
    - Walk vault.iter_notes_and_moc
    - Collect frontmatter tags only (ignore inline #tag in bodies)
    - Print each tag with its note count
    - Sorted: frequency-desc then alpha
    - Read-only (never commits)
    """
    vault_path = Path.cwd().resolve()

    # Collect tags from all notes and moc files
    tag_counts = {}
    for note_path in vault.iter_notes_and_moc(vault_path):
        try:
            fm, _body = frontmatter.read_frontmatter(note_path)
        except ValueError:
            # Skip malformed notes
            continue

        for tag in fm.get("tags", []):
            tag_counts[tag] = tag_counts.get(tag, 0) + 1

    # Sort: frequency-desc then alpha
    sorted_tags = sorted(tag_counts.items(), key=lambda x: (-x[1], x[0]))

    # Print results
    for tag, count in sorted_tags:
        print(f"{tag} ({count})")

    return 0


def generate_tags_index(vault_path: Path) -> int:
    """
    Generate indexes/tags.md with one section per tag.

    Per docs/decisions.md Q004-2:
    - Generated, committed, content-pinned
    - One ## tag section per tag, alpha-sorted
    - Bulleted backlinks to carrying notes
    - Called by reindex

    Auto-commits if changed; skips if identical.
    """
    # Collect tag->notes mapping
    tag_to_notes = {}
    for note_path in vault.iter_notes_and_moc(vault_path):
        try:
            fm, _body = frontmatter.read_frontmatter(note_path)
        except ValueError:
            continue

        for tag in fm.get("tags", []):
            if tag not in tag_to_notes:
                tag_to_notes[tag] = []
            rel_path = note_path.relative_to(vault_path)
            tag_to_notes[tag].append((rel_path, fm.get("title", "")))

    # Sort tags alphabetically
    sorted_tags = sorted(tag_to_notes.keys())

    # Generate content
    lines = ["# Tags\n"]
    for tag in sorted_tags:
        lines.append(f"## {tag}\n")
        # Sort notes by path within each tag
        notes = sorted(tag_to_notes[tag], key=lambda x: x[0].as_posix())
        for rel_path, title in notes:
            # Use wikilink format: [[<rel-path>|<title>]]
            lines.append(f"- [[{rel_path.as_posix()}|{title}]]\n")

    content = "".join(lines)

    # Ensure indexes/ directory exists
    indexes_dir = vault_path / "indexes"
    indexes_dir.mkdir(parents=True, exist_ok=True)

    tags_index_path = indexes_dir / "tags.md"

    # Check if identical
    if tags_index_path.exists():
        existing = tags_index_path.read_text(encoding="utf-8")
        if existing == content:
            # No change, skip
            return 0

    # Atomic write
    temp_path = tags_index_path.with_suffix(".md.tmp")
    temp_path.write_text(content, encoding="utf-8")
    temp_path.replace(tags_index_path)

    # Commit
    commit_result = gitadapter.commit_paths([tags_index_path], vault_path, "cairn reindex: tags.md")
    if commit_result.returncode != 0:
        print(f"error: commit failed: {commit_result.stderr}", file=sys.stderr)
        return 1

    return 0


import sys

