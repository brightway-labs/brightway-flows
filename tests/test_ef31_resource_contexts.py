"""
Tests that EF 3.1 material resource categories map to resource (reso-*) contexts,
and that natural gas and coal mine off-gas resolve to separate flow objects.
"""

import unittest

from brightway_flows.domain.flow import Flow
from brightway_flows.flow_layers import resolve_flow_layers
from brightway_flows.transformers.default_context_mapping import (
    DefaultContextMappingTransformer,
)
from brightway_flows.sources import base_source_list

#: `resolve_flow_layers` asks which list its flows came from rather than
#: reading it off `flow.source`, and these are the base list's rows (#13).
BASE = base_source_list()


def _as_flows(rows):
    """resolve_flow_layers takes Flow records; tests still author dicts."""
    return [Flow.from_dict(r) for r in rows]

# EF 3.1 source UUIDs for the two flows that used to be incorrectly merged.
_NATURAL_GAS_UUID = "fe0acd60-3ddc-11dd-a6fa-0050c2490048"
_COAL_MINE_OFFGAS_UUID = "00fdc4bc-724b-4993-ad43-c70df533b092"

# Expected flow object IDs from flow-object-overrides.json.
_NATURAL_GAS_FO_ID = "fo-634eaeddc2496342"
_COAL_MINE_FO_ID = "fo-eb9073f83e17ec30"

# All EF 3.1 material resource categories that must land on reso-* IRIs.
_MATERIAL_RESOURCE_CASES = [
    (
        ["Resources", "Resources from air", "Renewable material resources from air"],
        "https://vocab.brightway.one/flow-contexts/reso-air",
    ),
    (
        ["Resources", "Resources from biosphere", "Renewable material resources from biosphere"],
        "https://vocab.brightway.one/flow-contexts/reso-biot",
    ),
    (
        ["Resources", "Resources from ground", "Non-renewable material resources from ground"],
        "https://vocab.brightway.one/flow-contexts/reso-grou",
    ),
    (
        ["Resources", "Resources from ground", "Renewable material resources from ground"],
        "https://vocab.brightway.one/flow-contexts/reso-grou",
    ),
    (
        ["Resources", "Resources from water", "Non-renewable material resources from water"],
        "https://vocab.brightway.one/flow-contexts/reso-wate",
    ),
    (
        ["Resources", "Resources from water", "Renewable material resources from water"],
        "https://vocab.brightway.one/flow-contexts/reso-wate",
    ),
]


class EF31ResourceContextMappingTest(unittest.TestCase):
    """DefaultContextMappingTransformer maps all EF 3.1 material resources to reso-* IRIs."""

    def setUp(self):
        self.transformer = DefaultContextMappingTransformer()
        self.transformer.setup()

    def _run(self, source_context: list[str]) -> str | None:
        """Return the context_iri change value for a single EF 3.1 flow."""
        flow = Flow.from_dict({
            "uuid": "test-uuid",
            "source": "EF 3.1",
            # Not a declared field, so it round-trips through Flow.extra.
            "elementary_flow_categorization": source_context,
        })
        changes = self.transformer.transform([flow])
        iri_changes = [c for c in changes if c.field == "context_iri"]
        return iri_changes[0].new_value if iri_changes else None

    def test_material_resources_all_map_to_resource_context(self):
        for source_context, expected_iri in _MATERIAL_RESOURCE_CASES:
            with self.subTest(category=source_context[-1]):
                result = self._run(source_context)
                self.assertEqual(
                    result,
                    expected_iri,
                    msg=f"{source_context[-1]!r} mapped to {result!r}, expected {expected_iri!r}",
                )

    def test_material_resources_never_map_to_environmental(self):
        for source_context, _ in _MATERIAL_RESOURCE_CASES:
            with self.subTest(category=source_context[-1]):
                result = self._run(source_context)
                self.assertIsNotNone(result)
                assert result is not None
                self.assertFalse(
                    result.split("/")[-1].startswith("envi-"),
                    msg=f"{source_context[-1]!r} incorrectly mapped to environmental IRI {result!r}",
                )

    def test_energy_resource_categories_still_map_to_reso(self):
        energy_cases = [
            ["Resources", "Resources from ground", "Non-renewable energy resources from ground"],
            ["Resources", "Resources from ground", "Renewable energy resources from ground"],
            ["Resources", "Resources from water", "Renewable energy resources from water"],
            ["Resources", "Resources from biosphere", "Renewable energy resources from biosphere"],
        ]
        for source_context in energy_cases:
            with self.subTest(category=source_context[-1]):
                result = self._run(source_context)
                self.assertIsNotNone(result)
                assert result is not None
                self.assertTrue(
                    result.split("/")[-1].startswith("reso-"),
                    msg=f"{source_context[-1]!r} mapped to {result!r}",
                )


class NaturalGasCoalMineOffgasSplitTest(unittest.TestCase):
    """Natural gas and coal mine off-gas must resolve to separate flow objects."""

    def _make_flows(self):
        # Both flows are primarily methane (CAS 74-82-8), which is why the
        # resolver would otherwise merge them into one flow object.
        return [
            {
                "uuid": _NATURAL_GAS_UUID,
                "name": "natural gas",
                "source": "EF 3.1",
                "context": {"dimension": "Resource", "media": "Ground"},
                "cas_numbers": ["74-82-8"],
            },
            {
                "uuid": _COAL_MINE_OFFGAS_UUID,
                "name": "Gas, mine, off-gas, process, coal mining",
                "source": "EF 3.1",
                "context": {"dimension": "Environmental", "media": "Ground", "geography": "Unknown"},
                "cas_numbers": ["74-82-8"],
            },
        ]

    def test_natural_gas_gets_own_flow_object(self):
        _, _, stats = resolve_flow_layers(_as_flows(self._make_flows()), source_list=BASE)
        self.assertEqual(stats["flow_object_count"], 2, "expected two separate flow objects")

    def test_natural_gas_uuid_maps_to_correct_flow_object(self):
        _, elementary_flows, _ = resolve_flow_layers(_as_flows(self._make_flows()), source_list=BASE)
        ng_ef = next(ef for ef in elementary_flows if ef.source_refs[0]["source_flow_uuid"] == _NATURAL_GAS_UUID)
        self.assertEqual(ng_ef.flow_object_id, _NATURAL_GAS_FO_ID)

    def test_coal_mine_offgas_uuid_maps_to_correct_flow_object(self):
        _, elementary_flows, _ = resolve_flow_layers(_as_flows(self._make_flows()), source_list=BASE)
        cog_ef = next(ef for ef in elementary_flows if ef.source_refs[0]["source_flow_uuid"] == _COAL_MINE_OFFGAS_UUID)
        self.assertEqual(cog_ef.flow_object_id, _COAL_MINE_FO_ID)

    def test_override_hits_counted(self):
        _, _, stats = resolve_flow_layers(_as_flows(self._make_flows()), source_list=BASE)
        self.assertEqual(stats["override_hits"], 2)


if __name__ == "__main__":
    unittest.main()
