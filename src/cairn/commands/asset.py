import hashlib
import json
import os
import sys
from datetime import date
from pathlib import Path

from cairn.frontmatter import read_frontmatter, write_frontmatter
from cairn.gitadapter import commit_paths


def run_asset(args):
    """Dispatch to asset subcommands."""
    if args.asset_command == "add":
        return _run_asset_add(args)
    else:
        print(f"error: unknown asset subcommand '{args.asset_command}'", file=sys.stderr)
        return 1


def _run_asset_add(args):
    """Add an asset to the vault.

    - Normal (file <= 1 MB): copy to assets/<basename>, commit it.
    - File > 1 MB without --large: refuse (exit 1), copy nothing.
    - --large (>1 MB): copy to assets/local/<basename> (gitignored),
      update the tracked manifest assets/local.manifest.json, commit the manifest.
    """
    vault = Path.cwd().resolve()
    src_path = Path(args.path).resolve()

    if not src_path.exists():
        print(f"error: source file does not exist: {args.path}", file=sys.stderr)
        return 1

    # Read source file bytes
    data = src_path.read_bytes()
    size = len(data)
    sha = hashlib.sha256(data).hexdigest()
    basename = src_path.name

    # Check size threshold
    LARGE_THRESHOLD = 1_048_576  # 1 MB
    if size > LARGE_THRESHOLD and not args.large:
        print(f"error: {basename} is {size} bytes; pass --large to add it to assets/local/", file=sys.stderr)
        return 1

    commit_paths_list = []
    commit_msg = f"cairn asset add: "

    if args.large:
        # --large case: copy to assets/local/ and update manifest
        dest = vault / "assets" / "local" / basename
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)

        manifest_path = vault / "assets" / "local.manifest.json"
        # Load existing manifest or create new
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text())
        else:
            manifest = {"manifest_version": 1, "entries": []}

        # Remove any existing entry with the same path
        manifest["entries"] = [e for e in manifest["entries"] if e.get("path") != f"assets/local/{basename}"]

        # Add new entry
        entry = {
            "path": f"assets/local/{basename}",
            "size_bytes": size,
            "sha256": sha,
            "added": date.today().isoformat(),
            "referenced_by": args.note or "",
        }
        manifest["entries"].append(entry)

        # Sort entries by path for byte-stability
        manifest["entries"].sort(key=lambda e: e.get("path", ""))

        # Write manifest with sorted keys and 2-space indent
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

        commit_paths_list = [manifest_path]
        commit_msg += f"{basename} ({size} bytes, --large)"

        # Warn on stderr about repo impact
        print(f"warning: {basename} ({size} bytes) added to gitignored assets/local/; not backed up by git push", file=sys.stderr)

    else:
        # Normal case: copy to assets/ and commit the file
        dest = vault / "assets" / basename

        # Refuse to overwrite existing file
        if dest.exists():
            print(f"error: {basename} already exists in assets/", file=sys.stderr)
            return 1

        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)

        commit_paths_list = [dest]
        commit_msg += f"assets/{basename}"

    # Handle --note flag
    if args.note:
        note_path = vault / args.note
        if not note_path.exists():
            print(f"error: note does not exist: {args.note}", file=sys.stderr)
            return 1

        # Read note
        fm, body = read_frontmatter(note_path)

        # Append relative markdown link
        if args.large:
            link = f"[{basename}](assets/local/{basename})"
        else:
            link = f"[{basename}](assets/{basename})"
        body += f"\n{link}\n"

        # Set source_url in frontmatter if provided
        if args.source_url:
            fm["source_url"] = args.source_url

        # Atomic write
        temp = note_path.with_suffix(note_path.suffix + ".tmp")
        temp.write_text(write_frontmatter(fm) + body, encoding="utf-8")
        os.replace(temp, note_path)

        commit_paths_list.append(note_path)

    # Commit
    result = commit_paths(commit_paths_list, vault, commit_msg)
    if result.returncode != 0:
        print(f"error: git commit failed: {result.stderr}", file=sys.stderr)
        return 1

    return 0
