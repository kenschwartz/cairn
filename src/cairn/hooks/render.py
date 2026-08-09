import json
from importlib import resources


def read_scan_source() -> str:
    """Return the text of cairn/scan.py.

    importlib.resources is used instead of Path(scan.__file__) so this works
    whether cairn is installed on disk or run from a zipapp. From a zipapp,
    __file__ points inside the archive and is not a real filesystem path, so
    Path(__file__).read_text() raises NotADirectoryError. resources.files()
    reads package data correctly in both cases.
    """
    return resources.files("cairn").joinpath("scan.py").read_text(encoding="utf-8")


def _template_text(name: str) -> str:
    return resources.files("cairn.hooks").joinpath(name).read_text(encoding="utf-8")


def render_pre_commit(scan_source: str) -> str:
    template = _template_text("pre_commit.py.tmpl")
    return template.replace("{{SCAN_SOURCE}}\n", scan_source)


def render_pre_push(allowlist: list[str]) -> str:
    template = _template_text("pre_push.py.tmpl")
    return template.replace("{{ALLOWLIST}}", json.dumps(allowlist))
