"""
Tests driven from the fixture files in tests/fixtures/secrets/.

These are redundant with the unit tests in test_scan.py but serve a different
purpose: they use the on-disk fixture files as the canonical inputs, matching
what the hook would scan when those files are staged. If the fixture file
content and the test_scan.py inline strings ever diverge, these tests catch it.

v1 scope only (see test_scan.py's module docstring for the full rationale):
card.txt, ssn.txt, high_entropy_token.txt, low_entropy_token.txt,
suppressed_line.txt, and suppressed_adjacent.txt were removed along with
their rules (dropped or deferred to v2). public_key.txt, ssh_public_key.txt,
ssh_public_key_fido.txt, github_token.txt, anthropic_key.txt,
encrypted_private_key.txt, and pgp_private_key_block.txt were added for
the v1 rules (and the later PGP-BLOCK design amendment) the old gate lacked.
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

    def test_encrypted_private_key_fixture_fires(self, scan):
        """
        DESIGN.md rules table: private key pattern includes
        '(?:ENCRYPTED )?'.
        """
        data = (FIXTURES / "encrypted_private_key.txt").read_bytes()
        findings = scan.scan_bytes(data, "encrypted_private_key.txt")
        rules = {f.rule for f in findings}
        assert "private_key" in rules

    def test_pgp_private_key_block_fixture_fires(self, scan):
        """
        DESIGN.md rules table (amended): private key pattern includes
        '(?: BLOCK)?', added specifically so the real-world GPG export
        header '-----BEGIN PGP PRIVATE KEY BLOCK-----' is caught, per
        Ken's recorded intent "catch all key material".
        """
        data = (FIXTURES / "pgp_private_key_block.txt").read_bytes()
        findings = scan.scan_bytes(data, "pgp_private_key_block.txt")
        rules = {f.rule for f in findings}
        assert "private_key" in rules

    def test_public_key_fixture_fires(self, scan):
        data = (FIXTURES / "public_key.txt").read_bytes()
        findings = scan.scan_bytes(data, "public_key.txt")
        rules = {f.rule for f in findings}
        assert "public_key" in rules

    def test_public_key_fixture_does_not_fire_private_key_rule(self, scan):
        data = (FIXTURES / "public_key.txt").read_bytes()
        findings = scan.scan_bytes(data, "public_key.txt")
        rules = {f.rule for f in findings}
        assert "private_key" not in rules

    def test_ssh_public_key_fixture_fires(self, scan):
        data = (FIXTURES / "ssh_public_key.txt").read_bytes()
        findings = scan.scan_bytes(data, "ssh_public_key.txt")
        rules = {f.rule for f in findings}
        assert "ssh_public_key" in rules

    def test_ssh_public_key_fido_fixture_fires(self, scan):
        """FIDO security-key form, per DESIGN.md explicitly."""
        data = (FIXTURES / "ssh_public_key_fido.txt").read_bytes()
        findings = scan.scan_bytes(data, "ssh_public_key_fido.txt")
        rules = {f.rule for f in findings}
        assert "ssh_public_key" in rules

    def test_github_token_fixture_fires(self, scan):
        data = (FIXTURES / "github_token.txt").read_bytes()
        findings = scan.scan_bytes(data, "github_token.txt")
        rules = {f.rule for f in findings}
        assert "github_token" in rules

    def test_anthropic_key_fixture_fires(self, scan):
        data = (FIXTURES / "anthropic_key.txt").read_bytes()
        findings = scan.scan_bytes(data, "anthropic_key.txt")
        rules = {f.rule for f in findings}
        assert "anthropic_api_key" in rules

    def test_no_fixture_leaks_its_own_secret_in_findings(self, scan):
        """
        Cross-fixture invariant: for every secret fixture, no finding's
        excerpt contains the raw secret line verbatim.
        """
        for fixture_path in sorted(FIXTURES.glob("*.txt")):
            data = fixture_path.read_bytes()
            findings = scan.scan_bytes(data, fixture_path.name)
            text = data.decode("utf-8", errors="replace")
            lines = text.splitlines()
            for f in findings:
                secret_line = lines[f.line - 1]
                # The excerpt must be strictly shorter than the full line
                # that contains the secret (a masked excerpt can never be
                # the whole matched line for any v1 rule, all of which are
                # well over 8 characters).
                assert f.excerpt != secret_line, (
                    f"{fixture_path.name}: excerpt equals the full source "
                    f"line, meaning nothing was masked"
                )
