"""Hand-authored corrections to input data, applied before anything reads it.

Every flow list we ingest has errors, and they are not all the same *kind* of
error, so this is deliberately not one function per list.  A fix names what to
match, what field to change, and why; which list it belongs to is the file it
sits in, not a branch in the code.

Two operations, because two things go wrong with vendor data:

``new_value``
    Replace a field.  A CAS that names the wrong isomer, a unit that was
    mistyped.  Optionally guarded by ``original_value``, so a fix that no
    longer describes the data is skipped rather than applied blindly.

``remove_value``
    Drop an identifier the flow should not be carrying.  The case this exists
    for is an identifier that belongs to a *mixture* appearing on its
    constituents: EF 3.1 puts EINECS 232-319-8, which names pyrethrins, on both
    ``jasmolin i`` and ``jasmolin ii``.  Identifiers are how the merge decides
    two things are the same substance, so a shared one makes two distinct
    constituents indistinguishable.  Replacing the field is the wrong shape
    here -- on a list-valued field the other entries in it are correct and must
    survive, and on a scalar there is no replacement to write: the flow has no
    registry number, which is the whole of what the fix says.

    So a list drops the one entry and a scalar is cleared to ``None``, which is
    what `pipeline.loading` reads as "no number" already.  Only clearing the
    scalar was missing, and its absence was silent: a `remove_value` on
    ``cas_number`` fell through the list check and reported itself applied
    while changing nothing, which is how ecoinvent's brine kept water's
    registry number in all five versions after a curator had taken it off.

One fix carries a number as well as a value, and only one kind can:

``conversion_factor``
    On a fix that rewrites ``unit``, how many of the new unit one of the old one
    is.  A unit rewrite is not like the others -- a CAS that names the wrong
    isomer is simply wrong, but a vendor measuring standing wood in kilograms is
    not wrong, it is measuring the same resource another way, and rebasing it
    onto the unit the rest of the list uses discards a fact unless the factor is
    kept.  With it the rewrite stops being a silent reinterpretation of the
    vendor's amounts: the pair is published as ``qudt:conversionMultiplier`` on
    the flow's ``xkos:ConceptAssociation``, beside a source concept that still
    states the unit the vendor shipped.  That is the same place, and the same
    property, a factor from a correspondence table lands in --
    :mod:`brightway_flows.merge.conversions` -- and it exists here because a
    list with no correspondence table had nowhere to say it.

    ``original_value`` is required with it, so the fix declares both halves of
    the pair rather than depending on what the row happened to hold when it ran.
    That is also what makes it idempotent: a second pass finds the unit already
    rewritten and can still record which unit it was rewritten *from*.

One more key, and it only means anything on a fix that rewrites ``name``:

``retain_original_as_synonym``
    Keep the spelling the fix replaced, as an alternative label on the row, so
    that a reader searching the published list for the vendor's own name still
    finds the substance.  ecoinvent and EF 3.1 both write ``Silver-110`` for
    what is measured as ``Silver-110m``, and correcting the name is right --
    but the correction also deletes the only string a consumer holding one of
    those inventories knows the substance by, and nothing downstream can put it
    back.  `flow-object-overrides.json` already states the principle for the
    other way a name gets overruled: "every member name that is not the stated
    label becomes an alternative label on the object, so a source's own
    spelling stays searchable".

    Opt-in rather than automatic, because most of what these files rewrite is
    not a name.  ``Palladium-234m`` corrected to ``Protactinium-234m`` names a
    different element, and the column-wrap repairs replace strings like
    ``eico- safluoro`` that are not words in any language.  Retaining those
    would publish a wrong name and a corrupted one as things the substance is
    called.  So the flag asserts something a curator has checked: that the
    replaced string is a name this substance genuinely has, and only the
    preferred one was wrong.

    Written to ``altLabel`` rather than to ``synonyms`` because ``synonyms`` is
    not published: `bootstrap_labels` moves ``name`` into ``prefLabel`` and
    clears both legacy fields, and only ``altLabel`` survives it.

    Re-applied on a pass that finds the rename already done, where the fix
    matches on the name it replaces.  That is not belt and braces: the flag used
    to take effect only on the pass that actually renamed, so a flag added to a
    fix whose rows the *stored extraction* had already renamed never wrote
    anything at all, on that build or any later one.  ``Silver-110`` was missing
    from the published list for that reason, which is the very thing #24 added
    the flag to prevent.  Retention is idempotent by construction, so re-doing
    it costs a comparison.

Matching is on any field, not only ``uuid``.  EF 3.1 repeats a substance once
per context, 13 flows each for the two jasmolins, so a uuid-keyed rule would
state itself 26 times and go stale the moment a context is added.  Matching on
CAS states the rule once, about the substance.

Both operations are idempotent, and two call sites depend on that.  The base
list has its fixes applied twice -- once when `extract` writes the derived
artifact, once when the transform reads it back (#237) -- so applying a fix to
data that already carries it has to be a silent no-op rather than a warning.
That holds for a fix that changes the field it matches on, too: it cannot match
a second time, and "matched nothing" is checked against the value it *would*
have written before it is reported.

Rows here are dicts by design: this runs at the I/O boundary, before records
exist, and it names the source list's own field names.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import orjson
import structlog

from brightway_flows.domain.common import Provenance
from brightway_flows.domain.labels import Label

logger = structlog.get_logger(__name__)

#: Fields a fix may touch.  A whitelist rather than free rein: a typo in
#: `field` would otherwise add a key nothing reads, and the fix would look
#: applied while changing nothing.  Both spellings appear because source lists
#: ship singular scalars (`cas_number`) and extracted EF 3.1 rows ship plural
#: lists (`cas_numbers`).
MUTABLE_FIELDS = frozenset({
    "cas_number", "cas_numbers",
    "ec_number", "ec_numbers",
    "name", "unit", "context", "synonyms",
    # A vendor's free-text note on the flow, which is published.  Here so that a
    # fix can say, on the row itself, what a reader of the published list needs
    # to know and the vendor did not write down: borate is the ion and borax is
    # a particular sodium salt of it, and EF 3.1 gives both the salt's registry
    # number (#106).  A comment is the only field on these two rows that can
    # carry that, since neither name nor number is wrong once the number is off
    # the ion.
    "general_comment",
})

#: Asks a ``name`` rewrite to keep the spelling it replaced as an alternative
#: label.  Off unless a fix says otherwise: see the module docstring for why a
#: replaced name is usually not a name.
RETAIN_ORIGINAL_KEY = "retain_original_as_synonym"

#: Where a `conversion_factor` is recorded on the row it applies to.  Read by
#: `brightway_flows.merge.conversions.conversion_from_source_flow`, which is
#: the only consumer; it survives normalisation in `Flow.extra`, which exists to
#: round-trip keys the record class does not declare.
#:
#: Underscored for the same reason `_provided` is: it is this pipeline talking
#: to itself about a row, not a field any source list ships.
UNIT_CONVERSION_KEY = "_unit_conversion"


def fix_criteria(fix: dict[str, Any]) -> dict[str, Any]:
    """What *fix* matches on, as one mapping.

    ``uuid`` is shorthand for the commonest criterion, and what every existing
    fixes file is written in terms of.  Public because a fix's criteria are read
    outside this module too -- ``tests/test_cross_version_manual_fixes.py`` asks
    whether a correction one version states is still needed by another -- and a
    second copy of this rule would be free to drift from the one the pipeline
    applies.
    """
    criteria = dict(fix.get("match") or {})
    if "uuid" in fix:
        criteria["uuid"] = fix["uuid"]
    return criteria


def _conversion_declared_by(
    fix: dict[str, Any], *, index: int, filename: str
) -> dict[str, Any] | None:
    """The unit pair and factor *fix* states, or ``None`` if it states none.

    Every condition here is an authoring mistake rather than a data condition,
    so each raises.  A factor that is quietly ignored is worse than one that
    fails the build: the file would go on claiming the vendor's amounts are
    convertible while the published mapping said nothing.

    :raises ValueError: if the factor is on a fix that does not rewrite
        ``unit``, does not also declare ``original_value``, or is not a positive
        real number.
    """
    if "conversion_factor" not in fix:
        return None
    if fix.get("field") != "unit" or "new_value" not in fix:
        raise ValueError(
            f"Manual fix {index} in {filename} states a `conversion_factor` but "
            f"does not rewrite `unit`. A factor converts one unit to another; on "
            f"any other field there is nothing for it to convert."
        )
    if "original_value" not in fix:
        raise ValueError(
            f"Manual fix {index} in {filename} states a `conversion_factor` "
            f"without `original_value`. The factor is a statement about a pair of "
            f"units, so the fix has to name both rather than depend on what the "
            f"row held when it ran."
        )
    factor = fix["conversion_factor"]
    if isinstance(factor, bool) or not isinstance(factor, (int, float)):
        raise ValueError(
            f"Manual fix {index} in {filename} has a non-numeric "
            f"`conversion_factor`: {factor!r}."
        )
    if not factor > 0 or factor == float("inf"):
        raise ValueError(
            f"Manual fix {index} in {filename} has a `conversion_factor` of "
            f"{factor!r}. One unit is a positive number of another."
        )
    return {
        "source_unit": str(fix["original_value"]),
        "target_unit": str(fix["new_value"]),
        "factor": float(factor),
        "comment": str(fix.get("comment") or "").strip(),
    }


def matches(flow: dict[str, Any], criteria: dict[str, Any]) -> bool:
    """Does *flow* satisfy every criterion?

    A criterion matches a list-valued field if the wanted value is *in* it, so
    ``{"cas_numbers": "4466-14-2"}`` matches a row carrying that CAS among
    others, and a scalar field if it is equal.
    """
    for key, wanted in criteria.items():
        actual = flow.get(key)
        if isinstance(actual, list):
            if wanted not in actual:
                return False
        elif actual != wanted:
            return False
    return True


def apply_manual_fixes(
    flows: list[dict[str, Any]],
    path: Path,
    *,
    label: str = "",
    quiet: bool = False,
) -> list[dict[str, Any]]:
    """Apply the corrections in *path* to *flows*, in place.

    Returns the same list object.  A missing file is not an error: a list with
    no corrections is the normal state of a list on the day it is added.

    *quiet* drops the per-fix log lines, for a caller applying a file to one
    row at a time -- the lookup, asking about a query -- where "this fix
    matched nothing" is the ordinary case for every fix but one and not a
    signal that the file has gone stale.  Authoring mistakes still raise.

    :raises ValueError: if a fix has no comment, or names a field outside
        :data:`MUTABLE_FIELDS`.  Both are authoring mistakes, and a fix that
        silently does nothing is worse than one that fails: the file would go
        on asserting a correction that is not happening.
    """
    if not path.exists():
        logger.debug("no_manual_fixes_file", path=str(path), source=label)
        return flows

    payload = orjson.loads(path.read_bytes())
    fixes: list[dict[str, Any]] = payload.get("fixes", [])

    applied = 0
    for index, fix in enumerate(fixes):
        comment = str(fix.get("comment") or "").strip()
        field = fix.get("field")
        if not comment:
            raise ValueError(
                f"Manual fix {index} in {path.name} has no comment. A fix changes "
                f"source data, so it has to say why."
            )
        if field not in MUTABLE_FIELDS:
            raise ValueError(
                f"Manual fix {index} in {path.name} names field {field!r}, which is "
                f"not one of {sorted(MUTABLE_FIELDS)}."
            )

        has_set = "new_value" in fix
        has_remove = "remove_value" in fix
        if has_set == has_remove:
            raise ValueError(
                f"Manual fix {index} in {path.name} needs exactly one of "
                f"`new_value` or `remove_value`."
            )

        criteria = fix_criteria(fix)
        if not criteria:
            raise ValueError(
                f"Manual fix {index} in {path.name} matches nothing: give `uuid` "
                f"or `match`."
            )

        conversion = _conversion_declared_by(fix, index=index, filename=path.name)

        matched = [flow for flow in flows if matches(flow, criteria)]
        if not matched:
            # A fix that *renames* on the field it matches cannot match twice:
            # after the first pass the rows hold `new_value` and the criterion
            # still names the value they had before.  The base list applies its
            # fixes at extract and again when the transform reads the derived
            # file back (#237), so every such fix warned on the second pass
            # that it had matched nothing -- which reads exactly like the fix
            # having gone stale, and is the one signal a curator has for that.
            #
            # Look for the rows under the value the fix would have written. If
            # they are there, the fix has landed and there is nothing to say.
            if has_set and field in criteria:
                already = dict(criteria)
                already[field] = fix["new_value"]
                renamed = [flow for flow in flows if matches(flow, already)]
                if renamed:
                    # The retained spelling is re-applied here rather than only
                    # on the pass that renames.  It is idempotent, and without
                    # it the flag only ever took effect if `extract` happened to
                    # run after the flag was added: on any later pass the rows
                    # already hold the new name, this branch fires, and the
                    # synonym was never written.  `Silver-110` was gone from the
                    # published list for that reason, which is exactly what
                    # #24 added the flag to prevent.
                    if field == "name" and fix.get(RETAIN_ORIGINAL_KEY):
                        for flow in renamed:
                            _retain_as_alt_label(flow, criteria[field], source=label)
                    if not quiet:
                        logger.info(
                            "manual_fix_already_applied",
                            source=label, index=index, criteria=criteria, field=field,
                        )
                    continue
            if not quiet:
                logger.warning(
                    "manual_fix_matched_nothing",
                    source=label, index=index, criteria=criteria, field=field,
                )
            continue

        changed = 0
        for flow in matched:
            current = flow.get(field)
            if conversion is not None:
                # Before the already-applied check below, not after it: the
                # record is about the pair the fix declares, and a row that
                # already holds the new unit still has to say which unit it was
                # rebased from.  Both halves come from the fix rather than from
                # the row, so writing it twice writes the same thing.
                flow[UNIT_CONVERSION_KEY] = dict(conversion)
            if has_set:
                if current == fix["new_value"]:
                    # Already applied.  Same reasoning as `remove_value` below,
                    # and it has to come before the guard: once the fix has
                    # landed, `current` is the new value and no longer the
                    # original, so the guard would read a successful fix as a
                    # mismatch and warn about it on every subsequent pass.
                    continue
                if "original_value" in fix and current != fix["original_value"]:
                    logger.warning(
                        "manual_fix_original_value_mismatch",
                        source=label, index=index, field=field,
                        expected_original=fix["original_value"], actual_current=current,
                    )
                    continue
                if field == "name" and fix.get(RETAIN_ORIGINAL_KEY):
                    _retain_as_alt_label(flow, current, source=label)
                flow[field] = fix["new_value"]
            elif isinstance(current, list):
                if fix["remove_value"] not in current:
                    # Already absent: the fix has been applied, or the data
                    # moved on.  Not worth a warning per matched row.
                    continue
                flow[field] = [x for x in current if x != fix["remove_value"]]
            else:
                # A scalar the source list ships singular -- ecoinvent's
                # `cas_number`.  Cleared rather than dropped from the row so
                # that the key stays where every reader looks for it, and to
                # `None` rather than `""` because that is what a flow with no
                # number arrives as.  Idempotent for the same reason the list
                # branch is: on a second pass the value is already gone and no
                # longer equals what the fix names.
                if current != fix["remove_value"]:
                    continue
                flow[field] = None
            changed += 1

        if changed:
            applied += 1
        if not quiet:
            logger.info(
                "manual_fix_applied",
                source=label, index=index, criteria=criteria, field=field,
                operation="set" if has_set else "remove",
                rows_changed=changed, comment=comment,
            )

    if not quiet:
        logger.info(
            "manual_fixes_complete",
            source=label, path=str(path), total=len(fixes), applied=applied,
        )
    return flows


def _retain_as_alt_label(flow: dict[str, Any], replaced: Any, *, source: str) -> None:
    """Add *replaced* to *flow*'s alternative labels, once, with provenance.

    Idempotent for the reason everything else here is: the base list applies
    its fixes twice (#237), and a label added on the first pass must not be
    added again on the second.  The comparison is on the label text alone --
    provenance differs between a label this writes and the same string arriving
    from ChEBI, and the question is whether the name is already on the row.

    Nothing is retained where the row has no name to retain, which is the case
    for a fix that fills an empty field rather than correcting a wrong one.
    """
    text = str(replaced or "").strip()
    if not text:
        return
    existing = flow.get("altLabel")
    labels: list[Any] = list(existing) if isinstance(existing, list) else []
    for entry in labels:
        value = entry.get("@value") if isinstance(entry, dict) else entry
        if isinstance(value, str) and value.strip().casefold() == text.casefold():
            return
    labels.append(
        Label(
            value=text,
            source=Provenance(
                was_generated_by="manual_fixes",
                was_attributed_to="brightway-flows",
                had_primary_source=[source or "manual fix"],
                was_derived_from="name the fix replaced, retained as altLabel",
            ).to_dict(),
        ).to_dict()
    )
    flow["altLabel"] = labels
