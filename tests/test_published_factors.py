"""The published LCIA artifacts, and the count that must not move.

Two things are being proved here, and the second is the one with a reader
downstream.

**The files say what the tables say.**  `lcia-factors.json.gz` and
`lcia-differences.json` are written from the same records `write_characterisation`
was handed, in the same call, and each validates against the JSON Schema checked
in beside it.  A consumer who never opens SQLite gets the same run.

**`lcia_factor_count` keeps its meaning.**  It has always been the JRC's non-zero
factors, and there are three implementations now, so the obvious thing to do --
widen it -- would silently change every query anybody has written against it.  It
stays as it was, and `lcia_flow_factor_counts` is the per-implementation count
beside it: a view, so it cannot drift from the factors it counts.  Over the full
build of 2026-08-17 the two agree for **all 95,689 flows** -- 267,487 non-zero JRC
factors summed either way, and zero flows where the column and the view disagree.
These state the same invariant, small enough to run in a second.
"""

from __future__ import annotations

import gzip
import sqlite3
import tempfile
import unittest
from dataclasses import fields
from pathlib import Path

import orjson
from jsonschema import Draft202012Validator

from brightway_flows.domain.lcia.crosswalk import ef_method
from brightway_flows.domain.lcia.records import (
    LCIA_SCHEMA_VERSION,
    CharacterizationFactor,
)
from brightway_flows.domain.schema import build_all, check_schema_version
from brightway_flows.filesystem import (
    LCIA_DIFFERENCES_FILEPATH,
    LCIA_FACTORS_FILEPATH,
)
from brightway_flows.lcia.pipeline import characterise
from brightway_flows.lcia.publish import artifact_paths
from brightway_flows.sources import LciaMethodSpec, LciaSpec, SourceList
from brightway_flows.webapps.app.queries.flows import _factor_counts

#: EF 3.1's implementations, read from its method file rather than from an enum:
#: an implementation belongs to a method, and which four these are is what
#: `data/lcia-impact-categories.json` says.
_METHOD = ef_method()
JRC_IMPL = _METHOD.reference
ECOINVENT_IMPL = _METHOD.implementation("ecoinvent-centre")
GREENDELTA_IMPL = _METHOD.implementation("greendelta")
CONSENSUS_IMPL = _METHOD.consensus
IMPLEMENTATION_NAMES = {row.name for row in _METHOD.implementations}

#: Two crosswalked categories, so one flow can carry a number and a stated zero
#: without the two colliding on the key that says they are one factor.
FIRST, SECOND = sorted(ef_method().by_stated_identifier("jrc"))[:2]


def _entry(method_uuid: str, amount: float) -> dict:
    """One `lcia_methods` row as EF's files state it."""
    definition = ef_method().by_stated_identifier("jrc")[method_uuid]
    return {
        "method_uuid": method_uuid,
        "name": definition.stated["jrc"].name,
        "methodology": "Environmental Footprint",
        "impact_category": definition.stated["jrc"].name,
        "impact_indicator": definition.stated["jrc"].indicator,
        "characterization_factor": amount,
    }


class ARunThatPublishesTestCase(unittest.TestCase):
    """One build, two flows, three implementations, and both files written."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.db = root / "consensus-flows.sqlite3"
        # `cf-1` carries a number and a stated zero, so its count and its
        # non-zero count differ -- which is the whole reason for keeping two.
        flows = [
            ("cf-1", "fo-1", "Ammonia", "Environmental → Air → Unknown", "ctx-air",
             1, [_entry(FIRST, 1.5), _entry(SECOND, 0.0)]),
            ("cf-2", "fo-2", "Copper", "Environmental → Ground → Silvicultural",
             "ctx-silv", 0, []),
        ]
        connection = sqlite3.connect(self.db)
        connection.execute(
            "CREATE TABLE elementary_flows (uuid TEXT, flow_object_id TEXT, "
            "pref_label_value TEXT, context_display TEXT, context_iri TEXT, "
            "unit TEXT, is_deprecated INTEGER, replaced_by_uuid TEXT, "
            "lcia_factor_count INTEGER, "
            "flow_json TEXT, context_dimension TEXT, context_media TEXT)"
        )
        connection.execute(
            "CREATE TABLE elementary_flow_sources (elementary_flow_uuid TEXT, "
            "list_name TEXT, list_version TEXT, source_flow_uuid TEXT, "
            "source_metadata_json TEXT)"
        )
        connection.execute("CREATE TABLE pipeline_runs (run_id TEXT, timestamp TEXT)")
        # The substances, because `characterise` reads their registry numbers:
        # what somebody else's model states arrives keyed on CAS and nothing else
        # (`lcia.contradictions`). Neither of these is in the evidence file.
        connection.execute(
            "CREATE TABLE flow_objects (flow_object_id TEXT, "
            "pref_label_value TEXT, classifications_json TEXT, "
            "properties_json TEXT)"
        )
        connection.executemany(
            "INSERT INTO flow_objects (flow_object_id, pref_label_value, "
            "classifications_json) VALUES (?, ?, '{}')",
            [("fo-1", "Ammonia"), ("fo-2", "Copper")],
        )
        connection.executemany(
            "INSERT INTO elementary_flows VALUES (?, ?, ?, ?, ?, 'kg', 0, NULL, ?, ?, ?, ?)",
            [
                (uuid, object_id, label, context, iri, count,
                 orjson.dumps({"lcia_methods": entries}).decode(),
                 # The dimension and media the real table carries, derived from
                 # the display name so the fixture cannot disagree with itself.
                 *context.split(" → ")[:2])
                for uuid, object_id, label, context, iri, count, entries in flows
            ],
        )
        connection.executemany(
            "INSERT INTO elementary_flow_sources VALUES (?, ?, ?, ?, ?)",
            [
                ("cf-1", "ecoinvent", "3.12", "ei-1",
                 orjson.dumps({"unit": "kg"}).decode()),
                # GreenDelta's package names flows by the ecoinvent UUID it was
                # built against, so its row is resolved through a release of
                # ecoinvent's -- 3.8 here, to exercise the chain rather than the
                # list that happens to be first.
                ("cf-1", "ecoinvent", "3.8", "gd-1",
                 orjson.dumps({"unit": "kg"}).decode()),
            ],
        )
        connection.execute(
            "INSERT INTO pipeline_runs VALUES (?, ?)", ("build-9", "2026-08-17")
        )
        connection.commit()
        connection.close()

        # ecoinvent states the same number for the same category, so the
        # consensus implementation has something to agree with and all four
        # implementations appear in the counts.
        ecoinvent_name = ef_method().by_stated_identifier("jrc")[FIRST].stated["ecoinvent-centre"].name
        factors_path = root / "ecoinvent-3.12-lcia-factors.json"
        factors_path.write_bytes(orjson.dumps({
            "schema_version": 1,
            "methods": [{
                "method": "EF v3.1",
                "categories": [
                    {"category": ecoinvent_name, "indicator": "i", "unit": "u"}
                ],
                "factors": [
                    {"flow_uuid": "ei-1", "category": ecoinvent_name, "amount": 1.5}
                ],
            }],
        }))
        self.source = SourceList(
            list_name="ecoinvent",
            list_version="3.12",
            flows_path=root / "flows.json",
            lcia=LciaSpec(
                adapter="brightway_flows.integrations.ecoinvent_lcia:fetch",
                factors_path=factors_path,
                methods=(LciaMethodSpec(name="EF v3.1", no_long_term=None),),
                implemented_by="ecoinvent Centre",
            ),
        )
        # And GreenDelta's, in the shape their adapter writes: a category
        # addressed by the JRC's own UUID, and a geography on the row.
        greendelta_path = root / "bafu-greendelta-lcia-factors.json"
        greendelta_name = ef_method().by_stated_identifier("jrc")[FIRST].stated["greendelta"].name
        greendelta_path.write_bytes(orjson.dumps({
            "schema_version": 1,
            "methods": [{
                "method": "EF 3.1 Method (adapted)",
                "categories": [
                    {"category": greendelta_name, "category_uuid": FIRST,
                     "unit": "u", "factor_count": 1}
                ],
                "factors": [
                    {"flow_uuid": "gd-1", "category": greendelta_name,
                     "category_uuid": FIRST, "amount": 1.5, "geography": None}
                ],
                "flows": [
                    {"uuid": "gd-1", "name": "Ammonia",
                     "category": "Elementary flows/Emission to air/unspecified",
                     "unit": "kg", "cas": ""}
                ],
            }],
        }))
        self.greendelta = SourceList(
            list_name="bafu",
            list_version="2026-v1",
            flows_path=root / "flows.json",
            lcia=LciaSpec(
                adapter="brightway_flows.integrations.greendelta_lcia:fetch",
                factors_path=greendelta_path,
                methods=(LciaMethodSpec(name="EF 3.1 Method (adapted)"),),
                implemented_by="GreenDelta",
                resolve_through=("ecoinvent-3.12", "ecoinvent-3.8"),
            ),
        )
        self.stats = characterise(
            self.db,
            source_lists={
                "ecoinvent-3.12": self.source,
                "bafu-2026-v1": self.greendelta,
            },
        )
        self.factors_path, self.differences_path = artifact_paths(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def _rows(self, sql, parameters=()):
        connection = sqlite3.connect(self.db)
        try:
            return connection.execute(sql, parameters).fetchall()
        finally:
            connection.close()

    def _factors(self) -> dict:
        return orjson.loads(gzip.decompress(self.factors_path.read_bytes()))

    def _differences(self) -> dict:
        return orjson.loads(self.differences_path.read_bytes())


class TheCountThatMustNotMoveTestCase(ARunThatPublishesTestCase):
    def test_the_view_reproduces_the_column_for_every_flow(self):
        """A LEFT JOIN, because a flow with no factors has no row in the view and
        that absence has to read as zero rather than as a missing answer."""
        rows = self._rows(
            """
            SELECT flow.uuid, flow.lcia_factor_count, coalesce(counted.non_zero, 0)
            FROM elementary_flows AS flow
            LEFT JOIN (
                SELECT elementary_flow_uuid, non_zero_factors AS non_zero
                FROM lcia_flow_factor_counts
                WHERE implemented_by = ?
            ) AS counted ON counted.elementary_flow_uuid = flow.uuid
            ORDER BY flow.uuid
            """,
            (JRC_IMPL.name,),
        )
        self.assertEqual(rows, [("cf-1", 1, 1), ("cf-2", 0, 0)])
        for uuid, column, view in rows:
            with self.subTest(flow=uuid):
                self.assertEqual(column, view)

    def test_a_stated_zero_is_counted_but_not_as_a_non_zero(self):
        """#47 kept the zeros, because "assessed, and zero" is not "never
        assessed".  The column has never counted them and still does not; the
        view is where a reader finds out how many there are."""
        counts = dict(self._rows(
            "SELECT implemented_by, factors || '/' || non_zero_factors "
            "FROM lcia_flow_factor_counts WHERE elementary_flow_uuid = 'cf-1'"
        ))
        self.assertEqual(counts[JRC_IMPL.name], "2/1")

    def test_each_implementation_is_counted_separately(self):
        """The question `lcia_factor_count` cannot answer now that there are
        four of them."""
        self.assertEqual(
            sorted(self._rows(
                "SELECT implemented_by, factors FROM lcia_flow_factor_counts "
                "WHERE elementary_flow_uuid = 'cf-1'"
            )),
            [
                (JRC_IMPL.name, 2),
                (GREENDELTA_IMPL.name, 1),
                # The consensus implementation republishes both of the JRC's: one
                # number the two agreed on, and one only the JRC stated.
                (CONSENSUS_IMPL.name, 2),
                (ECOINVENT_IMPL.name, 1),
            ],
        )

    def test_the_count_cannot_drift_from_the_factors(self):
        """It is a view and not a table, which is the property being asserted: a
        factor that goes away takes its count with it, and nothing has to
        remember to recompute anything."""
        before = self._rows(
            "SELECT sum(factors) FROM lcia_flow_factor_counts "
            "WHERE elementary_flow_uuid = 'cf-1'"
        )
        self.assertEqual(before, [(6,)])
        connection = sqlite3.connect(self.db)
        try:
            connection.execute(
                "DELETE FROM lcia_characterization_factors "
                "WHERE elementary_flow_uuid = 'cf-1' AND amount = 0"
            )
            connection.commit()
        finally:
            connection.close()
        self.assertEqual(
            self._rows(
                "SELECT sum(factors) FROM lcia_flow_factor_counts "
                "WHERE elementary_flow_uuid = 'cf-1'"
            ),
            [(4,)],
        )


class WhatTheReviewAppShowsTestCase(ARunThatPublishesTestCase):
    """The page leads with the consensus count; the column keeps the JRC's."""

    def _counts(self):
        connection = sqlite3.connect(self.db)
        connection.row_factory = sqlite3.Row
        try:
            return _factor_counts(connection, "cf-1")
        finally:
            connection.close()

    def test_the_consensus_implementation_is_first(self):
        """Not the largest count: the implementation this list publishes."""
        counts = self._counts()
        self.assertEqual(counts[0].implemented_by, CONSENSUS_IMPL.name)
        self.assertEqual(
            {count.implemented_by for count in counts},
            IMPLEMENTATION_NAMES,
        )

    def test_a_count_says_how_many_of_its_factors_are_zero(self):
        """One number would have to choose between "states 2" and "states 1 and a
        zero", and #47 is the reason both are worth having."""
        jrc = next(
            count for count in self._counts()
            if count.implemented_by == JRC_IMPL.name
        )
        self.assertEqual((jrc.factors, jrc.non_zero_factors, jrc.zeros), (2, 1, 1))

    def test_a_build_without_a_characterisation_shows_nothing(self):
        """Three zeros would read as "characterised by nobody", which is a
        different statement from "nobody has asked yet"."""
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        self.addCleanup(connection.close)
        self.assertEqual(_factor_counts(connection, "cf-1"), [])


class TheFilesTestCase(ARunThatPublishesTestCase):
    def test_both_artifacts_are_written_beside_the_database(self):
        """Never into the data directory: a run against a build somewhere else
        must not overwrite the published files."""
        self.assertTrue(self.factors_path.exists())
        self.assertTrue(self.differences_path.exists())
        self.assertEqual(self.factors_path.parent, self.db.parent)
        self.assertEqual(self.factors_path.name, LCIA_FACTORS_FILEPATH.name)
        self.assertEqual(self.differences_path.name, LCIA_DIFFERENCES_FILEPATH.name)

    def test_the_factors_file_validates_against_its_schema(self):
        errors = Draft202012Validator(
            build_all()["lcia-factors.json"]
        ).iter_errors(self._factors())
        self.assertEqual([error.message for error in errors], [])

    def test_the_differences_file_validates_against_its_schema(self):
        errors = Draft202012Validator(
            build_all()["lcia-differences.json"]
        ).iter_errors(self._differences())
        self.assertEqual([error.message for error in errors], [])

    def test_both_declare_the_lcia_version_and_not_the_flow_lists(self):
        for artifact, document in (
            ("lcia-factors.json", self._factors()),
            ("lcia-differences.json", self._differences()),
        ):
            with self.subTest(artifact=artifact):
                self.assertEqual(
                    check_schema_version(
                        document, artifact=artifact, expected=LCIA_SCHEMA_VERSION
                    ),
                    LCIA_SCHEMA_VERSION,
                )

    def test_the_file_holds_every_category_and_factor_the_tables_do(self):
        document = self._factors()
        self.assertEqual(
            len(document["impact_categories"]),
            self._rows("SELECT count(*) FROM lcia_impact_categories")[0][0],
        )
        self.assertEqual(
            len(document["characterization_factors"]),
            self._rows("SELECT count(*) FROM lcia_characterization_factors")[0][0],
        )

    def test_a_published_category_carries_no_factor_list(self):
        """The factors are published once, under a key of their own.  A category
        carrying an empty `characterization_factors` beside 665,487 of them in
        the same file would say something untrue about what it holds."""
        for category in self._factors()["impact_categories"]:
            with self.subTest(category=category["name"]):
                self.assertNotIn("characterization_factors", category)

    def test_a_factor_is_its_category_its_flow_and_its_place(self):
        factor = next(
            row for row in self._factors()["characterization_factors"]
            if row["amount"] == 1.5 and row["derivation"] is None
        )
        self.assertEqual(factor["elementary_flow_uuid"], "cf-1")
        self.assertIn("impact_category_id", factor)
        self.assertNotIn("id", factor)
        self.assertEqual(
            set(factor), {field.name for field in fields(CharacterizationFactor)}
        )

    def test_every_implementation_of_every_method_is_in_the_file(self):
        """The categories come from the method files, not from the factors.

        So a method whose list this run did not merge still has its category
        rows in the file, carrying no factors -- which is what
        `consensus_categories_awaiting_factors` counts. Stepwise 2006's
        publisher is here for that reason: it is a registered method, and this
        fixture merges no Stepwise flows.
        """
        from brightway_flows.domain.lcia.crosswalk import lcia_methods

        expected = {
            implementation.name
            for method in lcia_methods()
            for implementation in method.implementations
        }
        self.assertEqual(
            {
                category["implemented_by"]
                for category in self._factors()["impact_categories"]
            },
            expected,
        )
        # The EF names are still all of them, which is what this asserted before
        # a second method existed.
        self.assertTrue(IMPLEMENTATION_NAMES <= expected)

    def test_a_consensus_factor_says_how_it_was_derived(self):
        derivations = {
            row["derivation"] for row in self._factors()["characterization_factors"]
        }
        self.assertIn("agreed", derivations)
        # A transcription arrives at nothing: it says what its publisher said.
        self.assertIn(None, derivations)

    def test_the_differences_file_carries_both_of_the_reports(self):
        """One row per (triple, implementation): the two rows here are the two
        implementations of one comparison, sharing its band."""
        document = self._differences()
        self.assertEqual(
            sorted(
                (row["implemented_by"], row["band"])
                for row in document["differences"]
            ),
            sorted([
                (ECOINVENT_IMPL.name, "identical"),
                (GREENDELTA_IMPL.name, "identical"),
                (JRC_IMPL.name, "identical"),
            ]),
        )
        self.assertIn("coverage", document)
        # The run's own counts, so a reader can check the file against the
        # numbers its publisher quoted without recomputing them.
        self.assertEqual(document["stats"]["difference_shared"], 1)

    def test_running_it_again_writes_the_same_bytes(self):
        """The files are a projection of one build, so an unchanged build has
        nothing new to say -- and a reshuffled array would read as a change."""
        factors = gzip.decompress(self.factors_path.read_bytes())
        differences = self.differences_path.read_bytes()
        characterise(
            self.db,
            source_lists={
                "ecoinvent-3.12": self.source,
                "bafu-2026-v1": self.greendelta,
            },
        )
        self.assertEqual(gzip.decompress(self.factors_path.read_bytes()), factors)
        self.assertEqual(self.differences_path.read_bytes(), differences)


if __name__ == "__main__":
    unittest.main()
