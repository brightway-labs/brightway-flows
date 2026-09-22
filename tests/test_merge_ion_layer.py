"""A substance the merge creates for an ion reaches the element it is an ion of (#71).

BAFU names an emission to water `Iron, ion`. Nothing in the consensus list
answers to it -- the list holds `Iron(2+)` and `Iron(3+)`, which are different
substances -- so the merge mints a substance for the row, which is the right
thing to do. What it minted was a label and nothing else: no charge, no formula,
no element, no registry number.

Part of that is unavoidable. `Iron, ion` does not say whether it is ferrous or
ferric, and nothing can look up a structure for a name that does not name one.
But the element in it is not in question, and the list already knows what iron
is. The pass that says so exists -- it is the one that types `Sodium, ion` an
ion of sodium in the base list -- and the merge could not reach it, because it
sits behind `include_pubchem_isotopes` alongside the isotope machinery a merged
batch has no use for.

Two things are pinned here:

1. an object the merge creates for an ion is linked to the element flow object
   it is an ion of, and typed a monoatomic ion;
2. that element is looked for in the consensus list rather than in the batch,
   because a merge mints no elements and a batch asked about itself would
   recognise nothing.

The registry lookups the pass makes against Common Chemistry and PubChem are
stubbed out. They are cached and network-bound, and what is being tested is the
wiring, not what a registry says about iron on the day the suite runs.
"""

from __future__ import annotations

import unittest
from unittest import mock

from brightway_flows.domain.flow import Flow
from brightway_flows.domain.flow_object import FlowObject
from brightway_flows.domain.vocabulary import (
    CHEMROF_CHEMICAL_ELEMENT,
    CHEMROF_ELEMENTAL_CHARGE,
    CHEMROF_MONOATOMIC_ION,
)
from brightway_flows.merge.contexts import ContextExpectations
from brightway_flows.merge.creations import create_flows_for_unmatched_rows
from brightway_flows.merge.report import UnmatchedReason, UnmatchedRow
from brightway_flows.merge.state import MergeAccumulator, MergeIndexes
from brightway_flows.sources import resolve_source_list
from brightway_flows.transformers.unit_normalization import build_units_index

WATER = "https://vocab.brightway.one/flow-contexts/envi-wate-rive"

CONTEXTS = ContextExpectations(
    _by_source_context={("emissions to water", "river"): WATER},
    _source_label="test",
)
CONTEXT_STRINGS = {WATER: ["Environmental", "Water", "River"]}

IRON_OBJECT_ID = "fo-iron"


def _iron_element() -> FlowObject:
    """The iron the consensus list already holds, as the element pass typed it."""
    return FlowObject(
        flow_object_id=IRON_OBJECT_ID,
        prefLabel=[{"@value": "Iron", "@language": "en"}],
        altLabel=[],
        properties={},
        references=[],
        created_from={},
        types=[CHEMROF_CHEMICAL_ELEMENT],
    )


def _source_flow(uuid: str, name: str) -> Flow:
    return Flow.from_dict({
        "uuid": uuid,
        "identifier": uuid,
        "source": "bafu-2026-v1",
        "unit": "kg",
        "cas_numbers": [],
        "ec_numbers": [],
        "prefLabel": [{"@value": name, "@language": "en"}],
        "altLabel": [],
    })


def _unmatched(uuid: str, name: str) -> UnmatchedRow:
    return UnmatchedRow(
        source_uuid=uuid,
        source_name=name,
        source_context=["emissions to water", "river"],
        source_unit="kg",
        source_cas="",
        source_ec="",
        reason=UnmatchedReason.NO_FLOW_OBJECT_CANDIDATE,
        matching_method="algorithm",
    )


class CreatedIonReachesItsElementTestCase(unittest.TestCase):
    def setUp(self):
        self.units_index = build_units_index()
        self.flow_objects_by_id: dict[str, FlowObject] = {}
        self.indexes = MergeIndexes(
            flow_objects_by_id=self.flow_objects_by_id,
            flow_object_label_by_id={},
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
            source=resolve_source_list("bafu-2026-v1"),
        )
        self.accumulator = MergeAccumulator()
        # The registry lookups, silenced.  Patched on the module that calls
        # them, so the pass runs in full and only the network is missing.
        for name in (
            "_lookup_commonchemistry_ion_cas_cached",
            "_lookup_pubchem_ion_cas_cached",
        ):
            patcher = mock.patch(
                f"brightway_flows.flow_layers.ions.{name}", return_value=[]
            )
            patcher.start()
            self.addCleanup(patcher.stop)

    def create(self, name: str) -> FlowObject:
        objects, _created = create_flows_for_unmatched_rows(
            unmatched=[_unmatched("u-1", name)],
            source_flow_by_uuid={"u-1": _source_flow("u-1", name)},
            units_index=self.units_index,
            indexes=self.indexes,
            accumulator=self.accumulator,
        )
        self.assertEqual(len(objects), 1)
        return objects[0]

    def test_the_created_object_knows_which_element_it_is_an_ion_of(self):
        self.flow_objects_by_id[IRON_OBJECT_ID] = _iron_element()

        created = self.create("Iron, ion")

        relationships = created.properties.get("relationships", {})
        self.assertEqual(
            relationships.get("parent_element_flow_object_id"), IRON_OBJECT_ID
        )
        self.assertEqual(relationships.get("relationship_type"), "ion_of")

    def test_the_element_is_looked_for_in_the_consensus_list(self):
        """A merge mints no elements, so a batch asked about itself finds none."""
        created = self.create("Iron, ion")

        self.assertEqual(created.properties.get("relationships"), None)

    def test_a_stated_charge_is_published(self):
        """`Calcium II` says which ion it is; `Iron, ion` does not (#71)."""
        self.flow_objects_by_id[IRON_OBJECT_ID] = _iron_element()
        self.flow_objects_by_id["fo-calcium"] = FlowObject(
            flow_object_id="fo-calcium",
            prefLabel=[{"@value": "Calcium", "@language": "en"}],
            altLabel=[],
            properties={},
            references=[],
            created_from={},
            types=[CHEMROF_CHEMICAL_ELEMENT],
        )

        calcium = self.create("Calcium II")
        self.assertEqual(
            calcium.properties[CHEMROF_ELEMENTAL_CHARGE]["@value"], [2]
        )

        self.setUp()
        self.flow_objects_by_id[IRON_OBJECT_ID] = _iron_element()
        iron = self.create("Iron, ion")
        self.assertNotIn(CHEMROF_ELEMENTAL_CHARGE, iron.properties)

    def test_the_ion_is_published_as_an_ion_rather_than_as_unclassified(self):
        """The typing pass runs after this one and leaves the answer standing.

        It is asked second on purpose. Where it can read a structure it gives
        the more specific answer -- `Iron(2+)` is a cation of one atom, not the
        generic ion -- and where it cannot it declines rather than overwriting,
        which is what lets `Iron, ion` keep the one thing that *is* known about
        it. Untyped, it would publish as `unclassified` beside benzene, which is
        what #71 is about.
        """
        self.flow_objects_by_id[IRON_OBJECT_ID] = _iron_element()

        created = self.create("Iron, ion")

        self.assertIn(CHEMROF_MONOATOMIC_ION, created.types or [])

    def test_the_label_enrichment_settled_on_is_left_alone(self):
        """The merge does not let this pass rewrite a published label (#221)."""
        self.flow_objects_by_id[IRON_OBJECT_ID] = _iron_element()

        created = self.create("Iron, Ion")

        self.assertEqual(created.prefLabel[0]["@value"], "Iron, Ion")


if __name__ == "__main__":
    unittest.main()
