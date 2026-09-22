"""Remove altLabel values from qualified flows that are not qualifier-specific.

Qualified flows (biogenic CO2, fossil methane, green water, …) share CAS
numbers and many synonyms with their unqualified counterparts.  ChEBI/PubChem
enrichment attaches generic synonyms to all variants, which causes label-based
matching to find multiple flow objects as candidates for a single source flow.

This transformer strips altLabel values from any flow whose prefLabel carries
an origin qualifier when those altLabels do not themselves carry the *same*
qualifier.  The test is simply: ``detect_origin_qualifier(altLabel) == qualifier``.

Examples
--------
* "Green Water" (qualifier green_water) keeps "Green water resource" but drops
  "oxidane", "H2O", "Water", etc.
* "Carbon dioxide, biogenic" keeps "CO2, biogenic" but drops plain "CO2".
* "Carbon dioxide, non-fossil, resource correction" keeps only labels that also
  detect as "biogenic_resource_correction".
"""

from __future__ import annotations


from brightway_flows.domain.flow import Flow
from brightway_flows.domain.labels import (
    coerce_alt_labels,
    coerce_pref_label,
    dedupe_alt_labels_against_pref,
    flow_label_value,
)
from brightway_flows.pipeline import Change, Transformer
from brightway_flows.qualifiers import detect_origin_qualifier


class StripQualifierAltLabelsTransformer(Transformer):
    """Remove altLabel values that do not share the flow's origin qualifier."""

    name = "strip_qualifier_altlabels"
    answers_per_flow = True

    def transform(self, flows: list[Flow]) -> list[Change]:
        changes: list[Change] = []

        for flow in flows:
            name = flow_label_value(flow)
            if not name:
                continue
            qualifier = detect_origin_qualifier(name)
            if qualifier is None:
                continue

            existing_pref = coerce_pref_label(flow.prefLabel)
            existing_alt = coerce_alt_labels(flow.altLabel)

            kept = []
            removed: list[str] = []
            for label in existing_alt:
                if detect_origin_qualifier(label.value) == qualifier:
                    kept.append(label)
                else:
                    removed.append(label.value)

            if not removed:
                continue

            new_alt = dedupe_alt_labels_against_pref(
                alt_labels=kept, pref_label=existing_pref
            )
            changes.append(
                Change(
                    flow.uuid or "",
                    "altLabel",
                    [x.to_dict() for x in new_alt],
                    comment=(
                        f"Removed {len(removed)} altLabel value(s) lacking qualifier "
                        f"{qualifier!r}: "
                        f"{', '.join(repr(v) for v in sorted(removed)[:5])}"
                        + (" …" if len(removed) > 5 else "")
                    ),
                )
            )

        return changes
