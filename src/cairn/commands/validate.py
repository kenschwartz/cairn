import datetime
import re
import sys
from pathlib import Path

from cairn import frontmatter, vault

VALID_TYPES = {"note", "todo", "meeting", "reference", "project", "moc"}
VALID_STATUSES = {"active", "waiting", "done", "archived"}
REQUIRED_FIELDS = {"id", "title", "type", "status", "tags", "created", "updated", "cairn_version"}
OPTIONAL_FIELDS = {"project", "moc", "source", "source_url"}


def run_validate(args):
    """Validate vault notes (schema-only scope per DESIGN:845)."""
    vault_path = Path.cwd().resolve()
    notes = vault.iter_notes(vault_path)

    # Also validate moc/ per decisions.md
    moc_dir = vault_path / "moc"
    if moc_dir.is_dir():
        notes.extend(moc_dir.glob("*.md"))

    # Duplicate note filenames (DESIGN:834): in the flat layout a basename
    # collision can only happen across notes/ and moc/; it makes wiki-link
    # resolution by basename ambiguous. Report it.
    from collections import Counter
    seen = Counter(p.name for p in notes)
    dupes = sorted(name for name, count in seen.items() if count > 1)

    errors = []
    warnings = []
    for name in dupes:
        errors.append(
            (vault_path, "ERROR",
             f"duplicate note filename: {name} (appears in more than one of notes/, moc/)")
        )

    for note_path in notes:
        try:
            fm, body = frontmatter.read_frontmatter(note_path)
        except ValueError as e:
            errors.append((note_path, "ERROR", f"missing frontmatter: {e}"))
            continue

        # Check if inbox-tagged (relaxed mode)
        is_inbox = "inbox" in fm.get("tags", [])

        # Check required fields are present and non-empty
        for field in REQUIRED_FIELDS:
            if field not in fm:
                errors.append((note_path, "ERROR", f"missing required field: {field}"))
            elif not fm[field]:
                errors.append((note_path, "ERROR", f"empty required field: {field}"))

        # For optional fields, just check they're present (can be empty)
        # Actually, optional fields don't need to be present at all per DESIGN:849

        # Skip type/status validation for inbox-tagged notes (relaxed mode)
        if not is_inbox:
            if "type" in fm and fm["type"] not in VALID_TYPES:
                errors.append((note_path, "ERROR", f"invalid type: {fm['type']}"))
            if "status" in fm and fm["status"] not in VALID_STATUSES:
                errors.append((note_path, "ERROR", f"invalid status: {fm['status']}"))

        # Check tags (missing tags is error even for inbox)
        if "tags" in fm:
            if not fm["tags"]:
                errors.append((note_path, "ERROR", "missing tags (empty list)"))

        # Validate date format (YYYY-MM-DD)
        for date_field in ["created", "updated"]:
            if date_field in fm and fm[date_field]:
                if not re.match(r"^\d{4}-\d{2}-\d{2}$", fm[date_field]):
                    errors.append((note_path, "ERROR", f"malformed date {date_field}: {fm[date_field]} (expected YYYY-MM-DD)"))
                else:
                    # Additional check: ensure it's a valid date
                    try:
                        datetime.date.fromisoformat(fm[date_field])
                    except ValueError:
                        errors.append((note_path, "ERROR", f"invalid date {date_field}: {fm[date_field]}"))

    # Output findings
    for path, severity, message in errors:
        rel_path = path.relative_to(vault_path)
        print(f"{rel_path}: {severity}: {message}")

    for path, severity, message in warnings:
        rel_path = path.relative_to(vault_path)
        print(f"{rel_path}: {severity}: {message}")

    # Summary
    error_count = len(errors)
    warning_count = len(warnings)
    print(f"\n{error_count} error{'s' if error_count != 1 else ''}, {warning_count} warning{'s' if warning_count != 1 else ''}")

    return 0 if error_count == 0 else 1
