"""
Unit tests for the content scanner (cairn.scan).

Every rule needs a positive case AND a negative near-miss.
Entropy gate is pinned from both sides.
Suppression semantics are exact.
Masking is asserted.

Hermeticity: no filesystem I/O, no git, no subprocess.
scan_bytes() is a pure function and is tested as such.
"""

import importlib
import importlib.util
import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Import helpers
# ---------------------------------------------------------------------------

def _import_scan():
    import cairn.scan as scan
    return scan


def _import_scan_stdlib_only():
    """
    Import scan.py with the rest of the cairn package removed from sys.path.
    Enforces the stdlib-only constraint from DESIGN.md.
    """
    import cairn.scan as _normal
    scan_file = Path(_normal.__file__).resolve()

    saved_path = sys.path[:]
    saved_modules = {k: v for k, v in sys.modules.items()}

    # Only include scan.py parent (cairn/ package dir), not its parent.
    sys.path = [str(scan_file.parent)]
    for key in list(sys.modules.keys()):
        if key.startswith("cairn"):
            del sys.modules[key]

    try:
        spec = importlib.util.spec_from_file_location("_scan_isolated", scan_file)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.path = saved_path
        sys.modules.update(saved_modules)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def scan():
    return _import_scan()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def findings_for(scan_mod, text: str, path: str = "test.md"):
    return scan_mod.scan_bytes(text.encode(), path)


def rule_names(findings):
    return {f.rule for f in findings}


# ---------------------------------------------------------------------------
# scan.py stdlib-only constraint
# ---------------------------------------------------------------------------

class TestStdlibOnly:
    def test_scan_imports_with_no_cairn_package(self):
        """Import scan.py with the cairn package removed from sys.path."""
        mod = _import_scan_stdlib_only()
        assert hasattr(mod, "scan_bytes"), (
            "scan.py must expose scan_bytes() at module level"
        )

    def test_scan_bytes_runs_stdlib_only(self):
        mod = _import_scan_stdlib_only()
        result = mod.scan_bytes(b"hello world", "test.md")
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# scan_bytes interface contract
# ---------------------------------------------------------------------------

class TestScanInterface:
    def test_returns_list(self, scan):
        assert isinstance(scan.scan_bytes(b"clean", "f.md"), list)

    def test_empty_bytes_returns_empty(self, scan):
        assert scan.scan_bytes(b"", "f.md") == []

    def test_finding_has_required_fields(self, scan):
        data = b"-----BEGIN RSA PRIVATE KEY-----\nfake body\n"
        findings = scan.scan_bytes(data, "k.pem")
        assert len(findings) >= 1
        f = findings[0]
        assert hasattr(f, "rule")
        assert hasattr(f, "path")
        assert hasattr(f, "line")
        assert hasattr(f, "excerpt")

    def test_path_propagated(self, scan):
        data = b"-----BEGIN PRIVATE KEY-----\nfake\n"
        findings = scan.scan_bytes(data, "myfile.md")
        assert all(f.path == "myfile.md" for f in findings)

    def test_line_number_is_positive_integer(self, scan):
        data = b"-----BEGIN PRIVATE KEY-----\nfake\n"
        findings = scan.scan_bytes(data, "f.md")
        assert all(isinstance(f.line, int) and f.line >= 1 for f in findings)

    def test_never_raises_on_malformed_input(self, scan):
        scan.scan_bytes(b"\xff\xfe\x00bad utf8\xab", "bad.md")

    def test_binary_file_skipped(self, scan):
        """Null byte in first 8192 bytes means binary; skip the file."""
        data = b"secret = abcdefghijklmnopqrstuvwxyz01234\x00rest"
        findings = scan.scan_bytes(data, "binary.bin")
        assert findings == [], (
            "Files with null byte in first 8192 bytes must be skipped"
        )

    def test_null_byte_beyond_8192_does_not_suppress(self, scan):
        """Null byte BEYOND position 8192 does not trigger binary skip."""
        prefix = b"-----BEGIN RSA PRIVATE KEY-----\nfake key body\n"
        padding = b"x" * (8192 - len(prefix) + 1)
        data = prefix + padding + b"\x00"
        findings = scan.scan_bytes(data, "near_binary.md")
        assert len(findings) >= 1


# ---------------------------------------------------------------------------
# Rule: Private key block
# ---------------------------------------------------------------------------

class TestPrivateKeyRule:
    RULE = "private_key"

    def test_positive_rsa(self, scan):
        data = "-----BEGIN RSA PRIVATE KEY-----\nMIIE...\n"
        assert self.RULE in rule_names(findings_for(scan, data))

    def test_positive_ec(self, scan):
        assert self.RULE in rule_names(findings_for(scan, "-----BEGIN EC PRIVATE KEY-----\nfake\n"))

    def test_positive_dsa(self, scan):
        assert self.RULE in rule_names(findings_for(scan, "-----BEGIN DSA PRIVATE KEY-----\nfake\n"))

    def test_positive_openssh(self, scan):
        assert self.RULE in rule_names(findings_for(scan, "-----BEGIN OPENSSH PRIVATE KEY-----\nfake\n"))

    def test_positive_pgp(self, scan):
        assert self.RULE in rule_names(findings_for(scan, "-----BEGIN PGP PRIVATE KEY-----\nfake\n"))

    def test_positive_bare_private_key(self, scan):
        assert self.RULE in rule_names(findings_for(scan, "-----BEGIN PRIVATE KEY-----\nfake\n"))

    def test_negative_public_key(self, scan):
        data = "-----BEGIN PUBLIC KEY-----\nMIIBIjAN...\n-----END PUBLIC KEY-----\n"
        assert self.RULE not in rule_names(findings_for(scan, data))

    def test_negative_certificate(self, scan):
        data = "-----BEGIN CERTIFICATE-----\nMIID...\n-----END CERTIFICATE-----\n"
        assert self.RULE not in rule_names(findings_for(scan, data))

    def test_masking(self, scan):
        data = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA...\n"
        fs = findings_for(scan, data)
        rsa_findings = [f for f in fs if f.rule == self.RULE]
        assert rsa_findings
        for f in rsa_findings:
            assert len(f.excerpt) <= 20, f"Excerpt too long: {f.excerpt!r}"


# ---------------------------------------------------------------------------
# Rule: AWS access key id
# ---------------------------------------------------------------------------

class TestAWSKeyRule:
    RULE = "aws_access_key_id"

    VALID_AKIA = "AKIAIOSFODNN7EXAMPLE"
    VALID_ASIA = "ASIAIOSFODNN7EXAMPL2"
    VALID_AGPA = "AGPAIOSFODNN7EXAMPL3"
    VALID_AIDA = "AIDAIOSFODNN7EXAMPL4"
    VALID_AROA = "AROAIOSFODNN7EXAMPL5"

    def test_positive_akia(self, scan):
        assert self.RULE in rule_names(findings_for(scan, f"key = {self.VALID_AKIA}"))

    def test_positive_asia(self, scan):
        assert self.RULE in rule_names(findings_for(scan, f"session_key = {self.VALID_ASIA}"))

    def test_positive_agpa(self, scan):
        assert self.RULE in rule_names(findings_for(scan, self.VALID_AGPA))

    def test_positive_aida(self, scan):
        assert self.RULE in rule_names(findings_for(scan, self.VALID_AIDA))

    def test_positive_aroa(self, scan):
        assert self.RULE in rule_names(findings_for(scan, self.VALID_AROA))

    def test_negative_akia_15_chars(self, scan):
        """AKIA + only 15 uppercase chars (19 total) must NOT fire."""
        near_miss = "AKIAIOSFODNN7EXAMPL"  # 19 chars
        assert self.RULE not in rule_names(findings_for(scan, near_miss))

    def test_negative_akia_17_chars_no_boundary(self, scan):
        """AKIA + 17 chars running into non-word char must NOT fire."""
        near_miss = "AKIAIOSFODNN7EXAMPLEXX"  # 22 chars total
        assert self.RULE not in rule_names(findings_for(scan, near_miss))

    def test_negative_unknown_prefix(self, scan):
        near_miss = "XXXX0000000000000000"
        assert self.RULE not in rule_names(findings_for(scan, near_miss))

    def test_masking(self, scan):
        fs = findings_for(scan, self.VALID_AKIA)
        found = [f for f in fs if f.rule == self.RULE]
        assert found
        for f in found:
            assert self.VALID_AKIA not in f.excerpt


# ---------------------------------------------------------------------------
# Rule: Labelled high-entropy token
# ---------------------------------------------------------------------------

class TestLabelledTokenRule:
    RULE = "labelled_token"

    HIGH_ENTROPY_VALUE = "xK9mP2nQ8rT5vW1yZ3bD6fH0jL4uE7gA9cN2mPqR"
    # 35 chars, 3 distinct symbols, entropy ~1.58. Long enough to reach the gate.
    LOW_ENTROPY_VALUE = "abcabcabcabcabcabcabcabcabcabcabcab"

    def test_positive_secret(self, scan):
        assert self.RULE in rule_names(findings_for(scan, f"secret = {self.HIGH_ENTROPY_VALUE}"))

    def test_positive_token(self, scan):
        assert self.RULE in rule_names(findings_for(scan, f"token: {self.HIGH_ENTROPY_VALUE}"))

    def test_positive_api_key(self, scan):
        assert self.RULE in rule_names(findings_for(scan, f"api_key = {self.HIGH_ENTROPY_VALUE}"))

    def test_positive_apikey(self, scan):
        assert self.RULE in rule_names(findings_for(scan, f"apikey: {self.HIGH_ENTROPY_VALUE}"))

    def test_positive_password(self, scan):
        assert self.RULE in rule_names(findings_for(scan, f"password = {self.HIGH_ENTROPY_VALUE}"))

    def test_positive_passwd(self, scan):
        assert self.RULE in rule_names(findings_for(scan, f"passwd: {self.HIGH_ENTROPY_VALUE}"))

    def test_positive_access_key(self, scan):
        assert self.RULE in rule_names(findings_for(scan, f"access_key = {self.HIGH_ENTROPY_VALUE}"))

    def test_positive_case_insensitive_label(self, scan):
        assert self.RULE in rule_names(findings_for(scan, f"SECRET = {self.HIGH_ENTROPY_VALUE}"))

    def test_entropy_gate_low_entropy_does_not_fire(self, scan):
        """
        Low-entropy 35-char fixture is long enough to reach the gate
        (clears the {32,} length rule) but must be rejected by the entropy check.
        DESIGN.md: 'abcabcabcabcabcabcabcabcabcabcabcab (35 chars, three distinct symbols, entropy 1.58)'
        """
        line = f"token = {self.LOW_ENTROPY_VALUE}"
        fs = findings_for(scan, line)
        assert self.RULE not in rule_names(fs), (
            f"Low-entropy value must not fire (entropy gate must reject it). "
            f"Got findings: {fs}"
        )

    def test_entropy_gate_high_entropy_fires(self, scan):
        line = f"token = {self.HIGH_ENTROPY_VALUE}"
        assert self.RULE in rule_names(findings_for(scan, line))

    def test_entropy_constant_named_symbol_exists(self, scan):
        assert hasattr(scan, "ENTROPY_THRESHOLD"), (
            "scan.py must expose ENTROPY_THRESHOLD as a named symbol"
        )

    def test_entropy_constant_value_is_3_0(self, scan):
        assert scan.ENTROPY_THRESHOLD == 3.0, (
            f"ENTROPY_THRESHOLD must be 3.0, got {scan.ENTROPY_THRESHOLD}"
        )

    def test_negative_short_value_under_32_chars(self, scan):
        """Under 32 chars: rejected by length rule, never reaches entropy gate."""
        assert self.RULE not in rule_names(findings_for(scan, "token = shortval1234"))

    def test_masking(self, scan):
        line = f"secret = {self.HIGH_ENTROPY_VALUE}"
        fs = findings_for(scan, line)
        found = [f for f in fs if f.rule == self.RULE]
        assert found
        for f in found:
            assert self.HIGH_ENTROPY_VALUE not in f.excerpt


# ---------------------------------------------------------------------------
# Rule: Payment card (Luhn)
# ---------------------------------------------------------------------------

class TestPaymentCardRule:
    RULE = "payment_card"

    VISA_TEST = "4111111111111111"
    MC_TEST = "5500005555555559"
    AMEX_TEST = "371449635398431"
    DISCOVER_TEST = "6011111111111117"

    def test_positive_visa(self, scan):
        assert self.RULE in rule_names(findings_for(scan, self.VISA_TEST))

    def test_positive_mc(self, scan):
        assert self.RULE in rule_names(findings_for(scan, self.MC_TEST))

    def test_positive_amex(self, scan):
        assert self.RULE in rule_names(findings_for(scan, self.AMEX_TEST))

    def test_positive_discover(self, scan):
        assert self.RULE in rule_names(findings_for(scan, self.DISCOVER_TEST))

    def test_positive_with_spaces(self, scan):
        assert self.RULE in rule_names(findings_for(scan, "4111 1111 1111 1111"))

    def test_positive_with_hyphens(self, scan):
        assert self.RULE in rule_names(findings_for(scan, "4111-1111-1111-1111"))

    def test_negative_luhn_fail(self, scan):
        bad_luhn = "4111111111111112"
        assert self.RULE not in rule_names(findings_for(scan, bad_luhn))

    def test_negative_too_short(self, scan):
        """12-digit run is below 13-digit minimum."""
        assert self.RULE not in rule_names(findings_for(scan, "411111111111"))

    def test_negative_commit_context(self, scan):
        text = f"sha: {self.VISA_TEST} in repo"
        fs = findings_for(scan, text)
        assert self.RULE not in rule_names(fs)

    def test_negative_hash_context(self, scan):
        text = f"hash {self.VISA_TEST} end"
        fs = findings_for(scan, text)
        assert self.RULE not in rule_names(fs)

    def test_negative_uuid_context(self, scan):
        text = f"uuid context {self.VISA_TEST} end"
        fs = findings_for(scan, text)
        assert self.RULE not in rule_names(fs)

    def test_negative_build_context(self, scan):
        text = f"build={self.VISA_TEST}"
        fs = findings_for(scan, text)
        assert self.RULE not in rule_names(fs)

    def test_masking(self, scan):
        fs = findings_for(scan, self.VISA_TEST)
        found = [f for f in fs if f.rule == self.RULE]
        assert found
        for f in found:
            assert self.VISA_TEST not in f.excerpt


# ---------------------------------------------------------------------------
# Rule: US SSN
# ---------------------------------------------------------------------------

class TestSSNRule:
    RULE = "us_ssn"

    def test_positive_hyphenated_zero(self, scan):
        assert self.RULE in rule_names(findings_for(scan, "ssn: 000-00-0000"))

    def test_positive_real_pattern(self, scan):
        assert self.RULE in rule_names(findings_for(scan, "My SSN is 123-45-6789."))

    def test_negative_bare_9_digits(self, scan):
        assert self.RULE not in rule_names(findings_for(scan, "reference 123456789 end"))

    def test_negative_wrong_grouping_2_2_4(self, scan):
        assert self.RULE not in rule_names(findings_for(scan, "12-34-5678"))

    def test_negative_wrong_grouping_4_2_3(self, scan):
        assert self.RULE not in rule_names(findings_for(scan, "1234-56-789"))

    def test_masking(self, scan):
        fs = findings_for(scan, "ssn: 000-00-0000")
        found = [f for f in fs if f.rule == self.RULE]
        assert found
        for f in found:
            assert "000-00-0000" not in f.excerpt


# ---------------------------------------------------------------------------
# Suppression marker
# ---------------------------------------------------------------------------

class TestSuppression:
    HIGH = "xK9mP2nQ8rT5vW1yZ3bD6fH0jL4uE7gA9cN2mPqR"

    def test_suppressed_on_same_line_token(self, scan):
        line = f"secret = {self.HIGH}  cairn:allow-secret"
        assert findings_for(scan, line) == []

    def test_suppressed_on_same_line_private_key(self, scan):
        line = "-----BEGIN RSA PRIVATE KEY-----  cairn:allow-secret"
        assert findings_for(scan, line) == []

    def test_suppressed_on_same_line_ssn(self, scan):
        line = "ssn: 000-00-0000  cairn:allow-secret"
        assert findings_for(scan, line) == []

    def test_suppressed_on_same_line_aws(self, scan):
        line = "key = AKIAIOSFODNN7EXAMPLE  cairn:allow-secret"
        assert findings_for(scan, line) == []

    def test_suppression_does_not_affect_adjacent_next_line(self, scan):
        """Marker on line 2 does NOT suppress line 3."""
        text = (
            f"secret = {self.HIGH}  cairn:allow-secret\n"
            f"secret = {self.HIGH}\n"
        )
        fs = findings_for(scan, text)
        assert len(fs) >= 1, "Line without marker must still fire"
        for f in fs:
            assert f.line != 1, (
                "Line 1 has cairn:allow-secret and must be suppressed"
            )

    def test_suppression_does_not_affect_adjacent_prev_line(self, scan):
        """Marker on line 2 does NOT suppress line 1."""
        text = (
            f"secret = {self.HIGH}\n"
            f"secret = {self.HIGH}  cairn:allow-secret\n"
        )
        fs = findings_for(scan, text)
        assert len(fs) >= 1, "Line 1 must still fire"
        assert any(f.line == 1 for f in fs), "Finding must come from line 1"

    def test_suppression_marker_must_be_line_suffix_not_mid_line(self, scan):
        """
        Marker in the middle of the line does NOT suppress.
        DESIGN.md: 'not a substring match anywhere on the line'.
        """
        line = f"see cairn:allow-secret docs and secret = {self.HIGH}"
        fs = findings_for(scan, line)
        assert len(fs) >= 1, (
            "Marker not at line end must NOT suppress the finding"
        )

    def test_suppression_with_trailing_whitespace(self, scan):
        """Trailing whitespace after the marker is stripped; still suppresses."""
        line = f"secret = {self.HIGH}  cairn:allow-secret   "
        assert findings_for(scan, line) == []


# ---------------------------------------------------------------------------
# Sentinel lines must not appear in scan.py itself
# ---------------------------------------------------------------------------

class TestSentinelConstraint:
    def test_scan_py_no_begin_sentinel(self):
        import cairn.scan as scan_mod
        src = Path(scan_mod.__file__).read_text()
        assert "# --- BEGIN CAIRN SCAN" not in src

    def test_scan_py_no_end_sentinel(self):
        import cairn.scan as scan_mod
        src = Path(scan_mod.__file__).read_text()
        assert "# --- END CAIRN SCAN" not in src


# ---------------------------------------------------------------------------
# Masking (cross-rule)
# ---------------------------------------------------------------------------

class TestMasking:
    def test_excerpt_length_cap_private_key(self, scan):
        data = "-----BEGIN RSA PRIVATE KEY-----\nfake\n"
        fs = findings_for(scan, data)
        assert fs
        for f in fs:
            assert len(f.excerpt) <= 20, f"Excerpt too long: {f.excerpt!r}"

    def test_aws_key_not_in_excerpt(self, scan):
        key = "AKIAIOSFODNN7EXAMPLE"
        fs = findings_for(scan, f"key={key}")
        found = [f for f in fs if f.rule == "aws_access_key_id"]
        assert found
        for f in found:
            assert key not in f.excerpt
