import hashlib
import os
import stat
import subprocess
import sys
from pathlib import Path

import cairn.scan as scan_mod
from cairn.hooks import render
from cairn.commands.init import DEFAULT_ALLOWLIST, get_allowlist, check_remotes


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


def _local_bin_on_path():
    home = Path.home()
    local_bin = str(home / ".local" / "bin")
    path = os.environ.get("PATH", "")
    return local_bin in path


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


def _history_scan(vault_path: Path, depth: int):
    findings = []
    result = subprocess.run(
        ["git", "ls-files"],
        capture_output=True,
        text=True,
        cwd=str(vault_path),
        env=os.environ.copy(),
    )
    for path in result.stdout.strip().splitlines():
        filepath = vault_path / path
        if filepath.is_file():
            try:
                data = filepath.read_bytes()
                findings.extend(scan_mod.scan_bytes(data, path))
            except OSError:
                pass

    log_result = subprocess.run(
        ["git", "log", "--format=%H", f"-n{depth}"],
        capture_output=True,
        text=True,
        cwd=str(vault_path),
        env=os.environ.copy(),
    )
    for commit_hash in log_result.stdout.strip().splitlines():
        files_result = subprocess.run(
            ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", commit_hash],
            capture_output=True,
            text=True,
            cwd=str(vault_path),
            env=os.environ.copy(),
        )
        for path in files_result.stdout.strip().splitlines():
            content_result = subprocess.run(
                ["git", "show", f"{commit_hash}:{path}"],
                capture_output=True,
                cwd=str(vault_path),
                env=os.environ.copy(),
            )
            if content_result.returncode == 0:
                findings.extend(scan_mod.scan_bytes(content_result.stdout, path))
    return findings


def run_doctor(args):
    vault_path = Path.cwd().resolve()
    messages = []
    hard_fail = False

    py_ok = sys.version_info >= (3, 11)
    messages.append(f"Python version: {sys.version_info.major}.{sys.version_info.minor} {'OK' if py_ok else 'FAIL'}")
    if not py_ok:
        hard_fail = True

    yaml_ok = _pyyaml_ok()
    messages.append(f"PyYAML: {'OK' if yaml_ok else 'FAIL'}")
    if not yaml_ok:
        hard_fail = True

    git_ok = _git_version_ok()
    messages.append(f"git: {'OK' if git_ok else 'FAIL'}")
    if not git_ok:
        hard_fail = True

    email_result = subprocess.run(
        ["git", "config", "user.email"],
        capture_output=True,
        text=True,
        cwd=str(vault_path),
        env=os.environ.copy(),
    )
    email = email_result.stdout.strip()
    if email:
        messages.append(f"git user.email: {email} OK")
    else:
        messages.append("git user.email: not set FAIL")
        hard_fail = True

    if _is_git_repo(vault_path):
        messages.append("vault is git repo: OK")
    else:
        messages.append("vault is git repo: FAIL")
        hard_fail = True

    allowlist = get_allowlist()
    scan_source = Path(scan_mod.__file__).read_text()
    expected_pre_commit = render.render_pre_commit(scan_source)
    expected_pre_push = render.render_pre_push(allowlist)

    hooks_dir = vault_path / ".git" / "hooks"
    pc_path = hooks_dir / "pre-commit"
    pp_path = hooks_dir / "pre-push"

    pc_ok, pc_msg = _verify_hook(pc_path, expected_pre_commit)
    if pc_ok:
        messages.append("pre-commit hook: OK")
    else:
        messages.append(f"pre-commit hook: {pc_msg} FAIL")
        hard_fail = True

    pp_ok, pp_msg = _verify_hook(pp_path, expected_pre_push)
    if pp_ok:
        messages.append("pre-push hook: OK")
    else:
        messages.append(f"pre-push hook: {pp_msg} FAIL")
        hard_fail = True

    remote_ok, remote_msg = check_remotes(vault_path, allowlist)
    if remote_ok:
        if "warning" in remote_msg.lower():
            messages.append(f"remotes: {remote_msg}")
        else:
            messages.append("remotes: OK")
    else:
        messages.append(f"remotes: {remote_msg} FAIL")
        hard_fail = True

    if _local_bin_on_path():
        messages.append("~/.local/bin on PATH: OK")
    else:
        messages.append("warning: ~/.local/bin is not on PATH")

    depth = args.scan_history if hasattr(args, "scan_history") and args.scan_history is not None else 20
    history_findings = _history_scan(vault_path, depth)
    if history_findings:
        messages.append(
            f"warning: history scan found {len(history_findings)} potential secret(s)"
        )
        for f in history_findings[:5]:
            messages.append(f"  {f.rule}: {f.path}:{f.line} {f.excerpt}")

    if args.fix and (not pc_ok or not pp_ok):
        hooks_dir.mkdir(parents=True, exist_ok=True)
        pc_path.write_text(expected_pre_commit)
        pc_path.chmod(0o755)
        pp_path.write_text(expected_pre_push)
        pp_path.chmod(0o755)
        messages.append("--fix: reinstalled hooks")
        # Re-verify after fix
        pc_ok, _ = _verify_hook(pc_path, expected_pre_commit)
        pp_ok, _ = _verify_hook(pp_path, expected_pre_push)
        if pc_ok and pp_ok:
            hard_fail = False
            for i, msg in enumerate(messages):
                if "hook:" in msg and "FAIL" in msg:
                    messages[i] = msg.replace("FAIL", "FIXED")

    for msg in messages:
        print(msg)

    return 1 if hard_fail else 0
