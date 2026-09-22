"""A source row that matches nothing becomes a consensus flow (#215).

The capability existed before #212 and took three builds to reach: the merge
reported the rows, a separate command wrote them to a file, and the next build's
transform turned that file into flow objects and elementary flows.  #214 moved
the enrichment half of that loop into the merge; this is the creation half.

What is asserted here is the shape of the rule rather than the size of its
output.  `multiple-flow-object-candidates` is excluded because the row matched
too much, not too little, and that exclusion is tested by constructing an
ambiguous row -- not by counting how many rows carry the reason today, which is
a number a data fix upstream can take to zero.
"""

from __future__ import annotations

import unittest

from brightway_flows.merge.contexts import ContextExpectations
from brightway_flows.domain.context_registry import context_for_iri
from brightway_flows.domain.elementary_flow import ElementaryFlow
from brightway_flows.domain.flow import Flow
from brightway_flows.domain.flow_object import FlowObject
from brightway_flows.domain.vocabulary import (
    CHEMINF_CAS_REGISTRY_NUMBER,
    SKOS_EXACT_MATCH_CURIE,
)
from brightway_flows.merge.creations import (
    CREATION_BLOCKED_KEY,
    create_flows_for_unmatched_rows,
)
from brightway_flows.manual_fixes import UNIT_CONVERSION_KEY
from brightway_flows.merge.report import UnmatchedReason, UnmatchedRow
from brightway_flows.sources import resolve_source_list
from brightway_flows.merge.state import MergeAccumulator, MergeIndexes
from brightway_flows.transformers.unit_normalization import build_units_index

AIR = "https://vocab.brightway.one/flow-contexts/envi-air-unkn"
WATER = "https://vocab.brightway.one/flow-contexts/envi-wate-unaq"

CONTEXTS = ContextExpectations(
    _by_source_context={
        ("air",): AIR,
        ("water", "ground-"): WATER,
    },
    _source_label="test",
)
CONTEXT_STRINGS = {
    AIR: ["Environmental", "Air"],
    WATER: ["Environmental", "Water", "Unconfined aquifer"],
}


def _source_flow(uuid: str, name: str, *, cas: str = "", ec: str = "") -> Flow:
    """A source row as it reaches the merge: enriched, with labels resolved."""
    return Flow.from_dict({
        "uuid": uuid,
        "identifier": uuid,
        "source": "ecoinvent-3.12",
        "unit": "kg",
        "cas_numbers": [cas] if cas else [],
        "ec_numbers": [ec] if ec else [],
        "prefLabel": [{"@value": name, "@language": "en"}],
        "altLabel": [],
    })


def _unmatched(
    uuid: str,
    name: str,
    context: list[str],
    *,
    cas: str = "",
    ec: str = "",
    unit: str = "kg",
    reason: UnmatchedReason = UnmatchedReason.NO_FLOW_OBJECT_CANDIDATE,
    shipped_name: str | None = None,
    basis: str | None = None,
) -> UnmatchedRow:
    return UnmatchedRow(
        source_uuid=uuid,
        source_name=name,
        source_context=context,
        source_unit=unit,
        source_cas=cas,
        source_ec=ec,
        reason=reason,
        source_shipped_name=shipped_name,
        matching_method="algorithm",
        basis=basis,
    )


class CreateFlowsTestCase(unittest.TestCase):
    def setUp(self):
        self.units_index = build_units_index()
        self.flow_objects_by_id: dict[str, FlowObject] = {}
        self.flow_object_label_by_id: dict[str, str] = {}
        self.indexes = MergeIndexes(
            flow_objects_by_id=self.flow_objects_by_id,
            flow_object_label_by_id=self.flow_object_label_by_id,
            cas_index={},
            ec_index={},
            label_index={},
            pref_label_index={},
            qualifier_index={},
            flow_objects_with_cas=set(),
            context_expectations=CONTEXTS,
            consensus_context_strings=CONTEXT_STRINGS,
            prepared_context_decisions={},
            mapping_file=None,
            source=resolve_source_list("ecoinvent-3.12"),
        )
        self.accumulator = MergeAccumulator()

    def create(self, rows, flows):
        return create_flows_for_unmatched_rows(
            unmatched=rows,
            source_flow_by_uuid={flow.uuid: flow for flow in flows},
            units_index=self.units_index,
            indexes=self.indexes,
            accumulator=self.accumulator,
        )

    def test_creates_a_flow_object_and_an_elementary_flow(self):
        row = _unmatched("u-1", "Ammonium bisulfate", ["air"], cas="7803-63-6")
        objects, created = self.create([row], [_source_flow("u-1", "Ammonium bisulfate", cas="7803-63-6")])

        self.assertEqual(len(objects), 1)
        self.assertEqual(len(created), 1)
        self.assertEqual(len(self.accumulator.merged_elementary), 1)
        flow = self.accumulator.merged_elementary[0]
        self.assertEqual(flow.flow_object_id, objects[0].flow_object_id)
        self.assertEqual(flow.context_iri, AIR)
        self.assertEqual(flow.source, "ecoinvent algorithm addition")

    def test_a_refused_row_s_basis_survives_into_the_created_record(self):
        """#198: ecoinvent's `Rhodium III` found the bare element by its own
        synonym and was refused, then minted.  Minting replaces the unmatched
        record, so the refusal is carried here or nowhere."""
        row = _unmatched("u-1", "Rhodium III", ["air"], cas="16065-89-7",
                         basis="label+ion-element-refused")
        _objects, created = self.create([row], [_source_flow("u-1", "Rhodium III", cas="16065-89-7")])
        self.assertEqual(created[0].unmatched_basis, "label+ion-element-refused")
        self.assertEqual(created[0].to_dict()["unmatched_basis"], "label+ion-element-refused")

    def test_an_ordinary_row_carries_no_unmatched_basis(self):
        """The other half: a row no name reached says nothing here, and the
        key is absent from its record rather than null."""
        row = _unmatched("u-1", "Ammonium bisulfate", ["air"], cas="7803-63-6")
        _objects, created = self.create([row], [_source_flow("u-1", "Ammonium bisulfate", cas="7803-63-6")])
        self.assertIsNone(created[0].unmatched_basis)
        self.assertNotIn("unmatched_basis", created[0].to_dict())

    def test_the_created_flow_records_the_name_the_vendor_shipped(self):
        """#149: `source_flow_name` is the vendor's string, not the enriched one.

        The row reaches creation under the label enrichment settled on -- here
        `Zinc(2+)`, which is what the merge matched on and what the object is
        named -- and BAFU called it `Zinc II`.  A consumer holding BAFU's
        inventory has `Zinc II` and nothing else, and the schema page promises
        it verbatim; publishing `Zinc(2+)` there broke that for ~5,300 rows.
        """
        row = _unmatched("u-1", "Zinc(2+)", ["air"], cas="23713-49-7", shipped_name="Zinc II")
        self.create([row], [_source_flow("u-1", "Zinc(2+)", cas="23713-49-7")])

        flow = self.accumulator.merged_elementary[0]
        self.assertEqual(flow.source_refs[0]["source_flow_name"], "Zinc II")
        # The object and the flow are still named what enrichment settled on:
        # only the vendor's record of its own row changes.
        self.assertEqual(self.flow_object_label_by_id[flow.flow_object_id], "Zinc(2+)")

    def test_a_row_without_a_shipped_name_records_the_one_it_has(self):
        # The other half: a row built without a record -- an unmatched row from
        # an older merge, a test fixture -- has no vendor string to publish, and
        # the name it matched on is the only name it has.
        row = _unmatched("u-1", "Ammonium bisulfate", ["air"], cas="7803-63-6")
        self.create([row], [_source_flow("u-1", "Ammonium bisulfate", cas="7803-63-6")])
        flow = self.accumulator.merged_elementary[0]
        self.assertEqual(flow.source_refs[0]["source_flow_name"], "Ammonium bisulfate")

    def test_the_object_keeps_what_enrichment_resolved(self):
        row = _unmatched("u-1", "Ammonium bisulfate", ["air"], cas="7803-63-6")
        objects, created = self.create([row], [_source_flow("u-1", "Ammonium bisulfate", cas="7803-63-6")])

        values = objects[0].classifications[CHEMINF_CAS_REGISTRY_NUMBER]["@value"]
        self.assertEqual(values, ["7803-63-6"])
        self.assertEqual(created[0].flow_object_cas, ["7803-63-6"])
        self.assertFalse(created[0].identity_is_name_only)

    def test_a_name_only_source_makes_a_name_only_object(self):
        """A third of these rows have no CAS and no EC.  That is the source."""
        row = _unmatched("u-1", "Alkylbenzene (c10-c15)", ["air"])
        _objects, created = self.create([row], [_source_flow("u-1", "Alkylbenzene (c10-c15)")])

        self.assertTrue(created[0].identity_is_name_only)
        self.assertEqual(created[0].flow_object_cas, [])

    def test_multiple_flow_object_candidates_creates_nothing(self):
        """The row matched too much, not too little.  Choosing is a guess."""
        row = _unmatched(
            "u-1", "Pyrethrins", ["air"],
            cas="8003-34-7",
            reason=UnmatchedReason.MULTIPLE_FLOW_OBJECT_CANDIDATES,
        )
        objects, created = self.create([row], [_source_flow("u-1", "Pyrethrins", cas="8003-34-7")])

        self.assertEqual(objects, [])
        self.assertEqual(created, [])
        self.assertEqual(self.accumulator.merged_elementary, [])

    def test_one_substance_in_two_contexts_makes_one_object(self):
        rows = [
            _unmatched("u-1", "Astatine", ["air"], cas="7440-68-8"),
            _unmatched("u-2", "Astatine", ["water", "ground-"], cas="7440-68-8"),
        ]
        flows = [
            _source_flow("u-1", "Astatine", cas="7440-68-8"),
            _source_flow("u-2", "Astatine", cas="7440-68-8"),
        ]
        objects, created = self.create(rows, flows)

        self.assertEqual(len(objects), 1)
        self.assertEqual(len(created), 2)
        self.assertEqual(len(self.accumulator.merged_elementary), 2)
        self.assertEqual(
            {row.flow_object_id for row in created}, {objects[0].flow_object_id}
        )
        self.assertEqual(
            {flow.context_iri for flow in self.accumulator.merged_elementary},
            {AIR, WATER},
        )
        self.assertEqual([row.minted_flow_object for row in created], [True, False])

    def test_two_rows_in_one_context_share_one_flow(self):
        """`(flow_object_id, context_iri)` is unique across active flows."""
        rows = [
            _unmatched("u-1", "Disinfectants, unspecified", ["air"]),
            _unmatched("u-2", "Disinfectants, unspecified", ["air"]),
        ]
        flows = [
            _source_flow("u-1", "Disinfectants, unspecified"),
            _source_flow("u-2", "Disinfectants, unspecified"),
        ]
        objects, created = self.create(rows, flows)

        self.assertEqual(len(objects), 1)
        self.assertEqual(len(self.accumulator.merged_elementary), 1)
        flow = self.accumulator.merged_elementary[0]
        self.assertEqual(
            sorted(ref["source_flow_uuid"] for ref in flow.source_refs),
            ["u-1", "u-2"],
        )
        self.assertEqual(
            {row.new_elementary_flow_id for row in created},
            {flow.elementary_flow_id},
        )

    def _road_noise(self, order):
        """BAFU's road-noise pair: one flow, shipped in kilometres and metres."""
        rows = [
            _unmatched(uuid, "Noise, Road, Lorry, Average", ["air"], unit=unit)
            for uuid, unit in order
        ]
        flows = [
            _source_flow(uuid, "Noise, Road, Lorry, Average") for uuid, _unit in order
        ]
        return self.create(rows, flows)

    def test_two_rows_disagreeing_about_the_unit_declare_the_reference_one(self):
        """#70: BAFU ships its road noise in kilometres and again in metres.

        Both rows land on one flow, and the flow used to take whichever unit
        arrived first -- so the lorry came out in metres and the passenger car
        in kilometres, from one list, on one day.  The metre is what
        `units.json` makes the reference unit for a length.
        """
        for order in (
            (("u-km", "km"), ("u-m", "m")),
            (("u-m", "m"), ("u-km", "km")),
        ):
            with self.subTest(first=order[0][1]):
                self.setUp()
                self.create(
                    [
                        _unmatched(uuid, "Noise, Road, Lorry, Average", ["air"], unit=unit)
                        for uuid, unit in order
                    ],
                    [
                        _source_flow(uuid, "Noise, Road, Lorry, Average")
                        for uuid, _unit in order
                    ],
                )

                self.assertEqual(len(self.accumulator.merged_elementary), 1)
                flow = self.accumulator.merged_elementary[0]
                self.assertEqual(flow.unit, "m")
                self.assertTrue(flow.unit_iri.endswith("/M"))

    def test_each_row_keeps_the_unit_its_source_list_gave_it(self):
        """The flow restates the quantity; it does not restate the source.

        A source ref saying `m` for a row BAFU ships in `km` would be this list
        putting words in BAFU's mouth, and the concept association is the thing
        a consumer maps through.
        """
        self._road_noise((("u-km", "km"), ("u-m", "m")))

        flow = self.accumulator.merged_elementary[0]
        self.assertEqual(
            {
                ref["source_flow_uuid"]: ref["source_metadata"]["unit"]
                for ref in flow.source_refs
            },
            {"u-km": "km", "u-m": "m"},
        )
        units_by_uuid = {}
        for association in flow.concept_associations:
            concept = association["xkos:sourceConcept"]
            uuid = concept["@id"].rsplit("/", 1)[-1]
            units_by_uuid[uuid] = concept["qudt:hasUnit"]["@id"].rsplit("/", 1)[-1]
        self.assertEqual(units_by_uuid, {"u-km": "KiloM", "u-m": "M"})

    def test_no_conversion_multiplier_is_published_for_two_spellings_of_one_scale(self):
        """`units.json` converts kilometres to metres, and the reader has it.

        The same test every conversion in this project passes: only a factor the
        unit table could not already have made is published.
        """
        self._road_noise((("u-km", "km"), ("u-m", "m")))

        flow = self.accumulator.merged_elementary[0]
        for association in flow.concept_associations:
            self.assertNotIn("qudt:conversionMultiplier", association)

    def test_rows_that_agree_about_the_unit_are_left_alone(self):
        rows = [
            _unmatched("u-1", "Disinfectants, unspecified", ["air"], unit="km"),
            _unmatched("u-2", "Disinfectants, unspecified", ["air"], unit="km"),
        ]
        flows = [
            _source_flow("u-1", "Disinfectants, unspecified"),
            _source_flow("u-2", "Disinfectants, unspecified"),
        ]
        self.create(rows, flows)

        self.assertEqual(self.accumulator.merged_elementary[0].unit, "km")

    def test_units_with_no_reference_between_them_keep_the_first(self):
        """Two multiples of one scale and neither is the scale.

        `m*a` and `km*a` both state themselves against `m*s`, which neither of
        them is.  Choosing between them would be picking, not deciding, so the
        first row stands and the run says so.
        """
        rows = [
            _unmatched("u-1", "Occupation, arable", ["air"], unit="m.a"),
            _unmatched("u-2", "Occupation, arable", ["air"], unit="km.a"),
        ]
        flows = [
            _source_flow("u-1", "Occupation, arable"),
            _source_flow("u-2", "Occupation, arable"),
        ]
        self.create(rows, flows)

        self.assertEqual(self.accumulator.merged_elementary[0].unit, "m.a")

    def test_identifiers_are_minted_rather_than_the_source_uuid(self):
        row = _unmatched("u-1", "Butatriene", ["air"], cas="2873-50-9")
        objects, created = self.create([row], [_source_flow("u-1", "Butatriene", cas="2873-50-9")])

        self.assertNotEqual(created[0].new_elementary_flow_id, "u-1")
        self.assertNotEqual(objects[0].flow_object_id, "u-1")

    def test_the_source_row_is_an_exact_match_to_the_flow_it_created(self):
        row = _unmatched("u-1", "Butatriene", ["air"], cas="2873-50-9")
        _objects, created = self.create([row], [_source_flow("u-1", "Butatriene", cas="2873-50-9")])

        flow = self.accumulator.merged_elementary[0]
        association = flow.concept_associations[0]
        source_concept = association["xkos:sourceConcept"]
        self.assertIn(SKOS_EXACT_MATCH_CURIE, source_concept)
        self.assertEqual(
            source_concept[SKOS_EXACT_MATCH_CURIE]["@id"].rsplit("/", 1)[-1],
            created[0].new_elementary_flow_id,
        )
        self.assertNotIn("xkos:mapType", association)

    def test_the_new_label_reaches_the_label_index(self):
        """Without this a created flow syncs with the empty string for a name."""
        row = _unmatched("u-1", "Calcium II", ["air"], cas="14127-61-8")
        objects, _created = self.create([row], [_source_flow("u-1", "Calcium II", cas="14127-61-8")])

        object_id = objects[0].flow_object_id
        self.assertEqual(self.flow_object_label_by_id[object_id], "Calcium II")
        self.assertIn(object_id, self.flow_objects_by_id)

    def test_an_id_that_already_exists_is_a_matcher_miss_not_a_creation(self):
        """`_stable_object_id` seeds on identity, so this is never a hash clash."""
        probe = _unmatched("u-1", "Astatine", ["air"], cas="7440-68-8")
        objects, _created = self.create([probe], [_source_flow("u-1", "Astatine", cas="7440-68-8")])
        existing_id = objects[0].flow_object_id

        self.setUp()
        self.flow_objects_by_id[existing_id] = FlowObject(
            flow_object_id=existing_id, prefLabel=[], altLabel=[],
            properties={}, references=[], created_from={},
        )
        row = _unmatched("u-2", "Astatine", ["air"], cas="7440-68-8")
        objects, created = self.create([row], [_source_flow("u-2", "Astatine", cas="7440-68-8")])

        self.assertEqual(objects, [])
        self.assertEqual(created, [])
        self.assertEqual(self.accumulator.merged_elementary, [])
        self.assertEqual(row.extra[CREATION_BLOCKED_KEY], existing_id)

    def test_an_object_a_manual_addition_already_uses_is_refused(self):
        """A curated grouping's target id is minted by the same seeding.

        In a bounded run the grouping file names flow objects the subset does
        not contain, so the object exists only as something manual additions
        put flows on.  Creating there would attach the row to the curator's
        group flow rather than giving the substance its own.
        """
        probe = _unmatched("u-1", "Pesticides, unspecified", ["air"])
        objects, _created = self.create([probe], [_source_flow("u-1", "Pesticides, unspecified")])
        grouped_id = objects[0].flow_object_id

        self.setUp()
        self.accumulator.elementary_by_object[grouped_id] = [ElementaryFlow(
            elementary_flow_id="manual-1",
            flow_object_id=grouped_id,
            source="ecoinvent manual addition",
            context=context_for_iri(AIR),
            context_iri=AIR,
            unit="kg",
            unit_iri="",
            lcia_methods=[],
            general_comment=None,
        )]
        row = _unmatched("u-2", "Pesticides, unspecified", ["air"])
        objects, created = self.create([row], [_source_flow("u-2", "Pesticides, unspecified")])

        self.assertEqual(objects, [])
        self.assertEqual(created, [])
        self.assertEqual(row.extra[CREATION_BLOCKED_KEY], grouped_id)

    def test_an_unregistered_context_raises(self):
        """Guessing would put the substance somewhere arbitrary."""
        row = _unmatched("u-1", "Astatine", ["nowhere"], cas="7440-68-8")
        with self.assertRaises(ValueError) as caught:
            self.create([row], [_source_flow("u-1", "Astatine", cas="7440-68-8")])
        self.assertIn("harmonised context", str(caught.exception))

    def test_the_object_is_typed_from_its_chemistry(self):
        """`flow_objects.flow_type` is NOT NULL; an untyped object is a defect."""
        row = _unmatched("u-1", "Astatine", ["air"], cas="7440-68-8")
        objects, _created = self.create([row], [_source_flow("u-1", "Astatine", cas="7440-68-8")])

        self.assertIn("semantic_typing", objects[0].created_from)


class ARowRebasedOntoAnotherUnitTestCase(unittest.TestCase):
    """A created flow whose row arrived in a unit a fix rebased.

    BAFU ships standing wood twice, once by mass and once by volume, and the
    mass rows are rebased onto cubic metres so that one resource is one flow.
    That is only honest if the mapping still says which unit the vendor's own
    amounts are in and what to multiply them by: the flow is in cubic metres,
    the vendor's numbers are kilograms, and 0.00204 is what joins them.

    Volume and mass are different quantity kinds, so `units.json` has no factor
    to defer to -- which is exactly the test a published conversion has to pass.
    """

    FACTOR = 0.00204

    def setUp(self):
        self.case = CreateFlowsTestCase("run")
        self.case.setUp()
        row = _unmatched("u-1", "Wood, unspecified, standing", ["air"], unit="m3")
        flow = _source_flow("u-1", "Wood, unspecified, standing")
        flow.unit = "m3"
        flow.extra[UNIT_CONVERSION_KEY] = {
            "source_unit": "kg",
            "target_unit": "m3",
            "factor": self.FACTOR,
            "comment": "0.49 oven-dry tonnes per m3",
        }
        self.case.create([row], [flow])
        self.flow = self.case.accumulator.merged_elementary[0]
        self.association = self.flow.concept_associations[0]

    def test_the_flow_is_created_in_the_unit_it_was_rebased_onto(self):
        self.assertEqual(self.flow.unit, "m3")

    def test_the_mapping_states_the_unit_the_vendor_shipped(self):
        """Not the one the row is being carried in. A mapping saying `m3` for a
        row whose amounts are kilograms would be this list restating the
        vendor's inventory rather than translating it."""
        concept = self.association["xkos:sourceConcept"]
        self.assertEqual(concept["qudt:hasUnit"]["@id"].rsplit("/", 1)[-1], "KiloGM")
        self.assertEqual(self.flow.source_refs[0]["source_metadata"]["unit"], "kg")

    def test_the_factor_is_published_on_the_mapping(self):
        self.assertEqual(
            self.association["qudt:conversionMultiplier"], self.FACTOR
        )
        self.assertEqual(
            self.flow.source_refs[0]["source_metadata"][
                "qudt:conversionMultiplier"
            ],
            self.FACTOR,
        )

    def test_an_ordinary_row_publishes_no_factor(self):
        case = CreateFlowsTestCase("run")
        case.setUp()
        case.create(
            [_unmatched("u-2", "Astatine", ["air"], cas="7440-68-8")],
            [_source_flow("u-2", "Astatine", cas="7440-68-8")],
        )
        association = case.accumulator.merged_elementary[0].concept_associations[0]
        self.assertNotIn("qudt:conversionMultiplier", association)


if __name__ == "__main__":
    unittest.main()
