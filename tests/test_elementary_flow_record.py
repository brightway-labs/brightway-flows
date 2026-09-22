"""One stored record per flow, the merge's projected from it (#255).

`elementary_flow_json` held the `ElementaryFlow` record the merge reads and
`flow_json` the `Flow` record the export reads.  Where the two carried the same
key they carried the same bytes -- `lcia_methods`, `source_refs`, `context`,
`context_iri`, `unit_iri`, `cas_match_labels` and the rest identical in 94,433
of 94,433 rows of the 2026-08-07 build, with no key differing anywhere.  That
was 221.3 MiB.

`elementary_flow_record` projects the second out of the first.  Verified
against every row of that build: 94,433 projections identical to the column
they replace, none differing.  What is pinned here is the part of the rule a
future reader would not guess.
"""

from __future__ import annotations

import unittest

from brightway_flows.domain.vocabulary import (
    DCTERMS_IS_REPLACED_BY,
    OWL_DEPRECATED,
    SKOS_DEFINITION_IRI,
)
from brightway_flows.pipeline.sqlite import elementary_flow_record


def _flow(**extra) -> dict:
    return {
        "uuid": "u-1",
        "flow_object_id": "fo-1",
        "source": "EF 3.1",
        "context": ["Air", "unspecified"],
        "context_iri": "https://vocab.brightway.one/flow-contexts/envi-air-unkn",
        "unit": "kg",
        "unit_iri": "https://qudt.org/vocab/unit/KiloGM",
        "lcia_methods": [],
        "source_refs": [],
        **extra,
    }


class ProjectionTestCase(unittest.TestCase):
    def test_the_occurrence_keys_are_copied(self):
        record = elementary_flow_record(_flow())
        self.assertEqual(record["flow_object_id"], "fo-1")
        self.assertEqual(record["context"], ["Air", "unspecified"])
        self.assertEqual(record["unit_iri"], "https://qudt.org/vocab/unit/KiloGM")

    def test_the_identifier_comes_from_uuid(self):
        """The same value under the other layer's name for it."""
        self.assertEqual(elementary_flow_record(_flow())["elementary_flow_id"], "u-1")

    def test_an_explicit_identifier_wins(self):
        record = elementary_flow_record(_flow(elementary_flow_id="ef-9"))
        self.assertEqual(record["elementary_flow_id"], "ef-9")

    def test_the_empty_forms_are_spelled_out(self):
        """`Flow` omits these when empty; `ElementaryFlow` states them."""
        record = elementary_flow_record(_flow())
        self.assertIsNone(record["general_comment"])
        self.assertEqual(record["cas_match_labels"], {})

    def test_a_deprecated_flow_carries_no_correspondences(self):
        """14,602 flows are deprecated and exactly 14,602 lack the key."""
        record = elementary_flow_record(
            _flow(**{OWL_DEPRECATED: True,
                     DCTERMS_IS_REPLACED_BY: {"@id": "https://example/x"},
                     "concept_associations": [{"target": "a"}]})
        )
        self.assertNotIn("concept_associations", record)
        self.assertIs(record[OWL_DEPRECATED], True)

    def test_a_live_flow_keeps_its_correspondences(self):
        record = elementary_flow_record(_flow(concept_associations=[{"target": "a"}]))
        self.assertEqual(record["concept_associations"], [{"target": "a"}])

    def test_the_substance_body_is_not_on_a_base_list_record(self):
        """93,993 of 94,433 records are this shape: occurrence keys only."""
        record = elementary_flow_record(
            _flow(altLabel=[{"@value": "syn"}], prefLabel=[{"@value": "Carbon dioxide"}],
                  properties={"x": 1}, references=[{"@id": "r"}],
                  cas_numbers=["124-38-9"])
        )
        for key in ("altLabel", "prefLabel", "properties", "references",
                    "cas_numbers", "name"):
            self.assertNotIn(key, record)

    def test_a_merge_created_record_carries_it(self):
        """The other 440 -- 251 `ecoinvent algorithm addition`, 189 manual.

        `elementary_flow_json` is documented as having exactly one shape and
        has two. Reproduced rather than tidied away: making them one changes
        what the merge reads.
        """
        record = elementary_flow_record(
            _flow(name="Carbon dioxide", altLabel=[{"@value": "syn"}],
                  prefLabel=[{"@value": "Carbon dioxide"}], properties={"x": 1},
                  references=[{"@id": "r"}], cas_numbers=["124-38-9"],
                  ec_numbers=["204-696-9"], **{SKOS_DEFINITION_IRI: ["a gas"]})
        )
        for key in ("name", "altLabel", "prefLabel", "properties", "references",
                    "cas_numbers", "ec_numbers", SKOS_DEFINITION_IRI):
            self.assertIn(key, record)

    def test_flow_only_keys_never_reach_the_record(self):
        """`_provided`, `_sources` and the rest are the transform's, not the
        merge's."""
        record = elementary_flow_record(
            _flow(_provided={"unit": "g"}, _sources={"unit": "unit_normalization"},
                  _transformed=True, identifier="https://example/flow/u-1",
                  synonyms=[], input_datasets=["EF 3.1"])
        )
        for key in ("_provided", "_sources", "_transformed", "identifier",
                    "synonyms", "input_datasets", "uuid"):
            self.assertNotIn(key, record)


if __name__ == "__main__":
    unittest.main()
