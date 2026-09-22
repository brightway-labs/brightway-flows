"""The alpha-emitter aggregates are not the elements whose CAS they carry.

`Plutonium-alpha`, `Uranium alpha` and `Curium Alpha` are the alpha-emitting
isotopes of one element reported together as activity -- which is why their unit
is kBq, and why Pu-241, a beta emitter, is carried separately alongside them.
Each arrives carrying the *element's* CAS number, and the CAS is what merged
them: one flow object stood for two substances, published the element's
structural properties over a set of isotopes, and gave both source flows one
name (#238).

Two halves, tested separately because they fail separately:

**Detection.** "alpha" is the commonest stereo and positional descriptor in the
list, and in every one of those uses it is a prefix or an infix naming a
position within one molecule. Only a *trailing* "alpha" is radiological. The
false cases below are real names from the source lists, not invented ones: they
are what a `\\balpha\\b` pattern would have swept up.

**Separation.** The split has to survive the whole flow-object stage, not just
the regex -- the object identity, the parent link, the class, the properties on
both layers, and the element enrichment that must no longer reach the aggregate.
"""

from __future__ import annotations

import unittest
from typing import Any

from brightway_flows.domain.flow import Flow
from brightway_flows.domain.flow_object import FlowObject
from brightway_flows.domain.vocabulary import (
    CHEMINF_CAS_REGISTRY_NUMBER,
    CHEMROF_CHEMICAL_ELEMENT,
    CHEMROF_ELEMENTAL_CHARGE,
    CHEMROF_INCHI2D_KEY_STRING,
    CHEMROF_INCHI2D_STRING,
    CHEMROF_IUPAC_NAME,
    CHEMROF_MOLECULAR_FORMULA,
    CHEMROF_MOLECULAR_MASS,
    CHEMROF_MONOISOTOPIC_MASS,
    CHEMROF_SMILES_STRING,
    IRIS,
    Term,
)
from brightway_flows.flow_layers import resolve_flow_layers
from brightway_flows.pipeline.semantic_typing import (
    SINGLE_SUBSTANCE_PROPERTIES,
    assign_semantic_types,
    classify,
    withdraw_single_substance_properties,
)
from brightway_flows.qualifiers import (
    ALPHA_EMITTERS,
    ORIGIN_QUALIFIERS,
    detect_origin_qualifier,
)
from brightway_flows.sources import base_source_list

BASE = base_source_list()

#: Every name in either source list that ends in "alpha", and the casings the
#: two lists disagree on. EF writes `Plutonium-alpha` and `Curium alpha`;
#: ecoinvent writes `Curium Alpha` and `Uranium Alpha`.
AGGREGATE_NAMES = (
    "Plutonium-alpha",
    "Uranium alpha",
    "Uranium Alpha",
    "Curium alpha",
    "Curium Alpha",
    "curium alpha",
    "CURIUM ALPHA",
    "Curium, alpha",
    "Curium Alpha ",
)

#: Names carrying "alpha" as a position within one molecule. All of these are in
#: the shipped list today, and none of them is a radiological aggregate.
POSITIONAL_ALPHA_NAMES = (
    "alpha-methylbenzyl alcohol",
    "alpha-methylstyrene",
    "alpha-cypermethrin",
    "alpha-methyltetrahydrofuran",
    "alpha-Chlorfenvinphos",
    "alpha-BHC",
    "(1s)-(-)-alpha-pinene",
    "16alpha-hydroxyprednisolone",
    "me-a-alpha-c",
    "17-acetoxy-6-chloro-1 alpha-chloromethyl-4,6-pregnadiene-3,20-dione",
    "6 alpha-fluoro-11 beta-hydroxy-16 alpha-methyl-21-valeryloxy-1,4-pregnadiene-3,20-dione",
    "17 beta-acetoxy-5 alpha-androstan-3-one",
    "(r)-alpha-amino-4-hydroxybenzeneacetic acid",
    "(s)-.alpha.-cyano-3-phenoxybenzyl (z)-(1r)-cis-3-(2-chloro-3,3,3-"
    "trifluoropropenyl)-2,2-dimethylcyclopropanecarboxylate",
    "5-hydroxy-2-(3-hydroxy-4-methoxyphenyl)-4-oxo-3,4-dihydro-2h-chromen-7-yl "
    "6-o-(6-deoxy-alpha-l-mannopyranosyl)-beta-d-glucopyranoside",
    "alpha, alpha’, alpha’’-1,2,3-propanetriyltris[w-hydroxypoly"
    "(oxy-methyl-1,2-ethanediyl)]",
)

#: Radiological, but not one element's alpha aggregate: this one already has its
#: own flow object because it shares a CAS with nothing.
OTHER_RADIOLOGICAL_NAMES = (
    "Radioactive species, alpha emitters",
    "Radioactive Species, Alpha Emitters",
)


def _prop(values: list[Any]) -> dict[str, Any]:
    return {"@value": values}


#: What the element's enrichment puts on a flow object, and what the aggregate
#: inherited from it through the shared CAS.
ELEMENT_STRUCTURE = {
    CHEMROF_MOLECULAR_FORMULA: _prop(["Cm"]),
    CHEMROF_SMILES_STRING: _prop(["[Cm]"]),
    CHEMROF_INCHI2D_STRING: _prop(["InChI=1S/Cm"]),
    CHEMROF_INCHI2D_KEY_STRING: _prop(["NIWWFAAXEMMFMS-UHFFFAOYSA-N"]),
    CHEMROF_MOLECULAR_MASS: _prop([247.0]),
    CHEMROF_MONOISOTOPIC_MASS: _prop([247.0703]),
    CHEMROF_IUPAC_NAME: _prop(["curium"]),
    # PubChem's entry for the neutral element. `_withdraw_element_charge`
    # already refuses it for `ChemicalElement`; a grouping class over
    # nuclides has no charge state either.
    CHEMROF_ELEMENTAL_CHARGE: _prop([0]),
}


def _flow(uuid: str, name: str, cas: str, *, unit: str = "kBq") -> dict[str, Any]:
    return {
        "uuid": uuid,
        "prefLabel": [{"@value": name, "@language": "en"}],
        "cas_numbers": [cas],
        "unit": unit,
        "source": "test",
        "properties": dict(ELEMENT_STRUCTURE),
    }


def _as_flows(rows: list[dict[str, Any]]) -> list[Flow]:
    return [Flow.from_dict(row) for row in rows]


def _make_object(
    *,
    label: str,
    qualifier: str | None,
    cas: str = "7440-51-9",
    properties: dict[str, Any] | None = None,
    types: list[str] | None = None,
) -> FlowObject:
    return FlowObject(
        flow_object_id="fo-" + label.lower().replace(" ", "-").replace(",", "")[:24],
        prefLabel=[{"@value": label, "@language": "en"}],
        altLabel=[],
        properties=dict(ELEMENT_STRUCTURE if properties is None else properties),
        references=[],
        created_from={},
        classifications={CHEMINF_CAS_REGISTRY_NUMBER: {"@value": [cas]}},
        types=types,
        origin_qualifier=qualifier,
    )


class AlphaEmitterDetectionTestCase(unittest.TestCase):
    """`detect_origin_qualifier` on the names that decide the split."""

    def test_the_aggregate_names_are_alpha_emitters(self):
        for name in AGGREGATE_NAMES:
            with self.subTest(name=name):
                self.assertEqual(detect_origin_qualifier(name), ALPHA_EMITTERS)

    def test_a_positional_alpha_is_not_a_qualifier(self):
        """A `\\balpha\\b` pattern would have matched every one of these."""
        for name in POSITIONAL_ALPHA_NAMES:
            with self.subTest(name=name):
                self.assertIsNone(detect_origin_qualifier(name))

    def test_the_unqualified_substances_are_not_alpha_emitters(self):
        for name in ("Plutonium", "plutonium", "Curium", "Uranium", "Uranium-238"):
            with self.subTest(name=name):
                self.assertIsNone(detect_origin_qualifier(name))

    def test_the_individual_isotopes_are_not_alpha_emitters(self):
        """These are single nuclides and already have their own flow objects."""
        for name in ("Plutonium-238", "Plutonium-241", "Curium-242", "Uranium-235"):
            with self.subTest(name=name):
                self.assertIsNone(detect_origin_qualifier(name))

    def test_the_standalone_word_is_not_a_qualifier(self):
        """"alpha" alone qualifies nothing -- there is no substance in front."""
        for name in ("alpha", "Alpha", "  alpha  "):
            with self.subTest(name=name):
                self.assertIsNone(detect_origin_qualifier(name))

    def test_the_unelemental_alpha_aggregate_is_untouched(self):
        """`Radioactive species, alpha emitters` shares a CAS with nothing.

        It is already its own flow object, and "alpha" is not trailing, so no
        qualifier applies and none is needed.
        """
        for name in OTHER_RADIOLOGICAL_NAMES:
            with self.subTest(name=name):
                self.assertIsNone(detect_origin_qualifier(name))

    def test_the_qualifier_is_registered(self):
        self.assertIn(ALPHA_EMITTERS, ORIGIN_QUALIFIERS)

    def test_alpha_emitters_is_last_in_precedence(self):
        """The narrowest check, so it may not shadow one of the others."""
        self.assertEqual(ORIGIN_QUALIFIERS[-1], ALPHA_EMITTERS)


class AlphaEmitterTypingTestCase(unittest.TestCase):
    """The class an aggregate gets, and the properties it loses."""

    def test_an_aggregate_is_an_atom_grouping_class(self):
        obj = _make_object(label="Curium Alpha", qualifier=ALPHA_EMITTERS)
        result = classify(obj, label="Curium Alpha")
        self.assertEqual(list(result.types), [IRIS[Term.ATOM_GROUPING_CLASS]])
        self.assertEqual(result.rule, "alpha_emitter_aggregate")

    def test_the_aggregate_rule_outranks_the_element_structure_it_inherited(self):
        """Without it, `[Cm]` types the aggregate as the element itself."""
        unqualified = _make_object(label="Curium", qualifier=None)
        self.assertNotEqual(
            list(classify(unqualified, label="Curium").types),
            [IRIS[Term.ATOM_GROUPING_CLASS]],
        )

    def test_typing_withdraws_the_single_substance_properties(self):
        obj = _make_object(label="Curium Alpha", qualifier=ALPHA_EMITTERS)
        counts = assign_semantic_types([obj], [])
        for key in SINGLE_SUBSTANCE_PROPERTIES:
            with self.subTest(property=key):
                self.assertNotIn(key, obj.properties)
        self.assertEqual(
            counts["single_substance_properties_withdrawn"], len(ELEMENT_STRUCTURE)
        )

    def test_typing_leaves_the_elements_own_properties_alone(self):
        obj = _make_object(label="Curium", qualifier=None)
        assign_semantic_types([obj], [])
        self.assertIn(CHEMROF_MOLECULAR_FORMULA, obj.properties)
        self.assertIn(CHEMROF_SMILES_STRING, obj.properties)

    def test_withdrawal_reaches_the_flow_layer_too(self):
        """The export projects the flow, which carries its own copy (#238)."""
        aggregate = Flow.from_dict(_flow("u-agg", "Curium Alpha", "7440-51-9"))
        aggregate.origin_qualifier = ALPHA_EMITTERS
        element = Flow.from_dict(_flow("u-elem", "Curium", "7440-51-9"))

        counts = withdraw_single_substance_properties([aggregate, element])

        self.assertEqual(counts["records"], 1)
        for key in SINGLE_SUBSTANCE_PROPERTIES:
            with self.subTest(property=key):
                self.assertNotIn(key, aggregate.properties)
        self.assertIn(CHEMROF_MOLECULAR_FORMULA, element.properties)


class AlphaEmitterSeparationTestCase(unittest.TestCase):
    """The three groupings from #238, run through the flow-object stage.

    Names, CAS numbers and units are the ones the source lists actually carry:
    all three aggregates arrive with the element's CAS, which is what merged
    them, and the uranium rows include elemental uranium as a *resource* (kg)
    beside the kBq flows.

    Uranium yields **three** objects where the other two yield two, and that is
    the point of #17 rather than an inconsistency: `uranium-238` also carries
    `7440-61-1`, the element's number, so taking the aggregate off the object
    still left a second substance on it -- an ore in kg published as a single
    nuclide. Keying a nuclide by its nuclide separates that third thing, and
    only then is the remaining object elemental uranium and nothing else.
    """

    def _by_label(self, flow_objects) -> dict[str, Any]:
        return {fo.prefLabel[0]["@value"].lower(): fo for fo in flow_objects}

    def _plutonium(self) -> list[dict[str, Any]]:
        return [
            _flow("pu-element-ef", "plutonium", "7440-07-5"),
            _flow("pu-alpha-ef", "Plutonium-alpha", "7440-07-5"),
            _flow("pu-alpha-ei", "Plutonium-alpha", "7440-07-5"),
        ]

    def _curium(self) -> list[dict[str, Any]]:
        return [
            _flow("cm-element-ef", "curium", "7440-51-9"),
            _flow("cm-alpha-ef", "Curium alpha", "7440-51-9"),
            _flow("cm-alpha-ei", "Curium Alpha", "7440-51-9"),
        ]

    def _uranium(self) -> list[dict[str, Any]]:
        return [
            _flow("u-238-ef", "uranium-238", "7440-61-1"),
            _flow("u-alpha-ef", "Uranium alpha", "7440-61-1"),
            _flow("u-alpha-ei", "Uranium Alpha", "7440-61-1"),
            _flow("u-resource-ef", "Uranium", "7440-61-1", unit="kg"),
        ]

    def _layer(self, rows: list[dict[str, Any]]):
        return resolve_flow_layers(_as_flows(rows), source_list=BASE)

    def test_the_aggregate_is_held_apart_from_the_substance_whose_cas_it_carries(self):
        """One object per distinct substance in the group.

        Two for plutonium and curium -- the element and the aggregate. Three
        for uranium, because `uranium-238` is in that group carrying the
        element's CAS as well, and it is a third substance (#17).
        """
        for name, rows, expected in (
            ("plutonium", self._plutonium(), 2),
            ("curium", self._curium(), 2),
            ("uranium", self._uranium(), 3),
        ):
            with self.subTest(element=name):
                flow_objects, _elementary, _stats = self._layer(rows)
                self.assertEqual(len(flow_objects), expected)
                self.assertEqual(
                    sorted(
                        str(fo.origin_qualifier)
                        for fo in flow_objects
                        if fo.origin_qualifier
                    ),
                    [ALPHA_EMITTERS],
                )

    def test_the_nuclide_is_not_the_element_it_shares_a_registry_number_with(self):
        """#17: `uranium-238` and `Uranium` both carry `7440-61-1`.

        The CAS is the *element's* -- U-238's own is 24678-82-8 -- so it merged
        an ore measured in kg with a single nuclide, and there was no flow
        object for elemental uranium at all.
        """
        flow_objects, elementary, _stats = self._layer(self._uranium())
        by_uuid = {row.elementary_flow_id: row.flow_object_id for row in elementary}
        self.assertNotEqual(by_uuid["u-238-ef"], by_uuid["u-resource-ef"])
        self.assertNotEqual(by_uuid["u-238-ef"], by_uuid["u-alpha-ef"])

        by_label = self._by_label(flow_objects)
        self.assertIn("uranium", by_label)
        self.assertIn("uranium-238", by_label)

    def test_the_two_source_lists_agree_on_one_aggregate_object(self):
        """EF writes `Curium alpha`, ecoinvent writes `Curium Alpha`."""
        flow_objects, elementary, _stats = self._layer(self._curium())
        by_uuid = {row.elementary_flow_id: row.flow_object_id for row in elementary}
        self.assertEqual(by_uuid["cm-alpha-ef"], by_uuid["cm-alpha-ei"])
        self.assertNotEqual(by_uuid["cm-alpha-ef"], by_uuid["cm-element-ef"])

    def test_the_aggregate_links_to_the_element_and_not_to_a_nuclide(self):
        """#238 resolves the parent by CAS set, so it follows whichever object
        ends up holding `7440-61-1`. That used to be `Uranium-238`, and an
        aggregate of uranium's alpha emitters recorded as a child of U-238 is
        wrong in a way plutonium and curium never were (#17). Once the nuclide
        is keyed by its nuclide, the CAS is the element's alone.
        """
        for name, rows, element in (
            ("plutonium", self._plutonium(), "plutonium"),
            ("curium", self._curium(), "curium"),
            ("uranium", self._uranium(), "uranium"),
        ):
            with self.subTest(element=name):
                flow_objects, _elementary, _stats = self._layer(rows)
                aggregate = next(
                    fo for fo in flow_objects if fo.origin_qualifier == ALPHA_EMITTERS
                )
                self.assertEqual(
                    aggregate.parent_flow_object_id,
                    self._by_label(flow_objects)[element].flow_object_id,
                )

    def test_the_unqualified_object_keeps_its_identifier(self):
        """The split must not renumber the substance that was already right.

        A flow object id is `sha1("cas:<numbers>")`, and the element keeps that
        payload -- only the aggregate takes the `qual:` one. So the three
        objects the issue measured keep the ids they were published under, and
        three new ones appear beside them.
        """
        expected = {
            "plutonium": "fo-8e9d5d775b83fbdc",
            "curium": "fo-74d114e794587173",
            "uranium": "fo-93d10c394b58394e",
        }
        for element, rows in (
            ("plutonium", self._plutonium()),
            ("curium", self._curium()),
            ("uranium", self._uranium()),
        ):
            flow_objects, _elementary, _stats = self._layer(rows)
            by_label = self._by_label(flow_objects)
            aggregate = next(
                fo for fo in flow_objects if fo.origin_qualifier == ALPHA_EMITTERS
            )
            with self.subTest(element=element):
                self.assertEqual(
                    by_label[element].flow_object_id, expected[element]
                )
                self.assertNotEqual(
                    aggregate.flow_object_id, expected[element]
                )

    def test_the_aggregate_publishes_under_its_own_name(self):
        """`plutonium` and `Plutonium-alpha` published as `Plutonium` (#238)."""
        flow_objects, _elementary, _stats = self._layer(self._plutonium())
        labels = {
            fo.origin_qualifier: fo.prefLabel[0]["@value"] for fo in flow_objects
        }
        self.assertEqual(labels[ALPHA_EMITTERS], "Plutonium-alpha")
        self.assertEqual(labels[None], "plutonium")

    def test_the_element_label_no_longer_wins_on_length(self):
        """Which enrichment an object gets was decided by string length.

        `Curium Alpha` is longer than `Curium`, so the merged object took the
        aggregate's name -- and elemental curium published as `Curium Alpha`.
        """
        flow_objects, _elementary, _stats = self._layer(self._curium())
        labels = {
            fo.origin_qualifier: fo.prefLabel[0]["@value"] for fo in flow_objects
        }
        self.assertEqual(labels[None], "curium")
        self.assertNotIn("alpha", labels[None].lower())

    def test_element_enrichment_cannot_reach_the_aggregate(self):
        """It matches the element name against the object's canonical label.

        Not against `chemrof:ChemicalElement`, which is what #238 assumed: the
        guard is that `curiumalpha` is not `curium`, so splitting the object is
        what puts the aggregate out of reach.
        """
        from brightway_flows.flow_layers.labels import _canonical_name

        flow_objects, _elementary, _stats = self._layer(self._curium())
        by_qualifier = {fo.origin_qualifier: fo for fo in flow_objects}
        aggregate_label = by_qualifier[ALPHA_EMITTERS].prefLabel[0]["@value"]
        self.assertNotEqual(_canonical_name(aggregate_label), _canonical_name("curium"))
        self.assertEqual(
            _canonical_name(by_qualifier[None].prefLabel[0]["@value"]),
            _canonical_name("curium"),
        )

    def test_the_element_pass_no_longer_proposes_the_rename(self):
        """The whole of what the retired ruling used to hold back.

        `ElementPrefLabelPass` writes an element object's name over every flow
        that resolves to it. Once `Plutonium-alpha` is on its own object, it
        resolves to no element and the pass has nothing to propose -- so there
        is nothing left for `preferred-label-decisions.json` to reject.
        """
        from brightway_flows.domain.labels import flow_label_value
        from brightway_flows.pipeline.element_labels import ElementPrefLabelPass

        rows = self._plutonium()
        flow_objects, elementary, _stats = self._layer(rows)
        for obj in flow_objects:
            if obj.origin_qualifier is None:
                obj.types = [CHEMROF_CHEMICAL_ELEMENT]
                obj.prefLabel = [{"@value": "Plutonium", "@language": "en"}]

        flows = _as_flows(rows)
        by_uuid = {row.elementary_flow_id: row.flow_object_id for row in elementary}
        for flow in flows:
            flow.flow_object_id = by_uuid[flow.uuid]

        pass_ = ElementPrefLabelPass(decisions={})
        stats = pass_.apply(flows, flow_objects)

        self.assertEqual(stats["undecided"], 0)
        self.assertEqual(stats["renamed"], 0)
        self.assertEqual(pass_.review_queue_items(), [])
        labels = {flow.uuid: flow_label_value(flow) for flow in flows}
        self.assertEqual(labels["pu-alpha-ef"], "Plutonium-alpha")
        self.assertEqual(labels["pu-alpha-ei"], "Plutonium-alpha")
        self.assertEqual(labels["pu-element-ef"], "Plutonium")

    def test_the_aggregate_is_typed_and_stripped_end_to_end(self):
        """Layering, then typing: the two stages the pipeline runs in order."""
        flow_objects, elementary, _stats = self._layer(self._curium())
        assign_semantic_types(flow_objects, elementary)

        by_qualifier = {fo.origin_qualifier: fo for fo in flow_objects}
        aggregate = by_qualifier[ALPHA_EMITTERS]
        element = by_qualifier[None]

        self.assertEqual(aggregate.types, [IRIS[Term.ATOM_GROUPING_CLASS]])
        for key in SINGLE_SUBSTANCE_PROPERTIES:
            with self.subTest(property=key):
                self.assertNotIn(key, aggregate.properties)
        self.assertIn(CHEMROF_MOLECULAR_FORMULA, element.properties)


if __name__ == "__main__":
    unittest.main()
