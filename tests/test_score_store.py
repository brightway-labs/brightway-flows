"""The `score_*` tables hold what the comparison found, and a run is one of them.

The fixture is the real 3.8 APOS export cut to three unit processes, against
a hand-rolled build: enough of `elementary_flow_sources` and the consensus
factor table for the fossil-fuel flows of the wind activity to map, with one
`kg -> MJ` crossing carrying its multiplier and one carrying none.  The
writer is the real one, and so is `compare_artifact`, so what these tests
read back is what `compare-scores` writes.
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

import orjson

from brightway_flows.domain.lcia.unit_process_scores import load_score_artifact
from brightway_flows.lcia.scores.compare import ContributionReason
from brightway_flows.lcia.scores.pipeline import (
    compare_artifact,
    compare_scores,
    consensus_category_ids,
)
from brightway_flows.lcia.scores.store import (
    RELATIONS,
    ReleaseRecord,
    ScoreRun,
    consensus_factors,
    create_score_tables,
    finish_run,
    start_run,
    write_release,
)
from brightway_flows.settings import AssessedRelease, ScoreComparisonSettings

FIXTURE = (
    Path(__file__).resolve().parent / "data"
    / "unit-process-scores-ecoinvent-3.8-apos-fixture.json.gz"
)
WIND_SE = "b09e51ef9d976bc64905c74fd99842fc"
FOSSILS = "EF v3.0|energy resources: non-renewable|abiotic depletion potential (ADP): fossil fuels"

#: ecoinvent 3.8 flow uuids as the fixture carries them.
HARD_COAL = "b6d0042d-0ef8-49ed-9162-a07ff1ccf750"
URANIUM = "2ba5e39b-adb6-4767-a51d-90c1cf32fe98"


def _wind_flows(artifact):
    wind = next(u for u in artifact.unit_processes if u.activity_code == WIND_SE)
    factors = artifact.factors_by_category()[FOSSILS]
    return [(line.source_flow_uuid, factors.get(line.source_flow_uuid)) for line in wind.inventory
            if line.source_flow_uuid in factors]


class ScoreStoreTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.artifact = load_score_artifact(FIXTURE)
        cls.ids = consensus_category_ids()

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "consensus-flows.sqlite3"
        self.release = ScoreComparisonSettings().release("ecoinvent-3.8-apos")
        self._build()

    def _build(self) -> None:
        """A build with the wind activity's fossil flows merged, most of them."""
        connection = sqlite3.connect(self.path)
        connection.execute(
            "CREATE TABLE pipeline_runs (run_id TEXT, timestamp TEXT)"
        )
        connection.execute("INSERT INTO pipeline_runs VALUES ('build-1', '2026-08-25')")
        connection.execute(
            "CREATE TABLE lcia_runs (run_id TEXT, started_at TEXT)"
        )
        connection.execute("INSERT INTO lcia_runs VALUES ('lcia-1', '2026-08-25')")
        connection.execute(
            "CREATE TABLE elementary_flows (uuid TEXT PRIMARY KEY, unit TEXT)"
        )
        connection.execute(
            "CREATE TABLE elementary_flow_sources (id INTEGER PRIMARY KEY, "
            "elementary_flow_uuid TEXT, list_name TEXT, list_version TEXT, "
            "source_flow_uuid TEXT, source_flow_name TEXT, source_metadata_json TEXT)"
        )
        connection.execute(
            "CREATE TABLE lcia_characterization_factors (impact_category_id TEXT, "
            "elementary_flow_uuid TEXT, geography TEXT NOT NULL DEFAULT '', amount REAL)"
        )
        fossils_id = self.ids[("ef", "resource-use-fossils")]
        flows = _wind_flows(self.artifact)
        self.mapped = {}
        for source_uuid, their_factor in flows:
            if source_uuid == URANIUM:
                # Merged onto an MJ flow with no conversion recorded.
                target_unit, metadata, ours = "MJ", {"unit": "kg"}, 1.0
            elif source_uuid == HARD_COAL:
                # Merged onto an MJ flow, 18.01 MJ per kg: ours is 1.0 per MJ.
                target_unit, metadata = "MJ", {"unit": "kg", "qudt:conversionMultiplier": 18.01}
                ours = 1.0
            else:
                target_unit, metadata, ours = "kg", {"unit": "kg"}, 1.0  # imported as unity
            target = f"c-{source_uuid[:8]}"
            self.mapped[source_uuid] = target
            connection.execute("INSERT INTO elementary_flows VALUES (?, ?)", (target, target_unit))
            connection.execute(
                "INSERT INTO elementary_flow_sources (elementary_flow_uuid, list_name, "
                "list_version, source_flow_uuid, source_flow_name, source_metadata_json) "
                "VALUES (?, 'ecoinvent', '3.8', ?, ?, ?)",
                (target, source_uuid, source_uuid, orjson.dumps(metadata).decode()),
            )
            connection.execute(
                "INSERT INTO lcia_characterization_factors VALUES (?, ?, '', ?)",
                (fossils_id, target, ours),
            )
        connection.commit()
        connection.close()

    def _compare(self):
        ours = consensus_factors(self.path, category_ids=self.ids)
        return compare_artifact(
            self.artifact, db_path=self.path, release=self.release,
            our_factors=ours, category_ids=self.ids,
        )

    def test_consensus_factors_are_read_by_method_and_slug(self):
        ours = consensus_factors(self.path, category_ids=self.ids)
        self.assertEqual(set(ours), set(self.ids))
        self.assertEqual(len(ours[("ef", "resource-use-fossils")]), len(self.mapped))
        self.assertEqual(ours[("ef", "water-use")], {})

    def test_the_issue_s_second_comment(self):
        """Hard coal converted and agreeing; the others at unity and differing;
        uranium crossing with no conversion."""
        result = self._compare()
        rows = {
            (r.activity_code, r.source_flow_uuid): r
            for r in result.contributions if r.category_key == FOSSILS
        }
        self.assertIs(rows[(WIND_SE, HARD_COAL)].reason, ContributionReason.AGREE)
        self.assertEqual(rows[(WIND_SE, HARD_COAL)].multiplier, 18.01)
        self.assertIs(rows[(WIND_SE, URANIUM)].reason, ContributionReason.UNIT_CROSSING_UNCONVERTED)
        differing = [r for r in rows.values() if r.reason is ContributionReason.FACTOR_DIFFERS]
        self.assertGreaterEqual(len(differing), 3)
        wind = next(c for c in result.comparisons
                    if c.activity_code == WIND_SE and c.category_key == FOSSILS)
        self.assertAlmostEqual(wind.their_score, 0.30979, places=5)
        self.assertLess(wind.our_score, wind.their_score)

    def test_the_tables_hold_what_was_written(self):
        result = self._compare()
        run = ScoreRun("run-1", "2026-08-25T00:00:00+00:00", "build-1", "lcia-1")
        start_run(self.path, run=run)
        write_release(
            self.path,
            release=ReleaseRecord("ecoinvent-3.8-apos", str(FIXTURE), "abc"),
            artifact=self.artifact, result=result,
        )
        finish_run(self.path, run_id="run-1", finished_at="2026-08-25T00:01:00+00:00",
                   stats={"releases_compared": 1})
        connection = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        self.addCleanup(connection.close)
        run_row = connection.execute("SELECT build_run_id, lcia_run_id, finished_at, stats_json FROM score_runs").fetchone()
        self.assertEqual(run_row[:3], ("build-1", "lcia-1", "2026-08-25T00:01:00+00:00"))
        self.assertEqual(orjson.loads(run_row[3]), {"releases_compared": 1})
        self.assertEqual(
            connection.execute("SELECT count(*) FROM score_unit_processes").fetchone()[0], 3
        )
        self.assertEqual(
            connection.execute("SELECT count(*) FROM score_categories WHERE impact_category_id IS NULL").fetchone()[0],
            3,  # the three EF 3.0 `metals` categories
        )
        self.assertEqual(
            connection.execute("SELECT count(*) FROM score_comparisons").fetchone()[0],
            3 * 25,
        )
        self.assertEqual(
            connection.execute("SELECT count(*) FROM score_contributions").fetchone()[0],
            len(result.contributions),
        )
        top = connection.execute(
            "SELECT source_flow_uuid, reason FROM score_flow_priorities "
            "WHERE category_key = ? ORDER BY share_of_category DESC LIMIT 1", (FOSSILS,)
        ).fetchone()
        self.assertEqual(top[1], "factor-differs")

    def test_a_second_run_replaces_the_first(self):
        run = ScoreRun("run-1", "t", None, None)
        start_run(self.path, run=run)
        start_run(self.path, run=ScoreRun("run-2", "t", None, None))
        connection = sqlite3.connect(self.path)
        self.addCleanup(connection.close)
        self.assertEqual(
            [r[0] for r in connection.execute("SELECT run_id FROM score_runs")], ["run-2"]
        )

    def test_every_relation_is_dropped_first(self):
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        create_score_tables(connection)
        created = {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'view') "
                "AND name NOT LIKE 'sqlite_%'"
            )
        }
        self.assertEqual(created, set(RELATIONS))

    def test_the_pipeline_end_to_end(self):
        settings = ScoreComparisonSettings(
            artifact_dir=FIXTURE.parent,
            releases=[AssessedRelease(
                list_name="ecoinvent", list_version="3.8", system_model="apos",
                brightway_project="p", brightway_database="d", method_family="EF v3.0",
                artifact=FIXTURE.name,
            ), AssessedRelease(
                list_name="ecoinvent", list_version="3.12", system_model="cutoff",
                brightway_project="p", brightway_database="d", method_family="EF v3.1",
                artifact="nobody-exported-this.json",
            )],
        )
        stats = compare_scores(self.path, settings=settings)
        self.assertEqual(stats["releases_compared"], 1)
        self.assertEqual(stats["releases_without_artifact"], 1)
        self.assertEqual(stats["ecoinvent-3.8-apos.unit_processes"], 3)
        self.assertEqual(stats["ecoinvent-3.8-apos.their_categories_unmatched"], 3)
        connection = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        self.addCleanup(connection.close)
        self.assertEqual(
            connection.execute("SELECT release_key, artifact_sha256 != '' FROM score_releases").fetchall(),
            [("ecoinvent-3.8-apos", 1)],
        )

    def test_a_database_without_a_characterisation_is_refused(self):
        connection = sqlite3.connect(self.path)
        connection.execute("DROP TABLE lcia_runs")
        connection.commit()
        connection.close()
        with self.assertRaises(RuntimeError):
            compare_scores(self.path, settings=ScoreComparisonSettings(artifact_dir=FIXTURE.parent))

    def test_an_unknown_release_is_refused(self):
        with self.assertRaises(KeyError):
            compare_scores(self.path, settings=ScoreComparisonSettings(), releases=["ecoinvent-3.9.1-cutoff"])
