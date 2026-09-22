"""The two factor queues have pages, and the pages carry the evidence.

A ruling on a characterisation factor is a statement about somebody else's
science, and the numbers alone do not support one. What does is everything that
put them in front of the curator, which is what these assert is on the page:

* where each flow came from, and under what name each source list shipped it --
  the first contested question in a real build is 1,441x apart *because* EF ships
  the substance under an IUPAC name and ecoinvent ships `Gamma-cyhalothrin`, and a
  correspondence table put them on one flow;
* what the pipeline then did to the substance;
* every number all three implementations state about it, and any a collapse
  already declined.

The fixture is one substance in two contexts, contested in one category and
proposed in another, which is the smallest database that renders both pages.
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

import orjson

from brightway_flows.pipeline.review_records import (
    PipelineRun,
    ReviewQueue,
    ReviewQueueItem,
    Severity,
)
from brightway_flows.pipeline.review_tables import (
    REVIEW_SCHEMA_VERSION,
    write_review_tables,
)
from brightway_flows.webapps.app import create_app, db
from brightway_flows.webapps.app.queries import factors as factor_queries
from brightway_flows.webapps.app.queries import queue as queue_queries

CONTESTED = ReviewQueueItem(
    queue_name=ReviewQueue.CONTESTED_FACTOR,
    item_key="fo-1|ecotoxicity-freshwater",
    title="Kresoxim-methyl: Ecotoxicity, freshwater, 1 disputed",
    severity=Severity.BLOCKING,
    uuid="cf-1",
    flow_object_id="fo-1",
    payload={
        "category": "Ecotoxicity, freshwater",
        "substance": "Kresoxim-methyl",
        "contexts": ["Environmental → Ground → Agricultural"],
        "factor_count": 1,
        "worst_ratio": 397.387,
        "one_value_everywhere": True,
        "stated_values": [134.73, 53540.0],
        "implementations": [
            "European Commission — JRC", "ecoinvent Centre",
        ],
        "rows": [
            {
                "elementary_flow_uuid": "cf-1",
                "context_display": "Environmental → Ground → Agricultural",
                "geography": None,
                "category": "Ecotoxicity, freshwater",
                "stated": [
                    {
                        "implemented_by": "European Commission — JRC",
                        "amount": 134.73,
                        "source_flow_uuid": None,
                    },
                    {
                        "implemented_by": "ecoinvent Centre",
                        "amount": 53540.0,
                        "source_flow_uuid": "ei-1",
                    },
                ],
                "ratio": 397.387,
            }
        ],
    },
)

PROPOSED = ReviewQueueItem(
    queue_name=ReviewQueue.PROPOSED_FACTOR,
    item_key="fo-1|land-use",
    title="Kresoxim-methyl: Land use, 1 proposed",
    severity=Severity.BLOCKING,
    uuid="cf-2",
    flow_object_id="fo-1",
    payload={
        "category": "Land use",
        "substance": "Kresoxim-methyl",
        "contexts": ["Environmental → Ground → Silvicultural"],
        "factor_count": 1,
        "one_value_everywhere": True,
        "stated_values": [9.9],
        "implementations": ["ecoinvent Centre"],
        "rows": [
            {
                "elementary_flow_uuid": "cf-2",
                "context_display": "Environmental → Ground → Silvicultural",
                "geography": None,
                "category": "Land use",
                "stated": [
                    {
                        "implemented_by": "ecoinvent Centre",
                        "amount": 9.9,
                        "source_flow_uuid": "ei-2",
                    }
                ],
            }
        ],
    },
)


#: The third queue's row. Both implementations state EF's number and agree, and
#: the model both are derived from states a millionth of it: the question is not
#: which of the two is right but whether either should be published, so the row
#: carries the model's numbers beside the build's (#107).
CONTRADICTED = ReviewQueueItem(
    queue_name=ReviewQueue.CONTRADICTED_FACTOR,
    item_key="fo-1|human-toxicity-non-cancer",
    title=(
        "Kresoxim-methyl: Human toxicity, non-cancer, 1 contradicted by USEtox 2.1"
    ),
    severity=Severity.BLOCKING,
    uuid="cf-1",
    flow_object_id="fo-1",
    payload={
        "category": "Human toxicity, non-cancer",
        "substance": "Kresoxim-methyl",
        "contexts": ["Environmental → Ground → Agricultural"],
        "factor_count": 1,
        "worst_ratio": 1381461.0,
        "one_value_everywhere": True,
        "stated_values": [0.19957],
        "implementations": ["European Commission — JRC"],
        "contradicts": {
            "model": "USEtox 2.1",
            "read_from": ["USEtox2.1_LC-Impact_v2_results_HUMANTOX_20190326.xlsx"],
            "narrowest_ratio": 601767.0,
            "widest_ratio": 1381461.0,
            "comment": "",
            "compared": [
                {
                    "compartment": "emission to urban air close to ground",
                    "context_iri": "ctx-agri",
                    "elementary_flow_uuid": "cf-1",
                    "model_amount": 1.44463e-07,
                    "published_amount": 0.19957,
                    "ratio": 1381461.0,
                }
            ],
        },
        "rows": [
            {
                "elementary_flow_uuid": "cf-1",
                "context_display": "Environmental → Ground → Agricultural",
                "geography": None,
                "category": "Human toxicity, non-cancer",
                "stated": [
                    {
                        "implemented_by": "European Commission — JRC",
                        "amount": 0.19957,
                        "source_flow_uuid": None,
                    }
                ],
                "ratio": None,
            }
        ],
    },
)


def _write_fixture(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE elementary_flows (uuid TEXT, flow_object_id TEXT, "
        "pref_label_value TEXT, context_display TEXT, context_iri TEXT, unit TEXT)"
    )
    connection.execute(
        "CREATE TABLE elementary_flow_sources (elementary_flow_uuid TEXT, "
        "list_name TEXT, list_version TEXT, source_flow_uuid TEXT, "
        "source_flow_name TEXT, source_metadata_json TEXT)"
    )
    connection.execute(
        "CREATE TABLE lcia_impact_categories (id TEXT, name TEXT, implemented_by TEXT)"
    )
    connection.execute(
        "CREATE TABLE lcia_characterization_factors (impact_category_id TEXT, "
        "elementary_flow_uuid TEXT, geography TEXT, amount REAL, "
        "source_flow_uuid TEXT, derivation TEXT)"
    )
    connection.execute(
        "CREATE TABLE lcia_findings (kind TEXT, implemented_by TEXT, "
        "elementary_flow_uuid TEXT, impact_category_id TEXT, detail TEXT, "
        "context_json TEXT)"
    )
    connection.executemany(
        "INSERT INTO elementary_flows VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("cf-1", "fo-1", "Kresoxim-methyl",
             "Environmental → Ground → Agricultural", "ctx-agri", "kg"),
            ("cf-2", "fo-1", "Kresoxim-methyl",
             "Environmental → Ground → Silvicultural", "ctx-silv", "kg"),
            # A different substance, publishing the number `PROPOSED` proposes.
            ("cf-3", "fo-2", "Fungicides, unspecified",
             "Environmental → Ground → Agricultural", "ctx-agri", "kg"),
        ],
    )
    connection.executemany(
        "INSERT INTO elementary_flow_sources VALUES (?, ?, ?, ?, ?, ?)",
        [
            (
                "cf-1", "EF", "3.1", "cf-1", "kresoxim-methyl",
                orjson.dumps({
                    "original_context": ["Emissions", "Emissions to soil"],
                    "unit": "kg",
                }).decode(),
            ),
            (
                "cf-1", "ecoinvent", "3.12", "ei-1", "Kresoxim-methyl",
                orjson.dumps({
                    "original_context": ["soil", "agricultural"],
                    "unit": "kg",
                    "merge_basis": "prepared_mapping",
                    "mapping_file": "ecoinvent-3.11-biosphere-EF-3.1-biosphere",
                }).decode(),
            ),
        ],
    )
    connection.executemany(
        "INSERT INTO lcia_impact_categories VALUES (?, ?, ?)",
        [
            ("cat-jrc", "Ecotoxicity, freshwater", "European Commission — JRC"),
            ("cat-ei", "Ecotoxicity, freshwater", "ecoinvent Centre"),
            ("cat-ours", "Land use", "brightway-flows"),
        ],
    )
    connection.executemany(
        "INSERT INTO lcia_characterization_factors VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("cat-jrc", "cf-1", "", 134.73, None, None),
            ("cat-ei", "cf-1", "", 53540.0, "ei-1", None),
            # The proposed number, already published against the catch-all: the
            # shape #76 leaves behind, and what the `Also published elsewhere`
            # flag is for.
            ("cat-ours", "cf-3", "", 9.9, None, "agreed"),
        ],
    )
    connection.execute(
        "INSERT INTO lcia_findings VALUES (?, ?, ?, ?, ?, ?)",
        (
            "superseded-value",
            "European Commission — JRC",
            "cf-1",
            None,
            "Ecotoxicity, freshwater: 134.73 is published and 53540.0 was declined",
            "{}",
        ),
    )
    connection.commit()
    connection.close()

    write_review_tables(
        path,
        run=PipelineRun(
            run_id="run-1",
            timestamp="2026-08-17T00:00:00+00:00",
            schema_version=REVIEW_SCHEMA_VERSION,
        ),
        stats=[],
        changes=[],
        queue_items=[CONTESTED, PROPOSED, CONTRADICTED],
        formula_mismatches=[],
        element_coverage=[],
        context_mappings=[],
    )

    # After the review tables, not before: `write_review_tables` owns `changelog`
    # and drops it, so a row written first would be swept away -- which is how
    # the evidence section came to render empty the first time.
    connection = sqlite3.connect(path)
    connection.execute(
        "INSERT INTO changelog (change_index, transformer, flow_object_id, field, "
        "old_value_json, new_value_json, comment) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (1, "bootstrap_labels", "fo-1", "prefLabel", "null", "[]",
         "Bootstrapped prefLabel from legacy name field"),
    )
    connection.commit()
    connection.close()


class FactorQueuePageTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "consensus-flows.sqlite3"
        _write_fixture(self.path)

    def client(self):
        app = create_app(self.path)
        app.config["TESTING"] = True
        return app.test_client()

    def page(self, name):
        connection = db.connect(self.path)
        self.addCleanup(connection.close)
        return factor_queries.questions(
            connection, queue_queries.items(connection, name), queue=name
        )

    def test_both_queues_have_a_definition_and_a_template(self):
        definitions = {d.name: d for d in queue_queries.DEFINITIONS}
        for name in queue_queries.FACTOR_QUEUES:
            with self.subTest(name):
                self.assertIn(name, definitions)
                self.assertEqual(definitions[name].template, "queue_factors.html")

    def test_the_pages_render(self):
        client = self.client()
        for name in queue_queries.FACTOR_QUEUES:
            with self.subTest(name):
                response = client.get(f"/queue/{name}")
                self.assertEqual(response.status_code, 200)

    def test_the_contested_page_shows_both_numbers_and_the_ratio(self):
        html = self.client().get("/queue/contested-factor").get_data(as_text=True)
        self.assertIn("134.73", html)
        self.assertIn("53540.0", html)
        self.assertIn("397.4", html)

    def test_the_contradicted_page_shows_the_model_beside_the_method(self):
        """Both numbers, because a curator ruling on one of these is being asked
        to weigh a third party's model against the method's own publisher, and a
        page that said only "contradicted" would be asking them to take our word
        for it."""
        html = self.client().get("/queue/contradicted-factor").get_data(as_text=True)
        self.assertIn("What USEtox 2.1 states", html)
        self.assertIn("0.19957", html)
        self.assertIn("1.4446e-07", html)
        self.assertIn("emission to urban air close to ground", html)

    def test_the_contradicted_page_names_the_file_the_model_was_read_from(self):
        """A claim about somebody else's release that nobody can look up is not
        reviewable."""
        html = self.client().get("/queue/contradicted-factor").get_data(as_text=True)
        self.assertIn("USEtox2.1_LC-Impact_v2_results_HUMANTOX_20190326.xlsx", html)

    def test_the_page_says_where_the_flows_came_from(self):
        """The name each source list shipped, which is what a 397x disagreement
        is usually about."""
        html = self.client().get("/queue/contested-factor").get_data(as_text=True)
        self.assertIn("Where these flows came from", html)
        self.assertIn("kresoxim-methyl", html)
        self.assertIn("soil / agricultural", html)
        self.assertIn("ecoinvent-3.11-biosphere-EF-3.1-biosphere", html)

    def test_the_page_says_what_the_pipeline_did(self):
        html = self.client().get("/queue/contested-factor").get_data(as_text=True)
        self.assertIn("What the pipeline did to this substance", html)
        self.assertIn("bootstrap_labels", html)

    def test_the_page_shows_every_number_stated(self):
        html = self.client().get("/queue/contested-factor").get_data(as_text=True)
        self.assertIn("Every number stated about these flows", html)
        self.assertIn("European Commission", html)
        self.assertIn("ecoinvent Centre", html)

    def test_the_page_shows_a_number_already_declined(self):
        html = self.client().get("/queue/contested-factor").get_data(as_text=True)
        self.assertIn("Numbers already declined", html)
        self.assertIn("was declined", html)

    def test_the_proposed_page_says_whether_the_number_is_the_same_everywhere(self):
        """The fact a ruling about a compartment turns on."""
        html = self.client().get("/queue/proposed-factor").get_data(as_text=True)
        self.assertIn("Same number everywhere", html)
        self.assertIn("one number in every context", html)

    def test_the_proposed_page_shows_only_the_implementations_that_spoke(self):
        """Nobody else states a number there; a column of dashes would suggest
        another implementation had been asked and said nothing.  The columns come
        from the question rather than from a list written into the template, so
        this holds however many implementations there turn out to be."""
        html = self.client().get("/queue/proposed-factor").get_data(as_text=True)
        self.assertIn(">ecoinvent Centre</th>", html)
        self.assertNotIn(">European Commission — JRC</th>", html)

    def test_the_evidence_is_read_rather_than_stored(self):
        """The payload is the question; the evidence is a join. A queue row that
        carried it would freeze it at the moment `characterise` ran."""
        page = self.page("contested-factor")
        question = page.rows[0]
        self.assertNotIn("sources", question.item.payload)
        self.assertEqual(len(question.sources["cf-1"]), 2)
        self.assertEqual(len(question.factors["cf-1"]), 2)
        self.assertEqual(len(question.changes), 1)
        self.assertEqual(len(question.declined), 1)

    def test_the_page_names_the_substance_rather_than_its_identifier(self):
        """`fo-1` is the address, not the answer.

        A curator weighing a number has to know what it is a number about, and
        the flow object id says only where to click.  The id stays on the page
        because a ruling is keyed on it.
        """
        html = self.client().get("/queue/proposed-factor").get_data(as_text=True)
        self.assertIn(">Kresoxim-methyl</a>", html)
        self.assertIn("fo-1", html)

    def test_the_page_states_the_unit_the_factor_is_per(self):
        """A factor is per unit of the flow, and one question can cover flows
        measured differently."""
        html = self.client().get("/queue/proposed-factor").get_data(as_text=True)
        self.assertIn("Unit", html)
        self.assertIn(">kg</dd>", html)

    def test_the_proposed_page_flags_a_number_published_against_another_flow(self):
        """The evidence that a proposed number is a bucket's number under a
        specific name: this list already publishes 9.9 for a catch-all, and the
        implementation proposes the same 9.9 for the named substance (#76)."""
        html = self.client().get("/queue/proposed-factor").get_data(as_text=True)
        self.assertIn("Also published elsewhere", html)
        self.assertIn("Fungicides, unspecified", html)
        self.assertIn("published for", html)

    def test_the_flag_is_the_substance_rather_than_a_bare_yes(self):
        """Nearly every question in this queue matches something, so a yes/no
        that did not name the substance would carry no information."""
        page = self.page("proposed-factor")
        question = page.rows[0]
        self.assertEqual(question.elsewhere_substances, ["Fungicides, unspecified"])
        self.assertEqual(question.elsewhere_amounts, [9.9])

    def test_the_questions_own_flows_are_not_elsewhere(self):
        """A number this list publishes on the very flow under question is what
        `derivation` on that row already says; repeating it as a match would
        make every ruled question look like a duplicate of itself."""
        writable = sqlite3.connect(self.path)
        writable.execute(
            "INSERT INTO lcia_characterization_factors VALUES (?, ?, ?, ?, ?, ?)",
            ("cat-ours", "cf-2", "", 9.9, None, "sole"),
        )
        writable.commit()
        writable.close()
        question = self.page("proposed-factor").rows[0]
        objects = {row.flow_object_id for row in question.elsewhere}
        self.assertEqual(objects, {"fo-2"})

    def test_the_other_factor_queues_do_not_run_the_search(self):
        """It is the proposed queue's question -- should this list publish a
        number nobody here states -- and a scan of the factor table on an
        unindexed amount is not free."""
        html = self.client().get("/queue/contested-factor").get_data(as_text=True)
        self.assertNotIn("Also published elsewhere", html)

    def test_every_number_stated_carries_the_shipped_compartment(self):
        """The number was computed for the compartment the source list shipped,
        and this list's context is a translation of it."""
        html = self.client().get("/queue/contested-factor").get_data(as_text=True)
        self.assertIn("Shipped in", html)
        self.assertIn("Emissions / Emissions to soil", html)

    def test_a_database_without_the_factor_tables_still_renders(self):
        """A data directory whose build predates `characterise` is the normal
        state of one that has not been re-run, and the honest answer there is a
        page with no evidence rather than a stack trace."""
        connection = sqlite3.connect(self.path)
        connection.execute("DROP TABLE lcia_characterization_factors")
        connection.execute("DROP TABLE lcia_findings")
        connection.commit()
        connection.close()
        response = self.client().get("/queue/contested-factor")
        self.assertEqual(response.status_code, 200)
        self.assertIn("134.73", response.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
