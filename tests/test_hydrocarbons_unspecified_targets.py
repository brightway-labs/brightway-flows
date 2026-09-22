"""`Hydrocarbons, unspecified` and `hydrocarbons (unspecified)` are one bucket.

#178.  EF 3.1 spells the catch-all with brackets, ecoinvent and BAFU with a
comma, and no row on any list carries a registry number, so the name is the
only evidence.  Two ecoinvent rows the vendor's table omits and five BAFU rows
minted a second bucket whose name differed from EF's only in punctuation.

The fix is seven curated targets -- two in `ecoinvent-match-overrides.json`,
five in `bafu-2026-v1-match-overrides.json` -- every one onto a flow of EF's
own substance.  A synonym on EF's rows was tried first and cannot work:
`bootstrap_labels` deletes a base-list row's synonyms before the merge builds
the label index, which is tested here so that the reason does not have to be
rediscovered.

Three halves, then.  The seven rows are curated onto the bucket, in the
contexts EF has and onto its fresh-water flow where EF has no lake or river.
The seven rows the vendor's table already decides are not touched.  And the
synonym route really is closed.
"""

from __future__ import annotations

import unittest

from brightway_flows.domain.flow import Flow
from brightway_flows.filesystem import PACKAGE_DATA_DIR
from brightway_flows.match_overrides import apply_match_overrides, load_match_overrides
from brightway_flows.transformers.bootstrap_labels import BootstrapLabelsTransformer

ECOINVENT = PACKAGE_DATA_DIR / "ecoinvent-match-overrides.json"
BAFU = PACKAGE_DATA_DIR / "bafu-2026-v1-match-overrides.json"

#: EF's `hydrocarbons (unspecified)` flows, by the context they sit in.
EF = {
    "air, unspecified": "d86b9e8a-6555-11dd-ad8b-0800200c9a66",
    "agricultural soil": "d86b9e73-6555-11dd-ad8b-0800200c9a66",
    "water, unspecified": "fe0acd60-3ddc-11dd-aaa8-0050c2490048",
    "sea water": "fe0acd60-3ddc-11dd-aaa9-0050c2490048",
    "fresh water": "fe0acd60-3ddc-11dd-aaa6-0050c2490048",
}
BUCKET_FLOWS = set(EF.values()) | {
    "d86bc59b-6555-11dd-ad8b-0800200c9a66", "d86c3aa9-6555-11dd-ad8b-0800200c9a66",
    "7167805e-8819-4b84-b6ef-e65f719a9818", "d86b9e90-6555-11dd-ad8b-0800200c9a66",
    "d86becae-6555-11dd-ad8b-0800200c9a66", "d86bec97-6555-11dd-ad8b-0800200c9a66",
    "d86c13bc-6555-11dd-ad8b-0800200c9a66", "fe0acd60-3ddc-11dd-aaa7-0050c2490048",
}

ECOINVENT_ROWS = {
    "3fdc4e95-dc17-5f9f-9ddc-251ecd7c66c0": EF["air, unspecified"],
    "614d5544-9edf-5b76-90e8-e9c7b98a8084": EF["agricultural soil"],
}
BAFU_ROWS = {
    "3a47b869-9ac2-5e24-b6cd-d695188a0cb7": EF["air, unspecified"],
    "3b50226c-c9ab-5cbf-9af7-2da71da1e042": EF["water, unspecified"],
    "612a6cef-d1e7-524d-a3c3-c664e7c20e51": EF["sea water"],
    "21aa7a0c-606f-5d29-b960-a50c2f5bc0dd": EF["fresh water"],  # lake
    "83944839-e21a-5c7d-92c0-70ee8dbc60a4": EF["fresh water"],  # river
}
#: The seven ecoinvent rows the vendor's table decided, carried into the
#: overrides file when the tables were retired (#141).  They were right before
#: this change and must stay right: all nine rows on one substance is the claim.
CARRIED_FROM_THE_TABLE = {
    "49c42751-1b0b-4ab1-8e70-032e991ce6fd", "049a1473-3a62-4121-982b-5d15d0f2c683",
    "5e08c84c-69a2-4f0b-b3b3-6b7f0925712b", "f9abb851-8731-4c5b-b057-863996a1f94a",
    "e620a933-c348-4e7e-8893-ab0a0f681c7e", "042e5892-cd59-4e95-949e-cacce0e6a590",
    "9d508263-9cfd-444a-b1de-73f2bcf39c02",
}


def _by_source(path):
    return {o.source_uuid: o for o in load_match_overrides(path)}


class TheSevenRowsAreCuratedTestCase(unittest.TestCase):
    def test_ecoinvents_two_omitted_rows_target_the_bucket_in_their_own_context(self):
        rows = _by_source(ECOINVENT)
        for uuid, target in ECOINVENT_ROWS.items():
            with self.subTest(uuid=uuid):
                self.assertEqual(rows[uuid].target_uuid, target)

    def test_bafus_five_rows_target_the_bucket(self):
        rows = _by_source(BAFU)
        for uuid, target in BAFU_ROWS.items():
            with self.subTest(uuid=uuid):
                self.assertEqual(rows[uuid].target_uuid, target)
                self.assertIn(rows[uuid].target_uuid, BUCKET_FLOWS)

    def test_the_seven_rows_carried_from_the_table_still_target_the_bucket(self):
        rows = _by_source(ECOINVENT)
        for uuid in CARRIED_FROM_THE_TABLE:
            with self.subTest(uuid=uuid):
                self.assertIn(rows[uuid].target_uuid, BUCKET_FLOWS)

    def test_bafus_rows_are_appended_to_its_empty_table(self):
        """BAFU declares no correspondence table, so every override is appended."""
        appended = {
            str(row["source"]["uuid"]): str(row["target"]["uuid"])
            for row in apply_match_overrides([], BAFU)
        }
        for uuid, target in BAFU_ROWS.items():
            with self.subTest(uuid=uuid):
                self.assertEqual(appended.get(uuid), target)


class TheSynonymRouteIsClosedTestCase(unittest.TestCase):
    """Why the fix is seven targets and not one synonym.

    The first attempt wrote `Hydrocarbons, unspecified` as a synonym on EF's
    rows in `ef-3.1-manual-fixes.json`.  Measured on a full build of
    2026-08-30 at 53c2165, no row moved: `bootstrap_labels` records
    `["Hydrocarbons, unspecified"] -> []` in the changelog, and the merge's
    label index is built from the objects' prefLabel and altLabel afterwards.
    """

    def test_bootstrap_labels_drops_a_base_list_rows_synonyms(self):
        flow = Flow(
            uuid="d86b9e8a-6555-11dd-ad8b-0800200c9a66",
            name="hydrocarbons (unspecified)",
            synonyms=["Hydrocarbons, unspecified"],
        )
        changes = BootstrapLabelsTransformer().transform([flow])
        synonyms = [c for c in changes if c.field == "synonyms"]
        self.assertEqual(len(synonyms), 1)
        self.assertEqual(synonyms[0].new_value, [])
        self.assertFalse(
            [c for c in changes if c.field == "altLabel"],
            "a synonym is dropped, not carried onto the labels the merge indexes",
        )


if __name__ == "__main__":
    unittest.main()
