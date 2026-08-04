import os
import subprocess
from pathlib import Path

from cairn.errors import GitCommandError, GitUnavailableError


def run_git(args, cwd, check=False, text=True):
    try:
        result = subprocess.run(
            ["git"] + args,
            capture_output=True,
            text=text,
            cwd=str(cwd),
            env=os.environ.copy(),
        )
    except FileNotFoundError as exc:
        raise GitUnavailableError("git was not found on PATH") from exc
    except OSError as exc:
        raise GitUnavailableError(f"could not run git: {exc}") from exc
    if check and result.returncode != 0:
        stderr = result.stderr if text else result.stderr.decode("utf-8", "replace")
        raise GitCommandError(args, result.returncode, stderr)
    return result


def is_dirty(path: Path, cwd: Path) -> bool:
    result = run_git(["status", "--porcelain", str(path)], cwd, check=True)
    return bool(result.stdout.strip())


def commit_paths(paths: list[Path], cwd: Path, message: str):
    """Stage and commit paths. Returns the first failing CompletedProcess, else the commit."""
    for p in paths:
        add_result = run_git(["add", "--", str(p)], cwd)
        if add_result.returncode != 0:
            return add_result
    return run_git(["commit", "-m", message], cwd)
