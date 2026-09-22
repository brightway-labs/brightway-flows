"""A delayed-emission correction flow is not the substance it corrects for.

EF 3.1 ships six "Correction flow for delayed emission of X (within first 100
years)" rows.  Each is an accounting device with its own characterisation
factor, measured in kg*a, and each arrives carrying the base substance's CAS
number.  The CAS is what merged them: all fourteen `nitrous oxide` flows and
the correction flow became one object, and because the object takes the longest
name in the group, the list published no nitrous oxide at all -- only
`Correction Flow For Delayed Emission Of Nitrous Oxide (within First 100
Years)` (#268).  Sulphur hexafluoride's correction flow sits on the SF6 object
the same way; the four carbon corrections sit on the qualified carbon dioxide
and methane objects, where the qualified-name rule hid the collapse behind a
label that still read `Carbon Dioxide (fossil)`.

Two halves, tested separately because they fail separately:

**Detection.** The name says "delayed emission" and nothing else in either
source list does.  What has to hold is precedence: four of the six names also
contain a word a later check reads -- "biogenic", "fossil" -- and reading that
word first is what put the correction flow on the qualified substance.

**Separation.** The split has to survive the flow-object stage: one object per
correction, the base substance keeping its own name, and the fossil and
biogenic corrections of one substance staying apart from each other despite
sharing that substance's CAS.

**Typing.** Splitting the object leaves it holding the substance's chemistry:
a molecular formula, a SMILES, the InChI pair, two masses, an IUPAC name, a
charge and `NeutralMolecule`, all asserted of a quantity measured in kg*a
(#43).  What has to hold is that the correction is typed as nothing at all --
ChemROF has no class for an accounting flow and this project mints none -- and
that the withdrawal reaches both layers, because the published export projects
the flow rather than the object.
"""

from __future__ import annotations

import unittest
from typing import Any

from brightway_flows.domain.flow import Flow
from brightway_flows.domain.flow_object import FlowObject
from brightway_flows.domain.vocabulary import (
    CHEMINF_CAS_REGISTRY_NUMBER,
    CHEMROF_ELEMENTAL_CHARGE,
    CHEMROF_INCHI2D_KEY_STRING,
    CHEMROF_INCHI2D_STRING,
    CHEMROF_IUPAC_NAME,
    CHEMROF_MOLECULAR_FORMULA,
    CHEMROF_MOLECULAR_MASS,
    CHEMROF_MONOISOTOPIC_MASS,
    CHEMROF_SMILES_STRING,
)
from brightway_flows.flow_layers import resolve_flow_layers
from brightway_flows.flow_layers.labels import _object_pref_label_value
from brightway_flows.pipeline.semantic_typing import (
    SINGLE_SUBSTANCE_PROPERTIES,
    assign_semantic_types,
    classify,
    withdraw_single_substance_properties,
)
from brightway_flows.qualifiers import (
    ORIGIN_QUALIFIERS,
    detect_origin_qualifier,
    is_delayed_emission_correction,
)
from brightway_flows.sources import base_source_list

#: `resolve_flow_layers` asks which list its flows came from rather than
#: reading it off `flow.source`, and these are the base list's rows (#13).
BASE = base_source_list()

#: Every correction flow EF 3.1 ships, with the CAS it arrives carrying and the
#: qualifier it must be given.  These are the shipped names, verbatim.
CORRECTION_FLOWS = (
    (
        "01d5477f-ec52-4019-ada1-0618e7d85daa",
        "Correction flow for delayed emission of nitrous oxide (within first 100 years)",
        "10024-97-2",
        "delayed_emission_correction",
    ),
    (
        "1d758d0b-1a77-46a1-bbe8-8175f98a6d66",
        "Correction flow for delayed emission of sulphur hexafluoride "
        "(within first 100 years)",
        "2551-62-4",
        "delayed_emission_correction",
    ),
    (
        "36e96d4a-c158-4081-b101-f229d90fb3c9",
        "Correction flow for delayed emission of fossil methane (within first 100 years)",
        "74-82-8",
        "fossil_delayed_emission_correction",
    ),
    (
        "6055785e-2434-4fea-8c9e-dad3b2132c79",
        "Correction flow for delayed emission of biogenic methane (within first 100 years)",
        "74-82-8",
        "biogenic_delayed_emission_correction",
    ),
    (
        "9752faac-6a76-4ee8-a220-b795641624ab",
        "Correction flow for delayed emission of fossil carbon dioxide "
        "(within first 100 years)",
        "124-38-9",
        "fossil_delayed_emission_correction",
    ),
    (
        "eb72f44f-1868-405c-a967-526a2d45445c",
        "Correction flow for delayed emission of biogenic carbon dioxide "
        "(within first 100 years)",
        "124-38-9",
        "biogenic_delayed_emission_correction",
    ),
)

#: The substances the corrections are about, as their own flows name them.
#: None of these is a correction of anything.
BASE_SUBSTANCE_NAMES = (
    "nitrous oxide",
    "Nitrous Oxide",
    "sulphur hexafluoride",
    "Sulfur hexafluoride",
    "Carbon dioxide, fossil",
    "Carbon dioxide, biogenic",
    "Methane, fossil",
    "Methane, biogenic",
    "Carbon dioxide, non-fossil, resource correction",
)

CORRECTION_QUALIFIERS = (
    "delayed_emission_correction",
    "fossil_delayed_emission_correction",
    "biogenic_delayed_emission_correction",
)


def _flow(uuid: str, name: str, cas: str, *, unit: str = "kg") -> dict[str, Any]:
    return {
        "uuid": uuid,
        "prefLabel": [{"@value": name, "@language": "en"}],
        "cas_numbers": [cas],
        "unit": unit,
        "source": "EF 3.1",
        "context": {"dimension": "Environmental", "media": "Air", "strata": "Unknown"},
    }


def _correction_flow(index: int) -> dict[str, Any]:
    uuid, name, cas, _qualifier = CORRECTION_FLOWS[index]
    return _flow(uuid, name, cas, unit="kg*a")


def _layer(rows: list[dict[str, Any]]):
    return resolve_flow_layers([Flow.from_dict(row) for row in rows], source_list=BASE)


def _by_qualifier(flow_objects) -> dict[Any, Any]:
    return {fo.origin_qualifier: fo for fo in flow_objects}


class DelayedEmissionDetectionTestCase(unittest.TestCase):
    """`detect_origin_qualifier` on the names that decide the split."""

    def test_each_correction_flow_gets_its_qualifier(self):
        for _uuid, name, _cas, qualifier in CORRECTION_FLOWS:
            with self.subTest(name=name):
                self.assertEqual(detect_origin_qualifier(name), qualifier)

    def test_the_carbon_corrections_are_not_read_as_the_carbon_qualifier(self):
        """The bug in one line: "of fossil methane" is also a `fossil` match.

        Whichever check runs first decides, and `fossil` winning is what put
        the correction flow on the `Methane (fossil)` object.
        """
        for _uuid, name, _cas, qualifier in CORRECTION_FLOWS:
            if qualifier == "delayed_emission_correction":
                continue
            with self.subTest(name=name):
                self.assertNotIn(detect_origin_qualifier(name), ("biogenic", "fossil"))

    def test_a_substance_is_not_a_correction(self):
        for name in BASE_SUBSTANCE_NAMES:
            with self.subTest(name=name):
                self.assertNotIn(
                    detect_origin_qualifier(name) or "", CORRECTION_QUALIFIERS
                )

    def test_the_qualifiers_are_registered(self):
        for qualifier in CORRECTION_QUALIFIERS:
            with self.subTest(qualifier=qualifier):
                self.assertIn(qualifier, ORIGIN_QUALIFIERS)

    def test_the_carbon_variants_are_checked_before_the_bare_one(self):
        """`delayed emission` alone matches all six, so it must not run first."""
        order = list(ORIGIN_QUALIFIERS)
        self.assertLess(
            order.index("biogenic_delayed_emission_correction"),
            order.index("delayed_emission_correction"),
        )
        self.assertLess(
            order.index("fossil_delayed_emission_correction"),
            order.index("delayed_emission_correction"),
        )

    def test_the_carbon_origin_may_be_said_before_the_correction(self):
        """A name is free to put the origin word first, and one day one will.

        Falling through to the bare qualifier would then group the biogenic and
        the fossil correction of one substance by `(qualifier, CAS)` -- and
        they share their substance's CAS, so that is the collapse these three
        qualifiers exist to prevent.
        """
        for name, expected in (
            (
                "Biogenic carbon dioxide, correction flow for delayed emission",
                "biogenic_delayed_emission_correction",
            ),
            (
                "Fossil carbon dioxide, correction flow for delayed emission",
                "fossil_delayed_emission_correction",
            ),
            (
                "Non-fossil methane, correction flow for delayed emission",
                "biogenic_delayed_emission_correction",
            ),
        ):
            with self.subTest(name=name):
                self.assertEqual(detect_origin_qualifier(name), expected)

    def test_the_family_is_named_and_complete(self):
        for qualifier in CORRECTION_QUALIFIERS:
            with self.subTest(qualifier=qualifier):
                self.assertTrue(is_delayed_emission_correction(qualifier))
        for qualifier in ("biogenic", "fossil", "green_water", None, ""):
            with self.subTest(qualifier=qualifier):
                self.assertFalse(is_delayed_emission_correction(qualifier))

    def test_the_corrections_are_checked_before_the_carbon_qualifiers(self):
        order = list(ORIGIN_QUALIFIERS)
        self.assertLess(
            order.index("delayed_emission_correction"), order.index("biogenic")
        )
        self.assertLess(
            order.index("delayed_emission_correction"), order.index("fossil")
        )


class DelayedEmissionSeparationTestCase(unittest.TestCase):
    """What the flow-object stage does with a correction flow."""

    def test_nitrous_oxide_is_published_under_its_own_name(self):
        """#268: the list had no nitrous oxide, only the correction flow."""
        flow_objects, _elementary, _stats = _layer([
            _correction_flow(0),
            _flow("08a91e70-3ddc-11dd-94c3-0050c2490048", "nitrous oxide", "10024-97-2"),
            _flow("0bea8c86-83f3-4ddd-b817-84cd84535d2b", "nitrous oxide", "10024-97-2"),
        ])

        self.assertEqual(len(flow_objects), 2)
        by_qualifier = _by_qualifier(flow_objects)
        substance = by_qualifier[None]
        correction = by_qualifier["delayed_emission_correction"]
        self.assertEqual(_object_pref_label_value(substance), "nitrous oxide")
        self.assertIn("Correction flow", _object_pref_label_value(correction))

    def test_the_correction_points_back_at_the_substance(self):
        flow_objects, _elementary, _stats = _layer([
            _correction_flow(0),
            _flow("08a91e70-3ddc-11dd-94c3-0050c2490048", "nitrous oxide", "10024-97-2"),
        ])

        by_qualifier = _by_qualifier(flow_objects)
        self.assertEqual(
            by_qualifier["delayed_emission_correction"].parent_flow_object_id,
            by_qualifier[None].flow_object_id,
        )

    def test_the_correction_flow_stays_off_the_substance_object(self):
        """Each layer keeps them apart, not just the object layer."""
        _flow_objects, elementary, _stats = _layer([
            _correction_flow(0),
            _flow("08a91e70-3ddc-11dd-94c3-0050c2490048", "nitrous oxide", "10024-97-2"),
        ])

        by_uuid = {ef.elementary_flow_id: ef.flow_object_id for ef in elementary}
        self.assertNotEqual(
            by_uuid["01d5477f-ec52-4019-ada1-0618e7d85daa"],
            by_uuid["08a91e70-3ddc-11dd-94c3-0050c2490048"],
        )

    def test_the_two_carbon_dioxide_corrections_do_not_merge_with_each_other(self):
        """Both carry 124-38-9, so one qualifier for both would collapse them."""
        flow_objects, _elementary, _stats = _layer([
            _correction_flow(4),
            _correction_flow(5),
            _flow("u-co2-fossil", "Carbon dioxide, fossil", "124-38-9"),
            _flow("u-co2-biogenic", "Carbon dioxide, biogenic", "124-38-9"),
            _flow("u-co2", "Carbon dioxide", "124-38-9"),
        ])

        self.assertEqual(len(flow_objects), 5)
        self.assertEqual(
            sorted(
                str(fo.origin_qualifier) for fo in flow_objects if fo.origin_qualifier
            ),
            [
                "biogenic",
                "biogenic_delayed_emission_correction",
                "fossil",
                "fossil_delayed_emission_correction",
            ],
        )

    def test_the_qualified_substance_keeps_its_own_name(self):
        """`Carbon Dioxide (fossil)` was the label a merged object published."""
        flow_objects, _elementary, _stats = _layer([
            _correction_flow(4),
            _flow("u-co2-fossil", "Carbon dioxide, fossil", "124-38-9"),
        ])

        by_qualifier = _by_qualifier(flow_objects)
        self.assertEqual(
            _object_pref_label_value(by_qualifier["fossil"]),
            "Carbon dioxide, fossil",
        )
        self.assertIn(
            "Correction flow",
            _object_pref_label_value(by_qualifier["fossil_delayed_emission_correction"]),
        )

    def test_a_renamed_correction_is_recovered_from_the_name_it_arrived_under(self):
        """A rename to the coarse qualifier must not undo the split.

        Every correction flow's name contains the word a coarser check reads,
        so `Methane (fossil)` detects `fossil` -- and taking that answer sends
        the correction back onto the substance object, silently.  These renames
        happen: `consensus_match` relabelled the sulphur hexafluoride
        correction to `Sulfur hexafluoride` in the shipped build.
        """
        uuid, name, cas, qualifier = CORRECTION_FLOWS[2]
        renamed = _flow(uuid, "Methane (fossil)", cas, unit="kg*a")
        renamed["source_refs"] = [
            {
                "list_name": "EF",
                "list_version": "3.1",
                "source_flow_uuid": uuid,
                "source_flow_name": name,
            }
        ]

        flow_objects, _elementary, _stats = _layer([
            renamed,
            _flow("u-ch4-fossil", "Methane, fossil", "74-82-8"),
        ])

        self.assertEqual(len(flow_objects), 2)
        by_qualifier = _by_qualifier(flow_objects)
        self.assertIn(qualifier, by_qualifier)
        self.assertEqual(
            _object_pref_label_value(by_qualifier["fossil"]), "Methane, fossil"
        )

    def test_every_correction_flow_gets_its_own_object(self):
        rows = [_correction_flow(i) for i in range(len(CORRECTION_FLOWS))]

        flow_objects, elementary, _stats = _layer(rows)

        self.assertEqual(len(flow_objects), len(CORRECTION_FLOWS))
        self.assertEqual(
            len({ef.flow_object_id for ef in elementary}), len(CORRECTION_FLOWS)
        )


#: What the correction object inherited from the substance through the CAS it
#: shares with it.  These are nitrous oxide's, as the shipped build carries
#: them on `fo-0984ea13649c1034`.
SUBSTANCE_CHEMISTRY = {
    CHEMROF_MOLECULAR_FORMULA: {"@value": ["N2O"]},
    CHEMROF_SMILES_STRING: {"@value": ["[N-]=[N+]=O"]},
    CHEMROF_INCHI2D_STRING: {"@value": ["InChI=1S/N2O/c1-2-3"]},
    CHEMROF_INCHI2D_KEY_STRING: {"@value": ["GQPLMRYTRLFLPF-UHFFFAOYSA-N"]},
    CHEMROF_MOLECULAR_MASS: {"@value": [44.013]},
    CHEMROF_MONOISOTOPIC_MASS: {"@value": [44.0011]},
    CHEMROF_IUPAC_NAME: {"@value": ["nitrous oxide"]},
    CHEMROF_ELEMENTAL_CHARGE: {"@value": [0]},
}


def _correction_object(
    qualifier: str = "delayed_emission_correction",
    *,
    cas: str = "10024-97-2",
) -> FlowObject:
    return FlowObject(
        flow_object_id="fo-" + qualifier[:20],
        prefLabel=[{
            "@value": "Correction flow for delayed emission of nitrous oxide "
                      "(within first 100 years)",
            "@language": "en",
        }],
        altLabel=[],
        properties=dict(SUBSTANCE_CHEMISTRY),
        references=[],
        created_from={},
        classifications={CHEMINF_CAS_REGISTRY_NUMBER: {"@value": [cas]}},
        origin_qualifier=qualifier,
        parent_flow_object_id="fo-8c6906c0ddba5602",
    )


class DelayedEmissionTypingTestCase(unittest.TestCase):
    """What the correction object may say about itself (#43)."""

    def test_a_correction_is_not_a_molecule(self):
        """It has a SMILES, so every structural rule below would place it."""
        for qualifier in CORRECTION_QUALIFIERS:
            with self.subTest(qualifier=qualifier):
                result = classify(_correction_object(qualifier))
                self.assertEqual(result.types, ())
                self.assertEqual(
                    result.reason, "delayed_emission_correction_not_a_substance"
                )

    def test_the_substance_itself_is_still_a_molecule(self):
        """The control: same chemistry, same CAS, no qualifier."""
        substance = _correction_object()
        substance.origin_qualifier = None
        result = classify(substance)
        self.assertEqual(result.rule, "neutral_molecule")

    def test_typing_withdraws_the_substance_chemistry(self):
        obj = _correction_object()

        counts = assign_semantic_types([obj], [])

        for key in SINGLE_SUBSTANCE_PROPERTIES:
            with self.subTest(property=key):
                self.assertNotIn(key, obj.properties)
        self.assertEqual(
            counts["single_substance_properties_withdrawn"], len(SUBSTANCE_CHEMISTRY)
        )
        self.assertEqual(counts["untyped_delayed_emission_correction_not_a_substance"], 1)

    def test_the_object_publishes_no_type(self):
        obj = _correction_object()

        assign_semantic_types([obj], [])

        self.assertFalse(obj.types)

    def test_the_reason_is_recorded_on_the_object(self):
        """Untyped by decision, so the decision is readable afterwards."""
        obj = _correction_object()

        assign_semantic_types([obj], [])

        decision = obj.created_from["semantic_typing"]
        self.assertEqual(
            decision["reason"], "delayed_emission_correction_not_a_substance"
        )
        self.assertEqual(decision["types"], [])

    def test_what_the_correction_is_about_survives(self):
        """The CAS and the parent say which substance, which is true."""
        obj = _correction_object()

        assign_semantic_types([obj], [])

        self.assertEqual(
            obj.classifications[CHEMINF_CAS_REGISTRY_NUMBER]["@value"], ["10024-97-2"]
        )
        self.assertEqual(obj.parent_flow_object_id, "fo-8c6906c0ddba5602")

    def test_the_withdrawal_reaches_the_flow_layer_too(self):
        """The published export projects the flow, not the object."""
        correction = Flow.from_dict(_correction_flow(0))
        correction.properties = dict(SUBSTANCE_CHEMISTRY)
        correction.origin_qualifier = "delayed_emission_correction"
        substance = Flow.from_dict(
            _flow("08a91e70-3ddc-11dd-94c3-0050c2490048", "nitrous oxide", "10024-97-2")
        )
        substance.properties = dict(SUBSTANCE_CHEMISTRY)

        counts = withdraw_single_substance_properties([correction, substance])

        self.assertEqual(counts["records"], 1)
        for key in SINGLE_SUBSTANCE_PROPERTIES:
            with self.subTest(property=key):
                self.assertNotIn(key, correction.properties)
        self.assertIn(CHEMROF_MOLECULAR_FORMULA, substance.properties)
