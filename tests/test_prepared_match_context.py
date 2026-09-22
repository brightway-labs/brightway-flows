"""A correspondence table says which substance, not which compartment.

EF 3.1 has no forestry soil compartment, so a table that maps ecoinvent's
`soil / forestry` rows onto `Emissions to non-agricultural soil` is naming the
nearest flow EF has.  That is the whole of what a correspondence table can do
here, and it is right.

What used to follow from it was not.  A row a table covered took the target's
compartment as well as its substance, and a row no table covered kept its own --
so atrazine sprayed on forest came out as an emission to non-agricultural soil
and pyrethrins sprayed on forest came out as an emission to forestry soil, with
nothing about the two emissions different and the whole of the difference being
whether EF happens to ship the substance (#84).

Industrial soil showed the same thing between two lists rather than inside one:
ecoinvent and BAFU both file an industrial soil compartment and both map it to
`Ground -> Industrial`, and BAFU's rows stayed there while ecoinvent's were
pulled onto non-agricultural by its tables.

So the table is read for the substance and the compartment stays the row's own.
What is *not* refused is a coarsening: a table pointing a forestry row at soil,
unspecified is still followed, because `Unknown` on the geography axis is the
absence of a claim rather than a competing one -- and that half is tested here
too, because a rule that refuses one target is one edit away from refusing every
target above the row.
"""

import unittest

from brightway_flows.domain.context_registry import context_for_iri
from brightway_flows.domain.elementary_flow import ElementaryFlow
from brightway_flows.merge.contexts import ContextExpectations
from brightway_flows.merge.prepared_context_decisions import (
    PreparedContextDecision,
    PreparedContextRuling,
)
from brightway_flows.merge.rows import apply_prepared_decision
from brightway_flows.merge.state import (
    MergeAccumulator,
    MergeIndexes,
    SourceRow,
)
from brightway_flows.sources import resolve_source_list

NS = "https://vocab.brightway.one/flow-contexts/"
FORESTRY_SOIL = NS + "envi-grou-silv"
INDUSTRIAL_SOIL = NS + "envi-grou-indu"
NON_AGRICULTURAL_SOIL = NS + "envi-grou-noag"
SOIL_UNSPECIFIED = NS + "envi-grou-unkn"
GROUNDWATER = NS + "envi-wate-unaq"
SURFACE_WATER = NS + "envi-wate-suwa"
WATER_UNSPECIFIED = NS + "envi-wate-unkn"

#: The compartments the two ecoinvent rows in #84's worked example are filed
#: in, spelled as ecoinvent spells them.
COMPARTMENTS = {
    ("soil", "forestry"): FORESTRY_SOIL,
    ("soil", "industrial"): INDUSTRIAL_SOIL,
    ("soil", "unspecified"): SOIL_UNSPECIFIED,
    ("water", "ground-"): GROUNDWATER,
}


def _flow(elementary_flow_id, flow_object_id, context_iri, unit="kg"):
    """One base-list flow as the merge carries it: a record, not a payload."""
    return ElementaryFlow(
        elementary_flow_id=elementary_flow_id,
        flow_object_id=flow_object_id,
        source="EF 3.1",
        context=context_for_iri(context_iri),
        context_iri=context_iri,
        unit=unit,
        unit_iri="",
        lcia_methods=[],
        general_comment="",
    )


def _row(name="Atrazine", context=("soil", "forestry"), uuid="src-1", unit="kg"):
    context_iri = COMPARTMENTS[tuple(context)]
    return SourceRow(
        uuid=uuid,
        name=name,
        synonyms=[],
        labels=[name],
        context=list(context),
        context_iri=context_iri,
        context_normalized=list(context),
        unit=unit,
        unit_iri="",
        cas="",
        ec="",
    )


def _indexes(decisions=None):
    return MergeIndexes(
        flow_objects_by_id={},
        flow_object_label_by_id={"fo-atrazine": "Atrazine"},
        cas_index={},
        ec_index={},
        label_index={},
        pref_label_index={},
        qualifier_index={},
        flow_objects_with_cas=set(),
        context_expectations=ContextExpectations(
            _by_source_context=dict(COMPARTMENTS),
            _source_label="ecoinvent-3.12",
        ),
        consensus_context_strings={},
        prepared_context_decisions=decisions or {},
        mapping_file=None,
        source=resolve_source_list("ecoinvent-3.12"),
    )


def _apply(row, target, accumulator, indexes=None):
    """Run one row through the prepared route, as the merge loop would."""
    return apply_prepared_decision(
        row=row,
        prepared_rows=[{"target": {"uuid": target}}],
        indexes=indexes or _indexes(),
        accumulator=accumulator,
    )


class TableDecidesTheSubstanceTestCase(unittest.TestCase):
    """The half of #84 that moves rows: the compartment stays the row's own."""

    def test_a_forestry_row_is_not_published_on_non_agricultural_soil(self):
        """Atrazine's, the row the issue is written around.

        EF ships an atrazine flow in non-agricultural soil and the table names
        it, so before this the pesticide ecoinvent said went on forest soil was
        published as an emission to soil that is merely not farmland.
        """
        accumulator = MergeAccumulator()
        accumulator.add_flow(_flow("ef-atrazine", "fo-atrazine", NON_AGRICULTURAL_SOIL))

        self.assertTrue(_apply(_row(), "ef-atrazine", accumulator))

        self.assertEqual(accumulator.prepared_matches, [])
        (match,) = accumulator.algorithm_matches
        created = accumulator.all_by_elem_id[match.target_elementary_flow_id]
        self.assertEqual(created.context_iri, FORESTRY_SOIL)
        # The substance is the table's, which is the curated half of its answer.
        self.assertEqual(created.flow_object_id, "fo-atrazine")

    def test_the_created_flow_says_a_curator_named_the_substance(self):
        """Not an algorithmic match: the substance came from the table.

        A report that called this route algorithmic would send somebody looking
        for the name-and-CAS reasoning that decided it, and there is none.
        """
        accumulator = MergeAccumulator()
        accumulator.add_flow(_flow("ef-atrazine", "fo-atrazine", NON_AGRICULTURAL_SOIL))
        _apply(_row(), "ef-atrazine", accumulator)

        (match,) = accumulator.algorithm_matches
        self.assertEqual(match.matching_method, "prepared")
        self.assertEqual(match.basis, "prepared_mapping")
        self.assertEqual(match.basis_value, "ef-atrazine")
        self.assertEqual(
            match.algorithm_details["rejected_contradicting_context_iri"],
            NON_AGRICULTURAL_SOIL,
        )

    def test_it_joins_a_flow_of_the_same_substance_already_in_its_compartment(self):
        """Two lists filing one substance on forest soil meet on one flow.

        The point of the compartment surviving: BAFU's forestry rows were
        already there, and an ecoinvent row arriving must join them rather than
        mint a second flow beside them.
        """
        accumulator = MergeAccumulator()
        accumulator.add_flow(_flow("ef-atrazine", "fo-atrazine", NON_AGRICULTURAL_SOIL))
        accumulator.add_flow(_flow("silv-atrazine", "fo-atrazine", FORESTRY_SOIL))

        self.assertTrue(_apply(_row(), "ef-atrazine", accumulator))

        self.assertEqual(accumulator.algorithm_matches, [])
        (match,) = accumulator.prepared_matches
        self.assertEqual(match.target_elementary_flow_id, "silv-atrazine")
        self.assertEqual(match.prepared_target_elementary_flow_id, "ef-atrazine")
        self.assertEqual(match.prepared_target_resolution, "source-context-target")

    def test_an_industrial_soil_row_keeps_its_compartment_too(self):
        """The between-lists half of #84, on the compartment both lists agree on."""
        accumulator = MergeAccumulator()
        accumulator.add_flow(_flow("ef-glyph", "fo-glyphosate", NON_AGRICULTURAL_SOIL))

        _apply(
            _row(name="Glyphosate", context=("soil", "industrial")),
            "ef-glyph",
            accumulator,
        )

        (match,) = accumulator.algorithm_matches
        created = accumulator.all_by_elem_id[match.target_elementary_flow_id]
        self.assertEqual(created.context_iri, INDUSTRIAL_SOIL)

    def test_a_groundwater_row_keeps_its_compartment(self):
        """#77, and the same act on water rather than soil.

        EF 3.1 has no groundwater emission compartment, so the tables point
        ecoinvent's `water / ground-` rows at EF's fresh water.  Publishing them
        there was allowed while ecoinvent's own `EF v3.1` implementation reading
        the freshwater factor was taken as saying where the release happened; it
        says what the release is characterised as, and the row said groundwater.
        """
        accumulator = MergeAccumulator()
        accumulator.add_flow(_flow("ef-fresh", "fo-zinc", SURFACE_WATER))

        _apply(_row(name="Zinc", context=("water", "ground-")), "ef-fresh", accumulator)

        (match,) = accumulator.algorithm_matches
        created = accumulator.all_by_elem_id[match.target_elementary_flow_id]
        self.assertEqual(created.context_iri, GROUNDWATER)

    def test_a_groundwater_row_joins_a_flow_already_in_its_compartment(self):
        """What the split cost, stated as the thing that now happens instead.

        BAFU files `emissions to water / groundwater` and nothing pulled its
        rows off it, so BAFU's groundwater flows were already on the aquifer
        while ecoinvent's rows for the same substances were on surface water --
        32 substances published twice.  An ecoinvent row arriving must join them
        rather than mint a second flow beside them.
        """
        accumulator = MergeAccumulator()
        accumulator.add_flow(_flow("ef-fresh", "fo-zinc", SURFACE_WATER))
        accumulator.add_flow(_flow("bafu-zinc", "fo-zinc", GROUNDWATER))

        self.assertTrue(
            _apply(
                _row(name="Zinc", context=("water", "ground-")),
                "ef-fresh",
                accumulator,
            )
        )

        self.assertEqual(accumulator.algorithm_matches, [])
        (match,) = accumulator.prepared_matches
        self.assertEqual(match.target_elementary_flow_id, "bafu-zinc")
        self.assertEqual(match.prepared_target_elementary_flow_id, "ef-fresh")
        self.assertEqual(match.prepared_target_resolution, "source-context-target")


class WhatIsStillFollowedTestCase(unittest.TestCase):
    """The other half, and the one a widening of the rule would break."""

    def test_a_coarsening_onto_soil_unspecified_is_still_followed(self):
        """`Unknown` is the absence of a claim, not a competing one.

        A table with nothing better than "an emission to soil" for a forestry
        row is still believed, and the row is published there.  Refusing this
        as well would be refusing every target above the row rather than the
        one that denies it.
        """
        accumulator = MergeAccumulator()
        accumulator.add_flow(_flow("ef-soil", "fo-atrazine", SOIL_UNSPECIFIED))

        _apply(_row(), "ef-soil", accumulator)

        self.assertEqual(accumulator.algorithm_matches, [])
        (match,) = accumulator.prepared_matches
        self.assertEqual(match.target_elementary_flow_id, "ef-soil")
        self.assertEqual(match.prepared_target_resolution, "direct-active-target")

    def test_a_coarsening_onto_water_unspecified_is_still_followed(self):
        """The same half, on the compartment #77 moved.

        A table with nothing better than "an emission to water" for a
        groundwater row is still believed.  `Unknown` on the water body axis is
        the absence of a claim, so refusing EF's fresh water is not refusing
        every target above the row.
        """
        accumulator = MergeAccumulator()
        accumulator.add_flow(_flow("ef-water", "fo-zinc", WATER_UNSPECIFIED))

        _apply(_row(name="Zinc", context=("water", "ground-")), "ef-water", accumulator)

        self.assertEqual(accumulator.algorithm_matches, [])
        (match,) = accumulator.prepared_matches
        self.assertEqual(match.target_elementary_flow_id, "ef-water")

    def test_a_table_pointing_at_the_rows_own_compartment_is_untouched(self):
        accumulator = MergeAccumulator()
        accumulator.add_flow(_flow("silv-atrazine", "fo-atrazine", FORESTRY_SOIL))

        _apply(_row(), "silv-atrazine", accumulator)

        (match,) = accumulator.prepared_matches
        self.assertEqual(match.target_elementary_flow_id, "silv-atrazine")
        self.assertEqual(match.prepared_target_resolution, "direct-active-target")

    def test_a_curators_expected_decision_keeps_its_own_name(self):
        """The branch this rule joined was already there, and still says so.

        `expected` means the curator looked at the pairing and said the target
        does not cover the row's context.  Two reasons now lead to the same
        move, and the report has to go on distinguishing a curator's ruling
        from a rule.
        """
        accumulator = MergeAccumulator()
        accumulator.add_flow(_flow("ef-soil", "fo-atrazine", SOIL_UNSPECIFIED))
        accumulator.add_flow(_flow("silv-atrazine", "fo-atrazine", FORESTRY_SOIL))
        decisions = {
            ("src-1", "ef-soil"): PreparedContextRuling(
                list_name="ecoinvent",
                source_uuid="src-1",
                prepared_target_elementary_flow_id="ef-soil",
                decision=PreparedContextDecision.EXPECTED,
            )
        }

        _apply(_row(), "ef-soil", accumulator, indexes=_indexes(decisions))

        (match,) = accumulator.prepared_matches
        self.assertEqual(match.target_elementary_flow_id, "silv-atrazine")
        self.assertEqual(
            match.prepared_target_resolution, "manual-expected-context-target"
        )


if __name__ == "__main__":
    unittest.main()
