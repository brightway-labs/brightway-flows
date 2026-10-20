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
    PROV_HAD_PRIMARY_SOURCE_CURIE,
    PROV_WAS_GENERATED_BY_CURIE,
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
        rulings = {
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
        self.water = {
            row["source_uuid"]: row
            for row in json.loads(
                (PACKAGE_DATA_DIR / "water-flow-materials.json").read_bytes()
            )["rows"]
            if row["source"] == "openlca-2.8.2"
        }
        self.land_rulings = {u: r for u, r in rulings.items() if u in self.land}
        self.water_rulings = {u: r for u, r in rulings.items() if u in self.water}
        self.rulings = rulings

    def test_every_ruling_is_a_land_row_or_a_water_row(self):
        self.assertEqual(
            len(self.land_rulings) + len(self.water_rulings), len(self.rulings)
        )

    def test_181_names_shipped_twice(self):
        """185 duplicates over 181 names: four names ship three copies.  The
        last 15 names were ruled on 20 October 2026, once the first build with
        the list showed that another name reaches each of their classes."""
        self.assertEqual(len(self.land_rulings), 185)
        self.assertEqual(
            len({row.valid_uuid for row in self.land_rulings.values()}), 181
        )

    def test_25_water_names_shipped_twice(self):
        """28 duplicates over 25 names: three names ship three copies (#389)."""
        self.assertEqual(len(self.water_rulings), 28)
        self.assertEqual(
            len({row.valid_uuid for row in self.water_rulings.values()}), 25
        )

    def test_a_duplicate_and_its_valid_row_are_one_land_class(self):
        for uuid, row in self.land_rulings.items():
            with self.subTest(uuid):
                self.assertEqual(
                    self.land[uuid]["key"], self.land[row.valid_uuid]["key"]
                )
                self.assertEqual(
                    self.land[uuid]["source_name"],
                    self.land[row.valid_uuid]["source_name"],
                )

    def test_a_duplicate_and_its_valid_row_are_one_water_material(self):
        for uuid, row in self.water_rulings.items():
            with self.subTest(uuid):
                self.assertEqual(
                    self.water[uuid]["node"], self.water[row.valid_uuid]["node"]
                )
                self.assertEqual(
                    self.water[uuid]["source_name"],
                    self.water[row.valid_uuid]["source_name"],
                )

    def test_the_valid_row_is_the_one_in_resource_land(self):
        """Except `Occupation, sea and ocean`, which has no land copy and keeps
        `in water`."""
        compartments = Counter(
            self.land[row.valid_uuid]["source_context"][1]
            for row in self.land_rulings.values()
        )
        self.assertEqual(compartments, Counter({"land": 184, "in water": 1}))

    def test_the_valid_water_row_is_the_one_in_resource_in_water(self):
        compartments = Counter(
            self.water[row.valid_uuid]["source_context"][1]
            for row in self.water_rulings.values()
        )
        self.assertEqual(compartments, Counter({"in water": 28}))


class TheMergeCheckTestCase(unittest.TestCase):
    def _check(self, targets, *, given=("dup", "valid")):
        return duplicates_reaching_their_valid_row(
            targets,
            list_name="openlca",
            source_label="openlca-2.8.2",
            source_uuids=set(given),
            duplicates=RULINGS,
        )

    def test_a_pair_that_lands_together_is_borne_out(self):
        self.assertEqual(set(self._check({"dup": "t", "valid": "t"})), {"dup"})

    def test_a_pair_that_lands_apart_stops_the_merge(self):
        with self.assertRaises(ValueError):
            self._check({"dup": "t1", "valid": "t2"})

    def test_a_pair_this_merge_did_not_see_is_skipped(self):
        """A bounded run, or a release that does not ship one of the two."""
        self.assertEqual(self._check({"dup": "t"}, given=("dup",)), {})

    def test_a_valid_row_given_but_unmatched_stops_the_merge(self):
        """Both rows were in the merge and only the copy landed.  Skipped, the
        copy ruled a duplicate would publish as the only live mapping and
        nothing would say the ruling went unapplied."""
        with self.assertRaisesRegex(ValueError, "valid row valid reached nothing"):
            self._check({"dup": "t"})

    def test_a_duplicate_given_but_unmatched_stops_the_merge(self):
        with self.assertRaisesRegex(ValueError, "dup reached nothing"):
            self._check({"valid": "t"})

    def test_a_pair_given_and_both_unmatched_has_nothing_to_mark(self):
        self.assertEqual(self._check({}), {})


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

    def _mark(self):
        return mark_deprecated_mappings(
            [self.flow],
            {"dup": RULINGS[("openlca", "dup")]},
            flow_iri_prefix=PREFIX,
            merge_activity="merge:openlca-2.8.2",
        )

    def test_the_duplicate_is_deprecated_onto_the_valid_row(self):
        marked = self._mark()
        self.assertEqual(marked, 1)
        valid, duplicate = (
            a[XKOS_SOURCE_CONCEPT_CURIE] for a in self.flow.concept_associations
        )
        self.assertNotIn(OWL_DEPRECATED_CURIE, valid)
        self.assertIs(duplicate[OWL_DEPRECATED_CURIE], True)
        self.assertEqual(
            duplicate[DCTERMS_IS_REPLACED_BY_CURIE], {"@id": f"{PREFIX}valid"}
        )

    def test_the_ruling_is_in_the_mapping_s_provenance(self):
        """Why the row is superseded, and by which row, beside the mark."""
        self._mark()
        valid, duplicate = self.flow.concept_associations
        self.assertNotIn("provenance", valid)
        sources = duplicate["provenance"][PROV_HAD_PRIMARY_SOURCE_CURIE]
        self.assertIn("source-row-duplicates.json", sources)
        self.assertIn("duplicate_of=openlca:valid", sources)
        self.assertEqual(
            duplicate["provenance"][PROV_WAS_GENERATED_BY_CURIE], "merge:openlca-2.8.2"
        )

    def test_the_match_s_provenance_is_kept(self):
        """Merged into what the match wrote, not written over it."""
        self.flow.concept_associations[1]["provenance"] = {
            PROV_WAS_GENERATED_BY_CURIE: "merge",
            PROV_HAD_PRIMARY_SOURCE_CURIE: ["openlca:2.8.2:dup"],
        }
        self._mark()
        provenance = self.flow.concept_associations[1]["provenance"]
        self.assertEqual(provenance[PROV_WAS_GENERATED_BY_CURIE], "merge")
        self.assertEqual(
            provenance[PROV_HAD_PRIMARY_SOURCE_CURIE],
            ["openlca:2.8.2:dup", "source-row-duplicates.json", "duplicate_of=openlca:valid"],
        )

    def test_both_mappings_stay_exact(self):
        """Two copies of one flow are not two flows sharing a consensus flow."""
        self._mark()
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
