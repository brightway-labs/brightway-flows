"""A published label names the source that actually supplied the string.

`build_flow_objects` copies each elementary flow's labels onto the flow object.
It used to forward the label's own source only when that source was a plain
string -- and no writer produces one: every transformer that writes a label
attaches a `Provenance` dict.  So the guard never fired, and every published
label was stamped `wasGeneratedBy: hybrid_name_cas_v1` with the seed list as
its sole `hadPrimarySource` (#247).

That was wrong for ~99.5% of them.  `Prifrac 2981` is a Common Chemistry trade
name fetched by CAS; EF 3.1 never supplied it, and its own synonyms are purged
by `bootstrap_labels` before any enricher runs.  The published record named the
list anyway.

These tests pin the two halves of the fix: the label's own activity and
`wasDerivedFrom` survive the copy, and the seed list joins the label's primary
sources instead of replacing them -- it still records which member list put
this label on this object, which is the one thing the seed source does say.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

from brightway_flows.domain.flow import Flow
from brightway_flows.flow_layers import resolve_flow_layers
from brightway_flows.flow_layers.labels import _label_entry
from brightway_flows.sources import SourceList

_EF31 = SourceList(
    list_name="EF",
    list_version="3.1",
    flows_path=Path("/nonexistent/ef-31-flows.json"),
    declared_source_label="EF 3.1",
)

#: What `consensus_match.add_commonchem_altlabels` writes: a name read from
#: Common Chemistry by CAS, with nothing of the flow list in it.
_COMMON_CHEMISTRY = {
    "prov:wasGeneratedBy": "consensus_match",
    "prov:wasAttributedTo": "brightway-flows",
    "prov:hadPrimarySource": [
        "CAS:57-11-4",
        "https://commonchemistry.cas.org/detail?cas_rn=57-11-4",
    ],
    "prov:wasDerivedFrom": "common chemistry CAS lookup",
}

#: What `bootstrap_labels` writes: the list's own name for the flow.  Here the
#: seed source is the truth, and the fix must not lose it.
_BOOTSTRAP = {
    "prov:wasGeneratedBy": "bootstrap_labels",
    "prov:wasAttributedTo": "brightway-flows",
    "prov:hadPrimarySource": ["EF 3.1"],
    "prov:wasDerivedFrom": "legacy name field",
}


def _stearic_acid(**overrides: Any) -> Flow:
    payload: dict[str, Any] = {
        "uuid": "0004cecf-b2e9-44a2-b1aa-78a72fe95dfe",
        "source": "EF 3.1",
        "unit": "kg",
        "context": ["Emissions", "Emissions to air"],
        "cas_numbers": ["57-11-4"],
        "prefLabel": [
            {"@value": "Stearic Acid", "@language": "en", "source": _BOOTSTRAP}
        ],
        "altLabel": [
            {"@value": "Prifrac 2981", "@language": "en", "source": _COMMON_CHEMISTRY}
        ],
    }
    payload.update(overrides)
    return Flow(**payload)


def _only_object(flows: list[Flow]):
    objects, _elementary, _stats = resolve_flow_layers(flows, source_list=_EF31)
    matching = [obj for obj in objects if obj.altLabel or obj.prefLabel]
    return matching[0]


class CarriedLabelProvenanceTestCase(unittest.TestCase):
    """The reported case: an enricher's string, attributed to the seed list."""

    def test_the_enricher_keeps_its_activity(self):
        obj = _only_object([_stearic_acid()])
        row = next(r for r in obj.altLabel if r["@value"] == "Prifrac 2981")
        self.assertEqual(
            row["provenance"]["prov:wasGeneratedBy"], "consensus_match"
        )

    def test_the_enricher_keeps_its_derivation(self):
        """`wasDerivedFrom: altLabel` said only which field it landed in."""
        obj = _only_object([_stearic_acid()])
        row = next(r for r in obj.altLabel if r["@value"] == "Prifrac 2981")
        self.assertEqual(
            row["provenance"]["prov:wasDerivedFrom"], "common chemistry CAS lookup"
        )

    def test_the_real_primary_sources_survive(self):
        obj = _only_object([_stearic_acid()])
        row = next(r for r in obj.altLabel if r["@value"] == "Prifrac 2981")
        sources = row["provenance"]["prov:hadPrimarySource"]
        self.assertIn("CAS:57-11-4", sources)
        self.assertIn(
            "https://commonchemistry.cas.org/detail?cas_rn=57-11-4", sources
        )

    def test_the_seed_list_is_no_longer_the_only_source(self):
        obj = _only_object([_stearic_acid()])
        row = next(r for r in obj.altLabel if r["@value"] == "Prifrac 2981")
        self.assertNotEqual(
            row["provenance"]["prov:hadPrimarySource"], ["EF 3.1"]
        )

    def test_the_seed_list_is_still_recorded(self):
        """It says which member list put this label on this object."""
        obj = _only_object([_stearic_acid()])
        row = next(r for r in obj.altLabel if r["@value"] == "Prifrac 2981")
        self.assertIn("EF 3.1", row["provenance"]["prov:hadPrimarySource"])

    def test_a_pref_label_the_list_did_supply_keeps_saying_so(self):
        obj = _only_object([_stearic_acid()])
        row = obj.prefLabel[0]
        self.assertEqual(row["@value"], "Stearic Acid")
        self.assertEqual(
            row["provenance"]["prov:wasGeneratedBy"], "bootstrap_labels"
        )
        self.assertEqual(
            row["provenance"]["prov:hadPrimarySource"], ["EF 3.1"]
        )


class SubstitutedPrefLabelTestCase(unittest.TestCase):
    """A prefLabel the layering itself chose is not the label's string.

    `pref_value` falls back to the flow's display name, and for a qualified
    flow it can be replaced by a name recovered from `source_refs`.  Neither is
    what the flow's prefLabel provenance describes, so that provenance must not
    be attached to it.
    """

    def test_a_recovered_name_is_not_attributed_to_the_label_writer(self):
        flow = _stearic_acid(
            uuid="u-qualified",
            prefLabel=[
                {
                    "@value": "carbon dioxide",
                    "@language": "en",
                    "source": _BOOTSTRAP,
                }
            ],
            altLabel=[],
            cas_numbers=["124-38-9"],
            source_refs=[
                {
                    "list_name": "EF",
                    "list_version": "3.1",
                    "source_flow_uuid": "u-qualified",
                    "source_flow_name": "carbon dioxide, biogenic",
                }
            ],
        )
        obj = _only_object([flow])
        row = obj.prefLabel[0]
        if row["@value"] == "carbon dioxide":
            self.skipTest("no qualifier was detected; nothing was substituted")
        self.assertEqual(
            row["provenance"]["prov:wasGeneratedBy"], "hybrid_name_cas_v1"
        )


class LabelEntryTestCase(unittest.TestCase):
    """`_label_entry` is also called with literal sources, which still work."""

    def test_a_label_with_no_provenance_falls_back_to_the_resolver(self):
        row = _label_entry(
            value="Carbon dioxide",
            language="en",
            resolver_name="hybrid_name_cas_v1",
            seed_source="EF 3.1",
            was_derived_from="prefLabel",
        )
        self.assertEqual(
            row["provenance"]["prov:wasGeneratedBy"], "hybrid_name_cas_v1"
        )
        self.assertEqual(row["provenance"]["prov:hadPrimarySource"], ["EF 3.1"])

    def test_a_string_source_is_still_a_primary_source(self):
        row = _label_entry(
            value="Carbon dioxide",
            language="en",
            resolver_name="hybrid_name_cas_v1",
            seed_source="EF 3.1",
            was_derived_from="prefLabel",
            label_source="legacy_prefLabel",
        )
        self.assertEqual(
            row["provenance"]["prov:hadPrimarySource"],
            ["EF 3.1", "legacy_prefLabel"],
        )

    def test_extra_primary_sources_still_reach_the_row(self):
        row = _label_entry(
            value="Zinc(2+)",
            language="en",
            resolver_name="ion_enrichment",
            seed_source="EF 3.1",
            was_derived_from="prefLabel",
            extra_primary_sources=["PubChem", "Common Chemistry"],
        )
        self.assertEqual(
            row["provenance"]["prov:hadPrimarySource"],
            ["Common Chemistry", "EF 3.1", "PubChem"],
        )


if __name__ == "__main__":
    unittest.main()
