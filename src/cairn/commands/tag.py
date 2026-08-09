"""Tag rename/remove command for Cairn (Phase 4)."""

import sys
from pathlib import Path

from cairn import frontmatter, gitadapter, tags, vault


def run_tag(args):
    """Dispatch to tag subcommands."""
    if args.tag_command == "rename":
        return _run_tag_rename(args)
    elif args.tag_command == "remove":
        return _run_tag_remove(args)
    else:
        print(f"error: unknown tag subcommand '{args.tag_command}'", file=sys.stderr)
        return 1


def _run_tag_rename(args):
    """
    Rename a tag across all notes.

    Per docs/decisions.md Q004-3:
    - Normalize old and new via tags.normalize_tag
    - Find notes whose frontmatter tags contain normalized OLD
    - Zero matches -> stderr "no notes carry tag '<old>'", exit 1
    - COLLISION: if any note already carries normalized NEW (and not also being renamed from old) ->
      stderr "tag '<new>' already exists", exit 1
    - Rewrite each candidate note's frontmatter (replace old with new, preserving order)
    - Per-file atomic write (temp + os.replace)
    - Malformed notes: skip and report as failure
    - Single commit of successfully-rewritten paths
    - Report: successes committed + failures on stderr
    - Exit non-zero ONLY if zero successes; otherwise exit 0 with failures on stderr
    """
    old_raw = args.old
    new_raw = args.new

    vault_path = Path.cwd().resolve()

    # Normalize tags
    old_tag = tags.normalize_tag(old_raw)
    new_tag = tags.normalize_tag(new_raw)

    # Collect candidate notes and detect malformed notes
    candidates = []
    malformed = []
    for note_path in vault.iter_notes_and_moc(vault_path):
        try:
            fm, _body = frontmatter.read_frontmatter(note_path)
            note_tags = fm.get("tags", [])
            if old_tag in note_tags:
                candidates.append((note_path, fm, note_tags))
        except ValueError:
            # Track malformed notes for reporting
            malformed.append(note_path)

    # Initialize failures list
    failures = []

    # Add malformed notes to failures list
    for path in malformed:
        rel_path = path.relative_to(vault_path)
        failures.append((rel_path, "malformed frontmatter"))

    # Zero matches -> refuse (but still report malformed if any)
    if not candidates:
        if failures:
            for rel_path, reason in failures:
                print(f"{rel_path}: {reason}", file=sys.stderr)
            return 1
        print(f"no notes carry tag '{old_raw}'", file=sys.stderr)
        return 1

    # Collision check: if any note already carries new_tag (and not also being renamed from old)
    for note_path in vault.iter_notes_and_moc(vault_path):
        try:
            fm, _body = frontmatter.read_frontmatter(note_path)
            note_tags = fm.get("tags", [])
            if new_tag in note_tags and old_tag not in note_tags:
                print(f"tag '{new_raw}' already exists", file=sys.stderr)
                return 1
        except ValueError:
            continue

    # Rewrite candidates
    success_paths = []

    for note_path, fm, note_tags in candidates:
        try:
            # Read full content for rewrite
            fm_current, body = frontmatter.read_frontmatter(note_path)

            # Rebuild tags list: replace old with new, preserving order, dedup
            # (a note carrying BOTH old and new would otherwise get [new, new]).
            new_tags = list(dict.fromkeys(
                new_tag if t == old_tag else t for t in note_tags
            ))

            # Update frontmatter
            fm_current["tags"] = new_tags

            # Atomic write: temp + os.replace
            new_content = frontmatter.write_frontmatter(fm_current) + body
            temp_path = note_path.with_suffix(".md.tmp")
            temp_path.write_text(new_content, encoding="utf-8")
            temp_path.replace(note_path)

            success_paths.append(note_path)
        except (ValueError, OSError) as e:
            # Record failure and skip
            rel_path = note_path.relative_to(vault_path)
            failures.append((rel_path, str(e)))

    # Commit if any successes
    if success_paths:
        commit_msg = f"cairn tag rename: {old_raw} -> {new_raw} ({len(success_paths)} notes)"
        commit_result = gitadapter.commit_paths(success_paths, vault_path, commit_msg)
        if commit_result.returncode != 0:
            # Files stay on disk per DESIGN:755
            print(f"error: commit failed: {commit_result.stderr}", file=sys.stderr)
            return 1

    # Report
    if success_paths:
        print(f"committed {len(success_paths)} notes")

    if failures:
        for rel_path, reason in failures:
            print(f"{rel_path}: {reason}", file=sys.stderr)

    # Exit code: non-zero ONLY if zero successes
    if not success_paths:
        return 1
    return 0


def _run_tag_remove(args):
    """
    Remove a tag from all notes.

    Per docs/decisions.md Q004-1:
    - Find notes whose frontmatter tags contain the normalized tag
    - Zero matches -> refuse
    - Rewrite each candidate note (drop the tag from list; if list becomes empty, leave it empty)
    - Single commit of successfully-rewritten paths
    - Report failures on stderr
    - Exit non-zero ONLY if zero successes
    """
    tag_raw = args.tag
    vault_path = Path.cwd().resolve()

    # Normalize tag
    tag = tags.normalize_tag(tag_raw)

    # Collect candidate notes and detect malformed notes
    candidates = []
    malformed = []
    for note_path in vault.iter_notes_and_moc(vault_path):
        try:
            fm, _body = frontmatter.read_frontmatter(note_path)
            note_tags = fm.get("tags", [])
            if tag in note_tags:
                candidates.append((note_path, fm, note_tags))
        except ValueError:
            # Track malformed notes for reporting
            malformed.append(note_path)

    # Initialize failures list
    failures = []

    # Add malformed notes to failures list
    for path in malformed:
        rel_path = path.relative_to(vault_path)
        failures.append((rel_path, "malformed frontmatter"))

    # Zero matches -> refuse (but still report malformed if any)
    if not candidates:
        if failures:
            for rel_path, reason in failures:
                print(f"{rel_path}: {reason}", file=sys.stderr)
            return 1
        print(f"no notes carry tag '{tag_raw}'", file=sys.stderr)
        return 1

    # Rewrite candidates
    success_paths = []

    for note_path, fm, note_tags in candidates:
        try:
            # Read full content for rewrite
            fm_current, body = frontmatter.read_frontmatter(note_path)

            # Drop the tag from list
            new_tags = [t for t in note_tags if t != tag]
            fm_current["tags"] = new_tags

            # Atomic write: temp + os.replace
            new_content = frontmatter.write_frontmatter(fm_current) + body
            temp_path = note_path.with_suffix(".md.tmp")
            temp_path.write_text(new_content, encoding="utf-8")
            temp_path.replace(note_path)

            success_paths.append(note_path)
        except (ValueError, OSError) as e:
            rel_path = note_path.relative_to(vault_path)
            failures.append((rel_path, str(e)))

    # Commit if any successes
    if success_paths:
        commit_msg = f"cairn tag remove: {tag_raw} ({len(success_paths)} notes)"
        commit_result = gitadapter.commit_paths(success_paths, vault_path, commit_msg)
        if commit_result.returncode != 0:
            print(f"error: commit failed: {commit_result.stderr}", file=sys.stderr)
            return 1

    # Report
    if success_paths:
        print(f"committed {len(success_paths)} notes")

    if failures:
        for rel_path, reason in failures:
            print(f"{rel_path}: {reason}", file=sys.stderr)

    # Exit code: non-zero ONLY if zero successes
    if not success_paths:
        return 1
    return 0
