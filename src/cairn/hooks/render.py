import json
from pathlib import Path


def _template_path(name: str) -> Path:
    return Path(__file__).parent / name


def render_pre_commit(scan_source: str) -> str:
    template = _template_path("pre_commit.py.tmpl").read_text()
    return template.replace("{{SCAN_SOURCE}}\n", scan_source)


def render_pre_push(allowlist: list[str]) -> str:
    template = _template_path("pre_push.py.tmpl").read_text()
    return template.replace("{{ALLOWLIST}}", json.dumps(allowlist))
