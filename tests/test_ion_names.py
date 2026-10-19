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

    def test_an_ion_of_an_element_is_read_whatever_it_is_typed(self):
        """`Chromium IV` is typed a mixture on the build of `43403ac` (#403),
        and recorded as the ion of chromium: the name is still an ion's."""
        obj = _object("Chromium IV", IRIS[Term.IMPRECISE_CHEMICAL_MIXTURE], charge=4)
        obj.properties["relationships"] = {
            "parent_element_flow_object_id": "fo-chromium",
            "relationship_type": "ion_of",
        }
        standardise_ion_names([obj])
        self.assertEqual(_label(obj), "Chromium(4+)")
        self.assertEqual(_synonyms(obj), ["Chromium(IV)", "Chromium IV"])

    def test_a_name_ending_in_a_numeral_is_not_an_ion_for_that(self):
        obj = _object("Pyrethrin I", NEUTRAL)
        standardise_ion_names([obj])
        self.assertEqual(_label(obj), "Pyrethrin I")

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


class FlowsCarryTheSynonymsTestCase(unittest.TestCase):
    """The published list reads a flow's synonyms off the flow."""

    def test_every_flow_of_an_ion_carries_the_standards_synonyms_first(self):
        from brightway_flows.domain.flow import Flow
        from brightway_flows.pipeline.ion_names import carry_ion_synonyms_onto_flows
        from brightway_flows.pipeline.layer_writes import LayerWriteLog

        lead = _object("Lead(2+)", CATION, charge=2, object_id="fo-lead")
        standardise_ion_names([lead])
        flow = Flow(uuid="ef-1", flow_object_id="fo-lead",
                    prefLabel=[{"@value": "Lead(2+)", "@language": "en"}],
                    altLabel=[{"@value": "plumbous ion", "@language": "en"}])
        writes = LayerWriteLog()
        stats = carry_ion_synonyms_onto_flows([flow], [lead], writes=writes)
        self.assertEqual(
            [row["@value"] for row in flow.altLabel],
            ["Lead(II)", "Lead II", "plumbous ion"],
        )
        self.assertEqual(stats["flows_given_synonyms"], 1)
        self.assertEqual(len(writes.writes), 1)

        again = carry_ion_synonyms_onto_flows([flow], [lead], writes=writes)
        self.assertEqual(again["flows_given_synonyms"], 0)


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



class MatchingReadsTheStandardTestCase(unittest.TestCase):
    """A synonym the standard wrote is the substance's own name respelled, and
    the merge reads it as a preferred name.  AGRIBALYSE's `Bromide` to
    industrial soil carries 59-99-4, which reaches nothing, so it is matched
    on its name -- which was bromide's label until the standard made it
    `Bromide(1-)`.  Read as an ordinary synonym of a numbered substance it was
    refused, and the row minted a second `Bromide` (#401)."""

    def test_the_old_label_still_finds_the_ion_as_its_name(self):
        from brightway_flows.merge.matching import _build_indexes

        bromide = _object("Bromide", ANION, charge=-1, object_id="fo-bromide")
        standardise_ion_names([bromide])
        _, _, labels, preferred = _build_indexes([bromide])
        self.assertEqual(preferred["bromide"], {"fo-bromide"})
        self.assertEqual(preferred["bromide(1-)"], {"fo-bromide"})

    def test_a_synonym_that_was_never_the_label_is_only_a_synonym(self):
        """`Chromium VI` was never chromium(6+)'s name.  Read as one, it let
        ecoinvent's own `Chromium IV` -> `Chromium VI` crosswalk move 3.8's
        row numbered for chromium(4+) onto chromium(6+)."""
        from brightway_flows.merge.matching import _build_indexes

        chromium = _object("Chromium(6+)", CATION, charge=6, alt=["chromate ion"],
                           object_id="fo-cr6")
        standardise_ion_names([chromium])
        _, _, labels, preferred = _build_indexes([chromium])
        self.assertIn("chromium vi", labels)
        self.assertNotIn("chromium vi", preferred)
        self.assertNotIn("chromate ion", preferred)

    def test_the_replaced_label_stays_marked_when_read_back(self):
        """The merge reads the transform's substances back and runs the pass
        again over what it mints; the mark must survive a second pass."""
        caesium = _object("Cesium(1+)", CATION, charge=1, object_id="fo-cs")
        standardise_ion_names([caesium])
        standardise_ion_names([caesium])
        from brightway_flows.domain.ion_names import is_replaced_label_row

        replaced = [row["@value"] for row in caesium.altLabel if is_replaced_label_row(row)]
        self.assertEqual(replaced, ["Cesium(1+)"])


if __name__ == "__main__":
    unittest.main()
