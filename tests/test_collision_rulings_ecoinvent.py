"""What a source list mapped onto the flow a ruling collapses.

ecoinvent reaches EF 3.1 through a prepared correspondence table that names a
target by identifier, and for perfluoropentane in unspecified air that target is
`4d9a8790-3ddd-11dd-9062-0050c2490048` -- the row #44's ruling collapses,
because the characterisation is on the other one.  Collapsing a flow a source
list maps onto is only safe if the mapping lands on the survivor, and
`merge/prepared.py` is what makes it: it follows the replacement chain and
records that it did.

This is that guarantee as a test rather than as a claim, built by applying the
shipped rulings to real records and resolving the shipped table against them.
"""

import unittest
from pathlib import Path

import orjson

from brightway_flows.domain.context_registry import context_for_iri
from brightway_flows.domain.elementary_flow import ElementaryFlow
from brightway_flows.domain.lcia.records import (
    StatedFactor,
    stated_category,
)
from brightway_flows.domain.flow import Flow
from brightway_flows.merge.prepared import _resolve_active_prepared_target
from brightway_flows.pipeline.collision_decisions import (
    apply_collision_rulings,
    load_collision_rulings,
)
from brightway_flows.pipeline.deduplication import duplicate_survivor_rank

OVERRIDES_TABLE = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "brightway_flows"
    / "data"
    / "ecoinvent-match-overrides.json"
)

#: The one collision in the shipped rulings whose collapsed row ecoinvent 3.8
#: maps onto.  Named rather than discovered so that a table that stops naming it
#: is a failure here and not a test that quietly checks nothing.
PERFLUOROPENTANE_UNSPECIFIED_AIR = (
    "fo-437b79cb0b62b121",
    "https://vocab.brightway.one/flow-contexts/envi-air-unkn",
    "kg",
)


def _curated_target_uuids() -> set[str]:
    """Every EF flow this project's own correspondence points at.

    This used to read the composed 3.8 table -- the mapping whose rows a
    collision ruling must not strand.  The tables are retired and the table
    went to git history (#141), so the mapping that can be stranded now is
    the override rows', and it is read here from the file the merge reads.
    """
    payload = orjson.loads(OVERRIDES_TABLE.read_bytes())
    return {
        str(row.get("target_uuid") or "").strip()
        for row in payload.get("overrides", [])
        if row.get("target_uuid")
    }


def _record(uuid: str, ruling, factors: list[StatedFactor]) -> ElementaryFlow:
    return ElementaryFlow(
        elementary_flow_id=uuid,
        flow_object_id=ruling.flow_object_id,
        source="EF 3.1",
        # Resolved from the IRI the ruling names, so the record cannot say
        # one context and its `context_iri` another.
        context=context_for_iri(ruling.context_iri),
        context_iri=ruling.context_iri,
        unit=ruling.unit,
        unit_iri="",
        lcia_methods=factors,
        general_comment=None,
    )



class TheRedirectTestCase(unittest.TestCase):
    def setUp(self):
        self.index = load_collision_rulings()
        self.ruling = self.index[PERFLUOROPENTANE_UNSPECIFIED_AIR]
        self.survivor = _record(
            self.ruling.survivor,
            self.ruling,
            [
                StatedFactor(
                    category=stated_category(
                        uuid="climate-change", name="Climate change"
                    ),
                    flow_uuid=self.ruling.survivor,
                    amount=9220.0,
                )
            ],
        )
        self.collapsed = _record(self.ruling.merged[0], self.ruling, [])
        rows = [self.survivor, self.collapsed]
        counts = apply_collision_rulings(
            flows=[Flow(uuid=row.elementary_flow_id, name="", source="EF 3.1")
                   for row in rows],
            elementary_flows=rows,
            rulings={self.ruling.key: self.ruling},
        )
        self.assertEqual(counts["collision_rulings_applied"], 1)
        self.records = {row.elementary_flow_id: row for row in rows}
        self.payloads = {row.elementary_flow_id: row.to_dict() for row in rows}

    def test_the_prepared_target_resolves_to_the_survivor(self):
        resolved, row, chain, reason = _resolve_active_prepared_target(
            self.ruling.merged[0],
            all_by_elem_id=self.records,
            active_by_elem_id={
                self.survivor.elementary_flow_id:
                    self.records[self.survivor.elementary_flow_id]
            },
        )
        self.assertEqual(resolved, self.ruling.survivor)
        self.assertEqual(reason, "redirected-from-deprecated-target")
        self.assertEqual(chain, [self.ruling.merged[0], self.ruling.survivor])
        self.assertIsNotNone(row)

    def test_the_survivor_carries_the_characterisation_the_mapping_wanted(self):
        """ecoinvent mapped onto an uncharacterised row; what it reaches now is
        the row holding the factor, which is the point of the collapse."""
        payload = self.payloads[self.ruling.survivor]
        self.assertEqual(len(payload["lcia_methods"]), 1)

    def test_both_rows_stay_on_one_flow_object(self):
        """The object was never the question -- the two rows already shared
        one -- so a consumer resolving the merged flow to its substance lands
        in the same place before and after."""
        self.assertEqual(
            {payload["flow_object_id"] for payload in self.payloads.values()},
            {self.ruling.flow_object_id},
        )


class CarbonTetrachlorideKeepsTheMappedRowTestCase(unittest.TestCase):
    """#105, and the other way round from the case above.

    Perfluoropentane is a ruling that collapses the row the table names and
    relies on the redirect to carry the mapping across.  The five carbon
    tetrachloride rulings do not need a redirect at all, because they keep the
    row the table names -- and the reason they have to be written down is that
    deduplication's sort would have collapsed it.

    The two rows tie on factor count in all five contexts, so the sort falls
    through to the identifier and `8a31…` sorts before both `d86c61db…` and
    `fe0acd60…`.  That is the row EF ships bare: no registry number, no EC
    number, no synonyms, and no source list mapping onto it.
    """

    OBJECT = "fo-e8f7bd337de840c4"

    def setUp(self):
        self.rulings = [
            ruling for ruling in load_collision_rulings().values()
            if ruling.flow_object_id == self.OBJECT
        ]

    def test_all_five_air_contexts_are_ruled_on(self):
        """Named as a count because #105 is about the pairing, not one row: a
        repair that fixed unspecified air alone would leave four."""
        self.assertEqual(len(self.rulings), 5)



    def test_the_sort_would_have_kept_the_other_row(self):
        """The premise of the whole file, as a failing alternative.

        If EF ever changes the factors so that the sort agrees, this test says
        so rather than leaving five rulings that look like restatements of what
        deduplication does anyway.
        """
        for ruling in self.rulings:
            with self.subTest(context=ruling.context_iri):
                # Equal factor counts, which is what makes the identifier
                # decide; the numbers themselves are checked on the build.
                rows = [
                    _record(uuid, ruling, [])
                    for uuid in (ruling.survivor, *ruling.merged)
                ]
                rows.sort(key=duplicate_survivor_rank)
                self.assertNotEqual(rows[0].elementary_flow_id, ruling.survivor)


class NoRulingStrandsACuratedRowTestCase(unittest.TestCase):
    def test_every_collapsed_flow_an_override_names_has_a_live_survivor(self):
        """The general form: a ruling may collapse a flow the correspondence
        maps onto, but never onto a flow another ruling also collapses -- that
        would leave the mapping resolving onto a deprecated row.  The
        correspondence is this project's own override rows now (#141)."""
        index = load_collision_rulings()
        collapsed = {uuid for ruling in index.values() for uuid in ruling.merged}
        targets = _curated_target_uuids()
        for ruling in index.values():
            for uuid in ruling.merged:
                if uuid not in targets:
                    continue
                with self.subTest(target=uuid):
                    self.assertNotIn(ruling.survivor, collapsed)


if __name__ == "__main__":
    unittest.main()
