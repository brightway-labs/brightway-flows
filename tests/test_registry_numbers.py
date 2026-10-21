"""A registry number is read the same whoever padded it (#375)."""

import unittest

from brightway_flows.domain.registry_numbers import normalize_cas_number


class PaddingTestCase(unittest.TestCase):
    def test_a_padded_number_loses_its_leading_zeros(self):
        self.assertEqual(normalize_cas_number("000108-90-7"), "108-90-7")
        self.assertEqual(normalize_cas_number("023950-58-5"), "23950-58-5")

    def test_an_unpadded_number_is_unchanged(self):
        self.assertEqual(normalize_cas_number("108-90-7"), "108-90-7")
        self.assertEqual(normalize_cas_number("7440-43-9"), "7440-43-9")

    def test_surrounding_space_is_dropped(self):
        self.assertEqual(normalize_cas_number("  000071-43-2 "), "71-43-2")

    def test_only_the_first_segment_is_touched(self):
        """`50-00-0` is formaldehyde; its zeros are its own."""
        self.assertEqual(normalize_cas_number("50-00-0"), "50-00-0")
        self.assertEqual(normalize_cas_number("000050-00-0"), "50-00-0")

    def test_what_is_not_a_cas_number_comes_back_as_it_came(self):
        """An EC number written without hyphens, and openLCA's `E…` values, are
        left for the check-digit step to report rather than half-corrected."""
        for value in ("2025884", "E1730135", "202-588-4-x", "", "abc"):
            with self.subTest(value=value):
                self.assertEqual(normalize_cas_number(value), value.strip())


if __name__ == "__main__":
    unittest.main()
