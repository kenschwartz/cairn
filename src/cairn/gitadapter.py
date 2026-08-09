import os
import subprocess
from pathlib import Path


def run_git(args, cwd):
    return subprocess.run(
        ["git"] + args,
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env=os.environ.copy(),
    )


def is_dirty(path: Path, cwd: Path) -> bool:
    result = subprocess.run(
        ["git", "status", "--porcelain", str(path)],
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env=os.environ.copy(),
    )
    return bool(result.stdout.strip())


def commit_paths(paths: list[Path], cwd: Path, message: str):
    for p in paths:
        subprocess.run(
            ["git", "add", str(p)],
            capture_output=True,
            cwd=str(cwd),
            env=os.environ.copy(),
        )
    # Commit ONLY the command-owned paths via an explicit pathspec. A bare
    # `git commit -m` would sweep in ANY other file the user had staged,
    # violating "commit only command-owned paths" (DESIGN:746-753). The pathspec
    # scopes the commit; other staged files stay staged and uncommitted.
    return subprocess.run(
        ["git", "commit", "-m", message, "--", *[str(p) for p in paths]],
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env=os.environ.copy(),
    )
