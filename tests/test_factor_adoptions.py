"""The curated file where a number crosses from one substance to another.

`lcia-factor-rulings.json` answers one question at a time and refuses to answer
it once the numbers move.  This one answers about a *substance* taking another
substance's number, with a verdict: 62 pesticides whose numbers are a
catch-all's, 23 minerals priced from their elements, ten ions taking their
element's, two conjugate pairs, 53 land classes taking their family's -- and
nine declines, which are the record that somebody looked and said no.

What is tested here is the loader's refusals, and the shape of the shipped
file.  A curated decision that is quietly skipped is a decision that looks
applied and is not, which is the failure `lcia.rulings` raises rather than warns
about, and this file follows it.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from brightway_flows.lcia.adoptions import (
    ADOPTIONS_SCHEMA_VERSION,
    FACTOR_ADOPTIONS_FILEPATH,
    FACTOR_ADOPTIONS_FILEPATHS,
    STEPWISE_FACTOR_ADOPTIONS_FILEPATH,
    FactorAdoptionError,
    NumberFrom,
    Relationship,
    Verdict,
    load_factor_adoptions,
)

VALID = {
    "flow_object_id": "fo-1",
    "substance": "Alanycarb",
    "catch_all": "Insecticides, Unspecified",
    "relationship": "catch-all",
    "verdict": "adopt",
    "categories": ["ecotoxicity-freshwater"],
    "implemented_by": ["ecoinvent Centre"],
    "comment": "Every proposed number is the bucket's; measured on the build.",
}

ION = {
    "flow_object_id": "fo-ion",
    "substance": "Copper, Ion",
    "donor": {"flow_object_id": "fo-cu", "substance": "Copper"},
    "relationship": "ion-of",
    "verdict": "adopt",
    "categories": ["ecotoxicity-freshwater"],
    "implemented_by": ["ecoinvent Centre"],
    "comment": "The ion takes the element's number.",
}


def _write(directory: str, *rows, version=ADOPTIONS_SCHEMA_VERSION, method="ef") -> Path:
    path = Path(directory) / "adoptions.json"
    path.write_text(json.dumps({"schema_version": version, "method": method, "adoptions": list(rows)}))
    return path


class LoadingTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)

    def _load(self, *rows, **kwargs):
        return load_factor_adoptions(_write(self.directory.name, *rows, **kwargs))

    def test_a_valid_file_loads_keyed_on_the_substance(self):
        loaded = self._load(VALID, ION)
        self.assertEqual(set(loaded), {"fo-1", "fo-ion"})
        self.assertIs(loaded["fo-1"].relationship, Relationship.CATCH_ALL)
        self.assertIs(loaded["fo-1"].verdict, Verdict.ADOPT)
        self.assertEqual(loaded["fo-1"].donor_name, "Insecticides, Unspecified")
        self.assertEqual(loaded["fo-ion"].donor.flow_object_id, "fo-cu")
        self.assertEqual(loaded["fo-ion"].donor_name, "Copper")

    def test_a_missing_file_is_no_adoptions_rather_than_an_error(self):
        self.assertEqual(load_factor_adoptions(Path(self.directory.name) / "nowhere.json"), {})

    def test_a_decline_loads_as_one(self):
        loaded = self._load({**ION, "verdict": "decline", "relationship": "substitute"})
        self.assertIs(loaded["fo-ion"].verdict, Verdict.DECLINE)

    def test_an_unknown_verdict_or_relationship_is_refused(self):
        with self.assertRaisesRegex(FactorAdoptionError, "verdict"):
            self._load({**ION, "verdict": "maybe"})
        with self.assertRaisesRegex(FactorAdoptionError, "relationship"):
            self._load({**ION, "relationship": "cousin-of"})

    def test_an_entry_without_a_comment_is_refused(self):
        with self.assertRaisesRegex(FactorAdoptionError, "comment"):
            self._load({**ION, "comment": ""})

    def test_an_entry_naming_no_category_or_implementation_is_refused(self):
        with self.assertRaisesRegex(FactorAdoptionError, "categories"):
            self._load({**ION, "categories": []})
        with self.assertRaisesRegex(FactorAdoptionError, "implementation"):
            self._load({**ION, "implemented_by": []})

    def test_two_entries_for_one_substance_are_refused(self):
        with self.assertRaisesRegex(FactorAdoptionError, "second"):
            self._load(ION, {**ION, "comment": "again"})

    def test_a_file_of_another_schema_version_is_refused(self):
        with self.assertRaisesRegex(FactorAdoptionError, "schema version"):
            self._load(ION, version=1)

    def test_a_file_about_another_method_answers_nothing(self):
        path = _write(self.directory.name, ION, method="stepwise-2006")
        self.assertEqual(load_factor_adoptions(path, method="ef"), {})

    def test_who_the_number_belongs_to_is_required(self):
        """A donor for a relationship, a catch-all for a catch-all, the numbers
        for an own number: an entry with none says only that somebody said yes."""
        with self.assertRaisesRegex(FactorAdoptionError, "names no donor"):
            self._load({**ION, "donor": None})
        with self.assertRaisesRegex(FactorAdoptionError, "catch-all"):
            self._load({**VALID, "catch_all": ""})
        with self.assertRaisesRegex(FactorAdoptionError, "records the numbers"):
            self._load({**VALID, "catch_all": "", "relationship": "formula-weighted"})

    def test_a_substance_is_not_its_own_donor(self):
        with self.assertRaisesRegex(FactorAdoptionError, "its own donor"):
            self._load({**ION, "donor": {"flow_object_id": "fo-ion", "substance": "Copper, Ion"}})

    def test_numbers_of_an_implementation_the_entry_is_not_about_are_refused(self):
        with self.assertRaisesRegex(FactorAdoptionError, "not about"):
            self._load({**ION, "adopted_about": {"Somebody else": [1.0]}})

    def test_a_non_numeric_adopted_about_is_refused(self):
        with self.assertRaisesRegex(FactorAdoptionError, "not a number"):
            self._load({**ION, "adopted_about": {"ecoinvent Centre": ["1.0"]}})

    def test_a_relationship_entry_covers_whatever_number_is_stated(self):
        entry = self._load(ION)["fo-ion"]
        self.assertTrue(entry.covers(category_slug="ecotoxicity-freshwater", speaking={"ecoinvent Centre"}, stated={"ecoinvent Centre": 1.0}))
        self.assertTrue(entry.covers(category_slug="ecotoxicity-freshwater", speaking={"ecoinvent Centre"}, stated={"ecoinvent Centre": 2.0}))
        self.assertFalse(entry.covers(category_slug="land-use", speaking={"ecoinvent Centre"}, stated={"ecoinvent Centre": 1.0}))
        self.assertFalse(entry.covers(category_slug="ecotoxicity-freshwater", speaking={"ecoinvent Centre", "Somebody else"}, stated={"ecoinvent Centre": 1.0, "Somebody else": 1.0}))

    def test_a_pinned_entry_covers_only_its_numbers(self):
        entry = self._load({**VALID, "catch_all": "", "relationship": "formula-weighted", "adopted_about": {"ecoinvent Centre": [1.646e-05]}})["fo-1"]
        self.assertTrue(entry.covers(category_slug="ecotoxicity-freshwater", speaking={"ecoinvent Centre"}, stated={"ecoinvent Centre": 1.646e-05}))
        self.assertFalse(entry.covers(category_slug="ecotoxicity-freshwater", speaking={"ecoinvent Centre"}, stated={"ecoinvent Centre": 1.65e-05}))


class DonorNumberTest(unittest.TestCase):
    """An entry taking the donor's published number, for a recipient nobody
    states (#197): its own shape, and never the other route's."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)

    def _load(self, *rows, **kwargs):
        return load_factor_adoptions(_write(self.directory.name, *rows, **kwargs))

    def test_the_default_is_the_transcriptions_number(self):
        self.assertIs(self._load(ION)["fo-ion"].number_from, NumberFrom.TRANSCRIPTION)

    def test_a_donor_entry_loads(self):
        entry = self._load({**ION, "number_from": "donor"}, method="stepwise-2006")["fo-ion"]
        self.assertIs(entry.number_from, NumberFrom.DONOR)
        self.assertTrue(entry.takes_donor_number(category_slug="ecotoxicity-freshwater", speaking={"ecoinvent Centre"}))
        self.assertFalse(entry.takes_donor_number(category_slug="land-use", speaking={"ecoinvent Centre"}))
        self.assertFalse(entry.takes_donor_number(category_slug="ecotoxicity-freshwater", speaking={"Somebody else"}))

    def test_a_donor_entry_answers_no_stated_row(self):
        entry = self._load({**ION, "number_from": "donor"})["fo-ion"]
        self.assertFalse(entry.covers(category_slug="ecotoxicity-freshwater", speaking={"ecoinvent Centre"}, stated={"ecoinvent Centre": 1.0}))

    def test_a_transcription_entry_takes_no_donor_number(self):
        self.assertFalse(self._load(ION)["fo-ion"].takes_donor_number(category_slug="ecotoxicity-freshwater", speaking={"ecoinvent Centre"}))

    def test_an_unknown_number_from_is_refused(self):
        with self.assertRaisesRegex(FactorAdoptionError, "number_from"):
            self._load({**ION, "number_from": "thin air"})

    def test_a_donor_entry_needs_a_donor(self):
        with self.assertRaisesRegex(FactorAdoptionError, "no donor is named"):
            self._load({**VALID, "number_from": "donor"})

    def test_a_donor_entry_cannot_be_pinned(self):
        with self.assertRaisesRegex(FactorAdoptionError, "cannot pin"):
            self._load({**ION, "number_from": "donor", "adopted_about": {"ecoinvent Centre": [1.0]}})


class TheCuratedFileTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.entries = load_factor_adoptions(method="ef")

    def test_the_file_is_where_the_loader_looks(self):
        self.assertTrue(FACTOR_ADOPTIONS_FILEPATH.exists())

    def test_every_entry_answers_a_stated_row(self):
        for entry in self.entries.values():
            with self.subTest(entry.substance):
                self.assertIs(entry.number_from, NumberFrom.TRANSCRIPTION)

    def test_the_populations_signed_so_far(self):
        by_relationship = Counter(
            (str(entry.relationship), str(entry.verdict)) for entry in self.entries.values()
        )
        self.assertEqual(
            by_relationship,
            Counter({
                ("catch-all", "adopt"): 62,
                ("formula-weighted", "adopt"): 23,
                ("ion-of", "adopt"): 10,
                ("conjugate-of", "adopt"): 1,
                ("salt-of", "adopt"): 1,
                ("land-family", "adopt"): 53,
                ("substitute", "decline"): 6,
                ("catch-all", "decline"): 3,
            }),
        )

    def test_every_entry_is_about_ecoinvents_numbers_alone(self):
        for entry in self.entries.values():
            with self.subTest(entry.substance):
                self.assertEqual(entry.implemented_by, frozenset({"ecoinvent Centre"}))

    def test_only_the_minerals_are_pinned(self):
        pinned = {entry.substance for entry in self.entries.values() if entry.adopted_about}
        self.assertEqual(len(pinned), 23)
        for entry in self.entries.values():
            if entry.adopted_about:
                self.assertIs(entry.relationship, Relationship.FORMULA_WEIGHTED)

    def test_the_declines_are_the_ones_the_issues_argued(self):
        declined = {entry.substance: entry.donor_name for entry in self.entries.values() if entry.verdict is Verdict.DECLINE}
        self.assertEqual(
            declined,
            {
                "α-Hexachlorocyclohexane": "Lindane",
                "β-Hexachlorocyclohexane": "Lindane",
                "δ-Hexachlorocyclohexane": "Lindane",
                "Tetrachlorvinphos": "Rabon",
                "(s)-.alpha.-cyano-3-phenoxybenzyl (z)-(1r)-cis-3-(2-chloro-3,3,3-trifluoropropenyl)-2,2-dimethylcyclopropanecarboxylate": "Cyhalothrin",
                "(R)-2-(4-chloro-2-methylphenoxy)propionic Acid": "Mecoprop",
                "2,4-D Ester": "Herbicides, Unspecified",
                "Dimethyl Hexynediol": "Oils, Unspecified",
                "Fenpropimorph": "Fungicides, Unspecified",
            },
        )

    def test_fenoxycarb_is_not_entered(self):
        """#130's twin: an identity defect for the merge, not a signature here."""
        self.assertNotIn("Fenoxycarb", {entry.substance for entry in self.entries.values()})


class TheStepwiseFileTest(unittest.TestCase):
    """23 metal ions taking their element's published Stepwise number (#197):
    every one an `ion-of` adopt with the number from the donor, about the one
    publisher, and none of them chromium, which Stepwise names itself."""

    @classmethod
    def setUpClass(cls):
        cls.entries = load_factor_adoptions(method="stepwise-2006")

    def test_the_file_is_where_the_loader_looks(self):
        self.assertTrue(STEPWISE_FACTOR_ADOPTIONS_FILEPATH.exists())
        self.assertIn(STEPWISE_FACTOR_ADOPTIONS_FILEPATH, FACTOR_ADOPTIONS_FILEPATHS)

    def test_the_population_signed(self):
        by_shape = Counter(
            (str(entry.relationship), str(entry.verdict), str(entry.number_from))
            for entry in self.entries.values()
        )
        self.assertEqual(by_shape, Counter({("ion-of", "adopt", "donor"): 23}))

    def test_every_entry_is_about_the_one_publisher(self):
        for entry in self.entries.values():
            with self.subTest(entry.substance):
                self.assertEqual(entry.implemented_by, frozenset({"2.-0 LCA consultants"}))
                self.assertFalse(entry.adopted_about)
                self.assertIsNotNone(entry.donor)

    def test_the_elements_are_the_sixteen_stepwise_characterises(self):
        elements = {entry.donor.substance for entry in self.entries.values()}
        self.assertEqual(
            elements,
            {"Antimony", "Arsenic", "Barium", "Beryllium", "Cadmium", "Cobalt", "Copper",
             "Iron", "Lead", "Manganese", "Mercury", "Molybdenum", "Nickel", "Selenium",
             "Silver", "Zinc"},
        )

    def test_chromium_is_the_publishers_business(self):
        """Stepwise names `Chromium III` and `Chromium VI` itself; its silence about
        the trivalent ion's ecotoxicity is a decision, and no entry overrides it."""
        for entry in self.entries.values():
            self.assertNotIn("Chromium", entry.substance)
            self.assertNotEqual(entry.donor.substance, "Chromium")

    def test_the_categories_are_stepwise_toxicity_categories(self):
        allowed = {"ecotoxicity-aquatic", "ecotoxicity-terrestrial",
                   "human-toxicity-carcinogens", "human-toxicity-non-carcinogens"}
        for entry in self.entries.values():
            with self.subTest(entry.substance):
                self.assertTrue(entry.categories <= allowed, entry.categories)

    def test_the_two_files_are_read_for_one_method_at_a_time(self):
        """Copper's ion is signed in both; asked for everything, the loader says so
        rather than keeping one."""
        with self.assertRaisesRegex(FactorAdoptionError, "one method at a time"):
            load_factor_adoptions()


if __name__ == "__main__":
    unittest.main()
