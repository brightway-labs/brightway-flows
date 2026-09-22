"""Remove altLabel values that duplicate another flow object's prefLabel.

An altLabel that is also the prefLabel of a *different* substance is
confusing and incorrect: it suggests that two distinct substances share the
same preferred name, which they cannot.  The canonical form of each flow's
prefLabel is collected across all flows, and any altLabel whose canonical
form matches a *different* prefLabel is removed.

Same-substance, different-context flows share the same canonical prefLabel,
so they never trigger removal for each other.
"""

from __future__ import annotations


from brightway_flows.domain.flow import Flow
from brightway_flows.domain.labels import (
    canonical_label_value,
    coerce_alt_labels,
    coerce_pref_label,
    dedupe_alt_labels_against_pref,
    flow_label_value,
)
from brightway_flows.pipeline import Change, Transformer, writable_flows


class StripCrossObjectAltLabelsTransformer(Transformer):
    """Remove altLabel values that are the prefLabel of a different flow object."""

    name = "strip_cross_object_altlabels"
    # The whole rule is "this alt label is some *other* object's name", and the
    # other object is usually one this call cannot write to.  Shown only the
    # writable flows it would stop recognising the names it exists to catch.
    answers_per_flow = False

    def transform(self, flows: list[Flow]) -> list[Change]:
        changes: list[Change] = []

        # Collect every canonical prefLabel that appears across all flows.
        all_canonical_prefs: set[str] = set()
        flow_canonical_pref: dict[str, str] = {}

        for flow in flows:
            name = flow_label_value(flow)
            if not name:
                continue
            canon = canonical_label_value(name)
            if canon:
                all_canonical_prefs.add(canon)
                uuid = flow.uuid or ""
                if uuid:
                    flow_canonical_pref[uuid] = canon

        # Phase 2 decides, and a decision about a finished flow is dropped on
        # arrival.  Phase 1 above still reads every flow, because "is this
        # synonym some other substance's name?" is a question about the set and
        # the other substance is usually one this call cannot write to.
        for flow in writable_flows(flows):
            uuid = flow.uuid or ""
            this_canon = flow_canonical_pref.get(uuid, "")
            if not this_canon:
                continue

            existing_pref = coerce_pref_label(flow.prefLabel)
            existing_alt = coerce_alt_labels(flow.altLabel)

            kept = []
            removed: list[str] = []
            for label in existing_alt:
                canon_alt = canonical_label_value(label.value)
                if (
                    canon_alt
                    and canon_alt in all_canonical_prefs
                    and canon_alt != this_canon
                ):
                    removed.append(label.value)
                else:
                    kept.append(label)

            if not removed:
                continue

            new_alt = dedupe_alt_labels_against_pref(
                alt_labels=kept, pref_label=existing_pref
            )
            changes.append(
                Change(
                    uuid,
                    "altLabel",
                    [x.to_dict() for x in new_alt],
                    comment=(
                        f"Removed {len(removed)} altLabel value(s) that duplicate "
                        f"another flow object's prefLabel: "
                        f"{', '.join(repr(v) for v in sorted(removed))}"
                    ),
                )
            )

        return changes
