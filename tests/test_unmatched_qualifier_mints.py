"""A qualifier no flow object carries rules its candidates out, rather than losing.

`Carbon dioxide, non-fossil, resource correction` carries 124-38-9 and detects the
qualifier `biogenic_resource_correction`.  Seven flow objects carry that registry
number and not one of them carries that qualifier, so the narrowing found nothing
-- and the code then *ignored* the qualifier and let the label branch match
unqualified `Carbon Dioxide`, which is the substance the qualifier exists to
distinguish the row from.  That is #133.

The fix is to read an empty narrowing as evidence rather than as an absence: the
row's own name has ruled out every candidate the number found, so there is nothing
to choose between and `no-flow-object-candidate` is both true and creatable.  It is
the same judgement the material branch above it already makes, and the same one
`merge.creations` documents -- several candidates mean the row matched too much,
and a qualifier none of them carries means it matched too little.

Narrow on purpose.  It fires only where the qualifier is carried by *nothing*, not
where it is carried by objects that happen not to share this CAS.  Three qualifiers
were in that state on the 2026-08-21 build -- `biogenic_resource_correction`,
`grey_water` and `blue_water` -- which is the whole population the rule can reach.
"""

import unittest

from brightway_flows.merge.contexts import ContextExpectations
from brightway_flows.merge.matching import resolve_flow_object
from brightway_flows.merge.report import UnmatchedReason
from brightway_flows.merge.state import MergeAccumulator, MergeIndexes, SourceRow
from brightway_flows.sources import resolve_source_list

CO2 = "fo-carbon-dioxide"
CO2_BIOGENIC = "fo-carbon-dioxide-biogenic"
CAS = "124-38-9"


def _row(name, *, cas=CAS):
    return SourceRow(
        uuid="s-1", name=name, synonyms=[], labels=[name],
        context=["natural resource", "in air"], context_iri="",
        context_normalized=(), unit="kg", unit_iri="", cas=cas, ec="",
    )


def _indexes(*, qualifier_index):
    return MergeIndexes(
        flow_objects_by_id={}, flow_object_label_by_id={},
        cas_index={CAS: {CO2, CO2_BIOGENIC}},
        ec_index={},
        label_index={"carbon dioxide": {CO2}},
        pref_label_index={"carbon dioxide": {CO2}},
        qualifier_index=qualifier_index,
        flow_objects_with_cas={CO2, CO2_BIOGENIC},
        context_expectations=ContextExpectations(
            _by_source_context={}, _source_label="test"
        ),
        consensus_context_strings={},
        prepared_context_decisions={}, mapping_file=None,
        source=resolve_source_list("ecoinvent-3.12"),
    )


def _resolve(row, indexes):
    accumulator = MergeAccumulator()
    resolution = resolve_flow_object(
        row=row, indexes=indexes, accumulator=accumulator
    )
    return resolution, accumulator


class AQualifierNothingCarriesTestCase(unittest.TestCase):
    def test_the_row_is_reported_creatable_rather_than_matched(self):
        """#133.  `biogenic_resource_correction` is carried by no object, so the
        two candidates 124-38-9 found are both ruled out by the row's name."""
        resolution, accumulator = _resolve(
            _row("Carbon dioxide, non-fossil, resource correction"),
            _indexes(qualifier_index={"biogenic": {CO2_BIOGENIC}}),
        )
        self.assertIsNone(resolution)
        self.assertEqual(len(accumulator.unmatched), 1)
        self.assertEqual(
            accumulator.unmatched[0].reason, UnmatchedReason.NO_FLOW_OBJECT_CANDIDATE
        )

    def test_it_does_not_fall_through_to_the_label(self):
        """The whole defect.  `Carbon dioxide` is in the label index and would
        match, which is how the row reached unqualified carbon dioxide before."""
        resolution, _ = _resolve(
            _row("Carbon dioxide, non-fossil, resource correction"),
            _indexes(qualifier_index={"biogenic": {CO2_BIOGENIC}}),
        )
        self.assertIsNone(resolution)

    def test_a_qualifier_some_object_carries_still_narrows(self):
        """The behaviour this must not disturb: `cas+qualifier` is how every
        biogenic and fossil row reaches its substance."""
        resolution, _ = _resolve(
            _row("Carbon dioxide, biogenic"),
            _indexes(qualifier_index={"biogenic": {CO2_BIOGENIC}}),
        )
        self.assertIsNotNone(resolution)
        self.assertEqual(resolution.flow_object_id, CO2_BIOGENIC)
        self.assertEqual(resolution.basis, "cas+qualifier")

    def test_an_unqualified_row_is_untouched(self):
        """No qualifier detected means the branch is never entered, and the
        label still resolves the row as it always did."""
        resolution, _ = _resolve(
            _row("Carbon dioxide"),
            _indexes(qualifier_index={"biogenic": {CO2_BIOGENIC}}),
        )
        self.assertIsNotNone(resolution)
        self.assertEqual(resolution.flow_object_id, CO2)

    def test_a_carried_qualifier_that_misses_this_cas_reports_ambiguity(self):
        """The deliberate limit, and the distinction the rule turns on.

        Here the qualifier *is* carried, just not by anything sharing this
        registry number.  The candidates are therefore still two substances the
        row might be, so the outcome stays `multiple-flow-object-candidates` --
        matched too much, which `merge.creations` refuses to mint for.  Only an
        uncarried qualifier means matched too little.
        """
        resolution, accumulator = _resolve(
            _row("Carbon dioxide, biogenic"),
            _indexes(qualifier_index={"biogenic": {"fo-something-else"}}),
        )
        self.assertIsNone(resolution)
        self.assertEqual(
            accumulator.unmatched[0].reason,
            UnmatchedReason.MULTIPLE_FLOW_OBJECT_CANDIDATES,
        )


if __name__ == "__main__":
    unittest.main()
