"""The three ways into the flow objects: all of them, the agricultural
chemicals, and the periodic table.

What is pinned here is what would break silently:

- **The static routes win over the flow-object detail route.**  Both live under
  `/flow-objects/`, and one of them takes a `path` converter that would happily
  match `elements`.  Werkzeug orders them correctly; nothing said so, and a
  reordering would turn the periodic table into a 404 that looks like a missing
  flow object.
- **The periodic table is the periodic table.**  Every atomic number from 1 to
  118 appears in exactly one cell.  The layout is written out by hand, so a
  typo would drop an element or draw one twice, and neither is visible in a
  screenshot of a 118-cell grid.
- **An element's children are read from the child.**  The element carries a
  list of its isotopes and no list of its ions, so a page that read the
  parent's list would show every nuclide and silently no ion at all.
- **A role filter is "any of", not "all of".**  A substance bears as many roles
  as apply, and an all-of reading answers a question nobody asked.
- **The origin facet counts substances, not flows.**  It is a question about
  which list minted the substance, and counting flows would report EF 3.1 at
  its flow count and tell a reader nothing.

Three states per route -- data, an empty database, no database -- as everywhere
else in this application, because that is the class of failure the pages this
replaces actually had.
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from brightway_flows.domain.common import Provenance
from brightway_flows.domain.context_registry import context_from_dict
from brightway_flows.domain.elementary_flow import ElementaryFlow
from brightway_flows.domain.flow import Flow
from brightway_flows.domain.flow_object import FlowObject, Role
from brightway_flows.flow_layers.roles import CURATED_BY, GENERATED_BY
from brightway_flows.pipeline.review_records import (
    ElementCoverage,
    ElementStatus,
    PipelineRun,
)
from brightway_flows.pipeline.review_tables import (
    REVIEW_SCHEMA_VERSION,
    write_review_tables,
)
from brightway_flows.pipeline.sqlite import _write_consensus_sqlite
from brightway_flows.webapps.app import create_app
from brightway_flows.webapps.app.queries import elements as element_queries
from brightway_flows.webapps.app.queries import roles as role_queries
from brightway_flows.webapps.app.queries import substances as substance_queries

_AIR = context_from_dict(
    {"dimension": "Environmental", "media": "Air", "strata": "Unknown"}
)

HERBICIDE = "http://purl.obolibrary.org/obo/CHEBI_24527"
PESTICIDE = "http://purl.obolibrary.org/obo/CHEBI_25944"
INSECTICIDE = "http://purl.obolibrary.org/obo/CHEBI_24852"
FUNGICIDE = "http://purl.obolibrary.org/obo/CHEBI_24127"
CONTAMINANT = "http://purl.obolibrary.org/obo/CHEBI_78298"

#: The two element flow objects the fixture hangs children off.
IRON = "fo-iron"
ANTIMONY = "fo-antimony"


def _role(iri: str, label: str, *, curated: bool = False) -> dict:
    return Role(
        iri=iri,
        label=label,
        definition=f"A substance used as a {label}.",
        provenance=Provenance(
            was_generated_by=CURATED_BY if curated else GENERATED_BY,
            was_attributed_to="brightway-flows",
        ),
    ).to_dict()


def _flow(uuid, name, *, unit="kg", source="EF 3.1") -> Flow:
    return Flow(
        uuid=uuid,
        source=source,
        unit=unit,
        prefLabel=[{"@value": name, "@language": "en"}],
        context=_AIR,
    )


def _flow_object(
    flow_object_id,
    name,
    *,
    roles=(),
    seed_source="EF 3.1",
    resolver="hybrid_name_cas_v1",
    properties=None,
    types=(),
) -> FlowObject:
    created_from = {"resolver": resolver}
    # `None` rather than the key with an empty value: an object the pipeline
    # minted for itself has no source list, and the page has to be able to tell
    # that from a list called "".
    if seed_source is not None:
        created_from["seed_source"] = seed_source
    return FlowObject(
        flow_object_id=flow_object_id,
        prefLabel=[{"@value": name, "@language": "en"}],
        altLabel=[],
        classifications={},
        properties=properties or {},
        references=[],
        created_from=created_from,
        types=list(types) or None,
        roles=list(roles) or None,
    )


def _elementary(uuid, flow_object_id, *, unit="kg") -> ElementaryFlow:
    return ElementaryFlow(
        elementary_flow_id=uuid,
        flow_object_id=flow_object_id,
        source="EF 3.1",
        context=None,
        context_iri="",
        unit=unit,
        unit_iri="",
        lcia_methods=[],
        general_comment=None,
        source_refs=[],
    )


def _child(flow_object_id, name, parent, relationship, *, isotope=None, types=()):
    """A nuclide or an ion, stating its parent element the way the pipeline does."""
    properties = {
        "relationships": {
            "parent_element_flow_object_id": parent,
            "relationship_type": relationship,
        }
    }
    if isotope:
        properties["isotope"] = isotope
    return _flow_object(flow_object_id, name, properties=properties, types=types)


def _elements() -> list[ElementCoverage]:
    """Four rows, one in each of the three states, plus a second linked one."""
    return [
        ElementCoverage(
            atomic_number=26,
            symbol="Fe",
            name="Iron",
            status=ElementStatus.LINKED,
            flow_object_id=IRON,
            pubchem_page_url="https://pubchem.ncbi.nlm.nih.gov/element/26",
        ),
        ElementCoverage(
            atomic_number=51,
            symbol="Sb",
            name="Antimony",
            status=ElementStatus.NOT_LINKED,
            flow_object_id=ANTIMONY,
        ),
        ElementCoverage(
            atomic_number=118,
            symbol="Og",
            name="Oganesson",
            status=ElementStatus.MISSING,
        ),
        ElementCoverage(
            atomic_number=1,
            symbol="H",
            name="Hydrogen",
            status=ElementStatus.LINKED,
            flow_object_id="fo-hydrogen",
        ),
    ]


def _write_fixture(path: Path, *, flows, flow_objects, elementary, elements=()):
    import brightway_flows.pipeline.sqlite as sqlite_module

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
            timestamp="2026-08-19T00:00:00+00:00",
            schema_version=REVIEW_SCHEMA_VERSION,
            flow_count=len(flows),
            change_count=0,
        ),
        stats=[],
        changes=[],
        queue_items=[],
        formula_mismatches=[],
        element_coverage=list(elements),
        context_mappings=[],
    )


class FlowObjectViewTestCase(unittest.TestCase):
    """One list holding a herbicide, an element, its nuclide and its two ions."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "consensus-flows.sqlite3"
        _write_fixture(
            self.path,
            flows=[
                _flow("u-1", "Atrazine"),
                _flow("u-2", "Iron"),
                _flow("u-3", "Iron-59"),
            ],
            flow_objects=[
                # Two roles, one of them entailed: the pipeline materialises
                # `pesticide` beside `herbicide` rather than leaving it to be
                # derived, and the tree counts both.
                _flow_object(
                    "fo-atrazine",
                    "Atrazine",
                    roles=[_role(HERBICIDE, "herbicide"), _role(PESTICIDE, "pesticide")],
                    seed_source="EF 3.1",
                ),
                _flow_object(
                    "fo-spinetoram",
                    "Spinetoram",
                    roles=[
                        _role(INSECTICIDE, "insecticide", curated=True),
                        _role(PESTICIDE, "pesticide", curated=True),
                    ],
                    seed_source="ecoinvent-3.12",
                ),
                # An environmental-fate role and nothing agricultural: it must
                # not appear on the agricultural-chemicals page.
                _flow_object(
                    "fo-dioxin",
                    "2,3,7,8-TCDD",
                    roles=[_role(CONTAMINANT, "environmental contaminant")],
                    seed_source="bafu-2026-v1",
                ),
                _flow_object(IRON, "Iron", seed_source="EF 3.1"),
                _flow_object(ANTIMONY, "Antimony", seed_source="EF 3.1"),
                # Minted by the pipeline: no source list at all.
                _flow_object(
                    "fo-minted",
                    "Rhenium",
                    seed_source=None,
                    resolver="element_enrichment_minted_element_v1",
                ),
                _child(
                    "fo-iron-59",
                    "Iron-59",
                    IRON,
                    element_queries.ISOTOPE_OF,
                    isotope={
                        "nuclide": "59Fe",
                        "mass_number": 59,
                        "half_life_and_uncertainty": "44.500 d ± 0.012",
                        "decay_modes": "β-=100%",
                        "specific_activity_bq_per_g": "1.8e15",
                    },
                    types=["https://w3id.org/chemrof/Isotope"],
                ),
                _child(
                    "fo-iron-2",
                    "Iron(2+)",
                    IRON,
                    element_queries.ION_OF,
                    types=["https://w3id.org/chemrof/AtomCation"],
                ),
                _child(
                    "fo-iron-3",
                    "Iron(3+)",
                    IRON,
                    element_queries.ION_OF,
                    types=["https://w3id.org/chemrof/AtomCation"],
                ),
            ],
            elementary=[
                _elementary("u-1", "fo-atrazine"),
                _elementary("u-2", IRON),
                _elementary("u-3", "fo-iron-59"),
            ],
            elements=_elements(),
        )
        self.app = create_app(database_path=self.path)
        self.client = self.app.test_client()
        self.connection = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        self.connection.row_factory = sqlite3.Row
        self.addCleanup(self.connection.close)

    # ── routing ──────────────────────────────────────────────────────────

    def test_the_static_views_are_reached_before_the_flow_object_detail(self):
        """Both live under `/flow-objects/`, and one takes a path converter."""
        for path, marker in (
            ("/flow-objects/elements/", "Periodic table of the elements"),
            ("/flow-objects/agricultural-chemicals/", "Agricultural chemicals"),
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn(marker, response.get_data(as_text=True))

    def test_an_element_is_addressed_by_symbol_in_any_case(self):
        self.assertEqual(self.client.get("/flow-objects/elements/Fe").status_code, 200)
        moved = self.client.get("/flow-objects/elements/fe")
        self.assertEqual(moved.status_code, 301)
        self.assertTrue(moved.headers["Location"].endswith("/flow-objects/elements/Fe"))

    def test_an_unknown_symbol_is_a_404(self):
        self.assertEqual(self.client.get("/flow-objects/elements/Zz").status_code, 404)

    # ── the periodic table ───────────────────────────────────────────────

    def test_every_element_is_drawn_exactly_once(self):
        """The layout is written out by hand, so a typo drops or doubles one."""
        drawn = [
            slot
            for row in (*element_queries.PERIODIC_ROWS, *element_queries.F_BLOCK_ROWS)
            for slot in row
            if isinstance(slot, int)
        ]
        self.assertEqual(sorted(drawn), list(range(1, 119)))

    def test_every_layout_row_is_eighteen_wide(self):
        """Two grids, one column width. A short row shifts everything after it."""
        for row in (*element_queries.PERIODIC_ROWS, *element_queries.F_BLOCK_ROWS):
            with self.subTest(row=row[:3]):
                self.assertEqual(len(row), 18)

    def test_the_three_coverage_states_are_counted_apart(self):
        table = element_queries.periodic_table(self.connection)
        self.assertEqual((table.linked, table.unreferenced, table.missing), (2, 1, 1))

    def test_an_element_with_no_row_is_a_gap_rather_than_an_empty_cell(self):
        """A database with no row for an element has no opinion about it.

        Which is a different statement from "this element is uncovered", and
        the cell must not make the stronger one.
        """
        table = element_queries.periodic_table(self.connection)
        cells = table.row(element_queries.PERIODIC_ROWS[3])
        self.assertIsNone(cells[0])  # 19, potassium: no row in this fixture
        self.assertIsNotNone(cells[7])  # 26, iron

    def test_the_marker_rows_stand_in_for_the_f_block(self):
        table = element_queries.periodic_table(self.connection)
        period_six = table.row(element_queries.PERIODIC_ROWS[5])
        self.assertEqual(period_six[2], element_queries.LANTHANIDES)
        self.assertIn(
            element_queries.LANTHANIDES, element_queries.MARKER_LABELS
        )

    # ── nuclides and ions ────────────────────────────────────────────────

    def test_an_element_carries_its_nuclides_and_its_ions(self):
        """Both families, read from the child.

        The element's own `isotopes` block lists only isotopes, so a page that
        read the parent's list would show the nuclide and neither ion.
        """
        iron = element_queries.element_detail(self.connection, 26)
        self.assertEqual([item.name for item in iron.nuclides], ["Iron-59"])
        self.assertEqual(
            [item.name for item in iron.ions], ["Iron(2+)", "Iron(3+)"]
        )

    def test_a_nuclide_keeps_its_half_life_and_decay_modes(self):
        iron = element_queries.element_detail(self.connection, 26)
        nuclide = iron.nuclides[0]
        self.assertEqual(nuclide.nuclide, "59Fe")
        self.assertEqual(nuclide.mass_number, 59)
        self.assertEqual(nuclide.half_life, "44.500 d ± 0.012")
        self.assertEqual(nuclide.decay_modes, "β-=100%")

    def test_an_element_with_no_flow_object_still_has_a_page(self):
        """Oganesson is the case: covered by a row, carried by nothing."""
        response = self.client.get("/flow-objects/elements/Og")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("not in the list", body)

    def test_the_element_page_shows_the_tree(self):
        body = self.client.get("/flow-objects/elements/Fe").get_data(as_text=True)
        for marker in ("Nuclides", "Ions", "Iron-59", "Iron(3+)", "59Fe"):
            with self.subTest(marker=marker):
                self.assertIn(marker, body)

    # ── the role axis ────────────────────────────────────────────────────

    def test_the_role_tree_is_the_allow_lists_own_hierarchy(self):
        tree = role_queries.role_tree(
            self.connection, role_queries.AGROCHEMICAL_FAMILY
        )
        roots = {node.label for node in tree}
        self.assertIn("pesticide", roots)
        pesticide = next(node for node in tree if node.label == "pesticide")
        self.assertIn("herbicide", {child.label for child in pesticide.children})

    def test_a_role_counts_the_substances_the_build_asserts_it_of(self):
        counts = role_queries.role_object_counts(self.connection)
        self.assertEqual(counts.get(HERBICIDE), 1)
        self.assertEqual(counts.get(INSECTICIDE), 1)
        # Entailed onto both, and counted on both: a published table that omits
        # what it entails answers wrongly.
        self.assertEqual(counts.get(PESTICIDE), 2)
        self.assertNotIn(FUNGICIDE, counts)

    def test_the_two_halves_of_the_axis_are_counted_apart(self):
        evidence = role_queries.evidence_counts(
            self.connection, role_queries.AGROCHEMICAL_FAMILY
        )
        self.assertEqual(evidence, {"ChEBI": 2, "Curated": 2})

    def test_the_environmental_fate_roles_are_not_agricultural_chemicals(self):
        """The dioxin bears a role, and not one this page is about."""
        self.assertEqual(
            role_queries.substances_with_any_role(
                self.connection, role_queries.AGROCHEMICAL_FAMILY
            ),
            2,
        )
        body = self.client.get(
            "/flow-objects/agricultural-chemicals/"
        ).get_data(as_text=True)
        self.assertIn("Atrazine", body)
        self.assertNotIn("2,3,7,8-TCDD", body)

    def test_a_role_filter_is_any_of_and_not_all_of(self):
        page = substance_queries.substance_page(
            self.connection, roles=(HERBICIDE, INSECTICIDE)
        )
        self.assertEqual(
            {row.name for row in page.rows}, {"Atrazine", "Spinetoram"}
        )

    def test_selecting_one_role_narrows_to_it(self):
        body = self.client.get(
            f"/flow-objects/agricultural-chemicals/?role={HERBICIDE}"
        ).get_data(as_text=True)
        self.assertIn("Atrazine", body)
        self.assertNotIn("Spinetoram", body)

    def test_an_unknown_role_shows_the_whole_family_rather_than_nothing(self):
        """A hand-edited URL is not a filter nobody can clear."""
        body = self.client.get(
            "/flow-objects/agricultural-chemicals/?role=nonsense"
        ).get_data(as_text=True)
        self.assertIn("Atrazine", body)
        self.assertIn("Spinetoram", body)

    def test_a_substances_roles_reach_its_own_page(self):
        body = self.client.get("/flow-objects/fo-spinetoram").get_data(as_text=True)
        self.assertIn("insecticide", body)
        self.assertIn("Curated", body)

    # ── origin ───────────────────────────────────────────────────────────

    def test_the_origin_facet_counts_substances(self):
        options = dict(substance_queries.substance_origin_options(self.connection))
        # The herbicide, the two elements, the nuclide and the two ions.
        self.assertEqual(options["EF 3.1"], "EF 3.1 (6)")
        self.assertEqual(options["ecoinvent-3.12"], "ecoinvent-3.12 (1)")

    def test_an_object_no_list_minted_is_left_out_of_the_facet(self):
        """Calling it a source list would be a claim that a list published it."""
        options = dict(substance_queries.substance_origin_options(self.connection))
        self.assertNotIn("", options)
        self.assertEqual(len(options), 3)

    def test_filtering_by_origin_selects_that_lists_substances(self):
        page = substance_queries.substance_page(
            self.connection, origin_source="ecoinvent-3.12"
        )
        self.assertEqual([row.name for row in page.rows], ["Spinetoram"])

    def test_the_origin_column_is_on_the_page(self):
        body = self.client.get("/flow-objects/?origin=bafu-2026-v1").get_data(
            as_text=True
        )
        self.assertIn("2,3,7,8-TCDD", body)
        self.assertNotIn("Atrazine", body)

    def test_the_qualifier_filter_is_no_longer_called_origin(self):
        """Two different questions cannot share one label on one form."""
        body = self.client.get("/flow-objects/").get_data(as_text=True)
        self.assertIn('for="filter-origin">Origin<', body)
        self.assertIn('for="filter-qualifier">Qualifier<', body)


class EmptyDatabaseTestCase(unittest.TestCase):
    """A database the pipeline has written nothing into."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "consensus-flows.sqlite3"
        sqlite3.connect(self.path).close()
        self.client = create_app(database_path=self.path).test_client()

    def test_the_new_views_render(self):
        """`/flow-objects/` itself is not here, and that is a finding.

        It 500s on a table-less database, and has since before this branch --
        so does `/flows/`, for the same reason: neither checks that
        `flow_objects` exists before querying it.  Pinning the defect as
        expected behaviour would make it permanent, and fixing it is a
        different change from this one.  The two views added here do check.
        """
        for path in (
            "/flow-objects/agricultural-chemicals/",
            "/flow-objects/elements/",
        ):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)

    def test_the_agricultural_chemicals_page_says_it_cannot_answer(self):
        """Rather than an empty table, which reads as "no substance has a role"."""
        body = self.client.get(
            "/flow-objects/agricultural-chemicals/"
        ).get_data(as_text=True)
        self.assertIn("no <code>flow_objects</code> table", body)

    def test_the_periodic_table_says_the_build_has_no_coverage_table(self):
        """Rather than 118 cells all claiming the element is missing."""
        body = self.client.get("/flow-objects/elements/").get_data(as_text=True)
        self.assertIn("no element coverage table", body)


class NoDatabaseTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.client = create_app(
            database_path=Path(self._tmp.name) / "absent.sqlite3"
        ).test_client()

    def test_every_view_is_a_page_and_not_a_crash(self):
        for path in (
            "/flow-objects/",
            "/flow-objects/agricultural-chemicals/",
            "/flow-objects/elements/",
            "/flow-objects/elements/Fe",
            "/flow-objects/particles/",
        ):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
