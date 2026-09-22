"""The shell of the consolidated review application.

Phase 1 of `plans/webapp-consolidation.md`. What is pinned here is the class of
defect the four applications this replaces actually have, rather than the
happy path:

- **A route that only works when a file happens to exist.** Three ETL pages read
  files the pipeline stopped writing and have shown an empty state ever since;
  the inputs app raises on start-up if `ef-31-flows.json` is absent. So: 200
  with data, 200 with an empty database, 200 with no database at all.
- **A link to a page that does not exist.** `/duplicate-context-by-pattern`
  renders a template nobody wrote, and `wsgi/merge.py` imports a deleted module.
  So: every `href` a template emits resolves against the URL map.
- **A connection nobody closes, and a global loaded at import.** So: the request
  connection is read-only and is gone when the request ends.

The query layer is tested separately, without Flask, against a fixture database
written by the pipeline's own writers -- a fixture that disagreed with the
schema would make these pass over a shape the pipeline never produces.
"""

import re
import sqlite3
import tempfile
import unittest
from pathlib import Path

from brightway_flows.merge.report import UnmatchedRow
from brightway_flows.sources import resolve_source_list
from brightway_flows.merge.store import (
    MergeOutcome,
    MergeRunInput,
    write_merge_run,
)
from brightway_flows.pipeline.review_records import (
    ChangeEvent,
    ElementCoverage,
    ElementStatus,
    PipelineRun,
    ReviewQueue,
    ReviewQueueItem,
    Severity,
)
from brightway_flows.pipeline.review_tables import (
    REVIEW_SCHEMA_VERSION,
    number_change_events,
    write_review_tables,
)
from brightway_flows.webapps.app import SECTIONS, create_app, db, navigation
from brightway_flows.webapps.app.queries import overview as queries

SOURCE = resolve_source_list("ecoinvent-3.12")
TEMPLATE_DIR = (
    Path(__file__).resolve().parent.parent
    / "src" / "brightway_flows" / "webapps" / "app" / "templates"
)
STATIC_DIR = (
    Path(__file__).resolve().parent.parent
    / "src" / "brightway_flows" / "webapps" / "app" / "static"
)

#: A colour literal: a hex triple/sextet/octet, or an `rgb()`/`rgba()` call.
_COLOUR_LITERAL = re.compile(r"#[0-9a-fA-F]{3,8}(?![0-9a-fA-F])|rgba?\([^)]*\)")


def _colour_token_spans(css: str) -> list[tuple[int, int]]:
    """Byte ranges where a colour literal is a token definition, not a use.

    A `:root` rule -- bare, chained with `[data-theme=...]`, or nested one
    level inside `@media (prefers-color-scheme: dark)` -- is where every
    colour is *named*. Everywhere else, a colour has to spend that name.
    """
    spans = []
    i = 0
    while (brace := css.find("{", i)) != -1:
        selector = css[i:brace]
        depth = 1
        j = brace + 1
        while depth and j < len(css):
            if css[j] == "{":
                depth += 1
            elif css[j] == "}":
                depth -= 1
            j += 1
        if ":root" in selector or "prefers-color-scheme" in selector:
            spans.append((brace, j))
        i = j
    return spans


def _colour_literals_outside_tokens(css: str) -> list[str]:
    spans = _colour_token_spans(css)
    return [
        match.group(0)
        for match in _COLOUR_LITERAL.finditer(css)
        if not any(start <= match.start() < end for start, end in spans)
    ]


def _write_fixture(path: Path, *, queues=(), elements=(), changes=()) -> None:
    """A database with the review tables filled, written by the real writer."""
    numbered = number_change_events(list(changes), flow_object_id_by_uuid={})
    write_review_tables(
        path,
        run=PipelineRun(
            run_id="run-1",
            timestamp="2026-08-06T00:00:00+00:00",
            schema_version=REVIEW_SCHEMA_VERSION,
            flow_count=400,
            change_count=len(numbered),
            input_files=["/data/ef-31-flows.json"],
            transformer_names=["bootstrap_labels", "consensus_match"],
        ),
        stats=[],
        changes=numbered,
        queue_items=list(queues),
        formula_mismatches=[],
        element_coverage=list(elements),
        context_mappings=[],
    )


def _write_merge(path: Path) -> None:
    row = UnmatchedRow(
        source_uuid="s-1", source_name="Flow s-1", source_context=["air"],
        source_unit="kg", source_cas="", source_ec="",
        reason="no-flow-object-candidate",
    )
    write_merge_run(
        path,
        run_id="merge-1",
        started_at="2026-08-06T00:01:00+00:00",
        finished_at="2026-08-06T00:02:00+00:00",
        inputs=[MergeRunInput(
            run_id="merge-1", list_name="ecoinvent", list_version="3.12",
            sequence=0, row_count=1,
        )],
        outcomes=[MergeOutcome.from_unmatched(
            "merge-1", SOURCE, row, has_candidates=False,
        )],
        stats={},
    )


class ShellStatesTestCase(unittest.TestCase):
    """The three states every route has to survive."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "consensus-flows.sqlite3"

    def client(self):
        app = create_app(self.path)
        app.config["TESTING"] = True
        return app.test_client()

    def test_a_missing_database_is_a_page_not_a_crash(self):
        """The expected first state of a checkout. It has to say what to run."""
        response = self.client().get("/run/")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn(str(self.path), body)
        self.assertIn("brightway-flows build", body)

    def test_a_database_with_no_review_tables_still_renders(self):
        """What a data directory looks like after an upgrade and before a rebuild."""
        sqlite3.connect(self.path).close()
        response = self.client().get("/run/")
        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("no <code>pipeline_runs</code> row", body)
        # An em dash, not a zero: this database cannot answer, which is not the
        # same as answering "nothing".
        self.assertIn("—", body)
        self.assertNotIn(">0<", body)

    def test_a_filled_database_renders_the_run(self):
        _write_fixture(self.path)
        response = self.client().get("/run/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("run-1", response.get_data(as_text=True))

    def test_the_stylesheet_is_served_from_this_package(self):
        """Not from a CDN. The apps this replaces do not render offline."""
        response = self.client().get("/static/app.css")
        self.assertEqual(response.status_code, 200)
        self.assertIn("--diff-added", response.get_data(as_text=True))

    def test_colour_is_always_a_token(self):
        """A curator page nobody drew still has to use the token for its role.

        Every colour question the design boards answer is answered once, in
        the `:root` blocks at the top of `app.css`. A hex or `rgb()` value
        anywhere else is a colour the boards never approved.
        """
        css = (STATIC_DIR / "app.css").read_text(encoding="utf-8")
        self.assertEqual(_colour_literals_outside_tokens(css), [])

    def test_the_stylesheet_fetches_no_font_from_somewhere_else(self):
        """Inter is self-hosted; the canvas links Google Fonts, the app does not."""
        css = (STATIC_DIR / "app.css").read_text(encoding="utf-8")
        self.assertNotIn("fonts.googleapis.com", css)
        self.assertNotIn("fonts.gstatic.com", css)
        self.assertNotIn("//cdn.", css)
        self.assertIn('url("fonts/InterVariable.woff2")', css)

    def test_the_font_and_its_licence_are_checked_in(self):
        self.assertTrue((STATIC_DIR / "fonts" / "InterVariable.woff2").is_file())
        self.assertTrue((STATIC_DIR / "fonts" / "OFL.txt").is_file())


class ContentTestCase(unittest.TestCase):
    """What the current-run page says about a run that needs a curator."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "consensus-flows.sqlite3"

    def body(self):
        app = create_app(self.path)
        app.config["TESTING"] = True
        return app.test_client().get("/run/").get_data(as_text=True)

    def test_a_blocked_queue_is_called_out_before_any_count(self):
        _write_fixture(self.path, queues=[
            ReviewQueueItem(
                queue_name=ReviewQueue.CAS_AMBIGUOUS, item_key="a",
                severity=Severity.BLOCKING,
            ),
        ])
        body = self.body()
        self.assertIn("Needs a curator", body)
        self.assertIn("cas-ambiguous", body)

    def test_a_run_with_nothing_blocked_says_so(self):
        """A page that can only report problems is a page nobody trusts."""
        _write_fixture(self.path, queues=[
            ReviewQueueItem(
                queue_name=ReviewQueue.EC_CROSS_CHECK, item_key="a",
                severity=Severity.INFO,
            ),
        ])
        body = self.body()
        self.assertIn("Nothing waiting", body)
        self.assertNotIn("Needs a curator", body)

    def test_a_bounded_run_says_so_before_the_counts(self):
        """Every count below it describes part of the list, not the list."""
        write_review_tables(
            self.path,
            run=PipelineRun(
                run_id="run-1", timestamp="2026-08-06T00:00:00+00:00",
                schema_version=REVIEW_SCHEMA_VERSION, max_flows=400,
            ),
            stats=[],
            changes=[], queue_items=[], formula_mismatches=[],
            element_coverage=[], context_mappings=[],
        )
        self.assertIn("Bounded run", self.body())

    def test_the_merge_is_on_the_same_page_as_the_transform(self):
        """They are one build. The old apps could not say that."""
        _write_fixture(self.path)
        _write_merge(self.path)
        body = self.body()
        self.assertIn("merge-1", body)
        self.assertIn("ecoinvent 3.12", body)


class QueryTestCase(unittest.TestCase):
    """`queries/` holds no Flask import, so it is tested without a request."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "consensus-flows.sqlite3"

    def overview(self):
        connection = db.connect(self.path)
        try:
            return queries.load_overview(connection)
        finally:
            connection.close()

    def test_an_absent_table_reads_as_unknown_not_as_zero(self):
        """Zero would say "nothing to review"; the truth is "not in this file"."""
        sqlite3.connect(self.path).close()
        content = self.overview().content
        self.assertIsNone(content.elementary_flows)
        self.assertIsNone(content.changes)

    def test_queues_sort_most_blocking_first(self):
        _write_fixture(self.path, queues=[
            ReviewQueueItem(queue_name=ReviewQueue.EC_MALFORMED, item_key="a",
                            severity=Severity.INFO),
            ReviewQueueItem(queue_name=ReviewQueue.EC_MALFORMED, item_key="b",
                            severity=Severity.INFO),
            ReviewQueueItem(queue_name=ReviewQueue.CAS_AMBIGUOUS, item_key="c",
                            severity=Severity.BLOCKING),
        ])
        names = [queue.name for queue in self.overview().queues]
        self.assertEqual(names, ["cas-ambiguous", "ec-malformed"])

    def test_an_empty_queue_is_left_out(self):
        """A curator opens this to find work. Empty queues are chrome."""
        _write_fixture(self.path)
        self.assertEqual(self.overview().queues, [])

    def test_element_coverage_splits_covered_from_not(self):
        _write_fixture(self.path, elements=[
            ElementCoverage(atomic_number=1, symbol="H", name="Hydrogen",
                            status=ElementStatus.LINKED),
            ElementCoverage(atomic_number=2, symbol="He", name="Helium",
                            status=ElementStatus.MISSING),
            ElementCoverage(atomic_number=3, symbol="Li", name="Lithium",
                            status=ElementStatus.NOT_LINKED),
        ])
        checks = self.overview().checks
        self.assertEqual(checks.covered_elements, 1)
        self.assertEqual(checks.uncovered_elements, 2)
        self.assertEqual(checks.total_elements, 3)

    def test_the_change_count_covers_every_transformer(self):
        """The reason `changelog` replaces `consensus_changes` on this page."""
        _write_fixture(self.path, changes=[
            ChangeEvent(uuid="u-1", field_name="unit", old_value="kg",
                        new_value="m3", transformer="unit_normalization"),
            ChangeEvent(uuid="u-1", field_name="cas_numbers", old_value=[],
                        new_value=["124-38-9"], transformer="consensus_match"),
        ])
        self.assertEqual(self.overview().content.changes, 2)

    def test_a_run_needs_a_curator_when_the_merge_left_anything_unplaced(self):
        """An unmatched source flow is a decision, the same as a blocked rename."""
        _write_fixture(self.path)
        _write_merge(self.path)
        overview = self.overview()
        self.assertEqual(overview.blocking_total, 0)
        self.assertEqual(overview.merge.unmatched, 1)
        self.assertTrue(overview.needs_a_curator)


class ConnectionTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "consensus-flows.sqlite3"
        _write_fixture(self.path)

    def test_the_connection_refuses_to_write(self):
        """`mode=ro` and `PRAGMA query_only`, so a stray INSERT in a query
        module raises rather than editing the artifact the pipeline owns."""
        connection = db.connect(self.path)
        try:
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute("DELETE FROM pipeline_runs")
        finally:
            connection.close()

    def test_the_request_connection_is_closed_when_the_request_ends(self):
        app = create_app(self.path)
        with app.test_request_context("/run/"):
            connection = db.get_connection()
            self.assertIs(db.get_connection(), connection, "one per request")
        # Outside the context the teardown has run; the connection is unusable.
        with self.assertRaises(sqlite3.ProgrammingError):
            connection.execute("SELECT 1")

    def test_nothing_is_read_while_the_app_is_being_built(self):
        """The inputs app loads a 189 MB file at import and raises when it is
        absent, so a worker cannot start without it."""
        missing = Path(self._tmp.name) / "nope.sqlite3"
        app = create_app(missing)
        self.assertEqual(app.config["CONSENSUS_DB_PATH"], missing)


class WsgiEntryTestCase(unittest.TestCase):
    """Every deployment entry point has to import.

    `wsgi/merge.py` named `webapps.merge_review`, deleted when `run_report`
    replaced it, so it raised `ImportError` on start-up -- and
    `docs/operating/deployment.md` went on telling people to serve it. Nothing
    caught that because nothing imported the `wsgi/` modules.
    """

    WSGI_DIR = Path(__file__).resolve().parent.parent / "wsgi"

    def test_every_entry_point_exposes_an_application(self):
        import importlib.util

        for path in sorted(self.WSGI_DIR.glob("*.py")):
            with self.subTest(entry=path.name):
                spec = importlib.util.spec_from_file_location(
                    f"wsgi_{path.stem}", path
                )
                self.assertIsNotNone(spec)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                self.assertTrue(
                    callable(getattr(module, "application", None)),
                    f"{path.name} exposes no WSGI application",
                )

    def test_the_consolidated_entry_point_exists(self):
        self.assertTrue((self.WSGI_DIR / "app.py").exists())

    def test_the_dead_merge_entry_point_is_gone(self):
        self.assertFalse((self.WSGI_DIR / "merge.py").exists())


class LinkIntegrityTestCase(unittest.TestCase):
    """Every link a template emits has to go somewhere.

    Both dead pages in the applications this replaces are this defect:
    `/duplicate-context-by-pattern` 500s on a template that does not exist, and
    the ETL dashboard links to it from its navigation.
    """

    #: `href="..."` with a literal value, which is the only kind that can be
    #: checked statically. `url_for` calls are checked by Flask itself.
    _HREF = re.compile(r'href="(/[^"{}]*)"')

    def test_every_literal_href_resolves_to_a_route(self):
        app = create_app(Path("/nonexistent.sqlite3"))
        adapter = app.url_map.bind("localhost")
        for template in sorted(TEMPLATE_DIR.rglob("*.html")):
            for href in self._HREF.findall(template.read_text()):
                path = href.split("?", 1)[0].split("#", 1)[0]
                if not path:
                    continue
                with self.subTest(template=template.name, href=href):
                    try:
                        adapter.match(path)
                    except Exception as error:  # noqa: BLE001 -- reported below
                        self.fail(f"{template.name} links to {href}: {error}")

    def test_the_navigation_offers_only_sections_that_exist(self):
        """It grows a section at a time, and never advertises one early."""
        app = create_app(Path("/nonexistent.sqlite3"))
        adapter = app.url_map.bind("localhost")
        for group in navigation().values():
            for section in group:
                with self.subTest(section=section["key"]):
                    adapter.match(section["href"])

    def test_every_section_is_built(self):
        """`SECTIONS` carried the shape of the finished app while it was being
        built, with an href filled in per phase. All of them are reachable now,
        so this pins that -- a section losing its href is a regression, not a
        stage. `docs` joined them when the project's documentation moved into
        the application that needs it, and `factors` when `characterise` gave it
        something to show. The order is the top bar's and then the Browse
        panel's (`plans/public-site.md` §3): the published records first, the
        curators' tools under Build & review after them.  `download` and
        `about` joined `top` when step 5 built their pages."""
        keys = [section.key for section in SECTIONS]
        self.assertEqual(
            keys,
            ["docs", "download", "about", "flows", "substances", "factors", "checks",
             "overview", "scores", "queue", "merge"],
        )
        self.assertEqual(
            [section["key"] for group in navigation().values() for section in group],
            keys,
        )


if __name__ == "__main__":
    unittest.main()
