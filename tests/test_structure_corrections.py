"""A curated structure, for the substance the pipeline cannot work one out for.

#129.  Antimony trisulfide reaches every route to a structure and each one is
blocked or wrong: the name reader returns a *mono*sulfide, Common Chemistry
registers the composition and no structure, and EF's own name describes a
four-antimony cage.  So it was published with no structure and, through typing
rule 10, as a substance of variable composition -- which Sb2S3 is not.

Two things are worth testing hardest, and neither is "does it write the value".

The **self-check**: a curator writes the SMILES and also the InChI, the InChIKey
and the formula, and the loader derives all three and refuses the file if they
disagree.  That is what stops the file's readable half drifting from the half
that decides anything.

The **bounds on the class**: a stated class overrules the chemistry rules, so it
must not be able to overrule the rules that say a row is not a substance at all.
"""

from __future__ import annotations

import unittest
from unittest import mock

from brightway_flows.domain.structure_corrections import (
    StructureCorrection,
    correction_for,
    structure_corrections,
)
from brightway_flows.domain.vocabulary import IRIS, Term


class TheCuratedFileIsReadable(unittest.TestCase):
    def test_antimony_trisulfide_is_corrected(self):
        (correction,) = [
            c for c in structure_corrections() if c.cas_number == "1345-04-6"
        ]
        self.assertEqual(correction.molecular_formula, "S3Sb2")
        self.assertEqual(correction.inchikey, "IHBMMJGTJFPEQY-UHFFFAOYSA-N")
        self.assertEqual(correction.inchi, "InChI=1S/3S.2Sb")
        self.assertEqual(correction.flow_type, IRIS[Term.NEUTRAL_MOLECULE])

    def test_the_smiles_is_stored_canonically(self):
        # Not the curator's spelling: what is published has to be the string
        # every other structural value on the record was derived from.
        correction = correction_for(["1345-04-6"])
        self.assertEqual(correction.smiles, "[S]=[Sb][S][Sb]=[S]")

    def test_every_entry_explains_itself(self):
        # A structure asserted on a curator's authority and no argument for it
        # is the thing this file must never become.
        for correction in structure_corrections():
            with self.subTest(cas=correction.cas_number):
                self.assertGreater(len(correction.comment), 400)

    def test_it_stays_small(self):
        # Stated so that a second entry has to be argued for.  Every entry here
        # is a claim no source list makes and no registry backs.
        self.assertLessEqual(len(structure_corrections()), 3)


class TheFileIsCheckedAgainstItself(unittest.TestCase):
    """The half that keeps the readable values honest."""

    def _load(self, payload):
        structure_corrections.cache_clear()
        with mock.patch(
            "brightway_flows.domain.structure_corrections.orjson.loads",
            return_value=payload,
        ):
            try:
                return structure_corrections()
            finally:
                structure_corrections.cache_clear()

    def _entry(self, **overrides):
        entry = {
            "cas_number": "1345-04-6",
            "label": "Antimony Trisulfide",
            "smiles": "S=[Sb]S[Sb]=S",
            "inchi": "InChI=1S/3S.2Sb",
            "inchikey": "IHBMMJGTJFPEQY-UHFFFAOYSA-N",
            "molecular_formula": "S3Sb2",
            "flow_type": "NeutralMolecule",
            "comment": "x" * 500,
        }
        entry.update(overrides)
        return {"corrections": [entry]}

    def test_a_correct_entry_loads(self):
        self.assertEqual(len(self._load(self._entry())), 1)

    def test_a_wrong_inchikey_is_refused(self):
        with self.assertRaises(ValueError) as caught:
            self._load(self._entry(inchikey="AAAAAAAAAAAAAA-UHFFFAOYSA-N"))
        self.assertIn("InChIKey", str(caught.exception))

    def test_a_wrong_formula_is_refused(self):
        with self.assertRaises(ValueError) as caught:
            self._load(self._entry(molecular_formula="SSb"))
        self.assertIn("molecular formula", str(caught.exception))

    def test_a_wrong_inchi_is_refused(self):
        with self.assertRaises(ValueError):
            self._load(self._entry(inchi="InChI=1S/S.Sb"))

    def test_an_unreadable_smiles_is_refused(self):
        with self.assertRaises(ValueError):
            self._load(self._entry(smiles="not a structure"))

    def test_a_class_the_project_does_not_publish_is_refused(self):
        with self.assertRaises(ValueError) as caught:
            self._load(self._entry(flow_type="Sulfide"))
        self.assertIn("Sulfide", str(caught.exception))

    def test_one_number_corrected_twice_is_refused(self):
        payload = self._entry()
        payload["corrections"].append(dict(payload["corrections"][0]))
        with self.assertRaises(ValueError) as caught:
            self._load(payload)
        self.assertIn("twice", str(caught.exception))


class LookingUpACorrection(unittest.TestCase):
    def test_a_number_that_is_corrected(self):
        self.assertIsNotNone(correction_for(["1345-04-6"]))

    def test_a_number_that_is_not(self):
        self.assertIsNone(correction_for(["7732-18-5"]))

    def test_no_numbers_at_all(self):
        self.assertIsNone(correction_for([]))
        self.assertIsNone(correction_for(None))

    def test_a_bare_string_is_accepted(self):
        self.assertIsNotNone(correction_for("1345-04-6"))

    def test_two_numbers_corrected_differently_answer_nothing(self):
        """Two substances wearing one flow, which picking one would hide."""
        other = StructureCorrection(
            cas_number="1-2-3", label="", smiles="C", inchi="", inchikey="",
            molecular_formula="CH4", molecular_mass="", monoisotopic_mass="",
            flow_type=IRIS[Term.NEUTRAL_MOLECULE], comment="",
        )
        with mock.patch(
            "brightway_flows.domain.structure_corrections._by_cas",
            return_value={
                "1345-04-6": correction_for("1345-04-6"), "1-2-3": other
            },
        ):
            self.assertIsNone(correction_for(["1345-04-6", "1-2-3"]))


if __name__ == "__main__":
    unittest.main()
