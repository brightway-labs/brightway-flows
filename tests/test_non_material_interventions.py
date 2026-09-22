"""#70: the six BAFU traffic-noise rows, and what holds them together.

Noise is a real environmental burden with a compartment of its own, and it is
not a substance.  These tests pin both halves of the answer: the six rows say
what they are instead of claiming their identity is unreadable, and they point
at one another through a minted family rather than through
`brightway:baseSubstance`, which would publish them as the thing they are not.
"""

import json
import unittest
from pathlib import Path
from tempfile import mkdtemp
from unittest import mock

import orjson

from brightway_flows.context_mapping import context_iri_by_source_context
from brightway_flows.domain.context_registry import context_from_dict
from brightway_flows.domain.flow import Flow
from brightway_flows.domain.flow_object import FlowObject
from brightway_flows.domain.simple_flow import SimpleFlow
from brightway_flows.domain.vocabulary import (
    BRIGHTWAY_BASE_INTERVENTION,
    BRIGHTWAY_BASE_SUBSTANCE,
)
from brightway_flows.flow_layers import non_material
from brightway_flows.flow_layers.non_material import (
    NonMaterialFamilyError,
    attach_non_material_families,
    _families,
    _family_for,
)
from brightway_flows.merge.contexts import ContextExpectations
from brightway_flows.merge.creations import create_flows_for_unmatched_rows
from brightway_flows.merge.report import UnmatchedReason, UnmatchedRow
from brightway_flows.merge.state import MergeAccumulator, MergeIndexes
from brightway_flows.pipeline.semantic_typing import assign_semantic_types
from brightway_flows.sources import (
    base_source_list,
    known_source_lists,
    resolve_source_list,
)
from brightway_flows.transformers.unit_normalization import build_units_index

BAFU = "bafu-2026-v1"
BAFU_NON_MATERIAL = ["non material emissions", "unspecified"]

#: The compartment BAFU calls `non material emissions`, as this list maps it.
NON_MATERIAL = context_from_dict({"dimension": "Environmental", "media": "Other"})
GROUND_LEVEL_AIR = context_from_dict({
    "dimension": "Environmental", "media": "Air", "strata": "Ground level",
    "population_density": "Urban (>1000 people/square mile)",
})

#: The six names, with the units BAFU gives them: what is counted is not how
#: much noise there is but how much transport it accompanied.
BAFU_NOISE = (
    ("Noise, Aircraft, Freight", "t.km"),
    ("Noise, Aircraft, Passenger", "p.km"),
    ("Noise, Rail, Freight Train", "t.km"),
    ("Noise, Rail, Passenger Train, Average", "p.km"),
    ("Noise, Road, Lorry, Average", "m"),
    ("Noise, Road, Passenger Car, Average", "km"),
)


def make_object(label, **kwargs):
    return FlowObject(
        flow_object_id="fo-" + label.lower().replace(" ", "-").replace(",", "")[:28],
        prefLabel=[{"@value": label, "@language": "en"}],
        altLabel=[],
        properties=kwargs.pop("properties", {}),
        references=[],
        created_from={},
        **kwargs,
    )


class Occurrence:
    """One elementary flow, reduced to what the family pass reads off it."""

    def __init__(self, flow_object_id, context):
        self.flow_object_id = flow_object_id
        self.context = context


def occurrences(*pairs):
    return [Occurrence(object_id, context) for object_id, context in pairs]


def make_simple_flow(label, unit, **kwargs):
    return SimpleFlow(
        identifier=label,
        source="BAFU/2026-v1",
        cas_numbers=[],
        ec_numbers=[],
        context_iri="https://vocab.brightway.one/flow-contexts/envi-othe",
        unit=unit,
        unit_iri="",
        prefLabel=label,
        altLabel=[],
        properties={},
        references=[],
        definition=[],
        jsonld_id=f"https://example.invalid/{label}",
        **kwargs,
    )


class NoiseFamilyTestCase(unittest.TestCase):
    """Six measurements of one thing, and the thing itself."""

    def setUp(self):
        self.objects = [make_object(label) for label, _unit in BAFU_NOISE]
        self.flows = occurrences(
            *[(obj.flow_object_id, NON_MATERIAL) for obj in self.objects]
        )

    def test_the_six_noise_rows_become_one_family(self):
        objects, stats = attach_non_material_families(self.objects, self.flows)

        self.assertEqual(stats["non_material_candidates"], 6)
        self.assertEqual(stats["non_material_families_minted"], 1)
        self.assertEqual(stats["non_material_members_linked"], 6)
        self.assertEqual(stats["non_material_unfamilied"], 0)

        parents = {obj.parent_intervention_id for obj in self.objects}
        self.assertEqual(len(parents), 1)
        parent_id = parents.pop()
        minted = [obj for obj in objects if obj.flow_object_id == parent_id]
        self.assertEqual(len(minted), 1)
        self.assertEqual(minted[0].prefLabel[0]["@value"], "Noise")

    def test_each_row_keeps_its_own_flow_object(self):
        """The invariant is one substance, one context, one flow.

        Six flows sharing one object in one context is what the review app's
        duplicate check exists to find, and the six differ in unit and in
        characterisation factors besides.  What they share is a parent.
        """
        objects, _stats = attach_non_material_families(self.objects, self.flows)

        member_ids = {obj.flow_object_id for obj in self.objects}
        self.assertEqual(len(member_ids), 6)
        self.assertEqual(len(objects), 7)

    def test_the_family_carries_a_definition(self):
        """A flow object that is not a substance has to say what it is."""
        objects, _stats = attach_non_material_families(self.objects, self.flows)

        by_id = {obj.flow_object_id: obj for obj in objects}
        parent = by_id[self.objects[0].parent_intervention_id]
        self.assertTrue(parent.skos_definition)
        self.assertIn(
            "rather than as a release of matter",
            parent.skos_definition[0]["@value"],
        )

    def test_the_family_identifier_is_a_function_of_the_family(self):
        """Minted from the family id, so it survives a rebuild unchanged."""
        first, _stats = attach_non_material_families(
            [make_object(label) for label, _ in BAFU_NOISE], self.flows
        )
        second, _stats = attach_non_material_families(self.objects, self.flows)

        self.assertEqual(
            {obj.flow_object_id for obj in first},
            {obj.flow_object_id for obj in second},
        )


class WhatIsNotAFamilyMemberTestCase(unittest.TestCase):
    """The candidate set is decided by the context, and only by the context."""

    def test_a_substance_with_one_stray_occurrence_is_not_a_candidate(self):
        """Every context, not any.  Carbon dioxide stays carbon dioxide."""
        substance = make_object("Carbon dioxide")
        objects, stats = attach_non_material_families(
            [substance],
            occurrences(
                (substance.flow_object_id, NON_MATERIAL),
                (substance.flow_object_id, GROUND_LEVEL_AIR),
            ),
        )

        self.assertEqual(stats["non_material_candidates"], 0)
        self.assertIsNone(substance.parent_intervention_id)
        self.assertEqual(len(objects), 1)

    def test_a_candidate_no_family_claims_is_counted_rather_than_swept_in(self):
        """A second kind of non-material flow is a decision, not a default."""
        radiation = make_object("Ionising radiation, to air")
        objects, stats = attach_non_material_families(
            [radiation],
            occurrences((radiation.flow_object_id, NON_MATERIAL)),
        )

        self.assertEqual(stats["non_material_candidates"], 1)
        self.assertEqual(stats["non_material_unfamilied"], 1)
        self.assertEqual(stats["non_material_families_minted"], 0)
        self.assertIsNone(radiation.parent_intervention_id)
        self.assertEqual(len(objects), 1)

    def test_a_family_of_one_mints_nothing(self):
        """One member *is* the intervention; a parent over it groups nothing."""
        lone = make_object("Noise, Road, Lorry, Average")
        objects, stats = attach_non_material_families(
            [lone], occurrences((lone.flow_object_id, NON_MATERIAL))
        )

        self.assertEqual(stats["non_material_candidates"], 1)
        self.assertEqual(stats["non_material_families_minted"], 0)
        self.assertEqual(stats["non_material_members_linked"], 0)
        self.assertIsNone(lone.parent_intervention_id)
        self.assertEqual(len(objects), 1)


class TypingTheFamilyTestCase(unittest.TestCase):
    """Layering, then typing: the two stages the pipeline runs in order."""

    def test_every_member_and_the_family_itself_say_what_they_are(self):
        """The family has no flows of its own, so it inherits its members'.

        Without that it reaches the last rule and is told its identity is
        unreadable -- the answer #70 exists to stop, one level up.
        """
        members = [make_object(label) for label, _unit in BAFU_NOISE]
        flows = occurrences(*[(obj.flow_object_id, NON_MATERIAL) for obj in members])
        objects, _stats = attach_non_material_families(members, flows)

        assign_semantic_types(objects, flows)

        for obj in objects:
            with self.subTest(label=obj.prefLabel[0]["@value"]):
                self.assertEqual(obj.types, None)
                self.assertEqual(
                    obj.created_from["semantic_typing"]["reason"],
                    "non_material_intervention_not_a_chemical_entity",
                )


class PublishedLinkTestCase(unittest.TestCase):
    """What the export says, which is the whole reason for a second term."""

    def test_the_link_is_a_base_intervention_and_not_a_base_substance(self):
        payload = make_simple_flow(
            "Noise, Road, Lorry, Average",
            "km",
            parent_intervention_id={"@id": "https://example.invalid/fo-noise"},
        ).to_dict()

        self.assertEqual(
            payload[BRIGHTWAY_BASE_INTERVENTION],
            {"@id": "https://example.invalid/fo-noise"},
        )
        self.assertNotIn(BRIGHTWAY_BASE_SUBSTANCE, payload)

    def test_a_substance_publishes_neither(self):
        payload = make_simple_flow("Carbon dioxide", "kg").to_dict()

        self.assertNotIn(BRIGHTWAY_BASE_INTERVENTION, payload)
        self.assertNotIn(BRIGHTWAY_BASE_SUBSTANCE, payload)


class DeclaredFamiliesTestCase(unittest.TestCase):
    """Properties of the rows this project actually ships."""

    def test_the_shipped_families_all_load(self):
        self.assertTrue(_families())

    def test_every_family_carries_its_reasoning(self):
        """`comment` is why the family exists; `definition` is what it says.

        The definition is published on the minted object and a reader sees it.
        The comment is for whoever re-reads the decision, which is the thing a
        hand-written exception to an automatic rule most needs.
        """
        for family in _families():
            with self.subTest(family=family.id):
                self.assertGreater(len(family.comment), 40)
                self.assertGreater(len(family.definition), 40)

    def _vendor_files(self):
        files = {
            source.source_label: source.flows_path
            for source in (base_source_list(), *known_source_lists().values())
        }
        missing = [path for path in files.values() if not path.exists()]
        if missing:
            self.skipTest(f"vendor flow files not fetched: {missing[0].name}")
        return files

    def _vendor_names(self):
        return [
            str(flow.get("name") or "")
            for path in self._vendor_files().values()
            for flow in json.loads(path.read_bytes())
        ]

    def test_every_family_names_flows_a_registered_list_ships(self):
        """A family matching nothing is inert, and inert reads like a typo.

        The same argument `flow_specific_context_mappings` makes about a uuid no
        version carries: these are few enough to check against the vendor files,
        so a pattern that has stopped matching fails here rather than doing
        nothing.  Two matches, not one -- a family of one mints no object, so a
        family that can only ever match one flow is inert in a second way.
        """
        names = self._vendor_names()
        for family in _families():
            with self.subTest(family=family.id):
                matched = {name for name in names if family.pattern.search(name)}
                self.assertGreater(
                    len(matched), 1,
                    f"{family.id} matches {sorted(matched)}, which mints nothing",
                )

    def test_no_two_families_claim_one_flow_the_lists_ship(self):
        """Asked of the vendor data rather than of the patterns.

        Two patterns can be disjoint in principle and overlap on the one name a
        list actually ships, and it is the name that decides.
        """
        for name in self._vendor_names():
            # `_family_for` raises when two families claim one name.
            _family_for(name)


class LoaderValidationTestCase(unittest.TestCase):
    """What a family has to carry, and what happens when it does not.

    These are hand-written decisions about what this list publishes, in a file a
    curator edits.  Every field is load-bearing: without `label` and
    `definition` the minted object says nothing about itself, without
    `name_pattern` the family claims no flows, and without `comment` nobody can
    re-check the reasoning that put it there.
    """

    GOOD = {
        "id": "noise",
        "label": "Noise",
        "definition": "Sound emitted by a human activity.",
        "name_pattern": r"^noise\b",
        "comment": "because",
    }

    def _families(self, *rows):
        """Load *rows* through the real loader, with its cache cleared."""
        path = Path(mkdtemp()) / "non-material-interventions.json"
        path.write_bytes(orjson.dumps({"families": list(rows)}))
        with mock.patch.object(non_material, "FAMILIES_FILEPATH", path):
            non_material._families.cache_clear()
            try:
                return non_material._families()
            finally:
                non_material._families.cache_clear()

    def test_a_complete_family_loads(self):
        self.assertEqual([f.id for f in self._families(self.GOOD)], ["noise"])

    def test_every_required_field_is_required(self):
        for field in ("id", "label", "definition", "name_pattern", "comment"):
            with self.subTest(missing=field):
                row = {k: v for k, v in self.GOOD.items() if k != field}
                with self.assertRaises(NonMaterialFamilyError) as caught:
                    self._families(row)
                self.assertIn(field, str(caught.exception))

    def test_an_empty_field_counts_as_missing(self):
        for field in ("id", "label", "definition", "name_pattern", "comment"):
            with self.subTest(empty=field):
                with self.assertRaises(NonMaterialFamilyError):
                    self._families({**self.GOOD, field: "   "})

    def test_two_families_with_one_id_is_an_error_rather_than_last_wins(self):
        """One family, one row -- the rule `flow_specific_context_mappings`
        states as "one flow, one rule", and for the same reason: two curated
        statements arbitrated by file order is not a decision."""
        other = {**self.GOOD, "label": "Sound"}
        with self.assertRaises(NonMaterialFamilyError) as caught:
            self._families(self.GOOD, other)
        self.assertIn("noise", str(caught.exception))

    def test_an_unusable_pattern_is_an_error_rather_than_a_dead_family(self):
        with self.assertRaises(NonMaterialFamilyError) as caught:
            self._families({**self.GOOD, "name_pattern": "^noise("})
        self.assertIn("name_pattern", str(caught.exception))

    def test_a_file_with_no_families_is_not_an_error(self):
        self.assertEqual(self._families(), ())

    def test_a_flow_two_families_claim_is_an_error(self):
        """Not first-match-wins: which family a flow joins would then be decided
        by the order two curators happened to write them in."""
        path = Path(mkdtemp()) / "non-material-interventions.json"
        path.write_bytes(orjson.dumps({"families": [
            self.GOOD,
            {**self.GOOD, "id": "sound", "label": "Sound", "name_pattern": "road"},
        ]}))
        with mock.patch.object(non_material, "FAMILIES_FILEPATH", path):
            non_material._families.cache_clear()
            try:
                with self.assertRaises(NonMaterialFamilyError) as caught:
                    _family_for("Noise, Road, Lorry, Average")
                self.assertIn("noise", str(caught.exception))
                self.assertIn("sound", str(caught.exception))
            finally:
                non_material._families.cache_clear()


class MergeIntegrationTestCase(unittest.TestCase):
    """Through the merge, over the rows BAFU actually ships.

    The tests above hold the family pass directly.  This one runs BAFU's real
    non-material rows through the merge's own creation path, with BAFU's real
    context rules loaded, so what is asserted is what a build does rather than
    what the pass does when called correctly.
    """

    def _bafu_noise_rows(self):
        path = resolve_source_list(BAFU).flows_path
        if not path.exists():
            self.skipTest(f"vendor flow file not fetched: {path.name}")
        rows = [
            flow for flow in json.loads(path.read_bytes())
            if flow["context"] == BAFU_NON_MATERIAL
        ]
        self.assertTrue(rows, "BAFU ships no non-material rows any more")
        return rows

    def _create(self, rows):
        indexes = MergeIndexes(
            flow_objects_by_id={},
            flow_object_label_by_id={},
            cas_index={},
            ec_index={},
            label_index={},
            pref_label_index={},
            qualifier_index={},
            flow_objects_with_cas=set(),
            context_expectations=ContextExpectations(
                _by_source_context=dict(context_iri_by_source_context(BAFU)),
                _source_label=BAFU,
            ),
            consensus_context_strings={},
            prepared_context_decisions={},
            mapping_file=None,
            source=resolve_source_list(BAFU),
        )
        unmatched = [
            UnmatchedRow(
                source_uuid=row["uuid"],
                source_name=row["name"],
                source_context=list(row["context"]),
                source_unit=row["unit"],
                source_cas="",
                source_ec="",
                reason=UnmatchedReason.NO_FLOW_OBJECT_CANDIDATE,
                matching_method="algorithm",
            )
            for row in rows
        ]
        flows = {
            row["uuid"]: Flow.from_dict({
                "uuid": row["uuid"],
                "identifier": row["uuid"],
                "source": BAFU,
                "unit": row["unit"],
                "prefLabel": [{"@value": row["name"], "@language": "en"}],
                "altLabel": [],
            })
            for row in rows
        }
        accumulator = MergeAccumulator()
        objects, _created = create_flows_for_unmatched_rows(
            unmatched=unmatched,
            source_flow_by_uuid=flows,
            units_index=build_units_index(),
            indexes=indexes,
            accumulator=accumulator,
        )
        return objects, accumulator

    def test_bafus_non_material_compartment_is_still_only_noise(self):
        """The premise of the family. A row here that is not noise is a
        decision to make -- see the `non_material_unfamilied` count."""
        for name in {row["name"] for row in self._bafu_noise_rows()}:
            with self.subTest(name=name):
                self.assertIsNotNone(_family_for(name))

    def test_the_noise_rows_come_out_of_the_merge_in_one_family(self):
        objects, _accumulator = self._create(self._bafu_noise_rows())

        by_id = {obj.flow_object_id: obj for obj in objects}
        parents = {
            obj.parent_intervention_id
            for obj in objects
            if obj.parent_intervention_id
        }
        self.assertEqual(len(parents), 1, "the noise rows did not reach one family")
        parent = by_id[parents.pop()]
        self.assertEqual(parent.prefLabel[0]["@value"], "Noise")
        members = [
            obj for obj in objects
            if obj.parent_intervention_id == parent.flow_object_id
        ]
        self.assertEqual(len(members), len(objects) - 1)

    def test_the_road_rows_come_out_in_metres(self):
        """BAFU ships the lorry and the passenger car in kilometres and again in
        metres; the metre is what `units.json` makes the reference for a
        length."""
        _objects, accumulator = self._create(self._bafu_noise_rows())

        road = {
            flow.extra["prefLabel"][0]["@value"]: flow.unit
            for flow in accumulator.merged_elementary
            if "road" in flow.extra["prefLabel"][0]["@value"].lower()
        }
        self.assertTrue(road, "BAFU ships no road-noise rows any more")
        self.assertEqual(set(road.values()), {"m"}, road)

    def test_none_of_them_is_published_as_a_substance(self):
        """The end of the whole chain: what the six say about themselves."""
        objects, _accumulator = self._create(self._bafu_noise_rows())

        for obj in objects:
            with self.subTest(label=obj.prefLabel[0]["@value"]):
                self.assertIsNone(obj.types)
                self.assertEqual(
                    obj.created_from["semantic_typing"]["reason"],
                    "non_material_intervention_not_a_chemical_entity",
                )


if __name__ == "__main__":
    unittest.main()
