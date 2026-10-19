"""Every ion is spelled one way and answers to the others.

`domain.ion_names` is the standard: `Lead(2+)` with `Lead(II)` and `Lead II`;
`Chloride(1-)` with `Chloride`, `Chloride(-I)` and `Chloride -I`; `Copper, ion`
with `Copper, Ion` and `Copper Ion`; the element in IUPAC's spelling, every form
repeated in the American one.  `pipeline.ion_names` applies it to the built
substances.

The halves that matter as much as the renames are the ones it leaves alone: a
substance that is not an ion, a polyatomic ion whose name states a charge (a
numeral would be an oxidation number no one atom has), and an ion whose name
states no charge, however sure PubChem is of one -- whether a charge is known is
#143's question, not a spelling.
"""

from __future__ import annotations

import unittest

from brightway_flows.domain.flow_object import FlowObject
from brightway_flows.domain.ion_names import (
    ION_NAMING_STANDARD,
    roman_numeral,
    standard_ion_label,
    standard_ion_synonyms,
)
from brightway_flows.domain.vocabulary import (
    CHEMROF_ELEMENTAL_CHARGE,
    IRIS,
    PROV_WAS_GENERATED_BY_CURIE,
    Term,
)
from brightway_flows.flow_layers.synonyms import carry_member_names
from brightway_flows.pipeline.ion_names import standardise_ion_names

CATION = IRIS[Term.ATOM_CATION]
ANION = IRIS[Term.ATOM_ANION]
GENERIC = IRIS[Term.MONOATOMIC_ION]
MOLECULAR_CATION = IRIS[Term.MOLECULAR_CATION]
MOLECULAR_ANION = IRIS[Term.MOLECULAR_ANION]
NEUTRAL = IRIS[Term.NEUTRAL_MOLECULE]


def _object(label, types, *, charge=None, alt=(), object_id="fo-1"):
    properties = {}
    if charge is not None:
        properties[CHEMROF_ELEMENTAL_CHARGE] = {"@value": [charge]}
    return FlowObject(
        flow_object_id=object_id,
        prefLabel=[{"@value": label, "@language": "en"}],
        altLabel=[{"@value": value, "@language": "en"} for value in alt],
        properties=properties,
        references=[],
        created_from={},
        types=[types],
    )


def _label(obj):
    return obj.prefLabel[0]["@value"]


def _synonyms(obj):
    return [row["@value"] if isinstance(row, dict) else row for row in obj.altLabel]


class StandardTestCase(unittest.TestCase):
    def test_a_cation_is_its_charge_number_and_answers_to_its_numeral(self):
        self.assertEqual(standard_ion_label("Lead", 2), "Lead(2+)")
        self.assertEqual(standard_ion_synonyms("Lead", 2), ["Lead(II)", "Lead II"])

    def test_an_anion_is_its_charge_number_and_answers_to_its_bare_name(self):
        self.assertEqual(standard_ion_label("Chloride", -1), "Chloride(1-)")
        self.assertEqual(standard_ion_label("Chlorine", -1), "Chloride(1-)")
        self.assertEqual(
            standard_ion_synonyms("Sulfide", -2),
            ["Sulfide", "Sulfide(-II)", "Sulfide -II"],
        )

    def test_an_unstated_charge_is_x_comma_ion(self):
        self.assertEqual(standard_ion_label("copper", None), "Copper, ion")
        self.assertEqual(
            standard_ion_synonyms("Copper", None), ["Copper, Ion", "Copper Ion"]
        )

    def test_the_element_is_spelled_as_iupac_spells_it_and_also_as_america_does(self):
        self.assertEqual(standard_ion_label("Cesium", 1), "Caesium(1+)")
        self.assertEqual(
            standard_ion_synonyms("Cesium", 1),
            ["Cesium(1+)", "Caesium(I)", "Caesium I", "Cesium(I)", "Cesium I"],
        )
        self.assertEqual(
            standard_ion_synonyms("Aluminium", None),
            ["Aluminum, ion", "Aluminium, Ion", "Aluminium Ion",
             "Aluminum, Ion", "Aluminum Ion"],
        )

    def test_an_element_spelled_once_has_no_second_spelling(self):
        """Sulfur is IUPAC's and America's spelling alike."""
        self.assertNotIn("Sulphide", " ".join(standard_ion_synonyms("Sulfide", -2)))

    def test_roman_numerals(self):
        self.assertEqual(
            [roman_numeral(n) for n in range(1, 9)],
            ["I", "II", "III", "IV", "V", "VI", "VII", "VIII"],
        )


class PassTestCase(unittest.TestCase):
    def test_a_cation_is_respelled_and_the_old_spelling_stays_a_synonym(self):
        obj = _object("Cesium(1+)", CATION, charge=1, alt=["cesium cation"])
        stats = standardise_ion_names([obj])
        self.assertEqual(_label(obj), "Caesium(1+)")
        self.assertEqual(
            _synonyms(obj),
            ["Cesium(1+)", "Caesium(I)", "Caesium I", "Cesium(I)", "Cesium I",
             "cesium cation"],
        )
        self.assertEqual(stats["renamed"], 1)

    def test_an_anion_takes_its_charge_from_the_object(self):
        """`Chloride` states no numeral; being chloride is the statement."""
        obj = _object("Chloride", ANION, charge=-1)
        standardise_ion_names([obj])
        self.assertEqual(_label(obj), "Chloride(1-)")
        self.assertEqual(_synonyms(obj)[:3], ["Chloride", "Chloride(-I)", "Chloride -I"])

    def test_a_generic_ion_keeps_its_unstated_charge(self):
        """`Titanium, ion` stays generic though PubChem says Ti+4 (#143)."""
        obj = _object("Titanium, ion", CATION, charge=4)
        standardise_ion_names([obj])
        self.assertEqual(_label(obj), "Titanium, ion")
        self.assertEqual(_synonyms(obj), ["Titanium, Ion", "Titanium Ion"])

    def test_a_title_cased_generic_is_respelled(self):
        obj = _object("Chromium, Ion", GENERIC)
        standardise_ion_names([obj])
        self.assertEqual(_label(obj), "Chromium, ion")
        self.assertEqual(_synonyms(obj), ["Chromium, Ion", "Chromium Ion"])

    def test_a_polyatomic_generic_is_respelled_too(self):
        obj = _object("Thiocyanate, Ion", MOLECULAR_ANION)
        standardise_ion_names([obj])
        self.assertEqual(_label(obj), "Thiocyanate, ion")

    def test_a_polyatomic_ion_with_a_stated_charge_is_left_alone(self):
        """`Methylmercury(1+)` is not mercury(I): no numeral is added."""
        obj = _object("Methylmercury(1+)", MOLECULAR_CATION, charge=1)
        stats = standardise_ion_names([obj])
        self.assertEqual(_label(obj), "Methylmercury(1+)")
        self.assertEqual(_synonyms(obj), [])
        self.assertEqual(stats["ions"], 0)

    def test_a_substance_that_is_not_an_ion_is_left_alone(self):
        obj = _object("Lead(2+) nitrate", NEUTRAL)
        standardise_ion_names([obj])
        self.assertEqual(_label(obj), "Lead(2+) nitrate")
        self.assertEqual(_synonyms(obj), [])

    def test_the_label_in_another_case_is_not_kept_as_a_synonym(self):
        obj = _object("Caesium(1+)", CATION, charge=1, alt=["caesium(1+)"])
        standardise_ion_names([obj])
        self.assertNotIn("caesium(1+)", _synonyms(obj))

    def test_running_twice_changes_nothing(self):
        obj = _object("Lead II", CATION, charge=2)
        standardise_ion_names([obj])
        first = (_label(obj), _synonyms(obj))
        stats = standardise_ion_names([obj])
        self.assertEqual((_label(obj), _synonyms(obj)), first)
        self.assertEqual(stats["renamed"], 0)
        self.assertEqual(stats["synonyms_added"], 0)

    def test_every_written_label_says_the_standard_wrote_it(self):
        obj = _object("Lead II", CATION, charge=2)
        standardise_ion_names([obj])
        for row in [*obj.prefLabel, *obj.altLabel]:
            self.assertEqual(
                row["provenance"][PROV_WAS_GENERATED_BY_CURIE], ION_NAMING_STANDARD
            )


class SynonymsSurviveTestCase(unittest.TestCase):
    """`carry_member_names` withdraws a synonym that answers for two
    substances.  One the standard promises stays where the standard put it."""

    def test_a_promised_synonym_another_substance_claims_is_kept(self):
        lead = _object("Lead(2+)", CATION, charge=2, object_id="fo-lead")
        other = _object("Lead, ore", NEUTRAL, alt=["Lead II"], object_id="fo-ore")
        standardise_ion_names([lead, other])
        carry_member_names([lead, other], [])
        self.assertIn("Lead II", _synonyms(lead))
        self.assertNotIn("Lead II", _synonyms(other))


if __name__ == "__main__":
    unittest.main()
