import datetime
import sys
import uuid
from pathlib import Path

from cairn import frontmatter, slugs, tags
from cairn.gitadapter import commit_paths


VALID_TYPES = {"note", "todo", "meeting", "reference", "project", "moc"}
VALID_STATUSES = {"active", "waiting", "done", "archived"}


def run_capture(args):
    """Create a quick-capture note from exactly one content source."""
    # Determine content sources (positional, --file, stdin)
    # Note: args.text is the positional, args.file is --file, stdin is fallback
    has_positional = args.text is not None
    has_file = args.file is not None

    # Detect if stdin has data using non-blocking peek
    # We read a single byte non-blocking to check, then prepend it if we use stdin
    stdin_peek = None
    has_stdin_data = False
    if not sys.stdin.isatty():
        import os
        import fcntl
        fd = sys.stdin.fileno()
        try:
            orig_flags = fcntl.fcntl(fd, fcntl.F_GETFL)
            fcntl.fcntl(fd, fcntl.F_SETFL, orig_flags | os.O_NONBLOCK)
            try:
                byte = os.read(fd, 1)
                if byte:
                    stdin_peek = byte
                    has_stdin_data = True
            except BlockingIOError:
                # No data available
                pass
            finally:
                fcntl.fcntl(fd, fcntl.F_SETFL, orig_flags)
        except Exception:
            pass

    # Count sources
    sources = sum([has_positional, has_file, has_stdin_data])

    if sources > 1:
        print("error: only one content source may be provided", file=sys.stderr)
        return 1
    if sources == 0:
        print("error: a content source is required (text, --file, or stdin)", file=sys.stderr)
        return 1

    # Read content from the single source
    if has_positional:
        content = args.text
    elif has_file:
        content = Path(args.file).read_text(encoding="utf-8")
    else:  # stdin
        # Read the rest of stdin and prepend the peeked byte
        rest = sys.stdin.read()
        content = (stdin_peek or b'').decode('utf-8', errors='replace') + rest
        if not content:
            print("error: stdin is empty", file=sys.stderr)
            return 1

    if not content:
        print("error: content source is empty", file=sys.stderr)
        return 1

    # Determine title
    if args.title:
        title = args.title
    else:
        # First non-empty line, truncated to 80
        lines = content.strip().splitlines()
        first_line = None
        for line in lines:
            if line.strip():
                first_line = line.strip()
                break
        if first_line:
            title = first_line[:80]
        else:
            # Fallback to generated name
            title = f"note-{uuid.uuid4().hex[:8]}"

    # Normalize tags: inbox always included, plus any --tag values
    raw_tags = ["inbox"]
    if args.tag:
        raw_tags.extend(args.tag)
    # Normalize and dedupe
    normalized_tags = []
    seen = set()
    for tag in raw_tags:
        norm = tags.normalize_tag(tag)
        if norm not in seen:
            normalized_tags.append(norm)
            seen.add(norm)

    vault_path = Path.cwd().resolve()
    notes_dir = vault_path / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)

    # Generate filename with collision handling
    base_slug = slugs.slugify(title)
    candidate = f"{base_slug}.md"
    i = 2
    while (notes_dir / candidate).exists():
        candidate = f"{base_slug}-{i}.md"
        i += 1
    target_path = notes_dir / candidate

    # Build frontmatter
    today = datetime.date.today().isoformat()
    note_id = uuid.uuid4().hex[:8]

    fm = {
        "id": note_id,
        "title": title,
        "type": "note",
        "status": "active",
        "project": args.project or "",
        "tags": normalized_tags,
        "created": today,
        "updated": today,
        "cairn_version": 1,
        "moc": args.moc or "",
        "source": args.source or "",
        "source_url": args.source_url or "",
    }

    # Atomic write
    content_with_fm = frontmatter.write_frontmatter(fm) + content
    tmp_path = target_path.with_suffix(".tmp")
    tmp_path.write_text(content_with_fm, encoding="utf-8")
    tmp_path.rename(target_path)

    # Auto-commit
    commit_result = commit_paths([target_path], vault_path, f"cairn capture: {target_path.relative_to(vault_path)}")
    if commit_result.returncode != 0:
        # File stays on disk per DESIGN:755 (mirror new.py behavior)
        print(f"error: commit failed. File written to {target_path}.", file=sys.stderr)
        return 1

    return 0
