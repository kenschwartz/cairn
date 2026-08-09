"""Dashboard command for Cairn (Phase 3)."""

import re
from pathlib import Path

from cairn import frontmatter, gitadapter, vault


def _extract_todos(body: str) -> list[str]:
    """
    Extract unchecked todos from body.

    Matches `- [ ]` and `* [ ]`.
    Returns list of task text in order.
    """
    pattern = r"^[\-*]\s\[\s\]\s+(.+)$"
    matches = re.findall(pattern, body, re.MULTILINE)
    return matches


def run_dashboard(args):
    """
    Generate dashboard.md and auto-commit.

    Sections (per decisions.md "Dashboard layout"):
    1. Open todos (unchecked `- [ ]` / `* [ ]`), grouped by note
    2. Recently created (10 newest by created desc)
    3. Active projects (type=project AND status=active)
    4. Untagged (count + paths)

    Byte-identical no-op: if generated content equals existing dashboard.md,
    skip write and commit.
    """
    vault_path = Path.cwd().resolve()
    dashboard_path = vault_path / "dashboard.md"

    # Scan notes/ + moc/, excluding generated files
    notes = vault.iter_notes_and_moc(vault_path)

    # Exclude generated files from scan
    scanned_notes = []
    for note_path in notes:
        rel_path = note_path.relative_to(vault_path)
        # Skip dashboard.md and indexes/
        if rel_path.name == "dashboard.md" or rel_path.parent.name == "indexes":
            continue
        scanned_notes.append(note_path)

    # Collect data for sections
    open_todos_by_note = {}  # {rel_path: [tasks]}
    all_notes_data = []  # [(rel_path, fm, body)]
    untagged_notes = []

    for note_path in scanned_notes:
        try:
            fm, body = frontmatter.read_frontmatter(note_path)
        except ValueError:
            # Skip malformed notes
            continue

        rel_path = note_path.relative_to(vault_path).as_posix()
        all_notes_data.append((rel_path, fm, body))

        # Collect open todos
        todos = _extract_todos(body)
        if todos:
            open_todos_by_note[rel_path] = todos

        # Check for untagged
        note_tags = fm.get("tags", [])
        if note_tags == ["untagged"]:
            untagged_notes.append(rel_path)

    # Sort notes for each section
    # 1. Open todos: already grouped, sort by note path then task order
    open_todos_sorted = sorted(open_todos_by_note.items())

    # 2. Recently created: 10 newest by created desc then path asc
    # Exclude type=project notes (they have their own section)
    recently_created = sorted(
        [
            (rel_path, fm, body)
            for rel_path, fm, body in all_notes_data
            if fm.get("type") != "project"
        ],
        key=lambda x: (x[1].get("created", ""), x[0]),
        reverse=True
    )[:10]

    # 3. Active projects: type=project AND status=active, sorted by path
    active_projects = sorted(
        [
            (rel_path, fm)
            for rel_path, fm, body in all_notes_data
            if fm.get("type") == "project" and fm.get("status") == "active"
        ],
        key=lambda x: x[0]
    )

    # 4. Untagged: already have list, sort for consistent output
    untagged_sorted = sorted(untagged_notes)

    # Build dashboard content
    lines = []
    lines.append("# Dashboard")
    lines.append("")

    # Open todos section
    lines.append("## Open todos")
    lines.append("")
    if open_todos_sorted:
        for note_path, tasks in open_todos_sorted:
            # Get title from note data
            title = next(
                (fm.get("title", "") for rp, fm, body in all_notes_data if rp == note_path),
                ""
            )
            lines.append(f"### {title or note_path}")
            for task in tasks:
                lines.append(f"- [ ] {task}")
            lines.append("")
    else:
        lines.append("No open todos.")
        lines.append("")

    # Recently created section
    lines.append("## Recently created")
    lines.append("")
    if recently_created:
        for rel_path, fm, body in recently_created:
            title = fm.get("title", "")
            created = fm.get("created", "")
            lines.append(f"- {title or rel_path} ({created})")
        lines.append("")
    else:
        lines.append("No recently created notes.")
        lines.append("")

    # Active projects section
    lines.append("## Active projects")
    lines.append("")
    if active_projects:
        for rel_path, fm in active_projects:
            title = fm.get("title", "")
            lines.append(f"- {title or rel_path}")
        lines.append("")
    else:
        lines.append("No active projects.")
        lines.append("")

    # Untagged section
    lines.append("## Untagged")
    lines.append("")
    if untagged_sorted:
        lines.append(f"{len(untagged_sorted)} untagged note(s):")
        for rel_path in untagged_sorted:
            title = next(
                (fm.get("title", "") for rp, fm, body in all_notes_data if rp == rel_path),
                ""
            )
            lines.append(f"- {title or rel_path}")
        lines.append("")
    else:
        lines.append("No untagged notes.")
        lines.append("")

    # Join content
    content = "\n".join(lines)

    # Byte-identical no-op check
    if dashboard_path.exists():
        existing_content = dashboard_path.read_text(encoding="utf-8")
        if content == existing_content:
            # No change, skip write and commit
            return 0

    # Atomic write
    temp_path = dashboard_path.with_suffix(".md.tmp")
    temp_path.write_text(content, encoding="utf-8")
    temp_path.replace(dashboard_path)

    # Auto-commit
    gitadapter.commit_paths([dashboard_path], vault_path, "cairn regenerate: dashboard")

    return 0
