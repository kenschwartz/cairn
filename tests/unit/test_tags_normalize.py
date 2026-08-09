"""
Gating tests for the corrected cairn.tags.normalize_tag (Track B prereq).

DESIGN:441 says: lowercase; every run of non-alphanumeric characters collapsed
to a single hyphen; the slash preserved (so hierarchical tags like
cfg/security work). Phase 1's normalize_tag only lowercased and collapsed
whitespace, which contradicts the spec. This file pins the differentiating cases
(the existing TestTagNormalization in test_new_and_autocommit.py covers the
subset that already passed and continues to pass).

The precise algorithm is in docs/decisions.md "tags.normalize_tag": NFKD +
drop combining marks, lowercase, split on '/', collapse non-alphanumeric runs
to a hyphen per segment, strip, rejoin with '/'.
"""

import pytest

from cairn.tags import normalize_tag


@pytest.mark.parametrize(
    "raw,expected",
    [
        # DESIGN:441 examples
        ("Trade Finance", "trade-finance"),
        ("CFG/Security", "cfg/security"),   # slash preserved
        ("A & B", "a-b"),                    # non-alphanumeric run -> hyphen
        # whitespace / run collapse
        ("foo   bar", "foo-bar"),
        ("foo--bar", "foo-bar"),             # runs collapse to one hyphen
        ("  leading", "leading"),
        ("trailing  ", "trailing"),
        # accent transliteration (NFKD, matches slugs)
        ("café", "cafe"),
        ("Über", "uber"),
        # slash edge cases
        ("a / b", "a/b"),                    # spaces around a slash do not survive
        ("a/b/c", "a/b/c"),                  # multiple slashes preserved
        ("  CFG / Security  ", "cfg/security"),
        # case + already-clean
        ("UPPER", "upper"),
        ("already-clean", "already-clean"),
        ("trade-finance", "trade-finance"),
    ],
)
def test_normalize_tag_design_441(raw, expected):
    assert normalize_tag(raw) == expected


def test_does_not_consume_slash_as_separator():
    # The defining difference from the slug rule: a slash is a hierarchy
    # delimiter, not a separator to be collapsed.
    assert normalize_tag("project/cairn") == "project/cairn"
    assert normalize_tag("Project/Cairn Build") == "project/cairn-build"


def test_lowercase_only_input_unchanged():
    assert normalize_tag("cfg") == "cfg"
    assert normalize_tag("a-b") == "a-b"
