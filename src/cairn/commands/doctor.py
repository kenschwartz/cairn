import hashlib
import os
import stat
import sys
from pathlib import Path

import cairn.scan as scan_mod
from cairn.hooks import render
from cairn.gitadapter import git_config_value, git_lines, is_git_repo, run_git, version_at_least
from cairn.commands.init import check_remotes, get_allowlist


class CheckReport:
    """Collects doctor check lines and tracks whether any hard check failed."""

    def __init__(self):
        self.messages = []
        self.hard_fail = False

    def record(self, label: str, ok: bool, detail: str = "") -> bool:
        prefix = f"{label}: {detail} " if detail else f"{label}: "
        self.messages.append(f"{prefix}{'OK' if ok else 'FAIL'}")
        if not ok:
            self.hard_fail = True
        return ok

    def note(self, message: str) -> None:
        self.messages.append(message)


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


def _verify_hook(hook_path: Path, expected_content: str):
    if not hook_path.exists():
        return False, f"{hook_path.name} missing"
    mode = stat.S_IMODE(hook_path.stat().st_mode)
    if mode != render.HOOK_MODE:
        return False, f"{hook_path.name} mode is {oct(mode)}, expected 0755"
    actual_hash = hashlib.sha256(hook_path.read_bytes()).hexdigest()
    expected_hash = hashlib.sha256(expected_content.encode()).hexdigest()
    if actual_hash != expected_hash:
        return False, f"{hook_path.name} content mismatch (SHA-256)"
    return True, ""


def _scan_file(vault_path: Path, path: str):
    filepath = vault_path / path
    if not filepath.is_file():
        return []
    try:
        return scan_mod.scan_bytes(filepath.read_bytes(), path)
    except OSError:
        return []


def _scan_blob(vault_path: Path, commit_hash: str, path: str):
    result = run_git(["show", f"{commit_hash}:{path}"], vault_path, text=False)
    if result.returncode != 0:
        return []
    return scan_mod.scan_bytes(result.stdout, path)


def _history_scan(vault_path: Path, depth: int):
    findings = []
    for path in git_lines(["ls-files"], vault_path):
        findings.extend(_scan_file(vault_path, path))

    for commit_hash in git_lines(["log", "--format=%H", f"-n{depth}"], vault_path):
        changed = git_lines(
            ["diff-tree", "--no-commit-id", "--name-only", "-r", commit_hash], vault_path
        )
        for path in changed:
            findings.extend(_scan_blob(vault_path, commit_hash, path))
    return findings


def run_doctor(args):
    vault_path = Path.cwd().resolve()
    report = CheckReport()

    report.record(
        "Python version",
        sys.version_info >= (3, 11),
        f"{sys.version_info.major}.{sys.version_info.minor}",
    )
    report.record("PyYAML", _pyyaml_ok())
    report.record("git", version_at_least())

    email = git_config_value("user.email", vault_path)
    report.record("git user.email", bool(email), email if email else "not set")
    report.record("vault is git repo", is_git_repo(vault_path))

    allowlist = get_allowlist()
    expected = render.render_hooks(allowlist)
    hooks_dir = render.hooks_dir(vault_path)

    hook_ok = {}
    for name in expected:
        ok, msg = _verify_hook(hooks_dir / name, expected[name])
        hook_ok[name] = ok
        report.record(f"{name} hook", ok, msg)

    remote_ok, remote_msg = check_remotes(vault_path, allowlist)
    if not remote_ok:
        report.record("remotes", False, remote_msg)
    elif "warning" in remote_msg.lower():
        report.note(f"remotes: {remote_msg}")
    else:
        report.record("remotes", True)

    if _local_bin_on_path():
        report.record("~/.local/bin on PATH", True)
    else:
        report.note("warning: ~/.local/bin is not on PATH")

    depth = args.scan_history if getattr(args, "scan_history", None) is not None else 20
    history_findings = _history_scan(vault_path, depth)
    if history_findings:
        report.note(
            f"warning: history scan found {len(history_findings)} potential secret(s)"
        )
        for f in history_findings[:5]:
            report.note(f"  {f.rule}: {f.path}:{f.line} {f.excerpt}")

    if args.fix and not all(hook_ok.values()):
        render.install_hooks(vault_path, hooks=expected)
        report.note("--fix: reinstalled hooks")
        reverified = all(
            _verify_hook(hooks_dir / name, content)[0] for name, content in expected.items()
        )
        if reverified:
            report.hard_fail = False
            for i, msg in enumerate(report.messages):
                if "hook:" in msg and "FAIL" in msg:
                    report.messages[i] = msg.replace("FAIL", "FIXED")

    for msg in report.messages:
        print(msg)

    return 1 if report.hard_fail else 0
