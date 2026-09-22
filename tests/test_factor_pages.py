"""`/factors`: the layer as it stands, rather than a backlog to drain.

The two factor queues ask a curator to decide something. These pages ask
nothing: they are for a reader who wants to know what this list says a substance
is worth, and how that compares to what the publishers say.

Six things they have to get right, and each has a test here:

* **The categories line up.** The JRC calls it `Ecotoxicity, freshwater` and
  ecoinvent calls it `ecotoxicity: freshwater`. The index is keyed on our name,
  so 25 rows carry three implementations; keyed on either publisher's own it
  would be 50 rows that never meet.
* **Nothing is named in a template.** The method sections, the columns and the
  labels come from the rows the run wrote, and this list's own implementation
  comes first because it is the one column that is always there. EF 3.1 is what
  is loaded today and it is not what will be loaded.
* **A category opens.** The index can only say how many factors a category
  holds; the page behind it is the list, addressed the way the category's own
  IRI addresses it.
* **Two implementations of one category can be put against each other.** Only
  the rows they state different numbers for, banded by the *pair* — the report's
  band is the widest among everybody who states the row, which is a different
  verdict about the same two.
* **A difference is not an error.** The report leads with the agreement and the
  band is a filter, not a verdict.
* **Nothing renders as a zero when the answer is "not asked".** A build that has
  not been characterised gets a page saying so — and an implementation that
  published nothing says what became of what it stated, because a bare zero
  reads as "the file was empty".
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import orjson

from brightway_flows.assessment.measures import Direction, collect_measures
from brightway_flows.assessment.report import _factor_lines
from brightway_flows.domain.lcia.crosswalk import (
    ef_method,
    impact_categories,
)
from brightway_flows.domain.lcia.records import (
    Band,
    CoverageGap,
    Difference,
    StatedFactor,
    stated_category,
)
from brightway_flows.lcia.categories import (
    impact_categories_for,
    published_impact_categories,
)
from brightway_flows.lcia.matching import MatchedFactor
from brightway_flows.lcia.report import Finding, FindingKind
from brightway_flows.lcia.store import CharacterisationRun, write_characterisation
from brightway_flows.webapps.app import create_app, db
from brightway_flows.webapps.app.queries import factors as queries

#: EF 3.1's implementations, read from its method file rather than from an enum:
#: an implementation belongs to a method, and which four these are is what
#: `data/lcia-impact-categories.json` says.
_METHOD = ef_method()
JRC_IMPL = _METHOD.reference
ECOINVENT_IMPL = _METHOD.implementation("ecoinvent-centre")
GREENDELTA_IMPL = _METHOD.implementation("greendelta")
CONSENSUS_IMPL = _METHOD.consensus
IMPLEMENTATION_NAMES = {row.name for row in _METHOD.implementations}

#: The category every fixture factor is under, in all four implementations.
SLUG = sorted(definition.slug for definition in impact_categories())[0]


def _category(implementation):
    return next(
        category
        for category in impact_categories_for(_METHOD.slug, implementation.slug)
        if str(category.meta.get("iri", "")).endswith(f"/{SLUG}")
    )


def _compared(
    uuid: str,
    *,
    geography: str,
    band: Band,
    ratio: float | None,
    derivation: str | None,
    amounts: dict[str, float],
) -> list[Difference]:
    """One comparison, as the table holds it: a row per implementation.

    The band and the ratio are the triple's and repeat across its rows, which is
    what makes a third implementation a third row rather than a schema change.
    """
    return [
        Difference(
            method=_METHOD.slug,
            elementary_flow_uuid=uuid,
            category_slug=SLUG,
            geography=geography,
            implemented_by=implemented_by,
            amount=amount,
            source_flow_uuid=None,
            band=band,
            ratio=ratio,
            derivation=derivation,
        )
        for implemented_by, amount in amounts.items()
    ]


def _matched(uuid: str, amount: float, *, derivation: str | None = None):
    return MatchedFactor(
        elementary_flow_uuid=uuid,
        factor=StatedFactor(
            category=stated_category(uuid="m-1", name="whatever the publisher calls it"),
            flow_uuid="",
            amount=amount,
        ),
        derivation=derivation,
    )


class FactorPageTestCase(unittest.TestCase):
    """A characterised build with two flows, three implementations, one row of
    every report."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "consensus-flows.sqlite3"
        connection = sqlite3.connect(self.path)
        connection.execute(
            "CREATE TABLE elementary_flows (uuid TEXT, pref_label_value TEXT, "
            "context_display TEXT, unit TEXT NOT NULL DEFAULT 'kg', "
            "lcia_factor_count INTEGER, "
            "flow_object_id TEXT NOT NULL DEFAULT 'fo-1', "
            "is_deprecated INTEGER NOT NULL DEFAULT 0, "
            "replaced_by_uuid TEXT, source TEXT NOT NULL DEFAULT 'EF 3.1', "
            "context_json TEXT NOT NULL DEFAULT '{}', "
            "consensus_change_count INTEGER NOT NULL DEFAULT 0, "
            "flow_json TEXT NOT NULL DEFAULT "
            "'{\"concept_associations\": [{\"source_list\": \"EF 3.1\"}]}')"
        )
        # Enough of the build's own tables for the flow page to render: it is
        # where the factor table lives, and where it sits on the page is a thing
        # this section has to get right.
        connection.execute(
            "CREATE TABLE flow_objects (flow_object_id TEXT, "
            "pref_label_value TEXT, alt_label_json TEXT NOT NULL DEFAULT '[]', "
            "classifications_json TEXT NOT NULL DEFAULT '{}', "
            "flow_type TEXT, origin_qualifier TEXT)"
        )
        connection.execute(
            "INSERT INTO flow_objects (flow_object_id, pref_label_value) "
            "VALUES ('fo-1', 'Copper hydroxide')"
        )
        connection.execute(
            "CREATE TABLE flow_object_payloads (flow_object_id TEXT, "
            "payload_json TEXT NOT NULL DEFAULT '{}')"
        )
        connection.executemany(
            "INSERT INTO elementary_flows (uuid, pref_label_value, context_display, "
            "lcia_factor_count) VALUES (?, ?, ?, ?)",
            [
                ("u-1", "Copper hydroxide", "Environmental → Ground → Unknown", 1),
                ("u-2", "Atrazine", "Environmental → Ground → Silvicultural", 0),
            ],
        )
        # The duplicate `u-1` was settled from: EF shipped one substance twice
        # in one compartment, this list kept one row and deprecated the other,
        # and the two rows' factors did not agree.  It is why there was a number
        # to decline, and until it was read the declined-numbers page could not
        # say where either number came from.
        connection.execute(
            "INSERT INTO elementary_flows (uuid, pref_label_value, "
            "context_display, lcia_factor_count, is_deprecated, replaced_by_uuid) "
            "VALUES ('u-1-old', 'Copper hydroxide', "
            "'Environmental → Ground → Unknown', 1, 1, 'u-1')"
        )
        # The two source rows a collision is between, as the merge recorded them:
        # what a reader needs to see instead of two uuids.
        connection.execute(
            "CREATE TABLE elementary_flow_sources (id INTEGER PRIMARY KEY, "
            "elementary_flow_uuid TEXT, list_name TEXT, list_version TEXT, "
            "source_flow_uuid TEXT, source_flow_name TEXT, "
            "source_metadata_json TEXT NOT NULL DEFAULT '{}')"
        )
        connection.executemany(
            "INSERT INTO elementary_flow_sources (elementary_flow_uuid, list_name, "
            "list_version, source_flow_uuid, source_flow_name, "
            "source_metadata_json) VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("u-1", "ecoinvent", "3.12", "s-1", "Glufosinate",
                 '{"original_context": ["soil"], "unit": "kg"}'),
                ("u-1", "ecoinvent", "3.12", "s-2", "Glufosinate ammonium",
                 '{"original_context": ["soil"], "unit": "kg"}'),
                # What each list shipped the collapsed rows as.  The published
                # label is `Copper hydroxide` on both by the time the layering
                # has run, so this is the only field that shows the duplication.
                ("u-1", "EF", "3.1", "s-kept", "copper hydroxide", "{}"),
                ("u-1-old", "EF", "3.1", "s-dropped", "Copper(II) hydroxide", "{}"),
            ],
        )
        connection.commit()
        connection.close()

        categories = {
            str(category.id): category for category in published_impact_categories()
        }
        jrc, ecoinvent, greendelta, consensus = (
            _category(JRC_IMPL),
            _category(ECOINVENT_IMPL),
            _category(GREENDELTA_IMPL),
            _category(CONSENSUS_IMPL),
        )
        write_characterisation(
            self.path,
            run=CharacterisationRun(
                run_id="lcia-1", started_at="2026-08-17T13:00:00+00:00",
                build_run_id="build-9",
            ),
            categories=categories,
            factors={
                str(jrc.id): [_matched("u-1", 1.5)],
                str(ecoinvent.id): [_matched("u-1", 53540.0), _matched("u-2", 6.0)],
                # The third transcription: it states a number about the same
                # flow and is not consulted about ours, so a page that shows it
                # beside the other two is what these tests are checking.
                str(greendelta.id): [_matched("u-1", 3.0)],
                str(consensus.id): [_matched("u-1", 1.5, derivation="sole")],
            },
            findings=[
                # Two source rows reaching one flow and disagreeing: the event
                # the check exists for.
                Finding(
                    kind=FindingKind.FACTOR_COLLISION,
                    implemented_by=ECOINVENT_IMPL.name,
                    elementary_flow_uuid="u-1",
                    impact_category_id=None,
                    detail="two rows, two numbers",
                    context={
                        "category": "Acidification", "geography": "YE",
                        "ratio": 397.0,
                        "rows": [
                            {"source_flow_uuid": "s-1", "amount": 134.73},
                            {"source_flow_uuid": "s-2", "amount": 53540.0},
                        ],
                    },
                ),
                # One row stating several numbers under one category and place,
                # which is not a disagreement and is not what the page opens on.
                Finding(
                    kind=FindingKind.FACTOR_COLLISION,
                    implemented_by=JRC_IMPL.name,
                    elementary_flow_uuid="u-2",
                    impact_category_id=None,
                    detail="one row, several numbers",
                    context={
                        "category": "Land use", "geography": None, "ratio": 268.0,
                        "rows": [
                            {"source_flow_uuid": None, "amount": -887.36},
                            {"source_flow_uuid": None, "amount": -227.0},
                        ],
                    },
                ),
                # A source row with factors and no flow to put them on, named
                # by the run: nothing else in the database can name it, because
                # it is the row that did not become a consensus flow.
                Finding(
                    kind=FindingKind.FLOW_NOT_REACHED,
                    implemented_by=ECOINVENT_IMPL.name,
                    elementary_flow_uuid=None,
                    impact_category_id=None,
                    detail="Silicon carries 2 factors and is merged onto no "
                           "consensus flow",
                    context={
                        "source_flow_uuid": "s-3", "name": "Silicon",
                        "context": "soil / industrial", "unit": "kg",
                        "factor_count": 2,
                        "categories": ["ecotoxicity: freshwater"],
                        "factors": [
                            {"category": "ecotoxicity: freshwater",
                             "geography": "", "amount": 0.0050755},
                            {"category": "human toxicity: non-carcinogenic",
                             "geography": "", "amount": 2.5102e-13},
                        ],
                    },
                ),
                Finding(
                    kind=FindingKind.SUPERSEDED_VALUE,
                    implemented_by=JRC_IMPL.name,
                    elementary_flow_uuid="u-1",
                    impact_category_id=None,
                    detail="Acidification: 4.1051e-06 is published and 4.11e-06 "
                           "was declined",
                    context={
                        "category": "Acidification", "published": 4.1051e-06,
                        "declined": 4.11e-06, "ratio": 1.0011936371830161,
                        "settled_by": "pipeline.deduplication",
                        # Written by `pipeline.deduplication` as a `urn:uuid:`
                        # primary source on the superseded value: the only
                        # record of which collapsed row the discarded number
                        # came from.
                        "declined_by": ["urn:uuid:u-1-old"],
                    },
                ),
            ],
            differences=[
                *_compared(
                    "u-1", geography="", band=Band.OVER_100X, ratio=35693.3,
                    derivation=None, amounts={
                        JRC_IMPL.name: 1.5,
                        ECOINVENT_IMPL.name: 53540.0,
                    },
                ),
                *_compared(
                    "u-2", geography="YE", band=Band.IDENTICAL, ratio=1.0,
                    derivation="agreed", amounts={
                        JRC_IMPL.name: 2.0,
                        ECOINVENT_IMPL.name: 2.0,
                    },
                ),
            ],
            coverage=[
                CoverageGap(
                    method=_METHOD.slug,
                    implemented_by=JRC_IMPL.name, dimension="category",
                    value=SLUG, flows=881,
                ),
                CoverageGap(
                    method=_METHOD.slug,
                    implemented_by=JRC_IMPL.name, dimension="compartment",
                    value="Environmental → Ground → Silvicultural", flows=12,
                ),
            ],
            stats={
                "difference_shared": 2, "difference_identical": 1,
                "coverage_skipped_long_term": 9018,
                "coverage_skipped_not_in_own_list": 30339,
                "ef_jrc_factors_published": 5,
                "ef_ecoinvent_centre_factors_published": 4,
                "ef_greendelta_factors_published": 3,
                "ef_consensus_factors_published": 6,
            },
        )

    def connection(self):
        connection = db.connect(self.path)
        self.addCleanup(connection.close)
        return connection

    def client(self, path: Path | None = None):
        app = create_app(path or self.path)
        app.config["TESTING"] = True
        return app.test_client()

    def _uncharacterised(self) -> Path:
        """A build with flows and no `characterise` run against it."""
        path = Path(self._tmp.name) / "plain.sqlite3"
        if not path.exists():
            connection = sqlite3.connect(path)
            connection.execute(
                "CREATE TABLE elementary_flows (uuid TEXT, flow_object_id TEXT, "
                "lcia_factor_count INTEGER NOT NULL DEFAULT 0, "
                "is_deprecated INTEGER NOT NULL DEFAULT 0, replaced_by_uuid TEXT)"
            )
            connection.commit()
            connection.close()
        return path

    def text(self, route: str) -> str:
        response = self.client().get(route)
        self.assertEqual(response.status_code, 200, route)
        return response.get_data(as_text=True)


class TheIndexTestCase(FactorPageTestCase):
    def test_the_categories_are_grouped_under_the_method_that_publishes_them(self):
        """One section per method, and the section is not written in a template.

        Two methods are registered, so the page has two sections: EF 3.1's 25
        categories and Stepwise 2006's 19. This fixture characterises only EF,
        which is why the second section's rows are all empty rather than absent
        -- a category the reader can see is a category the list publishes.
        """
        overview = queries.overview(self.connection())
        self.assertEqual(
            [method.label for method in overview.methods],
            ["EF 3.1", "Stepwise 2006"],
        )
        self.assertEqual(len(overview.methods[0].categories), 25)
        self.assertEqual(len(overview.methods[1].categories), 19)
        self.assertEqual(
            overview.categories,
            overview.methods[0].categories + overview.methods[1].categories,
        )

    def test_a_category_carries_every_implementation_of_it(self):
        """25 rows and not 75: the crosswalk is what knows that two publishers'
        names are one category."""
        overview = queries.overview(self.connection())
        self.assertEqual(
            IMPLEMENTATION_NAMES,
            set(overview.methods[0].implementations),
        )
        row = next(row for row in overview.categories if row.total)
        self.assertEqual(
            row.count(ECOINVENT_IMPL.name).factors, 2
        )
        self.assertEqual(row.count(JRC_IMPL.name).factors, 1)

    def test_this_list_is_the_first_column_however_little_it_says(self):
        """The one column the layout guarantees. Ordering the columns by weight
        alone put it wherever the run happened to leave it, which is not where a
        reader looking for what *this list* publishes expects it."""
        overview = queries.overview(self.connection())
        method = overview.methods[0]
        self.assertEqual(method.ours, [CONSENSUS_IMPL.name])
        self.assertEqual(method.implementations[0], CONSENSUS_IMPL.name)
        self.assertNotIn(CONSENSUS_IMPL.name, method.inputs)
        self.assertEqual(
            overview.implementations[0].implemented_by, CONSENSUS_IMPL.name
        )
        self.assertTrue(overview.implementations[0].ours)

    def test_the_implementations_read_are_ordered_by_how_much_they_say(self):
        overview = queries.overview(self.connection())
        totals = {
            summary.implemented_by: summary.factors
            for summary in overview.implementations
        }
        read = [totals[name] for name in overview.methods[0].inputs]
        self.assertEqual(read, sorted(read, reverse=True))

    def test_a_category_nobody_filled_is_still_a_row(self):
        """A count of zero is honest; leaving the category out would say it does
        not exist.

        43: the 24 of EF 3.1's 25 this fixture does not fill, and all 19 of
        Stepwise 2006's, which it characterises none of."""
        overview = queries.overview(self.connection())
        empty = [row for row in overview.categories if row.total == 0]
        self.assertEqual(len(empty), 43)

    def test_a_category_row_carries_the_way_to_address_it(self):
        """Method, version and slug -- what its IRI identifies it by. A link
        built from the name would break the day a second method publishes a
        category with the same one."""
        row = next(
            row for row in queries.overview(self.connection()).categories
            if row.slug == SLUG
        )
        self.assertTrue(row.linkable)
        self.assertEqual((row.method_slug, row.version), ("ef", "3.1"))

    def test_the_page_names_the_run_and_the_build_it_read(self):
        html = self.text("/factors/")
        self.assertIn("build-9", html)
        self.assertIn("Characterisation factors", html)

    def test_the_page_links_each_category_to_its_factors(self):
        html = self.text("/factors/")
        self.assertIn(f"/factors/category/ef/3.1/{SLUG}", html)

    def test_the_page_names_no_method_and_no_implementation_of_its_own(self):
        """Everything on it comes from the rows the run wrote. A template that
        spells `EF 3.1` or `ecoinvent Centre` is a template that goes on saying
        so after a second method is loaded."""
        html = self.text("/factors/")
        for name in ("Three implementations", "EF 3.1 as the European"):
            self.assertNotIn(name, html)

    def test_a_build_without_a_characterisation_says_so(self):
        """Rather than three zeros, which would read as "characterised by
        nobody" -- a different statement from "nobody has asked yet"."""
        plain = self._uncharacterised()
        response = self.client(plain).get("/factors/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("No factors yet", response.get_data(as_text=True))


class AnImplementationThatPublishedNothingTestCase(FactorPageTestCase):
    """A zero beside an implementation's name is the one number in this section
    a reader cannot act on, so the page says what became of what it stated."""

    def _stats(self, **extra):
        """The same run, with the ecoinvent counters a real run writes."""
        connection = sqlite3.connect(self.path)
        connection.execute(
            "UPDATE lcia_impact_categories SET factor_count = 0, flow_count = 0, "
            "non_zero_factor_count = 0 WHERE implemented_by = ?",
            (ECOINVENT_IMPL.name,),
        )
        connection.execute(
            "DELETE FROM lcia_characterization_factors WHERE impact_category_id IN "
            "(SELECT id FROM lcia_impact_categories WHERE implemented_by = ?)",
            (ECOINVENT_IMPL.name,),
        )
        connection.execute(
            "UPDATE lcia_runs SET stats_json = ?",
            (orjson.dumps({
                "difference_shared": 2, "difference_identical": 1,
                "ef_ecoinvent_centre_factors_stated": 27415,
                "ef_ecoinvent_centre_factors_published": 0,
                "ef_ecoinvent_centre_source_flows_merged": 0,
                "ef_ecoinvent_centre_flow-not-reached": 7960,
                **extra,
            }).decode(),),
        )
        connection.commit()
        connection.close()

    def test_the_summary_says_what_was_stated_and_what_reached_a_flow(self):
        self._stats()
        summary = next(
            row for row in queries.overview(self.connection()).implementations
            if row.implemented_by == ECOINVENT_IMPL.name
        )
        self.assertTrue(summary.silent)
        self.assertEqual(summary.stated, 27415)
        self.assertEqual(summary.merged, 0)
        self.assertEqual(summary.unreached, 7960)
        self.assertEqual(summary.unpublished, 27415)

    def test_the_page_says_why_rather_than_showing_a_bare_zero(self):
        """`ecoinvent Centre  0` reads as "the file was empty". The file was not
        empty: nothing it names was merged into the build that was
        characterised."""
        self._stats()
        html = self.text("/factors/")
        self.assertIn("27,415", html)
        self.assertIn("none of the flows they name was merged", html)
        self.assertIn("/factors/findings/flow-not-reached", html)

    def test_an_implementation_that_published_everything_says_nothing_extra(self):
        summary = next(
            row for row in queries.overview(self.connection()).implementations
            if row.implemented_by == JRC_IMPL.name
        )
        self.assertFalse(summary.silent)
        self.assertIsNone(summary.stated)
        self.assertEqual(summary.unpublished, 0)


class TheCategoryPageTestCase(FactorPageTestCase):
    """The row of the index, opened: every factor published under one category."""

    def detail(self):
        return queries.category(
            self.connection(), method="ef", version="3.1", slug=SLUG
        )

    def test_a_category_is_addressed_by_method_version_and_slug(self):
        detail = self.detail()
        self.assertEqual(detail.label, "EF 3.1")
        self.assertEqual(len(detail.ids), 4)
        self.assertEqual(detail.implementations[0], CONSENSUS_IMPL.name)

    def test_an_unknown_category_is_a_404(self):
        """A slug of another method's is not this method's category, and a page
        of zeros would say it was."""
        self.assertIsNone(
            queries.category(self.connection(), method="recipe", version="3.1",
                             slug=SLUG)
        )
        self.assertEqual(
            self.client().get(f"/factors/category/recipe/3.1/{SLUG}").status_code,
            404,
        )
        self.assertEqual(
            self.client().get("/factors/category/ef/3.1/nonsense").status_code, 404
        )

    def test_it_lists_every_flow_the_category_characterises(self):
        page = queries.category_factors(self.connection(), self.detail())
        self.assertEqual(page.total, 2)
        rows = {row.elementary_flow_uuid: row for row in page.rows}
        self.assertEqual(
            rows["u-1"].amounts,
            {
                JRC_IMPL.name: 1.5,
                ECOINVENT_IMPL.name: 53540.0,
                GREENDELTA_IMPL.name: 3.0,
                CONSENSUS_IMPL.name: 1.5,
            },
        )
        self.assertEqual(rows["u-1"].derivation, "sole")

    def test_a_page_is_flows_and_not_factor_rows(self):
        """The table holds a row per implementation, so paging over rows would
        put a third of a comparison at the bottom of a page -- and would change
        what a page holds the day a third implementation is loaded."""
        page = queries.category_factors(self.connection(), self.detail())
        self.assertEqual(page.total, len(page.rows))
        self.assertEqual(page.total, 2)

    def test_it_is_sorted_by_the_largest_number_anybody_states(self):
        """The question the page is opened with is which substances this
        category weighs heavily, and that answer is not alphabetical."""
        page = queries.category_factors(self.connection(), self.detail())
        self.assertEqual(
            [row.elementary_flow_uuid for row in page.rows], ["u-1", "u-2"]
        )
        by_name = queries.category_factors(
            self.connection(), self.detail(), sort="flow"
        )
        self.assertEqual(
            [row.elementary_flow_uuid for row in by_name.rows], ["u-2", "u-1"]
        )

    def test_a_row_this_list_publishes_nothing_for_says_so(self):
        """Somebody states a number and this list does not: the row a curator
        opening a category is looking for."""
        page = queries.category_factors(self.connection(), self.detail())
        rows = {row.elementary_flow_uuid: row for row in page.rows}
        self.assertTrue(rows["u-2"].disputed)
        self.assertFalse(rows["u-1"].disputed)

    def test_it_can_be_searched_by_flow_name(self):
        page = queries.category_factors(
            self.connection(), self.detail(), query="Atrazine"
        )
        self.assertEqual([row.elementary_flow_uuid for row in page.rows], ["u-2"])

    def test_the_page_renders_the_numbers_and_the_flows(self):
        html = self.text(f"/factors/category/ef/3.1/{SLUG}")
        self.assertIn("53,540", html)
        self.assertIn("Copper hydroxide", html)
        self.assertIn("Atrazine", html)
        self.assertIn(CONSENSUS_IMPL.name, html)

    def test_a_build_without_a_characterisation_says_so(self):
        response = self.client(self._uncharacterised()).get(
            f"/factors/category/ef/3.1/{SLUG}"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("No factors yet", response.get_data(as_text=True))


class TheCategoryComparisonTestCase(FactorPageTestCase):
    """One category narrowed to two of its implementations.

    The category page is as many implementations wide as there are; this is the
    other question a reader arrives with — *these two disagree about what?* — and
    the thing it has to get right is that the band is the pair's own. The
    published report bands a triple by the widest pair among everybody who states
    it, which with three implementations loaded is a different verdict about the
    same two.
    """

    #: A second and a third differing row, so that ordering, searching and the
    #: band across a stated zero are exercised by something other than one row.
    EXTRA = (
        ("u-3", "Aluminium", {JRC_IMPL: 1.3384e-06,
                              ECOINVENT_IMPL: 1.3384e-05}),
        ("u-4", "Zinc", {JRC_IMPL: 0.0,
                         ECOINVENT_IMPL: 5.0}),
    )

    def setUp(self):
        super().setUp()
        connection = sqlite3.connect(self.path)
        for uuid, name, amounts in self.EXTRA:
            connection.execute(
                "INSERT INTO elementary_flows (uuid, pref_label_value, "
                "context_display, lcia_factor_count) VALUES (?, ?, ?, 0)",
                (uuid, name, "Environmental → Air → Unknown"),
            )
            for implementation, amount in amounts.items():
                connection.execute(
                    "INSERT INTO lcia_characterization_factors "
                    "(impact_category_id, elementary_flow_uuid, geography, amount) "
                    "VALUES (?, ?, '', ?)",
                    (str(_category(implementation).id), uuid, amount),
                )
        connection.commit()
        connection.close()

    def detail(self):
        return queries.category(
            self.connection(), method="ef", version="3.1", slug=SLUG
        )

    def compare(self, left=None, right=None, **kwargs):
        detail = self.detail()
        pair = queries.default_pair(detail)
        return queries.pair_differences(
            self.connection(), detail,
            left=left or pair[0], right=right or pair[1], **kwargs,
        )

    def test_it_opens_on_two_publishers_and_not_on_ours(self):
        """This list's implementation is derived from theirs, so it agrees with
        one of them by construction: the comparison carrying information is
        between two independent renderings of the method."""
        self.assertEqual(
            queries.default_pair(self.detail()),
            (ECOINVENT_IMPL.name, JRC_IMPL.name),
        )

    def test_a_category_nobody_filled_cannot_be_compared(self):
        """Rather than a page comparing two implementations that both say
        nothing, which would read as perfect agreement."""
        empty = next(
            definition.slug for definition in impact_categories()
            if definition.slug != SLUG
        )
        detail = queries.category(
            self.connection(), method="ef", version="3.1", slug=empty
        )
        self.assertIsNone(queries.default_pair(detail))
        response = self.client().get(
            f"/factors/category/ef/3.1/{empty}/differences"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Nothing to compare here", response.get_data(as_text=True))

    def test_the_band_is_the_pair_s_own_and_not_the_widest_among_everybody(self):
        """`u-1` is 1.5 in two implementations and 53,540 in the third. The
        published report bands it `over-100x`, which is the right answer about
        the method and the wrong one about the two that agree exactly."""
        self.assertEqual(
            dict(queries.band_counts(self.connection()))["over-100x"], 1
        )
        page, comparison = self.compare(
            left=CONSENSUS_IMPL.name, right=JRC_IMPL.name
        )
        self.assertEqual((comparison.shared, comparison.identical), (1, 1))
        self.assertEqual(comparison.differing, 0)
        self.assertEqual(page.rows, [])

    def test_only_the_rows_they_state_different_numbers_for_are_listed(self):
        """The agreement is the headline and not a page of rows: a reader
        scrolling identical numbers is a reader who stops reading."""
        page, comparison = self.compare()
        self.assertEqual(comparison.shared, 3)
        self.assertEqual(comparison.identical, 0)
        self.assertEqual(page.total, 3)
        self.assertEqual(
            [row.elementary_flow_uuid for row in page.rows], ["u-4", "u-1", "u-3"]
        )

    def test_a_triple_only_one_of_them_states_is_counted_and_not_listed(self):
        """Two flow lists of different sizes, which is not a disagreement about a
        number and would drown the rows that are."""
        _page, comparison = self.compare()
        self.assertEqual(
            comparison.only,
            {ECOINVENT_IMPL.name: 1, JRC_IMPL.name: 0},
        )

    def test_a_stated_zero_against_a_number_ranks_above_every_ratio(self):
        """It is not a smaller disagreement than 35,693×, it is a different kind
        of one: whether the substance has an effect at all."""
        page, _comparison = self.compare()
        self.assertEqual(page.rows[0].elementary_flow_uuid, "u-4")
        self.assertEqual(page.rows[0].band, "incomparable")
        self.assertIsNone(page.rows[0].ratio)

    def test_a_row_says_which_of_the_two_is_higher(self):
        """By name, and by the pair rather than by everybody: the third
        implementation is not on this page and must not decide its arrow."""
        page, _comparison = self.compare()
        rows = {row.elementary_flow_uuid: row for row in page.rows}
        self.assertEqual(rows["u-1"].higher, ECOINVENT_IMPL.name)
        self.assertEqual(
            set(rows["u-1"].amounts), {ECOINVENT_IMPL.name,
                                       JRC_IMPL.name}
        )

    def test_a_row_says_what_this_list_published_about_the_disagreement(self):
        """The reader's next question about two publishers differing by 35,693×,
        and one neither of the two columns can answer."""
        page, _comparison = self.compare()
        rows = {row.elementary_flow_uuid: row for row in page.rows}
        self.assertEqual((rows["u-1"].ours, rows["u-1"].derivation), (1.5, "sole"))
        self.assertFalse(rows["u-1"].queued)
        self.assertTrue(rows["u-3"].queued)

    def test_the_pair_is_ordered_by_ratio_and_can_be_ordered_by_flow(self):
        page, _comparison = self.compare(sort="flow")
        self.assertEqual(
            [row.elementary_flow_uuid for row in page.rows], ["u-3", "u-1", "u-4"]
        )

    def test_a_band_narrows_the_comparison_and_the_counts_stay_whole(self):
        """The chips count every difference between the two, so a reader can see
        what they are filtering away rather than only what is left."""
        page, comparison = self.compare(band="over-100x")
        self.assertEqual([row.elementary_flow_uuid for row in page.rows], ["u-1"])
        self.assertEqual(comparison.differing, 3)
        self.assertEqual(
            {slug: count for slug, _label, count in comparison.bands},
            {"incomparable": 1, "outside-tolerance": 2, "within-tolerance": 0},
        )
        self.assertNotIn(
            "identical", [slug for slug, _label, _count in comparison.bands]
        )

    def test_it_can_be_searched_by_flow_name(self):
        page, _comparison = self.compare(query="Aluminium")
        self.assertEqual([row.elementary_flow_uuid for row in page.rows], ["u-3"])

    def test_a_pair_is_addressed_by_the_slugs_its_iris_use(self):
        """`implemented_by` is prose with an em dash in it. The slug is what the
        category's own IRI already spells the implementation."""
        self.assertEqual(
            self.detail().slugs[JRC_IMPL.name], "jrc"
        )
        self.assertEqual(self.detail().named("ecoinvent-centre"),
                         ECOINVENT_IMPL.name)
        html = self.text(
            f"/factors/category/ef/3.1/{SLUG}/differences"
            "?left=jrc&right=ecoinvent-centre"
        )
        self.assertIn("53,540", html)

    def test_an_implementation_this_category_does_not_have_is_a_404(self):
        """Rather than a silent fallback: a stale URL that quietly compares two
        other implementations is a page answering a question nobody asked."""
        self.assertEqual(
            self.client().get(
                f"/factors/category/ef/3.1/{SLUG}/differences?left=recipe"
            ).status_code,
            404,
        )

    def test_one_side_alone_still_opens_on_a_comparison(self):
        html = self.text(
            f"/factors/category/ef/3.1/{SLUG}/differences?left=brightway-flows"
        )
        self.assertIn(CONSENSUS_IMPL.name, html)
        self.assertIn("Copper hydroxide", html)

    def test_the_page_leads_with_the_agreement_and_names_neither_of_them(self):
        """The numbers and the labels come from the rows the run wrote. A
        template naming two implementations goes on comparing those two after a
        third is loaded."""
        html = self.text(f"/factors/category/ef/3.1/{SLUG}/differences")
        self.assertIn("Both state a number", html)
        self.assertIn("A difference is not an error", html)
        self.assertIn(ECOINVENT_IMPL.name, html)
        self.assertIn("35,693×", html)

    def test_a_build_without_a_characterisation_says_so(self):
        response = self.client(self._uncharacterised()).get(
            f"/factors/category/ef/3.1/{SLUG}/differences"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("No factors yet", response.get_data(as_text=True))


class TheDifferenceReportTestCase(FactorPageTestCase):
    def test_it_is_sorted_by_ratio_widest_first(self):
        page, _implementations = queries.differences(self.connection())
        self.assertEqual(
            [row.elementary_flow_uuid for row in page.rows], ["u-1", "u-2"]
        )

    def test_a_page_is_triples_and_not_rows(self):
        """The table holds a row per implementation, so paging over rows would
        put half a comparison at the bottom of a page."""
        page, implementations = queries.differences(self.connection())
        self.assertEqual(page.total, 2)
        self.assertEqual(
            implementations,
            sorted({JRC_IMPL.name, ECOINVENT_IMPL.name}),
        )
        self.assertEqual(
            page.rows[0].amounts,
            {
                JRC_IMPL.name: 1.5,
                ECOINVENT_IMPL.name: 53540.0,
            },
        )

    def test_a_band_is_a_filter_and_not_a_verdict(self):
        page, _implementations = queries.differences(
            self.connection(), band="identical"
        )
        self.assertEqual([row.band for row in page.rows], ["identical"])
        self.assertEqual(
            dict(queries.band_counts(self.connection()))["over-100x"], 1
        )

    def test_a_row_says_which_implementation_is_higher(self):
        """The first question a reader of a ratio asks, and one a ratio alone
        cannot answer.  By name, so a third implementation is answerable too."""
        page, _implementations = queries.differences(self.connection())
        self.assertEqual(page.rows[0].widest, ECOINVENT_IMPL.name)
        page, _implementations = queries.differences(
            self.connection(), band="identical"
        )
        self.assertEqual(page.rows[0].widest, "")

    def test_a_row_says_what_this_list_published(self):
        page, _implementations = queries.differences(
            self.connection(), band="identical"
        )
        self.assertEqual(page.rows[0].derivation, "agreed")
        queued, _implementations = queries.differences(
            self.connection(), band="over-100x"
        )
        self.assertEqual(queued.rows[0].derivation, "")

    def test_the_category_is_named_in_our_words(self):
        """Not the slug the table stores: a page keyed on `ecotoxicity-
        freshwater` makes a reader learn an identifier to read a number."""
        page, _implementations = queries.differences(self.connection())
        self.assertNotEqual(page.rows[0].category, SLUG)
        self.assertIn(page.rows[0].category, {
            category.name for category in published_impact_categories()
        })

    def test_it_can_be_searched_by_flow_name(self):
        page, _implementations = queries.differences(
            self.connection(), query="Atrazine"
        )
        self.assertEqual([row.elementary_flow_uuid for row in page.rows], ["u-2"])

    def test_the_page_renders_both_numbers(self):
        html = self.text("/factors/differences")
        self.assertIn("53,540", html)
        self.assertIn("Copper hydroxide", html)


class TheCoverageSummaryTestCase(FactorPageTestCase):
    def test_it_is_grouped_by_implementation_and_dimension(self):
        coverage = queries.coverage(self.connection())
        self.assertEqual(list(coverage), [(_METHOD.slug, JRC_IMPL.name)])
        self.assertEqual(
            sorted(row.dimension for row in coverage[(_METHOD.slug, JRC_IMPL.name)]),
            ["category", "compartment"],
        )

    def test_a_category_row_is_named_and_not_slugged(self):
        row = next(
            row
            for row in queries.coverage(self.connection())[
                (_METHOD.slug, JRC_IMPL.name)
            ]
            if row.dimension == "category"
        )
        self.assertNotEqual(row.value, SLUG)

    def test_the_page_says_what_was_set_aside_and_why(self):
        """30,339 of the apparent gaps are a flow the implementation's own list
        never had, and a page that hid that would be overstating the finding."""
        html = self.text("/factors/coverage")
        self.assertIn("30,339", html)
        self.assertIn("9,018", html)
        self.assertIn("Not a defect list", html)


class TheFindingsTestCase(FactorPageTestCase):
    def test_every_kind_is_listed_even_at_zero(self):
        """A kind with no rows this run is not a kind that cannot happen."""
        kinds = queries.findings_index(self.connection())
        self.assertEqual(
            [row.kind for row in kinds],
            ["factor-collision", "unit-crossing", "superseded-value",
             "flow-not-reached", "redirect-followed", "redirect-refused"],
        )
        self.assertEqual([row.count for row in kinds], [2, 0, 1, 1, 0, 0])

    def test_a_page_names_the_flow_and_what_was_found(self):
        html = self.text("/factors/findings/factor-collision")
        self.assertIn("Copper hydroxide", html)
        self.assertIn("397×", html)

    def test_an_unknown_kind_is_a_404(self):
        self.assertEqual(
            self.client().get("/factors/findings/nonsense").status_code, 404
        )


class ACollisionTestCase(FactorPageTestCase):
    """Two things wear one label, and only one of them is a disagreement.

    A publisher row stating several numbers for one category and one place is
    distinguishing them by something this build did not read — EF states a
    `location` on 42,871 of its factors, and a list extracted before that was
    read puts 213 land-use numbers on one flow. Those factors are *expected* to
    differ; listed beside a real collision they say a defect is 222 defects.
    """

    def test_the_page_opens_on_the_rows_that_are_a_disagreement(self):
        page = queries.findings(self.connection(), kind="factor-collision")
        self.assertEqual([row.elementary_flow_uuid for row in page.rows], ["u-1"])
        self.assertEqual(page.total, 1)

    def test_the_other_kind_is_counted_and_reachable(self):
        """Counted rather than dropped: it is a real thing about the run, and a
        page that hid it would be hiding a stale input."""
        self.assertEqual(
            queries.collision_sources(self.connection()),
            [("many", "Two source rows disagree", 1),
             ("one", "One row, several numbers", 1)],
        )
        page = queries.findings(
            self.connection(), kind="factor-collision", sources="one"
        )
        self.assertEqual([row.elementary_flow_uuid for row in page.rows], ["u-2"])

    def test_a_collision_names_the_rows_rather_than_their_uuids(self):
        """`s-1` is not a substance. The name, the compartment and the unit come
        from the source rows the merge already recorded against the flow."""
        page = queries.findings(self.connection(), kind="factor-collision")
        row = page.rows[0]
        self.assertEqual(
            [candidate.source_flow_name for candidate in row.colliding],
            ["Glufosinate", "Glufosinate ammonium"],
        )
        self.assertEqual(
            [candidate.amount for candidate in row.colliding], [134.73, 53540.0]
        )
        self.assertEqual(row.unit, "kg")
        self.assertEqual(row.source_rows, 2)

    def test_the_page_states_the_place_the_numbers_were_compared_inside(self):
        """A collision is between rows that share a place, so the place is what
        the disagreement is not explained by — the reader's first guess."""
        html = self.text("/factors/findings/factor-collision")
        self.assertIn("Glufosinate ammonium", html)
        self.assertIn("53,540", html)
        self.assertIn("YE", html)
        self.assertNotIn("s-1", html)

    def test_the_other_kind_says_why_it_is_not_a_disagreement(self):
        html = self.text("/factors/findings/factor-collision?source=one")
        self.assertIn("Not a disagreement", html)
        self.assertIn("Atrazine", html)


class AnUnreachedRowTestCase(FactorPageTestCase):
    """The row that did not become a consensus flow.

    Nothing else in the database can name it — it is the row the merge did not
    place — so the finding carries the name, the compartment, the unit and the
    factors, and the page reads them from there.
    """

    def test_the_row_is_named_and_its_factors_are_listed(self):
        page = queries.findings(self.connection(), kind="flow-not-reached")
        row = page.rows[0]
        self.assertEqual(row.source_flow_name, "Silicon")
        self.assertEqual(row.source_context, "soil / industrial")
        self.assertEqual(row.source_unit, "kg")
        self.assertEqual(
            [(stated.category, stated.amount) for stated in row.stated],
            [("ecotoxicity: freshwater", 0.0050755),
             ("human toxicity: non-carcinogenic", 2.5102e-13)],
        )

    def test_it_says_whether_a_consensus_flow_carries_the_row_at_all(self):
        """Nothing at all is a question for the merge; a flow that carries the
        row and none of its factors is a different fault in a different place."""
        page = queries.findings(self.connection(), kind="flow-not-reached")
        self.assertIsNone(page.rows[0].carried_by)
        connection = sqlite3.connect(self.path)
        connection.execute(
            "INSERT INTO elementary_flow_sources (elementary_flow_uuid, "
            "list_name, list_version, source_flow_uuid, source_flow_name) "
            "VALUES ('u-1', 'ecoinvent', '3.12', 's-3', 'Silicon')"
        )
        connection.commit()
        connection.close()
        carried = queries.findings(
            self.connection(), kind="flow-not-reached"
        ).rows[0].carried_by
        self.assertEqual(carried.elementary_flow_uuid, "u-1")
        self.assertEqual(carried.flow_name, "Copper hydroxide")
        self.assertEqual(carried.factors, 1)

    def test_the_page_names_the_row_rather_than_counting_its_factors(self):
        html = self.text("/factors/findings/flow-not-reached")
        self.assertIn("Silicon", html)
        self.assertIn("soil / industrial", html)
        self.assertIn("ecotoxicity: freshwater", html)
        self.assertIn("no consensus flow carries this row", html)


class ADeclinedNumberTestCase(FactorPageTestCase):
    """The two numbers and the ratio between them, as columns.

    A sentence a reader has to parse three of to compare two is not a table, and
    the questions asked here — where was the biggest factor settled, where were
    the two furthest apart — are sorts.
    """

    def test_the_row_carries_both_numbers_and_the_ratio(self):
        page = queries.findings(self.connection(), kind="superseded-value")
        row = page.rows[0]
        self.assertEqual(row.category, "Acidification")
        self.assertEqual(row.published, 4.1051e-06)
        self.assertEqual(row.declined, 4.11e-06)
        self.assertEqual(row.settled_by, "pipeline.deduplication")
        self.assertAlmostEqual(row.ratio, 1.0011936, places=6)

    def test_it_can_be_sorted_by_the_factor_and_by_the_ratio(self):
        """Both read out of the finding's own context: they mean different
        things to different kinds, so neither is a column of the table."""
        for sort in ("factor", "-factor", "ratio", "-ratio"):
            page = queries.findings(
                self.connection(), kind="superseded-value", sort=sort
            )
            self.assertEqual(page.total, 1, sort)

    def test_the_page_puts_them_side_by_side(self):
        html = self.text("/factors/findings/superseded-value")
        self.assertIn("Declined", html)
        self.assertIn("pipeline.deduplication", html)
        self.assertIn("Acidification", html)

    def test_the_row_names_both_flows_the_number_was_settled_from(self):
        """Two numbers means two rows, and the page said nothing about either.

        Without them a reader can see that a choice was made and not how the
        list came to have a choice to make.
        """
        row = queries.findings(self.connection(), kind="superseded-value").rows[0]
        self.assertEqual([entry.uuid for entry in row.merged], ["u-1", "u-1-old"])

    def test_each_row_carries_what_its_list_shipped_it_as(self):
        """Which is where the duplication shows: the published label is the
        same on every row of a collapse.

        Every source row, not the first: `u-1` was merged from ecoinvent as well
        as from EF, and choosing between the names would be this page deciding
        which list to believe.
        """
        kept, dropped = queries.findings(
            self.connection(), kind="superseded-value"
        ).rows[0].merged
        self.assertIn(("EF 3.1", "copper hydroxide"), kept.shipped_as)
        self.assertIn(("ecoinvent 3.12", "Glufosinate"), kept.shipped_as)
        self.assertEqual(dropped.shipped_as, [("EF 3.1", "Copper(II) hydroxide")])

    def test_the_kept_row_comes_first_and_is_marked(self):
        row = queries.findings(self.connection(), kind="superseded-value").rows[0]
        self.assertEqual([entry.survivor for entry in row.merged], [True, False])
        self.assertEqual([entry.is_deprecated for entry in row.merged], [False, True])

    def test_the_row_that_published_the_declined_number_is_marked(self):
        """Not the same question as which row was deprecated: where the two are
        one number written twice, the more precise one wins whichever row it
        came from, and then the survivor's own number is the declined one."""
        row = queries.findings(self.connection(), kind="superseded-value").rows[0]
        declined = [entry.uuid for entry in row.merged if entry.declined_here]
        self.assertEqual(declined, ["u-1-old"])

    def test_the_page_shows_them(self):
        html = self.text("/factors/findings/superseded-value")
        self.assertIn("Settled from", html)
        self.assertIn("Copper(II) hydroxide", html)
        self.assertIn("published the declined number", html)
        # And says what the duplication is, rather than leaving a reader to
        # infer it from a column of pairs.
        self.assertIn("issues/64", html)


class WhatAssessSeesTestCase(FactorPageTestCase):
    """`assess` folds the run's own counters in rather than recounting them."""

    def test_the_run_s_counters_arrive_as_factor_measures(self):
        measures = collect_measures(self.connection())
        self.assertEqual(measures["factors.difference_shared"].value, 2)
        self.assertEqual(measures["factors.difference_identical"].value, 1)
        self.assertEqual(
            measures["factors.coverage_skipped_not_in_own_list"].value, 30339
        )

    def test_every_factor_measure_is_neutral(self):
        """Two other teams' files being closer together is not this pipeline
        getting better, and a report calling it progress would be crediting this
        build for somebody else's release."""
        measures = collect_measures(self.connection())
        factors = [m for key, m in measures.items() if key.startswith("factors.")]
        self.assertTrue(factors)
        self.assertEqual({m.direction for m in factors}, {Direction.NEUTRAL})
        self.assertEqual({m.group for m in factors}, {"factors"})

    def test_a_queue_length_is_not_counted_twice(self):
        """The two factor queues are `review_queue` rows, so their length already
        arrives as `queue.<name>`; a second measure of one number is a second
        number that can disagree in a report."""
        measures = collect_measures(self.connection())
        self.assertEqual(
            [key for key in measures if key.startswith("factors.") and key.endswith("_items")],
            [],
        )

    def test_the_terminal_report_leads_with_the_agreement(self):
        """Seven numbers, and the choice is the point: the headline of this
        layer is that the implementations of one method agree."""
        lines = _factor_lines(
            SimpleNamespace(measures=collect_measures(self.connection())),
            lambda text, **_: text,
        )
        rendered = "\n".join(lines)
        self.assertIn("WHAT IT CHARACTERISED", rendered)
        self.assertIn("triples more than one of them states", rendered)
        self.assertIn("identical, to the last digit", rendered)
        # And each implementation's own count, named by the key `characterise`
        # writes.  #348 put every statistic about one method's own work under
        # that method's slug -- `jrc_factors_published` became
        # `ef_jrc_factors_published` -- and this section lost four of its seven
        # lines with nothing going red, the number #157, #165 and #347 all bound
        # among them.  Naming the labels is what makes a rename say so.
        for label in ("the JRC's", "the ecoinvent Centre's", "GreenDelta's", "this list's"):
            self.assertIn(label, rendered)

    def test_the_report_omits_the_section_when_nothing_characterised(self):
        connection = sqlite3.connect(self._uncharacterised())
        self.addCleanup(connection.close)
        self.assertEqual(
            _factor_lines(
                SimpleNamespace(measures=collect_measures(connection)),
                lambda text, **_: text,
            ),
            [],
        )

    def test_a_build_without_a_characterisation_has_no_factor_measures(self):
        """Absent, not zero: a build nothing has characterised has not been
        measured, which is a different fact."""
        connection = sqlite3.connect(self._uncharacterised())
        self.addCleanup(connection.close)
        self.assertEqual(
            [key for key in collect_measures(connection) if key.startswith("factors.")],
            [],
        )


class OneFlowsFactorsTestCase(FactorPageTestCase):
    """A flow's own factor table: one row per factor, sortable.

    The wide shape -- a column per implementation -- is right for a page about
    one *category*, where the same number is stated twice. It is wrong about a
    flow: a flow is characterised by several methods, whose implementations do
    not line up with each other, so the table grew a column for every
    implementation of every method and left most of them empty.
    """

    def test_a_factor_is_a_row_and_names_its_method_and_implementation(self):
        rows = queries.for_flow(self.connection(), "u-1")
        self.assertEqual(len(rows), 4)
        self.assertEqual({row.method for row in rows}, {"EF 3.1"})
        self.assertEqual(
            {row.implemented_by for row in rows},
            IMPLEMENTATION_NAMES,
        )
        stated = {row.implemented_by: row.amount for row in rows}
        self.assertEqual(stated[JRC_IMPL.name], 1.5)
        self.assertEqual(stated[ECOINVENT_IMPL.name], 53540.0)
        self.assertEqual(stated[GREENDELTA_IMPL.name], 3.0)

    def test_the_row_says_how_this_list_arrived_at_its_number(self):
        rows = queries.for_flow(self.connection(), "u-1")
        derivations = {row.implemented_by: row.derivation for row in rows}
        self.assertEqual(derivations[CONSENSUS_IMPL.name], "sole")
        self.assertEqual(derivations[JRC_IMPL.name], "")

    def test_it_can_be_ordered_by_any_of_its_columns(self):
        """Including by implementation, which orders ours first rather than
        alphabetically: it is the column the page is read for."""
        by_amount = queries.for_flow(self.connection(), "u-1", sort="amount")
        self.assertEqual(
            [row.amount for row in by_amount], sorted(row.amount for row in by_amount)
        )
        self.assertEqual(
            queries.for_flow(self.connection(), "u-1", sort="-amount")[0].amount,
            53540.0,
        )
        self.assertEqual(
            queries.for_flow(
                self.connection(), "u-1", sort="implementation"
            )[0].implemented_by,
            CONSENSUS_IMPL.name,
        )

    def test_a_hand_edited_sort_falls_back_rather_than_failing(self):
        self.assertEqual(
            len(queries.for_flow(self.connection(), "u-1", sort="nonsense")), 4
        )

    def test_a_flow_only_one_implementation_characterises(self):
        rows = queries.for_flow(self.connection(), "u-2")
        self.assertEqual(
            [row.implemented_by for row in rows], [ECOINVENT_IMPL.name]
        )
        self.assertFalse(rows[0].derivation)

    def test_a_flow_nobody_characterises_has_no_table(self):
        self.assertEqual(queries.for_flow(self.connection(), "u-404"), [])

    def test_the_page_puts_the_factors_after_the_concept_associations(self):
        """What a flow *is* comes before what it is worth: a number about a flow
        means nothing until the reader knows which substance it is about."""
        html = self.text("/flows/u-1")
        # From `<main>`: the Browse panel above it names "Characterisation
        # factors" too, in the Factors entry's summary.
        html = html[html.index('<main'):]
        self.assertLess(
            html.index("Concept associations"),
            html.index("Characterisation factors"),
        )

    def test_the_identity_does_not_carry_a_factor_count(self):
        """A count of factors is not part of what a flow is, and the table below
        is the number it was standing in for."""
        html = self.text("/flows/u-1")
        identity = html[html.index("Identity") : html.index("Characterisation")]
        self.assertNotIn("LCIA factors", identity)


if __name__ == "__main__":
    unittest.main()
