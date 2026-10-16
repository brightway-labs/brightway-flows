"""A source row shipped twice is one flow: both copies land together, and the
copy that is not kept is published deprecated onto the one that is.

GreenDelta's openLCA package ships `Occupation, annual crop` in
`Resource / land` and again in `Resource / unspecified`. Without a ruling the
pair reads as a land fold, which stops the build, and as two flows sharing a
consensus flow, which weakens both mappings to `skos:broadMatch`.
"""

from __future__ import annotations

import json
import unittest
from collections import Counter

from brightway_flows.domain.elementary_flow import ElementaryFlow
from brightway_flows.domain.vocabulary import (
    DCTERMS_IS_REPLACED_BY_CURIE,
    OWL_DEPRECATED_CURIE,
    SKOS_EXACT_MATCH_CURIE,
    XKOS_SOURCE_CONCEPT_CURIE,
    XKOS_TARGET_CONCEPT_CURIE,
)
from brightway_flows.filesystem import PACKAGE_DATA_DIR
from brightway_flows.merge.duplicate_rows import (
    DuplicateRow,
    duplicates_reaching_their_valid_row,
    load_source_row_duplicates,
    mark_deprecated_mappings,
)
from brightway_flows.pipeline.match_strength import cardinality_of, weaken
from brightway_flows.sources import registered_source_list

PREFIX = registered_source_list("openlca-2.8.2").flow_iri_prefix
TARGET = "https://vocab.brightway.one/elementary-flow/target"
RULINGS = {
    ("openlca", "dup"): DuplicateRow("openlca", "dup", "valid", "copy in unspecified"),
}


def _association(uuid: str) -> dict:
    return {
        XKOS_SOURCE_CONCEPT_CURIE: {
            "@id": f"{PREFIX}{uuid}",
            SKOS_EXACT_MATCH_CURIE: {"@id": TARGET},
        },
        XKOS_TARGET_CONCEPT_CURIE: {"@id": TARGET},
    }


class TheFileTestCase(unittest.TestCase):
    def setUp(self):
        self.rulings = {
            uuid: row
            for (list_name, uuid), row in load_source_row_duplicates().items()
            if list_name == "openlca"
        }
        self.land = {
            row["source_uuid"]: row
            for row in json.loads(
                (PACKAGE_DATA_DIR / "land-flow-classes.json").read_bytes()
            )["rows"]
            if row["source"] == "openlca-2.8.2"
        }

    def test_160_names_shipped_twice(self):
        """164 duplicates over 160 names: four names ship three copies."""
        self.assertEqual(len(self.rulings), 164)
        self.assertEqual(len({row.valid_uuid for row in self.rulings.values()}), 160)

    def test_a_duplicate_and_its_valid_row_are_one_land_class(self):
        for uuid, row in self.rulings.items():
            with self.subTest(uuid):
                self.assertEqual(
                    self.land[uuid]["key"], self.land[row.valid_uuid]["key"]
                )
                self.assertEqual(
                    self.land[uuid]["source_name"],
                    self.land[row.valid_uuid]["source_name"],
                )

    def test_the_valid_row_is_the_one_in_resource_land(self):
        """Except `Occupation, sea and ocean`, which has no land copy and keeps
        `in water`."""
        compartments = Counter(
            self.land[row.valid_uuid]["source_context"][1]
            for row in self.rulings.values()
        )
        self.assertEqual(compartments, Counter({"land": 163, "in water": 1}))


class TheMergeCheckTestCase(unittest.TestCase):
    def test_a_pair_that_lands_together_is_borne_out(self):
        borne = duplicates_reaching_their_valid_row(
            {"dup": "t", "valid": "t"},
            list_name="openlca", source_label="openlca-2.8.2", duplicates=RULINGS,
        )
        self.assertEqual(set(borne), {"dup"})

    def test_a_pair_that_lands_apart_stops_the_merge(self):
        with self.assertRaises(ValueError):
            duplicates_reaching_their_valid_row(
                {"dup": "t1", "valid": "t2"},
                list_name="openlca", source_label="openlca-2.8.2", duplicates=RULINGS,
            )

    def test_a_pair_this_merge_did_not_see_is_skipped(self):
        """A bounded run, or a release that does not ship one of the two."""
        borne = duplicates_reaching_their_valid_row(
            {"dup": "t"},
            list_name="openlca", source_label="openlca-2.8.2", duplicates=RULINGS,
        )
        self.assertEqual(borne, {})


class TheMappingTestCase(unittest.TestCase):
    def setUp(self):
        self.flow = ElementaryFlow.from_dict({
            "elementary_flow_id": "target",
            "flow_object_id": "fo-1",
            "source": "EF 3.1",
            "context": [],
            "context_iri": "",
            "unit": "m2*a",
            "unit_iri": "",
            "lcia_methods": [],
            "general_comment": "",
            "concept_associations": [_association("valid"), _association("dup")],
        })

    def test_the_duplicate_is_deprecated_onto_the_valid_row(self):
        marked = mark_deprecated_mappings(
            [self.flow], {"dup": RULINGS[("openlca", "dup")]}, flow_iri_prefix=PREFIX
        )
        self.assertEqual(marked, 1)
        valid, duplicate = (
            a[XKOS_SOURCE_CONCEPT_CURIE] for a in self.flow.concept_associations
        )
        self.assertNotIn(OWL_DEPRECATED_CURIE, valid)
        self.assertIs(duplicate[OWL_DEPRECATED_CURIE], True)
        self.assertEqual(
            duplicate[DCTERMS_IS_REPLACED_BY_CURIE], {"@id": f"{PREFIX}valid"}
        )

    def test_both_mappings_stay_exact(self):
        """Two copies of one flow are not two flows sharing a consensus flow."""
        mark_deprecated_mappings(
            [self.flow], {"dup": RULINGS[("openlca", "dup")]}, flow_iri_prefix=PREFIX
        )
        associations = self.flow.concept_associations
        weaken(associations, cardinality_of([associations]))
        for association in associations:
            self.assertIn(SKOS_EXACT_MATCH_CURIE, association[XKOS_SOURCE_CONCEPT_CURIE])

    def test_without_the_ruling_both_are_weakened(self):
        associations = self.flow.concept_associations
        weaken(associations, cardinality_of([associations]))
        for association in associations:
            self.assertNotIn(
                SKOS_EXACT_MATCH_CURIE, association[XKOS_SOURCE_CONCEPT_CURIE]
            )


if __name__ == "__main__":
    unittest.main()
