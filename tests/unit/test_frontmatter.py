"""
Unit tests for cairn.frontmatter.

write_frontmatter() is a pure function: dict in, YAML frontmatter block out.
Field order, quoting, unicode handling and block-style output are pinned here
because the on-disk note format is part of Cairn's contract.

Hermeticity: no filesystem I/O, no git, no subprocess.
"""

import yaml

from cairn.frontmatter import write_frontmatter


class TestDelimiters:
    def test_starts_and_ends_with_delimiter(self):
        out = write_frontmatter({"title": "Note"})
        assert out.startswith("---\n")
        assert out.endswith("---\n")

    def test_only_two_delimiter_lines(self):
        out = write_frontmatter({"title": "Note", "tags": ["a", "b"]})
        assert [line for line in out.splitlines() if line == "---"] == ["---", "---"]

    def test_empty_dict_yields_empty_body(self):
        assert write_frontmatter({}) == "---\n{}\n---\n"


class TestRoundTrip:
    def test_parses_back_to_the_same_mapping(self):
        data = {
            "id": "abcd1234",
            "title": "Quarterly review",
            "type": "note",
            "status": "active",
            "project": "",
            "tags": ["untagged"],
            "cairn_version": 1,
        }
        parsed = yaml.safe_load(write_frontmatter(data).strip("-\n"))
        assert parsed == data

    def test_field_order_is_preserved(self):
        data = {"z": 1, "a": 2, "m": 3}
        body = write_frontmatter(data)
        assert [line.split(":")[0] for line in body.splitlines()[1:-1]] == ["z", "a", "m"]

    def test_empty_string_value_round_trips(self):
        parsed = yaml.safe_load(write_frontmatter({"project": ""}).strip("-\n"))
        assert parsed == {"project": ""}

    def test_int_stays_int(self):
        parsed = yaml.safe_load(write_frontmatter({"cairn_version": 1}).strip("-\n"))
        assert parsed["cairn_version"] == 1
        assert isinstance(parsed["cairn_version"], int)


class TestFormatting:
    def test_lists_use_block_style_not_flow_style(self):
        body = write_frontmatter({"tags": ["one", "two"]})
        assert "[" not in body
        assert "- one" in body
        assert "- two" in body

    def test_unicode_is_not_escaped(self):
        body = write_frontmatter({"title": "Café résumé"})
        assert "Café résumé" in body
        assert "\\u" not in body

    def test_unicode_round_trips(self):
        parsed = yaml.safe_load(write_frontmatter({"title": "Café"}).strip("-\n"))
        assert parsed["title"] == "Café"

    def test_colon_in_value_is_quoted_and_round_trips(self):
        data = {"title": "Meeting: Q3 planning"}
        parsed = yaml.safe_load(write_frontmatter(data).strip("-\n"))
        assert parsed == data

    def test_value_that_looks_like_a_bool_round_trips_as_string(self):
        parsed = yaml.safe_load(write_frontmatter({"title": "yes"}).strip("-\n"))
        assert parsed["title"] == "yes"

    def test_multiline_value_round_trips(self):
        data = {"title": "line one\nline two"}
        parsed = yaml.safe_load(write_frontmatter(data).strip("-\n"))
        assert parsed == data

    def test_output_is_deterministic(self):
        data = {"title": "Note", "tags": ["a", "b"], "cairn_version": 1}
        assert write_frontmatter(data) == write_frontmatter(data)
