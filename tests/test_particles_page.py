"""`/flow-objects/particles`: the size-window page, and the distinctions it keeps.

Built the way the water page is, and pinned the same way:

- **The tree is the scheme, not the build.**  Seven windows appear whether or
  not a build reached them, and a window nothing reached says so.
- **A retired flow is counted apart.**  Two of the four strays #196 removed
  were flows on PM10's window; a page that counted them into the live flows
  would show the collapse as growth.
- **Every window shows the spelling it promises.**  The alternative labels
  come from the scheme, not from the build, so a reader sees the promise even
  on a build that predates it.
- **The refusal list is empty on a finished build, and says so.**  A row named
  as a particle size cut that the curated table has not read is what the merge
  guard stops on; the page shows the population so a reader can see it is
  empty, and shows the rows when it is not.

The fixture joins to the *real* scheme by `flow_object_id`, because that join is
the page's whole design.
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from brightway_flows.domain.context_registry import context_from_dict
from brightway_flows.domain.elementary_flow import ElementaryFlow
from brightway_flows.domain.flow import Flow
from brightway_flows.domain.flow_object import FlowObject
from brightway_flows.domain.particulate_size import size_classes
from brightway_flows.pipeline.sqlite import _write_consensus_sqlite
from brightway_flows.webapps.app import create_app
from brightway_flows.webapps.app.queries import particles as queries

_AIR = context_from_dict({"dimension": "Environmental", "media": "Air", "strata": "Unknown"})
_URBAN = context_from_dict(
    {"dimension": "Environmental", "media": "Air", "strata": "Ground level",
     "population_density": "Urban (>1000 people/square mile)"}
)


def _object_id(window: str) -> str:
    return size_classes()[window].flow_object_id


def _window_object(window: str) -> FlowObject:
    value = size_classes()[window]
    return FlowObject(
        flow_object_id=value.flow_object_id,
        prefLabel=[{"@value": value.label, "@language": "en"}],
        altLabel=[],
        properties={},
        references=[],
        created_from={"seed_source": "EF 3.1"},
        classifications={},
    )


def _flow(uuid, name, context, *, source="EF 3.1", factors=0, deprecated=False) -> Flow:
    return Flow(
        uuid=uuid, source=source, unit="kg",
        prefLabel=[{"@value": name, "@language": "en"}],
        context=context,
        lcia_methods=[{"amount": 1.0} for _ in range(factors)],
        owl_deprecated=True if deprecated else None,
    )


def _elementary(uuid, window, context, *, source="EF 3.1", factors=0):
    return ElementaryFlow(
        elementary_flow_id=uuid, flow_object_id=_object_id(window), source=source,
        context=context, context_iri="", unit="kg", unit_iri="",
        lcia_methods=[{"amount": 1.0} for _ in range(factors)],
        general_comment=None, source_refs=[],
    )


REACHED = ("pm10", "pm2_5", "pm2_5_to_pm10")


def _write_fixture(path: Path):
    import brightway_flows.pipeline.sqlite as sqlite_module

    flows = [
        _flow("u-pm10-air", "Particles (PM10)", _AIR, factors=1),
        _flow("u-pm10-urban", "Particles (PM10)", _URBAN, factors=1),
        _flow("u-pm2.5-air", "Particles (PM2.5)", _AIR, factors=1),
        _flow("u-coarse-air", "Particles (PM2.5 - PM10)", _AIR),
        _flow("u-coarse-bafu", "Particles (PM2.5 - PM10)", _URBAN, source="bafu-2026-v1"),
        _flow("u-stray", "Particulates, < 10 Um", _AIR, source="stepwise-2006-1.09", deprecated=True),
    ]
    elementary = [
        _elementary("u-pm10-air", "pm10", _AIR, factors=1),
        _elementary("u-pm10-urban", "pm10", _URBAN, factors=1),
        _elementary("u-pm2.5-air", "pm2_5", _AIR, factors=1),
        _elementary("u-coarse-air", "pm2_5_to_pm10", _AIR),
        _elementary("u-coarse-bafu", "pm2_5_to_pm10", _URBAN, source="bafu-2026-v1"),
        _elementary("u-stray", "pm10", _AIR, source="stepwise-2006-1.09", factors=2),
    ]
    objects = [_window_object(window) for window in REACHED]
    original = sqlite_module.CONSENSUS_DB_FILEPATH
    sqlite_module.CONSENSUS_DB_FILEPATH = path
    try:
        _write_consensus_sqlite(flows, [], objects, elementary)
    finally:
        sqlite_module.CONSENSUS_DB_FILEPATH = original


class TheParticlesPageTestCase(unittest.TestCase):
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
        return queries.particles_overview(self.connection, **kwargs)

    def test_every_window_is_shown_whether_or_not_the_build_reached_it(self):
        overview = self.overview()
        self.assertEqual(overview.windows, 7)
        self.assertEqual(overview.windows_with_flows, len(REACHED))
        unreached = {row.label for row in overview.rows if not row.in_build}
        self.assertIn("Particles (> PM10)", unreached)
        self.assertIn("Particles (unspecified size)", unreached)

    def test_a_child_never_precedes_its_parent(self):
        seen: set[str] = set()
        for row in self.overview().rows:
            if row.parent_id:
                self.assertIn(row.parent_id, seen, f"{row.concept_id} before parent")
            seen.add(row.concept_id)
        root = next(row for row in self.overview().rows if row.is_root)
        self.assertEqual(root.concept_id, "unsized")

    def test_the_bounds_read_as_a_reader_would_say_them(self):
        by_id = {row.concept_id: row for row in self.overview().rows}
        self.assertEqual(by_id["pm10"].window_text, "below 10 µm")
        self.assertEqual(by_id["pm2_5_to_pm10"].window_text, "2.5 – 10 µm")
        self.assertEqual(by_id["above_pm10"].window_text, "above 10 µm")
        self.assertEqual(by_id["unsized"].window_text, "no cut stated")

    def test_every_window_says_where_its_bound_is_read_from(self):
        for row in self.overview().rows:
            with self.subTest(row.concept_id):
                self.assertTrue(row.definition_source)
        body = self.client.get("/flow-objects/particles/").get_data(as_text=True)
        self.assertIn("2008/50/EC", body)

    def test_every_window_shows_the_spelling_it_promises(self):
        for row in self.overview().rows:
            with self.subTest(row.concept_id):
                self.assertTrue(row.alt_labels)
                self.assertTrue(all(label.startswith("Particulates") for label in row.alt_labels))

    def test_a_retired_flow_is_counted_apart(self):
        by_id = {row.concept_id: row for row in self.overview().rows}
        self.assertEqual(by_id["pm10"].flows, 2)
        self.assertEqual(by_id["pm10"].deprecated_flows, 1)
        self.assertEqual(by_id["pm10"].lcia_factor_count, 2)
        self.assertEqual(self.overview().deprecated_flows, 1)
        self.assertEqual(self.overview().total_flows, 6)

    def test_the_lists_that_reached_a_window_are_named(self):
        by_id = {row.concept_id: row for row in self.overview().rows}
        self.assertEqual(by_id["pm2_5_to_pm10"].sources, ("EF 3.1", "bafu-2026-v1"))

    def test_the_filters_narrow_the_flows(self):
        overview = self.overview(filters={"window": "pm2_5_to_pm10", "source": ""})
        self.assertEqual({flow.uuid for flow in overview.flows}, {"u-coarse-air", "u-coarse-bafu"})
        overview = self.overview(filters={"window": "", "source": "bafu-2026-v1"})
        self.assertEqual([flow.uuid for flow in overview.flows], ["u-coarse-bafu"])
        self.assertEqual(len(self.overview().window_options()), 3)

    def test_a_build_without_merge_outcomes_shows_no_refusals_and_no_rows_by_list(self):
        overview = self.overview()
        self.assertEqual(overview.unread, [])
        self.assertEqual(overview.lists, ())

    def test_the_page_renders_with_its_sections(self):
        body = self.client.get("/flow-objects/particles/").get_data(as_text=True)
        self.assertEqual(self.client.get("/flow-objects/particles/").status_code, 200)
        for text in ("The scheme", "Rows the merge would refuse", "Particles (PM2.5 - PM10)", "Particulates, &lt; 10 um"):
            with self.subTest(text):
                self.assertIn(text, body)

    def test_the_page_is_reached_from_the_flow_object_views(self):
        body = self.client.get("/flow-objects/water/").get_data(as_text=True)
        self.assertIn('href="/flow-objects/particles/"', body)


class EmptyAndAbsentDatabaseTestCase(unittest.TestCase):
    def test_an_empty_database_is_a_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "consensus-flows.sqlite3"
            sqlite3.connect(path).close()
            client = create_app(database_path=path).test_client()
            response = client.get("/flow-objects/particles/")
            self.assertEqual(response.status_code, 200)
            self.assertIn("no <code>flow_objects</code> table", response.get_data(as_text=True))

    def test_no_database_is_a_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = create_app(database_path=Path(tmp) / "absent.sqlite3").test_client()
            self.assertEqual(client.get("/flow-objects/particles/").status_code, 200)


if __name__ == "__main__":
    unittest.main()
