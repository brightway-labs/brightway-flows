"""The committed fixture is a real export, and it says what #209 said.

`tests/data/unit-process-scores-ecoinvent-3.8-apos-fixture.json.gz` was cut
from the 501-unit-process export of ecoinvent 3.8 APOS on 2026-08-25 with
`tools/export_unit_process_scores.py --only-codes …`: the Swedish wind
activity the comparison was diagnosed on, an APOS by-product with no
inventory at all, and a small waste-treatment activity.  It is the artifact
the comparison's tests read, so two things are pinned here: that it loads
through the same gate a real export does, and that the wind activity's EF v3.0
scores are the ones quoted in the issue, to six significant figures.  If
brightway or ecoinvent's LCIA implementation ever changes them, this is where
it shows.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from brightway_flows.domain.lcia.unit_process_scores import (
    load_score_artifact,
    write_score_artifact,
)

FIXTURE = (
    Path(__file__).resolve().parent / "data"
    / "unit-process-scores-ecoinvent-3.8-apos-fixture.json.gz"
)
WIND_SE = "b09e51ef9d976bc64905c74fd99842fc"
HARD_COAL_ASH = "4833c3968459fb9e6744c3dd74f66419"

#: The hand analysis's first table, the `bw2 (EF 3.0)` column.
ISSUE_79 = {
    "EF v3.0|climate change|global warming potential (GWP100)": 0.0277654,
    "EF v3.0|energy resources: non-renewable|abiotic depletion potential (ADP): fossil fuels": 0.30979,
    "EF v3.0|water use|user deprivation potential (deprivation-weighted water consumption)": 0.0120774,
    "EF v3.0|ecotoxicity: freshwater|comparative toxic unit for ecosystems (CTUe)": 2.50632,
    "EF v3.0|human toxicity: carcinogenic|comparative toxic unit for human (CTUh)": 1.22227e-10,
    "EF v3.0|particulate matter formation|impact on human health": 3.01204e-09,
    "EF v3.0|ionising radiation: human health|human exposure efficiency relative to u235": 0.00216732,
    "EF v3.0|land use|soil quality index": 0.325109,
    "EF v3.0|acidification|accumulated exceedance (ae)": 3.24392e-04,
}


class FixtureTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.artifact = load_score_artifact(FIXTURE)

    def test_it_is_the_release_it_says(self):
        release = self.artifact.release
        self.assertEqual(release.key, "ecoinvent-3.8-apos")
        self.assertEqual(release.method_family, "EF v3.0")
        self.assertEqual(len(self.artifact.categories), 28)
        self.assertEqual(len(self.artifact.unit_processes), 3)

    def test_the_wind_activity_scores_as_the_issue_says(self):
        wind = next(u for u in self.artifact.unit_processes if u.activity_code == WIND_SE)
        self.assertEqual(wind.geography, "SE")
        self.assertEqual(wind.reference_product, "electricity, high voltage")
        for key, quoted in ISSUE_79.items():
            with self.subTest(category=key.split("|")[1]):
                self.assertAlmostEqual(wind.scores[key] / quoted, 1.0, places=5)

    def test_a_by_product_with_no_inventory_scores_zero(self):
        ash = next(u for u in self.artifact.unit_processes if u.activity_code == HARD_COAL_ASH)
        self.assertEqual(ash.inventory, [])
        self.assertEqual(ash.product_amount, -1.0)
        self.assertEqual(set(ash.scores.values()), {0.0})

    def test_every_factor_is_on_a_flow_the_sample_emits(self):
        emitted = {line.source_flow_uuid for u in self.artifact.unit_processes for line in u.inventory}
        self.assertEqual({f.source_flow_uuid for f in self.artifact.flows}, emitted)
        self.assertTrue(all(f.source_flow_uuid in emitted for f in self.artifact.factors))

    def test_gzipped_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_score_artifact(self.artifact, Path(tmp) / "copy.json.gz")
            self.assertEqual(load_score_artifact(path), self.artifact)
