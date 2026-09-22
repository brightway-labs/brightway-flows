"""Strip leading/trailing whitespace from flow names."""

from __future__ import annotations

from brightway_flows.domain.flow import Flow
from brightway_flows.domain.labels import Label, coerce_pref_labels
from brightway_flows.pipeline import Change, Transformer


class StripNamesTransformer(Transformer):
    """Emit changes for prefLabel values that have leading or trailing whitespace."""

    name = "strip_names"
    answers_per_flow = True

    def setup(self) -> None:
        pass

    def transform(self, flows: list[Flow]) -> list[Change]:
        changes: list[Change] = []

        for flow in flows:
            pref_labels = coerce_pref_labels(flow.prefLabel)
            pref = pref_labels[0] if pref_labels else None
            raw = pref.value if pref is not None else None
            if raw and raw != raw.strip() and pref is not None:
                leading = raw != raw.lstrip()
                trailing = raw != raw.rstrip()
                if leading and trailing:
                    where = "leading and trailing"
                elif leading:
                    where = "leading"
                else:
                    where = "trailing"
                changes.append(Change(
                    flow.uuid,
                    "prefLabel",
                    [Label(value=raw.strip(), language=pref.language, source=pref.source).to_dict()]
                    + [x.to_dict() for x in pref_labels[1:]],
                    comment=f"Stripped {where} whitespace",
                ))

        return changes
