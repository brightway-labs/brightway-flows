"""What the geography split must and must not do, pinned before it moves.

Phase 0 of `plans/simapro-row-preparation.md` (#192).  The split is today a
feature of BAFU's extractor; the plan makes it a load step for AGRIBALYSE the
way the unit split already is for every SimaPro-shaped list.  Two families of
facts have to hold before, during and after that change:

- **Identity is the extraction's and nobody else's.**  A load step rewrites
  the name a row goes forward under; the uuid the extraction derived is what
  every curated table is keyed on, and a load step that touched one would
  invalidate 201 land classes, 1,047 water materials and the match overrides
  in one silent stroke.
- **The whitelist is what keeps the splitter honest.**  The vendor's own file
  ships the proof: `Particulates, SPM` is code-shaped, `SPM` is even a valid
  ISO alpha-3 (Saint-Pierre-et-Miquelon), and the row is suspended
  particulate matter (#190 group J).  Only a base-label whitelist keeps a
  place-reader off it.

The inventory counts are measured against the vendor extraction, which is
deterministic for a given release, so they are exact rather than build-bound.
"""

from __future__ import annotations

import unittest

import orjson

from brightway_flows.simapro_names import (
    GEOGRAPHY_BASE_LABELS,
    split_geography_suffix,
)
from brightway_flows.sources import known_source_lists


def _extracted(key: str) -> list[dict]:
    source = known_source_lists()[key]
    if not source.flows_path.exists():
        raise unittest.SkipTest(f"{key} is not extracted here")
    return orjson.loads(source.flows_path.read_bytes())


class TheInventoryTestCase(unittest.TestCase):
    """How many rows of each list carry a place in the name, exactly.

    Pinned so that phase 2's build diff has a number to be checked against,
    and so that a vendor release or a whitelist change that moves the
    population is a visible event rather than a drifting count.
    """

    def test_agribalyse_ships_708_rows_the_whitelist_reads(self):
        """546 over 14 bases before phase 2 widened the whitelist; 708 over
        20 once the sulfur dioxide, ammonia, nitrate, nitrogen monoxide,
        phosphorus and turbine-use bases and the thirteen custom geographies
        joined. The three code-shaped rows deliberately left over are the
        BOD5/COD spellings #187 places by synonym."""
        rows = [r for r in _extracted("agribalyse-3.2") if split_geography_suffix(r["name"])]
        self.assertEqual(len(rows), 708)
        bases = {split_geography_suffix(r["name"])[0].casefold() for r in rows}
        self.assertEqual(len(bases), 20)
        self.assertTrue(bases <= GEOGRAPHY_BASE_LABELS)

    def test_stepwise_and_bafu_ship_none(self):
        """Stepwise genuinely ships no regionalised name; BAFU ships none
        *in its extraction* because its extractor has already split them --
        which is why `geography_split: "extraction"` stays its answer."""
        for key in ("stepwise-2006-1.09", "bafu-2026-v1"):
            with self.subTest(key=key):
                rows = [r for r in _extracted(key) if split_geography_suffix(r["name"])]
                self.assertEqual(rows, [])

    def test_the_splitter_never_fires_on_suspended_particulate_matter(self):
        """The guard row, by name: whatever the whitelist gains, this stays."""
        self.assertIsNone(split_geography_suffix("Particulates, SPM"))


class IdentityIsTheExtractionsTestCase(unittest.TestCase):
    """`load_flows` may rewrite names; it must never rewrite a uuid.

    True today by construction; pinned because phase 2 puts a renaming step
    into `load_flows` and this is the invariant that makes that safe.
    """

    def test_loaded_uuids_are_the_files_uuids_for_every_simapro_list(self):
        """Loading may *remove* a uuid (an excluded row, per that list's
        additional-flows file) and may *add* one that file declares; it may
        never produce a uuid neither file carries, because a renaming step
        that also re-derived identity would do exactly that."""
        for key, source in sorted(known_source_lists().items()):
            if not source.simapro_origin:
                continue
            if not source.flows_path.exists():
                continue
            with self.subTest(key=key):
                shipped = {row["uuid"] for row in orjson.loads(source.flows_path.read_bytes())}
                declared = set(shipped)
                if source.additional_flows_path is not None:
                    payload = orjson.loads(source.additional_flows_path.read_bytes())
                    declared |= {row["uuid"] for row in payload.get("flows", [])}
                loaded = {flow.uuid for flow in source.load_flows()}
                self.assertEqual(loaded - declared, set())


class GeographySplitConfigTestCase(unittest.TestCase):
    """Which stage splits is the manifest's word, one word per list (#192).

    Phase 1 of the plan: the knob exists and BAFU's manifest states the
    behaviour its extractor always had; no manifest says ``"load"`` yet, so a
    build's output is unchanged to the byte -- that is this phase's whole
    claim, and `verify_run.py` is what checks it.
    """

    def test_bafu_declares_the_split_its_uuids_bake_in(self):
        self.assertEqual(
            known_source_lists()["bafu-2026-v1"].geography_split, "extraction"
        )

    def test_each_list_splits_at_exactly_the_stage_its_manifest_says(self):
        """Phase 2: AGRIBALYSE joins at load; nothing else splits in a build.
        Stepwise stays off because it ships not one regionalised name, and a
        release that starts shipping them flips the manifest, not code."""
        stages = {
            key: source.geography_split
            for key, source in known_source_lists().items()
            if source.geography_split
        }
        self.assertEqual(
            stages,
            {"bafu-2026-v1": "extraction", "agribalyse-3.2": "load"},
        )

    def test_a_block_on_a_list_simapro_did_not_shape_is_refused(self):
        from brightway_flows.sources import SourceList

        with self.assertRaises(ValueError):
            SourceList.from_manifest(
                {
                    "list_name": "x", "list_version": "1", "role": "source",
                    "merge_priority": 1, "flow_iri_prefix": "https://x/",
                    "inputs": {"flows": "x.json"},
                    "simapro": {"geography_split": "load"},
                },
                path=__import__("pathlib").Path("x.json"),
            )

    def test_a_misspelled_stage_is_refused_by_name(self):
        from brightway_flows.sources import SourceList

        for block in ({"geography_split": "adapter"}, {"geography": "load"}):
            with self.subTest(block=block), self.assertRaises(ValueError):
                SourceList.from_manifest(
                    {
                        "list_name": "x", "list_version": "1", "role": "source",
                        "merge_priority": 1, "simapro_origin": True,
                        "flow_iri_prefix": "https://x/",
                        "inputs": {"flows": "x.json"},
                        "simapro": block,
                    },
                    path=__import__("pathlib").Path("x.json"),
                )


class LoadStageSplitTestCase(unittest.TestCase):
    """The helper itself, against rows shaped the way the adapters ship them.

    Unused by any manifest in phase 1; phase 2 points AGRIBALYSE at it.
    """

    def _split(self, rows):
        from brightway_flows.sources import SourceList

        source = SourceList(
            list_name="x", list_version="1", flows_path=__import__("pathlib").Path("x.json"),
            simapro_origin=True, geography_split="load",
        )
        source._split_geography_suffixes(rows)
        return rows

    def test_a_whitelisted_base_loses_its_place_and_keeps_its_identity(self):
        (row,) = self._split([{"uuid": "u-1", "name": "Water, AE", "unit": "m3"}])
        self.assertEqual(row["name"], "Water")
        self.assertEqual(row["location"], "AE")
        self.assertEqual(row["original_name"], "Water, AE")
        self.assertEqual(row["uuid"], "u-1")

    def test_the_shipped_spelling_stays_a_name_the_row_answers_to(self):
        """The decision of 2026-09-01: a third party matching `Phosphorus,
        CN` against us must still land, so the spelling joins the synonyms
        the merge reads."""
        (row,) = self._split([{"uuid": "u-1", "name": "Water, AE", "unit": "m3"}])
        self.assertIn("Water, AE", row["synonyms"])

    def test_a_withdrawn_code_is_recorded_as_its_successor(self):
        (row,) = self._split([{"uuid": "u-1", "name": "Water, CS", "unit": "m3"}])
        self.assertEqual(row["location"], "RS")
        self.assertEqual(row["original_name"], "Water, CS")

    def test_an_unwhitelisted_base_and_a_non_code_keep_their_names(self):
        rows = self._split([
            {"uuid": "u-1", "name": "Particulates, SPM", "unit": "kg"},
            {"uuid": "u-2", "name": "Water, cooling", "unit": "m3"},
        ])
        for row in rows:
            with self.subTest(name=row["name"]):
                self.assertNotIn("location", row)
                self.assertNotIn("original_name", row)

    def test_applying_twice_changes_nothing_further(self):
        rows = [{"uuid": "u-1", "name": "Water, AE", "unit": "m3"}]
        self._split(rows)
        once = orjson.dumps(rows)
        self._split(rows)
        self.assertEqual(orjson.dumps(rows), once)

    def test_the_record_still_says_the_vendor_wrote_the_coded_name(self):
        """A consumer holding the vendor's inventory has `Phosphorus, CN` and
        no other string (decided 2026-09-01), and the split keeps that string
        on two channels without giving it back to the matcher's own label
        set: `original_name` rides into `flow.extra`, where the merge reads
        it for `shipped_name` -- the name a published mapping records and the
        member-name pass offers the landed substance -- and the row's
        synonyms, so the coded spelling still finds candidates. `provided.name`
        stays the base, which is what keeps
        `test_the_place_is_not_a_label_the_matcher_can_reach`'s guarantee for
        rows that gain no synonym (BAFU's)."""
        from brightway_flows.domain.flow import Flow
        from brightway_flows.pipeline.loading import _normalize_input_flow_record

        (row,) = self._split([{"uuid": "u-1", "name": "Phosphorus, CN", "unit": "kg"}])
        self.assertEqual(row["name"], "Phosphorus")
        flow = Flow.from_dict(_normalize_input_flow_record(row, source_hint="x"))
        self.assertEqual(flow.provided.name, "Phosphorus")
        self.assertEqual(flow.extra["original_name"], "Phosphorus, CN")
        self.assertIn("Phosphorus, CN", flow.provided.synonyms)


if __name__ == "__main__":
    unittest.main()
