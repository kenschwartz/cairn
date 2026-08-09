import os
import subprocess
from pathlib import Path

from cairn import vault
from cairn.hooks import render
from cairn.gitadapter import run_git
from cairn.config import get_allowlist


def check_remotes(vault_path: Path, allowlist: list[str]):
    result = run_git(["remote", "-v"], vault_path)
    if result.returncode != 0:
        return True, ""
    urls = set()
    for line in result.stdout.strip().splitlines():
        parts = line.split()
        if len(parts) >= 2:
            urls.add(parts[1])
    if not urls:
        return True, "warning: no remotes configured"
    for url in urls:
        if not any(url.startswith(p) for p in allowlist):
            return False, f"error: remote URL not in allowlist: {url}"
    return True, ""


def install_hooks(vault_path: Path, allowlist: list[str]):
    scan_source = render.read_scan_source()
    pre_commit = render.render_pre_commit(scan_source)
    pre_push = render.render_pre_push(allowlist)

    hooks_dir = vault_path / ".git" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)

    pc_path = hooks_dir / "pre-commit"
    pc_path.write_text(pre_commit)
    pc_path.chmod(0o755)

    pp_path = hooks_dir / "pre-push"
    pp_path.write_text(pre_push)
    pp_path.chmod(0o755)


def run_init(args):
    vault_path = Path(args.path).resolve()
    vault_path.mkdir(parents=True, exist_ok=True)

    messages = []

    for name in vault.VAULT_DIRS:
        p = vault_path / name
        if p.exists():
            messages.append(f"{name}/ already exists")
        else:
            p.mkdir(parents=True, exist_ok=True)
            messages.append(f"Created {name}/")

    git_dir = vault_path / ".git"
    if git_dir.exists():
        messages.append("git repository already exists")
    else:
        result = subprocess.run(
            ["git", "init"],
            capture_output=True,
            text=True,
            cwd=str(vault_path),
            env=os.environ.copy(),
        )
        if result.returncode == 0:
            messages.append("Initialized git repository")
        else:
            messages.append("error: git init failed")

    gi_path = vault_path / ".gitignore"
    if gi_path.exists():
        messages.append(".gitignore already exists")
    else:
        messages.append("Created .gitignore")
    vault.write_gitignore(vault_path)

    allowlist = get_allowlist()
    install_hooks(vault_path, allowlist)
    messages.append("Installed git hooks")

    ok, remote_msg = check_remotes(vault_path, allowlist)
    if remote_msg:
        messages.append(remote_msg)
    if not ok:
        for msg in messages:
            print(msg)
        return 1

    email_result = run_git(["config", "user.email"], vault_path)
    email = email_result.stdout.strip()
    if not email:
        messages.append("warning: git user.email is not set; auto-commit will be disabled")

    for msg in messages:
        print(msg)
    return 0
