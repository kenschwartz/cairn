"""
Tests driven from the fixture files in tests/fixtures/secrets/.

These are redundant with the unit tests in test_scan.py but serve a different
purpose: they use the on-disk fixture files as the canonical inputs, matching
what the hook would scan when those files are staged. If the fixture file
content and the test_scan.py inline strings ever diverge, these tests catch it.
"""

from pathlib import Path
import pytest

FIXTURES = Path(__file__).parent.parent / "fixtures" / "secrets"


@pytest.fixture(scope="module")
def scan():
    import cairn.scan as s
    return s


class TestFixtureFiles:
    def test_aws_key_fixture_fires(self, scan):
        data = (FIXTURES / "aws_key.txt").read_bytes()
        findings = scan.scan_bytes(data, "aws_key.txt")
        rules = {f.rule for f in findings}
        assert "aws_access_key_id" in rules

    def test_private_key_fixture_fires(self, scan):
        data = (FIXTURES / "private_key.txt").read_bytes()
        findings = scan.scan_bytes(data, "private_key.txt")
        rules = {f.rule for f in findings}
        assert "private_key" in rules

    def test_ssn_fixture_fires(self, scan):
        data = (FIXTURES / "ssn.txt").read_bytes()
        findings = scan.scan_bytes(data, "ssn.txt")
        rules = {f.rule for f in findings}
        assert "us_ssn" in rules

    def test_card_fixture_fires(self, scan):
        data = (FIXTURES / "card.txt").read_bytes()
        findings = scan.scan_bytes(data, "card.txt")
        rules = {f.rule for f in findings}
        assert "payment_card" in rules

    def test_high_entropy_token_fixture_fires(self, scan):
        data = (FIXTURES / "high_entropy_token.txt").read_bytes()
        findings = scan.scan_bytes(data, "high_entropy_token.txt")
        rules = {f.rule for f in findings}
        assert "labelled_token" in rules

    def test_low_entropy_token_fixture_does_not_fire(self, scan):
        """
        The low-entropy fixture must NOT fire.
        It is long enough to reach the entropy gate but must be rejected by it.
        """
        data = (FIXTURES / "low_entropy_token.txt").read_bytes()
        findings = scan.scan_bytes(data, "low_entropy_token.txt")
        rules = {f.rule for f in findings}
        assert "labelled_token" not in rules, (
            f"Low-entropy fixture must not fire labelled_token rule. Got: {rules}"
        )

    def test_suppressed_line_fixture_does_not_fire(self, scan):
        data = (FIXTURES / "suppressed_line.txt").read_bytes()
        findings = scan.scan_bytes(data, "suppressed_line.txt")
        # The suppressed line must produce zero findings.
        assert findings == []

    def test_suppressed_adjacent_fires_on_unsuppressed_line(self, scan):
        """
        First line (no marker) must fire.
        Second line (with marker) must be suppressed.
        """
        data = (FIXTURES / "suppressed_adjacent.txt").read_bytes()
        findings = scan.scan_bytes(data, "suppressed_adjacent.txt")
        # Must have at least one finding (from the unsuppressed line).
        assert len(findings) >= 1
        # No finding must be on line 2 (the suppressed line).
        # The comment lines are 1-2, the secret lines start at 3-4 in the file.
        # Identify the suppressed line by checking that no finding has the marker.
        for f in findings:
            content_line = data.decode("utf-8", errors="replace").splitlines()[f.line - 1]
            assert "cairn:allow-secret" not in content_line, (
                f"Finding at line {f.line} is on a suppressed line"
            )
