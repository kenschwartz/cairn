"""
Unit tests for cairn.hooks.render: pure functions, no filesystem beyond
reading the package's own template files, no git.

RAISE fix (docs/reviews/phase1-review-triage-2026-08-03.md, "Worth fixing
in the same round"): render_pre_commit unconditionally strips ONE trailing
newline from scan_source before embedding it between the sentinels, while
the pre_commit.py.tmpl template unconditionally inserts its own newline
separator before the END sentinel. DESIGN.md's "Hook mechanism" section
requires the inlined scan source to be byte-identical to scan.py on disk;
the byte-identity test at tests/integration/test_hooks.py and
tests/integration/test_init_doctor.py pins that today, but only by
comparing against whatever scan.py's CURRENT trailing-newline count
happens to be. This file pins the underlying property directly against
render_pre_commit(), with a fixed, known input, independent of scan.py's
incidental on-disk state.

Verified by hand-tracing the substitution:
  rendered = "...---\\n" + SUBSTITUTED_SOURCE + "\\n# --- END..."
For source ending in exactly one "\\n", render_pre_commit strips that one
newline before substitution, and the template's own separating "\\n"
supplies it back -- byte-identity holds by cancellation. For source with
NO trailing newline, nothing is stripped (the guard is `if
scan_source.endswith("\\n")`), but the template still appends its own
"\\n" before the END sentinel, so the inlined region ends up with ONE
EXTRA byte the source does not have. That is the live bug this file pins.
"""

from pathlib import Path

import pytest


def _extract_inlined(rendered: str) -> str:
    """
    Mirror the exact extraction logic used by the integration byte-identity
    tests (tests/integration/test_hooks.py TestScanSourceByteIdentity and
    tests/integration/test_init_doctor.py TestHookContentPinning), so this
    unit test is checking the same seam by the same method.
    """
    begin = "# --- BEGIN CAIRN SCAN (generated, do not edit) ---"
    end = "# --- END CAIRN SCAN ---"
    start = rendered.index(begin) + len(begin)
    if rendered[start] == "\n":
        start += 1
    end_idx = rendered.index(end)
    return rendered[start:end_idx]


class TestRenderPreCommitByteIdentity:
    def test_sentinels_present(self):
        from cairn.hooks import render
        rendered = render.render_pre_commit("def scan_bytes(d, p):\n    return []\n")
        assert "# --- BEGIN CAIRN SCAN (generated, do not edit) ---" in rendered
        assert "# --- END CAIRN SCAN ---" in rendered

    def test_source_with_trailing_newline_round_trips(self):
        """
        Positive control: the common case (source ends with exactly one
        newline, as most editors write files) must round-trip exactly.
        """
        from cairn.hooks import render
        source = "def scan_bytes(data, path):\n    return []\n"
        assert source.endswith("\n")
        inlined = _extract_inlined(render.render_pre_commit(source))
        assert inlined == source

    def test_source_with_no_trailing_newline_round_trips(self):
        """
        RED PROOF for the RAISE fix: source with NO trailing newline must
        still round-trip exactly. render_pre_commit must not fabricate a
        trailing newline that was not in its input -- the inlined region
        in the hook must be byte-identical to scan.py regardless of
        scan.py's trailing-newline count, not only when that count happens
        to be exactly one.
        """
        from cairn.hooks import render
        source = "def scan_bytes(data, path):\n    return []"
        assert not source.endswith("\n")
        inlined = _extract_inlined(render.render_pre_commit(source))
        assert inlined == source, (
            f"Byte-identity broke for a source with no trailing newline.\n"
            f"input:  {source!r}\n"
            f"inlined: {inlined!r}\n"
            f"This is the exact one-byte drift the RAISE item warns about: "
            f"the strip-one-newline guard in render_pre_commit does nothing "
            f"when there is no newline to strip, but the template still "
            f"appends its own separating newline before the END sentinel."
        )

    def test_source_with_two_trailing_newlines_round_trips(self):
        """A source ending in a blank line (two trailing newlines) must
        also round-trip exactly -- not just the single-newline case."""
        from cairn.hooks import render
        source = "def scan_bytes(data, path):\n    return []\n\n"
        inlined = _extract_inlined(render.render_pre_commit(source))
        assert inlined == source

    def test_real_scan_py_round_trips_today(self):
        """
        Cross-check against the actual scan.py file on disk right now, as
        an end-to-end sanity check alongside the fixed-input tests above.
        """
        import cairn.scan as scan_mod
        from cairn.hooks import render
        scan_src = Path(scan_mod.__file__).read_text()
        inlined = _extract_inlined(render.render_pre_commit(scan_src))
        assert inlined == scan_src


class TestRenderPrePush:
    def test_allowlist_embedded_as_json(self):
        from cairn.hooks import render
        rendered = render.render_pre_push(["https://github.com/CFG-INNERSOURCE/"])
        assert "CFG-INNERSOURCE" in rendered

    def test_allowlist_round_trips_as_valid_json_list(self):
        import json
        from cairn.hooks import render
        allowlist = ["https://github.com/CFG-INNERSOURCE/", "git@github.com:CFG-INNERSOURCE/"]
        rendered = render.render_pre_push(allowlist)
        marker = "ALLOWLIST = "
        idx = rendered.index(marker) + len(marker)
        end_idx = rendered.index("\n", idx)
        parsed = json.loads(rendered[idx:end_idx])
        assert parsed == allowlist
