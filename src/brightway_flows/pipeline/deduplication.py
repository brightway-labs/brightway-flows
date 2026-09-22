"""Detection and deprecation of duplicate elementary flows.

Two elementary flows that agree on every semantic field are the same flow. The
one with the most LCIA characterisation factors is kept; the rest are marked
deprecated and pointed at it.

**And where both of them publish one factor, the number is settled here too**,
because this is the module that decides which row survives and so the module
that decides which number does.  It used to decide it by accident: the factors
are not part of the signature, so two rows publishing `0.000118` and
`0.00011755` for one method are duplicates, the row holding more factors is
kept, and where that ties -- it usually does -- the identifier breaks it.  Over
the 130 collapses of the 2026-08-12 build, 68 factors are published twice with
different numbers, and the number that survived was chosen by a sort that never
looked at it (#63).

So `settle_factor_values` does three things a sort cannot: it prefers the more
precise of two numbers where they are one number written twice, it writes the
number it did not keep onto the factor that kept it, and it says out loud when
two numbers are too far apart to be one number rounded -- 66 of those 68, by up
to 400 times.  A gap that size is not a duplicate publishing its number twice,
it is a decision about which source to believe, and until now nothing said it
was being made.

The number it did not keep becomes a `SupersededValue` on the factor that kept
it, so a value this pass *refused* to write is as findable as one it wrote --
which is the whole of #63: the loser used to vanish.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from typing import Any

import orjson
import structlog

from brightway_flows.domain.common import Provenance
from brightway_flows.domain.elementary_flow import ElementaryFlow
from brightway_flows.domain.flow import Flow
from brightway_flows.domain.lcia.records import (
    StatedFactor,
    SupersededValue,
    non_zero_factor_count,
)
from brightway_flows.pipeline.layer_writes import LayerWriteLog
from brightway_flows.domain.vocabulary import (
    DCTERMS_IS_REPLACED_BY,
    DCTERMS_IS_REPLACED_BY_CURIE,
    OWL_DEPRECATED,
    OWL_DEPRECATED_CURIE,
)
from brightway_flows.flow_layers.contested_cas import (
    FACTOR_TOLERANCE,
    more_precise_value,
)

logger = structlog.get_logger(__name__)

#: `prov:wasGeneratedBy` on a number this pass settles.  A curated ruling
#: settles its own under its own name, so a reader can tell a number a person
#: decided about from a number a signature collapsed.
GENERATED_BY = "pipeline.deduplication"


#: The keys the duplicate signature does not compare: the identity itself, the
#: factors the survivor is then chosen by, the source references, and the
#: deprecation fields this pass writes.  Everything else is compared, so a key
#: absent from this set is a key that can hold two otherwise identical flows
#: apart -- which is the question `pipeline/collisions.py` reports and the
#: collision queue's page reads back.  Named rather than inlined so that the
#: page can say what deduplication compares without restating the rule.
SIGNATURE_EXCLUDED_KEYS: frozenset[str] = frozenset({
    "elementary_flow_id",
    "lcia_methods",
    "source_refs",
    OWL_DEPRECATED,
    DCTERMS_IS_REPLACED_BY,
    "is_replaced_by_uuid",
    OWL_DEPRECATED_CURIE,
    DCTERMS_IS_REPLACED_BY_CURIE,
})



def signed_on_fields(row: Any) -> dict[str, Any]:
    """The fields this module compares when it asks whether two flows are one."""
    to_dict = getattr(row, "to_dict", None)
    if to_dict is None:
        return {}
    return {key: value for key, value in to_dict().items() if key not in SIGNATURE_EXCLUDED_KEYS}


def fields_holding_apart(rows: Iterable[Any]) -> list[str]:
    """Which signed-on fields differ across *rows* -- what stops them collapsing.

    The collision queue reports two live flows that share a substance, a context
    and a unit, and a curator's first question about such a pair is what is left
    keeping them apart.  Answering it from this module rather than beside the
    queue is the point: a field this does not sign on is not holding anything
    apart, however different it looks.  A preferred label is the example -- 74 of
    the 116 groups in the 2026-08-12 build differ in theirs, and none of them is
    held apart by it, because a name is not on the record this signs.  That is
    #31 exactly: the water pair differed only in name and was collapsed.

    Rows with no `to_dict()` contribute nothing, so the collision guard's own
    duck-typed reading of a flow stays possible.
    """
    signed = [signed_on_fields(row) for row in rows]
    signed = [row for row in signed if row]
    if len(signed) < 2:
        return []
    keys: set[str] = set()
    for row in signed:
        keys.update(row)
    differing = []
    for key in sorted(keys):
        rendered = {
            orjson.dumps(row.get(key), option=orjson.OPT_SORT_KEYS) for row in signed
        }
        if len(rendered) > 1:
            differing.append(key)
    return differing


def duplicate_survivor_rank(row: Any) -> tuple[int, str]:
    """How this module orders a duplicate group: the first row is the one kept.

    Most characterisation factors first; the identifier only breaks a tie.  A
    named function rather than an inline sort key because `pipeline/collisions`
    tells a curator which flow this would keep, and a second statement of the
    rule is a statement that drifts -- it said "the lowest identifier", which
    named the wrong flow on 27 of 116 groups and, on 26 of those, pointed at the
    flow holding no factors over the one holding all of them (#58).
    """
    return (
        -non_zero_factor_count(getattr(row, "lcia_methods", None)),
        str(getattr(row, "elementary_flow_id", "") or ""),
    )


def factor_key(factor: StatedFactor) -> str:
    """What makes two characterisation rows the same factor.

    The method identifier and the place, because that is what a factor answers:
    one number per method per flow per geography.  Falling back to the method's
    name keeps a source that publishes no identifier -- ecoinvent's workbook
    states none for a category any more than for a flow -- from having every one
    of its rows read as distinct.

    The geography joined the key with #314's PR 3b, which is what let it be
    read at all.  It changes no outcome in the build of 2026-08-16 and could not:
    no flow that took part in a collapse carries more than one row of any one
    method, so no pair this settles is a pair the place would have separated.
    """
    for value in (factor.category.uuid, factor.category.name):
        if isinstance(value, str) and value.strip():
            key = value.strip()
            return f"{key}@{factor.geography}" if factor.geography else key
    return ""


def _relative_difference(left: float, right: float) -> float | None:
    """How far apart two published numbers are, as a fraction of the smaller.

    `None` where the question does not arise: a relative difference is not
    defined across zero, and an uptake credit against an emission is a question
    about sign conventions rather than about a number.  `worst_disagreement`
    skips exactly these pairs for exactly this reason.
    """
    if left == 0 or right == 0 or (left > 0) != (right > 0):
        return None
    low, high = sorted((abs(left), abs(right)))
    return high / low - 1


def _provenance_for(
    *, source_flow_id: str, generated_by: str, derived_from: str | None
) -> Provenance:
    return Provenance(
        was_generated_by=generated_by,
        was_attributed_to="brightway-flows",
        had_primary_source=[f"urn:uuid:{source_flow_id}"],
        was_derived_from=derived_from,
    )


def settle_factor_values(
    *,
    survivor: Any,
    dropped: Any,
    generated_by: str,
    derived_from: str | None = None,
) -> Counter:
    """Settle the numbers where *survivor* and *dropped* both publish a factor.

    Only where both publish it.  A factor only *dropped* holds is a different
    question -- whose characterisation applies to this flow -- and it is the one
    a curator answers in `pipeline/collision_decisions.py`; nothing here unions
    a factor set, which is why this can run over every duplicate group without
    deciding anything a person has not.  What both rows publishing one factor
    settles is narrower and needs no curator: they agree that this method
    characterises this flow, and differ only in the number.

    **The more precise number wins**, where the two are one number written
    twice.  EF publishes a refrigerant under an industry designation and a
    chemical name and gives the freshwater ecotoxicity as `0.000118` on one and
    `0.00011755` on the other; `more_precise_value` is what says those are one
    number, and it refuses far more than it accepts.

    **The number not kept is written down either way** -- onto the factor row
    that kept the other one, naming the flow that published it.  Whichever
    number stands, the other was published by a real source list about this
    substance in this context, and dropping it without trace leaves nothing a
    reader could use to tell that a number was chosen rather than simply
    published.

    **A gap too large to be rounding is logged and counted.**  Discarding a
    number 400 times the one kept is not a merge, it is a decision about which
    source to believe, and it should not pass in silence.  It is still not
    *refused*: this runs after the pipeline has already concluded that these two
    rows are one flow -- on a signature, or on a curator's ruling -- and
    refusing here would leave a duplicate standing while everything else
    treated it as collapsed.  The warning and the count are how somebody sees
    it.

    The survivor's row is edited in place rather than replaced, so the
    harmonised flow -- which shares the row with its elementary record -- states
    the same number as the elementary flow.  Two artifacts giving one factor two
    values would be a worse answer than the one this replaces.
    """
    counts: Counter = Counter()
    held: dict[str, StatedFactor] = {}
    for factor in survivor.lcia_methods or []:
        key = factor_key(factor)
        if key and key not in held:
            held[key] = factor

    for factor in dropped.lcia_methods or []:
        kept = held.get(factor_key(factor))
        if kept is None:
            continue
        kept_value, other_value = kept.amount, factor.amount
        if kept_value == other_value:
            continue

        counts["factor_values_differ"] += 1
        if more_precise_value(kept_value, other_value) == other_value:
            kept.amount = other_value
            kept.provenance = _provenance_for(
                source_flow_id=dropped.elementary_flow_id,
                generated_by=generated_by,
                derived_from=derived_from,
            )
            counts["factors_made_precise"] += 1
            declined, declined_by = kept_value, survivor.elementary_flow_id
        else:
            declined, declined_by = other_value, dropped.elementary_flow_id

        relative = _relative_difference(kept_value, other_value)
        if relative is None or relative > FACTOR_TOLERANCE:
            counts["factor_values_conflict"] += 1
            logger.warning(
                "merged_factor_values_conflict",
                settled_by=generated_by,
                flow=survivor.elementary_flow_id,
                superseded=dropped.elementary_flow_id,
                factor=factor_key(kept),
                kept=kept.amount,
                declined=declined,
                relative_difference=relative,
            )
        kept.superseded_values.append(
            SupersededValue(
                amount=declined,
                provenance=_provenance_for(
                    source_flow_id=declined_by,
                    generated_by=generated_by,
                    derived_from=derived_from,
                ),
                relative_difference=relative,
            )
        )
    return counts


def _elementary_duplicate_signature(row: ElementaryFlow) -> str:
    return orjson.dumps(
        signed_on_fields(row), option=orjson.OPT_SORT_KEYS
    ).decode("utf-8")

def _apply_elementary_duplicate_deprecations(
    *,
    flows: list[Flow],
    elementary_flows: list[ElementaryFlow],
    writes: LayerWriteLog | None = None,
) -> dict[str, int]:
    log = LayerWriteLog() if writes is None else writes
    by_signature: dict[str, list[ElementaryFlow]] = {}
    for row in elementary_flows:
        if not row.elementary_flow_id:
            continue
        # A flow that is already deprecated is a duplication somebody has
        # already settled, and this pass must not settle it again.  The
        # signature deliberately excludes the deprecation fields, so a
        # deprecated row and the row it points at look identical here -- and
        # `duplicate_survivor_rank` would then pick between them by factor count
        # and identifier, which is how a curated ruling got reversed: EF's
        # `Energy, geothermal, converted` and `primary energy from geothermics`
        # carry no factors and, once the layering has moved their names onto the
        # object they share, nothing else the signature reads. The ruling
        # deprecated the legacy row onto the surviving one and the sort then
        # deprecated the survivor back onto the legacy row, leaving each
        # pointing at the other and a source list's mapping resolving to
        # neither (#73).  `find_collisions` excludes deprecated flows for the
        # same reason, in the same words.
        if row.owl_deprecated:
            continue
        signature = _elementary_duplicate_signature(row)
        by_signature.setdefault(signature, []).append(row)

    flow_by_uuid = {f.uuid: f for f in flows}

    duplicate_group_count = 0
    deprecated_count = 0
    settled: Counter = Counter()
    for rows in by_signature.values():
        if len(rows) < 2:
            continue
        duplicate_group_count += 1
        rows_sorted = sorted(rows, key=duplicate_survivor_rank)
        canonical_id = rows_sorted[0].elementary_flow_id
        canonical_link = f"urn:uuid:{canonical_id}" if canonical_id else ""
        for duplicate_row in rows_sorted[1:]:
            elem_id = duplicate_row.elementary_flow_id
            if not elem_id:
                continue
            settled.update(
                settle_factor_values(
                    survivor=rows_sorted[0],
                    dropped=duplicate_row,
                    generated_by=GENERATED_BY,
                )
            )
            duplicate_row.owl_deprecated = True
            duplicate_row.dcterms_is_replaced_by = canonical_link
            duplicate_row.is_replaced_by_uuid = canonical_id
            deprecated_count += 1

            flow = flow_by_uuid.get(elem_id)
            if flow is not None:
                # Through the log so a deprecation reaches the changelog: a
                # flow disappearing from the published list is the single
                # largest thing that can happen to it, and until #92 it was
                # the one change no review page could show.
                for name, value in (
                    ("owl_deprecated", True),
                    ("dcterms_is_replaced_by", canonical_link),
                    ("is_replaced_by_uuid", canonical_id),
                ):
                    log.write(
                        flow, name, value,
                        pass_name=GENERATED_BY,
                        comment=f"duplicate of {canonical_id}",
                    )

    return {
        "duplicate_elementary_group_count": duplicate_group_count,
        "deprecated_elementary_flow_count": deprecated_count,
        **{f"duplicate_{name}": value for name, value in settled.items()},
    }
