import json
from pathlib import Path

import cairn.scan as scan_mod

HOOK_MODE = 0o755


def _template_path(name: str) -> Path:
    return Path(__file__).parent / name


def render_pre_commit(scan_source: str) -> str:
    template = _template_path("pre_commit.py.tmpl").read_text()
    if scan_source.endswith("\n"):
        scan_source = scan_source[:-1]
    return template.replace("{{SCAN_SOURCE}}", scan_source)


def render_pre_push(allowlist: list[str]) -> str:
    template = _template_path("pre_push.py.tmpl").read_text()
    return template.replace("{{ALLOWLIST}}", json.dumps(allowlist))


def render_hooks(allowlist: list[str]) -> dict[str, str]:
    """Render every hook cairn installs, keyed by its filename in .git/hooks."""
    scan_source = Path(scan_mod.__file__).read_text()
    return {
        "pre-commit": render_pre_commit(scan_source),
        "pre-push": render_pre_push(allowlist),
    }


def hooks_dir(vault_path: Path) -> Path:
    return vault_path / ".git" / "hooks"


def install_hooks(
    vault_path: Path,
    allowlist: list[str] | None = None,
    hooks: dict[str, str] | None = None,
) -> None:
    """Write the rendered hooks into the vault, executable.

    Pass already-rendered `hooks` to avoid re-rendering (doctor renders them to
    verify before it decides to reinstall).
    """
    if hooks is None:
        hooks = render_hooks(allowlist or [])
    target_dir = hooks_dir(vault_path)
    target_dir.mkdir(parents=True, exist_ok=True)
    for name, content in hooks.items():
        path = target_dir / name
        path.write_text(content)
        path.chmod(HOOK_MODE)
