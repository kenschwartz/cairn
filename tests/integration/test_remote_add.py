"""
Gating tests for `cairn remote add` (Phase 2).

Per docs/decisions.md "cairn remote add": `cairn remote add <url> [--name <name>]`,
default name `origin`; refuse if the name exists (no overwrite); validate the
URL against config.get_allowlist() before adding; non-interactive. Pairs with
the Phase-1 pre-push hook (the friendly adder; the hook is the hard control).

The allowlist is injected hermetically via XDG_CONFIG_HOME -> a temp config.toml.
Remotes under test are local bare repos whose path matches the injected prefix.
"""

import os
import subprocess
from pathlib import Path


def _allowlist_env(tmp_path, prefix):
    """Return an env copy with XDG_CONFIG_HOME pointing at a config that allows
    only the given prefix."""
    xdg = tmp_path / "xdg"
    (xdg / "cairn").mkdir(parents=True)
    (xdg / "cairn" / "config.toml").write_text(
        f'[remote]\nallowed_prefixes = ["{prefix}"]\n'
    )
    env = os.environ.copy()
    env["XDG_CONFIG_HOME"] = str(xdg)
    return env


def _remote_add(vault, args, env):
    return subprocess.run(
        ["cairn", "remote", "add"] + args,
        cwd=str(vault), capture_output=True, text=True, env=env,
    )


def _remotes(vault):
    r = subprocess.run(
        ["git", "remote", "-v"], cwd=str(vault),
        capture_output=True, text=True, env=os.environ.copy(),
    )
    return r.stdout


def _make_bare(path):
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", "--bare", str(path)],
        check=True, capture_output=True, env=os.environ.copy(),
    )
    return path


class TestRemoteAdd:
    def test_allowlisted_url_added_as_origin(self, tmp_vault, tmp_path):
        remotes_dir = tmp_path / "remotes"
        prefix = str(remotes_dir) + "/"
        bare = _make_bare(remotes_dir / "repo1")
        env = _allowlist_env(tmp_path, prefix)
        r = _remote_add(tmp_vault, [str(bare)], env)
        assert r.returncode == 0, r.stderr
        assert str(bare) in _remotes(tmp_vault)

    def test_non_allowlisted_url_refused(self, tmp_vault, tmp_path):
        remotes_dir = tmp_path / "remotes"
        prefix = str(remotes_dir) + "/"
        env = _allowlist_env(tmp_path, prefix)
        evil = "https://evil.example.com/stolen.git"
        r = _remote_add(tmp_vault, [evil], env)
        assert r.returncode != 0, "non-allowlisted URL must be refused"
        assert evil not in _remotes(tmp_vault), "refused URL must not be added"

    def test_custom_name(self, tmp_vault, tmp_path):
        remotes_dir = tmp_path / "remotes"
        prefix = str(remotes_dir) + "/"
        bare = _make_bare(remotes_dir / "repo2")
        env = _allowlist_env(tmp_path, prefix)
        r = _remote_add(tmp_vault, [str(bare), "--name", "upstream"], env)
        assert r.returncode == 0, r.stderr
        out = _remotes(tmp_vault)
        assert "upstream" in out
        assert str(bare) in out

    def test_refuse_when_name_exists(self, tmp_vault, tmp_path):
        remotes_dir = tmp_path / "remotes"
        prefix = str(remotes_dir) + "/"
        bare1 = _make_bare(remotes_dir / "a")
        bare2 = _make_bare(remotes_dir / "b")
        env = _allowlist_env(tmp_path, prefix)
        assert _remote_add(tmp_vault, [str(bare1)], env).returncode == 0
        r = _remote_add(tmp_vault, [str(bare2)], env)  # default name origin again
        assert r.returncode != 0, "must not overwrite an existing remote name"
        # original origin untouched
        assert str(bare1) in _remotes(tmp_vault)
        assert str(bare2) not in _remotes(tmp_vault)
