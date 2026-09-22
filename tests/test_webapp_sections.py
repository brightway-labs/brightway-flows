"""The four sections ported in Phase 2: flows, substances, checks and merge.

The query layer is tested against a fixture database built by the pipeline's own
writer, without Flask. The routes get one smoke test each, plus the three states
every route has to survive -- data, an empty database, no database -- because
that class of failure is most of what was wrong with the applications these
replace.

What is pinned beyond "it renders":

- **Filters and paging happen in SQL.** The ETL app read everything and sliced
  in Python, which is what made it unusable on the real database.
- **A search FTS5 cannot parse falls back rather than 500s.** `C6H6 AND` is a
  reasonable thing to type and a syntax error to FTS5.
- **A page beyond the end is the last page.** Not an error, and not an empty
  table under a pager claiming there is more.
- **Deprecated flows are hidden by default.** They have been replaced; a reader
  looking for a substance wants the row that is current.
- **The detail page reads no history.** That is the whole point of moving it
  behind `/flows/<uuid>/changes`, and it is only true if nothing queries for it.
"""

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
    FormulaMismatch,
    PipelineRun,
)
from brightway_flows.pipeline.review_tables import (
    REVIEW_SCHEMA_VERSION,
    number_change_events,
    write_review_tables,
)
from brightway_flows.pipeline.sqlite import _write_consensus_sqlite
from brightway_flows.domain.context_registry import context_from_dict
from brightway_flows.domain.elementary_flow import ElementaryFlow
from brightway_flows.domain.flow import Flow
from brightway_flows.domain.flow_object import FlowObject
from brightway_flows.webapps.app import create_app, db
from brightway_flows.webapps.app.queries import checks as check_queries
from brightway_flows.webapps.app.queries import flows as flow_queries
from brightway_flows.webapps.app.queries import merge as merge_queries
from brightway_flows.webapps.app.queries import substances as substance_queries

SOURCE = resolve_source_list("ecoinvent-3.12")

#: Neither medium is a context on its own: air needs a vertical stratum or
#: an indoor class, and water needs a body.
_AIR = context_from_dict(
    {"dimension": "Environmental", "media": "Air", "strata": "Unknown"}
)
_WATER = context_from_dict(
    {"dimension": "Environmental", "media": "Water", "water_body": "Unknown"}
)


def _flow(uuid, name, *, context=_AIR, unit="kg",
          source="EF 3.1", cas=None, deprecated=False) -> Flow:
    """One harmonised flow, in the shape `_write_consensus_sqlite` takes."""
    return Flow(
        uuid=uuid,
        source=source,
        unit=unit,
        prefLabel=[{"@value": name, "@language": "en"}],
        context=context,
        cas_numbers=[cas] if cas else [],
        owl_deprecated=True if deprecated else None,
    )


def _flow_object(flow_object_id, name, *, cas=None, alt_labels=(), smiles=None,
                 types=(), origin_qualifier=None,
                 parent_flow_object_id=None) -> FlowObject:
    from brightway_flows.domain.vocabulary import (
        CHEMINF_CAS_REGISTRY_NUMBER,
        CHEMROF_SMILES_STRING,
    )

    return FlowObject(
        flow_object_id=flow_object_id,
        prefLabel=[{"@value": name, "@language": "en"}],
        altLabel=[{"@value": label, "@language": "en"} for label in alt_labels],
        classifications=(
            {CHEMINF_CAS_REGISTRY_NUMBER: {"@value": list(cas)}} if cas else {}
        ),
        properties=(
            {CHEMROF_SMILES_STRING: {"@value": [smiles]}} if smiles else {}
        ),
        references=[],
        created_from={},
        types=list(types) or None,
        origin_qualifier=origin_qualifier,
        parent_flow_object_id=parent_flow_object_id,
    )


def _elementary(uuid, flow_object_id, *, unit="kg", source="EF 3.1") -> ElementaryFlow:
    return ElementaryFlow(
        elementary_flow_id=uuid,
        flow_object_id=flow_object_id,
        source=source,
        context=None,
        context_iri="",
        unit=unit,
        unit_iri="",
        lcia_methods=[],
        general_comment=None,
        source_refs=[
            {
                "list_name": "EF",
                "list_version": "3.1",
                "source_flow_uuid": f"src-{uuid}",
                "source_flow_name": f"Source name for {uuid}",
            }
        ],
    )


def _write_fixture(path: Path, *, flows, flow_objects, elementary, changes=(),
                   mismatches=()):
    """A database written by the pipeline's own writers.

    A hand-built fixture would let these tests pass over a shape the pipeline
    never produces, which is the failure mode a fixture is supposed to prevent.
    """
    import brightway_flows.pipeline.sqlite as sqlite_module

    original = sqlite_module.CONSENSUS_DB_FILEPATH
    sqlite_module.CONSENSUS_DB_FILEPATH = path
    try:
        numbered = number_change_events(
            list(changes),
            flow_object_id_by_uuid={
                row.elementary_flow_id: row.flow_object_id for row in elementary
            },
        )
        _write_consensus_sqlite(flows, numbered, flow_objects, elementary)
    finally:
        sqlite_module.CONSENSUS_DB_FILEPATH = original

    write_review_tables(
        path,
        run=PipelineRun(
            run_id="run-1", timestamp="2026-08-06T00:00:00+00:00",
            schema_version=REVIEW_SCHEMA_VERSION, flow_count=len(flows),
            change_count=len(numbered),
        ),
        stats=[],
        changes=numbered,
        queue_items=[],
        formula_mismatches=list(mismatches),
        element_coverage=[],
        context_mappings=[],
    )


class SectionTestCase(unittest.TestCase):
    """A small list: two substances, three flows, one of them deprecated."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "consensus-flows.sqlite3"
        _write_fixture(
            self.path,
            flows=[
                _flow("u-1", "Carbon dioxide", cas="124-38-9"),
                _flow("u-2", "Carbon dioxide", context=_WATER),
                _flow("u-3", "Methane", unit="kBq", deprecated=True),
            ],
            flow_objects=[
                _flow_object("fo-co2", "Carbon dioxide", cas=["124-38-9"],
                             alt_labels=["Carbonic anhydride"], smiles="O=C=O"),
                _flow_object("fo-ch4", "Methane", cas=["74-82-8"]),
            ],
            elementary=[
                _elementary("u-1", "fo-co2"),
                _elementary("u-2", "fo-co2"),
                _elementary("u-3", "fo-ch4", unit="kBq"),
            ],
            changes=[
                ChangeEvent(uuid="u-1", field_name="unit", old_value="g",
                            new_value="kg", transformer="unit_normalization"),
                ChangeEvent(uuid="u-1", field_name="cas_numbers", old_value=[],
                            new_value=["124-38-9"], transformer="consensus_match"),
            ],
            mismatches=[
                FormulaMismatch(
                    flow_object_id="fo-ch4",
                    chebi_id="http://purl.obolibrary.org/obo/CHEBI_16183",
                    similarity_score=0.4, threshold=0.55, pref_label="Methane",
                    flow_formula="CH4", chebi_label="water", chebi_formula="H2O",
                ),
            ],
        )

    def connection(self):
        connection = db.connect(self.path)
        self.addCleanup(connection.close)
        return connection

    def client(self):
        app = create_app(self.path)
        app.config["TESTING"] = True
        return app.test_client()


class FlowQueryTestCase(SectionTestCase):
    def test_deprecated_flows_are_hidden_by_default(self):
        """They have been replaced; a reader wants the row that is current."""
        page = flow_queries.flow_page(self.connection(), flow_queries.FlowFilters())
        self.assertEqual(sorted(row.uuid for row in page.rows), ["u-1", "u-2"])

    def test_deprecated_flows_can_be_asked_for(self):
        for value, expected in (("all", 3), ("only", 1), ("exclude", 2)):
            with self.subTest(value):
                page = flow_queries.flow_page(
                    self.connection(),
                    flow_queries.FlowFilters(deprecated=value),
                )
                self.assertEqual(page.total, expected)

    def test_a_context_filter_narrows_to_one_axis(self):
        page = flow_queries.flow_page(
            self.connection(),
            flow_queries.FlowFilters(context={"media": "Water"}),
        )
        self.assertEqual([row.uuid for row in page.rows], ["u-2"])

    def test_the_total_counts_matches_not_the_page(self):
        """"1,204 matching" has to be the filtered set, not what fits on screen."""
        page = flow_queries.flow_page(
            self.connection(), flow_queries.FlowFilters(deprecated="all")
        )
        self.assertEqual(page.total, 3)
        self.assertEqual(len(page.rows), 3)

    def test_a_page_beyond_the_end_is_the_last_page(self):
        page = flow_queries.flow_page(
            self.connection(), flow_queries.FlowFilters(), page=9999
        )
        self.assertEqual(page.number, 1)
        self.assertEqual(page.total, 2)

    def test_a_search_fts5_cannot_parse_does_not_raise(self):
        """`carbon AND` is a reasonable thing to type and a syntax error to FTS5.

        It falls back to LIKE, which searches for the literal string and so
        finds nothing here. What matters is that a malformed query is a slow
        empty result rather than a 500 -- the behaviour the consensus app had.
        """
        page = flow_queries.flow_page(
            self.connection(), flow_queries.FlowFilters(query="carbon AND")
        )
        self.assertEqual(page.rows, [])
        self.assertEqual(page.total, 0)

    def test_search_still_works_without_the_fts_tables(self):
        """The other thing the fallback catches: no FTS index at all.

        `no such table: elementary_flows_fts` is the same `OperationalError` as
        a syntax error, and here the fallback earns its keep -- a database
        written before the index existed is still searchable, by substring.
        """
        writable = sqlite3.connect(self.path)
        writable.execute("DROP TABLE elementary_flows_fts")
        writable.execute("DROP TABLE flow_objects_fts")
        writable.commit()
        writable.close()

        page = flow_queries.flow_page(
            self.connection(), flow_queries.FlowFilters(query="carbon")
        )
        self.assertEqual(sorted(row.uuid for row in page.rows), ["u-1", "u-2"])

    def test_search_finds_a_flow_by_name(self):
        page = flow_queries.flow_page(
            self.connection(), flow_queries.FlowFilters(query="methane", deprecated="all")
        )
        self.assertEqual([row.uuid for row in page.rows], ["u-3"])

    def test_sorting_is_reversible_and_a_bad_key_is_ignored(self):
        """A hand-edited URL must not produce a SQL error, nor an order the
        column header does not claim."""
        ascending = flow_queries.flow_page(
            self.connection(), flow_queries.FlowFilters(deprecated="all"), sort="unit"
        )
        descending = flow_queries.flow_page(
            self.connection(), flow_queries.FlowFilters(deprecated="all"), sort="-unit"
        )
        self.assertEqual(
            [row.unit for row in ascending.rows],
            list(reversed([row.unit for row in descending.rows])),
        )
        nonsense = flow_queries.flow_page(
            self.connection(), flow_queries.FlowFilters(deprecated="all"),
            sort="'; DROP TABLE elementary_flows; --",
        )
        self.assertEqual(nonsense.total, 3)

    def test_a_flow_carries_its_source_lists(self):
        """Load-bearing now that the input layer is gone: this is the only place
        a flow's origin appears."""
        detail = flow_queries.flow_detail(self.connection(), "u-1")
        self.assertEqual([ref.list_name for ref in detail.sources], ["EF"])
        self.assertEqual(detail.sources[0].source_flow_name, "Source name for u-1")

    def test_an_unknown_flow_is_none_not_an_exception(self):
        self.assertIsNone(flow_queries.flow_detail(self.connection(), "nope"))

    def test_filter_chips_describe_what_is_filtered(self):
        filters = flow_queries.FlowFilters(query="carbon", source="EF 3.1",
                                           context={"media": "Air"})
        labels = {label for _, label, _ in filters.active}
        self.assertEqual(labels, {"Search", "Source", "Media"})

    def test_the_default_deprecated_filter_is_not_a_chip(self):
        """It is the default; a chip for it would be noise on every page."""
        self.assertEqual(flow_queries.FlowFilters().active, [])


class SubstanceQueryTestCase(SectionTestCase):
    def test_a_substance_counts_its_flows_and_its_changes(self):
        page = substance_queries.substance_page(self.connection())
        by_id = {row.flow_object_id: row for row in page.rows}
        self.assertEqual(by_id["fo-co2"].linked_flows, 2)
        # Two changes, both on u-1, which resolves to fo-co2. The count comes
        # from `changelog`, keyed by substance -- no join.
        self.assertEqual(by_id["fo-co2"].change_count, 2)

    def test_a_deprecated_flow_is_not_counted_as_linked(self):
        page = substance_queries.substance_page(self.connection())
        by_id = {row.flow_object_id: row for row in page.rows}
        self.assertEqual(by_id["fo-ch4"].linked_flows, 0)

    def test_the_detail_page_lists_every_flow_including_deprecated(self):
        """The list page hides them; the substance page is where you go to find
        out what happened to one."""
        detail = substance_queries.substance_detail(self.connection(), "fo-ch4")
        self.assertEqual([flow.uuid for flow in detail.flows], ["u-3"])
        self.assertTrue(detail.flows[0].is_deprecated)

    def test_a_substance_with_smiles_offers_a_structure(self):
        detail = substance_queries.substance_detail(self.connection(), "fo-co2")
        self.assertTrue(detail.has_structure)
        self.assertEqual(detail.smiles_candidates, ["O=C=O"])

    def test_a_substance_without_smiles_does_not(self):
        detail = substance_queries.substance_detail(self.connection(), "fo-ch4")
        self.assertFalse(detail.has_structure)

    def test_an_unknown_substance_is_none(self):
        self.assertIsNone(substance_queries.substance_detail(self.connection(), "nope"))


class OriginQualifierTestCase(SectionTestCase):
    """The biogenic/fossil split is visible, and it is not the type axis.

    The fixture is the real shape of the problem: three flow objects that share
    a CAS number, were deliberately not merged, and carry the *same* ChemROF
    class. Whatever the type filter does, it cannot tell them apart.
    """

    NEUTRAL_MOLECULE = "https://w3id.org/chemrof/NeutralMolecule"

    def setUp(self):
        super().setUp()
        self.connection().close()
        _write_fixture(
            self.path,
            flows=[
                _flow("q-base", "Carbon dioxide", cas="124-38-9"),
                _flow("q-bio", "Carbon dioxide (biogenic)", cas="124-38-9"),
                # A second occurrence of the *same* substance, so that a count
                # of flows and a count of substances cannot be confused.
                _flow("q-bio-2", "Carbon dioxide (biogenic)", cas="124-38-9",
                      context=_WATER),
                _flow("q-fos", "Carbon dioxide (fossil)", cas="124-38-9"),
            ],
            flow_objects=[
                _flow_object("fo-co2", "Carbon dioxide", cas=["124-38-9"],
                             types=[self.NEUTRAL_MOLECULE]),
                _flow_object("fo-co2-bio", "Carbon dioxide (biogenic)",
                             cas=["124-38-9"], types=[self.NEUTRAL_MOLECULE],
                             origin_qualifier="biogenic",
                             parent_flow_object_id="fo-co2"),
                _flow_object("fo-co2-fos", "Carbon dioxide (fossil)",
                             cas=["124-38-9"], types=[self.NEUTRAL_MOLECULE],
                             origin_qualifier="fossil",
                             parent_flow_object_id="fo-co2"),
            ],
            elementary=[
                _elementary("q-base", "fo-co2"),
                _elementary("q-bio", "fo-co2-bio"),
                _elementary("q-bio-2", "fo-co2-bio"),
                _elementary("q-fos", "fo-co2-fos"),
            ],
        )

    def test_the_type_axis_cannot_separate_them(self):
        """The premise. If this ever stops being true the filter is redundant."""
        page = substance_queries.substance_page(self.connection())
        types = {row.flow_object_id: row.flow_type for row in page.rows}
        self.assertEqual(
            types,
            {
                "fo-co2": self.NEUTRAL_MOLECULE,
                "fo-co2-bio": self.NEUTRAL_MOLECULE,
                "fo-co2-fos": self.NEUTRAL_MOLECULE,
            },
        )

    def test_a_qualified_object_is_not_typed_by_its_qualifier(self):
        """`OriginQualifiedSubstance` was the facet's answer for these, and it
        answered the type question with the origin one."""
        page = substance_queries.substance_page(self.connection())
        self.assertNotIn(
            "OriginQualifiedSubstance", {row.flow_type for row in page.rows}
        )

    def test_an_untyped_qualified_object_is_unclassified(self):
        """Both facts, not one: the typing failed *and* it is biogenic."""
        from brightway_flows.pipeline.sqlite import _compute_flow_type

        self.assertEqual(
            _compute_flow_type({"origin_qualifier": "biogenic"}), "unclassified"
        )

    def test_the_flow_filter_narrows_to_one_qualifier(self):
        page = flow_queries.flow_page(
            self.connection(), flow_queries.FlowFilters(origin_qualifier="biogenic")
        )
        self.assertEqual(sorted(row.uuid for row in page.rows), ["q-bio", "q-bio-2"])

    def test_an_unqualified_flow_is_not_matched_by_any_qualifier(self):
        for qualifier in ("biogenic", "fossil"):
            with self.subTest(qualifier):
                page = flow_queries.flow_page(
                    self.connection(),
                    flow_queries.FlowFilters(origin_qualifier=qualifier),
                )
                self.assertNotIn("q-base", [row.uuid for row in page.rows])

    def test_the_qualifier_reaches_the_row_and_the_detail(self):
        page = flow_queries.flow_page(self.connection(), flow_queries.FlowFilters())
        by_uuid = {row.uuid: row for row in page.rows}
        self.assertEqual(by_uuid["q-bio"].origin_qualifier, "biogenic")
        self.assertEqual(by_uuid["q-base"].origin_qualifier, "")

        detail = flow_queries.flow_detail(self.connection(), "q-bio")
        self.assertEqual(detail.origin_qualifier, "biogenic")
        self.assertEqual(detail.type_label, "Neutral molecule")

    def test_the_flow_filter_options_offer_every_qualifier_in_use(self):
        options = flow_queries.filter_options(
            self.connection(), flow_queries.FlowFilters()
        )
        self.assertEqual(
            sorted(value for value, _ in options["qualifier"]),
            ["biogenic", "fossil"],
        )

    def test_the_flow_options_are_counted_in_flows(self):
        """Two flows of one biogenic substance: the option says 2, not 1.

        The cheap query -- `GROUP BY origin_qualifier` over `flow_objects` --
        says 1, and the page then returns two rows.
        """
        options = dict(
            flow_queries.filter_options(
                self.connection(), flow_queries.FlowFilters()
            )["qualifier"]
        )
        self.assertEqual(options["biogenic"], "biogenic (2)")
        self.assertEqual(options["fossil"], "fossil (1)")

    def test_a_type_option_reads_as_the_vocabulary_names_it(self):
        """Whichever path produced it: the precomputed table stores the IRI.

        The name, not the last segment.  `NeutralMolecule` was legible and
        `ENVO_01000892` is not, and every flow object typed by ENVO was offered
        in this dropdown as an accession.
        """
        options = dict(
            flow_queries.filter_options(
                self.connection(), flow_queries.FlowFilters()
            )["type"]
        )
        self.assertEqual(options[self.NEUTRAL_MOLECULE], "Neutral molecule (4)")

    def test_the_precomputed_counts_carry_both_facets(self):
        rows = self.connection().execute(
            "SELECT option_group, option_value, item_count FROM filter_option_counts "
            "WHERE option_group IN ('type', 'qualifier') "
            "ORDER BY option_group, option_value"
        ).fetchall()
        self.assertEqual(
            [(r["option_group"], r["option_value"], r["item_count"]) for r in rows],
            [
                ("qualifier", "biogenic", 2),
                ("qualifier", "fossil", 1),
                ("type", self.NEUTRAL_MOLECULE, 4),
            ],
        )

    def test_a_database_without_the_precomputed_facets_falls_back(self):
        """A database written before this change is still readable.

        Its options are counted in substances, because counting them in flows
        needs a join that costs 652ms on a database that also has no
        `idx_flow_objects_facets` — and the webapp cannot add one, its
        connection being `mode=ro`. The label says which it is.
        """
        writable = sqlite3.connect(self.path)
        writable.execute(
            "DELETE FROM filter_option_counts WHERE option_group IN ('type', 'qualifier')"
        )
        writable.commit()
        writable.close()

        options = flow_queries.filter_options(
            self.connection(), flow_queries.FlowFilters()
        )
        self.assertEqual(
            dict(options["qualifier"])["biogenic"], "biogenic (1 substance)"
        )
        self.assertEqual(
            dict(options["type"])[self.NEUTRAL_MOLECULE],
            "Neutral molecule (3 substances)",
        )

    def test_the_facets_do_not_narrow_with_the_other_filters(self):
        """As on `main`, where the type options were a global `GROUP BY`.

        Narrowing them means the join, and the join is what
        `idx_flow_objects_facets` exists to make survivable at all. It is also
        what a reader wants: an option list narrowed by its own selection offers
        only what is already selected.
        """
        options = flow_queries.filter_options(
            self.connection(),
            flow_queries.FlowFilters(source="EF 3.1", origin_qualifier="biogenic"),
        )
        self.assertEqual(
            sorted(value for value, _ in options["qualifier"]),
            ["biogenic", "fossil"],
        )
        # Still the flow counts, not the fallback's substance counts.
        self.assertEqual(dict(options["qualifier"])["biogenic"], "biogenic (2)")

    def test_the_covering_index_is_built(self):
        row = self.connection().execute(
            "SELECT sql FROM sqlite_master WHERE name = 'idx_flow_objects_facets'"
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertIn("flow_type", row["sql"])
        self.assertIn("origin_qualifier", row["sql"])

    def test_the_qualifier_is_a_removable_chip(self):
        filters = flow_queries.FlowFilters(origin_qualifier="biogenic")
        self.assertIn(("qualifier", "Origin", "biogenic"), filters.active)

    def test_the_substance_filter_narrows_to_one_qualifier(self):
        page = substance_queries.substance_page(
            self.connection(), origin_qualifier="fossil"
        )
        self.assertEqual([row.flow_object_id for row in page.rows], ["fo-co2-fos"])
        self.assertEqual(page.rows[0].origin_qualifier, "fossil")

    def test_the_substance_options_count_the_substances(self):
        options = substance_queries.substance_qualifier_options(self.connection())
        self.assertEqual(
            sorted(options), [("biogenic", "biogenic (1)"), ("fossil", "fossil (1)")]
        )

    def test_the_flow_page_shows_the_qualifier(self):
        client = self.client()
        self.assertIn(b"Origin qualifier", client.get("/flows/q-bio").data)
        self.assertNotIn(b"Origin qualifier", client.get("/flows/q-base").data)

    def test_the_lists_filter_on_the_qualifier_parameter(self):
        client = self.client()
        for route in ("/flows/?qualifier=biogenic", "/flow-objects/?qualifier=biogenic"):
            with self.subTest(route):
                body = client.get(route).data
                self.assertIn(b"(biogenic)", body)
                self.assertNotIn(b"(fossil)", body)


class CheckQueryTestCase(SectionTestCase):
    def test_a_label_on_two_substances_is_shared(self):
        connection = self.connection()
        connection.close()
        # `Methane` is added as an alternative label of carbon dioxide, which is
        # exactly the false synonym this check exists to find.
        _write_fixture(
            self.path,
            flows=[_flow("u-1", "Carbon dioxide")],
            flow_objects=[
                _flow_object("fo-co2", "Carbon dioxide", alt_labels=["Methane"]),
                _flow_object("fo-ch4", "Methane"),
            ],
            elementary=[_elementary("u-1", "fo-co2")],
        )
        page = check_queries.shared_labels(self.connection())
        self.assertEqual([row.label for row in page.rows], ["Methane"])
        self.assertEqual(page.rows[0].substances, 2)
        self.assertEqual(
            sorted(claim.kind for claim in page.rows[0].claims),
            ["alternative", "preferred"],
        )

    def test_formula_mismatches_group_under_their_substance(self):
        page = check_queries.formula_mismatches(self.connection())
        self.assertEqual([row.flow_object_id for row in page.rows], ["fo-ch4"])
        self.assertEqual(page.rows[0].matches[0]["formula"], "H2O")

    def test_a_kbq_flow_without_isotope_metadata_is_a_gap(self):
        page = check_queries.isotope_gaps(self.connection())
        self.assertEqual([row.uuid for row in page.rows], ["u-3"])

    def test_the_index_counts_every_check(self):
        checks = {check.key: check for check in check_queries.index(self.connection())}
        self.assertEqual(checks["formula-mismatches"].count, 1)
        self.assertEqual(checks["isotope-gaps"].count, 1)
        self.assertTrue(checks["formula-mismatches"].available)

    def test_a_check_whose_table_is_absent_says_so(self):
        """Not a zero: a database that cannot answer is not a clean bill of
        health."""
        # A database the pipeline wrote before `formula_mismatches` existed:
        # the flow tables are complete, that one table is absent.
        bare = Path(self._tmp.name) / "bare.sqlite3"
        _write_fixture(
            bare,
            flows=[_flow("u-1", "Carbon dioxide")],
            flow_objects=[_flow_object("fo-co2", "Carbon dioxide")],
            elementary=[_elementary("u-1", "fo-co2")],
        )
        writable = sqlite3.connect(bare)
        writable.execute("DROP TABLE formula_mismatches")
        writable.commit()
        writable.close()

        read = db.connect(bare)
        self.addCleanup(read.close)
        checks = {check.key: check for check in check_queries.index(read)}
        self.assertFalse(checks["formula-mismatches"].available)
        self.assertIsNone(checks["formula-mismatches"].count)


class MergeQueryConnectionTestCase(SectionTestCase):
    """The merge reads take the request's connection, like everything else."""

    def setUp(self):
        super().setUp()
        row = UnmatchedRow(
            source_uuid="s-1", source_name="Flow s-1", source_context=["air"],
            source_unit="kg", source_cas="", source_ec="",
            reason="no-flow-object-candidate",
        )
        write_merge_run(
            self.path,
            run_id="merge-1",
            started_at="2026-08-06T00:01:00+00:00",
            finished_at="2026-08-06T00:02:00+00:00",
            inputs=[MergeRunInput(run_id="merge-1", list_name="ecoinvent",
                                  list_version="3.12", sequence=0, row_count=1)],
            outcomes=[MergeOutcome.from_unmatched(
                "merge-1", SOURCE, row, has_candidates=False)],
            stats={},
        )

    def test_a_run_reports_its_counts(self):
        run = merge_queries.load_run(self.connection())
        self.assertTrue(run.exists)
        self.assertEqual(run.stats["unmatched"], 1)
        self.assertEqual(run.stats["source rows"], 1)

    def test_outcomes_come_back_on_the_shared_page_type(self):
        """One pager renders every list in the app; a page type of its own is
        how the merge section ended up unrenderable by it."""
        page = merge_queries.outcome_page(self.connection(), run_id="merge-1")
        self.assertEqual(page.total, 1)
        self.assertEqual(page.first_row, 1)
        self.assertEqual(page.last_row, 1)
        self.assertFalse(page.has_next)

    def test_a_database_with_no_merge_tables_is_no_run(self):
        bare = Path(self._tmp.name) / "no-merge.sqlite3"
        sqlite3.connect(bare).close()
        connection = db.connect(bare)
        self.addCleanup(connection.close)
        self.assertFalse(merge_queries.load_run(connection).exists)


class CandidateNameTestCase(SectionTestCase):
    """The candidates a tied row was choosing between, as a curator sees them.

    The run records identifiers, a score, a unit and a context; the name is not
    among them, and a page of eighteen uuids is what "tied elementary
    candidates" looked like before. The name comes from the published list, and
    two candidates alike in name, unit and context are the answer to a
    different question -- a duplicate in the consensus list -- than two that
    differ.
    """

    def setUp(self):
        super().setUp()
        row = UnmatchedRow(
            source_uuid="t-1", source_name="Carbon dioxide",
            source_context=["air"], source_unit="kg", source_cas="124-38-9",
            source_ec="", reason="tied-elementary-candidates",
            candidate_flow_object_ids=["fo-co2"],
            candidate_elementary_flow_ids=["u-1", "u-2", "gone"],
            candidate_elementary_flows=[
                {"elementary_flow_id": "u-1", "score": 4, "unit": "kg",
                 "context": ["Environmental", "Air", "Unknown"]},
                {"elementary_flow_id": "u-2", "score": 4, "unit": "kg",
                 "context": ["Environmental", "Water", "Unknown"]},
                {"elementary_flow_id": "gone", "score": 1, "unit": "kg",
                 "context": ["Environmental", "Air", "Unknown"]},
            ],
            algorithm_details={"elementary_candidate_count": 3,
                               "eligible_candidate_count": 3,
                               "filtered_out_context_mismatch_count": 0},
        )
        write_merge_run(
            self.path,
            run_id="merge-2",
            started_at="2026-08-07T00:01:00+00:00",
            finished_at="2026-08-07T00:02:00+00:00",
            inputs=[MergeRunInput(run_id="merge-2", list_name="ecoinvent",
                                  list_version="3.12", sequence=0, row_count=1)],
            outcomes=[MergeOutcome.from_unmatched(
                "merge-2", SOURCE, row, has_candidates=True)],
            stats={},
        )

    def summary(self):
        connection = self.connection()
        outcomes = merge_queries.outcome_detail(connection, "merge-2", "t-1")
        return merge_queries.candidate_summaries(connection, outcomes)[0]

    def test_a_candidate_carries_its_name_unit_and_context(self):
        flow = self.summary().flows[0]
        self.assertEqual(flow.name, "Carbon dioxide")
        self.assertEqual(flow.unit, "kg")
        self.assertEqual(flow.context, ["Environmental", "Air", "Unknown"])
        self.assertTrue(flow.resolved)

    def test_the_candidate_substance_is_named_too(self):
        [candidate] = self.summary().objects
        self.assertEqual(candidate.flow_object_id, "fo-co2")
        self.assertEqual(candidate.name, "Carbon dioxide")

    def test_a_candidate_the_list_no_longer_holds_says_so(self):
        """Rather than an empty name beside a uuid, which reads as a bug."""
        missing = self.summary().flows[-1]
        self.assertEqual(missing.elementary_flow_id, "gone")
        self.assertFalse(missing.resolved)
        self.assertEqual(missing.name, "")

    def test_the_page_shows_what_the_selector_could_not_choose_between(self):
        page = self.client().get("/merge/outcomes/t-1")
        body = page.get_data(as_text=True)
        self.assertEqual(page.status_code, 200)
        self.assertIn("Carbon dioxide", body)
        self.assertIn("Environmental → Water → Unknown", body)
        self.assertIn("tied", body)


class RouteTestCase(SectionTestCase):
    ROUTES = (
        "/flows/", "/flow-objects/", "/checks/", "/merge/",
        "/checks/shared-labels", "/checks/formula-mismatches",
        "/checks/duplicate-contexts", "/checks/duplication-report",
        "/checks/isotope-gaps", "/checks/unit-disagreements",
        "/merge/outcomes", "/merge/conflicts",
    )

    def test_every_route_renders_with_data(self):
        client = self.client()
        for route in self.ROUTES:
            with self.subTest(route):
                self.assertEqual(client.get(route).status_code, 200)

    def test_every_route_renders_without_a_database(self):
        """The expected first state of a checkout."""
        app = create_app(Path(self._tmp.name) / "absent.sqlite3")
        app.config["TESTING"] = True
        client = app.test_client()
        for route in self.ROUTES:
            with self.subTest(route):
                response = client.get(route)
                self.assertEqual(response.status_code, 200)
                self.assertIn("No database yet", response.get_data(as_text=True))

    def test_the_detail_pages_render(self):
        client = self.client()
        self.assertEqual(client.get("/flows/u-1").status_code, 200)
        self.assertEqual(client.get("/flow-objects/fo-co2").status_code, 200)
        self.assertEqual(client.get("/merge/outcomes/s-1").status_code, 200)

    def test_an_unknown_identifier_is_a_404(self):
        client = self.client()
        self.assertEqual(client.get("/flows/nope").status_code, 404)
        self.assertEqual(client.get("/flow-objects/nope").status_code, 404)

    def test_the_flow_detail_page_reads_no_history(self):
        """The point of moving history behind `/flows/<uuid>/changes` is that a
        detail page does not pay for it. That is only true if nothing queries
        for it, so this asserts the query is never issued.
        """
        connection = db.connect(self.path)
        self.addCleanup(connection.close)
        seen: list[str] = []
        # `sqlite3.Connection.execute` is read-only, so the statements are
        # collected from the driver rather than by wrapping the method.
        connection.set_trace_callback(seen.append)
        flow_queries.flow_detail(connection, "u-1")
        connection.set_trace_callback(None)
        self.assertFalse(
            [sql for sql in seen if "changelog" in sql or "provenance_activities" in sql],
            "the detail page must not read history",
        )

    def test_a_substance_with_a_structure_serves_an_svg(self):
        response = self.client().get("/flow-objects/fo-co2/structure.svg")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "image/svg+xml")
        self.assertIn(b"<svg", response.data)

    def test_a_substance_without_one_is_a_404(self):
        self.assertEqual(
            self.client().get("/flow-objects/fo-ch4/structure.svg").status_code, 404
        )

    def test_the_navigation_now_offers_every_ported_section(self):
        """The labels are the data model's two words, in its order.

        A flow object is the substance and an elementary flow is that substance
        in one context; "Substances" and "Flows" hid the distinction the merge
        pages turn on, and listed the derived thing first.
        """
        body = self.client().get("/").get_data(as_text=True)
        for label in ("Flow objects", "Elementary flows", "Checks", "Merge"):
            with self.subTest(label):
                self.assertIn(f">{label}</a>", body)


if __name__ == "__main__":
    unittest.main()
