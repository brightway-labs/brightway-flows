"""A published flow is called what its substance is called.

The name of a substance is written down twice: once on the flow object, which is
where every correction lands -- a preferred-label ruling (#313), an element
name, a land class renamed from its fields (#66) -- and once on each of the
substance's flows, which is what `harmonised-flows-simple.json.gz` publishes.
Until this pass nothing carried a correction from the first copy to the second,
so a name settled on the substance stopped there: the 19 August 2026 build held
886 flows publishing a name their own substance had already superseded, and 149
substances appeared in the export under two different names at once (#7).

This pass establishes the rule the two copies were missing: **the flow gets the
substance's label, and the name it had becomes a synonym of the flow.**

Detection strategy
------------------

Every flow that resolves to a flow object is compared against that object's
preferred label, by string.  Three cases:

* **The two agree** -- nothing happens, which is the ordinary case.
* **They differ only in case, spacing or punctuation** (`decision_key`'s
  canonical folding, the same one label rulings use) -- the substance's spelling
  is written outright.  `Hc Blue No. 1` beside twelve flows saying
  `HC Blue No. 1` is not two names, and no curator is asked about it.
* **They are different names** -- the substance's name is written onto the flow,
  and the name the flow had is appended to the flow's `altLabel`, so a reader
  holding the old name can still find the flow (#311's rule: a spelling a
  correction replaces stays searchable).

The exception is the whole point of the exception.  Before demoting the old
name to a synonym, the pass asks whether that name already answers for a
*different* substance -- as another object's preferred label, as its synonym,
or as the current name of another object's flows.  A name that answers for two
substances is an identification bug: either two substance records are one
substance, or one flow sits on the wrong record, and renaming the flow would
delete the only visible symptom (#116 holds four of these).  So in that case:

* a ruling in `preferred-label-decisions.json` covering the pair is followed --
  ``approve`` renames the flow and withholds the colliding synonym (#113: a
  name that would answer for two substances is published for neither),
  ``reject`` leaves the flow's own name standing;
* with no ruling, the flow keeps its name and the pair goes to the
  ``substance-label-conflict`` queue, blocking, with the other claimants named
  in the payload.

Deliberately not a `Transformer`: like `ElementPrefLabelPass` it needs the flow
objects, which are resolved after every transformer has run.  It runs after
that pass, as the last writer of a published `prefLabel`, so what leaves for
the export is what the substance layer says.  The merge applies the same rule
to the whole database after its own object-label writes
(:func:`apply_substance_labels_to_database`), for the reason `carry_member_names`
does: whether a name answers for two substances is a fact about the list, not
about the batch one merge minted.
"""

from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import orjson
import structlog

from brightway_flows.domain.common import Provenance
from brightway_flows.domain.flow import Flow
from brightway_flows.domain.flow_object import FlowObject
from brightway_flows.domain.labels import coerce_alt_labels, flow_label_value
from brightway_flows.domain.preferred_label_decisions import (
    LabelDecision,
    LabelRuling,
    decision_key,
    load_preferred_label_decisions,
    rule_on_replacement,
    undecided_label_item_key,
)
from brightway_flows.flow_layers.labels import _canonical_name
from brightway_flows.pipeline.layer_writes import LayerWriteLog
from brightway_flows.pipeline.review_records import (
    ReviewQueue,
    ReviewQueueItem,
    Severity,
)
from brightway_flows.pipeline.sqlite import merge_object_payload

logger = structlog.get_logger(__name__)

#: What `prov:wasGeneratedBy` says on the labels this writes, the rule name a
#: ruling in `preferred-label-decisions.json` is recorded against, and the
#: stage its counters file under.  Not in `DEFAULT_APPROVED_RULES` -- but the
#: default only decides the *conflict* case: a rename whose demoted name
#: answers for no other substance is the substance naming its own flow, which
#: is not a curation question and is applied without one.
PASS_NAME = "substance_label_v1"

#: The stage the merge files this pass's counters under.
MERGE_SUBSTANCE_LABEL_STAGE = "merge_substance_labels"


def _label_values(rows: Any) -> list[str]:
    out: list[str] = []
    if isinstance(rows, list):
        for row in rows:
            value = row.get("@value") if isinstance(row, dict) else row
            if isinstance(value, str) and value.strip():
                out.append(value.strip())
    return out


def _claimants(
    labels_by_object: dict[str, str],
    alt_labels_by_object: dict[str, list[str]],
    current_by_flow_object: dict[str, set[str]],
) -> dict[str, set[str]]:
    """Which substances each canonical name answers for.

    Three sources of a claim, because a reader can reach a substance through
    any of them: an object's preferred label, an object's synonyms, and the
    current names of the object's own flows -- the last because this pass runs
    before its own writes, so a flow name it is about to demote elsewhere is
    still a live claim here.
    """
    claims: dict[str, set[str]] = defaultdict(set)
    for object_id, label in labels_by_object.items():
        key = _canonical_name(label)
        if key:
            claims[key].add(object_id)
    for object_id, values in alt_labels_by_object.items():
        for value in values:
            key = _canonical_name(value)
            if key:
                claims[key].add(object_id)
    for object_id, names in current_by_flow_object.items():
        for name in names:
            key = _canonical_name(name)
            if key:
                claims[key].add(object_id)
    return claims


class _Conflict:
    """One name found answering for two substances, folded over its flows."""

    __slots__ = ("current", "target", "object_id", "other_object_ids", "uuids", "cas")

    def __init__(self, current: str, target: str, object_id: str, others: set[str]):
        self.current = current
        self.target = target
        self.object_id = object_id
        self.other_object_ids = set(others)
        self.uuids: list[str] = []
        self.cas = ""


class _Decider:
    """The rule, shared by the record-level pass and the database applier."""

    def __init__(
        self,
        labels_by_object: dict[str, str],
        alt_labels_by_object: dict[str, list[str]],
        current_by_flow_object: dict[str, set[str]],
        decisions: dict[tuple[str, str], LabelDecision],
    ):
        self.claims = _claimants(
            labels_by_object, alt_labels_by_object, current_by_flow_object
        )
        self.decisions = decisions
        self.stats: Counter[str] = Counter({
            key: 0 for key in (
                "flows_with_a_substance",
                "agreeing",
                "labelled",
                "respelled",
                "renamed",
                "synonyms_demoted",
                "demoted_names_withheld",
                "kept_by_ruling",
                "kept_awaiting_ruling",
            )
        })
        self.conflicts: dict[tuple[str, str, str], _Conflict] = {}

    def decide(self, *, current: str, target: str, object_id: str) -> str:
        """One of ``agree | label | respell | rename | demote | keep | defer``.

        ``demote`` is ``rename`` plus the synonym; ``rename`` alone means the
        synonym is withheld because another substance answers to it.
        """
        self.stats["flows_with_a_substance"] += 1
        if current == target:
            self.stats["agreeing"] += 1
            return "agree"
        if not current:
            self.stats["labelled"] += 1
            return "label"
        key = decision_key(current, target)
        if key[0] == key[1]:
            self.stats["respelled"] += 1
            return "respell"

        current_key = _canonical_name(current)
        others = self.claims.get(current_key, set()) - {object_id}
        if not others:
            self.stats["renamed"] += 1
            self.stats["synonyms_demoted"] += 1
            return "demote"

        ruling = rule_on_replacement(
            self.decisions, current=current, replacement=target, rule=PASS_NAME
        )
        if ruling is LabelRuling.APPROVED:
            # #113: a name that answers for two substances is published for
            # neither, so the rename happens and the synonym does not.
            self.stats["renamed"] += 1
            self.stats["demoted_names_withheld"] += 1
            return "rename"
        if ruling is LabelRuling.REJECTED:
            self.stats["kept_by_ruling"] += 1
            return "keep"

        self.stats["kept_awaiting_ruling"] += 1
        conflict_key = (current, target, object_id)
        if conflict_key not in self.conflicts:
            self.conflicts[conflict_key] = _Conflict(current, target, object_id, others)
        return "defer"

    def record_deferred(self, *, current: str, target: str, object_id: str,
                        uuid: str, cas: str) -> None:
        conflict = self.conflicts[(current, target, object_id)]
        conflict.uuids.append(uuid)
        if cas and not conflict.cas:
            conflict.cas = cas

    def queue_items(self, labels_by_object: dict[str, str]) -> list[ReviewQueueItem]:
        """One row per (name, substance) pair, however many flows share it."""
        return [
            ReviewQueueItem(
                queue_name=ReviewQueue.SUBSTANCE_LABEL_CONFLICT,
                item_key=undecided_label_item_key(
                    PASS_NAME, conflict.current, conflict.target
                ),
                title=(
                    f"{conflict.current} → {conflict.target} "
                    f"({conflict.current!r} also answers for "
                    f"{len(conflict.other_object_ids)} other substance(s))"
                ),
                severity=Severity.BLOCKING,
                uuid=conflict.uuids[0] if conflict.uuids else "",
                flow_object_id=conflict.object_id,
                cas=conflict.cas,
                payload={
                    "rule": PASS_NAME,
                    "current": conflict.current,
                    "replacement": conflict.target,
                    "flow_count": len(conflict.uuids),
                    "uuids": sorted(conflict.uuids)[:20],
                    #: Strings rather than pairs, because the queue page
                    #: renders a payload list one line per entry, as text.
                    "other_claimants": sorted(
                        f"{labels_by_object.get(other) or '(unnamed)'} ({other})"
                        for other in conflict.other_object_ids
                    ),
                },
            )
            for conflict in sorted(
                self.conflicts.values(), key=lambda c: (c.current, c.object_id)
            )
        ]


def _object_label_maps(
    flow_objects: list[FlowObject],
) -> tuple[dict[str, str], dict[str, list[str]]]:
    labels: dict[str, str] = {}
    alts: dict[str, list[str]] = {}
    for obj in flow_objects:
        object_id = obj.flow_object_id.strip()
        if not object_id:
            continue
        label = flow_label_value(obj).strip()
        if label:
            labels[object_id] = label
        alts[object_id] = _label_values(obj.altLabel)
    return labels, alts


def _demoted_entry(value: str, previous: Any) -> dict[str, Any]:
    """The demoted name as an `altLabel` row, keeping its own provenance.

    *previous* is the prefLabel row list the name is being demoted from; its
    provenance says who wrote the name originally, which is worth more than
    this pass's own attribution (#247).
    """
    source: Any = None
    if isinstance(previous, list) and previous and isinstance(previous[0], dict):
        source = previous[0].get("source") or previous[0].get("provenance")
    entry: dict[str, Any] = {"@value": value, "@language": "en", "@lang": "en"}
    entry["provenance"] = (
        source
        if isinstance(source, dict)
        else Provenance(
            was_generated_by=PASS_NAME,
            was_attributed_to="brightway-flows",
            had_primary_source=[],
            was_derived_from="flow.prefLabel",
        ).to_dict()
    )
    return entry


def _pref_label_rows(target: str, object_id: str) -> list[dict[str, Any]]:
    return [
        {
            "@value": target,
            "@language": "en",
            "@lang": "en",
            "source": Provenance(
                was_generated_by=PASS_NAME,
                was_attributed_to="brightway-flows",
                had_primary_source=[],
                was_derived_from=f"flow_object.prefLabel ({object_id})",
            ).to_dict(),
        }
    ]


def _alt_label_with(demoted: str, previous_pref: Any, existing: Any) -> list[Any]:
    """*existing* plus the demoted name, unless the list already answers to it."""
    rows = list(existing) if isinstance(existing, list) else []
    known = {_canonical_name(item.value) for item in coerce_alt_labels(rows)}
    if _canonical_name(demoted) in known:
        return rows
    return rows + [_demoted_entry(demoted, previous_pref)]


class SubstancePrefLabelPass:
    """Applies the substance's name to its flows; see the module docstring."""

    name = PASS_NAME

    def __init__(
        self,
        decisions: dict[tuple[str, str], LabelDecision] | None = None,
        *,
        writes: LayerWriteLog | None = None,
    ):
        self._decisions = (
            load_preferred_label_decisions() if decisions is None else decisions
        )
        self.writes = LayerWriteLog() if writes is None else writes
        self._decider: _Decider | None = None
        self._labels_by_object: dict[str, str] = {}

    def apply(self, flows: list[Flow], flow_objects: list[FlowObject]) -> dict[str, int]:
        labels, alts = _object_label_maps(flow_objects)
        current_by_object: dict[str, set[str]] = defaultdict(set)
        for flow in flows:
            object_id = flow.flow_object_id.strip()
            if object_id:
                value = flow_label_value(flow).strip()
                if value:
                    current_by_object[object_id].add(value)

        decider = _Decider(labels, alts, current_by_object, self._decisions)
        self._decider = decider
        self._labels_by_object = labels

        for flow in flows:
            object_id = flow.flow_object_id.strip()
            target = labels.get(object_id, "")
            if not target:
                continue
            current = flow_label_value(flow).strip()
            verdict = decider.decide(
                current=current, target=target, object_id=object_id
            )
            if verdict in ("agree", "keep"):
                continue
            if verdict == "defer":
                decider.record_deferred(
                    current=current, target=target, object_id=object_id,
                    uuid=flow.uuid,
                    cas=flow.cas_numbers[0] if flow.cas_numbers else "",
                )
                continue
            if verdict == "demote":
                self.writes.write(
                    flow,
                    "altLabel",
                    _alt_label_with(current, flow.prefLabel, flow.altLabel),
                    pass_name=self.name,
                    comment=f"demoted by the substance's name: {current}",
                )
            self.writes.write(
                flow,
                "prefLabel",
                _pref_label_rows(target, object_id),
                pass_name=self.name,
                comment=f"the substance's name: {target}",
            )

        stats = dict(decider.stats)
        logger.info("substance_pref_labels", **stats)
        return stats

    def review_queue_items(self) -> list[ReviewQueueItem]:
        if self._decider is None:
            return []
        return self._decider.queue_items(self._labels_by_object)


def apply_substance_labels_to_database(
    db_path: Path,
    decisions: dict[tuple[str, str], LabelDecision] | None = None,
) -> tuple[Counter[str], list[ReviewQueueItem]]:
    """The same rule, over every live flow a database holds.

    The merge's counterpart of the pass above, run after its object-label
    writes and before the export, because a merge moves object labels on flows
    it never touches -- `carry_member_names` demotes a second preferred label,
    a minted object's name wins a contest -- and the flows of a pre-existing
    object are not otherwise rewritten (#7).

    Rewrites only `flow_json`, and only the two label keys on it: the flow's
    own keys win over the hoisted object payload at read time
    (`merge_object_payload`), so nothing else needs to move, and
    `elementary_flows.pref_label_value` already carries the object's label.
    Deprecated flows are left alone -- they are not published, and their name
    is part of the record of why they were retired.
    """
    resolved = load_preferred_label_decisions() if decisions is None else decisions
    connection = sqlite3.connect(db_path)
    try:
        labels: dict[str, str] = {}
        alts: dict[str, list[str]] = {}
        for object_id, value, alt_json in connection.execute(
            "SELECT flow_object_id, pref_label_value, alt_label_json FROM flow_objects"
        ):
            object_id = str(object_id or "").strip()
            if not object_id:
                continue
            if isinstance(value, str) and value.strip():
                labels[object_id] = value.strip()
            try:
                alts[object_id] = _label_values(orjson.loads(alt_json or b"[]"))
            except orjson.JSONDecodeError:
                alts[object_id] = []

        rows = connection.execute(
            "SELECT ef.uuid, ef.flow_object_id, ef.flow_json, p.payload_json "
            "FROM elementary_flows ef "
            "LEFT JOIN flow_object_payloads p ON p.flow_object_id = ef.flow_object_id "
            "WHERE ef.is_deprecated = 0 AND ef.flow_json IS NOT NULL "
            "ORDER BY ef.rowid"
        ).fetchall()

        current_by_object: dict[str, set[str]] = defaultdict(set)
        merged_rows: list[tuple[str, str, dict[str, Any], dict[str, Any]]] = []
        for uuid, object_id, flow_json, payload_json in rows:
            object_id = str(object_id or "").strip()
            own = orjson.loads(flow_json)
            merged = merge_object_payload(own, payload_json)
            merged_rows.append((str(uuid), object_id, own, merged))
            if object_id:
                value = flow_label_value(merged).strip()
                if value:
                    current_by_object[object_id].add(value)

        decider = _Decider(labels, alts, current_by_object, resolved)
        updates: list[tuple[str, str]] = []
        for uuid, object_id, own, merged in merged_rows:
            target = labels.get(object_id, "")
            if not target:
                continue
            current = flow_label_value(merged).strip()
            verdict = decider.decide(
                current=current, target=target, object_id=object_id
            )
            if verdict in ("agree", "keep"):
                continue
            if verdict == "defer":
                cas = merged.get("cas_numbers")
                decider.record_deferred(
                    current=current, target=target, object_id=object_id,
                    uuid=uuid,
                    cas=cas[0] if isinstance(cas, list) and cas else "",
                )
                continue
            if verdict == "demote":
                own["altLabel"] = _alt_label_with(
                    current, merged.get("prefLabel"), merged.get("altLabel")
                )
            own["prefLabel"] = _pref_label_rows(target, object_id)
            updates.append((orjson.dumps(own).decode("utf-8"), uuid))

        if updates:
            connection.executemany(
                "UPDATE elementary_flows SET flow_json = ? WHERE uuid = ?", updates
            )
            connection.commit()

        stats = decider.stats
        stats["flows_rewritten"] = len(updates)
        items = decider.queue_items(labels)
        logger.info("applied_substance_labels_to_database", **dict(stats))
        return stats, items
    finally:
        connection.close()


__all__ = [
    "MERGE_SUBSTANCE_LABEL_STAGE",
    "PASS_NAME",
    "SubstancePrefLabelPass",
    "apply_substance_labels_to_database",
]
