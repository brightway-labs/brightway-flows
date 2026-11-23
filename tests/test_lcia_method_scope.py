"""A curated factor file says which method it is about, and is read for that one.

Two impact categories can share a slug and be different categories: EF 3.1 has an
`acidification` counted in mol H+-eq from the Accumulated Exceedance model, and a
second method can have one counted in something else from something else.  A
ruling written about the first, obeyed for the second because the slugs matched,
would publish a number no curator ever looked at.

So every curated file that names a category by slug states its method once, at the
top, and every loader takes the method it is being read for.  What these pin is
the two halves of that: a file about another method answers nothing, and a file
about no method at all -- or about one nothing registers -- raises where it is
read rather than quietly ruling on nothing (rule 14).
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from brightway_flows.domain.lcia.crosswalk import ef_method
from brightway_flows.lcia.adoptions import load_factor_adoptions
from brightway_flows.lcia.contradictions import load_underlying_model_factors
from brightway_flows.lcia.misattributions import load_misattributed_factors
from brightway_flows.lcia.precision import load_rounded_printings
from brightway_flows.lcia.rulings import load_factor_rulings
from brightway_flows.lcia.scope import curated_method, out_of_scope

METHOD = ef_method().slug

#: Every loader that reads a curated file about one method's categories, and the
#: key its rows are under.  A loader added without a method is a loader this
#: notices.
LOADERS = (
    (load_factor_rulings, "rulings"),
    (load_factor_adoptions, "adoptions"),
    (load_misattributed_factors, "moves"),
    (load_rounded_printings, "printings"),
    (load_underlying_model_factors, "substances"),
)


class TheFileNamesItsMethodTestCase(unittest.TestCase):
    """`curated_method` on a payload, which is where the check lives."""

    def test_the_method_is_read_back(self):
        self.assertEqual(
            curated_method({"method": METHOD}, filename="x.json"), METHOD
        )

    def test_a_file_naming_no_method_raises(self):
        with self.assertRaises(ValueError) as caught:
            curated_method({"schema_version": 1}, filename="x.json")
        self.assertIn("whose impact categories", str(caught.exception))

    def test_a_file_naming_an_unregistered_method_raises(self):
        """A typo would otherwise load, match nothing, and rule on nothing."""
        with self.assertRaises(ValueError) as caught:
            curated_method({"method": "stepwize"}, filename="x.json")
        self.assertIn("registered methods are", str(caught.exception))

    def test_a_file_about_another_method_is_out_of_scope(self):
        self.assertTrue(
            out_of_scope({"method": METHOD}, filename="x.json", method="other")
        )
        self.assertFalse(
            out_of_scope({"method": METHOD}, filename="x.json", method=METHOD)
        )

    def test_reading_for_no_method_reads_everything(self):
        """What a test and the file's own checks want: no filter at all."""
        self.assertFalse(
            out_of_scope({"method": METHOD}, filename="x.json", method=None)
        )

    def test_an_out_of_scope_file_is_still_checked(self):
        """A typo in a file nobody is reading for is still a typo."""
        with self.assertRaises(ValueError):
            out_of_scope({"method": "stepwize"}, filename="x.json", method=METHOD)


class EveryLoaderTakesAMethodTestCase(unittest.TestCase):
    """The curated files as shipped, read for EF and read for something else."""

    def test_the_shipped_files_are_read_for_ef(self):
        for loader, _key in LOADERS:
            with self.subTest(loader.__name__):
                self.assertTrue(loader(method=METHOD))

    def test_the_shipped_files_answer_nothing_for_another_method(self):
        for loader, _key in LOADERS:
            with self.subTest(loader.__name__):
                self.assertFalse(loader(method="stepwise"))

    def test_a_file_with_no_method_raises_in_every_loader(self):
        for loader, key in LOADERS:
            with self.subTest(loader.__name__), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "curated.json"
                path.write_text(
                    json.dumps({"schema_version": 1, "description": "", key: []})
                )
                with self.assertRaises(Exception):
                    loader(path, method=METHOD)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
