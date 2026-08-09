"""Reindex command for Cairn (Phase 3b)."""

from pathlib import Path

from cairn import links
from cairn.commands.dashboard import run_dashboard


def run_reindex(args):
    """
    Regenerate generated outputs via pluggable generators.

    Per docs/decisions.md "reindex is extensible":
    - Phase 3b: dashboard.md + link cache
    - Phase 4: adds indexes/tags.md to the generator list

    Auto-commits generated outputs that changed.
    Link cache is per-machine (not committed).
    """
    vault_path = Path.cwd().resolve()

    # Generator list: extensible for Phase 4
    generators = [
        ("dashboard", run_dashboard),
        ("link_cache", lambda _: links.build_index(vault_path)),
    ]

    # Run each generator
    for name, generator in generators:
        result = generator(None)
        # Generators handle their own commits (dashboard) or cache writes (links)
        if result != 0 and name == "dashboard":
            return result

    return 0
