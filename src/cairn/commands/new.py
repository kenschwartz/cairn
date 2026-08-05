import datetime
import sys
from pathlib import Path

from cairn import frontmatter, slugs, tags, vault
from cairn.gitadapter import is_dirty, commit_paths

VALID_TYPES = {"note", "todo", "meeting", "reference", "project", "moc"}
VALID_STATUSES = {"active", "waiting", "done", "archived"}


def run_new(args):
    title = args.title
    if not title:
        print("error: title is required", file=sys.stderr)
        return 1

    note_type = args.type or "note"
    if note_type not in VALID_TYPES:
        print(f"error: invalid type '{note_type}'", file=sys.stderr)
        return 1

    raw_tags = args.tag or []
    if not raw_tags:
        raw_tags = ["untagged"]
    normalized_tags = [tags.normalize_tag(t) for t in raw_tags]

    vault_path = Path.cwd().resolve()
    notes_dir = vault_path / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)

    base_slug = slugs.slugify(title)
    base_path = notes_dir / f"{base_slug}.md"

    if base_path.exists() and is_dirty(base_path, vault_path):
        print(f"error: {base_path} has uncommitted changes", file=sys.stderr)
        return 1

    candidate = f"{base_slug}.md"
    i = 2
    while (notes_dir / candidate).exists():
        candidate = f"{base_slug}-{i}.md"
        i += 1
    target_path = notes_dir / candidate

    if is_dirty(target_path, vault_path):
        print(f"error: {target_path} has uncommitted changes", file=sys.stderr)
        return 1

    today = datetime.date.today().isoformat()
    note_id = __import__("uuid").uuid4().hex[:8]

    fm = {
        "id": note_id,
        "title": title,
        "type": note_type,
        "status": "active",
        "project": args.project or "",
        "tags": normalized_tags,
        "created": today,
        "updated": today,
        "cairn_version": 1,
        "moc": "",
        "source": "",
        "source_url": "",
    }

    content = frontmatter.write_frontmatter(fm)
    content += f"# {title}\n\n"

    tmp_path = target_path.with_suffix(".tmp")
    tmp_path.write_text(content, encoding="utf-8")
    tmp_path.rename(target_path)

    commit_result = commit_paths([target_path], vault_path, f"cairn new: {title}")
    if commit_result.returncode != 0:
        print(f"error: commit failed. File written to {target_path}.", file=sys.stderr)
        print(commit_result.stderr, file=sys.stderr)
        return 1

    return 0
