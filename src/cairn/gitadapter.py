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
    return subprocess.run(
        ["git", "commit", "-m", message],
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env=os.environ.copy(),
    )
