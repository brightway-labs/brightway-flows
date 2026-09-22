"""`/flow-objects/water`: the taxonomy page, and the distinctions it keeps.

The water page differs from the other flow-object views in where its rows come
from, and everything worth pinning here follows from that:

- **The tree is the taxonomy, not the build.**  A land class is a value the
  page decomposes out of a published flow object, so `queries/land.py` can read
  its rows off the database.  A kind of water is a curated concept that exists
  whether or not a flow reaches it -- `saline_water` mints no flow object at
  all, and several kinds are BAFU's -- so the rows are the seventeen concepts,
  and a build that reaches twelve of them shows five saying so.
- **A withdrawal and a return are counted apart.**  They are the two halves of
  EF 3.1's water use pair, characterised with opposite signs, and the collapse
  of one into the other is the defect (#31) the whole taxonomy exists to stop.
  A page that showed one flow count could not show that a pair is intact.
- **"Nobody publishes it" is not "the published class is inexact".**  Turbine
  water cites an identifier this project minted; fossil groundwater cites ENVO
  as a close match rather than an equivalence.  Both are exceptions, they are
  different exceptions, and the taxonomy states its own reason for each -- so
  the page reads those reasons rather than restating one for the group.

The fixture joins to the *real* taxonomy by `flow_object_id`, because that join
is the page's whole design: a concept file and a build that disagree about
which object is which material is exactly the failure worth catching.
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from brightway_flows.domain.context_registry import context_from_dict
from brightway_flows.domain.elementary_flow import ElementaryFlow
from brightway_flows.domain.flow import Flow
from brightway_flows.domain.flow_object import FlowObject
from brightway_flows.domain.materials import material_concepts
from brightway_flows.pipeline.sqlite import _write_consensus_sqlite
from brightway_flows.webapps.app import create_app
from brightway_flows.webapps.app.queries import water as queries

#: A withdrawal from an unspecified body, and the return of the same water to
#: surface water: the shape of the pair the taxonomy is for.
_WITHDRAWAL = context_from_dict(
    {"dimension": "Resource", "media": "Water", "water_body": "Unknown"}
)
_RETURN = context_from_dict(
    {"dimension": "Environmental", "media": "Water", "water_body": "Surface water"}
)
_FROM_OCEAN = context_from_dict(
    {"dimension": "Resource", "media": "Water", "water_body": "Ocean"}
)
#: Neither a withdrawal from the environment nor a return to it.  BAFU carries
#: a water flow here, and the page must not file it under either.
_ECONOMIC = context_from_dict({"dimension": "Economic"})


def _object_id(concept_id: str) -> str:
    """The flow object the real taxonomy says this concept mints."""
    return material_concepts()[concept_id]["flow_object_id"]


def _water_object(concept_id: str) -> FlowObject:
    concept = material_concepts()[concept_id]
    return FlowObject(
        flow_object_id=concept["flow_object_id"],
        prefLabel=[{"@value": concept["label"], "@language": "en"}],
        altLabel=[],
        properties={},
        references=[],
        created_from={"seed_source": "EF 3.1"},
        classifications={
            queries.MATERIAL_CLASSIFICATION: {
                "@id": (
                    "https://vocab.brightway.one/environmental-materials/"
                    + concept_id.replace("_", "-")
                ),
                "@value": [concept_id],
            }
        },
    )


def _flow(uuid, name, context, *, source="EF 3.1", unit="m3", factors=0,
          deprecated=False) -> Flow:
    return Flow(
        uuid=uuid,
        source=source,
        unit=unit,
        prefLabel=[{"@value": name, "@language": "en"}],
        context=context,
        lcia_methods=[{"amount": 1.0} for _ in range(factors)],
        owl_deprecated=True if deprecated else None,
    )


def _elementary(uuid, concept_id, context, *, source="EF 3.1", unit="m3",
                factors=0):
    # The factors go here rather than on the `Flow`: the layered elementary
    # flow is what the writer counts, and a fixture that stated them only on
    # the source flow would silently publish a factor count of zero.
    return ElementaryFlow(
        elementary_flow_id=uuid,
        flow_object_id=_object_id(concept_id),
        source=source,
        context=context,
        context_iri="",
        unit=unit,
        unit_iri="",
        lcia_methods=[{"amount": 1.0} for _ in range(factors)],
        general_comment=None,
        source_refs=[],
    )


#: The kinds the fixture reaches.  Deliberately not all of them: the point of
#: reading the tree from the taxonomy is that the rest still appear.
REACHED = ("cooling_water", "sea_water", "water")


def _write_fixture(path: Path, *, extra_objects=(), extra_flows=(),
                   extra_elementary=()):
    import brightway_flows.pipeline.sqlite as sqlite_module

    flows = [
        # The balanced pair, on one kind.
        _flow("u-cool-in", "Cooling water", _WITHDRAWAL, factors=2),
        _flow("u-cool-out", "Cooling water", _RETURN, factors=2),
        # A second list on the same kind, and a kilogram rather than a cubic
        # metre: sea water is filed in kg by EF.
        _flow("u-sea", "Sea water", _FROM_OCEAN, unit="kg"),
        _flow("u-sea-bafu", "Sea water", _WITHDRAWAL, source="bafu-2026-v1"),
        # A retired flow, which must not be counted into a direction.
        _flow("u-water-gone", "Water", _RETURN, deprecated=True),
        # Neither a withdrawal nor a return.
        _flow("u-water-econ", "Water", _ECONOMIC, source="bafu-2026-v1"),
        *extra_flows,
    ]
    elementary = [
        _elementary("u-cool-in", "cooling_water", _WITHDRAWAL, factors=2),
        _elementary("u-cool-out", "cooling_water", _RETURN, factors=2),
        _elementary("u-sea", "sea_water", _FROM_OCEAN, unit="kg"),
        _elementary("u-sea-bafu", "sea_water", _WITHDRAWAL, source="bafu-2026-v1"),
        # Retired, and carrying factors: they must not reach the kind's total.
        _elementary("u-water-gone", "water", _RETURN, factors=3),
        _elementary("u-water-econ", "water", _ECONOMIC, source="bafu-2026-v1"),
        *extra_elementary,
    ]
    objects = [_water_object(concept_id) for concept_id in REACHED]
    objects.extend(extra_objects)

    original = sqlite_module.CONSENSUS_DB_FILEPATH
    sqlite_module.CONSENSUS_DB_FILEPATH = path
    try:
        _write_consensus_sqlite(flows, [], objects, elementary)
    finally:
        sqlite_module.CONSENSUS_DB_FILEPATH = original


class TheWaterPageTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "consensus-flows.sqlite3"
        _write_fixture(self.path)
        self.client = create_app(database_path=self.path).test_client()
        self.connection = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        self.connection.row_factory = sqlite3.Row
        self.addCleanup(self.connection.close)

    def overview(self, **kwargs):
        return queries.water_overview(self.connection, **kwargs)

    # ── the tree ─────────────────────────────────────────────────────────

    def test_every_kind_is_shown_whether_or_not_the_build_reached_it(self):
        """A build reaching three kinds is not a taxonomy with three kinds."""
        overview = self.overview()
        self.assertEqual(overview.kinds, len(material_concepts()))
        self.assertEqual(overview.kinds_with_flows, len(REACHED))
        unreached = [row for row in overview.rows if not row.in_build]
        self.assertIn("Brine", {row.label for row in unreached})

    def test_a_kind_that_mints_no_flow_object_is_a_grouping_and_says_so(self):
        """`saline_water` exists so sea water and brine have ENVO's parent."""
        overview = self.overview()
        saline = next(row for row in overview.rows if row.concept_id == "saline_water")
        self.assertEqual(saline.flow_object_id, "")
        self.assertFalse(saline.in_build)
        self.assertEqual(saline.linked_flows, 0)

    def test_a_child_never_precedes_its_parent(self):
        """The indent is drawn from `depth`, so the order has to be a tree."""
        overview = self.overview()
        seen: set[str] = set()
        for row in overview.rows:
            if row.parent_id:
                self.assertIn(row.parent_id, seen, f"{row.concept_id} before parent")
            seen.add(row.concept_id)

    def test_depth_is_the_distance_to_a_root(self):
        overview = self.overview()
        depths = {row.concept_id: row.depth for row in overview.rows}
        self.assertEqual(depths["water"], 0)
        self.assertEqual(depths["surface_water"], 1)
        self.assertEqual(depths["lake_water"], 2)

    # ── the pair the taxonomy exists for ─────────────────────────────────

    def test_a_withdrawal_and_a_return_are_counted_apart(self):
        """One count could not show that EF's balanced pair is intact."""
        overview = self.overview()
        cooling = next(
            row for row in overview.rows if row.concept_id == "cooling_water"
        )
        self.assertEqual((cooling.withdrawals, cooling.returns), (1, 1))
        self.assertEqual(cooling.linked_flows, 2)

    def test_a_dimension_that_is_neither_is_passed_through(self):
        """BAFU's `Economic` water is not a withdrawal and not a return."""
        self.assertEqual(queries.direction_of("Resource"), queries.WITHDRAWAL)
        self.assertEqual(queries.direction_of("Environmental"), queries.RETURN)
        self.assertEqual(queries.direction_of("Economic"), "Economic")
        overview = self.overview()
        water = next(row for row in overview.rows if row.concept_id == "water")
        self.assertEqual((water.withdrawals, water.returns), (0, 0))
        self.assertEqual(water.other_flows, 1)

    def test_a_retired_flow_is_counted_apart_from_the_live_ones(self):
        """Adding it to a direction would make a merged-away half look live."""
        overview = self.overview()
        water = next(row for row in overview.rows if row.concept_id == "water")
        self.assertEqual(water.deprecated_flows, 1)
        self.assertEqual(water.linked_flows, 1)
        self.assertEqual(overview.deprecated_flows, 1)

    def test_a_retired_flows_factors_are_not_counted_onto_the_kind(self):
        overview = self.overview()
        cooling = next(
            row for row in overview.rows if row.concept_id == "cooling_water"
        )
        self.assertEqual(cooling.lcia_factor_count, 4)
        # The retired flow carries three, and the kind it hangs on reports none.
        water = next(row for row in overview.rows if row.concept_id == "water")
        self.assertEqual(water.lcia_factor_count, 0)

    def test_a_kind_names_the_lists_that_reach_it(self):
        overview = self.overview()
        sea = next(row for row in overview.rows if row.concept_id == "sea_water")
        self.assertEqual(set(sea.sources), {"EF 3.1", "bafu-2026-v1"})

    # ── how well anchored a kind is ──────────────────────────────────────

    def test_a_minted_identifier_is_not_a_citation(self):
        """Turbine water cites nothing: no authority carries the concept."""
        overview = self.overview()
        turbine = next(
            row for row in overview.rows if row.concept_id == "turbine_water"
        )
        self.assertTrue(turbine.anchors)
        self.assertEqual(turbine.published_anchors, ())
        self.assertTrue(turbine.is_minted)
        # Not an inexact match, which is a different finding about a concept.
        self.assertFalse(turbine.is_inexact)

    def test_an_inexact_citation_is_not_a_missing_one(self):
        """Fossil groundwater overlaps ENVO's bore hole water without being it."""
        overview = self.overview()
        fossil = next(
            row for row in overview.rows if row.concept_id == "fossil_groundwater"
        )
        self.assertTrue(fossil.is_inexact)
        self.assertFalse(fossil.is_minted)
        self.assertEqual(
            [anchor.predicate for anchor in fossil.published_anchors],
            ["skos:closeMatch"],
        )

    def test_the_two_findings_are_separate_lists(self):
        overview = self.overview()
        self.assertEqual([row.concept_id for row in overview.minted], ["turbine_water"])
        self.assertEqual(
            [row.concept_id for row in overview.inexact], ["fossil_groundwater"]
        )

    def test_each_asserted_edge_carries_its_own_reason(self):
        """Two kinds are `ours` for entirely different reasons.

        One explanation for the group would be wrong about one of them, which
        is why the page reads `broader_reason` instead of restating it.
        """
        overview = self.overview()
        reasons = {row.concept_id: row.broader_reason for row in overview.ours}
        self.assertIn("lake_water", reasons)
        self.assertIn("turbine_water", reasons)
        self.assertNotEqual(reasons["lake_water"], reasons["turbine_water"])
        self.assertTrue(all(reasons.values()))

    def test_an_exception_is_listed_once_however_many_things_it_states(self):
        """Fossil groundwater asserts its parent *and* declines equivalence."""
        overview = self.overview()
        ids = [row.concept_id for row in overview.exceptions]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn("fossil_groundwater", ids)

    def test_a_kind_that_names_a_place_says_which_place(self):
        """For a withdrawal the kind and the body are one fact stated twice."""
        overview = self.overview()
        bodies = {row.concept_id: row.withdrawal_body for row in overview.rows}
        self.assertEqual(bodies["lake_water"], "Lake")
        self.assertEqual(bodies["sea_water"], "Ocean")
        # Cooling water names what the water was used for, not where it was.
        self.assertEqual(bodies["cooling_water"], "")

    # ── the flows and their filters ──────────────────────────────────────

    def test_every_flow_on_a_water_object_is_listed(self):
        overview = self.overview()
        self.assertEqual(overview.total_flows, 6)
        self.assertEqual(
            {flow.uuid for flow in overview.all_flows},
            {"u-cool-in", "u-cool-out", "u-sea", "u-sea-bafu", "u-water-gone",
             "u-water-econ"},
        )

    def test_the_filters_are_read_together(self):
        """All of them: a reader picking a kind and a direction wants one half."""
        overview = self.overview(
            filters={"kind": "cooling_water", "direction": queries.RETURN}
        )
        self.assertEqual([flow.uuid for flow in overview.flows], ["u-cool-out"])
        # The any-of reading would return the withdrawal and the sea water too.
        self.assertEqual(overview.total_flows, 6)

    def test_filtering_by_water_body_selects_that_body(self):
        overview = self.overview(filters={"body": "Ocean"})
        self.assertEqual([flow.uuid for flow in overview.flows], ["u-sea"])

    def test_only_the_kinds_carrying_a_flow_are_offered(self):
        """A filter that can select nothing looks no different from a broken one."""
        overview = self.overview()
        offered = dict(overview.kind_options())
        self.assertEqual(set(offered), set(REACHED))
        self.assertEqual(offered["cooling_water"], "Cooling water (2)")
        self.assertNotIn("brine", offered)

    def test_a_hand_edited_filter_selects_nothing_rather_than_erroring(self):
        overview = self.overview(filters={"kind": "atlantis_water"})
        self.assertEqual(overview.flows, [])
        self.assertEqual(overview.kinds, len(material_concepts()))

    # ── a build this checkout's taxonomy does not recognise ──────────────

    def test_a_concept_this_taxonomy_lacks_is_counted_not_dropped(self):
        """Sixteen of seventeen looks like a smaller taxonomy, not an older build."""
        stale = FlowObject(
            flow_object_id="fo-stale-water",
            prefLabel=[{"@value": "Aqua vitae", "@language": "en"}],
            altLabel=[], properties={}, references=[], created_from={},
            classifications={
                queries.MATERIAL_CLASSIFICATION: {
                    "@id": (
                        "https://vocab.brightway.one/environmental-materials/"
                        "aqua-vitae"
                    ),
                    "@value": ["aqua_vitae"],
                }
            },
        )
        path = Path(self._tmp.name) / "stale.sqlite3"
        _write_fixture(path, extra_objects=[stale])
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        self.addCleanup(connection.close)
        overview = queries.water_overview(connection)
        self.assertEqual(overview.unrecognised, 1)
        self.assertEqual(overview.kinds, len(material_concepts()))

    def test_a_recognised_concept_is_not_counted_as_unrecognised(self):
        self.assertEqual(self.overview().unrecognised, 0)

    # ── the page ─────────────────────────────────────────────────────────

    def test_the_page_renders_and_names_the_kinds(self):
        body = self.client.get("/flow-objects/water/").get_data(as_text=True)
        for marker in (
            "Cooling water",
            "Saline water",
            "Turbine water",
            "bore hole water",   # what fossil groundwater cites, and how
            "skos:closeMatch",
            "bafu-2026-v1",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, body)

    def test_a_filter_reaches_the_page(self):
        body = self.client.get(
            "/flow-objects/water/?kind=cooling_water&direction=Return"
        ).get_data(as_text=True)
        self.assertIn("u-cool-out", body)
        self.assertNotIn("u-cool-in", body)

    def test_a_filter_chip_names_the_kind_rather_than_its_id(self):
        """The one place a snake_case id would stand where a label belongs."""
        body = self.client.get(
            "/flow-objects/water/?kind=sea_water"
        ).get_data(as_text=True)
        self.assertIn('<span class="chip__value">Sea water</span>', body)

    def test_the_view_strip_offers_water_and_marks_it_current(self):
        body = self.client.get("/flow-objects/water/").get_data(as_text=True)
        self.assertIn('href="/flow-objects/water/"', body)
        self.assertIn('aria-current="page"', body)
        # And it is reachable from its siblings, which is what a strip is for.
        land = self.client.get("/flow-objects/land/").get_data(as_text=True)
        self.assertIn('href="/flow-objects/water/"', land)


class NoWaterInTheBuildTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "consensus-flows.sqlite3"
        sqlite3.connect(self.path).close()
        self.client = create_app(database_path=self.path).test_client()

    def test_a_database_with_no_flow_objects_is_a_page(self):
        """Not "there is no water", which is a different claim entirely."""
        response = self.client.get("/flow-objects/water/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "no <code>flow_objects</code> table", response.get_data(as_text=True)
        )


class NoDatabaseTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.client = create_app(
            database_path=Path(self._tmp.name) / "absent.sqlite3"
        ).test_client()

    def test_the_page_is_a_page_and_not_a_crash(self):
        self.assertEqual(self.client.get("/flow-objects/water/").status_code, 200)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
