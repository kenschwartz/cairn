import sys
from pathlib import Path

from cairn import config
from cairn.gitadapter import run_git


def run_remote(args):
    """Dispatch to remote subcommands."""
    if args.remote_command == "add":
        return _run_remote_add(args)
    else:
        print(f"error: unknown remote subcommand '{args.remote_command}'", file=sys.stderr)
        return 1


def _run_remote_add(args):
    """Add a git remote after validating against allowlist."""
    url = args.url
    name = args.name or "origin"

    vault_path = Path.cwd().resolve()

    # Validate URL against allowlist
    allowlist = config.get_allowlist()
    allowed = False
    for prefix in allowlist:
        if url.startswith(prefix):
            allowed = True
            break

    if not allowed:
        print(f"error: URL '{url}' is not in the allowlist", file=sys.stderr)
        return 1

    # Check if remote already exists
    result = run_git(["remote", "-v"], vault_path)
    if result.returncode == 0:
        for line in result.stdout.splitlines():
            if line.startswith(f"{name}\t"):
                print(f"error: remote '{name}' already exists", file=sys.stderr)
                return 1

    # Add the remote
    result = run_git(["remote", "add", name, url], vault_path)
    if result.returncode != 0:
        print(f"error: git remote add failed: {result.stderr}", file=sys.stderr)
        return 1

    return 0
