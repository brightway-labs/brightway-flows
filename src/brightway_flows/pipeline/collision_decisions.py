"""Curated rulings that two live flows of one substance are one flow.

`pipeline.collisions` asks the question -- two live flows share a flow object, a
context and a unit, so are they two flows or one? -- and says plainly that the
pipeline cannot answer it.  This is where the answers are applied.

A ruling is a curator's, keyed on the collision rather than on a flow, so it
survives a rebuild and does not have to be rewritten when EF publishes the same
duplication again.  The same contract as `contested-cas-decisions.json` and
`preferred-label-decisions.json`: the rules propose, a curator decides.

**Why this is not left to deduplication.**  `pipeline/deduplication.py` collapses
flows whose every semantic field agrees, and a collision is precisely the case
where they do not: the two rows carry different names, which is the only thing
telling them apart.  Loosening that signature to catch them would collapse every
collision at once, including the ones that are two substances -- `Nitrogen,
organic bound` against `dinitrogen`, four water contexts of it, was that case
until #57 took the registry number the two shared off the organic-bound rows,
and a nutrient load would have been collapsed into nitrogen gas.  So the
collapse is made one collision at a time, with the evidence written down.

**What a ruling does, and what deduplication would not have done.**

*The survivor is named, not sorted for.*  Deduplication keeps the flow with the
most characterisation factors and breaks ties on the identifier; the collision
queue predicts a survivor by identifier alone.  Neither is a decision, and where
the two rows differ in what they carry -- one holds the characterisation, the
other holds the identifier ecoinvent maps onto -- the choice is the ruling's.

*The factors are unioned onto the survivor.*  Deduplication drops the loser's,
which is how #31 turned a balanced pair of water factors into a one-sided
charge.  Every ruling in the file today collapses a row whose factor set is
contained in the survivor's, so nothing is added and nothing is lost; the union
is here so that a ruling written later against changed data cannot quietly lose
a factor the way #31 did.

*Where both rows publish one factor, the number is chosen and the other is
written down.*  A union has nothing to add when the survivor already holds the
factor, and until #63 that was the end of it: the survivor's number stood and
the other disappeared.  Usually they agree.  Where they do not, they are almost
always one number written to two precisions -- EF publishes a refrigerant's
freshwater ecotoxicity as `0.00011755` under its chemical name and `0.000118`
under its industry designation -- and which of the two the survivor happened to
hold was settled by an identifier sort.  Over the 116 collisions of the
2026-08-12 build, 152 factors are published twice with different numbers, and
the row a sort would keep holds the more precise number 72 times and the
rounded one 70.  So the more precise number is now preferred where the two are
one number, the number not kept is recorded on the factor it lost to, and a gap
too large to be rounding is logged rather than passed over.

*The source references follow.*  A reference stranded on a deprecated flow is a
source list mapped onto a record the export marks as superseded.

The deprecation itself is the ordinary one, and `pipeline/redirects.py` will
classify it `identity-merge` on its own evidence: both rows come from the same
source context, which is what that reason means -- the same flow reached the
list more than once.  No new deprecation reason is minted here, because none of
these is a new *kind* of deprecation; what is new is that a person decided it.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import orjson
import structlog

from brightway_flows.domain.common import Provenance
from brightway_flows.domain.flow import Flow
from brightway_flows.pipeline.collisions import collision_key, is_deprecated
from brightway_flows.pipeline.deduplication import (
    factor_key,
    settle_factor_values,
)
from brightway_flows.pipeline.layer_writes import LayerWriteLog
from brightway_flows.filesystem import PACKAGE_DATA_DIR

logger = structlog.get_logger(__name__)

DECISIONS_FILEPATH = (
    PACKAGE_DATA_DIR / "elementary-flow-collision-decisions.json"
)

#: The on-disk format of *this* ruling file, and nothing else -- the other
#: ruling files version themselves independently, and the bare
#: ``SCHEMA_VERSION`` is ``domain.schema``'s, the version the project publishes
#: (#98).  Read by the loader rather than only declared here: a version
#: constant nothing checks is a comment, and the file is hand-edited.
DECISIONS_SCHEMA_VERSION = 1

#: The only verdict the file carries.  A collision a curator judges to be two
#: distinct flows needs no ruling to stay as it is -- the pipeline already
#: leaves it alone -- and recording that verdict here would be a second place to
#: look for a decision that changes nothing.  It belongs in the queue's own
#: record when the queue can hold one.
MERGE = "merge"

#: `prov:wasGeneratedBy` on every value a ruling writes, including a number it
#: settles: a reader can then tell a number a person decided about from one a
#: signature collapsed under `deduplication.GENERATED_BY`.
GENERATED_BY = "pipeline.collision_decisions"


@dataclass(frozen=True)
class CollisionRuling:
    """One curator's answer to one collision."""

    flow_object_id: str
    context_iri: str
    unit: str
    survivor: str
    merged: tuple[str, ...]
    names: tuple[str, ...]
    comment: str

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.flow_object_id, self.context_iri, self.unit)

    @property
    def members(self) -> frozenset[str]:
        """Every flow the ruling was written about, survivor included."""
        return frozenset({self.survivor, *self.merged})


class CollisionRulingError(ValueError):
    """A ruling that cannot be read as one.

    Raised rather than skipped.  A malformed ruling that is silently ignored is
    a curator's decision that looks applied and is not, which is the failure
    mode every decisions file in this project is written to avoid.
    """


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise CollisionRulingError(message)


def load_collision_rulings(
    path: Path | None = None,
) -> dict[tuple[str, str, str], CollisionRuling]:
    """The rulings, keyed on the collision they answer.

    The key is `(flow_object_id, context_iri, unit)` -- the same triple
    `pipeline.collisions` keys its queue item on, so a ruling and the item it
    answers are found by the same string.
    """
    filepath = path or DECISIONS_FILEPATH
    if not filepath.exists():
        return {}
    payload = orjson.loads(filepath.read_bytes())
    _require(isinstance(payload, dict), f"{filepath.name} is not an object")
    version = payload.get("schema_version")
    _require(
        version == DECISIONS_SCHEMA_VERSION,
        f"{filepath.name} is schema version {version!r}; this reads "
        f"{DECISIONS_SCHEMA_VERSION}",
    )
    rows = payload.get("decisions")
    _require(isinstance(rows, list), f"{filepath.name} carries no decisions list")

    index: dict[tuple[str, str, str], CollisionRuling] = {}
    for position, row in enumerate(rows):
        _require(isinstance(row, dict), f"decision {position} is not an object")
        decision = str(row.get("decision") or "").strip()
        _require(
            decision == MERGE,
            f"decision {position} says {decision!r}; only {MERGE!r} is understood",
        )
        survivor = str(row.get("survivor_elementary_flow_id") or "").strip()
        merged = tuple(
            str(value).strip()
            for value in row.get("merged_elementary_flow_ids") or ()
            if str(value).strip()
        )
        ruling = CollisionRuling(
            flow_object_id=str(row.get("flow_object_id") or "").strip(),
            context_iri=str(row.get("context_iri") or "").strip(),
            unit=str(row.get("unit") or "").strip(),
            survivor=survivor,
            merged=merged,
            names=tuple(str(value) for value in row.get("names") or ()),
            comment=str(row.get("comment") or "").strip(),
        )
        _require(
            all(ruling.key), f"decision {position} does not name a collision"
        )
        _require(survivor != "", f"decision {position} names no survivor")
        _require(merged != (), f"decision {position} merges no flow")
        _require(
            survivor not in merged,
            f"decision {position} merges {survivor} onto itself",
        )
        _require(
            len(set(merged)) == len(merged),
            f"decision {position} names a merged flow twice",
        )
        _require(
            ruling.key not in index,
            f"decision {position} repeats the collision {'|'.join(ruling.key)}",
        )
        index[ruling.key] = ruling
    return index


def _provenance(*, ruling: CollisionRuling, source_flow_id: str) -> Provenance:
    return Provenance(
        was_generated_by=GENERATED_BY,
        was_attributed_to="brightway-flows",
        had_primary_source=[f"urn:uuid:{source_flow_id}"],
        was_derived_from=DECISIONS_FILEPATH.name,
    )


def _union_factors(
    *,
    survivor: Any,
    merged_row: Any,
    ruling: CollisionRuling,
) -> Counter:
    """Add the factors *merged_row* holds and *survivor* does not, then settle
    the numbers on the factors both of them publish.

    The union is the part only a ruling does: a curator has said these two rows
    are one flow, so the characterisation of both applies to the survivor.  The
    settling is `pipeline.deduplication`'s and is shared with it, because "both
    rows publish this method and give it different numbers" is one question
    however the two rows came to be one flow (#63).

    Order matters between them.  A factor carried across arrives holding the
    only number anybody published for it, so there is nothing left to settle
    about it; running the union first is what keeps it out of the settling's
    counts.
    """
    survivor_rows = list(survivor.lcia_methods or [])
    held = {key for key in (factor_key(row) for row in survivor_rows) if key}
    counts: Counter = Counter()
    for factor in merged_row.lcia_methods or []:
        key = factor_key(factor)
        if not key or key in held:
            continue
        # A copy, because the row stays on the flow it came from as well, and
        # the two go on to be settled and published separately.  `replace`
        # rather than the record itself: the provenance being written is the
        # statement that *this* copy arrived by a ruling.
        carried = replace(
            factor,
            provenance=_provenance(
                ruling=ruling, source_flow_id=merged_row.elementary_flow_id
            ),
            superseded_values=list(factor.superseded_values),
        )
        survivor_rows.append(carried)
        held.add(key)
        counts["collision_ruling_factors_added"] += 1
    if counts["collision_ruling_factors_added"]:
        survivor.lcia_methods = survivor_rows

    settled = settle_factor_values(
        survivor=survivor,
        dropped=merged_row,
        generated_by=GENERATED_BY,
        derived_from=DECISIONS_FILEPATH.name,
    )
    for name, value in settled.items():
        counts[f"collision_ruling_{name}"] += value
    return counts


def _carry_source_refs(
    *,
    survivor: Any,
    merged_row: Any,
    ruling: CollisionRuling,
) -> int:
    """Move *merged_row*'s source references onto the survivor.

    A source list that resolved onto the deprecated flow resolved onto this
    substance in this context, and that is what the survivor now is.  Refs are
    compared whole: two references that agree on every field are one reference,
    and nothing here can tell two that differ apart.
    """
    existing = list(survivor.source_refs or [])
    seen = {orjson.dumps(ref, option=orjson.OPT_SORT_KEYS) for ref in existing}
    carried = 0
    for ref in merged_row.source_refs or []:
        signature = orjson.dumps(ref, option=orjson.OPT_SORT_KEYS)
        if signature in seen:
            continue
        moved = dict(ref)
        moved["provenance"] = _provenance(
            ruling=ruling, source_flow_id=merged_row.elementary_flow_id
        )
        existing.append(moved)
        seen.add(signature)
        carried += 1
    if carried:
        survivor.source_refs = existing
    return carried


def apply_collision_rulings(
    *,
    flows: Iterable[Flow],
    elementary_flows: Iterable[Any],
    rulings: Mapping[tuple[str, str, str], CollisionRuling] | None = None,
    writes: LayerWriteLog | None = None,
) -> Counter:
    """Collapse the collisions a curator has ruled on, and tally what happened.

    A ruling whose collision is not in this build is counted, not raised on: a
    bounded run holds a few hundred flows and will match almost none of them,
    and a file of rulings that only a full build can load would be a file nobody
    could develop against.

    A ruling that names a compartment its own flows are not in is counted
    *separately* and logged, because it is not that at all -- it is an
    authoring mistake, and it looked identical to a bounded run until #106.  A
    ruling can only be told apart from a bounded one by asking where the flows
    it names actually are, which is a question a full build can answer and a
    loader cannot.

    A ruling whose collision is present but no longer holds the same flows is
    counted and logged and *not applied*, which is the same reasoning
    `contested-cas-decisions.json` uses for a changed name set: a ruling written
    about different data should not go on being obeyed silently.

    The deprecation reaches the flow through *writes*, so it reaches the
    changelog.  The pass beside this one deprecates too, from a signature rather
    than from a decision, and recorded its deprecations from #92 onwards while
    these -- the ones a curator is most likely to come looking for -- left no
    trace at all (#94).
    """
    index = load_collision_rulings() if rulings is None else dict(rulings)
    log = LayerWriteLog() if writes is None else writes
    counts: Counter = Counter()
    counts["collision_rulings"] = len(index)
    if not index:
        return counts

    live_by_key: dict[tuple[str, str, str], list[Any]] = {}
    key_by_flow: dict[str, tuple[str, str, str]] = {}
    for row in elementary_flows:
        if is_deprecated(row):
            continue
        row_key = collision_key(row)
        live_by_key.setdefault(row_key, []).append(row)
        key_by_flow[str(getattr(row, "elementary_flow_id", "") or "")] = row_key

    flow_by_uuid = {flow.uuid: flow for flow in flows}

    for key, ruling in index.items():
        group = live_by_key.get(key) or []
        present = {
            str(getattr(row, "elementary_flow_id", "") or "") for row in group
        }
        if len(group) < 2:
            elsewhere = {key_by_flow.get(member) for member in ruling.members}
            if len(elsewhere) == 1 and None not in elsewhere:
                # Every flow the ruling names is live in this build, together,
                # under a *different* key -- so this is a ruling written about
                # the wrong collision rather than one outside a bounded run,
                # and the two must not read alike.  Seven rulings named
                # `envi-air-hist15me` and their flows were all in
                # `envi-air-mest15me-ru10pesq`, because EF 3.1 calls that one
                # compartment `Emissions to non-urban air or from high stacks`
                # and the ruling was written from the second half of the name.
                # Each applied to nothing, silently, and three collisions #44
                # had already decided went on being published twice (#106).
                found = next(iter(elsewhere))
                counts["collision_rulings_misplaced"] += 1
                logger.warning(
                    "collision_ruling_names_the_wrong_collision",
                    collision="|".join(key),
                    flows_are_in="|".join(found),
                    ruled_about=sorted(ruling.members),
                )
                continue
            counts["collision_rulings_absent"] += 1
            continue
        if present != ruling.members:
            counts["collision_rulings_stale"] += 1
            logger.warning(
                "collision_ruling_group_changed",
                collision="|".join(key),
                ruled_about=sorted(ruling.members),
                found=sorted(present),
            )
            continue

        by_id = {row.elementary_flow_id: row for row in group}
        survivor = by_id[ruling.survivor]
        for merged_id in ruling.merged:
            merged_row = by_id[merged_id]
            counts.update(
                _union_factors(
                    survivor=survivor, merged_row=merged_row, ruling=ruling
                )
            )
            counts["collision_ruling_source_refs_carried"] += _carry_source_refs(
                survivor=survivor, merged_row=merged_row, ruling=ruling
            )
            replacement = f"urn:uuid:{ruling.survivor}"
            merged_row.owl_deprecated = True
            merged_row.dcterms_is_replaced_by = replacement
            merged_row.is_replaced_by_uuid = ruling.survivor
            flow = flow_by_uuid.get(merged_id)
            if flow is not None:
                # The curator's own words on the row, because a deprecation
                # nothing explains is the thing a curator opens the changelog
                # to explain.
                comment = f"merged onto {ruling.survivor} by curator ruling"
                if ruling.comment:
                    comment = f"{comment}: {ruling.comment}"
                for name, value in (
                    ("owl_deprecated", True),
                    ("dcterms_is_replaced_by", replacement),
                    ("is_replaced_by_uuid", ruling.survivor),
                ):
                    log.write(
                        flow, name, value,
                        pass_name=GENERATED_BY,
                        comment=comment,
                    )
            else:
                # The harmonised flow the elementary row was built from is
                # missing, so the export would publish the deprecation on one
                # of the two records and not the other.
                counts["collision_ruling_flow_missing"] += 1
                logger.warning(
                    "collision_ruling_flow_missing",
                    collision="|".join(key),
                    flow=merged_id,
                )
            counts["collision_ruling_flows_deprecated"] += 1
        counts["collision_rulings_applied"] += 1

    logger.info("applied_collision_rulings", **dict(counts))
    return counts
