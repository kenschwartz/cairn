import hashlib
import os
import stat
import shutil
import subprocess
import sys
from pathlib import Path

import cairn.scan as scan_mod
from cairn.hooks import render
from cairn.config import get_allowlist
from cairn.commands.init import check_remotes


def _git_version_ok():
    result = subprocess.run(
        ["git", "--version"],
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    if result.returncode != 0:
        return False
    text = result.stdout.strip()
    try:
        version_str = text.split()[2]
        major, minor = version_str.split(".")[:2]
        return (int(major), int(minor)) >= (2, 30)
    except Exception:
        return False


def _pyyaml_ok():
    try:
        import yaml
        return bool(yaml.__version__)
    except Exception:
        return False


def _cairn_on_path():
    return shutil.which("cairn") is not None


def _is_git_repo(vault_path: Path):
    result = subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        capture_output=True,
        text=True,
        cwd=str(vault_path),
        env=os.environ.copy(),
    )
    return result.returncode == 0


def _verify_hook(hook_path: Path, expected_content: str):
    if not hook_path.exists():
        return False, f"{hook_path.name} missing"
    mode = stat.S_IMODE(hook_path.stat().st_mode)
    if mode != 0o755:
        return False, f"{hook_path.name} mode is {oct(mode)}, expected 0755"
    actual_hash = hashlib.sha256(hook_path.read_bytes()).hexdigest()
    expected_hash = hashlib.sha256(expected_content.encode()).hexdigest()
    if actual_hash != expected_hash:
        return False, f"{hook_path.name} content mismatch (SHA-256)"
    return True, ""


def run_doctor(args):
    vault_path = Path.cwd().resolve()
    messages = []

    py_fail = sys.version_info < (3, 11)
    messages.append(
        f"Python version: {sys.version_info.major}.{sys.version_info.minor} "
        f"{'OK' if not py_fail else 'FAIL'}"
    )

    yaml_fail = not _pyyaml_ok()
    messages.append(f"PyYAML: {'OK' if not yaml_fail else 'FAIL'}")

    git_fail = not _git_version_ok()
    messages.append(f"git: {'OK' if not git_fail else 'FAIL'}")

    email_result = subprocess.run(
        ["git", "config", "user.email"],
        capture_output=True,
        text=True,
        cwd=str(vault_path),
        env=os.environ.copy(),
    )
    email = email_result.stdout.strip()
    email_fail = not email
    if email:
        messages.append(f"git user.email: {email} OK")
    else:
        messages.append("git user.email: not set FAIL")

    repo_fail = not _is_git_repo(vault_path)
    messages.append("vault is git repo: OK" if not repo_fail else "vault is git repo: FAIL")

    hookspath_result = subprocess.run(
        ["git", "config", "--get", "core.hooksPath"],
        capture_output=True,
        text=True,
        cwd=str(vault_path),
        env=os.environ.copy(),
    )
    hookspath_fail = False
    if hookspath_result.returncode == 0 and hookspath_result.stdout.strip():
        diverted = hookspath_result.stdout.strip()
        messages.append(f"core.hooksPath diverted to {diverted} FAIL")
        hookspath_fail = True

    allowlist = get_allowlist()
    scan_source = Path(scan_mod.__file__).read_text()
    expected_pre_commit = render.render_pre_commit(scan_source)
    expected_pre_push = render.render_pre_push(allowlist)

    hooks_dir = vault_path / ".git" / "hooks"
    pc_path = hooks_dir / "pre-commit"
    pp_path = hooks_dir / "pre-push"

    pc_ok, pc_msg = _verify_hook(pc_path, expected_pre_commit)
    pc_fail = not pc_ok
    if pc_ok:
        messages.append("pre-commit hook: OK")
    else:
        messages.append(f"pre-commit hook: {pc_msg} FAIL")

    pp_ok, pp_msg = _verify_hook(pp_path, expected_pre_push)
    pp_fail = not pp_ok
    if pp_ok:
        messages.append("pre-push hook: OK")
    else:
        messages.append(f"pre-push hook: {pp_msg} FAIL")

    remote_ok, remote_msg = check_remotes(vault_path, allowlist)
    remote_fail = not remote_ok
    if remote_ok:
        if "warning" in remote_msg.lower():
            messages.append(f"remotes: {remote_msg}")
        else:
            messages.append("remotes: OK")
    else:
        messages.append(f"remotes: {remote_msg} FAIL")

    if _cairn_on_path():
        messages.append("cairn executable on PATH: OK")
    else:
        messages.append("warning: cairn executable is not on PATH")

    if args.fix and (pc_fail or pp_fail):
        hooks_dir.mkdir(parents=True, exist_ok=True)
        pc_path.write_text(expected_pre_commit)
        pc_path.chmod(0o755)
        pp_path.write_text(expected_pre_push)
        pp_path.chmod(0o755)
        messages.append("--fix: reinstalled hooks")
        pc_ok, _ = _verify_hook(pc_path, expected_pre_commit)
        pp_ok, _ = _verify_hook(pp_path, expected_pre_push)
        pc_fail = not pc_ok
        pp_fail = not pp_ok
        if not pc_fail and not pp_fail:
            for i, msg in enumerate(messages):
                if "hook:" in msg and "FAIL" in msg:
                    messages[i] = msg.replace("FAIL", "FIXED")

    hard_fail = any(
        [
            py_fail,
            yaml_fail,
            git_fail,
            email_fail,
            repo_fail,
            hookspath_fail,
            pc_fail,
            pp_fail,
            remote_fail,
        ]
    )

    for msg in messages:
        print(msg)

    return 1 if hard_fail else 0
