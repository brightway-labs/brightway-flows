"""The check-digit rule, graded against the registry that issued the numbers.

The arithmetic is small enough that a handful of hand-written cases would pass
whatever rule the module implemented, which is how the ELINCS exception went
unnoticed until #120: every unit test agreed with the code because both were
written from the same account of the scheme.  So the decisive case here is not
a case at all but a sweep of the ECHA EC inventory this package ships -- 106,213
numbers ECHA actually issued, which is the only authority on what a valid EC
number looks like.

Two things have to hold at once, and stating them together is the point.  Every
number in the inventory must validate, or the rule is rejecting real numbers;
and the rule must still refuse a wrong digit, or it has stopped catching the
transcription errors it exists for.
"""

from __future__ import annotations

import unittest

from brightway_flows.integrations.ec_inventory import load_ec_inventory
from brightway_flows.transformers.check_digits import (
    EC_RE,
    ELINCS_LEADING_DIGIT,
    cas_check_digit_valid,
    correct_cas,
    correct_ec,
    ec_check_digit_valid,
)


def _remainder(ec: str) -> int:
    """The weighted sum of the first six digits, mod 11."""
    digits = ec.replace("-", "")
    return sum(int(d) * (i + 1) for i, d in enumerate(digits[:6])) % 11


class ECInventorySweepTestCase(unittest.TestCase):
    """The rule against the whole of the register it is a rule about."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.numbers = [
            record["ec_number"]
            for record in load_ec_inventory()["records"]
            if record.get("ec_number")
        ]

    def test_every_number_echa_issued_is_accepted(self):
        """No published EC number is called malformed.

        This is the assertion #120 is about.  Before the fix 181 of them
        failed, and ten of those reach EF 3.1.
        """
        rejected = [ec for ec in self.numbers if not ec_check_digit_valid(ec)]
        self.assertEqual(
            rejected[:20], [], f"{len(rejected)} published EC numbers rejected"
        )

    def test_the_exception_is_exactly_the_elincs_block(self):
        """181 numbers, all beginning with 4, all carrying check digit 1.

        The count and its confinement to one block are the whole evidence for
        reading remainder 10 as a digit, so they are asserted rather than
        described.  If a future inventory carries a remainder-10 number outside
        the 4 block, or one inside it with any other check digit, the exception
        as written is no longer the right shape and this fails.
        """
        exceptional = [ec for ec in self.numbers if _remainder(ec) == 10]
        self.assertEqual(len(exceptional), 181)
        self.assertEqual({ec[0] for ec in exceptional}, {ELINCS_LEADING_DIGIT})
        self.assertEqual({ec[-1] for ec in exceptional}, {"1"})

    def test_no_published_number_is_wrong_in_any_other_way(self):
        """The other 106,032 satisfy the rule as ordinarily stated.

        Without this the sweep above would also pass for a rule that accepted
        everything, which is the failure mode a check digit exists to prevent.
        """
        ordinary = [ec for ec in self.numbers if _remainder(ec) != 10]
        self.assertEqual(len(ordinary), 106032)
        wrong = [ec for ec in ordinary if int(ec[-1]) != _remainder(ec)]
        self.assertEqual(wrong, [])

    def test_every_number_is_nine_characters_in_the_expected_form(self):
        """`NNN-NNN-N`, which is what the arithmetic above assumes."""
        malformed = [ec for ec in self.numbers if not EC_RE.match(ec)]
        self.assertEqual(malformed[:20], [])


class ECCheckDigitTestCase(unittest.TestCase):
    """The named cases, chosen so each says something the sweep cannot."""

    def test_the_ten_numbers_ef_31_carries(self):
        """The substances #120 was filed for, named rather than counted.

        Every one is remainder 10 in the ELINCS block, and every one has an
        ECHA infocard.  A count of rejections falling to zero would also be
        satisfied by the step no longer running; these ten will not.
        """
        for ec, substance in (
            ("418-140-1", "acryloylmorpholine"),
            ("423-740-1", "Peonile"),
            ("424-090-1", "DMBA"),
            ("424-620-1", "TUPH"),
            ("425-430-1", "cyclopropylacetylene"),
            ("427-440-1", "MMBC"),
            ("429-200-1", "IDS, Na-salz"),
            ("431-060-1", "oxadiazinamine"),
            ("434-800-1", "furilazole"),
            ("435-790-1", "HFE-7500"),
        ):
            with self.subTest(substance=substance):
                self.assertEqual(_remainder(ec), 10)
                self.assertTrue(ec_check_digit_valid(ec))

    def test_a_remainder_of_ten_outside_elincs_is_still_an_error(self):
        """The half of the old rule that was right, and is kept.

        No number in the inventory outside the 4 block has remainder 10 -- the
        sweep above is what says so -- and one turning up there is therefore a
        transcription error with no digit to propose for it.  The three below
        are constructed for that property, not taken from the register: the
        register has none to take.
        """
        for ec in ("200-005-1", "300-003-1", "500-010-1"):
            with self.subTest(ec=ec):
                self.assertEqual(_remainder(ec), 10)
                self.assertFalse(ec_check_digit_valid(ec))
                self.assertIsNone(correct_ec(ec))

    def test_the_elincs_exception_does_not_excuse_a_wrong_digit(self):
        """A 4-block number whose sum is 10 and whose digit is not 1.

        Accepting remainder 10 must not become accepting anything in the
        block: `423-740-7` is Peonile's number mistyped, and is refused.
        """
        self.assertEqual(_remainder("423-740-7"), 10)
        self.assertFalse(ec_check_digit_valid("423-740-7"))
        self.assertEqual(correct_ec("423-740-7"), "423-740-1")

    def test_an_ordinary_wrong_digit_is_corrected(self):
        """Water is 231-791-2; a mistyped last digit is put back."""
        self.assertTrue(ec_check_digit_valid("231-791-2"))
        self.assertFalse(ec_check_digit_valid("231-791-5"))
        self.assertEqual(correct_ec("231-791-5"), "231-791-2")

    def test_a_string_that_is_not_an_ec_number_is_refused(self):
        """Nothing to compute over, so nothing to propose."""
        for ec in ("", "231-791", "1231-791-2", "231-791-X", "7732-18-5"):
            with self.subTest(ec=ec):
                self.assertFalse(ec_check_digit_valid(ec))
                self.assertIsNone(correct_ec(ec))


class CASCheckDigitTestCase(unittest.TestCase):
    """Unchanged by #120, and asserted so that it stays that way.

    CAS is a weighted sum mod 10, so it always has a digit and has no
    equivalent of the skipped slot.
    """

    def test_real_numbers_validate(self):
        for cas in ("7732-18-5", "50-00-0", "10461-98-0", "297730-93-9"):
            with self.subTest(cas=cas):
                self.assertTrue(cas_check_digit_valid(cas))

    def test_a_wrong_digit_is_corrected(self):
        self.assertFalse(cas_check_digit_valid("7732-18-1"))
        self.assertEqual(correct_cas("7732-18-1"), "7732-18-5")

    def test_a_string_that_is_not_a_cas_number_is_refused(self):
        for cas in ("", "7732-18", "231-791-2", "7732-18-X"):
            with self.subTest(cas=cas):
                self.assertFalse(cas_check_digit_valid(cas))
                self.assertIsNone(correct_cas(cas))


if __name__ == "__main__":
    unittest.main()
