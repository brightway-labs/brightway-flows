"""`/scores`: a vendor's datasets scored two ways, as pages.

Three states every route has to survive, each its own test: no database at
all; a database `compare-scores` has not run against, which says so rather
than showing a table of zeros; and a compared one.  The compared one is
written by the real writer from the real fixture against a hand-rolled
build, so the pages read what `compare-scores` writes.  And the measures:
`assess` sees the run's counts under `scores.*`.
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

import orjson

from brightway_flows.assessment.measures import _score_measures
from brightway_flows.domain.lcia.unit_process_scores import load_score_artifact
from brightway_flows.lcia.scores.pipeline import compare_scores
from brightway_flows.settings import AssessedRelease, ScoreComparisonSettings
from brightway_flows.webapps.app import create_app, db
from brightway_flows.webapps.app.queries import scores as queries

FIXTURE = (
    Path(__file__).resolve().parent / "data"
    / "unit-process-scores-ecoinvent-3.8-apos-fixture.json.gz"
)
WIND_SE = "b09e51ef9d976bc64905c74fd99842fc"
FOSSILS = "EF v3.0|energy resources: non-renewable|abiotic depletion potential (ADP): fossil fuels"
HARD_COAL = "b6d0042d-0ef8-49ed-9162-a07ff1ccf750"


def _settings() -> ScoreComparisonSettings:
    return ScoreComparisonSettings(
        artifact_dir=FIXTURE.parent,
        releases=[AssessedRelease(
            list_name="ecoinvent", list_version="3.8", system_model="apos",
            brightway_project="p", brightway_database="d", method_family="EF v3.0",
            artifact=FIXTURE.name,
        )],
    )


class ScorePagesTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "consensus-flows.sqlite3"

    def _build(self, *, compared: bool) -> None:
        """A build with the wind activity's hard coal merged, and nothing else."""
        connection = sqlite3.connect(self.path)
        connection.execute("CREATE TABLE pipeline_runs (run_id TEXT, timestamp TEXT)")
        connection.execute("INSERT INTO pipeline_runs VALUES ('build-1', '2026-08-25')")
        connection.execute("CREATE TABLE lcia_runs (run_id TEXT, started_at TEXT)")
        connection.execute("INSERT INTO lcia_runs VALUES ('lcia-1', '2026-08-25')")
        connection.execute(
            "CREATE TABLE elementary_flows (uuid TEXT PRIMARY KEY, unit TEXT, "
            "pref_label_value TEXT, context_display TEXT)"
        )
        connection.execute(
            "INSERT INTO elementary_flows VALUES ('c-coal', 'kg', 'Hard coal', "
            "'Resource → Ground')"
        )
        connection.execute(
            "CREATE TABLE elementary_flow_sources (id INTEGER PRIMARY KEY, "
            "elementary_flow_uuid TEXT, list_name TEXT, list_version TEXT, "
            "source_flow_uuid TEXT, source_flow_name TEXT, source_metadata_json TEXT)"
        )
        connection.execute(
            "INSERT INTO elementary_flow_sources (elementary_flow_uuid, list_name, "
            "list_version, source_flow_uuid, source_flow_name, source_metadata_json) "
            "VALUES ('c-coal', 'ecoinvent', '3.8', ?, 'Coal, hard, unspecified, in ground', "
            "'{\"unit\": \"kg\"}')",
            (HARD_COAL,),
        )
        connection.execute(
            "CREATE TABLE lcia_characterization_factors (impact_category_id TEXT, "
            "elementary_flow_uuid TEXT, geography TEXT NOT NULL DEFAULT '', amount REAL)"
        )
        connection.commit()
        connection.close()
        if compared:
            compare_scores(self.path, settings=_settings())

    def client(self):
        app = create_app(self.path)
        app.config["TESTING"] = True
        return app.test_client()

    def text(self, route: str, status: int = 200) -> str:
        response = self.client().get(route)
        self.assertEqual(response.status_code, status, route)
        return response.get_data(as_text=True)

    def test_no_database_names_the_file(self):
        body = self.text("/scores/")
        self.assertIn("consensus-flows.sqlite3", body)

    def test_not_compared_yet_says_so(self):
        self._build(compared=False)
        for route in ("/scores/", "/scores/ecoinvent-3.8-apos/datasets",
                      f"/scores/ecoinvent-3.8-apos/dataset/{WIND_SE}"):
            with self.subTest(route=route):
                body = self.text(route)
                self.assertIn("compare-scores", body)
                self.assertNotIn("Datasets scored two ways", body)

    def test_the_index_draws_the_issue_s_table(self):
        self._build(compared=True)
        body = self.text("/scores/")
        self.assertIn("ecoinvent 3.8 apos", body)
        self.assertIn("EF v3.0", body)
        self.assertIn("energy resources: non-renewable", body)
        # EF 3.0's metals categories: on the table, marked, not linked.
        self.assertIn("no category of ours", body)
        self.assertIn("Scored with", body)  # the method-version note

    def test_a_category_ranks_the_flows(self):
        self._build(compared=True)
        body = self.text(f"/scores/ecoinvent-3.8-apos/category/{FOSSILS}")
        self.assertIn("Coal, hard, unspecified, in ground", body)
        self.assertIn("unmapped flow", body)
        self.assertIn("Hard coal", body)  # the consensus flow, linked
        filtered = self.text(f"/scores/ecoinvent-3.8-apos/category/{FOSSILS}?reason=unmapped-flow")
        self.assertIn("chip--active", filtered)
        self.text("/scores/ecoinvent-3.8-apos/category/nobody", 404)
        self.text(f"/scores/nobody/category/{FOSSILS}", 404)

    def test_a_dataset_shows_both_scores_and_the_flows_under_one_category(self):
        self._build(compared=True)
        body = self.text(f"/scores/ecoinvent-3.8-apos/dataset/{WIND_SE}")
        self.assertIn("electricity production, wind", body)
        self.assertIn("0.30979", body)  # the vendor's fossil-ADP score, #209
        opened = self.text(
            f"/scores/ecoinvent-3.8-apos/dataset/{WIND_SE}?category={FOSSILS}"
        )
        self.assertIn("flow by flow", opened)
        self.assertIn("no consensus factor", opened)
        self.text(f"/scores/ecoinvent-3.8-apos/dataset/{WIND_SE}?category=nobody", 404)
        self.text("/scores/ecoinvent-3.8-apos/dataset/nobody", 404)

    def test_datasets_are_searchable(self):
        self._build(compared=True)
        body = self.text("/scores/ecoinvent-3.8-apos/datasets?q=wind")
        self.assertIn("electricity production, wind", body)
        self.assertNotIn("concrete production", body)
        self.assertIn("concrete production", self.text("/scores/ecoinvent-3.8-apos/datasets"))

    def test_the_queries_read_without_an_app(self):
        self._build(compared=True)
        connection = db.connect(self.path)
        self.addCleanup(connection.close)
        (card,) = queries.releases(connection)
        self.assertEqual(card.unit_processes, 3)
        fossils = next(c for c in card.categories if c.key == FOSSILS)
        # A dataset the vendor scores at zero is left out of the counts: a
        # ratio against zero says nothing.  The by-product is one of them.
        artifact = load_score_artifact(FIXTURE)
        self.assertEqual(
            fossils.datasets,
            sum(1 for u in artifact.unit_processes if u.scores[FOSSILS] != 0),
        )
        self.assertLess(fossils.datasets, 3)
        self.assertEqual(fossils.slug, "resource-use-fossils")
        metals = next(c for c in card.categories if "metals" in c.name)
        self.assertTrue(metals.unmatched)

    def test_assess_sees_the_counts(self):
        self._build(compared=True)
        connection = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        self.addCleanup(connection.close)
        # The score measures alone: `collect_measures` wants a whole build's
        # tables, and this build is three of them.
        keys = {m.key: m.value for m in _score_measures(connection)}
        self.assertTrue(all(m.group == "scores" for m in _score_measures(connection)))
        self.assertEqual(keys["scores.ecoinvent-3.8-apos.unit_processes"], 3)
        self.assertEqual(keys["scores.ecoinvent-3.8-apos.their_categories_unmatched"], 3)
        self.assertIn("scores.ecoinvent-3.8-apos.pairs_within_2x", keys)
        self.assertEqual(keys["scores.releases_compared"], 1)

    def test_the_fixture_is_what_the_pages_show(self):
        self._build(compared=True)
        artifact = load_score_artifact(FIXTURE)
        connection = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        self.addCleanup(connection.close)
        (row,) = connection.execute("SELECT unit_processes, stats_json FROM score_releases")
        self.assertEqual(row[0], len(artifact.unit_processes))
        self.assertEqual(orjson.loads(row[1])["their_categories"], len(artifact.categories))
