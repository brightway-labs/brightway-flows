"""The merge reads both layers as records, and the conversions are lossless.

`_load_working_set` used to return `list[dict]` for both layers, and every
lookup in `merge/matching.py` read a substance through `.get()`. `AGENTS.md`
gives the reason that is wrong: attribute access makes a wrong field name raise
where it is written instead of returning `None`. In the transform stage that
costs a label; in the merge it costs a published identifier pointing at the
wrong substance, silently.

`merge/state.py` used to justify the dicts by saying the merge "reads
`elementary-flows.json` from disk, so it works at a file boundary". That
stopped being true when `_load_working_set` started reading the database. The
boundary went; the dicts stayed.

Four things are pinned here, because the conversion is only safe while all hold:

1. `_load_working_set` returns `FlowObject` and `ElementaryFlow` records.
2. `FlowObject.from_dict` is the exact inverse of what the transform stored.
   `flow_object_json` is written as `FlowObject.to_dict()`, so a key the record
   does not declare would be **dropped** on the way in and lost on the way out
   -- `FlowObject` has no `extra` bag, unlike `ElementaryFlow`. Verified against
   all 8,021 objects of the 2026-08-14 build before the conversion was made;
   this is that check in miniature, over an object carrying every optional
   field, so a new undeclared key on the writer's side fails here.
3. `ElementaryFlow.from_dict` loses no *content* from what
   `elementary_flow_record` projects. It does move key order, and that is the
   half of #93 worth stating on purpose rather than discovering: over all
   95,190 rows of the 2026-08-14 build the round trip returned the same keys
   with the same values, in a different order on 93,993 of them.
4. That reordering reaches no published byte, because nothing serialises the
   working list in the order it holds. The one column a merge-created flow
   reaches, `elementary_flows.flow_json`, is written through
   `_as_harmonised`, which rebuilds it as a `Flow`.
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

import orjson

from brightway_flows.domain.context_registry import context_for_iri
from brightway_flows.domain.elementary_flow import ElementaryFlow
from brightway_flows.domain.flow import Flow
from brightway_flows.domain.lcia.records import StatedFactor, stated_category
from brightway_flows.domain.flow_object import FlowObject
from brightway_flows.domain.vocabulary import (
    CHEMINF_CAS_REGISTRY_NUMBER,
    CHEMROF_MONOATOMIC_ION,
    RO_HAS_ROLE_IRI,
    SKOS_DEFINITION_IRI,
)
from brightway_flows.merge.datastores import _as_harmonised
from brightway_flows.merge.matching import _build_indexes, _load_working_set
from brightway_flows.pipeline.sqlite import elementary_flow_record

SCHEMA = """
CREATE TABLE flow_objects (
    flow_object_id TEXT PRIMARY KEY,
    flow_object_json TEXT
);
CREATE TABLE elementary_flows (
    elementary_flow_id TEXT PRIMARY KEY,
    flow_object_id TEXT,
    flow_json TEXT
);
CREATE TABLE flow_object_payloads (
    flow_object_id TEXT PRIMARY KEY,
    payload_json TEXT NOT NULL
);
"""


def _every_field_populated() -> FlowObject:
    """A flow object carrying every optional field, including the aliased ones.

    The aliased three are the ones a round-trip can lose quietly: they serialise
    under an IRI or under `@type`, so a `from_dict` that did not consult
    `_ALIASES` would drop them into nothing and `to_dict` would emit them as
    null.
    """
    return FlowObject(
        flow_object_id="fo-1",
        prefLabel=[{"@value": "Sodium ion", "@language": "en"}],
        altLabel=[{"@value": "Na+", "@language": "en"}],
        properties={"chemrof:molecular_formula": "Na+"},
        references=["https://pubchem.ncbi.nlm.nih.gov/compound/923"],
        created_from={"resolver": "hybrid_name_cas_v1"},
        classifications={CHEMINF_CAS_REGISTRY_NUMBER: {"@value": ["17341-25-2"]}},
        origin_qualifier="blue_water",
        parent_flow_object_id="fo-parent",
        parent_intervention_id="fo-family",
        skos_definition=[{"@value": "A monoatomic cation.", "@language": "en"}],
        types=[CHEMROF_MONOATOMIC_ION],
        roles=[{"@id": "http://purl.obolibrary.org/obo/CHEBI_33286"}],
    )


class TheConversionIsLosslessTestCase(unittest.TestCase):
    def test_every_declared_field_survives_a_round_trip(self):
        original = _every_field_populated()
        self.assertEqual(FlowObject.from_dict(original.to_dict()), original)

    def test_the_aliased_fields_survive_under_their_serialised_keys(self):
        payload = _every_field_populated().to_dict()
        # Named rather than derived from `_ALIASES`: this asserts what the
        # stored shape *is*, and reading it off the table under test would make
        # the assertion true by construction.
        for key in ("@type", SKOS_DEFINITION_IRI, RO_HAS_ROLE_IRI):
            with self.subTest(key=key):
                self.assertIn(key, payload)
        rebuilt = FlowObject.from_dict(payload)
        self.assertEqual(rebuilt.types, [CHEMROF_MONOATOMIC_ION])
        self.assertIsNotNone(rebuilt.skos_definition)
        self.assertEqual(len(rebuilt.roles or []), 1)

    def test_key_order_does_not_move(self):
        """The bytes matter: #293 is two builds of one revision differing."""
        payload = _every_field_populated().to_dict()
        self.assertEqual(
            list(FlowObject.from_dict(payload).to_dict()), list(payload)
        )

    def test_an_undeclared_key_is_dropped_rather_than_carried(self):
        """`FlowObject` has no `extra` bag, and this is what that costs.

        Stated as a test rather than left as a surprise: if the transform ever
        writes a key the record does not declare, it does not survive the merge
        reading it back. The fix would be an `_EXTRA_FIELD`, as
        `ElementaryFlow` has; the check is here so the choice is a decision.
        """
        payload = _every_field_populated().to_dict() | {"invented_key": 1}
        self.assertNotIn("invented_key", FlowObject.from_dict(payload).to_dict())


#: The water a release reaches when the list does not say which body.
WATER = "https://vocab.brightway.one/flow-contexts/envi-wate-unkn"


def _stored_flow() -> Flow:
    """One flow as the transform stores it in `flow_json`.

    Built through `Flow`, not hand-written, because that is what the column
    holds and it is what makes the projection below work: a hand-written row
    omitting `unit_iri` would fail the record and tell a reader that the merge
    cannot read the database, when what it cannot read is the fixture.
    """
    return Flow(
        uuid="ef-1",
        flow_object_id="fo-1",
        source="EF 3.1",
        context=context_for_iri(WATER),
        context_iri=WATER,
        unit="kg",
        unit_iri="http://qudt.org/vocab/unit/KiloGM",
        lcia_methods=[
            StatedFactor(
                category=stated_category(uuid="gwp", name="Climate change"),
                flow_uuid="ef-1",
                amount=1.0,
            )
        ],
    )


class TheElementaryConversionIsLosslessTestCase(unittest.TestCase):
    """#93: what the record keeps, and the one thing it moves."""

    def test_the_projected_record_round_trips_with_the_same_content(self):
        projected = elementary_flow_record(_stored_flow().to_dict())
        rebuilt = ElementaryFlow.from_dict(projected).to_dict()
        self.assertEqual(rebuilt, projected)

    def test_the_key_order_moves_and_this_is_where_it_is_said(self):
        """`elementary_flow_record` appends the three keys it defaults, so a
        base-list row comes out of the projection in an order the record does
        not share. 93,993 of the 2026-08-14 build's 95,190 rows move; what they
        move to is the declaration order, which is the order the merge's own
        created flows were already in."""
        projected = elementary_flow_record(_stored_flow().to_dict())
        rebuilt = ElementaryFlow.from_dict(projected).to_dict()
        self.assertNotEqual(list(rebuilt), list(projected))
        self.assertEqual(rebuilt.keys() ^ projected.keys(), set())
        self.assertEqual(list(rebuilt)[0], "elementary_flow_id")
        self.assertEqual(list(projected)[0], "flow_object_id")

    def test_the_column_a_created_flow_reaches_is_written_in_flow_order(self):
        """Which is why no published byte moves with it: `_as_harmonised`
        rebuilds the row as a `Flow`, so `flow_json` is in `Flow`'s order
        whatever order the working list was holding."""
        stored = _stored_flow()
        record = ElementaryFlow.from_dict(
            elementary_flow_record(stored.to_dict())
        )
        harmonised = _as_harmonised(record)
        self.assertEqual(
            list(harmonised)[:3], list(stored.to_dict())[:3]
        )
        self.assertEqual(harmonised["uuid"], "ef-1")

    def test_a_substance_key_the_record_does_not_declare_is_kept(self):
        """The merge's own created flows carry the substance body as well, and
        `ElementaryFlow` declares none of it. The passthrough bag is what makes
        the round trip lossless for those 1,197 rows rather than only for the
        93,993."""
        projected = elementary_flow_record(_stored_flow().to_dict()) | {
            "name": "Water", "cas_numbers": ["7732-18-5"],
        }
        rebuilt = ElementaryFlow.from_dict(projected)
        self.assertEqual(rebuilt.extra["name"], "Water")
        self.assertEqual(rebuilt.to_dict()["cas_numbers"], ["7732-18-5"])


class TheWorkingSetIsRecordsTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = Path(self._tmp.name) / "consensus-flows.sqlite3"
        conn = sqlite3.connect(self.db)
        conn.executescript(SCHEMA)
        conn.execute(
            "INSERT INTO flow_objects (flow_object_id, flow_object_json) VALUES (?, ?)",
            ("fo-1", orjson.dumps(_every_field_populated().to_dict()).decode()),
        )
        conn.execute(
            "INSERT INTO elementary_flows (elementary_flow_id, flow_object_id, flow_json) "
            "VALUES (?, ?, ?)",
            ("ef-1", "fo-1", orjson.dumps(_stored_flow().to_dict()).decode()),
        )
        conn.commit()
        conn.close()

    def test_flow_objects_come_back_as_records(self):
        flow_objects, elementary = _load_working_set(self.db)

        self.assertEqual([type(obj) for obj in flow_objects], [FlowObject])
        self.assertEqual(flow_objects[0].flow_object_id, "fo-1")
        self.assertEqual(flow_objects[0].origin_qualifier, "blue_water")

    def test_elementary_flows_come_back_as_records(self):
        _flow_objects, elementary = _load_working_set(self.db)

        self.assertEqual([type(row) for row in elementary], [ElementaryFlow])
        self.assertEqual(elementary[0].elementary_flow_id, "ef-1")
        self.assertEqual(elementary[0].flow_object_id, "fo-1")
        self.assertEqual(elementary[0].context_iri, WATER)
        # The context is the domain object, not the dict it was stored as: a
        # candidate is scored on it, so it is read like every other context.
        self.assertEqual(elementary[0].context, context_for_iri(WATER))

    def test_a_stored_row_the_record_cannot_represent_stops_the_read(self):
        """Rather than reaching the merge as a flow with fields missing. The
        one thing worse than a build that stops is a build that publishes an
        identifier pointing at the wrong place in the environment."""
        conn = sqlite3.connect(self.db)
        conn.execute(
            "INSERT INTO elementary_flows (elementary_flow_id, flow_object_id, flow_json) "
            "VALUES (?, ?, ?)",
            ("ef-2", "fo-1", orjson.dumps({"uuid": "ef-2"}).decode()),
        )
        conn.commit()
        conn.close()
        with self.assertRaises(TypeError):
            _load_working_set(self.db)

    def test_what_was_stored_is_what_comes_back(self):
        stored = _every_field_populated().to_dict()
        flow_objects, _elementary = _load_working_set(self.db)
        self.assertEqual(flow_objects[0].to_dict(), stored)

    def test_the_indexes_are_built_from_records(self):
        """`_build_indexes` reading `.get()` on a record returns nothing, and
        would do it silently -- the merge would match no row and report every
        one as unplaceable."""
        flow_objects, _elementary = _load_working_set(self.db)
        cas_index, _ec, label_index, pref_index = _build_indexes(flow_objects)

        self.assertEqual(cas_index["17341-25-2"], {"fo-1"})
        self.assertEqual(label_index["sodium ion"], {"fo-1"})
        self.assertEqual(pref_index["sodium ion"], {"fo-1"})
        # The alt label reaches the general index and not the prefLabel one.
        self.assertEqual(label_index["na+"], {"fo-1"})
        self.assertNotIn("na+", pref_index)


if __name__ == "__main__":
    unittest.main()
