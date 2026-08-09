"""Search command for Cairn (Phase 3)."""

import sys
from pathlib import Path

from cairn import frontmatter, tags, vault


def run_search(args):
    """
    Execute search with text query and/or structured filters.

    Text query: case-insensitive substring over body + title + source.
    Filters: --tag/--type/--status/--project (exact normalized match).
    Multiple --tag require ALL (AND logic across all filters).
    No query AND no filter -> error.
    Filter-only (>=1 filter, no text) works.

    Malformed notes: never match frontmatter filters; text query may match body.
    Results sorted by rel path ascending. Read-only: never commits.
    """
    vault_path = Path.cwd().resolve()

    # Extract filters
    tag_filters = args.tag or []
    type_filter = args.type
    status_filter = args.status
    project_filter = args.project

    # Extract text query (remaining positional args)
    text_query = " ".join(args.query) if hasattr(args, "query") and args.query else ""

    # Validate: at least one filter or text query required
    has_filters = tag_filters or type_filter or status_filter or project_filter
    if not text_query and not has_filters:
        print("Error: search requires a text query or at least one filter (--tag/--type/--status/--project)", file=sys.stderr)
        return 1

    # Normalize tag filters for comparison
    normalized_tag_filters = [tags.normalize_tag(t) for t in tag_filters]

    # Search scope: notes/ + moc/
    notes = vault.iter_notes_and_moc(vault_path)

    results = []
    for note_path in notes:
        rel_path = note_path.relative_to(vault_path).as_posix()

        # Try to read frontmatter
        try:
            fm, body = frontmatter.read_frontmatter(note_path)
            malformed = False
        except ValueError:
            # Malformed note: can't use frontmatter filters
            fm = {}
            body = note_path.read_text(encoding="utf-8")
            malformed = True

        # Skip frontmatter filters for malformed notes
        if malformed and has_filters:
            # Text query might still match body
            if text_query and text_query.lower() in body.lower():
                results.append((rel_path, "(malformed)", "", body))
            continue

        # Apply structured filters
        filters_match = True

        # Tag filter: ALL specified tags must be present
        if normalized_tag_filters:
            note_tags = [tags.normalize_tag(t) for t in fm.get("tags", [])]
            if not all(tag in note_tags for tag in normalized_tag_filters):
                filters_match = False

        # Type filter
        if type_filter and fm.get("type") != type_filter:
            filters_match = False

        # Status filter
        if status_filter and fm.get("status") != status_filter:
            filters_match = False

        # Project filter
        if project_filter and fm.get("project") != project_filter:
            filters_match = False

        # Skip if filters don't match (when filters are specified)
        if has_filters and not filters_match:
            continue

        # Text query search (case-insensitive over body + title + source)
        if text_query:
            searchable_text = (
                body.lower()
                + " "
                + fm.get("title", "").lower()
                + " "
                + fm.get("source", "").lower()
            )
            if text_query.lower() not in searchable_text:
                continue

        # Note matched
        title = fm.get("title", "(malformed)" if malformed else "")
        note_type = fm.get("type", "")
        status = fm.get("status", "")
        results.append((rel_path, title, f"{note_type}/{status}", body))

    # Sort by rel path ascending
    results.sort(key=lambda x: x[0])

    # Output results
    for rel_path, title, type_status, body in results:
        print(f"{rel_path}: {title}")
        if type_status:
            print(f"  {type_status}")

        # Extract excerpt (first 80 chars around match)
        if text_query:
            # Find first match position
            search_body = body.lower()
            pos = search_body.find(text_query.lower())
            if pos != -1:
                start = max(0, pos - 40)
                end = min(len(body), pos + len(text_query) + 40)
                excerpt = body[start:end].replace("\n", " ")
                print(f"  ...{excerpt}...")
        print()

    # Summary
    print(f"Found {len(results)} result(s)")

    return 0
