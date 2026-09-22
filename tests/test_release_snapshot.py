"""What `release-snapshot` reads out of a build, and that it reads back.

A fixture database with the real tables -- the flow tables, the run tables,
the merge tables and the LCIA tables -- holding two substances, three flows
(one deprecated), two factors and their source rows.  The snapshot is then
checked field by field, written, read back, and validated against its
generated schema.
"""

from __future__ import annotations

import gzip
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

import jsonschema
import orjson

from brightway_flows.domain.schema import (
    SchemaVersionError,
    release_migration_unresolved_schema,
    release_snapshot_schema,
)
from brightway_flows.domain.vocabulary import (
    CHEMINF_CAS_REGISTRY_NUMBER,
    OWL_DEPRECATED,
)
from brightway_flows.lcia.store import SCHEMA as LCIA_SCHEMA
from brightway_flows.merge.store import create_merge_tables
from brightway_flows.pipeline.review_tables import create_review_tables
from brightway_flows.pipeline.sqlite import _SCHEMA as FLOW_SCHEMA
from brightway_flows.releases.diff import diff_releases
from brightway_flows.releases.randonneur_files import unresolved_report
from brightway_flows.releases.snapshot import (
    RELEASE_SNAPSHOT_SCHEMA_VERSION,
    SnapshotError,
    build_snapshot,
    load_snapshot,
    read_stamp,
    snapshot_path,
    write_snapshot,
)
from brightway_flows.releases.version import (
    ReleaseVersion,
    ReleaseVersionError,
    named_version,
)

AIR = "https://vocab.brightway.one/flow-contexts/envi-air-unkn"
WATER = "https://vocab.brightway.one/flow-contexts/envi-wate-unkn"
COMMIT = "0123456789abcdef0123456789abcdef01234567"
CATEGORY = "3897dc04-68ec-5953-a76d-d40db54cc82a"
METHOD = "3c980711-0000-5000-8000-000000000001"


def _label(text: str) -> list[dict[str, str]]:
    return [{"@value": text, "@language": "en"}]


def _flow_payload(uuid: str, obj: str, *, context: str, label: str, **extra) -> dict:
    return {
        "uuid": uuid, "identifier": uuid, "source": "EF 3.1", "unit": "kg",
        "unit_iri": "https://vocab.brightway.one/units/unit/KiloGM",
        "context_iri": context, "flow_object_id": obj, "prefLabel": _label(label),
        "altLabel": _label("Cd"), "cas_numbers": ["7440-43-9"], "ec_numbers": [],
        "@type": ["https://w3id.org/chemrof/FullySpecifiedAtom"],
        "properties": {"https://w3id.org/chemrof/molecular_formula": {"@value": "Cd"}},
        "references": [{"@id": "https://example.org/cadmium"}],
        **extra,
    }


def _object_payload(obj: str, label: str, cas: str) -> dict:
    return {
        "flow_object_id": obj, "prefLabel": _label(label), "altLabel": _label("Cd"),
        "classifications": {
            CHEMINF_CAS_REGISTRY_NUMBER: {"@value": [cas], "provenance": {"who": "EF 3.1"}},
        },
        "properties": {}, "references": [], "@type": ["https://w3id.org/chemrof/FullySpecifiedAtom"],
    }


def write_fixture(path: Path, *, dirty: bool = False, characterised: bool = True) -> Path:
    with closing(sqlite3.connect(path)) as connection:
        for statement in FLOW_SCHEMA:
            connection.execute(statement)
        create_review_tables(connection)
        create_merge_tables(connection)
        connection.execute(
            "INSERT INTO pipeline_runs (run_id, timestamp, schema_version, git_commit, git_dirty) "
            "VALUES ('run-1', '2026-09-02T06:01:34+00:00', 1, ?, ?)", (COMMIT, int(dirty)),
        )
        connection.execute(
            "INSERT INTO merge_runs (run_id, started_at, finished_at, schema_version) "
            "VALUES ('merge-1', '2026-09-02T06:05:00+00:00', '2026-09-02T06:20:00+00:00', 2)"
        )
        connection.executemany(
            "INSERT INTO merge_run_inputs (run_id, list_name, list_version, sequence) VALUES (?, ?, ?, ?)",
            [("merge-1", "ecoinvent", "3.12", 1), ("merge-1", "bafu", "2026-v1", 2)],
        )
        connection.executemany(
            "INSERT INTO flow_objects (flow_object_id, pref_label_value, flow_object_json) VALUES (?, ?, ?)",
            [
                ("fo-1", "Cadmium", orjson.dumps(_object_payload("fo-1", "Cadmium", "7440-43-9"))),
                ("fo-2", "Lead", orjson.dumps(_object_payload("fo-2", "Lead", "7439-92-1"))),
            ],
        )
        flows = [
            ("f1", "fo-1", 0, None, _flow_payload("f1", "fo-1", context=AIR, label="Cadmium")),
            ("f2", "fo-1", 0, None, _flow_payload("f2", "fo-1", context=WATER, label="Cadmium")),
            ("f3", "fo-1", 1, "f1", _flow_payload(
                "f3", "fo-1", context=AIR, label="Cadmium",
                **{OWL_DEPRECATED: True, "is_replaced_by_uuid": "f1"},
            )),
        ]
        connection.executemany(
            "INSERT INTO elementary_flows (uuid, flow_object_id, pref_label_value, source, unit, "
            "is_deprecated, replaced_by_uuid, context_iri, flow_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (uuid, obj, "Cadmium", "EF 3.1", "kg", deprecated, replaced, payload["context_iri"],
                 orjson.dumps(payload))
                for uuid, obj, deprecated, replaced, payload in flows
            ],
        )
        connection.executemany(
            "INSERT INTO elementary_flow_sources (elementary_flow_uuid, list_name, list_version, "
            "source_flow_uuid, source_flow_name, source_metadata_json) VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("f1", "EF 3.1", "3.1", "f1", "Cadmium", '{"original_context": ["Emissions to air"]}'),
                ("f1", "ecoinvent", "3.12", "ei-1", "Cadmium", '{"original_context": ["air"]}'),
                ("f2", "EF 3.1", "3.1", "f2", "Cadmium", '{"original_context": ["Emissions to water"]}'),
                ("f3", "EF 3.1", "3.1", "f3", "Cadmium", '{"original_context": ["Emissions to air"]}'),
            ],
        )
        if characterised:
            for statement in LCIA_SCHEMA:
                connection.execute(statement)
            connection.execute(
                "INSERT INTO lcia_runs (run_id, started_at, finished_at, schema_version, build_run_id) "
                "VALUES ('lcia-1', '2026-09-02T06:21:00+00:00', '2026-09-02T06:21:21+00:00', 2, 'run-1')"
            )
            connection.execute(
                "INSERT INTO lcia_methods (id, name, iri) VALUES (?, 'EF', 'https://example.org/ef')",
                (METHOD,),
            )
            connection.execute(
                "INSERT INTO lcia_impact_categories (id, iri, method_id, name, version, implemented_by, "
                "timeframe, area_of_protection, midpoint_endpoint, uncertainty_cutoff, unit_iri) "
                "VALUES (?, 'https://example.org/ef/cc', ?, 'Climate change', '3.1', 'JRC', "
                "'long', 'climate', 'midpoint', 'none', 'https://example.org/kgco2')",
                (CATEGORY, METHOD),
            )
            connection.executemany(
                "INSERT INTO lcia_characterization_factors (impact_category_id, elementary_flow_uuid, "
                "geography, amount) VALUES (?, ?, ?, ?)",
                [(CATEGORY, "f1", "", 1.0), (CATEGORY, "f2", "CH", 2.5)],
            )
        connection.commit()
    return path


class SnapshotTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db = write_fixture(self.root / "consensus-flows.sqlite3")
        self.snapshot = build_snapshot(self.db, version=named_version("1.0.0"))

    def test_the_stamp_names_the_build(self):
        stamp = self.snapshot.stamp
        self.assertEqual((stamp.version, stamp.development), ("1.0.0", False))
        self.assertEqual(stamp.randonneur_id, "brightway-flows-1.0.0")
        self.assertEqual((stamp.run_id, stamp.revision, stamp.revision_dirty), ("run-1", COMMIT, False))
        self.assertEqual(stamp.merge_run_id, "merge-1")
        self.assertEqual(stamp.merged_lists, ["ecoinvent-3.12", "bafu-2026-v1"])
        self.assertEqual(stamp.characterise_run_id, "lcia-1")

    def test_every_flow_is_read_and_the_deprecated_one_is_marked(self):
        flows = self.snapshot.flows_by_identifier
        self.assertEqual(set(flows), {"f1", "f2", "f3"})
        self.assertEqual(set(self.snapshot.live_flows), {"f1", "f2"})
        self.assertTrue(flows["f3"].is_deprecated)
        self.assertEqual(flows["f3"].replaced_by_identifier, "f1")
        self.assertEqual(flows["f3"].deprecation_reason, "identity-merge")
        self.assertEqual(flows["f1"].flow_object_id, "fo-1")
        self.assertEqual(flows["f1"].prefLabel, "Cadmium")
        self.assertEqual(flows["f1"].altLabel, ["Cd"])
        self.assertEqual(
            flows["f1"].properties, {"https://w3id.org/chemrof/molecular_formula": "Cd"}
        )
        self.assertEqual(flows["f1"].references, ["https://example.org/cadmium"])

    def test_the_redirects_are_the_exports(self):
        """The deprecation in the fixture, plus the withdrawals the export
        publishes on every build from the source lists' curated files."""
        (redirect,) = [r for r in self.snapshot.redirects if r.reason == "identity-merge"]
        self.assertEqual((redirect.identifier, redirect.replaced_by_identifier), ("f3", "f1"))
        others = [r for r in self.snapshot.redirects if r.identifier != "f3"]
        self.assertTrue(others)
        self.assertEqual({r.reason for r in others}, {"source-row-withdrawn"})
        self.assertEqual({r.replaced_by_identifier for r in others}, {None})

    def test_a_substance_is_read_with_its_registry_numbers_inside_classifications(self):
        objects = self.snapshot.objects_by_id
        self.assertEqual(set(objects), {"fo-1", "fo-2"})
        self.assertEqual(objects["fo-1"].prefLabel, "Cadmium")
        self.assertEqual(objects["fo-1"].classifications, {CHEMINF_CAS_REGISTRY_NUMBER: ["7440-43-9"]})
        self.assertEqual(objects["fo-1"].types, ["https://w3id.org/chemrof/FullySpecifiedAtom"])
        self.assertNotIn("flow_object_id", objects["fo-1"].published_fields())

    def test_factors_are_read_by_their_triple(self):
        factors = self.snapshot.factors_by_key
        self.assertEqual(set(factors), {(CATEGORY, "f1", ""), (CATEGORY, "f2", "CH")})
        self.assertEqual(factors[(CATEGORY, "f2", "CH")].amount, 2.5)
        self.assertEqual(factors[(CATEGORY, "f1", "")].implemented_by, "JRC")

    def test_source_rows_are_read_per_list_and_version(self):
        self.assertEqual(
            self.snapshot.rows_by_key[("ecoinvent", "3.12", "ei-1")], {"f1"}
        )
        self.assertEqual(
            self.snapshot.rows_by_flow["f1"], {("EF 3.1", "3.1", "f1"), ("ecoinvent", "3.12", "ei-1")}
        )
        self.assertEqual(
            self.snapshot.source_lists, {("EF 3.1", "3.1"), ("ecoinvent", "3.12")}
        )

    def test_it_writes_and_reads_back_unchanged(self):
        path = write_snapshot(self.snapshot, snapshot_path("1.0.0", self.root / "releases"))
        self.assertEqual(path.name, "1.0.0.json.gz")
        loaded = load_snapshot(path)
        self.assertEqual(loaded.to_dict(), self.snapshot.to_dict())
        self.assertTrue(diff_releases(loaded, self.snapshot).is_empty())

    def test_it_validates_against_its_schema(self):
        document = orjson.loads(orjson.dumps(self.snapshot.to_dict()))
        jsonschema.validate(document, release_snapshot_schema())

    def test_the_unresolved_report_validates_against_its_schema(self):
        other = build_snapshot(self.db, version=named_version("1.1.0"))
        other.elementary_flows = [f for f in other.elementary_flows if f.identifier != "f1"]
        other.source_rows = [
            r for r in other.source_rows if r.elementary_flow_uuid != "f1"
        ] + [type(r)("EF 3.1", "3.1", "f1", "f2") for r in other.source_rows[:1]]
        # f1's EF row now lands on f2 and its ecoinvent row nowhere: one target,
        # so resolved; make it a split by sending the ecoinvent row elsewhere.
        other.source_rows.append(type(other.source_rows[0])("ecoinvent", "3.12", "ei-1", "f9"))
        other.elementary_flows.append(
            type(other.elementary_flows[0]).from_simple(
                other.elementary_flows[0], flow_object_id="fo-2"
            )
        )
        other.elementary_flows[-1].identifier = "f9"
        diff = diff_releases(self.snapshot, other)
        report = orjson.loads(orjson.dumps(unresolved_report(diff)))
        jsonschema.validate(report, release_migration_unresolved_schema())
        self.assertEqual(report["counts"]["by_reason"].get("split"), 1)

    def test_writing_twice_gives_the_same_bytes_but_for_the_creation_time(self):
        first = build_snapshot(self.db, version=named_version("1.0.0"))
        second = build_snapshot(self.db, version=named_version("1.0.0"))
        first.stamp.created = second.stamp.created = ""
        self.assertEqual(orjson.dumps(first.to_dict()), orjson.dumps(second.to_dict()))

    def test_a_build_nobody_characterised_has_no_factors(self):
        db = write_fixture(self.root / "bare.sqlite3", characterised=False)
        snapshot = build_snapshot(db, version=named_version("0.1.0"))
        self.assertEqual(snapshot.characterization_factors, [])
        self.assertEqual(snapshot.stamp.characterise_run_id, "")

    def test_a_modified_tree_is_refused_unless_named(self):
        db = write_fixture(self.root / "dirty.sqlite3", dirty=True)
        with self.assertRaises(ReleaseVersionError):
            read_stamp(db)
        self.assertEqual(read_stamp(db, version=named_version("x")).version, "x")


class LoadingTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_a_snapshot_of_another_version_is_refused(self):
        path = self.root / "old.json.gz"
        path.write_bytes(gzip.compress(orjson.dumps({
            "schema_version": RELEASE_SNAPSHOT_SCHEMA_VERSION + 1, "stamp": {},
        })))
        with self.assertRaises(SchemaVersionError):
            load_snapshot(path)

    def test_a_missing_file_says_so(self):
        with self.assertRaises(SnapshotError):
            load_snapshot(self.root / "nowhere.json.gz")

    def test_a_plain_json_snapshot_is_read_too(self):
        path = self.root / "plain.json"
        path.write_bytes(orjson.dumps({
            "schema_version": RELEASE_SNAPSHOT_SCHEMA_VERSION,
            "stamp": {
                "version": "1.0.0", "development": False, "run_id": "r", "revision": "",
                "revision_dirty": False, "timestamp": "",
            },
        }))
        self.assertEqual(load_snapshot(path).stamp.version, "1.0.0")


class VersionTestCase(unittest.TestCase):
    def test_a_development_build_carries_the_modifier(self):
        self.assertEqual(
            ReleaseVersion("1.0.0-3-gabcdef0", development=True).randonneur_id,
            "brightway-flows-1.0.0-3-gabcdef0-dev",
        )
        self.assertEqual(ReleaseVersion("1.0.0").randonneur_id, "brightway-flows-1.0.0")

    def test_a_name_given_by_hand_is_a_release(self):
        self.assertEqual(named_version(" 2.0.0 "), ReleaseVersion("2.0.0", development=False))
        with self.assertRaises(ReleaseVersionError):
            named_version("  ")


if __name__ == "__main__":
    unittest.main()
