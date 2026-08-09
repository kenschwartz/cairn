"""Link index for Cairn vault (Phase 3).

Tracks outbound wikilinks and markdown links across notes/moc for rename support.
Public API:
- build_index(vault: Path) -> dict: scan and persist to $XDG_CACHE_HOME/cairn/links.json
- inbound_links(index: dict, title: str) -> list[str]: find notes linking to title
"""

import json
import os
import re
from pathlib import Path

from cairn import frontmatter, vault


def _normalize_title(title: str) -> str:
    """
    Normalize title for link matching (lowercase + collapse whitespace).

    Matches the wiki-link resolver rule: lowercase and collapse runs of whitespace
    to a single space, then trim. DESIGN:392.
    """
    normalized = " ".join(title.lower().split())
    return normalized.strip()


def _extract_wikilinks(text: str) -> list[str]:
    """
    Extract wikilink targets from text.

    Returns targets from [[Target]], [[Target|display]], [[Target#heading]].
    The target is the portion before '|' and '#'.
    """
    pattern = r"\[\[([^\]|#]+)(?:[#|][^\]]*)?\]\]"
    matches = re.findall(pattern, text)
    return matches


def _extract_mdlinks(text: str) -> list[str]:
    """
    Extract markdown link targets from text.

    Returns .md targets from [text](relative.md) and [text](relative.md#h).
    Ignores external http/https/mailto links.
    """
    pattern = r"\[([^\]]+)\]\(([^)]+)\)"
    matches = re.findall(pattern, text)
    targets = []
    for _display, target in matches:
        # Skip external links
        if target.startswith(("http://", "https://", "mailto:")):
            continue
        # Only capture .md links
        if target.endswith(".md"):
            # Strip fragment if present
            clean_target = target.split("#")[0]
            targets.append(clean_target)
    return targets


def build_index(vault_path: Path) -> dict:
    """
    Scan notes/ and moc/ and build link index.

    Returns dict keyed by POSIX-relative path:
    {rel_path: {title, title_norm, outbound_wikilinks:[], outbound_mdlinks:[], headings:[]}}
    Persists to $XDG_CACHE_HOME/cairn/links.json.

    Malformed notes (read_frontmatter raises) are skipped.
    """
    index = {}
    notes = vault.iter_notes_and_moc(vault_path)

    for note_path in notes:
        try:
            fm, body = frontmatter.read_frontmatter(note_path)
        except ValueError:
            # Skip malformed notes
            continue

        rel_path = note_path.relative_to(vault_path).as_posix()
        title = fm.get("title", "")
        title_norm = _normalize_title(title)

        # Extract links from body
        outbound_wikilinks = _extract_wikilinks(body)
        outbound_mdlinks = _extract_mdlinks(body)

        index[rel_path] = {
            "title": title,
            "title_norm": title_norm,
            "outbound_wikilinks": outbound_wikilinks,
            "outbound_mdlinks": outbound_mdlinks,
            "headings": [],  # Reserved for future expansion
        }

    # Persist to cache
    cache_dir = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))) / "cairn"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / "links.json"

    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(index, f, sort_keys=True, indent=2)

    return index


def inbound_links(index: dict, title: str) -> list[str]:
    """
    Find notes that link to the given title.

    Returns list of rel_paths where outbound_wikilinks contains a target that
    normalizes to the given title (case/whitespace insensitive).
    """
    target_norm = _normalize_title(title)
    linkers = []

    for rel_path, record in index.items():
        for link_target in record["outbound_wikilinks"]:
            if _normalize_title(link_target) == target_norm:
                linkers.append(rel_path)
                break

    return linkers
