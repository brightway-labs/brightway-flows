"""EF 3.1's two names for one renewable energy resource, collapsed to one flow.

EF 3.1 ships `Energy, geothermal, converted` and `primary energy from
geothermics` in the same category, in the same unit, and four such pairs in all.
Nothing on either row tells them apart -- no CAS, no synonym, no comment, no
characterisation factor -- so both survived the merge and the list published the
same resource twice under two names (#73).

Two curated files answer it, and neither works without the other: a merge group
in `flow-object-overrides.json` puts a pair on one flow object, which is the
only thing that can, since these flows carry no identifier any resolver could
group them by; a ruling in `elementary-flow-collision-decisions.json` then says
the two rows of that object in that context are one flow and names which one
survives.

These are the shipped files applied to the nine flows EF publishes, rather than
a fixture that would go on passing if a row were edited out.  The fifth flow,
`primary energy from waves`, is here for the case the rules must *not* catch: it
is the only wave energy entry any list has, so it duplicates nothing.
"""

import unittest

from brightway_flows.domain.flow import Flow
from brightway_flows.flow_layers import resolve_flow_layers
from brightway_flows.flow_layers.layering import (
    _load_overrides,
    _merge_group_labels,
    _uuid_overrides,
)
from brightway_flows.pipeline.collision_decisions import (
    apply_collision_rulings,
    load_collision_rulings,
)
from brightway_flows.pipeline.collisions import find_collisions
from brightway_flows.pipeline.deduplication import (
    _apply_elementary_duplicate_deprecations,
)
from brightway_flows.sources import base_source_list

BASE = base_source_list()

RESO_AIR = "https://vocab.brightway.one/flow-contexts/reso-air"
RESO_GROUND = "https://vocab.brightway.one/flow-contexts/reso-grou"
RESO_WATER = "https://vocab.brightway.one/flow-contexts/reso-wate"

#: The four pairs, as `(flow object, context, surviving uuid and name, legacy
#: uuid and name)`.  EF's own spellings are lower case; by the time the layering
#: sees them `normalize_name_case` has title-cased them, which is the form the
#: overrides state and the form these rows carry.
PAIRS = [
    (
        "fo-c4f4bb8d95c22ef6",
        RESO_GROUND,
        ("c0060563-96ea-4322-8305-61c39f2ad3cd", "Energy, Geothermal, Converted"),
        ("04202046-6556-11dd-ad8b-0800200c9a66", "Primary Energy From Geothermics"),
    ),
    (
        "fo-bc635179bc43bfc7",
        RESO_AIR,
        ("1c80d3da-b8c4-4275-a552-c96a709a11dd", "Energy, Solar, Converted"),
        ("04202048-6556-11dd-ad8b-0800200c9a66", "Primary Energy From Solar Energy"),
    ),
    (
        "fo-70259b1e9c786701",
        RESO_AIR,
        ("0ab82f67-9e7e-417a-8de8-9801226a436f", "Energy, Kinetic (in Wind), Converted"),
        ("0420204a-6556-11dd-ad8b-0800200c9a66", "Primary Energy From Wind Power"),
    ),
    (
        "fo-98218e5a3fcea37f",
        RESO_WATER,
        (
            "e89f564c-7250-4fee-b759-dc8b42fe62bf",
            "Energy, Potential (in Hydropower Reservoir), Converted",
        ),
        ("04202047-6556-11dd-ad8b-0800200c9a66", "Primary Energy From Hydro Power"),
    ),
]

WAVES = ("04202049-6556-11dd-ad8b-0800200c9a66", "Primary Energy From Waves")

#: EF's category for each context, kept because it is what the flows carry and
#: what a reader checking these rows against the source archive would look for.
CATEGORY = {
    RESO_AIR: ["Resources", "Resources from air", "Renewable energy resources from air"],
    RESO_GROUND: [
        "Resources",
        "Resources from ground",
        "Renewable energy resources from ground",
    ],
    RESO_WATER: [
        "Resources",
        "Resources from water",
        "Renewable energy resources from water",
    ],
}


def _flow(uuid: str, name: str, context_iri: str) -> Flow:
    """One EF row as it reaches the layering: named, in MJ, uncharacterised."""
    return Flow.from_dict({
        "uuid": uuid,
        "name": name,
        "prefLabel": [{"@value": name, "@language": "en"}],
        "source": "EF 3.1",
        "unit": "MJ",
        "context": CATEGORY[context_iri],
        "context_iri": context_iri,
        "lcia_methods": [],
    })


def _the_nine_flows() -> list[Flow]:
    rows = []
    for _, context_iri, survivor, legacy in PAIRS:
        rows.append(_flow(survivor[0], survivor[1], context_iri))
        rows.append(_flow(legacy[0], legacy[1], context_iri))
    rows.append(_flow(WAVES[0], WAVES[1], RESO_WATER))
    return rows


def _labels(rows) -> list[str]:
    return [str(row.get("@value") or "") for row in rows or []]


class TheMergeGroupsTestCase(unittest.TestCase):
    """What the layering does with the shipped overrides."""

    def setUp(self):
        self.objects, self.elementary, self.stats = resolve_flow_layers(
            _the_nine_flows(), source_list=BASE
        )
        self.by_id = {obj.flow_object_id: obj for obj in self.objects}
        self.object_of = {
            row.elementary_flow_id: row.flow_object_id for row in self.elementary
        }

    def test_each_pair_lands_on_one_flow_object(self):
        for flow_object_id, _, survivor, legacy in PAIRS:
            with self.subTest(flow_object_id):
                self.assertEqual(self.object_of[survivor[0]], flow_object_id)
                self.assertEqual(self.object_of[legacy[0]], flow_object_id)

    def test_the_object_is_named_by_the_name_the_other_lists_use(self):
        """Not by the length rule, which would have kept `Primary Energy From
        Geothermics` and `Primary Energy From Solar Energy` -- both longer than
        the `converted` name they would have replaced."""
        for flow_object_id, _, survivor, _legacy in PAIRS:
            with self.subTest(flow_object_id):
                self.assertEqual(
                    _labels(self.by_id[flow_object_id].prefLabel), [survivor[1]]
                )

    def test_the_legacy_name_stays_on_the_object_as_an_alternative(self):
        for flow_object_id, _, _survivor, legacy in PAIRS:
            with self.subTest(flow_object_id):
                self.assertIn(
                    legacy[1], _labels(self.by_id[flow_object_id].altLabel)
                )

    def test_the_object_ids_are_the_ones_the_surviving_name_already_mints(self):
        """A merge group pins an id, so it can move one.  These name the id the
        `converted` flow was already published under, which is why nothing that
        resolves by name has to change."""
        for flow_object_id, context_iri, survivor, _legacy in PAIRS:
            with self.subTest(flow_object_id):
                without_the_legacy_row, _, _ = resolve_flow_layers(
                    [_flow(survivor[0], survivor[1], context_iri)], source_list=BASE
                )
                self.assertEqual(
                    without_the_legacy_row[0].flow_object_id, flow_object_id
                )

    def test_waves_keeps_its_own_flow_object(self):
        self.assertNotIn(WAVES[0], _uuid_overrides(_load_overrides()))
        waves_object_id = self.object_of[WAVES[0]]
        self.assertNotIn(waves_object_id, {pair[0] for pair in PAIRS})
        self.assertEqual(
            [row.elementary_flow_id
             for row in self.elementary
             if row.flow_object_id == waves_object_id],
            [WAVES[0]],
        )
        self.assertEqual(
            _labels(self.by_id[waves_object_id].prefLabel), [WAVES[1]]
        )

    def test_the_nine_flows_become_five_objects(self):
        self.assertEqual(self.stats["flow_object_count"], 5)
        self.assertEqual(self.stats["elementary_flow_count"], 9)


class TheRulingsTestCase(unittest.TestCase):
    """What the shipped rulings then do with the two rows on one object."""

    def setUp(self):
        self.flows = _the_nine_flows()
        _objects, self.elementary, _stats = resolve_flow_layers(
            self.flows, source_list=BASE
        )
        self.counts = apply_collision_rulings(
            flows=self.flows,
            elementary_flows=self.elementary,
            rulings=load_collision_rulings(),
        )
        self.payloads = {
            row.elementary_flow_id: row.to_dict() for row in self.elementary
        }

    def test_the_legacy_row_is_deprecated_onto_the_surviving_one(self):
        for _, _, survivor, legacy in PAIRS:
            with self.subTest(legacy[0]):
                payload = self.payloads[legacy[0]]
                self.assertTrue(payload["http://www.w3.org/2002/07/owl#deprecated"])
                self.assertEqual(payload["is_replaced_by_uuid"], survivor[0])

    def test_the_surviving_row_stays_live(self):
        for _, _, survivor, _legacy in PAIRS:
            with self.subTest(survivor[0]):
                self.assertNotIn(
                    "http://www.w3.org/2002/07/owl#deprecated",
                    self.payloads[survivor[0]],
                )

    def test_four_rulings_apply_and_nothing_else_moves(self):
        self.assertEqual(self.counts["collision_rulings_applied"], 4)
        self.assertEqual(self.counts["collision_ruling_flows_deprecated"], 4)

    def test_no_collision_is_left(self):
        self.assertEqual(find_collisions(self.elementary), [])

    def test_the_deduplication_pass_that_runs_next_leaves_the_ruling_alone(self):
        """The order the transform runs these in, because the two disagree
        about these pairs and the ruling has to win.  Nothing the signature
        reads tells the two rows apart -- no factors, and the names are on the
        object they now share -- so deduplication would rank them by identifier
        and deprecate each survivor back onto the legacy row it just replaced.
        """
        stats = _apply_elementary_duplicate_deprecations(
            flows=self.flows, elementary_flows=self.elementary
        )
        self.assertEqual(stats["deprecated_elementary_flow_count"], 0)
        live = {
            row.elementary_flow_id
            for row in self.elementary
            if not row.owl_deprecated
        }
        self.assertEqual(
            live, {survivor[0] for _, _, survivor, _legacy in PAIRS} | {WAVES[0]}
        )

    def test_waves_is_ruled_on_by_nothing(self):
        payload = self.payloads[WAVES[0]]
        self.assertNotIn("http://www.w3.org/2002/07/owl#deprecated", payload)
        for ruling in load_collision_rulings().values():
            self.assertNotIn(WAVES[0], ruling.members)


class TheTwoFilesAgreeTestCase(unittest.TestCase):
    """A ruling names flows; a merge group names the object they share. If the
    two disagree the ruling silently applies to nothing -- `collision_rulings`
    is keyed on the object, so a ruling for an object the flows are not on is
    counted absent and no build fails."""

    def setUp(self):
        self.overrides = _load_overrides()
        self.groups = {
            group.flow_object_id: set(group.source_uuids)
            for group in self.overrides.merge_groups
        }
        self.rulings = load_collision_rulings()

    def test_every_energy_ruling_names_flows_its_merge_group_holds(self):
        for flow_object_id, context_iri, survivor, legacy in PAIRS:
            with self.subTest(flow_object_id):
                ruling = self.rulings[(flow_object_id, context_iri, "MJ")]
                self.assertEqual(ruling.survivor, survivor[0])
                self.assertEqual(ruling.merged, (legacy[0],))
                self.assertEqual(self.groups[flow_object_id], set(ruling.members))

    def test_every_merge_group_states_the_label_its_object_takes(self):
        """Without one the length rule decides, and a group is written exactly
        because the names disagree."""
        labels = _merge_group_labels(self.overrides)
        for flow_object_id in self.groups:
            with self.subTest(flow_object_id):
                self.assertTrue(labels.get(flow_object_id))


if __name__ == "__main__":
    unittest.main()
