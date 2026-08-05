"""
Unit tests for the content scanner (cairn.scan).

Every rule needs a positive case AND a negative near-miss, per DESIGN.md
"Pre-commit content scan": 'v1 ships the high-precision credential and
key-material rules ... an implementation ships these and no fewer, and the
test suite pins each with a positive and a negative case.'

v1 scope (DESIGN.md, decided 2026-08-03, "go lighter"): private key block,
AWS access key id, public key block, SSH public key line, GitHub token,
Anthropic API key, plus binary-skip. The labelled high-entropy-token rule
and its entropy gate, the payment-card and SSN rules, and the
cairn:allow-secret suppression marker are NOT v1 (dropped or deferred to
v2 -- see TODO.md "Deferred scan features (v2)") and are intentionally
absent from this file. Do not re-add them without a design change.

Masking is asserted exactly per DESIGN.md "Failure behaviour": masking
happens INSIDE scan_bytes so Finding.excerpt is always safe.

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


def expected_excerpt(secret: str) -> str:
    """
    Hand-derive the expected masked excerpt per DESIGN.md's exact rule:
      - 1-2 chars: fixed placeholder only, no real characters -> "[...]"
      - 3-8 chars: first + last char, middle replaced -> "x[...]y"
      - longer:    first 4 + placeholder + last 4 -> "abcd[...]wxyz"
    This mirrors the contract, not any implementation, so it is safe to
    use for hand-derived assertions against a from-spec implementation.
    """
    n = len(secret)
    if n <= 2:
        return "[...]"
    if n <= 8:
        return secret[0] + "[...]" + secret[-1]
    return secret[:4] + "[...]" + secret[-4:]


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
        """
        Null byte in first 8192 bytes means binary; skip the file.

        The content before the null byte is a genuine v1 rule match (an AWS
        key id), not filler text, so this test actually proves the binary
        skip suppresses a real finding rather than merely proving that
        arbitrary text produces no findings.
        """
        data = b"key = AKIAIOSFODNN7EXAMPLE\x00rest"
        findings = scan.scan_bytes(data, "binary.bin")
        assert findings == [], (
            "Files with null byte in first 8192 bytes must be skipped, even "
            "when the content before the null byte would otherwise match a "
            "rule"
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
# DESIGN.md rules table (amended after an earlier FIX-DESIGN flag on this
# exact gap was raised and accepted -- Ken's recorded intent: "catch all
# key material"): '-----BEGIN (?:(?:RSA|EC|DSA|OPENSSH|PGP) )?
# (?:ENCRYPTED )?PRIVATE KEY(?: BLOCK)?-----'. The optional ' BLOCK' suffix
# is what makes the real GPG ASCII-armored header
# ('-----BEGIN PGP PRIVATE KEY BLOCK-----') match; without it the PGP
# alternative could never fire on real PGP output.
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

    def test_positive_encrypted_bare(self, scan):
        """
        DESIGN.md's rules table adds '(?:ENCRYPTED )?' to the private key
        pattern. '-----BEGIN ENCRYPTED PRIVATE KEY-----' is the standard
        PKCS8 encrypted-key header (e.g. what `openssl pkcs8` emits) and
        must fire.
        """
        data = "-----BEGIN ENCRYPTED PRIVATE KEY-----\nfake\n"
        assert self.RULE in rule_names(findings_for(scan, data))

    def test_positive_encrypted_with_type_prefix(self, scan):
        data = "-----BEGIN RSA ENCRYPTED PRIVATE KEY-----\nfake\n"
        assert self.RULE in rule_names(findings_for(scan, data))

    def test_negative_public_key(self, scan):
        data = "-----BEGIN PUBLIC KEY-----\nMIIBIjAN...\n-----END PUBLIC KEY-----\n"
        assert self.RULE not in rule_names(findings_for(scan, data))

    def test_negative_certificate(self, scan):
        data = "-----BEGIN CERTIFICATE-----\nMIID...\n-----END CERTIFICATE-----\n"
        assert self.RULE not in rule_names(findings_for(scan, data))

    def test_positive_pgp_block_real_world_form(self, scan):
        """
        DESIGN GAP RESOLVED (was flagged as a FIX-DESIGN gap, now accepted
        and fixed at the design level per Ken's recorded intent "catch all
        key material"): DESIGN.md's private key pattern is now
        '-----BEGIN (?:(?:RSA|EC|DSA|OPENSSH|PGP) )?(?:ENCRYPTED )?PRIVATE
        KEY(?: BLOCK)?-----'. The added optional ' BLOCK' suffix is what
        makes GPG's real ASCII-armored header,
        '-----BEGIN PGP PRIVATE KEY BLOCK-----', match. Verified by hand
        against the exact pattern text (re.search, Python 3.14): it now
        matches, full match '-----BEGIN PGP PRIVATE KEY BLOCK-----'
        (37 chars). This is a positive test, not a negative one anymore.
        """
        data = "-----BEGIN PGP PRIVATE KEY BLOCK-----\nfake\n-----END PGP PRIVATE KEY BLOCK-----\n"
        assert self.RULE in rule_names(findings_for(scan, data))

    def test_negative_pgp_public_key_block_does_not_fire_private_key(self, scan):
        """
        Genuine negative control alongside the positive above: a PGP
        PUBLIC key block ('-----BEGIN PGP PUBLIC KEY BLOCK-----') must
        NOT fire the private_key rule -- it is the public counterpart,
        not a secret.

        Note (verified by hand, not assumed): DESIGN.md's public_key
        pattern ('-----BEGIN (?:.* )?PUBLIC KEY-----') was NOT given the
        same '(?: BLOCK)?' treatment as the private_key pattern, so a
        real PGP public key block does not fire public_key EITHER under
        the current design text -- this test asserts only what is true
        (private_key does not fire), not that public_key does. That gap
        is separate from the one just fixed and is reported back, not
        silently patched here.
        """
        data = "-----BEGIN PGP PUBLIC KEY BLOCK-----\nfake\n-----END PGP PUBLIC KEY BLOCK-----\n"
        assert self.RULE not in rule_names(findings_for(scan, data))

    def test_masking(self, scan):
        data = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA...\n"
        fs = findings_for(scan, data)
        rsa_findings = [f for f in fs if f.rule == self.RULE]
        assert rsa_findings
        expected = expected_excerpt("-----BEGIN RSA PRIVATE KEY-----")
        for f in rsa_findings:
            assert f.excerpt == expected, (
                f"Expected hand-derived excerpt {expected!r}, got {f.excerpt!r}"
            )


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
        expected = expected_excerpt(self.VALID_AKIA)
        for f in found:
            assert self.VALID_AKIA not in f.excerpt
            assert f.excerpt == expected, (
                f"Expected hand-derived excerpt {expected!r}, got {f.excerpt!r}"
            )


# ---------------------------------------------------------------------------
# Rule: Public key block
# DESIGN.md rules table: '-----BEGIN (?:.* )?PUBLIC KEY-----'
# 'Public keys are NOT secret; blocking is a cleanliness policy (no key
# material in notes). Drop this row if it ever blocks a legitimate
# SSH-setup note.'
# ---------------------------------------------------------------------------

class TestPublicKeyRule:
    RULE = "public_key"

    def test_positive_bare(self, scan):
        data = "-----BEGIN PUBLIC KEY-----\nMIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8A...\n"
        assert self.RULE in rule_names(findings_for(scan, data))

    def test_positive_rsa_prefixed(self, scan):
        data = "-----BEGIN RSA PUBLIC KEY-----\nMIIBCgKCAQEA...\n"
        assert self.RULE in rule_names(findings_for(scan, data))

    def test_negative_certificate(self, scan):
        """A certificate block is not a public key block."""
        data = "-----BEGIN CERTIFICATE-----\nMIID...\n-----END CERTIFICATE-----\n"
        assert self.RULE not in rule_names(findings_for(scan, data))

    def test_negative_mentions_public_key_without_begin_marker(self, scan):
        """
        The literal text 'PUBLIC KEY-----' with no preceding '-----BEGIN '
        on the same line must not fire (prose ABOUT the format, not the
        format itself).
        """
        data = "This document explains PUBLIC KEY----- format basics."
        assert self.RULE not in rule_names(findings_for(scan, data))

    def test_does_not_also_fire_private_key_rule(self, scan):
        data = "-----BEGIN PUBLIC KEY-----\nMIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8A...\n"
        assert "private_key" not in rule_names(findings_for(scan, data))

    def test_masking(self, scan):
        data = "-----BEGIN PUBLIC KEY-----\nMIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8A...\n"
        fs = findings_for(scan, data)
        found = [f for f in fs if f.rule == self.RULE]
        assert found
        expected = expected_excerpt("-----BEGIN PUBLIC KEY-----")
        for f in found:
            assert f.excerpt == expected, (
                f"Expected hand-derived excerpt {expected!r}, got {f.excerpt!r}"
            )


# ---------------------------------------------------------------------------
# Rule: SSH public key line
# DESIGN.md rules table: '^(?:ssh-rsa|ssh-dss|ssh-ed25519|
# ecdsa-sha2-[a-z0-9-]+|sk-[a-z0-9-]+)(?:@[a-z0-9.-]+)?\s+
# [A-Za-z0-9+/=]{40,}'
# 'authorized_keys / id_*.pub format, including FIDO security-key types
# (sk-ssh-ed25519@openssh.com).'
# ---------------------------------------------------------------------------

class TestSSHPublicKeyRule:
    RULE = "ssh_public_key"

    # 45 chars: clears the {40,} minimum.
    BLOB = "AAAAC3NzaC1lZDI1NTE5AAAAIEXAMPLE0EXAMPLE0EXAM"
    # 35 chars: under the {40,} minimum -- deliberate near-miss.
    SHORT_BLOB = "AAAAC3NzaC1lZDI1NTE5AAAAIEXAMPLE0EX"
    FIDO_BLOB = "AAAAGnNrLXNzaC1lZDI1NTE5QG9wZW5zc2guY29tAAAAIEXAMPLE0EXAMPLE0EXAM"

    def test_positive_ssh_ed25519(self, scan):
        line = f"ssh-ed25519 {self.BLOB} user@example.local"
        assert self.RULE in rule_names(findings_for(scan, line))

    def test_positive_ssh_rsa(self, scan):
        line = f"ssh-rsa {self.BLOB} user@example.local"
        assert self.RULE in rule_names(findings_for(scan, line))

    def test_positive_ecdsa(self, scan):
        line = f"ecdsa-sha2-nistp256 {self.BLOB} user@example.local"
        assert self.RULE in rule_names(findings_for(scan, line))

    def test_positive_fido_sk_ssh_ed25519(self, scan):
        """FIDO security-key form, per DESIGN.md explicitly."""
        line = f"sk-ssh-ed25519@openssh.com {self.FIDO_BLOB} user@example.local"
        assert self.RULE in rule_names(findings_for(scan, line))

    def test_negative_blob_under_40_chars(self, scan):
        line = f"ssh-ed25519 {self.SHORT_BLOB} user@example.local"
        assert self.RULE not in rule_names(findings_for(scan, line))

    def test_negative_not_at_line_start(self, scan):
        """
        DESIGN.md anchors the pattern at '^' (line start). A comment
        prefix before the key type must prevent the match.
        """
        line = f"# ssh-ed25519 {self.BLOB} user@example.local"
        assert self.RULE not in rule_names(findings_for(scan, line))

    def test_negative_unknown_key_type(self, scan):
        line = f"dsa-nope {self.BLOB} user@example.local"
        assert self.RULE not in rule_names(findings_for(scan, line))

    def test_masking(self, scan):
        line = f"ssh-ed25519 {self.BLOB} user@example.local"
        fs = findings_for(scan, line)
        found = [f for f in fs if f.rule == self.RULE]
        assert found
        full_match = f"ssh-ed25519 {self.BLOB}"
        expected = expected_excerpt(full_match)
        for f in found:
            assert self.BLOB not in f.excerpt
            assert f.excerpt == expected, (
                f"Expected hand-derived excerpt {expected!r}, got {f.excerpt!r}"
            )


# ---------------------------------------------------------------------------
# Rule: GitHub token
# DESIGN.md rules table: 'gh[opsru]_[A-Za-z0-9]{36}'
# ---------------------------------------------------------------------------

class TestGithubTokenRule:
    RULE = "github_token"

    # Exactly 36 chars, alnum only, per the {36} exact count.
    CONT_36 = ("EXAMPLE0" * 4) + "EXAM"

    def test_positive_ghp(self, scan):
        assert len(self.CONT_36) == 36
        line = f"token = ghp_{self.CONT_36}"
        assert self.RULE in rule_names(findings_for(scan, line))

    def test_positive_gho(self, scan):
        """oauth-prefixed variant, per the [opsru] character class."""
        line = f"token = gho_{self.CONT_36}"
        assert self.RULE in rule_names(findings_for(scan, line))

    def test_negative_35_chars(self, scan):
        """One character short of the required 36 must not fire."""
        cont_35 = self.CONT_36[:-1]
        assert len(cont_35) == 35
        line = f"token = ghp_{cont_35}"
        assert self.RULE not in rule_names(findings_for(scan, line))

    def test_negative_wrong_prefix_letter(self, scan):
        """'x' is not in the [opsru] class."""
        line = f"token = ghx_{self.CONT_36}"
        assert self.RULE not in rule_names(findings_for(scan, line))

    def test_masking(self, scan):
        line = f"token = ghp_{self.CONT_36}"
        fs = findings_for(scan, line)
        found = [f for f in fs if f.rule == self.RULE]
        assert found
        full_match = f"ghp_{self.CONT_36}"
        assert len(full_match) == 40
        expected = expected_excerpt(full_match)
        for f in found:
            assert self.CONT_36 not in f.excerpt
            assert f.excerpt == expected, (
                f"Expected hand-derived excerpt {expected!r}, got {f.excerpt!r}"
            )


# ---------------------------------------------------------------------------
# Rule: Anthropic API key
# DESIGN.md rules table: 'sk-ant-api[A-Za-z0-9_-]{20,}'
# ---------------------------------------------------------------------------

class TestAnthropicKeyRule:
    RULE = "anthropic_api_key"

    # 20 chars from [A-Za-z0-9_-]: exactly clears the {20,} minimum.
    CONT_20 = "03-EXAMPLE0000000000"

    def test_positive_at_minimum_length(self, scan):
        assert len(self.CONT_20) == 20
        line = f"key = sk-ant-api{self.CONT_20}"
        assert self.RULE in rule_names(findings_for(scan, line))

    def test_positive_longer(self, scan):
        line = f"key = sk-ant-api{self.CONT_20}EXTRAEXTRA"
        assert self.RULE in rule_names(findings_for(scan, line))

    def test_negative_17_chars(self, scan):
        """Three characters short of the {20,} minimum must not fire."""
        cont_17 = "03-EXAMPLE0000000"
        assert len(cont_17) == 17
        line = f"key = sk-ant-api{cont_17}"
        assert self.RULE not in rule_names(findings_for(scan, line))

    def test_negative_missing_api_infix(self, scan):
        """'sk-ant-' without the 'api' infix must not fire."""
        line = f"key = sk-ant-{self.CONT_20}"
        assert self.RULE not in rule_names(findings_for(scan, line))

    def test_masking(self, scan):
        line = f"key = sk-ant-api{self.CONT_20}"
        fs = findings_for(scan, line)
        found = [f for f in fs if f.rule == self.RULE]
        assert found
        full_match = f"sk-ant-api{self.CONT_20}"
        assert len(full_match) == 30
        expected = expected_excerpt(full_match)
        for f in found:
            assert self.CONT_20 not in f.excerpt
            assert f.excerpt == expected, (
                f"Expected hand-derived excerpt {expected!r}, got {f.excerpt!r}"
            )


# ---------------------------------------------------------------------------
# v1 scope EXCLUSION gate (spec-QA review, BLOCK): every other test in this
# file proves a v1 rule DOES fire; none of them proves a dropped/deferred
# rule does NOT. A builder could leave scan.py's v2/dropped rules in place
# (as the current pre-rework implementation in fact does) and pass every
# positive/negative test above while still shipping card, SSN, labelled-
# token, and suppression logic that DESIGN.md's v1 scope explicitly
# excludes (see "Pre-commit content scan": card/SSN dropped; labelled
# high-entropy-token + its entropy gate + cairn:allow-secret suppression
# deferred to v2). These are ABSENCE tests: v1 scan_bytes must yield ZERO
# findings for inputs that the removed rules would have caught, and the
# suppression marker must have NO effect since v1 recognizes no such
# directive. All four are expected RED right now: the current scan.py
# still carries every one of these rules.
# ---------------------------------------------------------------------------

class TestV1ScopeExcludesDroppedAndDeferredRules:
    def test_luhn_valid_card_number_yields_no_findings(self, scan):
        """4111111111111111 is the well-known Luhn-valid VISA test number."""
        findings = findings_for(scan, "card: 4111111111111111")
        assert findings == [], (
            f"v1 ships no payment-card rule (dropped for this vault); a "
            f"Luhn-valid card number must yield ZERO findings. "
            f"Got: {findings}"
        )

    def test_ssn_formatted_line_yields_no_findings(self, scan):
        findings = findings_for(scan, "ssn: 123-45-6789")
        assert findings == [], (
            f"v1 ships no SSN rule (dropped for this vault); an "
            f"SSN-formatted line must yield ZERO findings. "
            f"Got: {findings}"
        )

    def test_labelled_high_entropy_token_yields_no_findings(self, scan):
        """
        A recognized label plus a 40-char random-looking value: exactly
        the shape the v2-deferred labelled-token rule (with its entropy
        gate) was built to catch. v1 must not catch it at all.
        """
        line = "api_key = xK9mP2nQ8rT5vW1yZ3bD6fH0jL4uE7gA9cN2mPqR"
        findings = findings_for(scan, line)
        assert findings == [], (
            f"v1 defers the labelled high-entropy-token rule to v2; a "
            f"labelled token line must yield ZERO findings in v1. "
            f"Got: {findings}"
        )

    def test_suppression_marker_does_not_suppress_v1_finding(self, scan):
        """
        v1 ships no cairn:allow-secret suppression marker (deferred to
        v2). A genuine synthetic AWS key on a line ENDING with the marker
        text must STILL fire aws_access_key_id -- the marker is not yet a
        recognized directive at all in v1, so it must have NO effect,
        positive or negative.
        """
        line = "key = AKIAIOSFODNN7EXAMPLE  cairn:allow-secret"
        findings = findings_for(scan, line)
        assert "aws_access_key_id" in rule_names(findings), (
            f"v1 ships no suppression marker; a genuine AWS key must "
            f"still fire even when the line ends with "
            f"'cairn:allow-secret'. Got: {findings}"
        )


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
# Masking (cross-rule): the exact 3-tier contract from DESIGN.md
# "Pre-commit content scan" / "Failure behaviour":
#   1-2 chars   -> fixed placeholder only, no real characters: "[...]"
#   3-8 chars   -> first + last char, middle replaced: "x[...]y"
#   >8 chars    -> first 4 + placeholder + last 4: "abcd[...]wxyz"
#
# IMPORTANT (documented, not worked around): every v1 rule's minimum
# match length is well above 8 characters (the shortest possible match is
# the 20-char AWS key id; private/public key headers, SSH lines, GitHub
# tokens, and Anthropic keys are all longer). No v1 rule can produce a
# match in the 1-2 or 3-8 char tiers, so those tiers cannot be exercised
# through the public scan_bytes()/Finding contract -- there is no
# documented seam (e.g. a standalone mask() function) to unit-test them
# directly without assuming implementation internals this test author
# must not assume. This is flagged in the return report as a FIX-DESIGN
# gap: either document that v1 never reaches those tiers, or specify a
# masking helper as part of the public contract so a black-box test can
# pin them. The >8 tier below IS the tier every v1 rule actually uses and
# is pinned exactly, hand-derived, for one fixture per rule family.
# ---------------------------------------------------------------------------

class TestMasking:
    def test_private_key_excerpt_exact(self, scan):
        data = "-----BEGIN RSA PRIVATE KEY-----\nfake\n"
        fs = findings_for(scan, data)
        found = [f for f in fs if f.rule == "private_key"]
        assert found
        expected = expected_excerpt("-----BEGIN RSA PRIVATE KEY-----")
        for f in found:
            assert f.excerpt == expected

    def test_aws_key_excerpt_exact(self, scan):
        key = "AKIAIOSFODNN7EXAMPLE"
        fs = findings_for(scan, f"key={key}")
        found = [f for f in fs if f.rule == "aws_access_key_id"]
        assert found
        expected = expected_excerpt(key)
        for f in found:
            assert key not in f.excerpt
            assert f.excerpt == expected

    def test_public_key_excerpt_exact(self, scan):
        data = "-----BEGIN PUBLIC KEY-----\nfake\n"
        fs = findings_for(scan, data)
        found = [f for f in fs if f.rule == "public_key"]
        assert found
        expected = expected_excerpt("-----BEGIN PUBLIC KEY-----")
        for f in found:
            assert f.excerpt == expected

    def test_github_token_excerpt_exact(self, scan):
        cont = ("EXAMPLE0" * 4) + "EXAM"
        fs = findings_for(scan, f"ghp_{cont}")
        found = [f for f in fs if f.rule == "github_token"]
        assert found
        expected = expected_excerpt(f"ghp_{cont}")
        for f in found:
            assert cont not in f.excerpt
            assert f.excerpt == expected

    def test_anthropic_key_excerpt_exact(self, scan):
        cont = "03-EXAMPLE0000000000"
        fs = findings_for(scan, f"sk-ant-api{cont}")
        found = [f for f in fs if f.rule == "anthropic_api_key"]
        assert found
        expected = expected_excerpt(f"sk-ant-api{cont}")
        for f in found:
            assert cont not in f.excerpt
            assert f.excerpt == expected

    def test_no_excerpt_ever_contains_the_full_secret(self, scan):
        """
        Cross-rule invariant, independent of the exact tier math: whatever
        the masking produces, the full matched secret text must never
        appear verbatim in any excerpt.
        """
        secrets_and_lines = [
            ("AKIAIOSFODNN7EXAMPLE", "key = AKIAIOSFODNN7EXAMPLE"),
            (
                ("EXAMPLE0" * 4) + "EXAM",
                "token = ghp_" + (("EXAMPLE0" * 4) + "EXAM"),
            ),
            ("03-EXAMPLE0000000000", "key = sk-ant-api03-EXAMPLE0000000000"),
        ]
        for secret_fragment, line in secrets_and_lines:
            fs = findings_for(scan, line)
            assert fs, f"expected a finding for {line!r}"
            for f in fs:
                assert secret_fragment not in f.excerpt
