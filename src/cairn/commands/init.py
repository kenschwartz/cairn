import os
from pathlib import Path

from cairn import vault
from cairn.hooks import render
from cairn.gitadapter import git_config_value, init_repo, run_git

DEFAULT_ALLOWLIST = [
    "https://github.com/CFG-INNERSOURCE/",
    "git@github.com:CFG-INNERSOURCE/",
]


def parse_allowlist(value: str) -> list[str]:
    return [p.strip() for p in value.split(",") if p.strip()]


def get_allowlist():
    env = os.environ.get("CAIRN_ALLOWED_REMOTE_PREFIXES")
    if env:
        return parse_allowlist(env)
    return DEFAULT_ALLOWLIST[:]


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
    elif init_repo(vault_path).returncode == 0:
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
    render.install_hooks(vault_path, allowlist)
    messages.append("Installed git hooks")

    ok, remote_msg = check_remotes(vault_path, allowlist)
    if remote_msg:
        messages.append(remote_msg)
    if not ok:
        for msg in messages:
            print(msg)
        return 1

    if not git_config_value("user.email", vault_path):
        messages.append("warning: git user.email is not set; auto-commit will be disabled")

    for msg in messages:
        print(msg)
    return 0
