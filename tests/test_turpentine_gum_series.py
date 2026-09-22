"""Gum turpentine's thirteen rows, and the name that changes across them.

EF 3.1 publishes gum turpentine oil once per context.  Six of those rows -- the
six air contexts -- are named `Gum turpentine`; the other seven -- the three
soils and the four waters -- are named `turpentine`.  All thirteen carry EC
932-349-8, CAS 8006-64-2 and the same synonyms, and six contexts plus seven
contexts is thirteen contexts with none repeated, which is what says the
thirteen are one series and the name is the only thing varying across it.

`turpentine` is also EF's name for its *other* entry on that registry number,
EC 232-350-7, which has thirteen rows of its own.  8006-64-2 is ruled
`separate` in `contested-cas-decisions.json`, so the layering keys these flows
on their name -- and a split by name cannot help when the name is what changed.
The seven landed on the other entry, colliding with it in all seven contexts:
two live flows for one substance in one context and unit, freshwater
ecotoxicity 8.399 against 1.1619 in agricultural soil and 0.074841 against
0.00030382 in sea water (#281).

The correction is one fix in `ef-3.1-manual-fixes.json`, matched on the name
*and* the EC number, and these assert what it buys: the thirteen `932-349-8`
rows share one flow object, the other entry's thirteen keep theirs, and no
context holds two live flows of either.

The identifiers below are EF 3.1's own, and each expected object id is
`stable_flow_object_id("fo", "name:<name>|cas:8006-64-2")` -- the basis the
layering uses for a registry number ruled contested -- so a corrected row
landing anywhere else fails.
"""

from __future__ import annotations

import unittest

from brightway_flows.domain.context_registry import context_dict_for_iri
from brightway_flows.domain.flow import Flow
from brightway_flows.domain.flow_object import stable_flow_object_id
from brightway_flows.flow_layers import resolve_flow_layers
from brightway_flows.flow_layers.contested_cas import (
    Verdict,
    contested_cas_index,
    load_decisions,
)
from brightway_flows.integrations.ef31 import MANUAL_FIXES_FILEPATH
from brightway_flows.manual_fixes import apply_manual_fixes
from brightway_flows.pipeline.collisions import find_collisions
from brightway_flows.sources import base_source_list

BASE = base_source_list()

CAS = "8006-64-2"
GUM_EC = "932-349-8"
OIL_EC = "232-350-7"

IRI = "https://vocab.brightway.one/flow-contexts/"

#: The six air contexts, where EF names the substance `Gum turpentine`.
AIR = (
    "envi-air-aicrhe",
    "envi-air-grle-ur10pesq",
    "envi-air-hist15me",
    "envi-air-indr-unkn",
    "envi-air-lote",
    "envi-air-unkn",
)

#: The three soils and four waters, where EF names it `turpentine` -- the name
#: its other entry on this number already has.
SOIL_AND_WATER = (
    "envi-grou-agri",
    "envi-grou-noag",
    "envi-grou-unkn",
    "envi-wate-lote",
    "envi-wate-ocea",
    "envi-wate-suwa",
    "envi-wate-unkn",
)

#: EF's own identifiers, so a test that passes is a test about these rows.
GUM_NAMED_GUM = {
    "envi-air-aicrhe": "a89374f9-dfb3-4eca-bf34-6adb8e586e42",
    "envi-air-grle-ur10pesq": "eba02f58-2c1b-4dae-b79e-dea93057ecc5",
    "envi-air-hist15me": "045d3686-b740-47b2-a49f-5c8bd87c586c",
    "envi-air-indr-unkn": "2e9e7630-e156-419d-a07d-8e86877c29f8",
    "envi-air-lote": "2155f649-e56c-4f72-82b2-2bc77a4c259e",
    "envi-air-unkn": "9b44c946-d348-4cd2-ae06-8f40d3c6bd43",
}
GUM_NAMED_TURPENTINE = {
    "envi-grou-agri": "72a04c98-6939-4e89-a1a9-45878da175d7",
    "envi-grou-noag": "aed51cd8-3073-4125-b07b-82d0a4905a51",
    "envi-grou-unkn": "01bc88d7-b8a4-42c1-aa30-8fcd6b179387",
    "envi-wate-lote": "172c4e40-5de9-4622-8a88-ead3e2cebaba",
    "envi-wate-ocea": "296f9e5f-d204-44a8-ac84-d9e14fc5e30b",
    "envi-wate-suwa": "324f18e2-bbb5-428a-a9aa-f7f5b91b5f79",
    "envi-wate-unkn": "588b832c-4adc-4421-b81a-a1816a4157b1",
}
#: The other entry, one row per context, all named `turpentine`.
OIL = {
    "envi-air-aicrhe": "29061455-6556-11dd-ad8b-0800200c9a66",
    "envi-air-grle-ur10pesq": "4d9a8790-3ddd-11dd-8da8-0050c2490048",
    "envi-air-hist15me": "4d9a8790-3ddd-11dd-8da9-0050c2490048",
    "envi-air-indr-unkn": "9d5046f2-b48f-4c5f-87b2-489a8020f43b",
    "envi-air-lote": "4d9a8790-3ddd-11dd-96a2-0050c2490048",
    "envi-air-unkn": "4d9a8790-3ddd-11dd-96a1-0050c2490048",
    "envi-grou-agri": "29061453-6556-11dd-ad8b-0800200c9a66",
    "envi-grou-noag": "29061456-6556-11dd-ad8b-0800200c9a66",
    "envi-grou-unkn": "29061458-6556-11dd-ad8b-0800200c9a66",
    "envi-wate-lote": "2906145a-6556-11dd-ad8b-0800200c9a66",
    "envi-wate-ocea": "29061457-6556-11dd-ad8b-0800200c9a66",
    "envi-wate-suwa": "29061454-6556-11dd-ad8b-0800200c9a66",
    "envi-wate-unkn": "29061459-6556-11dd-ad8b-0800200c9a66",
}

#: EF's freshwater ecotoxicity factors, which are what the `separate` ruling
#: rests on and what a consumer sees two of today.
FACTORS = {
    ("gum", "envi-air-aicrhe"): 0.00074849,
    ("gum", "envi-air-grle-ur10pesq"): 0.0023951,
    ("gum", "envi-air-hist15me"): 0.00074849,
    ("gum", "envi-air-indr-unkn"): 0.0018188,
    ("gum", "envi-air-unkn"): 0.0015718,
    ("gum", "envi-grou-agri"): 1.1619,
    ("gum", "envi-grou-noag"): 1.1619,
    ("gum", "envi-grou-unkn"): 1.1619,
    ("gum", "envi-wate-ocea"): 0.00030382,
    ("gum", "envi-wate-suwa"): 256.29,
    ("gum", "envi-wate-unkn"): 256.29,
    ("oil", "envi-air-aicrhe"): 0.66863,
    ("oil", "envi-air-grle-ur10pesq"): 0.80503,
    ("oil", "envi-air-hist15me"): 0.66863,
    ("oil", "envi-air-indr-unkn"): 0.75729,
    ("oil", "envi-air-unkn"): 0.73683,
    ("oil", "envi-grou-agri"): 8.399,
    ("oil", "envi-grou-noag"): 8.3991,
    ("oil", "envi-grou-unkn"): 8.3991,
    ("oil", "envi-wate-ocea"): 0.074841,
    ("oil", "envi-wate-suwa"): 687.04,
    ("oil", "envi-wate-unkn"): 687.04,
}

GUM_OBJECT = stable_flow_object_id("fo", f"name:gum turpentine|cas:{CAS}")
OIL_OBJECT = stable_flow_object_id("fo", f"name:turpentine|cas:{CAS}")

#: Each slug's context, resolved from the vocabulary rather than written out
#: beside it.  The written-out version disagreed with the IRI it sat next to
#: on nine of the thirteen -- `Ground` rows carrying a `land_use`, an air
#: stratum EF calls `High stack` where the vocabulary says
#: `High stack, >150 meters`, `Water` rows carrying a vertical strata -- and
#: nothing compared the two until `context` became a `Context` (#97).
SLUGS = AIR + SOIL_AND_WATER


def _row(uuid: str, name: str, ec: str, slug: str, entry: str) -> dict:
    context = context_dict_for_iri(f"{IRI}{slug}")
    factor = FACTORS.get((entry, slug))
    return {
        "uuid": uuid,
        "name": name,
        "source": "EF 3.1",
        "context": context,
        "context_iri": f"{IRI}{slug}",
        "unit": "kg",
        "cas_numbers": [CAS],
        "ec_numbers": [ec],
        "lcia_methods": (
            [] if factor is None else
            [{"name": "Ecotoxicity, freshwater", "characterization_factor": factor}]
        ),
    }


def _rows() -> list[dict]:
    """EF 3.1's twenty-six rows for 8006-64-2, as it publishes them."""
    rows = [_row(uuid, "Gum turpentine", GUM_EC, slug, "gum")
            for slug, uuid in GUM_NAMED_GUM.items()]
    rows += [_row(uuid, "turpentine", GUM_EC, slug, "gum")
             for slug, uuid in GUM_NAMED_TURPENTINE.items()]
    rows += [_row(uuid, "turpentine", OIL_EC, slug, "oil")
             for slug, uuid in OIL.items()]
    return rows


def _corrected() -> list[dict]:
    rows = _rows()
    apply_manual_fixes(rows, MANUAL_FIXES_FILEPATH, label="EF 3.1")
    return rows


def _as_flows(rows: list[dict]) -> list[Flow]:
    """Rows as records, labelled the way `bootstrap_labels` labels them.

    The label is derived here rather than written into the row, because that is
    the order the pipeline runs in: `extract` applies the fixes, the transform
    reads the corrected rows back, and only then does a name become a
    `prefLabel`.  A row carrying its own label would carry the uncorrected one
    and the layering would never see the rename.
    """
    return [
        Flow.from_dict({
            **row, "prefLabel": [{"@value": row["name"], "@language": "en"}]
        })
        for row in rows
    ]


def _elementary(rows: list[dict]) -> list:
    _, elementary_flows, _ = resolve_flow_layers(_as_flows(rows), source_list=BASE)
    return elementary_flows


def _objects_by_uuid(rows: list[dict]) -> dict[str, str]:
    return {flow.elementary_flow_id: flow.flow_object_id for flow in _elementary(rows)}


class TheFixRenamesTheSevenTestCase(unittest.TestCase):
    """The correction itself: which rows it touches, and which it must not."""

    def test_the_seven_gum_rows_named_turpentine_are_renamed(self):
        by_uuid = {row["uuid"]: row for row in _corrected()}
        for slug, uuid in GUM_NAMED_TURPENTINE.items():
            with self.subTest(context=slug):
                self.assertEqual(by_uuid[uuid]["name"], "Gum turpentine")

    def test_the_six_already_named_rows_are_unchanged(self):
        by_uuid = {row["uuid"]: row for row in _corrected()}
        for slug, uuid in GUM_NAMED_GUM.items():
            with self.subTest(context=slug):
                self.assertEqual(by_uuid[uuid]["name"], "Gum turpentine")

    def test_the_other_entry_keeps_its_name_in_every_context(self):
        """The EC number in the criterion is what keeps these thirteen still.

        Matching on the name alone would rename the whole of 232-350-7 too,
        which is a different substance as far as this list has ruled.
        """
        by_uuid = {row["uuid"]: row for row in _corrected()}
        for slug, uuid in OIL.items():
            with self.subTest(context=slug):
                self.assertEqual(by_uuid[uuid]["name"], "turpentine")
                self.assertEqual(by_uuid[uuid]["ec_numbers"], [OIL_EC])

    def test_applying_twice_changes_nothing_further(self):
        """The base list has its fixes applied twice, at extract and at read (#237)."""
        rows = _corrected()
        once = [dict(row) for row in rows]
        apply_manual_fixes(rows, MANUAL_FIXES_FILEPATH, label="EF 3.1")
        self.assertEqual(rows, once)


class TheThirteenBecomeOneSeriesTestCase(unittest.TestCase):
    """What the rename buys, asserted against the published identifiers."""

    def test_uncorrected_the_series_is_split_across_two_objects(self):
        """The defect, so that the assertions below cannot pass vacuously."""
        resolved = _objects_by_uuid(_rows())
        self.assertEqual(
            {resolved[uuid] for uuid in GUM_NAMED_GUM.values()}, {GUM_OBJECT}
        )
        self.assertEqual(
            {resolved[uuid] for uuid in GUM_NAMED_TURPENTINE.values()}, {OIL_OBJECT}
        )

    def test_corrected_all_thirteen_share_the_gum_turpentine_object(self):
        resolved = _objects_by_uuid(_corrected())
        uuids = [*GUM_NAMED_GUM.values(), *GUM_NAMED_TURPENTINE.values()]
        self.assertEqual({resolved[uuid] for uuid in uuids}, {GUM_OBJECT})

    def test_the_other_entry_keeps_its_own_object(self):
        resolved = _objects_by_uuid(_corrected())
        self.assertEqual({resolved[uuid] for uuid in OIL.values()}, {OIL_OBJECT})

    def test_each_object_holds_thirteen_contexts_once_each(self):
        """One row per context on each side is the shape that says these are
        two complete series rather than one series and a remainder."""
        flows = _elementary(_corrected())
        for object_id in (GUM_OBJECT, OIL_OBJECT):
            contexts = [f.context_iri for f in flows if f.flow_object_id == object_id]
            with self.subTest(flow_object=object_id):
                self.assertEqual(len(contexts), 13)
                self.assertEqual(len(set(contexts)), 13)


class NoContextHoldsTwoLiveFlowsTestCase(unittest.TestCase):
    """The published defect, read through the guard that reports it (#271)."""

    def test_uncorrected_seven_contexts_collide(self):
        groups = find_collisions(_elementary(_rows()))
        self.assertEqual(len(groups), 7)
        colliding = {flow.context_iri for group in groups for flow in group}
        self.assertEqual(
            colliding, {f"{IRI}{slug}" for slug in GUM_NAMED_TURPENTINE}
        )

    def test_the_colliding_flows_disagree_about_the_numbers(self):
        """What makes the collision matter: not two spellings of one value."""
        groups = find_collisions(_elementary(_rows()))
        by_context = {group[0].context_iri: group for group in groups}
        sea = by_context[f"{IRI}envi-wate-ocea"]
        self.assertEqual(
            sorted(m.amount for f in sea for m in f.lcia_methods),
            [0.00030382, 0.074841],
        )

    def test_corrected_nothing_collides(self):
        self.assertEqual(find_collisions(_elementary(_corrected())), [])


class TheContestedNumberIsStillSeparateTestCase(unittest.TestCase):
    """The rename must not dissolve the ruling that keeps the two entries apart.

    `contested-cas-decisions.json` rules 8006-64-2 `separate` on air factors of
    7.5e-4 against 0.67 -- rows this correction does not touch.  Both names
    still exist afterwards, so the ruling still describes the data it was
    written about.
    """

    def _verdict(self, rows: list[dict]):
        index = contested_cas_index(_as_flows(rows), decisions=load_decisions())
        return index[CAS]

    def test_the_ruling_still_applies_after_the_rename(self):
        verdict = self._verdict(_corrected())
        self.assertIs(verdict.verdict, Verdict.SEPARATE)
        self.assertEqual(verdict.decided_by, self._verdict(_rows()).decided_by)

    def test_both_names_still_claim_the_number(self):
        """A ruling names the names it was written about, and warns if they
        have changed.  These are the two it names."""
        self.assertEqual(
            self._verdict(_corrected()).names, ("gum turpentine", "turpentine")
        )


if __name__ == "__main__":
    unittest.main()
