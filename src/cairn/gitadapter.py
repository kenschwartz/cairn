import os
import subprocess
from pathlib import Path

GIT_MIN_VERSION = (2, 30)


def run_git(args, cwd=None, text=True):
    """Run a git command with a copied environment and return CompletedProcess.

    Every git invocation in cairn goes through here so environment handling,
    output capture, and cwd stringification stay in one place. Pass text=False
    to get bytes back (needed for `git show` of arbitrary blobs).
    """
    return subprocess.run(
        ["git"] + [str(a) for a in args],
        capture_output=True,
        text=text,
        cwd=str(cwd) if cwd is not None else None,
        env=os.environ.copy(),
    )


def git_lines(args, cwd=None) -> list[str]:
    """Return the non-empty stdout lines of a git command, or [] if it failed."""
    result = run_git(args, cwd)
    if result.returncode != 0:
        return []
    return result.stdout.strip().splitlines()


def git_config_value(name: str, cwd=None) -> str:
    return run_git(["config", name], cwd).stdout.strip()


def is_git_repo(cwd) -> bool:
    return run_git(["rev-parse", "--git-dir"], cwd).returncode == 0


def init_repo(cwd):
    return run_git(["init"], cwd)


def version_at_least(minimum: tuple[int, int] = GIT_MIN_VERSION) -> bool:
    result = run_git(["--version"])
    if result.returncode != 0:
        return False
    try:
        version_str = result.stdout.strip().split()[2]
        major, minor = version_str.split(".")[:2]
        return (int(major), int(minor)) >= minimum
    except Exception:
        return False


def is_dirty(path: Path, cwd: Path) -> bool:
    return bool(run_git(["status", "--porcelain", path], cwd).stdout.strip())


def commit_paths(paths: list[Path], cwd: Path, message: str):
    for p in paths:
        run_git(["add", p], cwd)
    return run_git(["commit", "-m", message], cwd)
