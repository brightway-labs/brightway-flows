"""Ensure altLabel values are unique, preserving first occurrence."""

from __future__ import annotations

from brightway_flows.domain.flow import Flow
from brightway_flows.domain.labels import (
    coerce_alt_labels,
    coerce_pref_label,
    dedupe_alt_labels_against_pref,
)
from brightway_flows.pipeline import Change, Transformer


class DedupeAltLabelsTransformer(Transformer):
    """Normalize altLabel to unique label values with stable ordering."""

    name = "dedupe_altlabels"
    answers_per_flow = True

    def setup(self) -> None:
        return

    def transform(self, flows: list[Flow]) -> list[Change]:
        changes: list[Change] = []
        for flow in flows:
            uuid = flow.uuid
            if not isinstance(uuid, str) or not uuid:
                continue
            raw_alt = flow.altLabel
            if not isinstance(raw_alt, list) or len(raw_alt) < 2:
                continue

            deduped = dedupe_alt_labels_against_pref(
                alt_labels=coerce_alt_labels(raw_alt),
                pref_label=coerce_pref_label(flow.prefLabel),
            )
            deduped_payload = [label.to_dict() for label in deduped]
            if deduped_payload == raw_alt:
                continue

            changes.append(
                Change(
                    uuid,
                    "altLabel",
                    deduped_payload,
                    comment="Deduplicated altLabel values and removed entries matching prefLabel",
                )
            )
        return changes

