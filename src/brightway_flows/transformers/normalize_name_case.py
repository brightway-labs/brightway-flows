"""Normalize flow name casing with conservative title-casing rules."""

from __future__ import annotations

from brightway_flows.domain.flow import Flow
from brightway_flows.domain.labels import Label, coerce_pref_labels
from brightway_flows.pipeline import Change, Transformer


class NormalizeNameCaseTransformer(Transformer):
    """Title-case prefLabel unless a word already has internal capitals."""

    name = "normalize_name_case"
    answers_per_flow = True

    def setup(self) -> None:
        pass

    def transform(self, flows: list[Flow]) -> list[Change]:
        changes: list[Change] = []

        for flow in flows:
            pref_labels = coerce_pref_labels(flow.prefLabel)
            pref = pref_labels[0] if pref_labels else None
            raw = pref.value if pref is not None else None
            if not isinstance(raw, str) or not raw.strip():
                continue

            words = raw.split()
            transformed = " ".join(self._normalize_word(word) for word in words)
            if transformed != raw:
                changes.append(Change(
                    flow.uuid,
                    "prefLabel",
                    (
                        [Label(value=transformed, language=pref.language, source=pref.source).to_dict()]
                        + [x.to_dict() for x in pref_labels[1:]]
                    ),
                    comment=(
                        "Title-cased words without internal capitals "
                        "(preserved words with uppercase letters beyond the first character)"
                    ),
                ))

        return changes

    def _normalize_word(self, word: str) -> str:
        # Preserve terms like iPhone, eCoinvent, DNA, etc.
        if any(ch.isupper() for ch in word[1:]):
            return word
        if not word or not word[0].isalpha():
            return word
        return word[0].upper() + word[1:].lower()
