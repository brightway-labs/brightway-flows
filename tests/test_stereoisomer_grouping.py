"""Regression tests for stereoisomer flow-object separation.

The motivating case: δ-Hexachlorocyclohexane (UUID 25622e54-…) and
β-Hexachlorocyclohexane (UUID 08a91e70-…) are distinct substances that carry
different CAS numbers (319-86-8 and 319-85-7 respectively).  An upstream
PubChem transformer can rename both to a common parent name
"Hexachlorocyclohexane", after which the name-based lookup in
resolve_flow_layers would incorrectly merge them into one flow object.

The fix adds a CAS-disjoint guard: a name-only match against a candidate
object that already owns disjoint CAS numbers is rejected, and a new object
is created for the incoming flow.
"""

from __future__ import annotations

import unittest

from brightway_flows.domain.flow import Flow
from brightway_flows.flow_layers import resolve_flow_layers
from brightway_flows.pipeline import has_stereo_descriptor
from brightway_flows.sources import base_source_list

#: `resolve_flow_layers` asks which list its flows came from rather than
#: reading it off `flow.source`, and these are the base list's rows (#13).
BASE = base_source_list()


def _as_flows(rows):
    """resolve_flow_layers takes Flow records; tests still author dicts."""
    return [Flow.from_dict(r) for r in rows]



# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_AIR_CTX = {"dimension": "Environmental", "media": "Air", "strata": "Ground level",
             "population_density": "Urban (>1000 people/square mile)"}
_WATER_CTX = {"dimension": "Environmental", "media": "Water", "water_body": "River"}


def _flow(uuid: str, name: str, cas: list[str], context: dict | None = None) -> dict:
    return {
        "uuid": uuid,
        "prefLabel": [{"@value": name, "@language": "en"}],
        "source": "EF 3.1",
        "context": context or _AIR_CTX,
        "cas_numbers": cas,
    }


# ---------------------------------------------------------------------------
# CAS-disjoint name-match guard
# ---------------------------------------------------------------------------

class StereoisomerSeparationTestCase(unittest.TestCase):
    """β-HCH and δ-HCH must not share a flow object."""

    def _run(self, name_a: str, name_b: str) -> tuple[list, list, dict]:
        flows = [
            _flow("08a91e70-3ddc-11dd-9481-0050c2490048", name_a, ["319-85-7"]),
            _flow("25622e54-b11d-4992-92f7-5b8a45919f4e", name_b, ["319-86-8"]),
        ]
        return resolve_flow_layers(_as_flows(flows), source_list=BASE)

    def test_distinct_names_produce_separate_objects(self):
        """Different stereo names → different flow objects (baseline)."""
        flow_objects, elementary_flows, stats = self._run(
            "beta-1,2,3,4,5,6-hexachlorocyclohexane",
            "(1α,2α,3α,4β,5α,6β)-1,2,3,4,5,6-hexachlorocyclohexane",
        )
        self.assertEqual(stats["flow_object_count"], 2)
        foids = {ef.flow_object_id for ef in elementary_flows}
        self.assertEqual(len(foids), 2)

    def test_same_name_different_cas_produces_separate_objects(self):
        """After upstream rename to bare parent name, CAS-disjoint guard fires."""
        # This is the exact failure mode: both stereoisomers have been renamed
        # to the same generic parent name by a PubChem transformer.
        flow_objects, elementary_flows, stats = self._run(
            "Hexachlorocyclohexane",
            "Hexachlorocyclohexane",
        )
        self.assertEqual(
            stats["flow_object_count"], 2,
            "Stereoisomers with disjoint CAS numbers must not share a flow object "
            "even when their names are identical after upstream normalisation.",
        )
        foids = {ef.flow_object_id for ef in elementary_flows}
        self.assertEqual(len(foids), 2)

    def test_same_cas_same_name_merges(self):
        """Same substance across two sources still produces a single flow object."""
        flows = [
            _flow("u1", "Hexachlorocyclohexane", ["319-85-7"], _AIR_CTX),
            _flow("u2", "hexachlorocyclohexane", ["319-85-7"], _WATER_CTX),
        ]
        flow_objects, elementary_flows, stats = resolve_flow_layers(_as_flows(flows), source_list=BASE)
        self.assertEqual(stats["flow_object_count"], 1)
        self.assertEqual(len({ef.flow_object_id for ef in elementary_flows}), 1)

    def test_no_cas_same_name_merges(self):
        """Flows without CAS numbers that share a name still merge (no guard fires)."""
        flows = [
            _flow("u1", "Hexachlorocyclohexane", [], _AIR_CTX),
            _flow("u2", "Hexachlorocyclohexane", [], _WATER_CTX),
        ]
        flow_objects, elementary_flows, stats = resolve_flow_layers(_as_flows(flows), source_list=BASE)
        self.assertEqual(stats["flow_object_count"], 1)

    def test_three_isomers_all_separate(self):
        """α-, β-, and δ-HCH all get distinct flow objects when names collide."""
        flows = [
            _flow("uuid-alpha", "Hexachlorocyclohexane", ["319-84-6"], _AIR_CTX),
            _flow("uuid-beta",  "Hexachlorocyclohexane", ["319-85-7"], _AIR_CTX),
            _flow("uuid-delta", "Hexachlorocyclohexane", ["319-86-8"], _AIR_CTX),
        ]
        flow_objects, elementary_flows, stats = resolve_flow_layers(_as_flows(flows), source_list=BASE)
        self.assertEqual(stats["flow_object_count"], 3)
        foids = {ef.flow_object_id for ef in elementary_flows}
        self.assertEqual(len(foids), 3)


# ---------------------------------------------------------------------------
# has_stereo_descriptor helper
# ---------------------------------------------------------------------------

class HasSteroDescriptorTestCase(unittest.TestCase):
    def test_greek_letter_beta(self):
        self.assertTrue(has_stereo_descriptor("beta-1,2,3,4,5,6-hexachlorocyclohexane"))

    def test_greek_unicode_alpha(self):
        self.assertTrue(has_stereo_descriptor("(1α,2α,3α,4β,5α,6β)-1,2,3,4,5,6-hexachlorocyclohexane"))

    def test_cis_prefix(self):
        self.assertTrue(has_stereo_descriptor("cis-1,2-dichloroethylene"))

    def test_trans_prefix(self):
        self.assertTrue(has_stereo_descriptor("trans-2-butene"))

    def test_alpha_prefix(self):
        self.assertTrue(has_stereo_descriptor("alpha-Cypermethrin"))

    def test_delta_prefix(self):
        self.assertTrue(has_stereo_descriptor("delta-Hexachlorocyclohexane"))

    def test_plain_name_no_descriptor(self):
        self.assertFalse(has_stereo_descriptor("Hexachlorocyclohexane"))

    def test_benzene_no_descriptor(self):
        self.assertFalse(has_stereo_descriptor("Benzene"))

    def test_carbon_dioxide_no_descriptor(self):
        self.assertFalse(has_stereo_descriptor("Carbon dioxide"))


if __name__ == "__main__":
    unittest.main()
