"""Phase 3: the change log, the decision queues, and the context mappings.

The three of these depend on tables Phase 0 wrote, and each replaces a page that
read a JSON file the pipeline had stopped writing or wrote only behind a flag.

What is pinned beyond "it renders":

- **A detail page reads no history.** The whole point of the on-demand split,
  and only true if nothing queries for it. Asserted by watching the statements.
- **The fragment and the standalone page are the same content.** They share a
  template, so the `<details>` a reader expands and the page they land on with
  JavaScript off cannot drift apart.
- **`changelog` answers by substance without a join.** The reason it replaces
  `consensus_changes`, which has only the flow uuid.
- **Thirteen queues, one shape.** Adding one is a definition and a column list.
  The fourteenth, `elementary-flow-collision`, renders a group rather than a
  row and so brings its own template; `tests/test_collision_queue_page.py` is
  where that one is pinned.
- **An unknown queue name is a 404.** A typo that renders "nothing to do" is
  worse than one that says the page does not exist.
"""

import re
import sqlite3
import tempfile
import unittest
from pathlib import Path

from brightway_flows.pipeline.review_records import (
    ChangeEvent,
    ContextDefaultMapping,
    ElementCoverage,
    ElementStatus,
    PipelineRun,
    ReviewQueue,
    ReviewQueueItem,
    Severity,
)
from brightway_flows.pipeline.review_tables import (
    REVIEW_SCHEMA_VERSION,
    number_change_events,
    write_review_tables,
)
from brightway_flows.pipeline.sqlite import _write_consensus_sqlite
from brightway_flows.webapps.app import create_app, db
from brightway_flows.webapps.app.queries import changes as change_queries
from brightway_flows.webapps.app.queries import contexts as context_queries
from brightway_flows.domain.context_registry import context_from_dict
from brightway_flows.domain.elementary_flow import ElementaryFlow
from brightway_flows.domain.flow import Flow
from brightway_flows.domain.flow_object import FlowObject
from brightway_flows.webapps.app.queries import flows as flow_queries
from brightway_flows.webapps.app.queries import queue as queue_queries

CHANGES = [
    ChangeEvent(uuid="u-1", field_name="unit", old_value="g", new_value="kg",
                transformer="unit_normalization", flow_name="Carbon dioxide",
                comment="normalised"),
    ChangeEvent(uuid="u-1", field_name="cas_numbers", old_value=[],
                new_value=["124-38-9"], transformer="consensus_match",
                flow_name="Carbon dioxide", comment="from the sources"),
    ChangeEvent(uuid="u-2", field_name="unit", old_value="g", new_value="kg",
                transformer="unit_normalization", flow_name="Methane"),
]


def _write_fixture(path: Path, *, changes=CHANGES, queues=(), elements=(),
                   mappings=()):
    import brightway_flows.pipeline.sqlite as sqlite_module

    # Air of unstated height.  `Air` alone is not a context the vocabulary
    # accepts: the medium requires a vertical stratum or an indoor air class.
    context = context_from_dict(
        {"dimension": "Environmental", "media": "Air", "strata": "Unknown"}
    )
    flows = [
        Flow(uuid="u-1", source="EF 3.1", unit="kg",
             prefLabel=[{"@value": "Carbon dioxide", "@language": "en"}],
             context=context),
        Flow(uuid="u-2", source="EF 3.1", unit="kg",
             prefLabel=[{"@value": "Methane", "@language": "en"}],
             context=context),
    ]
    flow_objects = [
        FlowObject(flow_object_id="fo-co2", prefLabel=[{"@value": "Carbon dioxide"}],
                   altLabel=[], classifications={}, properties={}, references=[],
                   created_from={}),
        FlowObject(flow_object_id="fo-ch4", prefLabel=[{"@value": "Methane"}],
                   altLabel=[], classifications={}, properties={}, references=[],
                   created_from={}),
    ]
    elementary = [
        ElementaryFlow(elementary_flow_id="u-1", flow_object_id="fo-co2", unit="kg",
                       unit_iri="", source="EF 3.1", context=context,
                       context_iri="", lcia_methods=[], general_comment=None,
                       source_refs=[]),
        ElementaryFlow(elementary_flow_id="u-2", flow_object_id="fo-ch4", unit="kg",
                       unit_iri="", source="EF 3.1", context=context,
                       context_iri="", lcia_methods=[], general_comment=None,
                       source_refs=[]),
    ]

    numbered = number_change_events(
        [
            ChangeEvent(
                uuid=c.uuid, field_name=c.field_name, old_value=c.old_value,
                new_value=c.new_value, transformer=c.transformer,
                flow_name=c.flow_name, comment=c.comment,
            )
            for c in changes
        ],
        flow_object_id_by_uuid={"u-1": "fo-co2", "u-2": "fo-ch4"},
    )

    original = sqlite_module.CONSENSUS_DB_FILEPATH
    sqlite_module.CONSENSUS_DB_FILEPATH = path
    try:
        _write_consensus_sqlite(flows, numbered, flow_objects, elementary)
    finally:
        sqlite_module.CONSENSUS_DB_FILEPATH = original

    write_review_tables(
        path,
        run=PipelineRun(run_id="run-1", timestamp="2026-08-06T00:00:00+00:00",
                        schema_version=REVIEW_SCHEMA_VERSION),
        stats=[],
        changes=numbered,
        queue_items=list(queues),
        formula_mismatches=[],
        element_coverage=list(elements),
        context_mappings=list(mappings),
    )


class Phase3TestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "consensus-flows.sqlite3"
        _write_fixture(
            self.path,
            queues=[
                ReviewQueueItem(queue_name=ReviewQueue.EC_MALFORMED,
                                item_key="u-1:200-000-0", item_index=1,
                                severity=Severity.BLOCKING, uuid="u-1",
                                title="Carbon dioxide",
                                payload={"flow_name": "Carbon dioxide",
                                         "ec": "200-000-0"}),
                ReviewQueueItem(queue_name=ReviewQueue.EC_CROSS_CHECK,
                                item_key="u-2:cas_ec_mismatch:200-812-7",
                                item_index=1, severity=Severity.REVIEW,
                                uuid="u-2", title="Methane",
                                payload={"flow_name": "Methane",
                                         "type": "cas_ec_mismatch",
                                         "inventory_ec": "200-812-7",
                                         "pubchem_confirmed": True}),
            ],
            elements=[
                ElementCoverage(atomic_number=1, symbol="H", name="Hydrogen",
                                status=ElementStatus.LINKED,
                                flow_object_id="fo-h"),
                ElementCoverage(atomic_number=118, symbol="Og",
                                name="Oganesson", status=ElementStatus.MISSING),
            ],
            mappings=[
                ContextDefaultMapping(
                    source="ecoinvent-3.12",
                    source_context=["air", "low population density, long-term"],
                    context_iri="https://vocab.brightway.one/flow-contexts/envi-air",
                    context_display="Environmental → Air",
                    comment="Temporal differentiation is done by LCIA.",
                ),
            ],
        )

    def connection(self):
        connection = db.connect(self.path)
        self.addCleanup(connection.close)
        return connection

    def client(self):
        app = create_app(self.path)
        app.config["TESTING"] = True
        return app.test_client()


class ChangeLogTestCase(Phase3TestCase):
    def test_the_log_covers_every_transformer(self):
        """`consensus_changes` covers one; this is why it is replaced."""
        page = change_queries.change_page(self.connection())
        self.assertEqual(page.total, 3)
        self.assertEqual(
            {row.transformer for row in page.rows},
            {"unit_normalization", "consensus_match"},
        )

    def test_the_log_filters_by_transformer_and_field(self):
        connection = self.connection()
        self.assertEqual(
            change_queries.change_page(connection, transformer="consensus_match").total, 1
        )
        self.assertEqual(
            change_queries.change_page(connection, field_name="unit").total, 2
        )

    def test_the_log_searches_values_and_comments(self):
        page = change_queries.change_page(self.connection(), query="normalised")
        self.assertEqual([row.field_name for row in page.rows], ["unit"])

    def test_history_is_reachable_by_substance_without_a_join(self):
        """The reason `changelog` is keyed by `flow_object_id`.

        The flows an edit landed on come from `changelog_flows`, which is the
        join the substance page does *not* have to do.
        """
        history = change_queries.substance_history(self.connection(), "fo-co2")
        self.assertEqual(history.changes.total, 2)
        self.assertEqual(
            {flow.uuid for row in history.changes.rows for flow in row.flows},
            {"u-1"},
        )
        self.assertEqual({row.flow_count for row in history.changes.rows}, {1})

    def test_a_flows_history_carries_its_prov_trail(self):
        history = change_queries.flow_history(self.connection(), "u-1")
        self.assertEqual(len(history.activities), 2)
        first, second = history.activities
        self.assertEqual(first.used_entity_id, "ef:flow/u-1/v0")
        self.assertEqual(second.used_entity_id, first.generated_entity_id)
        self.assertTrue(first.activity_id.startswith("ef:activity/change/run-1/"))

    def test_the_field_summary_is_computed_not_stored(self):
        """`provenance.json` materialised this as a second copy of the
        activities grouped by field. It is a GROUP BY."""
        fields = {
            entry.field_name: entry
            for entry in change_queries.field_history(self.connection(), uuid="u-1")
        }
        self.assertEqual(fields["unit"].change_count, 1)
        self.assertEqual(fields["cas_numbers"].transformers, ["consensus_match"])
        self.assertEqual(fields["unit"].latest_comment, "normalised")

    def test_a_database_without_a_changelog_says_so(self):
        bare = Path(self._tmp.name) / "bare.sqlite3"
        _write_fixture(bare)
        writable = sqlite3.connect(bare)
        writable.execute("DROP TABLE changelog")
        writable.commit()
        writable.close()

        connection = db.connect(bare)
        self.addCleanup(connection.close)
        self.assertFalse(change_queries.available(connection))
        self.assertFalse(change_queries.flow_history(connection, "u-1").available)


class HistoryOnDemandTestCase(Phase3TestCase):
    def test_the_detail_page_reads_no_history(self):
        """The point of the split. Only true if nothing queries for it."""
        connection = db.connect(self.path)
        self.addCleanup(connection.close)
        seen: list[str] = []
        connection.set_trace_callback(seen.append)
        flow_queries.flow_detail(connection, "u-1")
        connection.set_trace_callback(None)
        self.assertFalse(
            [s for s in seen if "changelog" in s or "provenance_activities" in s]
        )

    def test_the_detail_page_offers_a_link_that_works_without_script(self):
        """The `<details>` wraps a plain link, so a reader with this file
        blocked navigates instead of expanding."""
        body = self.client().get("/flows/u-1").get_data(as_text=True)
        self.assertIn('data-fragment="/flows/u-1/changes?fragment=1"', body)
        self.assertIn('href="/flows/u-1/changes"', body)

    def test_the_fragment_is_a_fragment(self):
        """No layout, no navigation: it is inserted into a page that has both."""
        body = self.client().get("/flows/u-1/changes?fragment=1").get_data(as_text=True)
        self.assertNotIn("<html", body)
        self.assertNotIn("masthead", body)
        self.assertIn("PROV-O trail", body)

    def test_the_fragment_and_the_page_carry_the_same_content(self):
        """They share a template, so they cannot drift apart."""
        client = self.client()
        fragment = client.get("/flows/u-1/changes?fragment=1").get_data(as_text=True)
        page = client.get("/flows/u-1/changes").get_data(as_text=True)
        # Every table row of the fragment appears in the standalone page.
        rows = re.findall(r"<tr>.*?</tr>", fragment, re.S)
        self.assertTrue(rows)
        for row in rows:
            self.assertIn(row, page)


class QueueTestCase(Phase3TestCase):
    def test_every_queue_has_a_definition_and_a_route(self):
        client = self.client()
        for definition in queue_queries.DEFINITIONS:
            with self.subTest(definition.name):
                if definition.template == "queue.html":
                    self.assertTrue(definition.columns, "a queue renders columns")
                else:
                    # A queue whose item is not a row carries no columns: it
                    # names a template that renders something else.
                    self.assertFalse(definition.columns)
                self.assertTrue(definition.question, "a queue says what it asks")
                response = client.get(f"/queue/{definition.name}")
                self.assertEqual(response.status_code, 200)

    def test_an_unknown_queue_is_a_404(self):
        """A typo that renders "nothing to do" is worse than one that 404s."""
        self.assertEqual(self.client().get("/queue/nope").status_code, 404)

    def test_the_index_separates_flow_decisions_from_factor_decisions(self):
        """Not the same kind of work, and not even from the same run: a build
        writes the flow queues and `characterise` writes the factor ones, over a
        database the build has already finished with."""
        sections = dict(
            (group.key, [row.definition.name for row in rows])
            for group, rows in queue_queries.grouped(self.connection())
        )
        self.assertEqual(
            list(sections), [group.key for group in queue_queries.GROUPS]
        )
        self.assertEqual(
            sorted(sections[queue_queries.FACTOR_DECISIONS.key]),
            sorted(queue_queries.FACTOR_QUEUES),
        )
        for name in queue_queries.FACTOR_QUEUES:
            self.assertNotIn(name, sections[queue_queries.FLOW_DECISIONS.key])
        self.assertIn("elements", sections[queue_queries.FLOW_DECISIONS.key])

    def test_every_queue_lands_in_exactly_one_section(self):
        """A queue whose group nothing renders would vanish from the index."""
        placed = [
            name
            for _group, rows in queue_queries.grouped(self.connection())
            for name in (row.definition.name for row in rows)
        ]
        self.assertEqual(
            sorted(placed),
            sorted(definition.name for definition in queue_queries.DEFINITIONS),
        )

    def test_the_index_page_renders_both_sections(self):
        body = self.client().get("/queue/").get_data(as_text=True)
        for group in queue_queries.GROUPS:
            self.assertIn(group.title, body)

    def test_the_index_reports_blocking_separately_from_total(self):
        summaries = {
            summary.definition.name: summary
            for summary in queue_queries.index(self.connection())
        }
        self.assertEqual(summaries["ec-malformed"].total, 1)
        self.assertEqual(summaries["ec-malformed"].blocking, 1)
        self.assertEqual(summaries["ec-cross-check"].total, 1)
        self.assertEqual(summaries["ec-cross-check"].blocking, 0)

    def test_an_empty_queue_is_listed_as_clear(self):
        """Unlike the overview, which leaves them out: a curator choosing what
        to work on is told which queues are done."""
        summaries = {
            summary.definition.name: summary
            for summary in queue_queries.index(self.connection())
        }
        self.assertEqual(summaries["cas-ambiguous"].total, 0)
        self.assertTrue(summaries["cas-ambiguous"].available)

    def test_the_elements_queue_reads_its_own_table(self):
        """A different question -- what is missing, not what is wrong -- so a
        different table, shaped into the same rows."""
        page = queue_queries.items(self.connection(), queue_queries.ELEMENTS)
        self.assertEqual([item.payload["symbol"] for item in page.rows], ["Og"])
        self.assertEqual(page.rows[0].severity, str(Severity.INFO))

    def test_a_queue_filters_by_severity(self):
        connection = self.connection()
        self.assertEqual(
            queue_queries.items(connection, "ec-malformed",
                                severity=str(Severity.BLOCKING)).total,
            1,
        )
        self.assertEqual(
            queue_queries.items(connection, "ec-malformed",
                                severity=str(Severity.INFO)).total,
            0,
        )

    def test_a_queue_searches_its_payload(self):
        page = queue_queries.items(self.connection(), "ec-malformed",
                                   query="200-000-0")
        self.assertEqual([item.item_key for item in page.rows], ["u-1:200-000-0"])

    def test_a_queue_item_reads_columns_out_of_its_payload(self):
        page = queue_queries.items(self.connection(), "ec-cross-check")
        item = page.rows[0]
        self.assertEqual(item.value("inventory_ec"), "200-812-7")
        self.assertIsNone(item.value("not-a-field"))


class NamesInACellTestCase(unittest.TestCase):
    """A column of names is read, not parsed.

    Every list value in this table renders as JSON, which for a column of
    identifiers costs a reader two brackets and a pair of quotes and is worth
    it -- the shape of the value is part of what they are checking. For a
    column of names it is two brackets and a pair of quotes in front of the
    only thing on the page anyone is reading, so those columns say `lines` and
    get one entry per line.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "consensus-flows.sqlite3"
        _write_fixture(self.path, queues=[
            ReviewQueueItem(
                queue_name=ReviewQueue.CAS_AMBIGUOUS,
                item_key="EF 3.1:dmpa:299-85-4", item_index=1,
                severity=Severity.BLOCKING, uuid="u-1", title="Dmpa",
                payload={
                    "flow_name": "Dmpa", "source": "EF 3.1", "flow_count": 13,
                    "current_cas_numbers": ["299-85-4"],
                    "current_cas_names": ["299-85-4: Zytron"],
                    "possible_corrected_cas_names": [
                        "32161-30-1: 3,4-dimethoxy-L-phenylalanine",
                        "71-58-9: medroxyprogesterone acetate",
                    ],
                },
            ),
            # `Formate` reaches the queue carrying no number of its own: two of
            # its three cells have nothing in them.
            ReviewQueueItem(
                queue_name=ReviewQueue.CAS_AMBIGUOUS,
                item_key="EF 3.1:formate:", item_index=2,
                severity=Severity.BLOCKING, uuid="u-2", title="Formate",
                payload={
                    "flow_name": "Formate", "source": "EF 3.1", "flow_count": 3,
                    "current_cas_numbers": [], "current_cas_names": [],
                    "possible_corrected_cas_names": ["71-47-6: formate"],
                },
            ),
        ])
        app = create_app(self.path)
        app.config["TESTING"] = True
        self.body = app.test_client().get("/queue/cas-ambiguous").get_data(as_text=True)

    def test_a_name_is_rendered_as_a_name(self):
        self.assertIn("<div>71-58-9: medroxyprogesterone acetate</div>", self.body)
        self.assertNotIn("&#34;71-58-9", self.body)

    def test_the_row_says_how_many_flows_are_waiting_on_it(self):
        """One row per name; thirteen flows take the same answer."""
        self.assertIn("<td >13</td>", self.body)

    def test_an_empty_list_is_an_em_dash_not_an_empty_list(self):
        """A flow with no CAS of its own has nothing to name, and the cell says
        so the way every other blank cell on the site does."""
        self.assertNotIn("[]", self.body)


class ContextTestCase(Phase3TestCase):
    def test_the_rules_render_with_their_target_context(self):
        page = context_queries.mapping_page(self.connection())
        self.assertEqual(page.total, 1)
        mapping = page.rows[0]
        self.assertEqual(mapping.source, "ecoinvent-3.12")
        self.assertEqual(mapping.source_display,
                         "air → low population density, long-term")
        self.assertEqual(mapping.context_display, "Environmental → Air")
        self.assertEqual(mapping.context_short, "envi-air")

    def test_the_rules_filter_by_source(self):
        connection = self.connection()
        self.assertEqual(
            context_queries.mapping_page(connection, source="ecoinvent-3.12").total, 1
        )
        self.assertEqual(
            context_queries.mapping_page(connection, source="nope").total, 0
        )

    def test_a_database_without_the_table_says_so(self):
        bare = Path(self._tmp.name) / "no-contexts.sqlite3"
        _write_fixture(bare)
        writable = sqlite3.connect(bare)
        writable.execute("DROP TABLE context_default_mappings")
        writable.commit()
        writable.close()

        connection = db.connect(bare)
        self.addCleanup(connection.close)
        self.assertFalse(context_queries.available(connection))

        app = create_app(bare)
        app.config["TESTING"] = True
        response = app.test_client().get("/contexts")
        self.assertEqual(response.status_code, 200)
        self.assertIn("context_default_mappings", response.get_data(as_text=True))


class RouteTestCase(Phase3TestCase):
    ROUTES = ("/changes", "/contexts", "/queue/", "/queue/ec-malformed",
              "/queue/elements", "/flows/u-1/changes", "/flow-objects/fo-co2/changes")

    def test_every_route_renders_with_data(self):
        client = self.client()
        for route in self.ROUTES:
            with self.subTest(route):
                self.assertEqual(client.get(route).status_code, 200)

    def test_every_route_renders_without_a_database(self):
        app = create_app(Path(self._tmp.name) / "absent.sqlite3")
        app.config["TESTING"] = True
        client = app.test_client()
        for route in self.ROUTES:
            with self.subTest(route):
                response = client.get(route)
                self.assertEqual(response.status_code, 200)
                self.assertIn("No database yet", response.get_data(as_text=True))

    def test_the_navigation_is_now_complete(self):
        body = self.client().get("/").get_data(as_text=True)
        for label in ("Docs", "Current run", "Flow objects", "Elementary flows",
                      "Checks", "Queue", "Merge"):
            with self.subTest(label):
                self.assertIn(f">{label}</a>", body)


if __name__ == "__main__":
    unittest.main()
