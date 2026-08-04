import json
from pathlib import Path

from cairn.errors import CairnError


def _template_path(name: str) -> Path:
    return Path(__file__).parent / name


def _read_template(name: str) -> str:
    path = _template_path(name)
    try:
        return path.read_text()
    except OSError as exc:
        raise CairnError(f"could not read hook template {path}: {exc}") from exc


def render_pre_commit(scan_source: str) -> str:
    template = _read_template("pre_commit.py.tmpl")
    if scan_source.endswith("\n"):
        scan_source = scan_source[:-1]
    return template.replace("{{SCAN_SOURCE}}", scan_source)


def render_pre_push(allowlist: list[str]) -> str:
    template = _read_template("pre_push.py.tmpl")
    return template.replace("{{ALLOWLIST}}", json.dumps(allowlist))
