"""
Unit tests for the scanner's internal helpers (cairn.scan private functions).

test_scan.py covers the rules through scan_bytes(); these tests pin the helpers
directly, including the degenerate inputs the rules never reach: empty strings,
one-digit candidates, and every masking length band.

Hermeticity: no filesystem I/O, no git, no subprocess.
"""

import math

import pytest

import cairn.scan as scan


class TestShannonEntropy:
    def test_empty_string_is_zero(self):
        assert scan._shannon_entropy("") == 0.0

    def test_single_repeated_character_is_zero(self):
        assert scan._shannon_entropy("aaaaaaaa") == 0.0

    def test_uniform_two_symbol_string_is_one_bit(self):
        assert scan._shannon_entropy("abab") == pytest.approx(1.0)

    def test_uniform_n_symbol_string_is_log2_n(self):
        assert scan._shannon_entropy("abcdefgh") == pytest.approx(math.log2(8))

    def test_is_independent_of_symbol_order(self):
        assert scan._shannon_entropy("aabb") == pytest.approx(scan._shannon_entropy("abab"))

    def test_random_looking_token_clears_the_threshold(self):
        assert scan._shannon_entropy("Xk9v2Lq7Zm4Rt8Ns1Pd3Wb6Yc5Jh0Fg") >= scan.ENTROPY_THRESHOLD

    def test_repetitive_token_stays_below_the_threshold(self):
        assert scan._shannon_entropy("abababababababababababababababab") < scan.ENTROPY_THRESHOLD


class TestLuhn:
    def test_empty_string_is_invalid(self):
        assert scan._luhn_valid("") is False

    def test_single_digit_is_invalid(self):
        assert scan._luhn_valid("0") is False

    def test_known_valid_number(self):
        assert scan._luhn_valid("4111111111111111") is True

    def test_off_by_one_check_digit_is_invalid(self):
        assert scan._luhn_valid("4111111111111112") is False

    def test_doubling_carry_subtracts_nine(self):
        # '91': the leading 9 is doubled to 18 and folded back to 9, so 9 + 1 = 10.
        assert scan._luhn_valid("91") is True
        assert scan._luhn_valid("99") is False

    def test_returns_a_bool(self):
        assert isinstance(scan._luhn_valid("4111111111111111"), bool)


class TestMask:
    @pytest.mark.parametrize(
        "value,expected_len",
        [
            ("", 0),
            ("a", 1),
            ("abc", 1),
            ("abcd", 3),
            ("abcdef", 3),
            ("abcdefg", 6),
            ("abcdefghijkl", 6),
            ("abcdefghijklm", 12),
        ],
    )
    def test_length_bands(self, value, expected_len):
        assert len(scan._mask(value)) == expected_len

    def test_never_returns_more_than_the_first_twelve_characters(self):
        assert scan._mask("A" * 100) == "A" * 12

    def test_output_is_always_a_prefix_of_the_input(self):
        for value in ("", "ab", "abcde", "abcdefgh", "abcdefghijklmnop"):
            assert value.startswith(scan._mask(value))

    def test_a_long_secret_is_never_reproduced_whole(self):
        secret = "AKIA" + "Q" * 16
        assert scan._mask(secret) != secret
