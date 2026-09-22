"""Bootstrap structured labels from legacy name/synonyms fields.

The first writer of a preferred label, and deliberately not gated by
`preferred-label-decisions.json` (#16): it writes the raw source name onto a
flow that has *no* label, and never over one, so there is no replacement for a
curator to rule on.  `Methyl Pentane` and `HCFC-140` are poor published labels,
but the remedy is a rule proposing a better one -- which is gated -- rather than
a ruling on the bootstrap, whose alternative is no label at all.
"""

from __future__ import annotations

from brightway_flows.domain.flow import Flow
from brightway_flows.domain.common import Provenance
from brightway_flows.domain.labels import Label, coerce_pref_label
from brightway_flows.pipeline import Change, Transformer
from brightway_flows.sources import base_source_label


class BootstrapLabelsTransformer(Transformer):
    """Move legacy name into prefLabel and remove synonyms."""

    name = "bootstrap_labels"
    answers_per_flow = True

    def setup(self) -> None:
        pass

    def transform(self, flows: list[Flow]) -> list[Change]:
        changes: list[Change] = []

        for flow in flows:
            uuid = flow.uuid
            legacy_name = flow.name
            pref = coerce_pref_label(flow.prefLabel)

            if isinstance(legacy_name, str) and legacy_name.strip():
                legacy_name = legacy_name.strip()
                if pref is None:
                    changes.append(Change(
                        uuid,
                        "prefLabel",
                        [Label(
                            value=legacy_name,
                            source=Provenance(
                                was_generated_by="bootstrap_labels",
                                was_attributed_to="brightway-flows",
                                had_primary_source=[str(flow.source or base_source_label())],
                                was_derived_from="legacy name field",
                            ).to_dict(),
                        ).to_dict()],
                        comment="Bootstrapped prefLabel from legacy name field",
                    ))

            if flow.name is not None:
                changes.append(Change(
                    uuid,
                    "name",
                    None,
                    comment="Purged legacy name field to enforce prefLabel usage",
                ))

            if flow.synonyms:
                changes.append(Change(
                    uuid,
                    "synonyms",
                    [],
                    comment="Removed legacy synonyms field in favor of structured labels",
                ))

        return changes
