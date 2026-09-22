"""What the flow-object page says, and at what address.

Four things a reader of a substance page could not do.

- **The address said "substance".**  The navigation has said "Flow objects"
  since the sections were named, the data model has never called them anything
  else, and `/substances` was the last place the consensus app's word survived.
  It moves to `/flow-objects`, and the old paths redirect rather than 404 --
  the app is linked to from issues, from `docs/` and from bookmarks, none of
  which a rename gets to rewrite.
- **The properties table was keyed by IRI tail.**  `CHEMINF_000446` is what a
  reader saw where the row says "CAS registry number"; a term whose local name
  is an opaque accession has no readable form except through the registry that
  declares it.  Both are shown now, because the words are for reading and the
  term is what a curator quotes in an issue.
- **The known URLs were stored and never shown.**  `references` holds every
  external record the merge resolved this substance against -- ChEBI's
  cross-references, PubChem's identifier list, the CAS registry -- and the page
  rendered none of it.
- **A property whose value is a structure rendered blank.**  `property_value`
  reads `@value`, and the element enrichment writes `isotope`,
  `isotope_lookup` and `relationships` as whole nested payloads.  An empty cell
  says "this property is blank", which is a different claim.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from brightway_flows.domain.context_registry import context_from_dict
from brightway_flows.domain.elementary_flow import ElementaryFlow
from brightway_flows.domain.flow import Flow
from brightway_flows.domain.flow_object import FlowObject
from brightway_flows.domain.vocabulary import (
    CHEMINF_CAS_REGISTRY_NUMBER,
    CHEMROF_INCHI2D_KEY_STRING,
    CHEMROF_ISOMERIC_SMILES_STRING,
    CHEMROF_MOLECULAR_FORMULA,
    PROV_WAS_GENERATED_BY_CURIE,
)
from brightway_flows.integrations.chebi import XREF_URL_PREFIXES
from brightway_flows.webapps.app import create_app, filters, labels
from brightway_flows.webapps.app.queries import substances as queries

_UUID = "u-co2"
_ID = "fo-co2"
_AIR = context_from_dict(
    {"dimension": "Environmental", "media": "Air", "strata": "Unknown"}
)

_CHEBI_URL = "https://www.ebi.ac.uk/chebi/searchId.do?chebiId=CHEBI:16526"
_PUBCHEM_URL = "https://pubchem.ncbi.nlm.nih.gov/compound/280"
_WIKIPEDIA_URL = "https://en.wikipedia.org/wiki/Carbon_dioxide"
#: A ChEBI xref whose prefix `_expand_xref` has no expansion for.  Stored as it
#: was published, so the page has to show it without linking it.
_UNEXPANDED = "Beilstein:1900390"


def _reference(url: str, generated_by: str) -> dict[str, object]:
    """A reference in the shape `enrich_references` writes."""
    return {
        "@id": url,
        "provenance": {
            PROV_WAS_GENERATED_BY_CURIE: generated_by,
            "prov:wasAttributedTo": "brightway-flows",
        },
    }


def _fixture(path: Path) -> None:
    """One substance, with two shapes of reference and three properties."""
    import brightway_flows.pipeline.sqlite as sqlite_module

    flow = Flow(
        uuid=_UUID,
        source="EF 3.1",
        unit="kg",
        prefLabel=[{"@value": "Carbon dioxide", "@language": "en"}],
        context=_AIR,
        cas_numbers=["124-38-9"],
    )
    flow_object = FlowObject(
        flow_object_id=_ID,
        prefLabel=[{"@value": "Carbon dioxide", "@language": "en"}],
        altLabel=[],
        classifications={CHEMINF_CAS_REGISTRY_NUMBER: {"@value": ["124-38-9"]}},
        properties={
            CHEMROF_MOLECULAR_FORMULA: {"@value": "CO2"},
            CHEMROF_INCHI2D_KEY_STRING: {"@value": "CURLTUGMZLYLDI-UHFFFAOYSA-N"},
            CHEMROF_ISOMERIC_SMILES_STRING: {"@value": ["O=C=O"]},
            # No `@value`: a working record rather than a published term.
            "relationships": {"relationship_type": "isotope_of"},
        },
        references=[
            _reference(_CHEBI_URL, "enrich_references.chebi_id_link"),
            _reference(_PUBCHEM_URL, "enrich_references.pubchem_compound"),
            # The same URL twice: a substance with two ChEBI identifiers
            # collects a cross-reference once per identifier.
            _reference(_WIKIPEDIA_URL, "enrich_references.chebi_xrefs"),
            _reference(_WIKIPEDIA_URL, "enrich_references.chebi_xrefs"),
            # A bare string, which is what the isotope enrichment writes.
            _UNEXPANDED,
        ],
        created_from={},
    )
    elementary = ElementaryFlow(
        elementary_flow_id=_UUID,
        flow_object_id=_ID,
        source="EF 3.1",
        context=_AIR,
        context_iri="",
        unit="kg",
        unit_iri="",
        lcia_methods=[],
        general_comment=None,
        source_refs=[],
    )
    original = sqlite_module.CONSENSUS_DB_FILEPATH
    sqlite_module.CONSENSUS_DB_FILEPATH = path
    try:
        sqlite_module._write_consensus_sqlite(
            [flow], [], [flow_object], [elementary]
        )
    finally:
        sqlite_module.CONSENSUS_DB_FILEPATH = original


class RegionalisedSourceRowCountTestCase(unittest.TestCase):
    """The aggregate #192 asked for: how many source rows carried a place.

    Counted from `elementary_flow_sources.source_flow_name` through the
    geography splitter, because since #192 a split row's mapping records the
    vendor's coded spelling. The fixture ships one coded ref, one uncoded and
    one code-shaped non-place, and the count reads one.
    """

    def test_the_count_reads_the_coded_shipped_names(self):
        import brightway_flows.pipeline.sqlite as sqlite_module

        flow_object = FlowObject(
            flow_object_id="fo-water",
            prefLabel=[{"@value": "Water", "@language": "en"}],
            altLabel=[],
            properties={},
            references=[],
            created_from={},
        )
        elementary = ElementaryFlow(
            elementary_flow_id="u-water",
            flow_object_id="fo-water",
            source="EF 3.1",
            context=_AIR,
            context_iri="",
            unit="m3",
            unit_iri="",
            lcia_methods=[],
            general_comment=None,
            source_refs=[
                {"list_name": "bafu", "list_version": "2026-v1",
                 "source_flow_uuid": "s-1", "source_flow_name": "Water, AE"},
                {"list_name": "ecoinvent", "list_version": "3.12",
                 "source_flow_uuid": "s-2", "source_flow_name": "Water"},
                {"list_name": "agribalyse", "list_version": "3.2",
                 "source_flow_uuid": "s-3", "source_flow_name": "Particulates, SPM"},
            ],
        )
        flow = Flow(uuid="u-water", source="EF 3.1", unit="m3", context=_AIR)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "consensus.sqlite3"
            original = sqlite_module.CONSENSUS_DB_FILEPATH
            sqlite_module.CONSENSUS_DB_FILEPATH = path
            try:
                sqlite_module._write_consensus_sqlite(
                    [flow], [], [flow_object], [elementary]
                )
            finally:
                sqlite_module.CONSENSUS_DB_FILEPATH = original
            import sqlite3 as _sqlite3

            connection = _sqlite3.connect(path)
            connection.row_factory = _sqlite3.Row
            detail = queries.substance_detail(connection, "fo-water")
        assert detail is not None
        self.assertEqual(detail.regionalised_source_rows, 1)


class PredicateLabelTestCase(unittest.TestCase):
    """A stored key, said out loud."""

    def test_a_declared_term_reads_as_its_name(self):
        self.assertEqual(
            labels.predicate_label(CHEMROF_MOLECULAR_FORMULA), "Molecular formula"
        )

    def test_an_opaque_accession_reads_as_what_it_means(self):
        """The whole reason this goes through the registry.

        `CHEMINF_000446` is the local name, and no amount of splitting it into
        words makes it say "CAS registry number".
        """
        self.assertEqual(
            labels.predicate_label(CHEMINF_CAS_REGISTRY_NUMBER),
            "CAS registry number",
        )

    def test_an_acronym_is_spelled_not_capitalised(self):
        for key, expected in (
            (CHEMROF_ISOMERIC_SMILES_STRING, "Isomeric SMILES string"),
            (CHEMROF_INCHI2D_KEY_STRING, "InChI2D key string"),
        ):
            with self.subTest(key):
                self.assertEqual(labels.predicate_label(key), expected)

    def test_an_undeclared_key_is_split_rather_than_dropped(self):
        """`isotope_lookup` is a working record, not a published term."""
        self.assertEqual(labels.predicate_label("isotope_lookup"), "Isotope lookup")
        self.assertEqual(labels.predicate_term("isotope_lookup"), "isotope_lookup")

    def test_the_term_is_the_curie_the_document_is_keyed_by(self):
        self.assertEqual(
            labels.predicate_term(CHEMROF_MOLECULAR_FORMULA),
            "chemrof:molecular_formula",
        )

    def test_both_spellings_of_a_key_read_the_same(self):
        """A database written before the CURIEs landed carries expanded IRIs."""
        self.assertEqual(
            labels.predicate_label("chemrof:molecular_formula"),
            labels.predicate_label(CHEMROF_MOLECULAR_FORMULA),
        )

    def test_nothing_at_all_is_an_empty_string(self):
        for value in (None, "", "   "):
            self.assertEqual(labels.predicate_label(value), "")


class ResourceNameTestCase(unittest.TestCase):
    """Which database a known URL points at."""

    def test_every_expandable_xref_prefix_has_a_name(self):
        """The guard on the two tables drifting apart.

        `integrations.chebi` decides which xref prefixes become URLs.  A prefix
        added there and not named here would print a bare host in a column
        whose whole job is to say which database was consulted.
        """
        for key, prefix in XREF_URL_PREFIXES.items():
            with self.subTest(key):
                self.assertNotEqual(
                    labels.resource_name(f"{prefix}1234"),
                    "",
                    f"{key} has no resource name",
                )
                self.assertNotIn(".", labels.resource_name(f"{prefix}1234"))

    def test_the_names_are_the_databases_not_the_hosts(self):
        for url, expected in (
            (_CHEBI_URL, "ChEBI"),
            (_PUBCHEM_URL, "PubChem"),
            (_WIKIPEDIA_URL, "Wikipedia"),
            ("https://www.genome.jp/entry/C00011", "KEGG"),
            ("https://commonchemistry.cas.org/detail?cas_rn=124-38-9",
             "CAS Common Chemistry"),
        ):
            with self.subTest(url):
                self.assertEqual(labels.resource_name(url), expected)

    def test_an_unknown_host_is_still_named(self):
        """PubChem supplies URLs for registries this list has never heard of."""
        self.assertEqual(
            labels.resource_name("https://www.echa.europa.eu/x"), "echa.europa.eu"
        )

    def test_something_that_is_not_a_url_keeps_its_prefix(self):
        self.assertEqual(labels.resource_name(_UNEXPANDED), "Beilstein")


class PropertyValueTestCase(unittest.TestCase):
    """A property whose value is a structure is not a property with no value."""

    def test_a_nested_payload_renders_as_what_it_is(self):
        rendered = filters.property_value({"relationship_type": "isotope_of"})
        self.assertIn("isotope_of", rendered)

    def test_a_declared_value_is_unchanged(self):
        self.assertEqual(filters.property_value({"@value": "CO2"}), "CO2")
        self.assertEqual(
            filters.property_value({"@value": ["O=C=O", "C(=O)=O"]}),
            "O=C=O, C(=O)=O",
        )


class DetailRowTestCase(unittest.TestCase):
    """The two tables, as rows, before any template sees them."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "consensus-flows.sqlite3"
        _fixture(self.path)
        from brightway_flows.webapps.app import db

        self.connection = db.connect(self.path)
        self.addCleanup(self.connection.close)
        self.detail = queries.substance_detail(self.connection, _ID)

    def test_properties_are_ordered_by_what_they_say(self):
        """Not by key.

        Sorting on the IRI grouped the table by namespace and then by
        accession -- an order that means something to the vocabulary and
        nothing to a reader.
        """
        self.assertEqual(
            [row.label for row in self.detail.property_rows],
            ["InChI2D key string", "Isomeric SMILES string", "Molecular formula",
             "Relationships"],
        )

    def test_every_property_row_carries_its_term(self):
        terms = {row.label: row.term for row in self.detail.property_rows}
        self.assertEqual(terms["Molecular formula"], "chemrof:molecular_formula")

    def test_a_reference_is_named_and_credited(self):
        rows = {row.url: row for row in self.detail.reference_rows}
        self.assertEqual(rows[_CHEBI_URL].resource, "ChEBI")
        self.assertEqual(
            rows[_CHEBI_URL].generated_by, "enrich_references.chebi_id_link"
        )

    def test_the_same_url_recorded_twice_is_one_row(self):
        urls = [row.url for row in self.detail.reference_rows]
        self.assertEqual(len(urls), len(set(urls)))
        self.assertEqual(urls.count(_WIKIPEDIA_URL), 1)

    def test_a_bare_string_reference_is_read_too(self):
        """The shape the isotope enrichment writes: no `@id`, no provenance."""
        rows = {row.url: row for row in self.detail.reference_rows}
        self.assertIn(_UNEXPANDED, rows)
        self.assertEqual(rows[_UNEXPANDED].generated_by, "")

    def test_a_reference_that_is_not_a_url_is_not_a_link(self):
        rows = {row.url: row for row in self.detail.reference_rows}
        self.assertFalse(rows[_UNEXPANDED].is_link)
        self.assertTrue(rows[_CHEBI_URL].is_link)


class FlowObjectPageTestCase(unittest.TestCase):
    """The page itself, over a database the pipeline's own writer produced."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "consensus-flows.sqlite3"
        _fixture(self.path)
        app = create_app(self.path)
        app.config["TESTING"] = True
        self.client = app.test_client()

    def page(self) -> str:
        response = self.client.get(f"/flow-objects/{_ID}")
        self.assertEqual(response.status_code, 200)
        return response.get_data(as_text=True)

    def test_the_properties_table_says_the_words_and_the_term(self):
        page = self.page()
        self.assertIn("Molecular formula", page)
        self.assertIn("chemrof:molecular_formula", page)
        # What the column used to be: the IRI's last segment, alone.
        self.assertNotIn('<td class="mono">molecular_formula</td>', page)

    def test_the_known_urls_are_shown_with_the_resource_that_holds_them(self):
        page = self.page()
        table = page.split("Known URLs", 1)[1].split("</table>", 1)[0]
        self.assertIn(_CHEBI_URL, table)
        self.assertIn("ChEBI", table)
        self.assertIn("PubChem", table)
        self.assertIn("enrich_references.pubchem_compound", table)

    def test_a_reference_with_no_expansion_is_text_not_a_link(self):
        table = self.page().split("Known URLs", 1)[1].split("</table>", 1)[0]
        self.assertIn(_UNEXPANDED, table)
        self.assertNotIn(f'href="{_UNEXPANDED}"', table)

    def test_the_flows_section_says_which_flows_and_which_numbers(self):
        """"Flows" and "LCIA" name the same things twice over.

        Every other page calls a row of `elementary_flows` an elementary flow,
        and the column counts characterisation factors.
        """
        page = self.page()
        self.assertIn("<h2>Elementary flows</h2>", page)
        self.assertIn(">CFs</th>", page)


class LegacyUrlTestCase(unittest.TestCase):
    """`/substances` still answers, and says where it went."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "consensus-flows.sqlite3"
        _fixture(self.path)
        app = create_app(self.path)
        app.config["TESTING"] = True
        self.client = app.test_client()

    def test_each_old_path_moves_permanently_to_its_new_one(self):
        for old, new in (
            ("/substances/", "/flow-objects/"),
            (f"/substances/{_ID}", f"/flow-objects/{_ID}"),
            (f"/substances/{_ID}/structure.svg", f"/flow-objects/{_ID}/structure.svg"),
            (f"/substances/{_ID}/changes", f"/flow-objects/{_ID}/changes"),
        ):
            with self.subTest(old):
                response = self.client.get(old)
                self.assertEqual(response.status_code, 301)
                self.assertTrue(response.headers["Location"].endswith(new))

    def test_a_filter_survives_the_redirect(self):
        """The filters are query parameters, and a redirect that dropped them
        would answer a different question from the one that was asked."""
        response = self.client.get("/substances/?type=NeutralMolecule&page=2")
        self.assertEqual(response.status_code, 301)
        self.assertIn("type=NeutralMolecule", response.headers["Location"])
        self.assertIn("page=2", response.headers["Location"])

    def test_the_navigation_points_at_the_new_address(self):
        page = self.client.get("/flow-objects/").get_data(as_text=True)
        self.assertIn('href="/flow-objects/"', page)
        self.assertNotIn('href="/substances/"', page)


if __name__ == "__main__":
    unittest.main()
