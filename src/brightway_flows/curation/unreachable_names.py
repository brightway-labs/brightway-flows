"""Names that reach one substance without being published on it, and split it.

A source row is placed on a flow object by whatever evidence the merge had:
a published correspondence table, a registry number, a curated override.  None
of those leaves the row's *name* on the object.  So a name can be the whole of
what one list calls a substance and still be reachable nowhere, because the
object it belongs to publishes some other name for it.

That is invisible until a second list ships the same string.  The merge then
looks the name up, finds nothing, and mints the substance again -- the same
quantity published twice, under two ids, with the inventories that use them
unable to add up.  #74 is that failure with 394 BAFU datasets behind it:
ecoinvent's `Energy, gross calorific value, in biomass` reaches EF 3.1's flow
through a correspondence table, EF publishes it as `Biomass`, and BAFU's
identical string found nothing to match and became a second substance.

The name was never renamed.  It was never *arrived* -- the table said the two
were one flow and then said nothing about the name, which is the general shape
of the failure and the reason a check is worth having.  Every list this project
merges is a list of names, and the merge decides by identifiers wherever it can.

**What is reported.**  A name qualifies when both halves are true:

  - some row carrying it was placed on an object that does not publish it, as
    either a preferred or an alternative label; and
  - the same name *is* some other object's own preferred label.

The second half is what makes it a finding rather than a curiosity.  A name
that is merely unreachable costs nothing until something needs it; a name that
is unreachable **and** already names a second object has cost a split already.

**What is filtered out, and why it has to be.**  Two objects with the same name
are not always one substance.  A metal and its ion share a name in ordinary
speech and are two things, and this list keeps them apart deliberately.  So a
pair is dropped when the list already tells the two apart by something other
than the name:

  - a registry number.  Both objects carry one, and they do not share any --
    `aluminium` the metal against `aluminium(3+)` the ion.
  - an origin qualifier.  `carbon dioxide` fossil against `carbon dioxide`
    biogenic is the axis `qualifiers` exists for.

Neither test can be right about every pair, and neither is meant to be: what
comes out is a list a curator reads, in the manner of
`tools/build_scope_narrowing_shortlist.py`, and the filters only keep the
reading from being mostly ions.

Nothing here decides anything, and nothing in the pipeline imports it.
`tools/build_unreachable_name_shortlist.py` is the caller.
"""

from __future__ import annotations

import sqlite3

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import orjson

from brightway_flows.domain.labels import canonical_label_value, coerce_alt_labels
from brightway_flows.domain.records import SerialisableRecord
from brightway_flows.domain.vocabulary import (
    CHEMINF_CAS_REGISTRY_NUMBER,
    CHEMINF_EC_NUMBER,
)
from brightway_flows.merge.store import Outcome, latest_run_id, read_outcomes

#: How a row can be placed on an object without its name being consulted.
#: `algorithm` is here because its lookup order is CAS, then EC, then label:
#: only the last of those guarantees the name is on the object, and the basis
#: recorded on the outcome says which one was used.  `unmatched` and `created`
#: are absent -- neither places a row on an object somebody else's name owns.
PLACING_OUTCOMES = frozenset({
    Outcome.PREPARED,
    Outcome.ALGORITHM,
    Outcome.MANUAL_ADDITION,
})


@dataclass(frozen=True)
class FlowObjectNames:
    """The published names and separating identifiers of one flow object.

    Not a `SerialisableRecord`: it is an index this module reads and never
    publishes, and its sets would not survive the round trip if it claimed to
    be one.
    """

    flow_object_id: str
    pref_label: str = ""
    labels: frozenset[str] = field(default_factory=frozenset)
    identifiers: frozenset[str] = field(default_factory=frozenset)
    origin_qualifier: str = ""


@dataclass
class UnreachableName(SerialisableRecord):
    """One name that both reaches a substance and names a different one.

    `placed_on` and `names` are disjoint by construction: an object that
    publishes the name cannot be one the name fails to reach.
    """

    #: The name as a source list spells it, not the canonical key.
    name: str
    #: Objects rows of this name were placed on, which do not publish it.
    placed_on: list[str] = field(default_factory=list)
    #: What those objects publish instead, in the same order.
    placed_on_labels: list[str] = field(default_factory=list)
    #: Objects whose own preferred label is this name.
    names: list[str] = field(default_factory=list)
    #: `<list> <version>/<outcome>` for each placement that could not be
    #: reached by name, so a reader can see what decided it instead.
    decided_by: list[str] = field(default_factory=list)
    #: Source rows placed unreachably.  The ordering key: a name on 40 rows is
    #: a bigger split than a name on one.
    row_count: int = 0


def _identifiers(classifications: Any) -> frozenset[str]:
    """Every registry number on an object, CAS and EC together.

    The two are pooled deliberately.  The question this answers is only whether
    *some* number tells two objects apart, and a pair agreeing on neither kind
    is as separate as a pair disagreeing on one.
    """
    if not isinstance(classifications, dict):
        return frozenset()
    numbers: set[str] = set()
    for predicate in (CHEMINF_CAS_REGISTRY_NUMBER, CHEMINF_EC_NUMBER):
        row = classifications.get(predicate)
        if not isinstance(row, dict):
            continue
        values = row.get("@value")
        if isinstance(values, list):
            numbers.update(str(x).strip() for x in values if str(x).strip())
    return frozenset(numbers)


def read_flow_object_names(db_path: Path) -> dict[str, FlowObjectNames]:
    """Every flow object's published names, by id.

    Read straight from the table rather than through the published payloads:
    this needs four columns of 8,000 rows, and `read_published_flow_payloads`
    rebuilds every substance body to hand them over.
    """
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT flow_object_id, pref_label_value, alt_label_json, "
            "classifications_json, origin_qualifier FROM flow_objects"
        ).fetchall()
    finally:
        connection.close()

    objects: dict[str, FlowObjectNames] = {}
    for object_id, pref, alt_json, classifications_json, qualifier in rows:
        if not isinstance(object_id, str) or not object_id:
            continue
        pref_value = str(pref or "").strip()
        labels = {canonical_label_value(pref_value)} if pref_value else set()
        for item in coerce_alt_labels(orjson.loads(alt_json or b"[]")):
            if item.value.strip():
                labels.add(canonical_label_value(item.value))
        objects[object_id] = FlowObjectNames(
            flow_object_id=object_id,
            pref_label=pref_value,
            labels=frozenset(labels - {""}),
            identifiers=_identifiers(orjson.loads(classifications_json or b"{}")),
            origin_qualifier=str(qualifier or "").strip(),
        )
    return objects


def told_apart(left: FlowObjectNames, right: FlowObjectNames) -> bool:
    """Whether something other than the name already separates two objects.

    A registry number each, sharing none, or two different origin qualifiers.
    Either says the list has decided these are two substances on evidence, and
    a shared name is then expected rather than a defect.
    """
    if left.identifiers and right.identifiers and not (left.identifiers & right.identifiers):
        return True
    return left.origin_qualifier != right.origin_qualifier


def unreachable_names(db_path: Path, *, run_id: str | None = None) -> list[UnreachableName]:
    """Names that split a substance in the merge run *run_id*, worst first.

    Returns an empty list when the database records no merge run, which is what
    a build that has merged nothing looks like.
    """
    run = run_id or latest_run_id(db_path)
    if run is None:
        return []

    objects = read_flow_object_names(db_path)
    named_by: dict[str, set[str]] = {}
    for entry in objects.values():
        key = canonical_label_value(entry.pref_label)
        if key:
            named_by.setdefault(key, set()).add(entry.flow_object_id)

    # canonical name -> object it failed to reach -> how each row got there.
    unreached: dict[str, dict[str, set[str]]] = {}
    spellings: dict[str, str] = {}
    rows_per_name: dict[str, int] = {}
    for outcome in read_outcomes(db_path, run_id=run):
        if outcome.outcome not in PLACING_OUTCOMES or not outcome.flow_object_id:
            continue
        key = canonical_label_value(outcome.source_name)
        entry = objects.get(outcome.flow_object_id)
        if not key or entry is None or key in entry.labels:
            continue
        spellings.setdefault(key, outcome.source_name.strip())
        rows_per_name[key] = rows_per_name.get(key, 0) + 1
        unreached.setdefault(key, {}).setdefault(outcome.flow_object_id, set()).add(
            f"{outcome.list_name} {outcome.list_version}/{outcome.outcome}"
        )

    findings: list[UnreachableName] = []
    for key, placements in unreached.items():
        owners = named_by.get(key, set()) - set(placements)
        if not owners:
            continue
        if all(
            told_apart(objects[placed], objects[owner])
            for placed in placements
            for owner in owners
        ):
            continue
        placed_ids = sorted(placements)
        findings.append(UnreachableName(
            name=spellings.get(key, key),
            placed_on=placed_ids,
            placed_on_labels=[objects[object_id].pref_label for object_id in placed_ids],
            names=sorted(owners),
            decided_by=sorted({d for decisions in placements.values() for d in decisions}),
            row_count=rows_per_name.get(key, 0),
        ))
    return sorted(findings, key=lambda row: (-row.row_count, row.name.lower()))
