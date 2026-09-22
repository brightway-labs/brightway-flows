"""`/flow-objects/land`: the taxonomy page, and what it refuses to guess.

The land page reads a class back out of a built list, which means it depends on
two things the other flow-object views do not:

- **The key is the only thing stored.**  A published land object carries its
  class as a `LandUse.key`, and the page turns that back into seventeen axes
  with `LandUse.from_key`.  A build written by an older taxonomy can hold a key
  this checkout cannot read, and the page counts those rather than dropping
  them -- 331 classes shown out of 333 looks like a smaller taxonomy, not an
  older build.
- **The filters are read together.**  Each axis is an independent question
  about one piece of land, so `Cover: Forest` with `Intensity: Intensive` means
  intensively managed forest, not everything that is either.  An any-of reading
  would answer a question nobody asked and would look plausible doing it.
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from brightway_flows.domain.context_registry import context_from_dict
from brightway_flows.domain.elementary_flow import ElementaryFlow
from brightway_flows.domain.flow import Flow
from brightway_flows.domain.flow_object import FlowObject
from brightway_flows.domain.land_use import (
    Direction,
    Irrigation,
    LandCover,
    LandUse,
    ManagementIntensity,
    SuccessionalStage,
)
from brightway_flows.flow_layers.land_hierarchy import land_object_id
from brightway_flows.pipeline.semantic_typing import _attach_land_class
from brightway_flows.pipeline.sqlite import _write_consensus_sqlite
from brightway_flows.webapps.app import create_app
from brightway_flows.webapps.app.queries import land as queries

_OCCUPATION = context_from_dict({"dimension": "Land Use", "land_use": "Occupation"})
_TRANSFORMATION = context_from_dict(
    {"dimension": "Land Use", "land_use": "Transformation"}
)

CROPLAND = LandUse(direction=Direction.OCCUPATION, cover=LandCover.CROPLAND)
IRRIGATED = LandUse(
    direction=Direction.OCCUPATION,
    cover=LandCover.CROPLAND,
    irrigation=Irrigation.IRRIGATED,
)
IRRIGATED_INTENSIVE = LandUse(
    direction=Direction.OCCUPATION,
    cover=LandCover.CROPLAND,
    irrigation=Irrigation.IRRIGATED,
    intensity=ManagementIntensity.INTENSIVE,
)
FOREST_INTENSIVE = LandUse(
    direction=Direction.OCCUPATION,
    cover=LandCover.FOREST,
    intensity=ManagementIntensity.INTENSIVE,
)
FROM_PRIMARY = LandUse(
    direction=Direction.TRANSFORMATION_FROM,
    cover=LandCover.FOREST,
    stage=SuccessionalStage.PRIMARY,
)

CLASSES = (CROPLAND, IRRIGATED, IRRIGATED_INTENSIVE, FOREST_INTENSIVE, FROM_PRIMARY)


def _land_object(land_use: LandUse) -> FlowObject:
    """A land flow object as the pipeline writes one: id, label and block."""
    obj = FlowObject(
        flow_object_id=land_object_id(land_use),
        prefLabel=[{"@value": land_use.label, "@language": "en"}],
        altLabel=[],
        properties={},
        references=[],
        created_from={"seed_source": "EF 3.1"},
        classifications={},
    )
    _attach_land_class(obj)
    return obj


def _flow(uuid, land_use, *, source="EF 3.1", factors=0) -> Flow:
    return Flow(
        uuid=uuid,
        source=source,
        unit="m2*a",
        prefLabel=[{"@value": land_use.label, "@language": "en"}],
        context=(
            _OCCUPATION
            if land_use.direction is Direction.OCCUPATION
            else _TRANSFORMATION
        ),
        lcia_methods=[{"amount": 1.0} for _ in range(factors)],
    )


def _elementary(uuid, land_use, *, source="EF 3.1") -> ElementaryFlow:
    return ElementaryFlow(
        elementary_flow_id=uuid,
        flow_object_id=land_object_id(land_use),
        source=source,
        context=(
            _OCCUPATION
            if land_use.direction is Direction.OCCUPATION
            else _TRANSFORMATION
        ),
        context_iri="",
        unit="m2*a",
        unit_iri="",
        lcia_methods=[],
        general_comment=None,
        source_refs=[],
    )


def _write_fixture(path: Path, *, extra_objects=()):
    import brightway_flows.pipeline.sqlite as sqlite_module

    flows = [_flow(f"u-{i}", value) for i, value in enumerate(CLASSES)]
    elementary = [_elementary(f"u-{i}", value) for i, value in enumerate(CLASSES)]
    # A second list reaching one of the classes, which is the point of the whole
    # taxonomy: BAFU's spelling and EF's are one class.
    flows.append(_flow("u-bafu", IRRIGATED_INTENSIVE, source="bafu-2026-v1"))
    elementary.append(_elementary("u-bafu", IRRIGATED_INTENSIVE, source="bafu-2026-v1"))
    objects = [_land_object(value) for value in CLASSES] + list(extra_objects)

    original = sqlite_module.CONSENSUS_DB_FILEPATH
    sqlite_module.CONSENSUS_DB_FILEPATH = path
    try:
        _write_consensus_sqlite(flows, [], objects, elementary)
    finally:
        sqlite_module.CONSENSUS_DB_FILEPATH = original


class TheLandPageTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "consensus-flows.sqlite3"
        _write_fixture(self.path)
        self.client = create_app(database_path=self.path).test_client()
        self.connection = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        self.connection.row_factory = sqlite3.Row
        self.addCleanup(self.connection.close)

    def test_every_published_class_is_read_back(self):
        overview = queries.land_overview(self.connection)
        self.assertEqual(len(overview.all_rows), len(CLASSES))
        self.assertEqual(overview.unreadable, 0)
        self.assertEqual(
            {row.key for row in overview.all_rows.values()},
            {value.key for value in CLASSES},
        )

    def test_a_class_knows_its_axes_and_not_just_its_name(self):
        overview = queries.land_overview(self.connection)
        row = overview.all_rows[IRRIGATED_INTENSIVE.key]
        self.assertEqual(row.direction, Direction.OCCUPATION)
        self.assertEqual(row.cover, LandCover.CROPLAND)
        self.assertEqual(
            {name: value.value for name, value in row.qualifiers.items()},
            {"irrigation": "Irrigated", "intensity": "Intensive"},
        )
        self.assertEqual(row.depth, 2)

    def test_the_filters_are_read_together(self):
        """All of them, not any: an axis is a question about one piece of land."""
        overview = queries.land_overview(
            self.connection, filters={"cover": "Forest", "intensity": "Intensive"}
        )
        self.assertEqual([row.key for row in overview.rows], [FOREST_INTENSIVE.key])
        # The any-of reading would return the cropland classes too.
        self.assertNotIn(IRRIGATED_INTENSIVE.key, {row.key for row in overview.rows})

    def test_a_filter_no_class_states_selects_nothing(self):
        overview = queries.land_overview(
            self.connection, filters={"cover": "Seabed"}
        )
        self.assertEqual(overview.rows, [])
        self.assertEqual(overview.total, len(CLASSES))

    def test_only_the_values_this_build_reaches_are_offered(self):
        """A dropdown naming a regime no flow states invites a dead filter."""
        overview = queries.land_overview(self.connection)
        covers = dict(overview.axis_options("cover"))
        self.assertEqual(set(covers), {"Cropland", "Forest"})
        self.assertEqual(covers["Cropland"], "Cropland (3)")
        intensities = dict(overview.axis_options("intensity"))
        self.assertEqual(set(intensities), {"Intensive"})
        # Nothing in the fixture is irrigated *and* organic, so organic is not
        # offered at all rather than offered and empty.
        self.assertNotIn("Organic", intensities)

    def test_a_key_this_checkout_cannot_read_is_counted_not_dropped(self):
        """A build written by a taxonomy this checkout no longer declares."""
        stale = FlowObject(
            flow_object_id="fo-stale-land",
            prefLabel=[{"@value": "Something, ancient", "@language": "en"}],
            altLabel=[], properties={}, references=[], created_from={},
            classifications={
                queries.LAND_CLASSIFICATION: {
                    "@id": "https://vocab.brightway.one/land-classes/occupation/atlantis",
                    "@value": ["occupation/atlantis"],
                }
            },
        )
        path = Path(self._tmp.name) / "stale.sqlite3"
        _write_fixture(path, extra_objects=[stale])
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        self.addCleanup(connection.close)
        overview = queries.land_overview(connection)
        self.assertEqual(overview.unreadable, 1)
        self.assertEqual(overview.total, len(CLASSES))

    def test_a_class_names_the_lists_that_reach_it(self):
        """The point of the taxonomy, made visible on the page."""
        overview = queries.land_overview(self.connection)
        row = overview.all_rows[IRRIGATED_INTENSIVE.key]
        self.assertEqual(set(row.sources), {"EF 3.1", "bafu-2026-v1"})
        self.assertEqual(overview.all_rows[CROPLAND.key].sources, ("EF 3.1",))

    def test_the_citations_are_computed_from_the_fields(self):
        overview = queries.land_overview(self.connection)
        anchors = overview.all_rows[IRRIGATED_INTENSIVE.key].anchor_rows
        authorities = {anchor.authority.value for anchor in anchors}
        self.assertIn("envo", authorities)
        self.assertIn("agrovoc", authorities)

    def test_the_directions_are_counted_apart(self):
        overview = queries.land_overview(self.connection)
        counts = overview.by_direction
        self.assertEqual(counts["Occupation"], 4)
        self.assertEqual(counts["Transformation, from"], 1)
        self.assertEqual(counts["Transformation, to"], 0)

    def test_the_page_renders_and_names_the_classes(self):
        body = self.client.get("/flow-objects/land/").get_data(as_text=True)
        for marker in (
            IRRIGATED_INTENSIVE.label,
            IRRIGATED_INTENSIVE.key,
            "AGROVOC",
            "bafu-2026-v1",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, body)

    def test_a_filter_reaches_the_page(self):
        body = self.client.get(
            "/flow-objects/land/?cover=Forest&intensity=Intensive"
        ).get_data(as_text=True)
        self.assertIn(FOREST_INTENSIVE.label, body)
        self.assertNotIn(IRRIGATED_INTENSIVE.label, body)

    def test_a_hand_edited_filter_selects_nothing_rather_than_erroring(self):
        response = self.client.get("/flow-objects/land/?cover=Atlantis")
        self.assertEqual(response.status_code, 200)


class NoLandInTheBuildTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "consensus-flows.sqlite3"
        sqlite3.connect(self.path).close()
        self.client = create_app(database_path=self.path).test_client()

    def test_a_database_with_no_flow_objects_is_a_page(self):
        response = self.client.get("/flow-objects/land/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("no <code>flow_objects</code> table", response.get_data(as_text=True))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
