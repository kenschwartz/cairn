"""Rename command for Cairn (Phase 3b)."""

import datetime
import sys
from pathlib import Path

from cairn import frontmatter, gitadapter, links, slugs


def run_rename(args):
    """
    Rename a note: update title, recompute slug, git mv to new filename.

    Per DESIGN:408-418 and docs/decisions.md:
    - Updates frontmatter title and updated date
    - Recomputes slug from new title
    - If slug unchanged: frontmatter-only update
    - If slug changed: git mv with -2/-3 collision suffix
    - Single commit of only the target note
    - Dirty-tree precheck: refuse if target has uncommitted changes
    - Rollback on any failure after frontmatter write
    - Broken-link report after successful rename (informational, non-fatal)
    """
    vault_path = Path.cwd().resolve()
    note_rel = args.path
    new_title = args.title

    target_path = vault_path / note_rel

    # Check target exists
    if not target_path.exists():
        print(f"error: note not found: {note_rel}", file=sys.stderr)
        return 1

    # Dirty-tree precheck
    if gitadapter.is_dirty(target_path, vault_path):
        print(
            f"error: uncommitted changes on {note_rel}; commit or stash first",
            file=sys.stderr,
        )
        return 1

    # Capture original state for rollback
    original_bytes = target_path.read_bytes()
    original_rel = target_path.relative_to(vault_path)

    # Read frontmatter
    try:
        fm, body = frontmatter.read_frontmatter(target_path)
    except ValueError:
        print(f"error: malformed frontmatter in {note_rel}", file=sys.stderr)
        return 1

    old_title = fm.get("title", "")
    original_path = target_path

    # Update frontmatter
    fm["title"] = new_title
    fm["updated"] = datetime.date.today().isoformat()

    # Write updated frontmatter (atomic, same path)
    updated_content = frontmatter.write_frontmatter(fm) + body
    temp_path = target_path.with_suffix(".md.tmp")
    temp_path.write_bytes(updated_content.encode("utf-8"))
    temp_path.replace(target_path)

    # Recompute slug
    new_slug = slugs.slugify(new_title)
    current_filename = target_path.stem  # without .md
    new_filename = new_slug

    # Check if git mv needed
    if new_filename == current_filename:
        # Frontmatter-only change, no git mv
        commit_paths = [target_path]
        commit_msg = f"cairn rename: {original_rel}"
    else:
        # Need to git mv to new filename with collision suffix
        notes_dir = target_path.parent
        new_basename = f"{new_filename}.md"
        new_path = notes_dir / new_basename

        # Handle collision with -2/-3 suffix
        # Collision means: a file with the target filename already exists on disk.
        # Use the same suffix rule as note creation (DESIGN:530).
        suffix = 2
        candidate_slug = new_filename
        candidate_path = notes_dir / f"{candidate_slug}.md"
        while candidate_path.exists():
            candidate_slug = f"{new_filename}-{suffix}"
            candidate_path = notes_dir / f"{candidate_slug}.md"
            suffix += 1
        new_path = candidate_path

        # git mv
        mv_result = gitadapter.run_git(["mv", str(target_path), str(new_path)], vault_path)
        if mv_result.returncode != 0:
            # Rollback: restore original bytes at original path
            original_path.write_bytes(original_bytes)
            # Remove temp file if it exists
            if temp_path.exists():
                temp_path.unlink()
            # Reset any staged paths
            gitadapter.run_git(["reset"], vault_path)
            print(f"error: git mv failed: {mv_result.stderr}", file=sys.stderr)
            return 1

        commit_paths = [new_path]
        commit_msg = f"cairn rename: {original_rel} -> {new_path.relative_to(vault_path)}"

    # Commit
    commit_result = gitadapter.commit_paths(commit_paths, vault_path, commit_msg)
    if commit_result.returncode != 0:
        # File stays on disk per DESIGN:755
        print(f"error: commit failed: {commit_result.stderr}", file=sys.stderr)
        return 1

    # Broken-link report (informational, non-fatal)
    index = links.build_index(vault_path)
    broken = links.inbound_links(index, old_title)
    if broken:
        print("warning: the following notes still link to the old title:", file=sys.stderr)
        for linker in broken:
            print(f"  {linker}", file=sys.stderr)

    return 0
