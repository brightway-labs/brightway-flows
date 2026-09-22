"""The renames that were applied, read back out of the change log.

`fold_undecided_label_pairs` covers the renames a curator still owes a ruling
on.  This covers the other half: the ones a rule in `DEFAULT_APPROVED_RULES`
applied *because* nobody had ruled on them.  Those never reach a queue -- that
is what the default means -- so the change log is the only record of them, and
until #224 nothing read it back.

The rule is identified by the provenance of the label it wrote, not by the
comment on the change: `CC_CHEBI_AGREEMENT_DERIVATION` is on the value itself,
where `AGENTS.md` requires the derivation of a written value to be, and a
comment is free text that no reader can rely on.

What comes out is one row per distinct pair, as `UndecidedLabelPair` is: a
ruling is keyed on the pair of names, so the pair is the unit of review whether
the ruling is owed or was skipped.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from brightway_flows.domain.labels import coerce_pref_label
from brightway_flows.domain.preferred_label_decisions import decision_key
from brightway_flows.domain.records import SerialisableRecord
from brightway_flows.domain.vocabulary import (
    PROV_HAD_PRIMARY_SOURCE_CURIE,
    PROV_WAS_DERIVED_FROM_CURIE,
)
from brightway_flows.pipeline.review_records import ChangeEvent
from brightway_flows.pipeline.review_tables import read_changelog
from brightway_flows.transformers.consensus_match.rules import (
    CC_CHEBI_AGREEMENT_DERIVATION,
)
from brightway_flows.transformers.consensus_match.transformer import (
    ConsensusMatchTransformer,
)

#: The prefix `rename_from_cc_chebi_agreement` writes its CAS under in
#: `prov:hadPrimarySource`.
_CAS_PREFIX = "CAS:"


@dataclass
class AppliedLabelPair(SerialisableRecord):
    """One rename that was applied, with every occurrence folded into it.

    Deliberately the same shape as `UndecidedLabelPair`, minus its `decision`
    and `hint`: there is no ruling to record, and that is the point of the row.

    `flow_count` counts distinct flows rather than change events.  The merge
    runs the transformer chain once per source list, so one flow can carry the
    same rename twice, and a count of events would report the rename as
    affecting more of the list than it does.
    """

    current: str
    replacement: str
    flow_count: int = 0
    example_uuid: str = ""
    cas_numbers: list[str] = field(default_factory=list)


def _label_value(payload: Any) -> str:
    label = coerce_pref_label(payload)
    return label.value if label is not None else ""


def _source_of(payload: Any) -> dict[str, Any]:
    label = coerce_pref_label(payload)
    source = label.source if label is not None else None
    return source if isinstance(source, dict) else {}


def is_cc_chebi_rename(change: ChangeEvent) -> bool:
    """Whether *change* is the CC/ChEBI rule writing a preferred label."""
    return _source_of(change.new_value).get(PROV_WAS_DERIVED_FROM_CURIE) == (
        CC_CHEBI_AGREEMENT_DERIVATION
    )


def cas_of(change: ChangeEvent) -> str:
    """The CAS the rule keyed the replacement on, from the label's provenance."""
    sources = _source_of(change.new_value).get(PROV_HAD_PRIMARY_SOURCE_CURIE) or []
    for entry in sources:
        if isinstance(entry, str) and entry.startswith(_CAS_PREFIX):
            return entry[len(_CAS_PREFIX):].strip()
    return ""


def fold_applied_pairs(changes: list[ChangeEvent]) -> list[AppliedLabelPair]:
    """Applied renames folded to one row per pair, most-affecting first."""
    pairs: dict[tuple[str, str], AppliedLabelPair] = {}
    seen: dict[tuple[str, str], set[str]] = {}
    for change in changes:
        current = _label_value(change.old_value)
        replacement = _label_value(change.new_value)
        if not current or not replacement:
            continue
        key = decision_key(current, replacement)
        pair = pairs.get(key)
        if pair is None:
            pair = AppliedLabelPair(
                current=current, replacement=replacement, example_uuid=change.uuid
            )
            pairs[key] = pair
            seen[key] = set()
        if change.uuid not in seen[key]:
            seen[key].add(change.uuid)
            pair.flow_count += 1
        cas = cas_of(change)
        if cas and cas not in pair.cas_numbers:
            pair.cas_numbers.append(cas)

    for pair in pairs.values():
        pair.cas_numbers.sort()
    return sorted(pairs.values(), key=lambda pair: (-pair.flow_count, pair.current))


def applied_cc_chebi_renames(db_path: Path) -> list[AppliedLabelPair]:
    """Every `cc_chebi_agreement` rename this run applied, one row per pair."""
    changes = [
        change
        for change in read_changelog(
            db_path,
            transformer=ConsensusMatchTransformer.name,
            field_name="prefLabel",
        )
        if is_cc_chebi_rename(change)
    ]
    return fold_applied_pairs(changes)
