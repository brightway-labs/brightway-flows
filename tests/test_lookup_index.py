"""The lookup reads columns; the merge reads payloads; the indexes must agree.

`plans/lookup-api.md` §1.2 measures what the merge's own load costs -- 8.3 s and
950 MB to parse every `flow_object_json` and `flow_json`, and another 6.0 s and
900 MB to deep-copy the result -- and observes that matching needs none of it.
The selector reads four fields off a candidate and the indexes need five off a
flow object, and every one of the nine is a *column*.

So `lookup/index.py` reads the columns.  That is only a shortcut if it produces
the same indexes, and this file is what says so: both loads are run against one
fixture database and the indexes compared key for key.  If a field ever moves out
of a column and into the JSON, this fails -- rather than the lookup quietly
matching less than the build would.

The two guards are here for the same reason.  A lookup answers *for one build*,
so a database that cannot name its build, or that is half-written, or that holds
a slice somebody chose for a smoke run, has to be refused before a flow is read.
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest

from pathlib import Path
from unittest import mock

from brightway_flows.domain.context_registry import context_for_iri
from brightway_flows.domain.elementary_flow import ElementaryFlow
from brightway_flows.domain.flow import Flow
from brightway_flows.domain.flow_object import FlowObject
from brightway_flows.domain.vocabulary import (
    CHEMINF_CAS_REGISTRY_NUMBER,
    CHEMINF_EC_NUMBER,
)
from brightway_flows.lookup.index import (
    BuildStamp,
    UnusableBuildError,
    load_lookup_index,
    lookup_source_list,
)
from brightway_flows.merge.contexts import ContextExpectations
from brightway_flows.merge.matching import (
    _load_working_set,
    build_merge_accumulator,
    build_merge_indexes,
)
from brightway_flows.pipeline.review_tables import create_review_tables
from brightway_flows.pipeline.sqlite import _write_consensus_sqlite

PREFIX = "https://vocab.brightway.one/flow-contexts/"
AIR = PREFIX + "envi-air-unkn"
INDOOR = PREFIX + "envi-air-indr-unkn"
WATER = PREFIX + "envi-wate-unkn"

RUN_ID = "20260821T0000000000000000"
REVISION = "8be43a31ae7dfcb6704e10cac76840c734111595"
MERGE_RUN_ID = "a6c75ce74cb349af8f344507950a3142"


def _classification(predicate: str, *values: str) -> dict:
    return {predicate: {"@value": list(values)}}


def _flow_object(
    flow_object_id: str,
    name: str,
    *,
    alt_labels: tuple[str, ...] = (),
    cas: tuple[str, ...] = (),
    ec: tuple[str, ...] = (),
    qualifier: str | None = None,
) -> FlowObject:
    classifications: dict = {}
    if cas:
        classifications.update(_classification(CHEMINF_CAS_REGISTRY_NUMBER, *cas))
    if ec:
        classifications.update(_classification(CHEMINF_EC_NUMBER, *ec))
    return FlowObject(
        flow_object_id=flow_object_id,
        prefLabel=[{"@value": name, "@language": "en"}],
        altLabel=[{"@value": value, "@language": "en"} for value in alt_labels],
        properties={},
        references=[],
        created_from={"resolver": "fixture"},
        classifications=classifications,
        origin_qualifier=qualifier,
    )


def _flow(
    uuid: str, name: str, *, flow_object_id: str, context_iri: str, unit: str = "kg"
) -> Flow:
    return Flow(
        uuid=uuid,
        source="EF 3.1",
        unit=unit,
        prefLabel=[{"@value": name, "@language": "en"}],
        context=context_for_iri(context_iri),
        context_iri=context_iri,
        flow_object_id=flow_object_id,
    )


def _elementary(
    uuid: str,
    flow_object_id: str,
    *,
    context_iri: str,
    unit: str = "kg",
    deprecated: bool = False,
) -> ElementaryFlow:
    return ElementaryFlow(
        elementary_flow_id=uuid,
        flow_object_id=flow_object_id,
        source="EF 3.1",
        context=context_for_iri(context_iri),
        context_iri=context_iri,
        unit=unit,
        unit_iri="",
        lcia_methods=[],
        general_comment=None,
        owl_deprecated=True if deprecated else None,
    )


#: A list broad enough to exercise every index the merge builds: two substances
#: sharing a CAS and told apart by an origin qualifier, an EC number, an
#: alternative label, a substance with no registry number at all, and a
#: deprecated flow that must reach neither the candidate map nor the count.
def _fixture() -> tuple[list[Flow], list[FlowObject], list[ElementaryFlow]]:
    flow_objects = [
        _flow_object(
            "fo-benzene",
            "Benzene",
            alt_labels=("Benzol",),
            cas=("71-43-2",),
            ec=("200-753-7",),
        ),
        _flow_object("fo-water", "Water", cas=("7732-18-5",)),
        _flow_object(
            "fo-water-lake", "Water, lake", cas=("7732-18-5",), qualifier="blue_water"
        ),
        _flow_object("fo-noise", "Noise", alt_labels=("Sound",)),
    ]
    elementary = [
        _elementary("ef-benzene-air", "fo-benzene", context_iri=AIR),
        _elementary("ef-benzene-indoor", "fo-benzene", context_iri=INDOOR),
        _elementary("ef-benzene-water", "fo-benzene", context_iri=WATER),
        _elementary("ef-water-water", "fo-water", context_iri=WATER, unit="m3"),
        _elementary("ef-water-lake", "fo-water-lake", context_iri=WATER, unit="m3"),
        _elementary("ef-noise-air", "fo-noise", context_iri=AIR, unit="dimensionless"),
        _elementary("ef-benzene-old", "fo-benzene", context_iri=AIR, deprecated=True),
    ]
    flows = [
        _flow(
            row.elementary_flow_id,
            "fixture",
            flow_object_id=row.flow_object_id,
            context_iri=row.context_iri,
            unit=row.unit or "kg",
        )
        for row in elementary
    ]
    for flow, row in zip(flows, elementary):
        if row.owl_deprecated:
            flow.owl_deprecated = True
    return flows, flow_objects, elementary


def _write_run_tables(
    db_path: Path,
    *,
    max_flows: int | None = None,
    merge_finished: bool = True,
    max_rows: int | None = None,
    with_merge: bool = True,
) -> None:
    """The two tables a build's stages record themselves in.

    Written with the real DDL rather than a hand-rolled one, so a column
    renamed under the lookup's guards fails here.
    """
    from brightway_flows.merge.store import create_merge_tables

    connection = sqlite3.connect(db_path)
    try:
        create_review_tables(connection)
        connection.execute(
            "INSERT INTO pipeline_runs (run_id, timestamp, schema_version, dry_run, "
            "max_flows, flow_count, change_count, git_commit, git_dirty) "
            "VALUES (?, ?, 1, 0, ?, 7, 0, ?, 0)",
            (RUN_ID, "2026-08-21T00:00:00+00:00", max_flows, REVISION),
        )
        if with_merge:
            create_merge_tables(connection)
            connection.execute(
                "INSERT INTO merge_runs (run_id, started_at, finished_at, schema_version) "
                "VALUES (?, ?, ?, 1)",
                (
                    MERGE_RUN_ID,
                    "2026-08-21T00:00:00+00:00",
                    "2026-08-21T00:12:00+00:00" if merge_finished else None,
                ),
            )
            for sequence, (name, version) in enumerate(
                (("ecoinvent", "3.12"), ("bafu", "2026-v1"))
            ):
                connection.execute(
                    "INSERT INTO merge_run_inputs (run_id, list_name, list_version, "
                    "sequence, row_count, available_row_count, max_rows) "
                    "VALUES (?, ?, ?, ?, 10, 10, ?)",
                    (MERGE_RUN_ID, name, version, sequence, max_rows),
                )
        connection.commit()
    finally:
        connection.close()


def _fixture_database(tmp: Path, **run_tables) -> Path:
    db_path = tmp / "consensus-flows.sqlite3"
    flows, flow_objects, elementary = _fixture()
    _write_consensus_sqlite(flows, [], flow_objects, elementary, db_path=db_path)
    _write_run_tables(db_path, **run_tables)
    return db_path


class _Fixture(unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.tmp = Path(tempfile.mkdtemp())
        self.db_path = _fixture_database(self.tmp)


class TheProjectionBuildsTheSameIndexesTestCase(_Fixture):
    """The obligation §3.4 states, and the reason the shortcut is allowed.

    Both loads run against one database. The merge's parses every
    `flow_object_json` and every `flow_json`; the lookup's reads five columns and
    four. If they agree on every index, the second is the first done cheaply.
    """

    def _merge_indexes(self):
        flow_objects, _elementary = _load_working_set(self.db_path)
        return build_merge_indexes(
            flow_objects,
            context_expectations=ContextExpectations(
                _by_source_context={}, _source_label="lookup-query"
            ),
            consensus_context_strings={},
            prepared_context_decisions={},
            mapping_file=None,
            source=lookup_source_list(simapro_origin=False),
        )

    def test_every_identifier_and_label_index_is_equal_key_for_key(self):
        merge = self._merge_indexes()
        lookup, _by_object, _stamp = load_lookup_index(self.db_path)
        for name in (
            "cas_index",
            "ec_index",
            "label_index",
            "pref_label_index",
            "qualifier_index",
        ):
            with self.subTest(index=name):
                self.assertEqual(getattr(lookup, name), getattr(merge, name))
                self.assertTrue(getattr(merge, name), f"{name} is empty, so it proves nothing")

    def test_the_cas_bearing_subset_and_the_by_id_views_are_equal(self):
        merge = self._merge_indexes()
        lookup, _by_object, _stamp = load_lookup_index(self.db_path)
        self.assertEqual(lookup.flow_objects_with_cas, merge.flow_objects_with_cas)
        self.assertEqual(lookup.flow_object_label_by_id, merge.flow_object_label_by_id)
        self.assertEqual(
            sorted(lookup.flow_objects_by_id), sorted(merge.flow_objects_by_id)
        )

    def test_the_candidate_map_holds_the_same_flows_in_the_same_order(self):
        """`elementary_by_object` is what the selector picks candidates out of,
        and the four fields it scores on are the whole of what a candidate is
        for this purpose."""
        _flows, elementary = _load_working_set(self.db_path)
        merge = build_merge_accumulator(elementary).elementary_by_object
        _indexes, lookup, _stamp = load_lookup_index(self.db_path)

        def comparable(rows):
            return [
                (
                    row.elementary_flow_id,
                    row.unit,
                    row.context_iri,
                    tuple(_display(row)),
                )
                for row in rows
            ]

        from brightway_flows.domain.context_registry import context_display_parts

        def _display(row):
            return context_display_parts(row.context)

        self.assertEqual(sorted(lookup), sorted(merge))
        for object_id in sorted(merge):
            with self.subTest(flow_object=object_id):
                self.assertEqual(comparable(lookup[object_id]), comparable(merge[object_id]))

    def test_the_deprecated_flow_is_in_neither_map(self):
        """The premise of the comparison above: both sides drop it, so agreeing
        about it is not agreeing about nothing."""
        _flows, elementary = _load_working_set(self.db_path)
        merge = build_merge_accumulator(elementary).elementary_by_object
        _indexes, lookup, stamp = load_lookup_index(self.db_path)
        for source, rows in (("merge", merge), ("lookup", lookup)):
            with self.subTest(side=source):
                ids = {row.elementary_flow_id for group in rows.values() for row in group}
                self.assertNotIn("ef-benzene-old", ids)
                self.assertIn("ef-benzene-air", ids)
        self.assertEqual(stamp.elementary_flow_count, 6)

    def test_the_projected_records_carry_only_what_matching_reads(self):
        """Partial by construction, and deliberately so -- which is why they do
        not leave the package. A caller's answer is read from `flow_json` for the
        one winning row."""
        _indexes, by_object, _stamp = load_lookup_index(self.db_path)
        row = by_object["fo-benzene"][0]
        self.assertEqual(row.source, "")
        self.assertEqual(row.lcia_methods, [])
        self.assertIsNone(row.general_comment)
        self.assertTrue(row.elementary_flow_id)
        self.assertTrue(row.context_iri)


class TheSameComparisonAgainstARealBuildTestCase(unittest.TestCase):
    """The fixture above is nine flows; a build is ninety-six thousand.

    Skipped where there is no build, because most runs of this suite have none
    and a test that needs one would be a test nobody runs. Where there *is* one
    -- a worktree that has just built, or CI after a build step -- it is the same
    comparison over the real thing, which is the evidence that matters: the
    fixture proves the projection agrees with the full load about data this file
    wrote, and this proves it about data the pipeline wrote.

    Measured on the 21 August 2026 build of `8be43a3`: 7,984 flow objects and
    96,277 active flows, and every index equal.
    """

    def setUp(self) -> None:
        super().setUp()
        from brightway_flows.filesystem import CONSENSUS_DB_FILEPATH

        if not CONSENSUS_DB_FILEPATH.exists():
            self.skipTest(f"no build at {CONSENSUS_DB_FILEPATH}")
        self.db_path = CONSENSUS_DB_FILEPATH
        try:
            self.lookup, self.by_object, self.stamp = load_lookup_index(self.db_path)
        except UnusableBuildError as error:
            self.skipTest(str(error))

    def _merge_indexes(self):
        flow_objects, _elementary = _load_working_set(self.db_path)
        return build_merge_indexes(
            flow_objects,
            context_expectations=ContextExpectations(
                _by_source_context={}, _source_label="lookup-query"
            ),
            consensus_context_strings={},
            prepared_context_decisions={},
            mapping_file=None,
            source=lookup_source_list(simapro_origin=False),
        )

    def test_every_index_is_equal_over_the_whole_build(self):
        merge = self._merge_indexes()
        for name in (
            "cas_index",
            "ec_index",
            "label_index",
            "pref_label_index",
            "qualifier_index",
            "flow_objects_with_cas",
            "flow_object_label_by_id",
        ):
            with self.subTest(index=name):
                self.assertEqual(getattr(self.lookup, name), getattr(merge, name))
        self.assertEqual(
            sorted(self.lookup.flow_objects_by_id), sorted(merge.flow_objects_by_id)
        )

    def test_the_candidate_map_is_equal_over_the_whole_build(self):
        _flows, elementary = _load_working_set(self.db_path)
        merge = build_merge_accumulator(elementary).elementary_by_object

        from brightway_flows.domain.context_registry import context_display_parts

        def comparable(rows):
            return sorted(
                (
                    row.elementary_flow_id,
                    row.unit or "",
                    row.context_iri,
                    tuple(context_display_parts(row.context)),
                )
                for row in rows
            )

        self.assertEqual(sorted(self.by_object), sorted(merge))
        differing = [
            object_id
            for object_id in merge
            if comparable(self.by_object[object_id]) != comparable(merge[object_id])
        ]
        self.assertEqual(differing, [])


class TheContextExpectationsFieldIsUnusedTestCase(_Fixture):
    """It is empty on purpose, and that is only safe while nothing reads it.

    `ContextExpectations` asks three rules in order and all three key on the
    list's own `source` string, which for a query is a synthetic label no rule is
    written under. Filling it with the compartment rules read across every list
    would look like an improvement and would be a defect: four of those 90
    compartments are ones a list has already ruled its flows' *names* have to
    decide, so `natural resource / land` would answer `laus-occu` and file a
    caller's land transformation as an occupation. That is #52.

    `lookup/query.py` resolves context instead. This holds the two functions the
    lookup actually calls to not caring.
    """

    def test_it_is_empty(self):
        indexes, _by_object, _stamp = load_lookup_index(self.db_path)
        self.assertIsNone(
            indexes.context_expectations.resolve("any-uuid", ["natural resource", "land"], "Occupation, x")
        )

    def test_neither_matching_function_mentions_it(self):
        """Read off the source, because the alternative is trusting that a call
        site nobody has looked at recently still does not consult it."""
        import ast
        import inspect

        from brightway_flows.merge import matching

        for name in ("resolve_flow_object", "_select_elementary_flow"):
            with self.subTest(function=name):
                tree = ast.parse(inspect.getsource(getattr(matching, name)).lstrip())
                attributes = {
                    node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
                }
                self.assertNotIn("context_expectations", attributes)


class TheSimaproFlagIsTheOnlyThingThatVariesTestCase(_Fixture):
    """§3.4: two index records, one set of dicts.

    `MergeIndexes` is frozen and carries the list, and the list carries
    `simapro_origin`, which a caller states per query. Building the indexes twice
    for one boolean would cost the whole load again.
    """

    def test_replacing_the_list_shares_every_underlying_dict(self):
        from dataclasses import replace

        indexes, _by_object, _stamp = load_lookup_index(self.db_path)
        simapro = replace(indexes, source=lookup_source_list(simapro_origin=True))
        self.assertTrue(simapro.source.simapro_origin)
        self.assertFalse(indexes.source.simapro_origin)
        for name in ("cas_index", "label_index", "pref_label_index", "flow_objects_by_id"):
            with self.subTest(index=name):
                self.assertIs(getattr(simapro, name), getattr(indexes, name))

    def test_the_synthetic_list_is_not_registered(self):
        """§4: a build must never be able to name it as a `--source`."""
        from brightway_flows.sources import known_source_lists, resolve_source_list

        synthetic = lookup_source_list(simapro_origin=False)
        self.assertNotIn(synthetic.key, known_source_lists())
        with self.assertRaises(ValueError):
            resolve_source_list(synthetic.key)


class AnUnanswerableBuildIsRefusedTestCase(unittest.TestCase):
    """Refused before a flow is read, on signals the build already records.

    A lookup is a statement about one build. Half a build is not a list, and a
    slice of one is a statement about the slice.
    """

    def setUp(self) -> None:
        super().setUp()
        self.tmp = Path(tempfile.mkdtemp())

    def test_a_missing_database_says_what_to_run(self):
        with self.assertRaises(FileNotFoundError) as caught:
            load_lookup_index(self.tmp / "nothing.sqlite3")
        self.assertIn("brightway-flows build", str(caught.exception))

    def test_a_merge_still_running_is_refused(self):
        db_path = _fixture_database(self.tmp, merge_finished=False)
        with self.assertRaises(UnusableBuildError) as caught:
            load_lookup_index(db_path)
        self.assertIn("has not finished", str(caught.exception))

    def test_a_bounded_transform_is_refused(self):
        db_path = _fixture_database(self.tmp, max_flows=400)
        with self.assertRaises(UnusableBuildError) as caught:
            load_lookup_index(db_path)
        self.assertIn("400", str(caught.exception))
        self.assertIn("--max-flows", str(caught.exception))

    def test_a_bounded_merge_is_refused(self):
        db_path = _fixture_database(self.tmp, max_rows=50)
        with self.assertRaises(UnusableBuildError) as caught:
            load_lookup_index(db_path)
        self.assertIn("50", str(caught.exception))
        self.assertIn("--max-rows", str(caught.exception))

    def test_a_database_that_cannot_name_its_build_is_refused(self):
        """A fixture seeded through `_write_consensus_sqlite` alone has flows and
        no `pipeline_runs`. It looks exactly like a build and cannot say which
        one it is, which is the one thing every answer has to carry."""
        db_path = self.tmp / "no-run.sqlite3"
        flows, flow_objects, elementary = _fixture()
        _write_consensus_sqlite(flows, [], flow_objects, elementary, db_path=db_path)
        with self.assertRaises(UnusableBuildError) as caught:
            load_lookup_index(db_path)
        self.assertIn("pipeline_runs", str(caught.exception))

    def test_a_build_with_no_merge_is_answerable(self):
        """The base list on its own is a smaller consensus list, not a broken
        one, and the stamp says which lists it holds."""
        db_path = _fixture_database(self.tmp, with_merge=False)
        _indexes, by_object, stamp = load_lookup_index(db_path)
        self.assertTrue(by_object)
        self.assertEqual(stamp.merged_lists, ())
        self.assertEqual(stamp.merge_run_id, "")


class TheStampNamesTheBuildTestCase(_Fixture):
    """§3.2: a match expires with the build it came from, so the build is on it."""

    def test_it_carries_the_run_the_revision_and_the_lists(self):
        _indexes, _by_object, stamp = load_lookup_index(self.db_path)
        self.assertIsInstance(stamp, BuildStamp)
        self.assertEqual(stamp.run_id, RUN_ID)
        self.assertEqual(stamp.revision, REVISION)
        self.assertFalse(stamp.revision_dirty)
        self.assertEqual(stamp.merge_run_id, MERGE_RUN_ID)
        self.assertEqual(stamp.merged_lists, ("ecoinvent-3.12", "bafu-2026-v1"))
        self.assertEqual(stamp.flow_object_count, 4)
        self.assertEqual(stamp.elementary_flow_count, 6)

    def test_the_lists_are_in_merge_order(self):
        """Which list reached a substance first decides which object exists to
        match against, so the order is part of naming the build."""
        _indexes, _by_object, stamp = load_lookup_index(self.db_path)
        self.assertEqual(stamp.merged_lists[0], "ecoinvent-3.12")


class TheDatabaseIsOpenedReadOnlyTestCase(_Fixture):
    """§3.7, first of the three places "it does not write" is enforced.

    A build writes the shared data directory for the better part of an hour, so
    a lookup will sometimes be reading a database that is mid-run. Read-only is
    what stops this path from being able to make that worse.
    """

    def test_the_connection_asks_for_mode_ro(self):
        with mock.patch("sqlite3.connect", wraps=sqlite3.connect) as connect:
            load_lookup_index(self.db_path)
        self.assertTrue(connect.call_args_list)
        for call in connect.call_args_list:
            with self.subTest(call=call):
                self.assertIn("mode=ro", call.args[0])
                self.assertTrue(call.kwargs.get("uri"))

    def test_it_reads_a_database_whose_file_is_not_writable(self):
        self.db_path.chmod(0o444)
        self.addCleanup(self.db_path.chmod, 0o644)
        _indexes, by_object, _stamp = load_lookup_index(self.db_path)
        self.assertTrue(by_object)


if __name__ == "__main__":
    unittest.main()
