import hashlib
import os
import stat
import sys
from pathlib import Path

import cairn.scan as scan_mod
from cairn.errors import CairnError, GitUnavailableError
from cairn.gitadapter import run_git
from cairn.hooks import render
from cairn.commands.init import DEFAULT_ALLOWLIST, get_allowlist, check_remotes


def _git_version_ok(cwd: Path):
    """Return (ok, detail). detail names the reason when not ok."""
    try:
        result = run_git(["--version"], cwd)
    except GitUnavailableError as exc:
        return False, str(exc)
    if result.returncode != 0:
        return False, result.stderr.strip() or f"git --version exited {result.returncode}"
    text = result.stdout.strip()
    fields = text.split()
    if len(fields) < 3:
        return False, f"unrecognised git version output: {text!r}"
    parts = fields[2].split(".")
    if len(parts) < 2 or not parts[0].isdigit() or not parts[1].isdigit():
        return False, f"unrecognised git version: {fields[2]!r}"
    version = (int(parts[0]), int(parts[1]))
    if version < (2, 30):
        return False, f"version {fields[2]} is older than 2.30"
    return True, fields[2]


def _pyyaml_ok():
    """Return (ok, detail)."""
    try:
        import yaml
    except ImportError as exc:
        return False, f"PyYAML is not importable: {exc}"
    version = getattr(yaml, "__version__", "")
    if not version:
        return False, "PyYAML is importable but reports no version"
    return True, version


def _local_bin_on_path():
    home = Path.home()
    local_bin = str(home / ".local" / "bin")
    path = os.environ.get("PATH", "")
    return local_bin in path


def _is_git_repo(vault_path: Path):
    try:
        result = run_git(["rev-parse", "--git-dir"], vault_path)
    except GitUnavailableError:
        return False
    return result.returncode == 0


def _verify_hook(hook_path: Path, expected_content: str):
    if not hook_path.exists():
        return False, f"{hook_path.name} missing"
    try:
        mode = stat.S_IMODE(hook_path.stat().st_mode)
        hook_bytes = hook_path.read_bytes()
    except OSError as exc:
        return False, f"{hook_path.name} could not be read: {exc}"
    if mode != 0o755:
        return False, f"{hook_path.name} mode is {oct(mode)}, expected 0755"
    actual_hash = hashlib.sha256(hook_bytes).hexdigest()
    expected_hash = hashlib.sha256(expected_content.encode()).hexdigest()
    if actual_hash != expected_hash:
        return False, f"{hook_path.name} content mismatch (SHA-256)"
    return True, ""


def _history_scan(vault_path: Path, depth: int):
    """Return (findings, unscanned) where unscanned describes what could not be read.

    A path the scan could not read is reported rather than dropped: an unscanned
    file is not a clean file, and treating it as one hides the very thing the
    detective control exists to surface.
    """
    findings = []
    unscanned = []

    result = run_git(["ls-files"], vault_path)
    if result.returncode != 0:
        unscanned.append(
            "could not list tracked files: "
            + (result.stderr.strip() or f"git ls-files exited {result.returncode}")
        )
    for path in result.stdout.strip().splitlines():
        filepath = vault_path / path
        if filepath.is_file():
            try:
                data = filepath.read_bytes()
            except OSError as exc:
                unscanned.append(f"could not read {path}: {exc}")
                continue
            findings.extend(scan_mod.scan_bytes(data, path))

    log_result = run_git(["log", "--format=%H", f"-n{depth}"], vault_path)
    if log_result.returncode != 0:
        stderr = log_result.stderr.strip()
        # A repo with no commits yet has nothing to scan; anything else is a real failure.
        if "does not have any commits" not in stderr:
            unscanned.append(
                "could not read commit history: "
                + (stderr or f"git log exited {log_result.returncode}")
            )
    for commit_hash in log_result.stdout.strip().splitlines():
        files_result = run_git(
            ["diff-tree", "--no-commit-id", "--name-only", "-r", commit_hash], vault_path
        )
        if files_result.returncode != 0:
            unscanned.append(
                f"could not list files in {commit_hash[:8]}: "
                + (files_result.stderr.strip() or f"git diff-tree exited {files_result.returncode}")
            )
            continue
        for path in files_result.stdout.strip().splitlines():
            content_result = run_git(
                ["show", f"{commit_hash}:{path}"], vault_path, text=False
            )
            if content_result.returncode != 0:
                unscanned.append(f"could not read {path} at {commit_hash[:8]}")
                continue
            findings.extend(scan_mod.scan_bytes(content_result.stdout, path))
    return findings, unscanned


def run_doctor(args):
    vault_path = Path.cwd().resolve()
    messages = []
    # Named failures rather than a single flag, so `--fix` can clear the hook
    # failures it actually repaired without clearing unrelated ones.
    failures = set()

    py_ok = sys.version_info >= (3, 11)
    messages.append(f"Python version: {sys.version_info.major}.{sys.version_info.minor} {'OK' if py_ok else 'FAIL'}")
    if not py_ok:
        failures.add("python")

    yaml_ok, yaml_detail = _pyyaml_ok()
    if yaml_ok:
        messages.append(f"PyYAML: {yaml_detail} OK")
    else:
        messages.append(f"PyYAML: {yaml_detail} FAIL")
        failures.add("pyyaml")

    git_ok, git_detail = _git_version_ok(vault_path)
    if git_ok:
        messages.append(f"git: {git_detail} OK")
    else:
        messages.append(f"git: {git_detail} FAIL")
        failures.add("git")

    try:
        email_result = run_git(["config", "user.email"], vault_path)
        email = email_result.stdout.strip()
        email_error = ""
    except GitUnavailableError as exc:
        email = ""
        email_error = str(exc)
    if email:
        messages.append(f"git user.email: {email} OK")
    elif email_error:
        messages.append(f"git user.email: could not be read ({email_error}) FAIL")
        failures.add("email")
    else:
        messages.append("git user.email: not set FAIL")
        failures.add("email")

    if _is_git_repo(vault_path):
        messages.append("vault is git repo: OK")
    else:
        messages.append("vault is git repo: FAIL")
        failures.add("git-repo")

    allowlist = get_allowlist()
    try:
        scan_source = Path(scan_mod.__file__).read_text()
    except OSError as exc:
        raise CairnError(
            f"could not read the scan source needed to verify the hooks: {exc}"
        ) from exc
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
        failures.add("pre-commit-hook")

    pp_ok, pp_msg = _verify_hook(pp_path, expected_pre_push)
    if pp_ok:
        messages.append("pre-push hook: OK")
    else:
        messages.append(f"pre-push hook: {pp_msg} FAIL")
        failures.add("pre-push-hook")

    try:
        remote_ok, remote_msg = check_remotes(vault_path, allowlist)
    except GitUnavailableError as exc:
        remote_ok, remote_msg = False, f"error: {exc}"
    if remote_ok:
        if "warning" in remote_msg.lower():
            messages.append(f"remotes: {remote_msg}")
        else:
            messages.append("remotes: OK")
    else:
        messages.append(f"remotes: {remote_msg} FAIL")
        failures.add("remotes")

    if _local_bin_on_path():
        messages.append("~/.local/bin on PATH: OK")
    else:
        messages.append("warning: ~/.local/bin is not on PATH")

    depth = args.scan_history if hasattr(args, "scan_history") and args.scan_history is not None else 20
    try:
        history_findings, unscanned = _history_scan(vault_path, depth)
    except GitUnavailableError as exc:
        history_findings, unscanned = [], [str(exc)]
    if history_findings:
        messages.append(
            f"warning: history scan found {len(history_findings)} potential secret(s)"
        )
        for f in history_findings[:5]:
            messages.append(f"  {f.rule}: {f.path}:{f.line} {f.excerpt}")
    for problem in unscanned:
        messages.append(f"warning: history scan incomplete: {problem}")

    if args.fix and (not pc_ok or not pp_ok):
        try:
            hooks_dir.mkdir(parents=True, exist_ok=True)
            pc_path.write_text(expected_pre_commit)
            pc_path.chmod(0o755)
            pp_path.write_text(expected_pre_push)
            pp_path.chmod(0o755)
        except OSError as exc:
            for msg in messages:
                print(msg)
            raise CairnError(f"--fix could not reinstall the hooks: {exc}") from exc
        messages.append("--fix: reinstalled hooks")
        # Re-verify after fix
        pc_ok, pc_msg = _verify_hook(pc_path, expected_pre_commit)
        pp_ok, pp_msg = _verify_hook(pp_path, expected_pre_push)
        for label, ok, detail in (("pre-commit", pc_ok, pc_msg), ("pre-push", pp_ok, pp_msg)):
            if ok:
                failures.discard(f"{label}-hook")
            else:
                messages.append(f"--fix: {label} hook still failing: {detail}")
        if pc_ok and pp_ok:
            for i, msg in enumerate(messages):
                if "hook:" in msg and "FAIL" in msg:
                    messages[i] = msg.replace("FAIL", "FIXED")

    for msg in messages:
        print(msg)

    return 1 if failures else 0
