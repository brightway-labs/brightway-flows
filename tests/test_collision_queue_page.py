"""The collision queue's page: a group, read rather than listed.

`elementary-flow-collision` had 116 items and no page (#61).  It could not be
reached at all -- the index lists registered queues and an unregistered name is
a deliberate 404 -- so the groups #44, #279 and #281 rule on were read out of
SQLite by hand.

What is pinned here:

- **Every queue in `review_queue` has a page.**  The regression #61 is: a
  queue was added and the page was not, and nothing said so.
- **A group renders its flows, with what each carries.**  Two identifiers in a
  cell is what the shared template would have produced.
- **The flow deduplication would keep is marked.**  Not rendered while the
  payload named the lowest identifier, which is not how deduplication chooses
  and named the flow that would be dropped on 27 of the 116 groups; #58 made
  the payload carry deduplication's own ranking, and the old key is not read as
  a fallback.
- **What holds the flows apart is marked, and it is what the signature reads.**
  A name differs on most groups and holds nothing apart -- that is #31, where
  two flows separated by a name alone were collapsed anyway.
- **One query for the page's flows**, not one per group.
"""

import tempfile
import unittest
from pathlib import Path

from brightway_flows.domain.elementary_flow import ElementaryFlow
from brightway_flows.domain.flow import Flow, ProvidedValues
from brightway_flows.domain.flow_object import FlowObject
from brightway_flows.pipeline.deduplication import (
    SIGNATURE_EXCLUDED_KEYS,
    _elementary_duplicate_signature,
)
from brightway_flows.pipeline.review_records import (
    PipelineRun,
    ReviewQueue,
    ReviewQueueItem,
    Severity,
)
from brightway_flows.domain.context_registry import context_from_dict
from brightway_flows.pipeline.review_tables import (
    REVIEW_SCHEMA_VERSION,
    write_review_tables,
)
from brightway_flows.pipeline.sqlite import _write_consensus_sqlite
from brightway_flows.webapps.app import create_app, db
from brightway_flows.webapps.app.queries import collisions as collision_queries
from brightway_flows.webapps.app.queries import queue as queue_queries

CONTEXT = context_from_dict(
    {"dimension": "Environmental", "media": "Air", "strata": "Unknown"}
)
CONTEXT_IRI = "https://vocab.brightway.one/flow-contexts/envi-air"

#: Two live flows of one substance, in one context, in one unit.  They differ
#: in three ways, and only one of them is a field the duplicate signature
#: reads:
#:
#: * `general_comment` -- read, and so the whole of what keeps them two;
#: * `prefLabel` -- not read: the shape of #31;
#: * `ec_numbers` -- not read either, and carried by one of them only.
#:
#: One holds both characterisation factors and the other holds none, which is
#: the case #279 rules on and the one the payload's survivor field gets wrong.
FACTORS = [
    {"method_uuid": "m-1", "name": "Climate change", "characterization_factor": 1.0},
    {"method_uuid": "m-2", "name": "Climate change-Fossil",
     "characterization_factor": 1.0},
]


def _flow(uuid: str, *, label: str, comment: str, factors: list, **fields) -> Flow:
    return Flow(
        uuid=uuid,
        identifier=uuid,
        flow_object_id="fo-water",
        source="EF 3.1",
        unit="kg",
        context=CONTEXT,
        context_iri=CONTEXT_IRI,
        lcia_methods=factors,
        general_comment=comment,
        prefLabel=[{"@value": label, "@language": "en"}],
        provided=ProvidedValues(
            name=label.lower(), synonyms=[], context=CONTEXT,
            cas_numbers=[], ec_numbers=[], unit="kg",
        ),
        **fields,
    )


FLOWS = [
    _flow("u-1", label="Water to cooling", comment="", factors=list(FACTORS)),
    _flow("u-2", label="Water to turbine", comment="EF 3.1 note", factors=[],
          ec_numbers=["231-791-2"]),
]

ITEM = ReviewQueueItem(
    queue_name=ReviewQueue.ELEMENTARY_FLOW_COLLISION,
    item_key=f"fo-water|{CONTEXT_IRI}|kg",
    title="2 live flows share Water in one context and unit",
    severity=Severity.INFO,
    flow_object_id="fo-water",
    item_index=0,
    payload={
        "flow_object_id": "fo-water",
        "context_iri": CONTEXT_IRI,
        "unit": "kg",
        "elementary_flow_ids": ["u-1", "u-2"],
        "lcia_factor_counts": {"u-1": 2, "u-2": 0},
        "deduplication_would_keep": "u-1",
    },
)


def _write_fixture(path: Path, *, flows=FLOWS, items=(ITEM,)):
    import brightway_flows.pipeline.sqlite as sqlite_module

    flow_objects = [FlowObject(
        flow_object_id="fo-water",
        prefLabel=[{"@value": "Water"}],
        altLabel=[], classifications={}, properties={}, references=[],
        created_from={},
    )]
    elementary = [
        ElementaryFlow(
            elementary_flow_id=flow.uuid, flow_object_id="fo-water",
            source="EF 3.1", context=CONTEXT, context_iri=CONTEXT_IRI,
            unit="kg", unit_iri="", lcia_methods=flow.lcia_methods,
            general_comment=flow.general_comment, source_refs=[],
        )
        for flow in flows
    ]

    original = sqlite_module.CONSENSUS_DB_FILEPATH
    sqlite_module.CONSENSUS_DB_FILEPATH = path
    try:
        _write_consensus_sqlite(flows, [], flow_objects, elementary)
    finally:
        sqlite_module.CONSENSUS_DB_FILEPATH = original

    write_review_tables(
        path,
        run=PipelineRun(run_id="run-1", timestamp="2026-08-13T00:00:00+00:00",
                        schema_version=REVIEW_SCHEMA_VERSION),
        stats=[],
        changes=[],
        queue_items=list(items),
        formula_mismatches=[],
        element_coverage=[],
        context_mappings=[],
    )


class CollisionPageTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "consensus-flows.sqlite3"
        _write_fixture(self.path)

    def connection(self):
        connection = db.connect(self.path)
        self.addCleanup(connection.close)
        return connection

    def client(self):
        app = create_app(self.path)
        app.config["TESTING"] = True
        return app.test_client()

    def groups(self, **kwargs):
        connection = self.connection()
        return collision_queries.groups(
            connection,
            queue_queries.items(connection, queue_queries.COLLISIONS, **kwargs),
        )

    def field(self, group, label):
        for entry in group.fields:
            if entry.label == label:
                return entry
        return None

    def test_every_queue_in_the_table_has_a_page(self):
        """The regression #61 is: a queue was added and the page was not.

        Not "the collision queue has a page" -- that is one instance of it.
        """
        registered = {definition.name for definition in queue_queries.DEFINITIONS}
        self.assertEqual(
            sorted(str(name) for name in ReviewQueue if str(name) not in registered),
            [],
        )

    def test_the_page_is_reachable_and_listed(self):
        client = self.client()
        self.assertEqual(
            client.get(f"/queue/{queue_queries.COLLISIONS}").status_code, 200
        )
        index = client.get("/queue/").get_data(as_text=True)
        self.assertIn(f"/queue/{queue_queries.COLLISIONS}", index)

    def test_a_group_renders_its_flows_and_what_each_carries(self):
        body = self.client().get(
            f"/queue/{queue_queries.COLLISIONS}"
        ).get_data(as_text=True)
        for uuid in ("u-1", "u-2"):
            self.assertIn(f"/flows/{uuid}", body)
        # The names the source list shipped, and the factors each flow holds --
        # the pair the survivor field got backwards.
        self.assertIn("water to cooling", body)
        self.assertIn("water to turbine", body)
        self.assertIn("EF 3.1 note", body)

    def test_the_flow_deduplication_would_keep_is_marked(self):
        """Withheld while the payload computed it from the lowest identifier,
        which named the flow that would be *dropped* on 27 of 116 groups. #58
        made it deduplication's own ranking, so the page shows it."""
        group = self.groups().rows[0]
        self.assertEqual(
            {flow.uuid: flow.would_be_kept for flow in group.flows},
            {"u-1": True, "u-2": False},
        )
        body = self.client().get(
            f"/queue/{queue_queries.COLLISIONS}"
        ).get_data(as_text=True)
        self.assertIn("would be kept", body)

    def test_the_old_survivor_key_is_not_read(self):
        """A payload written by an older run carries `would_survive_
        deduplication`, whose value is the wrong flow. Reading it as a fallback
        would put #58's defect back on the page for exactly the builds it was
        wrong on."""
        item = ReviewQueueItem(
            queue_name=ReviewQueue.ELEMENTARY_FLOW_COLLISION,
            item_key=ITEM.item_key,
            title=ITEM.title,
            severity=Severity.INFO,
            flow_object_id="fo-water",
            item_index=0,
            payload={
                **{k: v for k, v in ITEM.payload.items() if k != "deduplication_would_keep"},
                "would_survive_deduplication": "u-2",
            },
        )
        path = Path(self._tmp.name) / "older-payload.sqlite3"
        _write_fixture(path, items=(item,))
        connection = db.connect(path)
        self.addCleanup(connection.close)
        group = collision_queries.groups(
            connection,
            queue_queries.items(connection, queue_queries.COLLISIONS),
        ).rows[0]
        self.assertEqual([flow.would_be_kept for flow in group.flows], [False, False])

    def test_the_factors_are_read_per_flow(self):
        group = self.groups().rows[0]
        self.assertEqual(
            {flow.uuid: flow.lcia_factor_count for flow in group.flows},
            {"u-1": 2, "u-2": 0},
        )

    def test_only_a_field_the_signature_reads_holds_the_flows_apart(self):
        """A name differs and holds nothing apart. That is #31 exactly."""
        group = self.groups().rows[0]
        self.assertEqual(
            [entry.key for entry in group.holding_apart], ["general_comment"]
        )
        self.assertIsNotNone(self.field(group, "Preferred label"))
        self.assertFalse(self.field(group, "Preferred label").holds_apart)
        self.assertFalse(self.field(group, "EC numbers").holds_apart)

    def test_a_field_carries_each_flows_value_in_the_groups_order(self):
        group = self.groups().rows[0]
        labels = [entry.label for entry in group.fields]
        self.assertEqual(
            [flow.values[labels.index("Preferred label")] for flow in group.flows],
            ["Water to cooling", "Water to turbine"],
        )
        self.assertEqual(
            [flow.values[labels.index("EC numbers")] for flow in group.flows],
            ["", "231-791-2"],
        )

    def test_a_label_renders_as_the_name_not_as_its_provenance(self):
        """A `prefLabel` as stored is several hundred characters of JSON, and
        the reader is comparing two names."""
        group = self.groups().rows[0]
        index = [entry.label for entry in group.fields].index("Preferred label")
        self.assertNotIn("@value", group.flows[0].values[index])

    def test_a_difference_the_page_cannot_show_is_not_a_column(self):
        """Two labels with one name between them and two provenances differ in
        the record and render as two identical cells."""
        flows = [
            _flow("u-1", label="Water", comment="", factors=list(FACTORS)),
            _flow("u-2", label="Water", comment="EF 3.1 note", factors=[]),
        ]
        flows[1].prefLabel[0]["source"] = {"prov:wasGeneratedBy": "bootstrap_labels"}
        path = Path(self._tmp.name) / "invisible.sqlite3"
        _write_fixture(path, flows=flows)

        connection = db.connect(path)
        self.addCleanup(connection.close)
        group = collision_queries.groups(
            connection,
            queue_queries.items(connection, queue_queries.COLLISIONS),
        ).rows[0]
        self.assertEqual(
            [entry.key for entry in group.fields], ["general_comment"]
        )

    def test_an_invisible_difference_the_signature_reads_is_marked_as_one(self):
        """The exception to the rule above.

        A merge-created flow carries its labels on the record itself, so the
        signature does read them, and two of them holding one name under two
        provenances are what keeps the flows apart while rendering as two
        identical cells.  Dropping that column would leave the group saying it
        is held apart by a field it does not show.
        """
        flows = [
            _flow("u-1", label="Water", comment="", factors=list(FACTORS),
                  name="water to cooling"),
            _flow("u-2", label="Water", comment="", factors=[],
                  name="water to turbine"),
        ]
        flows[1].prefLabel[0]["source"] = {"prov:wasGeneratedBy": "ecoinvent_merge"}
        path = Path(self._tmp.name) / "merge-created.sqlite3"
        _write_fixture(path, flows=flows)

        connection = db.connect(path)
        self.addCleanup(connection.close)
        group = collision_queries.groups(
            connection,
            queue_queries.items(connection, queue_queries.COLLISIONS),
        ).rows[0]
        label = self.field(group, "Preferred label")
        self.assertTrue(label.holds_apart)
        self.assertTrue(label.same_text)
        self.assertEqual(
            [entry.key for entry in group.holding_apart], ["name", "prefLabel"]
        )

        app = create_app(path)
        app.config["TESTING"] = True
        body = app.test_client().get(
            f"/queue/{queue_queries.COLLISIONS}"
        ).get_data(as_text=True)
        self.assertIn("same text, different record", body)

    def test_overlapping_lists_show_what_each_flow_does_not_share(self):
        """Two alternative-label lists of forty entries differing in one are
        two identical cells, both cut off at the width of the column."""
        shared = [f"synonym {number}" for number in range(20)]
        flows = [
            _flow("u-1", label="Water", comment="", factors=list(FACTORS),
                  altLabel=[{"@value": value} for value in [*shared, "only here"]]),
            _flow("u-2", label="Water", comment="EF 3.1 note", factors=[],
                  altLabel=[{"@value": value} for value in shared]),
        ]
        path = Path(self._tmp.name) / "overlapping.sqlite3"
        _write_fixture(path, flows=flows)

        connection = db.connect(path)
        self.addCleanup(connection.close)
        group = collision_queries.groups(
            connection,
            queue_queries.items(connection, queue_queries.COLLISIONS),
        ).rows[0]
        index = [entry.key for entry in group.fields].index("altLabel")
        self.assertTrue(group.fields[index].differences_only)
        self.assertEqual(
            [flow.values[index] for flow in group.flows], ["only here", ""]
        )

    def test_a_group_the_signature_would_have_collapsed_says_so(self):
        """Nothing it reads separates them: a blank cell would read as "no
        problem here", which is the opposite of what it means."""
        flows = [
            _flow("u-1", label="Water to cooling", comment="", factors=list(FACTORS)),
            _flow("u-2", label="Water to turbine", comment="", factors=[]),
        ]
        path = Path(self._tmp.name) / "collapsible.sqlite3"
        _write_fixture(path, flows=flows)

        app = create_app(path)
        app.config["TESTING"] = True
        body = app.test_client().get(
            f"/queue/{queue_queries.COLLISIONS}"
        ).get_data(as_text=True)
        self.assertIn("nothing deduplication compares", body)

    def test_an_identifier_with_no_flow_is_reported_not_raised(self):
        """A database rebuilt under a newer run than the queue was written by."""
        item = ReviewQueueItem(
            queue_name=ReviewQueue.ELEMENTARY_FLOW_COLLISION,
            item_key=ITEM.item_key, title=ITEM.title, severity=Severity.INFO,
            flow_object_id="fo-water", item_index=0,
            payload=dict(ITEM.payload, elementary_flow_ids=["u-1", "u-gone"]),
        )
        path = Path(self._tmp.name) / "stale.sqlite3"
        _write_fixture(path, items=(item,))

        connection = db.connect(path)
        self.addCleanup(connection.close)
        group = collision_queries.groups(
            connection,
            queue_queries.items(connection, queue_queries.COLLISIONS),
        ).rows[0]
        self.assertEqual([flow.uuid for flow in group.flows], ["u-1"])
        self.assertEqual(group.missing, ["u-gone"])

    def test_the_page_reads_its_flows_in_one_query(self):
        """Not one per group: the page shows fifty of them."""
        connection = self.connection()
        page = queue_queries.items(connection, queue_queries.COLLISIONS)
        seen: list[str] = []
        connection.set_trace_callback(seen.append)
        collision_queries.groups(connection, page)
        connection.set_trace_callback(None)
        self.assertEqual(
            len([statement for statement in seen if "elementary_flows" in statement]),
            1,
        )

    def test_the_queue_pages_and_searches_like_every_other(self):
        """The route, the paging and the search are the shared ones; only the
        rendering differs."""
        self.assertEqual(self.groups().total, 1)
        self.assertEqual(self.groups(query="water").total, 1)
        self.assertEqual(self.groups(query="chlorine").total, 0)
        self.assertEqual(
            self.groups(severity=str(Severity.BLOCKING)).total, 0
        )


class SignatureKeysTestCase(unittest.TestCase):
    """The page says what deduplication compares by importing the rule."""

    def test_the_signature_excludes_the_keys_the_page_reads_it_by(self):
        rows = [
            ElementaryFlow(
                elementary_flow_id=uuid, flow_object_id="fo-water", source="EF 3.1",
                context=CONTEXT, context_iri=CONTEXT_IRI,
                unit="kg",
                unit_iri="", lcia_methods=methods, general_comment=None,
            )
            for uuid, methods in (("u-1", list(FACTORS)), ("u-2", []))
        ]
        self.assertEqual(
            _elementary_duplicate_signature(rows[0]),
            _elementary_duplicate_signature(rows[1]),
            "the identifier and the factors are excluded, so these are one flow",
        )
        self.assertIn("lcia_methods", SIGNATURE_EXCLUDED_KEYS)
        self.assertNotIn("general_comment", SIGNATURE_EXCLUDED_KEYS)


if __name__ == "__main__":
    unittest.main()
