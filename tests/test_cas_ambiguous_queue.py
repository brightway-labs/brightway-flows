"""One question per name, and the names that answer it.

The `cas-ambiguous` queue asks which registry number a flow's name should
carry, when the name resolves to several ChEBI records and none of them holds
the number the flow has.  Two things were wrong with how it asked.

It asked once per *flow*.  The candidates are derived from the name and from
nothing else, so EF 3.1's `2-hydroxypropanoic Acid` -- filed in thirteen
contexts -- produced thirteen identical rows, and `Dmpa` another thirteen: 30
rows in the 2026-08-16 build for four questions.

And it asked in numbers alone.  `299-85-4` against `71-58-9` is not a question
anyone can answer by reading it; `Zytron` against `medroxyprogesterone acetate`
is.  The labels were meant to be there -- `matched_chebi_records` has a `label`
field -- but the record was read for a `name` key ChEBI does not write, so
every candidate reached the page nameless.
"""

import unittest

from brightway_flows.domain.flow import Flow
from brightway_flows.pipeline.review_records import ReviewQueue
from brightway_flows.transformers.commonchem_cas_review import (
    CommonchemCasReviewTransformer,
)

#: Two ChEBI records `2-hydroxypropanoic acid` resolves to, both offering the
#: racemic number -- so the name is ambiguous and the flow's own `(R)` number
#: is on neither.
LACTIC_RECORDS = {
    "CHEBI:28358": {"label": "rac-lactic acid", "cas_numbers": ["50-21-5"]},
    "CHEBI:78320": {"label": "2-hydroxypropanoic acid", "cas_numbers": ["50-21-5"]},
}

#: `Dmpa`, which two unrelated substances answer to.
DMPA_RECORDS = {
    "CHEBI:229731": {
        "label": "3,4-dimethoxy-L-phenylalanine", "cas_numbers": ["32161-30-1"],
    },
    "CHEBI:6716": {
        "label": "medroxyprogesterone acetate", "cas_numbers": ["71-58-9"],
    },
}


def _transformer(records, *, detail_by_cas=None):
    """The transformer with both caches and the network stubbed out.

    Under test is the row it writes, not how it reaches Common Chemistry.
    """
    transformer = CommonchemCasReviewTransformer()
    transformer._prefetch_commonchem = lambda flows: None
    transformer._save_json_cache = lambda path, payload: None
    # No exact name match, which is the precondition for the ambiguity pass:
    # where Common Chemistry knows the name there is an answer to defer to.
    transformer._commonchem_exact_name_hits = lambda name: []
    transformer._lookup_commonchemistry_detail_cached = (
        lambda cas: (detail_by_cas or {}).get(cas, {})
    )
    transformer._chebi_records = records
    transformer._chebi_by_name = {}
    for chebi_id, record in records.items():
        for cas in record["cas_numbers"]:
            transformer._chebi_by_cas.setdefault(cas, []).append(chebi_id)
    return transformer


def _flow(uuid, name, *, cas=(), source="EF 3.1"):
    return Flow(
        uuid=uuid,
        name=name,
        source=source,
        cas_numbers=list(cas),
        prefLabel=[{"@value": name, "@language": "en"}],
    )


class OneRowPerNameTestCase(unittest.TestCase):
    def _ambiguities(self, transformer, flows):
        transformer.transform(flows)
        return transformer.cas_ambiguous_candidates

    def test_thirteen_flows_under_one_name_are_one_row(self):
        """The question is about the name, and the name has one answer."""
        transformer = _transformer(LACTIC_RECORDS)
        transformer._chebi_by_name["2-hydroxypropanoicacid"] = list(LACTIC_RECORDS)
        flows = [
            _flow(f"u-{index}", "2-hydroxypropanoic Acid", cas=["10326-41-7"])
            for index in range(13)
        ]
        ambiguities = self._ambiguities(transformer, flows)

        self.assertEqual(len(ambiguities), 1)
        self.assertEqual(ambiguities[0].flow_count, 13)
        self.assertEqual(ambiguities[0].flow_uuids, [f"u-{i}" for i in range(13)])

    def test_the_row_links_to_one_of_the_flows_it_answers_for(self):
        """`uuid` is still a flow, so the page still has somewhere to link."""
        transformer = _transformer(LACTIC_RECORDS)
        transformer._chebi_by_name["2-hydroxypropanoicacid"] = list(LACTIC_RECORDS)
        ambiguities = self._ambiguities(transformer, [
            _flow("u-1", "2-hydroxypropanoic Acid", cas=["10326-41-7"]),
            _flow("u-2", "2-hydroxypropanoic Acid", cas=["10326-41-7"]),
        ])
        self.assertEqual(ambiguities[0].uuid, "u-1")

    def test_one_name_spelled_two_ways_is_one_row(self):
        """`Dmpa` and `DMPA` resolve to the same records: one question."""
        transformer = _transformer(DMPA_RECORDS)
        transformer._chebi_by_name["dmpa"] = list(DMPA_RECORDS)
        ambiguities = self._ambiguities(transformer, [
            _flow("u-1", "Dmpa", cas=["299-85-4"]),
            _flow("u-2", "DMPA", cas=["299-85-4"]),
        ])
        self.assertEqual(len(ambiguities), 1)
        self.assertEqual(ambiguities[0].flow_count, 2)

    def test_two_source_lists_are_two_rows(self):
        """Either list could be right about which substance it means."""
        transformer = _transformer(DMPA_RECORDS)
        transformer._chebi_by_name["dmpa"] = list(DMPA_RECORDS)
        ambiguities = self._ambiguities(transformer, [
            _flow("u-1", "Dmpa", cas=["299-85-4"]),
            _flow("u-2", "Dmpa", cas=["299-85-4"], source="ecoinvent 3.11"),
        ])
        self.assertEqual(
            [(a.source, a.flow_count) for a in ambiguities],
            [("EF 3.1", 1), ("ecoinvent 3.11", 1)],
        )

    def test_two_numbers_under_one_name_are_two_rows(self):
        """A different number is a different question, whatever the name."""
        transformer = _transformer(DMPA_RECORDS)
        transformer._chebi_by_name["dmpa"] = list(DMPA_RECORDS)
        ambiguities = self._ambiguities(transformer, [
            _flow("u-1", "Dmpa", cas=["299-85-4"]),
            _flow("u-2", "Dmpa", cas=["78-11-5"]),
        ])
        self.assertEqual(
            [a.current_cas_numbers for a in ambiguities],
            [["299-85-4"], ["78-11-5"]],
        )

    def test_the_key_is_the_question_not_the_flow(self):
        """So a rerun that reorders the flows does not renumber the queue."""
        transformer = _transformer(DMPA_RECORDS)
        transformer._chebi_by_name["dmpa"] = list(DMPA_RECORDS)
        self._ambiguities(transformer, [_flow("u-1", "Dmpa", cas=["299-85-4"])])
        keys = [
            item.item_key for item in transformer.review_queue_items()
            if item.queue_name is ReviewQueue.CAS_AMBIGUOUS
        ]
        self.assertEqual(keys, ["EF 3.1:dmpa:299-85-4"])


class TheNamesBehindTheNumbersTestCase(unittest.TestCase):
    def _one(self, transformer, flows):
        transformer.transform(flows)
        self.assertEqual(len(transformer.cas_ambiguous_candidates), 1)
        return transformer.cas_ambiguous_candidates[0]

    def test_a_candidate_carries_the_label_of_the_record_offering_it(self):
        """Read as `name`, ChEBI's `label` was always absent and the page said
        nothing about any candidate."""
        transformer = _transformer(DMPA_RECORDS)
        transformer._chebi_by_name["dmpa"] = list(DMPA_RECORDS)
        ambiguity = self._one(transformer, [_flow("u-1", "Dmpa", cas=["299-85-4"])])

        self.assertEqual(
            sorted(record.label for record in ambiguity.matched_chebi_records),
            ["3,4-dimethoxy-L-phenylalanine", "medroxyprogesterone acetate"],
        )
        self.assertEqual(
            ambiguity.possible_corrected_cas_names,
            [
                "32161-30-1: 3,4-dimethoxy-L-phenylalanine",
                "71-58-9: medroxyprogesterone acetate",
            ],
        )

    def test_two_records_offering_one_number_are_both_named(self):
        """Which is the usual case, and the two labels are why it is a question."""
        transformer = _transformer(LACTIC_RECORDS)
        transformer._chebi_by_name["2-hydroxypropanoicacid"] = list(LACTIC_RECORDS)
        ambiguity = self._one(
            transformer,
            [_flow("u-1", "2-hydroxypropanoic Acid", cas=["10326-41-7"])],
        )
        self.assertEqual(
            ambiguity.possible_corrected_cas_names,
            ["50-21-5: rac-lactic acid, 2-hydroxypropanoic acid"],
        )

    def test_the_flows_own_number_is_named_by_common_chemistry(self):
        transformer = _transformer(
            DMPA_RECORDS, detail_by_cas={"299-85-4": {"name": "Zytron"}}
        )
        transformer._chebi_by_name["dmpa"] = list(DMPA_RECORDS)
        ambiguity = self._one(transformer, [_flow("u-1", "Dmpa", cas=["299-85-4"])])
        self.assertEqual(ambiguity.current_cas_names, ["299-85-4: Zytron"])

    def test_a_registry_name_is_read_as_text_not_as_markup(self):
        """Common Chemistry marks up formulae for display.  A name is text."""
        transformer = _transformer(
            DMPA_RECORDS,
            detail_by_cas={
                "299-85-4": {"name": "Borax (B<sub>4</sub>Na<sub>2</sub>O<sub>7</sub>)"}
            },
        )
        transformer._chebi_by_name["dmpa"] = list(DMPA_RECORDS)
        ambiguity = self._one(transformer, [_flow("u-1", "Dmpa", cas=["299-85-4"])])
        self.assertEqual(ambiguity.current_cas_names, ["299-85-4: Borax (B4Na2O7)"])

    def test_chebi_names_the_number_common_chemistry_does_not(self):
        """Which is what happens to a hydrate or a mineral."""
        transformer = _transformer({
            **DMPA_RECORDS,
            "CHEBI:86222": {"label": "borax", "cas_numbers": ["299-85-4"]},
        })
        transformer._chebi_by_name["dmpa"] = list(DMPA_RECORDS)
        ambiguity = self._one(transformer, [_flow("u-1", "Dmpa", cas=["299-85-4"])])
        self.assertEqual(ambiguity.current_cas_names, ["299-85-4: borax"])

    def test_a_number_called_what_the_flow_is_called_is_left_out(self):
        """The column exists to show a disagreement.  Repeating the flow's own
        name in it is a column of noise."""
        transformer = _transformer(
            DMPA_RECORDS, detail_by_cas={"299-85-4": {"name": "DMPA"}}
        )
        transformer._chebi_by_name["dmpa"] = list(DMPA_RECORDS)
        ambiguity = self._one(transformer, [_flow("u-1", "Dmpa", cas=["299-85-4"])])
        self.assertEqual(ambiguity.current_cas_names, [])

    def test_a_number_nobody_names_is_left_out(self):
        transformer = _transformer(DMPA_RECORDS)
        transformer._chebi_by_name["dmpa"] = list(DMPA_RECORDS)
        ambiguity = self._one(transformer, [_flow("u-1", "Dmpa", cas=["299-85-4"])])
        self.assertEqual(ambiguity.current_cas_names, [])

    def test_a_flow_with_no_number_has_nothing_to_name(self):
        """`Formate` reaches the queue with no CAS at all: the question is only
        which candidate it should take."""
        transformer = _transformer(DMPA_RECORDS)
        transformer._chebi_by_name["dmpa"] = list(DMPA_RECORDS)
        ambiguity = self._one(transformer, [_flow("u-1", "Dmpa")])
        self.assertEqual(ambiguity.current_cas_numbers, [])
        self.assertEqual(ambiguity.current_cas_names, [])
        self.assertEqual(len(ambiguity.possible_corrected_cas_names), 2)


if __name__ == "__main__":
    unittest.main()
