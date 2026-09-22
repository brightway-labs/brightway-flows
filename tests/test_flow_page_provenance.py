"""What the flow page says about where a flow came from, and why.

Three columns on `/flows/<uuid>` showed nothing at all.  The concept-association
table asked each association for `source_list`, `list_name`, `source_flow_uuid`,
`source_flow` and `conversion_factor` -- five flat keys, none of which any
association has ever carried, because an association is a JSON-LD
`xkos:ConceptAssociation` and the list, the flow, its name and its compartment
are all inside `xkos:sourceConcept`.  Every row on every flow in the list
printed an em dash.

The `Source lists` table had the opposite problem: what it showed was right, and
it left out the one thing a curator is looking at the page to find out -- why
the merge holds an ecoinvent row and an EF row to be the same substance in the
same compartment.  That was in the database all along, in the `source_metadata`
each row carries, as four hyphenated category names.

What is pinned here:

- **Every column reads the shape the merge publishes**, in both spellings.
  A build before the CURIE change keys associations with expanded IRIs, and the
  app reads whichever database is in the data directory.
- **Every merge category the build produces has words.** An unrecognised one is
  printed rather than dropped, because "recorded, and this page has no words for
  it" is a different claim from "nothing was recorded".
- **The diff cells carry the class that gives them a width.** `From` and `To`
  break between any two characters, so an auto table layout gives them one
  character and hands the rest to the prose column beside them.
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
    CONSENSUS_ELEMENTARY_FLOW_IRI_PREFIX,
)
from brightway_flows.sources import base_source_list, registered_source_list
from brightway_flows.webapps.app import create_app
from brightway_flows.webapps.app import filters
from brightway_flows.webapps.app.match_reasons import match_reason

_ECOINVENT = registered_source_list("ecoinvent-3.12")
_BASE = base_source_list()
_UUID = "u-co2"
_SOURCE_UUID = "3ed5f377-344f-423a-b5ec-9a9a1162b944"

_AIR = context_from_dict(
    {"dimension": "Environmental", "media": "Air", "strata": "Unknown"}
)

#: An association in the shape the merge publishes, CURIE-keyed.
_ASSOCIATION = {
    "@type": "xkos:ConceptAssociation",
    "xkos:sourceConcept": {
        "@id": f"{_ECOINVENT.flow_iri_prefix}{_SOURCE_UUID}",
        "skos:prefLabel": "Carbon dioxide, fossil",
        "context": "air / non-urban air or from high stacks",
        "qudt:hasUnit": {"@id": "https://vocab.brightway.one/units/unit/KiloGM"},
        "skos:exactMatch": {"@id": f"{CONSENSUS_ELEMENTARY_FLOW_IRI_PREFIX}{_UUID}"},
    },
    "xkos:targetConcept": {
        "@id": f"{CONSENSUS_ELEMENTARY_FLOW_IRI_PREFIX}{_UUID}"
    },
    "qudt:conversionMultiplier": 1025.0,
}

#: The same association as a database written before #76's CURIEs holds it.
_EXPANDED = {
    "@type": "http://rdf-vocabulary.ddialliance.org/xkos#ConceptAssociation",
    "http://rdf-vocabulary.ddialliance.org/xkos#sourceConcept": {
        "@id": f"{_ECOINVENT.flow_iri_prefix}{_SOURCE_UUID}",
        "http://www.w3.org/2004/02/skos/core#prefLabel": "Carbon dioxide, fossil",
        "context": ["air", "non-urban air or from high stacks"],
        "http://www.w3.org/2004/02/skos/core#broadMatch": {
            "@id": f"{CONSENSUS_ELEMENTARY_FLOW_IRI_PREFIX}{_UUID}"
        },
    },
}


class AssociationColumnsTestCase(unittest.TestCase):
    """The four columns that read the source concept."""

    def test_the_list_is_named_from_the_iri_its_flows_are_minted_under(self):
        self.assertEqual(filters.source_list(_ASSOCIATION), "ecoinvent 3.12")

    def test_the_base_list_is_named_as_well(self):
        """`known_source_lists` leaves it out, and most associations point at it."""
        association = {
            "xkos:sourceConcept": {"@id": f"{_BASE.flow_iri_prefix}{_UUID}"}
        }
        self.assertEqual(
            filters.source_list(association),
            f"{_BASE.list_name} {_BASE.list_version}",
        )

    def test_an_unregistered_prefix_falls_back_to_the_iri_itself(self):
        association = {
            "xkos:sourceConcept": {
                "@id": "https://vocab.brightway.one/madeup/9.9/flow/abc"
            }
        }
        self.assertEqual(filters.source_list(association), "madeup 9.9")

    def test_the_flow_its_name_and_its_compartment_come_off_the_concept(self):
        self.assertEqual(filters.source_flow_uuid(_ASSOCIATION), _SOURCE_UUID)
        self.assertEqual(
            filters.source_flow_name(_ASSOCIATION), "Carbon dioxide, fossil"
        )
        self.assertEqual(
            filters.source_flow_context(_ASSOCIATION),
            "air / non-urban air or from high stacks",
        )

    def test_the_conversion_is_the_multiplier_the_association_carries(self):
        """`conversion_factor` is not a key any association has ever had."""
        self.assertEqual(filters.conversion_multiplier(_ASSOCIATION), "1,025")
        self.assertEqual(filters.conversion_multiplier(_EXPANDED), "")

    def test_expanded_iris_read_the_same_as_curies(self):
        self.assertEqual(filters.source_list(_EXPANDED), "ecoinvent 3.12")
        self.assertEqual(filters.source_flow_uuid(_EXPANDED), _SOURCE_UUID)
        self.assertEqual(
            filters.source_flow_name(_EXPANDED), "Carbon dioxide, fossil"
        )
        self.assertEqual(
            filters.source_flow_context(_EXPANDED),
            "air / non-urban air or from high stacks",
        )
        self.assertEqual(filters.match_type(_EXPANDED), "broadMatch")

    def test_nothing_at_all_is_an_empty_string_not_a_crash(self):
        for value in (None, "", {}, []):
            self.assertEqual(filters.source_list(value), "")
            self.assertEqual(filters.source_flow_uuid(value), "")
            self.assertEqual(filters.source_flow_name(value), "")
            self.assertEqual(filters.conversion_multiplier(value), "")


class MatchReasonTestCase(unittest.TestCase):
    """Every category the merge writes, as a sentence."""

    def test_the_base_list_is_the_flow_rather_than_a_match(self):
        reason = match_reason({"original_context": ["air"]}, base_list=True)
        self.assertIn("built from this one", reason)

    def test_a_registry_number_match_names_the_number_and_the_compartment(self):
        reason = match_reason({
            "cas_number": "124-38-9",
            "merge_basis": "cas",
            "merge_method": "algorithmic_fallback",
            "selector_reason": "exact-context-iri-match",
        })
        self.assertEqual(
            reason,
            "The CAS numbers are the same (124-38-9); both name the same "
            "compartment.",
        )

    def test_a_created_flow_says_it_was_created_and_why(self):
        reason = match_reason({
            "cas_number": "124-38-9",
            "merge_basis": "cas",
            "merge_method": "algorithmic_fallback",
            "selector_reason": "new-elementary-flow-created",
        })
        self.assertIn("no flow of this substance sat in that compartment", reason)

    def test_a_curated_mapping_names_the_file_it_was_written_in(self):
        reason = match_reason({
            "merge_basis": "prepared_mapping",
            "merge_method": "randonneur_replace_table",
            "selector_reason": "direct-target-uuid",
            "mapping_file": "ecoinvent-3.8-biosphere-EF-3.1-biosphere.json",
        })
        self.assertEqual(
            reason,
            "A curator's mapping table "
            "(ecoinvent-3.8-biosphere-EF-3.1-biosphere.json) names this flow.",
        )

    def test_a_mapping_onto_a_deprecated_flow_says_so(self):
        """The row the curator wrote is not the flow the reader is looking at."""
        reason = match_reason({
            "merge_basis": "prepared_mapping",
            "merge_method": "randonneur_replace_table",
            "selector_reason": "direct-target-uuid",
            "mapping_file": "ecoinvent-3.8-biosphere-EF-3.1-biosphere.json",
            "merge_details": {
                "prepared_target_resolution": "redirected-from-deprecated-target"
            },
        })
        self.assertIn("has since been deprecated", reason)

    def test_a_row_that_matched_nothing_says_the_flow_is_its_own(self):
        reason = match_reason({
            "merge_basis": "no-flow-object-candidate",
            "merge_method": "flow_object_creation",
            "selector_reason": "new-flow-object-created",
        })
        self.assertEqual(
            reason,
            "Nothing in the list carried this substance, so this flow was "
            "created from this row.",
        )

    def test_a_category_with_no_words_yet_is_printed_rather_than_dropped(self):
        reason = match_reason({
            "merge_basis": "something-new", "merge_method": "some_method",
        })
        self.assertEqual(reason, "Recorded as some_method on something-new.")

    def test_a_row_recording_no_decision_says_nothing(self):
        self.assertEqual(match_reason({"original_context": ["air"]}), "")
        self.assertEqual(match_reason(None), "")


def _fixture(path: Path) -> None:
    """One flow, carried by the base list and matched by one ecoinvent row."""
    import brightway_flows.pipeline.sqlite as sqlite_module

    flow = Flow(
        uuid=_UUID,
        source=_BASE.source_label,
        unit="kg",
        prefLabel=[{"@value": "Carbon dioxide", "@language": "en"}],
        context=_AIR,
        cas_numbers=["124-38-9"],
        concept_associations=[_ASSOCIATION],
    )
    flow_object = FlowObject(
        flow_object_id="fo-co2",
        prefLabel=[{"@value": "Carbon dioxide", "@language": "en"}],
        altLabel=[],
        classifications={CHEMINF_CAS_REGISTRY_NUMBER: {"@value": ["124-38-9"]}},
        properties={},
        references=[],
        created_from={},
    )
    elementary = ElementaryFlow(
        elementary_flow_id=_UUID,
        flow_object_id="fo-co2",
        source=_BASE.source_label,
        context=_AIR,
        context_iri="",
        unit="kg",
        unit_iri="",
        lcia_methods=[],
        general_comment=None,
        source_refs=[
            {
                "list_name": _BASE.list_name,
                "list_version": _BASE.list_version,
                "source_flow_uuid": "ef-co2",
                "source_flow_name": "Carbon dioxide",
                "source_metadata": {"original_context": ["Emissions", "to air"]},
            },
            {
                "list_name": _ECOINVENT.list_name,
                "list_version": _ECOINVENT.list_version,
                "source_flow_uuid": _SOURCE_UUID,
                "source_flow_name": "Carbon dioxide, fossil",
                "source_metadata": {
                    "cas_number": "124-38-9",
                    "merge_basis": "cas",
                    "merge_method": "algorithmic_fallback",
                    "selector_reason": "exact-context-iri-match",
                },
            },
        ],
    )
    original = sqlite_module.CONSENSUS_DB_FILEPATH
    sqlite_module.CONSENSUS_DB_FILEPATH = path
    try:
        sqlite_module._write_consensus_sqlite(
            [flow], [], [flow_object], [elementary]
        )
    finally:
        sqlite_module.CONSENSUS_DB_FILEPATH = original


class FlowPageTestCase(unittest.TestCase):
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
        response = self.client.get(f"/flows/{_UUID}")
        self.assertEqual(response.status_code, 200)
        return response.get_data(as_text=True)

    def test_each_source_row_says_why_it_is_this_flow(self):
        page = self.page()
        self.assertIn(
            "The CAS numbers are the same (124-38-9); both name the same "
            "compartment.",
            page,
        )
        self.assertIn("built from this one", page)

    def test_the_association_names_its_list_its_flow_and_its_name(self):
        page = self.page()
        self.assertIn("ecoinvent 3.12", page)
        self.assertIn(_SOURCE_UUID, page)
        self.assertIn("air / non-urban air or from high stacks", page)
        self.assertIn("1,025", page)

    def test_no_column_of_the_association_table_is_an_em_dash(self):
        """The failure this page had: a table of six columns of nothing."""
        page = self.page()
        table = page.split("Concept associations", 1)[1].split("</table>", 1)[0]
        self.assertNotIn("—", table)


class DiffCellTestCase(unittest.TestCase):
    """`From` and `To` have a width to be read in.

    The class and the rule that gives it a floor are checked together: either
    one alone is what the columns already had, and the symptom -- a value
    wrapped one character per line -- shows up in a browser and in no test.
    """

    ROOT = Path(__file__).resolve().parents[1] / "src" / "brightway_flows"

    def test_every_diff_cell_is_a_value_cell(self):
        templates = self.ROOT / "webapps" / "app" / "templates"
        for name in ("changes.html", "partials/history.html"):
            text = (templates / name).read_text()
            self.assertEqual(
                text.count('class="value value--'),
                text.count('<td class="value-cell">'),
                f"{name} has a diff cell with no width",
            )

    def test_the_stylesheet_gives_that_cell_a_minimum_width(self):
        css = (self.ROOT / "webapps" / "app" / "static" / "app.css").read_text()
        self.assertIn("td.value-cell {", css)
        self.assertIn("min-width:", css.split("td.value-cell {", 1)[1][:120])


if __name__ == "__main__":
    unittest.main()
