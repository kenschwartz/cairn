"""
Unit tests for cairn.hooks.render.

The rendered hooks are what actually guards every commit and push, and
`cairn doctor` compares the installed hooks against a re-render byte for byte.
So rendering must be deterministic, must inline the scanner verbatim, and must
leave no unsubstituted placeholders behind.

Hermeticity: reads only the packaged templates. No git, no subprocess, no writes.
"""

import ast
import json

import pytest

from cairn.hooks import render


@pytest.fixture()
def scan_source():
    from pathlib import Path

    import cairn.scan as scan_mod

    return Path(scan_mod.__file__).read_text()


class TestRenderPreCommit:
    def test_is_a_python_script(self, scan_source):
        assert render.render_pre_commit(scan_source).startswith("#!/usr/bin/env python3\n")

    def test_leaves_no_placeholder(self, scan_source):
        assert "{{SCAN_SOURCE}}" not in render.render_pre_commit(scan_source)

    def test_inlines_the_scanner_between_its_markers(self, scan_source):
        out = render.render_pre_commit(scan_source)
        begin = out.index("# --- BEGIN CAIRN SCAN")
        end = out.index("# --- END CAIRN SCAN")
        inlined = out[begin:end]
        assert "def scan_bytes(" in inlined
        assert "def _shannon_entropy(" in inlined

    def test_inlined_source_matches_scan_py_line_for_line(self, scan_source):
        out = render.render_pre_commit(scan_source)
        body = out.split("# --- BEGIN CAIRN SCAN (generated, do not edit) ---\n")[1]
        body = body.split("\n# --- END CAIRN SCAN ---")[0]
        assert body.splitlines() == scan_source.splitlines()

    def test_trailing_newline_of_scan_source_is_not_duplicated(self, scan_source):
        assert "\n\n# --- END CAIRN SCAN ---" not in render.render_pre_commit(scan_source)

    def test_source_without_trailing_newline_renders_identically(self, scan_source):
        assert render.render_pre_commit(scan_source.rstrip("\n")) == render.render_pre_commit(
            scan_source
        )

    def test_output_is_valid_python(self, scan_source):
        ast.parse(render.render_pre_commit(scan_source))

    def test_is_deterministic(self, scan_source):
        assert render.render_pre_commit(scan_source) == render.render_pre_commit(scan_source)


class TestRenderPrePush:
    def test_is_a_python_script(self):
        assert render.render_pre_push([]).startswith("#!/usr/bin/env python3\n")

    def test_leaves_no_placeholder(self):
        assert "{{ALLOWLIST}}" not in render.render_pre_push(["https://example.com/"])

    def test_allowlist_is_embedded_as_json(self):
        prefixes = ["https://github.com/ORG/", "git@github.com:ORG/"]
        out = render.render_pre_push(prefixes)
        line = next(line for line in out.splitlines() if line.startswith("ALLOWLIST = "))
        assert json.loads(line[len("ALLOWLIST = ") :]) == prefixes

    def test_empty_allowlist_renders_empty_json_list(self):
        out = render.render_pre_push([])
        assert "ALLOWLIST = []" in out

    def test_quotes_in_a_prefix_do_not_break_the_script(self):
        ast.parse(render.render_pre_push(['https://example.com/"quoted"/']))

    def test_output_is_valid_python(self):
        ast.parse(render.render_pre_push(["https://github.com/ORG/"]))

    def test_is_deterministic(self):
        prefixes = ["https://github.com/ORG/"]
        assert render.render_pre_push(prefixes) == render.render_pre_push(prefixes)


class TestTemplatePath:
    def test_resolves_next_to_the_hooks_package(self):
        path = render._template_path("pre_commit.py.tmpl")
        assert path.is_file()
        assert path.parent.name == "hooks"

    def test_templates_are_packaged(self):
        for name in ("pre_commit.py.tmpl", "pre_push.py.tmpl"):
            assert render._template_path(name).is_file()
