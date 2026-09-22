"""Claiming a published number against one somebody transcribed.

#49 is the first expectation that has to name a *factor* rather than a flow:
"ecoinvent states ten times what EF states here" is three facts about one flow,
and a subject that could only name the flow would have to choose which of them
it meant.  The `factor` subject kind selects the three separately, and `amount`
is how a claim states the number.

The number is written the way its source prints it -- `"4.78E+03"` -- and the
digits are the tolerance.  JRC 130796 Table 6 rounds to three significant
figures; the build holds 4775.290751488173.  Neither an equality claim nor a
percentage somebody picks would work: the first can never be met and the second
absorbs the transcription error it exists to catch.  Rounding the build's value
to the figures the claim states asks the question the document answers, and
asks the same one of every row.
"""

from __future__ import annotations

import unittest

from brightway_flows.assessment.evaluate import (
    _agrees_to_stated_precision,
    _matches,
)
from brightway_flows.assessment.expectations import (
    ExpectationFileError,
    _check_claim_values,
    significant_figures,
)


class SignificantFiguresTestCase(unittest.TestCase):
    """Leading zeros are placeholders; trailing ones are not."""

    def test_scientific_notation(self):
        self.assertEqual(significant_figures("4.78E+03"), 3)
        self.assertEqual(significant_figures("9.84E-01"), 3)
        self.assertEqual(significant_figures("1.3532E-06"), 5)

    def test_plain_notation(self):
        self.assertEqual(significant_figures("4200"), 4)
        self.assertEqual(significant_figures("0.00420"), 3)
        self.assertEqual(significant_figures("46.5"), 3)

    def test_a_sign_is_not_a_digit(self):
        self.assertEqual(significant_figures("-4.78E+03"), 3)


class AgreesToStatedPrecisionTestCase(unittest.TestCase):

    def test_the_table_value_against_the_published_one(self):
        # Table 6's vanadium row, against what the JRC's implementation holds.
        self.assertTrue(_agrees_to_stated_precision("4.78E+03", 4775.290751488173))

    def test_two_implementations_differing_in_the_last_bit_are_one_number(self):
        # Chromium(6+): 12274.013470217462 under the JRC and 12274.01347021746
        # under the ecoinvent Centre.  One published number, rendered twice.
        self.assertTrue(_agrees_to_stated_precision("1.23E+04", 12274.013470217462))
        self.assertTrue(_agrees_to_stated_precision("1.23E+04", 12274.01347021746))

    def test_an_order_of_magnitude_is_not_absorbed(self):
        # The whole of #49: rounding does not move a decimal point.
        self.assertFalse(_agrees_to_stated_precision("1.3532E-06", 1.3532e-05))
        self.assertFalse(_agrees_to_stated_precision("4.78E+03", 477.5290751488173))

    def test_a_wrong_digit_inside_the_stated_precision_fails(self):
        self.assertFalse(_agrees_to_stated_precision("4.78E+03", 4695.0))

    def test_more_figures_claimed_than_agree(self):
        # `4.7753E+03` states five, and the build's fifth digit is a 3, not a 2.
        self.assertTrue(_agrees_to_stated_precision("4.7753E+03", 4775.290751488173))
        self.assertFalse(_agrees_to_stated_precision("4.7752E+03", 4775.290751488173))

    def test_a_missing_number_is_not_agreement(self):
        self.assertFalse(_agrees_to_stated_precision("4.78E+03", None))
        self.assertFalse(_agrees_to_stated_precision("4.78E+03", "4780"))
        self.assertFalse(_agrees_to_stated_precision("4.78E+03", True))

    def test_the_claim_reaches_it_through_the_ordinary_comparison(self):
        # `_matches` is what a per-row claim goes through, and `amount` has to
        # be routed to the precision comparison there rather than to string
        # equality -- which is what it would get otherwise, and which would be
        # unmet on every build.
        self.assertTrue(_matches("amount", "4.78E+03", 4775.290751488173))
        self.assertFalse(_matches("amount", "4.78E+03", 47752.90751488173))


class LoaderRefusesAFloatTestCase(unittest.TestCase):
    """A float loses the precision the claim is made to, so it is refused.

    Not coerced: `4.78e3` would silently become an exact-equality claim against
    a number no published table states to seventeen digits, and would be unmet
    on every build for a reason that has nothing to do with the pipeline.
    """

    def test_a_float_is_refused(self):
        with self.assertRaises(ExpectationFileError) as caught:
            _check_claim_values("f.json", "0333-x", "factor", {"amount": 4780.0})
        self.assertIn("amount", str(caught.exception))

    def test_a_string_that_is_not_a_number_is_refused(self):
        with self.assertRaises(ExpectationFileError):
            _check_claim_values("f.json", "0333-x", "factor", {"amount": "about 4780"})

    def test_a_string_with_no_digits_is_refused(self):
        with self.assertRaises(ExpectationFileError):
            _check_claim_values("f.json", "0333-x", "factor", {"amount": "0"})

    def test_a_transcribed_number_loads(self):
        _check_claim_values("f.json", "0333-x", "factor", {"amount": "4.78E+03"})


if __name__ == "__main__":
    unittest.main()
