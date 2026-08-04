import os
from pathlib import Path

from cairn import vault
from cairn.errors import CairnError
from cairn.hooks import render
from cairn.gitadapter import run_git

DEFAULT_ALLOWLIST = [
    "https://github.com/CFG-INNERSOURCE/",
    "git@github.com:CFG-INNERSOURCE/",
]


def get_allowlist():
    env = os.environ.get("CAIRN_ALLOWED_REMOTE_PREFIXES")
    if env:
        return [p.strip() for p in env.split(",") if p.strip()]
    return DEFAULT_ALLOWLIST[:]


def check_remotes(vault_path: Path, allowlist: list[str]):
    result = run_git(["remote", "-v"], vault_path)
    if result.returncode != 0:
        detail = result.stderr.strip() or f"git exited {result.returncode}"
        return False, f"error: could not read git remotes: {detail}"
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
    import cairn.scan as scan_mod

    try:
        scan_source = Path(scan_mod.__file__).read_text()
    except OSError as exc:
        raise CairnError(f"could not read the scan source to render hooks: {exc}") from exc

    pre_commit = render.render_pre_commit(scan_source)
    pre_push = render.render_pre_push(allowlist)

    git_dir = vault_path / ".git"
    if not git_dir.exists():
        raise CairnError(
            f"cannot install hooks: {vault_path} is not a git repository"
        )

    hooks_dir = git_dir / "hooks"
    try:
        hooks_dir.mkdir(parents=True, exist_ok=True)
        for name, content in (("pre-commit", pre_commit), ("pre-push", pre_push)):
            hook_path = hooks_dir / name
            hook_path.write_text(content)
            hook_path.chmod(0o755)
    except OSError as exc:
        raise CairnError(f"could not install git hooks in {hooks_dir}: {exc}") from exc


def run_init(args):
    vault_path = Path(args.path).resolve()
    messages = []

    try:
        vault_path.mkdir(parents=True, exist_ok=True)

        for name in vault.VAULT_DIRS:
            p = vault_path / name
            if p.exists():
                messages.append(f"{name}/ already exists")
            else:
                p.mkdir(parents=True, exist_ok=True)
                messages.append(f"Created {name}/")
    except OSError as exc:
        raise CairnError(f"could not create the vault layout under {vault_path}: {exc}") from exc

    git_dir = vault_path / ".git"
    if git_dir.exists():
        messages.append("git repository already exists")
    else:
        result = run_git(["init"], vault_path)
        if result.returncode != 0:
            for msg in messages:
                print(msg)
            detail = result.stderr.strip() or f"git exited {result.returncode}"
            raise CairnError(f"git init failed in {vault_path}: {detail}")
        messages.append("Initialized git repository")

    gi_path = vault_path / ".gitignore"
    if gi_path.exists():
        messages.append(".gitignore already exists")
    else:
        messages.append("Created .gitignore")
    try:
        vault.write_gitignore(vault_path)
    except OSError as exc:
        raise CairnError(f"could not write {gi_path}: {exc}") from exc

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
