"""A printed context has to identify the context (#284).

`envi-air-indr-unkn` is indoor air, kind of setting unstated. `envi-air-unkn` is
air of unstated height. Both printed `Environmental → Air → Unknown`, because a
context is rendered by listing its answers and dropping the questions, and both
answered "Unknown" -- to different questions.

Two things followed, and the second is the expensive one:

- Indoor air did not say it was indoor. The one fact the context states was the
  one the name threw away.
- The review page for *one substance, one context, one flow* compared contexts by
  that name, so every substance holding both an indoor and an unspecified air
  flow was reported as a duplicate: 6,750 of 6,846 groups, and 14 real
  duplicates were swallowed into those oversized groups rather than listed.

What is pinned here:

- **`indoor` prints the fact, not the gap.** Its presence says indoors; the
  value only refines it, so "Unknown" renders `Indoor`.
- **No two registered contexts print the same name.** The collision was one pair
  out of 60 contexts, and nine of the 60 state "Unknown" across five different
  questions, so there is room for another.
- **The duplicate check groups by context identity.** A page that reads a
  rendering cannot tell two contexts apart however the rendering is worded.
- **The row tuple and the INSERT agree.** Adding `context_iri` moved the payload
  offset, which is a break with no test until this one.
- **There is one renderer.** The merge carried a second copy without the rule,
  so the bug survived there for as long as it took someone to notice that the
  two functions were the same function (#97).
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path

import orjson

from brightway_flows.domain.context_registry import (
    build_context_lookup,
    context_dict_for_iri,
    context_display_parts,
    context_from_dict,
)
from brightway_flows.domain.elementary_flow import ElementaryFlow
from brightway_flows.domain.flow import Flow
from brightway_flows.domain.flow_object import FlowObject
from brightway_flows.filesystem import PACKAGE_DATA_DIR
from brightway_flows.pipeline.review_records import PipelineRun
from brightway_flows.pipeline.review_tables import (
    REVIEW_SCHEMA_VERSION,
    write_review_tables,
)
from brightway_flows.pipeline.sqlite import (
    _EF_FLOW_JSON,
    _EF_FLOW_OBJECT_ID,
    _RELATIONS,
    _SCHEMA,
    _write_consensus_sqlite,
)
from brightway_flows.pipeline.sqlite_schema import recreate
from brightway_flows.webapps.app import db
from brightway_flows.webapps.app.queries import checks as check_queries

PREFIX = "https://vocab.brightway.one/flow-contexts/"
INDOOR_AIR = PREFIX + "envi-air-indr-unkn"
UNSPECIFIED_AIR = PREFIX + "envi-air-unkn"
GROUND = PREFIX + "envi-grou-agri"


class IndoorAirSaysIndoorTestCase(unittest.TestCase):
    def test_indoor_air_prints_as_indoor(self):
        """`IndoorAirClass.UNKNOWN` means indoors, setting unstated -- and
        "indoors" is the part a reader needs."""
        self.assertEqual(
            context_display_parts(context_dict_for_iri(INDOOR_AIR)),
            ["Environmental", "Air", "Indoor"],
        )

    def test_unstated_height_still_prints_unknown(self):
        """The other fields are plain attributes: there "Unknown" is the fact."""
        self.assertEqual(
            context_display_parts(context_dict_for_iri(UNSPECIFIED_AIR)),
            ["Environmental", "Air", "Unknown"],
        )

    def test_the_two_no_longer_print_alike(self):
        self.assertNotEqual(
            context_display_parts(context_dict_for_iri(INDOOR_AIR)),
            context_display_parts(context_dict_for_iri(UNSPECIFIED_AIR)),
        )

    def test_a_stated_indoor_class_is_unchanged(self):
        """Only the value that refines nothing is replaced."""
        self.assertEqual(
            context_display_parts(
                {"dimension": "Environmental", "media": "Air", "indoor": "Industrial"}
            ),
            ["Environmental", "Air", "Industrial"],
        )

    def test_the_source_context_list_is_printed_verbatim(self):
        """A raw source context is not ours to reword; `loading` prints these."""
        self.assertEqual(
            context_display_parts(["Emissions", "Emissions to air", "Unknown"]),
            ["Emissions", "Emissions to air", "Unknown"],
        )


class TheMergeUsesTheSameRendererTestCase(unittest.TestCase):
    """The fix reached the review page in #284 and stopped there.

    `merge/contexts._context_as_strings` listed the same fields in the same
    order without the `indoor` rule, so a merge candidate in indoor air rendered
    `["Environmental", "Air", "Unknown"]` -- the three strings unspecified
    outdoor air renders.

    In the merge that was not only a name.  The *source* side of the comparison
    comes from `consensus-flows-as-strings.json`, which is `Context.to_list()`
    and does say `"Indoor"`, so the two sides of one comparison disagreed about
    what a context is called: `_select_elementary_flow` scored an indoor source
    row against the indoor candidate, and level with the outdoor one.
    """

    #: Every merge module that turns a context into strings: three that render a
    #: candidate for the report, and `datastores`, which writes the published
    #: `context_display` column for the flows the merge adds.
    MERGE_RENDERERS = ("matching", "prepared", "rows", "datastores")

    def test_the_merge_renders_an_indoor_candidate_as_indoor(self):
        import importlib

        for name in self.MERGE_RENDERERS:
            with self.subTest(module=name):
                module = importlib.import_module(f"brightway_flows.merge.{name}")
                self.assertIs(module.context_display_parts, context_display_parts)
        self.assertEqual(
            context_display_parts(context_dict_for_iri(INDOOR_AIR)),
            ["Environmental", "Air", "Indoor"],
        )

    def test_the_two_sides_of_the_merge_comparison_agree(self):
        """What the source row is scored *as* and what the candidate is scored
        against are produced by different code, so they are pinned together."""
        strings_path = PACKAGE_DATA_DIR / "consensus-flows-as-strings.json"
        as_strings = orjson.loads(strings_path.read_bytes())
        for iri in (INDOOR_AIR, GROUND):
            with self.subTest(context=iri):
                rendered = context_display_parts(context_dict_for_iri(iri))
                self.assertIn(
                    as_strings[iri][-1],
                    rendered,
                    "the source side's last token names something the candidate "
                    "side does not say at all",
                )

    def test_the_merge_has_no_second_renderer_left(self):
        from brightway_flows.merge import contexts as merge_contexts

        self.assertFalse(hasattr(merge_contexts, "_context_as_strings"))

    def test_both_writers_of_context_display_agree(self):
        """`pipeline/sqlite` writes the column for transform flows and
        `merge/datastores` for the ones the merge adds.  A reader filtering on
        it cannot tell which wrote a row, so they have to render alike."""
        from brightway_flows.merge import datastores

        indoor = context_dict_for_iri(INDOOR_AIR)
        self.assertEqual(
            " → ".join(datastores.context_display_parts(indoor)),
            "Environmental → Air → Indoor",
        )


class EveryContextHasItsOwnNameTestCase(unittest.TestCase):
    def test_no_two_registered_contexts_print_the_same_name(self):
        by_name: dict[str, list[str]] = {}
        for iri in build_context_lookup():
            name = " → ".join(context_display_parts(context_dict_for_iri(iri)))
            by_name.setdefault(name, []).append(iri)
        collisions = {name: iris for name, iris in by_name.items() if len(iris) > 1}
        self.assertEqual(
            collisions,
            {},
            "two contexts render as one name, so a reader -- and any query "
            "grouping on the rendering -- cannot tell them apart:\n"
            + "\n".join(
                f"  {name!r}: {', '.join(sorted(iris))}"
                for name, iris in sorted(collisions.items())
            ),
        )

    def test_there_are_contexts_stating_unknown_to_check(self):
        """Guards the test above: the collision was between two of these, and a
        rename that removed them all would make it vacuous."""
        stating_unknown = [
            iri
            for iri in build_context_lookup()
            if "Unknown" in context_dict_for_iri(iri).values()
        ]
        self.assertGreaterEqual(len(stating_unknown), 9)


def _flow(uuid: str, *, context_iri: str, context, object_id: str) -> Flow:
    return Flow(
        uuid=uuid,
        identifier=uuid,
        flow_object_id=object_id,
        source="EF 3.1",
        unit="kg",
        context=context_from_dict(context),
        context_iri=context_iri,
        lcia_methods=[],
        prefLabel=[{"@value": "Formaldehyde", "@language": "en"}],
    )


class TheDuplicateCheckReadsIdentityTestCase(unittest.TestCase):
    """One substance with an indoor flow and an unspecified-air flow is not a
    duplicate; one substance with two flows in one context is."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "consensus-flows.sqlite3"

        indoor = context_dict_for_iri(INDOOR_AIR)
        unspecified = context_dict_for_iri(UNSPECIFIED_AIR)
        ground = context_dict_for_iri(GROUND)
        flows = [
            # Two contexts that used to print alike: not a duplicate.
            _flow("u-1", context_iri=INDOOR_AIR, context=indoor, object_id="fo-1"),
            _flow("u-2", context_iri=UNSPECIFIED_AIR, context=unspecified, object_id="fo-1"),
            # One context, twice: a duplicate, and the reason the page exists.
            _flow("u-3", context_iri=GROUND, context=ground, object_id="fo-2"),
            _flow("u-4", context_iri=GROUND, context=ground, object_id="fo-2"),
        ]
        flow_objects = [
            FlowObject(
                flow_object_id=object_id, prefLabel=[{"@value": name}], altLabel=[],
                classifications={}, properties={}, references=[], created_from={},
            )
            for object_id, name in (("fo-1", "Formaldehyde"), ("fo-2", "Copper"))
        ]
        elementary = [
            ElementaryFlow(
                elementary_flow_id=flow.uuid,
                flow_object_id=flow.flow_object_id,
                source="EF 3.1",
                context=flow.context,
                context_iri=flow.context_iri,
                unit="kg",
                unit_iri="",
                lcia_methods=[],
                general_comment=None,
                source_refs=[],
            )
            for flow in flows
        ]

        import brightway_flows.pipeline.sqlite as sqlite_module

        original = sqlite_module.CONSENSUS_DB_FILEPATH
        sqlite_module.CONSENSUS_DB_FILEPATH = self.path
        try:
            _write_consensus_sqlite(flows, [], flow_objects, elementary)
        finally:
            sqlite_module.CONSENSUS_DB_FILEPATH = original
        write_review_tables(
            self.path,
            run=PipelineRun(run_id="run-1", timestamp="2026-08-13T00:00:00+00:00",
                            schema_version=REVIEW_SCHEMA_VERSION),
            stats=[], changes=[], queue_items=[], formula_mismatches=[],
            element_coverage=[], context_mappings=[],
        )

    def connection(self):
        connection = db.connect(self.path)
        self.addCleanup(connection.close)
        return connection

    def test_only_the_real_duplicate_is_reported(self):
        page = check_queries.duplicate_contexts(self.connection())
        self.assertEqual(page.total, 1)
        self.assertEqual(page.rows[0].flow_object_id, "fo-2")
        self.assertEqual(page.rows[0].count, 2)

    def test_the_group_names_the_context_it_means(self):
        page = check_queries.duplicate_contexts(self.connection())
        self.assertEqual(page.rows[0].context_iri, GROUND)

    def test_the_two_air_flows_are_stored_apart(self):
        """The premise: they share a substance, and nothing else."""
        rows = self.connection().execute(
            "SELECT context_iri, context_display FROM elementary_flows "
            "WHERE flow_object_id = 'fo-1' ORDER BY context_iri"
        ).fetchall()
        self.assertEqual(
            [(row["context_iri"], row["context_display"]) for row in rows],
            [
                (INDOOR_AIR, "Environmental → Air → Indoor"),
                (UNSPECIFIED_AIR, "Environmental → Air → Unknown"),
            ],
        )


class TheRowTupleMatchesTheTableTestCase(unittest.TestCase):
    """`_EF_FLOW_JSON` is an offset into a tuple, and a new column moves it --
    `context_iri` did, and the payload position then pointed at an integer.

    Read off `_ELEMENTARY_FLOW_COLUMNS` since #96, so the two cannot part
    company by hand any more.  What can still part company is that list and the
    table the rows go into, so this checks the offsets against the table itself
    -- built here by the writer's own DDL -- rather than against the list they
    come from, which would be the same fact twice.
    """

    def _table_columns(self) -> list[str]:
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        recreate(connection, relations=_RELATIONS, schema=_SCHEMA)
        return [
            row[1] for row in connection.execute("PRAGMA table_info(elementary_flows)")
        ]

    def test_the_payload_offset_is_where_flow_json_is_written(self):
        self.assertEqual(self._table_columns()[_EF_FLOW_JSON], "flow_json")

    def test_the_object_offset_is_where_flow_object_id_is_written(self):
        self.assertEqual(self._table_columns()[_EF_FLOW_OBJECT_ID], "flow_object_id")


if __name__ == "__main__":
    unittest.main()
