"""Add RDKit-computed structural properties to flows after consensus matching.

For each computed value:
- If the value is not already present in ``@value``: add it.
- If the value is already present: record RDKit as an additional provenance source
  on that property (confirmation in the audit trail).

"Already present" is a question about the structure, not about the string --
see ``_already_present`` for why that distinction is the whole of #22.

Nothing is removed or replaced.
"""

from __future__ import annotations

import copy
from typing import Any

from brightway_flows.domain.flow import Flow
from brightway_flows.chem import (
    capture_rdkit_logs,
    configure_rdkit_logging,
)
from brightway_flows.domain.attestation import attest
from brightway_flows.domain.common import Provenance
from brightway_flows.domain.vocabulary import (
    QUDT_HAS_UNIT,
    RDFS_LABEL_CURIE,
)
from brightway_flows.filesystem import RDKIT_LOG_FILEPATH
from brightway_flows.pipeline import Change, Transformer
from brightway_flows.transformers.rdkit_enrichment import (
    _already_present,
    _computed_rows,
    _get_values,
    _merge_provenance,
    _merged_values,
    _parse_structure,
    _should_skip,
)


class RDKitPostConsensusTransformer(Transformer):
    """Add RDKit-computed structural values to properties after consensus matching.

    Uses the consensus-cleaned SMILES as input, so the structure is derived from
    the best available data rather than raw source values.

    When RDKit agrees with an existing value, its provenance is appended to that
    property's ``provenance`` list — providing an auditable confirmation without
    altering ``@value``.  When RDKit produces a new value, it is added to
    ``@value`` alongside existing entries.
    """

    name = "rdkit_post_consensus"
    answers_per_flow = True

    def setup(self) -> None:
        configure_rdkit_logging(RDKIT_LOG_FILEPATH)

    def transform(self, flows: list[Flow]) -> list[Change]:
        changes: list[Change] = []
        for flow in flows:
            change = self._process_flow(flow)
            if change is not None:
                changes.append(change)
        return changes

    def _process_flow(self, flow: dict[str, Any]) -> Change | None:
        flow_label = f"{flow.uuid} {flow.name or ''}"
        with capture_rdkit_logs(flow_label):
            return self._process_flow_inner(flow)

    def _process_flow_inner(self, flow: dict[str, Any]) -> Change | None:
        properties = flow.properties
        if not isinstance(properties, dict):
            return None
        if _should_skip(flow, properties):
            return None

        values, source = _parse_structure(properties)
        if values is None:
            return None

        new_properties = copy.deepcopy(properties)
        added: list[str] = []
        confirmed: list[str] = []

        computed = _computed_rows(values)
        prov = Provenance(
            was_generated_by="rdkit_post_consensus",
            was_attributed_to="brightway-flows",
            had_primary_source=[source],
        ).to_dict()

        for iri, label, value, unit_iri in computed:
            if not value:
                continue
            short = iri.rsplit("/", 1)[-1]
            existing = new_properties.get(iri)
            if isinstance(existing, dict):
                existing_values = _get_values(new_properties, iri)
                entry = dict(existing)
                if _already_present(iri, value, existing_values):
                    _merge_provenance(entry, prov)
                    # The record's own spelling, not RDKit's: `_already_present`
                    # matches a SMILES by structure, so the string RDKit just
                    # computed may not be the string the slot holds, and an
                    # attestation has to name a value that is actually there.
                    attest(
                        entry,
                        [v for v in existing_values if _already_present(iri, value, [v])],
                        "rdkit_post_consensus",
                    )
                    new_properties[iri] = entry
                    confirmed.append(short)
                else:
                    merged = _merged_values(iri, value, existing_values)
                    if value not in merged:
                        continue
                    entry["@value"] = merged
                    _merge_provenance(entry, prov)
                    attest(entry, [value], "rdkit_post_consensus")
                    new_properties[iri] = entry
                    added.append(short)
            else:
                entry = {"@id": iri, RDFS_LABEL_CURIE: label, "@value": [value], "provenance": prov}
                attest(entry, [value], "rdkit_post_consensus")
                if unit_iri:
                    entry[QUDT_HAS_UNIT] = unit_iri
                new_properties[iri] = entry
                added.append(short)

        if not added and not confirmed:
            return None

        comment_parts = [f"rdkit_post_consensus from {source!r}"]
        if added:
            comment_parts.append(f"added: {', '.join(added)}")
        if confirmed:
            comment_parts.append(f"confirmed: {', '.join(confirmed)}")

        return Change(
            flow.uuid,
            "properties",
            new_properties,
            comment="; ".join(comment_parts),
        )
