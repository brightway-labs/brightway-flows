"""The controls every table shares, and the two pages that were reorganised.

Nothing here is about one section.  These are the pieces a reader meets on every
page -- the pager, the reset, the badge filters, the order a dropdown is in --
plus the two addresses that moved: the front page to `/`, and the build's own
state to `/run/`.

What is pinned, and why each one is a defect somebody could reintroduce:

- **The front page is the homepage.** A published flow list whose front page
  is a build report answers the wrong question first.  (It was the
  documentation until `plans/public-site.md` step 8; the documentation is at
  `/docs/`, and the homepage has its own tests in `test_webapp_home.py`.)
- **The run page names no filesystem path.** It printed the database and every
  input by absolute path, on a site published to the internet, to readers with
  no account on the machine.
- **A download is offered only when the file is there.** A link to a file the
  build did not write is worse than a row saying it did not write it.
- **A filter dropdown is in alphabetical order and names its values.** Both
  lists were ordered by row count, and a type read as `ENVO_01000892`.
- **A random landing page happens only when nothing was asked for.** Anything in
  the query string is a question, and a question gets its own answer.
- **A badge is a filter, and its count is the rows it selects.** A chip counted
  over a different set from the table is a chip that lies.
"""

import re
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from brightway_flows.domain.context_registry import context_from_dict
from brightway_flows.domain.elementary_flow import ElementaryFlow
from brightway_flows.domain.flow import Flow
from brightway_flows.domain.flow_object import FlowObject
from brightway_flows.merge.report import UnmatchedRow
from brightway_flows.merge.store import (
    MergeOutcome,
    MergeRunInput,
    write_merge_run,
)
from brightway_flows.pipeline.review_records import (
    FormulaMismatch,
    PipelineRun,
    ReviewQueue,
    ReviewQueueItem,
    Severity,
)
from brightway_flows.pipeline.review_tables import (
    REVIEW_SCHEMA_VERSION,
    write_review_tables,
)
from brightway_flows.pipeline.sqlite import _write_consensus_sqlite
from brightway_flows.sources import resolve_source_list
from brightway_flows.webapps.app import artifacts, create_app, db
from brightway_flows.webapps.app.labels import type_label
from brightway_flows.webapps.app.queries import common
from brightway_flows.webapps.app.queries import queue as queue_queries
from brightway_flows.webapps.app.sections import SECTIONS

SOURCE = resolve_source_list("ecoinvent-3.12")


def _step(body: str, description: str) -> str:
    """Which page one pager button goes to, by the label it announces.

    Read off `aria-label` rather than off the visible text, because that is the
    thing a screen reader is given and the thing a silent regression would drop.
    """
    match = re.search(rf'aria-label="{description}"\s+href="([^"]+)"', body)
    if match is None:
        return ""
    page = re.search(r"page=(\d+)", match.group(1))
    return page.group(1) if page else ""


_AIR = context_from_dict(
    {"dimension": "Environmental", "media": "Air", "strata": "Unknown"}
)

#: An ENVO class the land taxonomy anchors, so the snapshot can name it.
CROPLAND = "http://purl.obolibrary.org/obo/ENVO_01000892"
NEUTRAL_MOLECULE = "https://w3id.org/chemrof/NeutralMolecule"


def _write_fixture(path: Path, *, queues=(), substances=2) -> None:
    """A small database written by the pipeline's own writers.

    *substances* many flow objects, so a page can be asked for more rows than
    fit on one page without the fixture becoming a second implementation of the
    schema.
    """
    import brightway_flows.pipeline.sqlite as sqlite_module

    flows, flow_objects, elementary = [], [], []
    for index in range(substances):
        uuid, object_id = f"u-{index}", f"fo-{index}"
        # Two types, so the type dropdown has something to sort and to name.
        types = [CROPLAND] if index % 2 else [NEUTRAL_MOLECULE]
        flows.append(Flow(
            uuid=uuid, source="EF 3.1", unit="kg",
            prefLabel=[{"@value": f"Substance {index:04d}", "@language": "en"}],
            context=_AIR,
        ))
        flow_objects.append(FlowObject(
            flow_object_id=object_id,
            prefLabel=[{"@value": f"Substance {index:04d}"}],
            altLabel=[], classifications={}, properties={}, references=[],
            created_from={}, types=types,
        ))
        elementary.append(ElementaryFlow(
            elementary_flow_id=uuid, flow_object_id=object_id, unit="kg",
            unit_iri="", source="EF 3.1", context=_AIR, context_iri="",
            lcia_methods=[], general_comment=None, source_refs=[],
        ))

    original = sqlite_module.CONSENSUS_DB_FILEPATH
    sqlite_module.CONSENSUS_DB_FILEPATH = path
    try:
        _write_consensus_sqlite(flows, [], flow_objects, elementary)
    finally:
        sqlite_module.CONSENSUS_DB_FILEPATH = original

    write_review_tables(
        path,
        run=PipelineRun(
            run_id="run-1",
            timestamp="2026-08-06T00:00:00+00:00",
            schema_version=REVIEW_SCHEMA_VERSION,
            flow_count=len(flows),
            input_files=["/home/somebody/.local/share/x/ef-31-flows.json"],
            transformer_names=["bootstrap_labels"],
        ),
        stats=[], changes=[], queue_items=list(queues),
        formula_mismatches=[], element_coverage=[], context_mappings=[],
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


class _AppTestCase(unittest.TestCase):
    SUBSTANCES = 2

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "consensus-flows.sqlite3"
        _write_fixture(self.path, substances=self.SUBSTANCES)

    def client(self):
        app = create_app(self.path)
        app.config["TESTING"] = True
        return app.test_client()

    def body(self, path: str) -> str:
        return self.client().get(path).get_data(as_text=True)

    def connection(self):
        connection = db.connect(self.path)
        self.addCleanup(connection.close)
        return connection


class FrontPageTestCase(_AppTestCase):
    """`/` is the homepage, and `/run/` is the build's own state."""

    def test_the_front_page_is_the_homepage(self):
        response = self.client().get("/")
        self.assertEqual(response.status_code, 200)
        # The homepage's own heading, rather than a run report or the docs.
        body = response.get_data(as_text=True)
        self.assertIn('class="home__title"', body)
        self.assertNotIn('class="docs', body)

    def test_the_documentation_still_answers_at_its_old_address(self):
        """Every link in an issue, a commit message or another page points there."""
        self.assertEqual(self.client().get("/docs/").status_code, 200)

    def test_every_section_has_a_blurb(self):
        for section in SECTIONS:
            with self.subTest(section.key):
                self.assertTrue(section.blurb.strip(), "a section nobody can describe")

    def test_the_run_page_is_at_its_own_address(self):
        self.assertIn("run-1", self.body("/run/"))


class RunPageTestCase(_AppTestCase):
    """No file paths, and the four files as downloads."""

    def test_the_page_names_no_filesystem_path(self):
        """It printed the database and every input by absolute path.

        A fact about one machine, published to readers who have no account on
        it -- and the only thing on the page that came close to answering "how
        do I get this data?".
        """
        body = self.body("/run/")
        self.assertNotIn(str(self.path), body)
        self.assertNotIn("/home/somebody/", body)

    def test_an_input_is_named_by_its_file_name(self):
        """Which list went into the run is still a fact about the run."""
        self.assertIn("ef-31-flows.json", self.body("/run/"))

    def test_every_artifact_is_listed_whether_or_not_it_was_written(self):
        """An absence shown as an absence.

        A build that has not been characterised has no factor file, and a row
        that vanished would say the run published fewer things rather than that
        one step has not been run.
        """
        body = self.body("/run/")
        for _key, title, filename, _description in artifacts.ARTIFACTS:
            with self.subTest(title):
                self.assertIn(filename, body)

    def test_the_database_is_offered_as_a_download(self):
        """Decision 8 came back that it may be published (#200), so it is a
        link like the other three; see `DatabaseDownloadTestCase`."""
        client = self.client()
        body = client.get("/run/").get_data(as_text=True)
        self.assertIn("/run/download/database", body)
        response = client.get("/run/download/database")
        self.addCleanup(response.close)
        self.assertEqual(response.status_code, 200)

    def test_a_file_this_build_did_not_write_is_not_a_link(self):
        """A link to a missing file is worse than a row saying it is missing."""
        missing = [
            entry
            for entry in artifacts.available(self.path, self.path.parent)
            if not entry.exists
        ]
        self.assertTrue(missing, "the fixture writes no JSON exports")
        body = self.body("/run/")
        for entry in missing:
            with self.subTest(entry.key):
                self.assertNotIn(f"/run/download/{entry.key}", body)
                self.assertEqual(
                    self.client().get(f"/run/download/{entry.key}").status_code, 404
                )

    def test_the_exports_are_looked_for_beside_the_database(self):
        """Not in whatever data directory the *process* was started with.

        `filesystem` resolves that once, at import; an application pointed at
        one build would otherwise offer another build's files.
        """
        entry = artifacts.artifact("flows", self.path, self.path.parent)
        self.assertEqual(entry.path.parent, self.path.parent)

    def test_an_unknown_key_is_a_404(self):
        self.assertEqual(self.client().get("/run/download/nope").status_code, 404)

    def test_a_size_is_stated_in_units_a_reader_compares_against(self):
        """Powers of 1000, like every browser and operating system."""
        entry = artifacts.Artifact(
            key="k", title="t", filename="f", description="d",
            path=Path("/nowhere"), exists=True, size=2_400_000_000,
        )
        self.assertEqual(entry.readable_size, "2.4 GB")


class TypeLabelTestCase(unittest.TestCase):
    """A type is named the way its vocabulary names it."""

    def test_an_envo_accession_is_named_by_the_anchor_snapshot(self):
        """`ENVO_01000892` is an identifier, not a word."""
        self.assertEqual(type_label(CROPLAND), "area of cropland")

    def test_a_chemrof_class_is_named_by_the_term_registry(self):
        self.assertEqual(type_label(NEUTRAL_MOLECULE), "Neutral molecule")

    def test_an_unknown_key_keeps_its_own_text(self):
        """"The app has no name for this" and "there is nothing here" are
        different claims, and only one of them is true."""
        self.assertEqual(type_label("unclassified"), "Unclassified")

    def test_nothing_is_nothing(self):
        self.assertEqual(type_label(""), "")


class OptionOrderTestCase(_AppTestCase):
    """Every filter dropdown is in alphabetical order, with a count."""

    def test_options_sort_on_the_name_and_not_on_the_count(self):
        options = common.alphabetical([
            ("v-1", "Zinc", 900), ("v-2", "aluminium", 3), ("v-3", "Boron", 40),
        ])
        self.assertEqual(
            options,
            [("v-2", "aluminium (3)"), ("v-3", "Boron (40)"), ("v-1", "Zinc (900)")],
        )

    def test_the_count_stays_in_the_label(self):
        """So the popular value is still recognisable -- it is just no longer
        the only one that is easy to find."""
        self.assertEqual(common.alphabetical([("v", "kg", 1204)]), [("v", "kg (1,204)")])

    def test_the_type_dropdown_offers_the_names_in_order(self):
        from brightway_flows.webapps.app.queries import substances as queries

        options = queries.substance_type_options(self.connection())
        labels = [label for _value, label in options]
        self.assertEqual(labels, sorted(labels, key=str.lower))
        self.assertIn("area of cropland (1)", labels)
        self.assertIn("Neutral molecule (1)", labels)


class RandomLandingTestCase(_AppTestCase):
    """Opening somewhere other than the first page, but only when unasked."""

    #: Three pages of flows, so a random page has somewhere to land.
    SUBSTANCES = common.PAGE_SIZE * 3

    def test_the_sentinel_is_not_a_page_anybody_can_ask_for(self):
        """`clamp_page` turns every number below 1 into 1, so 0 never was one."""
        self.assertEqual(common.clamp_page(common.RANDOM_PAGE, 500), 1)

    def test_a_real_page_number_is_clamped_and_not_randomised(self):
        with mock.patch("random.randint", return_value=99):
            self.assertEqual(common.resolve_page(2, 500), 2)
            self.assertEqual(common.resolve_page(9999, 500), 10)

    def test_the_sentinel_asks_for_a_page_that_exists(self):
        with mock.patch("random.randint", return_value=7) as randint:
            self.assertEqual(common.resolve_page(common.RANDOM_PAGE, 500), 7)
        randint.assert_called_once_with(1, 10)

    def test_arriving_with_nothing_asked_for_lands_elsewhere(self):
        with mock.patch("random.randint", return_value=3):
            for path in ("/flows/", "/flow-objects/"):
                with self.subTest(path):
                    body = self.body(path)
                    # Said out loud: a list that opens on page 3 with no
                    # explanation looks like a bug.
                    self.assertIn("chosen at random", body)
                    self.assertIn("Page 3 of 3", body)

    def test_a_question_gets_its_own_answer(self):
        """Anything in the query string -- a filter, a sort, a page."""
        with mock.patch("random.randint", side_effect=AssertionError("randomised")):
            for path in ("/flows/?page=2", "/flows/?q=Substance", "/flows/?sort=name",
                         "/flow-objects/?page=2"):
                with self.subTest(path):
                    body = self.body(path)
                    self.assertNotIn("chosen at random", body)


class PagerTestCase(_AppTestCase):
    """First, back five, previous, next, forward five, last."""

    SUBSTANCES = common.PAGE_SIZE * 12

    def test_every_step_is_offered(self):
        body = self.body("/flows/?page=6")
        for label in ("« First", "−5", "Previous", "Next", "+5", "Last »"):
            with self.subTest(label):
                self.assertIn(label, body)

    def test_a_jump_that_would_leave_the_list_lands_on_the_edge(self):
        """The reader asked to go back, and going back as far as there is to go
        is the answer."""
        self.assertEqual(_step(self.body("/flows/?page=3"), "Back 5 pages"), "1")

    def test_a_jump_that_fits_is_taken_whole(self):
        self.assertEqual(_step(self.body("/flows/?page=3"), "Forward 5 pages"), "8")

    def test_a_step_that_cannot_be_taken_keeps_its_place(self):
        """A pager whose buttons move as you page through it is a pager you have
        to re-read every time."""
        body = self.body("/flows/?page=1")
        self.assertIn('<span class="button" aria-disabled="true">« First</span>', body)
        self.assertIn('<span class="button" aria-disabled="true">−5</span>', body)

    def test_the_last_page_is_the_last_page(self):
        self.assertEqual(_step(self.body("/flows/?page=1"), "Last page"), "12")


class ResetTestCase(_AppTestCase):
    """One control that clears the search, the filters, the sort and the page."""

    def test_a_list_page_offers_it(self):
        self.assertIn('href="/flows/">Reset', self.body("/flows/?q=x&sort=name&page=2"))

    def test_it_is_drawn_even_when_nothing_is_filtered(self):
        """A control that appears and disappears is one a reader has to look
        for -- and a filter selecting nothing is when it is most wanted."""
        self.assertIn(">Reset", self.body("/flows/?q=nothing-matches-this"))

    def test_it_keeps_what_the_route_needs_to_exist(self):
        """The queue's name is the address, not a filter."""
        body = self.body("/queue/cas-ambiguous?q=x&severity=blocking")
        self.assertIn('href="/queue/cas-ambiguous">Reset', body)


class BadgeFilterTestCase(_AppTestCase):
    """A mark in a column is also a filter above the table."""

    QUEUES = (
        ReviewQueueItem(queue_name=ReviewQueue.CAS_AMBIGUOUS, item_key="a",
                        severity=Severity.BLOCKING),
        ReviewQueueItem(queue_name=ReviewQueue.CAS_AMBIGUOUS, item_key="b",
                        severity=Severity.BLOCKING),
        ReviewQueueItem(queue_name=ReviewQueue.CAS_AMBIGUOUS, item_key="c",
                        severity=Severity.INFO),
    )

    def setUp(self):
        super().setUp()
        _write_fixture(self.path, queues=self.QUEUES, substances=self.SUBSTANCES)

    def test_a_queue_offers_the_severities_it_has(self):
        badges, total = queue_queries.severity_badges(self.connection(), "cas-ambiguous")
        self.assertEqual(badges, [("blocking", "Blocking", 2), ("info", "Info", 1)])
        self.assertEqual(total, 3)

    def test_a_severity_with_nothing_in_it_is_not_offered(self):
        """A chip reading `review 0` is a control that can only empty the table."""
        badges, _total = queue_queries.severity_badges(
            self.connection(), "cas-ambiguous"
        )
        self.assertNotIn("review", [slug for slug, _label, _count in badges])

    def test_the_count_is_the_rows_the_chip_selects(self):
        """Counted under the search in force, not over the queue as a whole."""
        badges, total = queue_queries.severity_badges(
            self.connection(), "cas-ambiguous", query="no-such-row"
        )
        self.assertEqual(badges, [])
        self.assertEqual(total, 0)

    def test_choosing_a_badge_narrows_the_table(self):
        body = self.body("/queue/cas-ambiguous?severity=blocking")
        self.assertIn("chip--active", body)
        self.assertIn("of 2", " ".join(body.split()))

    def test_searching_does_not_drop_the_chosen_badge(self):
        """The chips hold the severity, and the search form is a second form."""
        body = self.body("/queue/cas-ambiguous?severity=blocking")
        self.assertIn('<input type="hidden" name="severity" value="blocking">', body)

    def test_the_elements_queue_offers_none(self):
        """It is a coverage table, every row the same kind of thing."""
        self.assertEqual(
            queue_queries.severity_badges(self.connection(), "elements"), ([], 0)
        )


class UnitDisagreementBadgeTestCase(_AppTestCase):
    """"Needs a decision" is the whole point of the page, so it is a filter."""

    def setUp(self):
        super().setUp()
        _write_merge(self.path)

    def test_the_badges_are_the_two_the_table_draws(self):
        from brightway_flows.webapps.app.queries import checks as queries

        badges, _total = queries.unit_disagreement_badges(self.connection())
        self.assertEqual(
            [slug for slug, _label, _count in badges],
            ["needs-a-decision", "settled"],
        )

    def test_the_page_renders_them(self):
        self.assertIn("Needs a decision", self.body("/checks/unit-disagreements"))

    def test_a_hand_edited_badge_selects_nothing_rather_than_raising(self):
        response = self.client().get("/checks/unit-disagreements?badge=nonsense")
        self.assertEqual(response.status_code, 200)


class AnchorTestCase(_AppTestCase):
    """Selecting a use class lands on the table it filters."""

    def test_a_class_link_points_at_the_table(self):
        """Three screens of definitions sit above the substances it filters, so
        the page re-rendered at the heading and left the reader to scroll."""
        body = self.body("/flow-objects/agricultural-chemicals/")
        self.assertIn('id="substances"', body)
        self.assertIn("#substances", body)

    def test_every_link_that_moves_the_table_carries_the_anchor(self):
        """Paging and sorting a table three screens below the fold must not send
        the reader back to the top of the prose above it.

        The section link in the strip of flow-object views is not one of these:
        it is a link to the page, not a link that changes what the table shows.
        """
        body = self.body("/flow-objects/agricultural-chemicals/")
        moving = [
            href
            for href in re.findall(
                r'href="(/flow-objects/agricultural-chemicals/\?[^"]*)"', body
            )
        ]
        self.assertTrue(moving, "the page emits no links into its own table")
        for href in moving:
            with self.subTest(href):
                self.assertTrue(href.endswith("#substances"), href)


class FormulaOriginTestCase(unittest.TestCase):
    """Where a substance's formula came from, which is often the whole answer.

    The check compares two strings and says they disagree.  Hydrogen-3 publishes
    `H2` because PubChem describes the bulk gas and RDKit agrees; the ChEBI
    record it cites is *ditritium* and says `T2`.  One substance, two
    descriptions, and nothing wrong with either -- which the page could not say
    while it showed the two strings and nothing else.
    """

    CHEBI = "http://purl.obolibrary.org/obo/CHEBI_29298"

    def setUp(self):
        import brightway_flows.pipeline.sqlite as sqlite_module
        from brightway_flows.domain.vocabulary import CHEMROF_MOLECULAR_FORMULA

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "consensus-flows.sqlite3"

        chebi = {
            "prov:wasGeneratedBy": "enrich_references.chebi_semantic",
            "prov:hadPrimarySource": [self.CHEBI],
            "prov:wasDerivedFrom": "chebi.basic_property_values.formula",
        }
        pubchem = {
            "prov:wasGeneratedBy": "enrich_references.pubchem_semantic",
            "prov:hadPrimarySource": ["CID:24824"],
            "prov:wasDerivedFrom": "pubchem.props.Molecular Formula",
        }
        substance = FlowObject(
            flow_object_id="fo-1",
            prefLabel=[{"@value": "Hydrogen-3"}],
            altLabel=[],
            classifications={},
            properties={
                CHEMROF_MOLECULAR_FORMULA: {
                    "@id": CHEMROF_MOLECULAR_FORMULA,
                    "@value": ["H2", "T2"],
                    "attested_by": {
                        "H2": ["enrich_references.pubchem_semantic"],
                        "T2": ["enrich_references.chebi_semantic"],
                    },
                    "provenance": [chebi, pubchem],
                }
            },
            references=[{"@id": "gmelin:16", "provenance": dict(chebi)}],
            created_from={},
        )
        flow = Flow(
            uuid="u-1", source="EF 3.1", unit="kg",
            prefLabel=[{"@value": "Hydrogen-3", "@language": "en"}], context=_AIR,
        )
        elementary = ElementaryFlow(
            elementary_flow_id="u-1", flow_object_id="fo-1", unit="kg",
            unit_iri="", source="EF 3.1", context=_AIR, context_iri="",
            lcia_methods=[], general_comment=None, source_refs=[],
        )

        original = sqlite_module.CONSENSUS_DB_FILEPATH
        sqlite_module.CONSENSUS_DB_FILEPATH = self.path
        try:
            _write_consensus_sqlite([flow], [], [substance], [elementary])
        finally:
            sqlite_module.CONSENSUS_DB_FILEPATH = original

        write_review_tables(
            self.path,
            run=PipelineRun(run_id="run-1", timestamp="2026-08-06T00:00:00+00:00",
                            schema_version=REVIEW_SCHEMA_VERSION),
            stats=[], changes=[], queue_items=[],
            formula_mismatches=[FormulaMismatch(
                flow_object_id="fo-1", chebi_id=self.CHEBI,
                similarity_score=0.0, threshold=0.6, pref_label="Hydrogen-3",
                flow_formula="H2", chebi_label="ditritium", chebi_formula="T2",
                chebi_cas_numbers=["10028-17-8"],
            )],
            element_coverage=[], context_mappings=[],
        )

    def connection(self):
        connection = db.connect(self.path)
        self.addCleanup(connection.close)
        return connection

    def page(self):
        from brightway_flows.webapps.app.queries import checks as queries

        return queries.formula_mismatches(self.connection())

    def test_every_formula_the_substance_holds_is_listed(self):
        """Not only the one published: where the declined one is the cited
        record's own string, the two records describe different things."""
        [row] = self.page().rows
        self.assertEqual([entry.formula for entry in row.origins], ["H2", "T2"])

    def test_the_published_formula_is_marked(self):
        [row] = self.page().rows
        self.assertEqual([entry.published for entry in row.origins], [True, False])

    def test_each_formula_names_the_field_it_was_read_from(self):
        """The level of detail that distinguishes "ChEBI's stated formula" from
        "computed from a SMILES we hold"."""
        [row] = self.page().rows
        self.assertEqual(
            [entry.derived_from for entry in row.origins],
            [["pubchem.props.Molecular Formula"],
             ["chebi.basic_property_values.formula"]],
        )

    def test_the_cited_record_says_what_else_it_supplied(self):
        """How a wrong citation shows itself: a record that gave this substance
        its formula, its mass and its structure is a record it is claimed to be.
        """
        [row] = self.page().rows
        [match] = row.matches
        self.assertIn("Molecular formula", match["supplied"])
        self.assertIn("a cross-reference", match["supplied"])

    def test_the_record_is_linked_rather_than_printed_as_an_iri(self):
        [row] = self.page().rows
        [match] = row.matches
        self.assertEqual(
            match["url"],
            "https://www.ebi.ac.uk/chebi/searchId.do?chebiId=CHEBI:29298",
        )

    def test_the_page_renders_them(self):
        app = create_app(self.path)
        app.config["TESTING"] = True
        body = app.test_client().get(
            "/checks/formula-mismatches"
        ).get_data(as_text=True)
        self.assertIn("Where it came from", body)
        self.assertIn("chebi.basic_property_values.formula", body)
        self.assertIn("supplied", body)


class DatabaseStatesTestCase(unittest.TestCase):
    """The three states every route has to survive, for the routes that moved."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "consensus-flows.sqlite3"

    def client(self):
        app = create_app(self.path)
        app.config["TESTING"] = True
        return app.test_client()

    def test_the_front_page_renders_without_a_database(self):
        """The homepage leaves its numbers out without one; it must not need one."""
        self.assertEqual(self.client().get("/").status_code, 200)

    def test_the_run_page_says_what_to_run(self):
        response = self.client().get("/run/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("brightway-flows build", response.get_data(as_text=True))

    def test_a_database_with_no_review_tables_still_renders_the_run_page(self):
        sqlite3.connect(self.path).close()
        self.assertEqual(self.client().get("/run/").status_code, 200)


if __name__ == "__main__":
    unittest.main()
