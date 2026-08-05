"""
Global fixtures and hermeticity enforcement for the Cairn test suite.

All tests that touch git or the filesystem run against tmp_path.
No test may read or write the real vault, real $HOME, or the user's git config.
"""

import os
import subprocess
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Session-scoped hermeticity: isolate HOME, git identity, git config
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True, scope="session")
def hermetic_env(tmp_path_factory):
    """
    Redirect HOME, GIT_CONFIG_GLOBAL, and GIT_CONFIG_SYSTEM to temp locations
    so no test can read or contaminate the real user environment.
    Set fixed GIT_AUTHOR_* and GIT_COMMITTER_* so commits are reproducible.
    """
    fake_home = tmp_path_factory.mktemp("fake_home")
    fake_global_cfg = fake_home / ".gitconfig"
    fake_system_cfg = fake_home / "git_system.cfg"

    # Write a minimal global config so git has an identity.
    fake_global_cfg.write_text(
        "[user]\n"
        "    name = Test Author\n"
        "    email = test@cairn.local\n"
    )
    fake_system_cfg.write_text("")

    env_overrides = {
        "HOME": str(fake_home),
        "GIT_CONFIG_GLOBAL": str(fake_global_cfg),
        "GIT_CONFIG_SYSTEM": str(fake_system_cfg),
        "GIT_AUTHOR_NAME": "Test Author",
        "GIT_AUTHOR_EMAIL": "test@cairn.local",
        "GIT_COMMITTER_NAME": "Test Author",
        "GIT_COMMITTER_EMAIL": "test@cairn.local",
    }

    original = {k: os.environ.get(k) for k in env_overrides}
    os.environ.update(env_overrides)

    yield fake_home

    for k, v in original.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


# ---------------------------------------------------------------------------
# tmp_vault: real vault directory with cairn init already run
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_vault(tmp_path):
    """
    Create a directory under tmp_path, run `cairn init` against it, and
    yield the Path.  Tests get a real git repo with really installed hooks.
    Nothing about the hook path is mocked.
    """
    vault = tmp_path / "vault"
    vault.mkdir()

    result = subprocess.run(
        ["cairn", "init", str(vault)],
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    assert result.returncode == 0, (
        f"cairn init failed (rc={result.returncode}):\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    return vault


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def run_cmd(cmd, cwd=None, extra_env=None):
    """Run a command with the current (hermetic) environment."""
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(cwd) if cwd else None,
        env=env,
    )


def git(args, cwd):
    """Run a git command in cwd and return CompletedProcess."""
    return run_cmd(["git"] + args, cwd=cwd)


def make_bare_repo(path: Path) -> Path:
    """Create a bare git repo at path and return it."""
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", "--bare", str(path)],
        check=True,
        capture_output=True,
        env=os.environ.copy(),
    )
    return path
