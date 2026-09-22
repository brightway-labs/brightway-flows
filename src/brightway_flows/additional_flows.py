"""Whole source flows a vendor ships somewhere the fetch does not look, and
what was decided about each.

Distinct from :mod:`brightway_flows.manual_fixes`, and the difference is
what the record *is*.  A fix names a field on a row the fetch already produced
and says the vendor got it wrong.  A row here is one the vendor got right and
the fetch never saw, because the distribution puts it in a file the adapter does
not open.  Expressed as a correction it would have nothing to attach to.

The motivating case is ecoinvent (#25).  ecoinvent publishes one
``ElementaryExchanges.xml`` per system model -- ``cutoff``, ``apos``,
``consequential`` and ``EN15804`` -- and the adapter reads ``cutoff``.  3.8's
APOS and consequential releases each carry the same three exchanges cutoff does
not: ``venting of argon, crude, liquid``, ``venting of nitrogen, liquid`` and
``residual wood, dry``, all in ``social / unspecified``.

Finding a record is not the same as accepting it, which is why a file has two
lists.  A record under ``flows`` is one the vendor got right; a record under
``excluded`` is one this list looked at and refused, with a stated reason.
Those three ecoinvent rows are the worked example of the second, and #115 is
where the difference was settled: all three are *products*.  Each duplicates an
intermediate exchange that every release from 3.8 to 3.12 carries under a stable
uuid, into an elementary list, under a compartment ecoinvent uses nowhere else;
no dataset in the release references the elementary uuid, and 3.9.1 removed all
three.  Adding them minted three consensus flows for records that were a defect
in one export of one release.

An exclusion is not a deletion, and both halves of that matter:

- The record **stays in the file**, with its evidence, so that a row refused on
  purpose and a row nobody looked at do not look alike -- the same reason a
  version with nothing to add still gets a file with an empty ``flows`` list.
- The exclusion is **enforced, not assumed**.  A uuid under ``excluded`` is
  removed from the fetched rows if it is there.  For ecoinvent it never is,
  because the adapter reads ``cutoff`` and these three are not in it -- but that
  makes the absence an accident of which file gets opened, and the day the
  adapter learns to read APOS the decision would silently reverse itself.

The other shape of refusal arrived with Stepwise 2006 (#167), and it is the
opposite case.  Stepwise is a SimaPro method file: its flows are the rows its own
factors characterise, so there is no second file shipping records the adapter
cannot see, and the six rows it refuses are ones the fetch produces on every run.
Removal is then the normal path rather than news, which is what
``excluded_rows_are_in_the_fetch`` says.  A file that sets it is telling this
module that finding the row is expected; a file that does not -- every ecoinvent
one -- keeps the reading that finding it means the evidence needs re-checking.
Nothing else about the shape changes: the record still carries the vendor's
identity for the row, still states a published reason, and is still published on
the correspondence.

What is excluded is published, on the source list's ``xkos:Correspondence``
under ``brightway:excludedSourceConcept``; see
:mod:`brightway_flows.pipeline.correspondences`.  A consumer comparing the
vendor's master data against the associations is exactly who #115 was raised by,
and the answer belongs where they are already looking rather than in this
repository.

Three records rather than four downloads of ~3.3 GB each per version, because
the divergence is closed rather than ongoing.  That is measured, not assumed:
`tools/compare_ecoinvent_system_models.py` reads all four releases of every
registered version and compares them exchange by exchange, and 3.8 is the only
version where any two disagree.  Should a later version disagree, the answer is
a manifest that names its system models, not more rows here.

**A version with nothing to add still gets a file, holding an empty ``flows``
list.**  Without one, a version whose releases were compared and agreed and a
version nobody has looked at are the same absence -- which is how
``consequential`` and ``EN15804`` went unchecked on every version for as long as
they did (#100).  The empty list is the finding, and the ``comparison`` block
above it is the evidence a later version's comparison is checked against.

A record whose uuid the fetch already produced is **dropped**, not appended.
That is what makes the file safe to leave in place if the adapter later learns
to read APOS: the fetch wins, and the run gets one flow rather than two rows
under one uuid.  Silently duplicating a uuid would be the worst outcome, since
the merge keys on it.

Rows are dicts by design, like manual fixes: this runs at the I/O boundary,
before records exist, and it names the source list's own field names.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import orjson
import structlog

logger = structlog.get_logger(__name__)

#: What a record has to carry to be a flow at all.  ``uuid`` because the merge
#: keys on it, ``context`` because a row with none is dropped before matching,
#: and ``comment`` for the same reason a manual fix needs one: this file asserts
#: that a vendor ships something the fetch cannot see, and an assertion with no
#: stated evidence cannot be checked when the vendor's next release lands.
REQUIRED_FIELDS = ("uuid", "name", "unit", "context", "comment")

#: Stripped before the record joins the fetched rows.  It is provenance for the
#: curator, not a field any consumer reads, and leaving it on would put it in
#: the published flow record.
_CURATION_ONLY = ("comment",)

#: What a record under ``excluded`` has to carry.  ``uuid``, ``name``,
#: ``context`` and ``unit`` are the source row as the vendor ships it, so that
#: the exclusion can be checked against the release rather than taken on trust,
#: and so that the published record identifies the flow to a consumer who has
#: the vendor's file and not this one.
#:
#: Both prose fields are mandatory, and they are not the same field.  ``reason``
#: is published and is addressed to a consumer who found a flow missing;
#: ``comment`` stays here and is addressed to the next curator, who needs to
#: know what was measured, when, and against which releases.  Collapsing them
#: would either publish a working note or bury the answer to the question the
#: exclusion exists to answer.
EXCLUDED_REQUIRED_FIELDS = ("uuid", "name", "unit", "context", "reason", "comment")


@dataclass(frozen=True)
class ExcludedSourceFlow:
    """One source row this list looked at and decided not to map.

    ``withdrew_identifier`` is the consensus identifier this project published
    for the row before the exclusion, and is empty for a row that was excluded
    before it ever reached a build.  It is recorded rather than derived because
    nothing in a build that no longer mints the flow can work it out -- the same
    problem, and the same answer, as the retired minted identifiers in
    :mod:`brightway_flows.pipeline.redirects`.
    """

    uuid: str
    name: str
    unit: str
    context: tuple[str, ...]
    reason: str
    source: str
    withdrew_identifier: str = ""


def load_excluded_source_flows(
    path: Path, *, source: str
) -> tuple[ExcludedSourceFlow, ...]:
    """The ``excluded`` records in *path*, in file order.

    A missing file, or one with no ``excluded`` key, yields ``()``: excluding
    nothing is the normal state of every list, and the key was added after the
    files were.

    *source* is stamped on rather than read per row, for the reason it is on an
    added row: a record in a list's file belongs to that list by construction,
    and the string is what the export keys the published block by.

    :raises ValueError: if ``excluded`` is not a list, if a record is missing
        any of :data:`EXCLUDED_REQUIRED_FIELDS`, or if a uuid is excluded twice.
        Every one of them is an authoring mistake that would otherwise produce
        an exclusion that silently applies to nothing.
    """
    if not path.exists():
        return ()
    payload = orjson.loads(path.read_bytes())
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} must contain an object.")
    rows = payload.get("excluded", [])
    if not isinstance(rows, list):
        raise ValueError(f"{path.name} has an 'excluded' key that is not a list.")

    out: list[ExcludedSourceFlow] = []
    seen: set[str] = set()
    for index, record in enumerate(rows):
        if not isinstance(record, dict):
            raise ValueError(f"Excluded record {index} in {path.name} is not an object.")
        for field_name in EXCLUDED_REQUIRED_FIELDS:
            value = record.get(field_name)
            if value is None or (isinstance(value, (str, list)) and not value):
                raise ValueError(
                    f"Excluded record {index} in {path.name} has no {field_name!r}. "
                    f"A record here refuses a flow the vendor ships, so it has to "
                    f"carry {', '.join(EXCLUDED_REQUIRED_FIELDS)}."
                )
        uuid = str(record["uuid"]).strip()
        if uuid in seen:
            raise ValueError(
                f"Excluded record {index} in {path.name} excludes {uuid} a second "
                f"time. One decision per row, or the file does not say which held."
            )
        seen.add(uuid)
        context = record["context"]
        out.append(ExcludedSourceFlow(
            uuid=uuid,
            name=str(record["name"]).strip(),
            unit=str(record["unit"]).strip(),
            context=tuple(str(part) for part in context)
            if isinstance(context, list)
            else (str(context),),
            reason=str(record["reason"]).strip(),
            source=source,
            withdrew_identifier=str(record.get("withdrew_identifier") or "").strip(),
        ))
    return tuple(out)


def apply_additional_flows(
    flows: list[dict[str, Any]],
    path: Path,
    *,
    source: str,
    label: str = "",
) -> list[dict[str, Any]]:
    """Apply the file at *path* to *flows*, in place: append what it adds and
    remove what it excludes.

    Returns the same list object.  A missing file is not an error: a list with
    no additional flows is the normal state of every list.

    The removal runs first, so that a uuid a file both adds and excludes ends up
    excluded rather than depending on which loop ran last -- and a file that
    says both is refused before either happens, since it does not state a
    decision.  Removal is normally a no-op: the rows an ``excluded`` record
    names are ones the fetch does not produce, which is how they came to need a
    curated record at all.  It exists so the exclusion is a decision rather than
    a side effect of which of the vendor's files the adapter opens (#115).

    *source* is stamped onto each record rather than declared per row.  A record
    in a list's additions file belongs to that list by construction, and the
    string is load-bearing -- context rules are keyed by it, so a row carrying
    the wrong one resolves to no context and fails into the report.

    Units are resolved here, the same way the ecoinvent adapter resolves them,
    so the file carries only what the vendor ships and ``unit_iri`` stays
    derived.  A hand-copied IRI would be a second place for `units.json` to go
    stale.

    :raises ValueError: if the payload has no ``flows`` list, if a record is
        missing any of :data:`REQUIRED_FIELDS` or
        :data:`EXCLUDED_REQUIRED_FIELDS`, if one uuid is both added and
        excluded, or if a record's unit cannot be resolved.  All of them are
        authoring mistakes, and every one would otherwise produce a row that
        looks decided and is not.
    """
    # Imported here, not at module scope: `sources` imports this module, and
    # importing a `transformers` submodule runs `transformers/__init__`, which
    # reaches `pipeline` and back into `sources`.  Same cycle `load_flows`
    # already breaks this way for `pipeline.loading`.
    from brightway_flows.transformers.unit_normalization import (
        build_units_index,
        resolve_unit_notation,
    )

    if not path.exists():
        logger.debug("no_additional_flows_file", path=str(path), source=label)
        return flows

    payload = orjson.loads(path.read_bytes())
    if not isinstance(payload, dict) or not isinstance(payload.get("flows"), list):
        raise ValueError(f"{path.name} must contain a 'flows' list.")
    records: list[dict[str, Any]] = [
        record for record in payload["flows"] if isinstance(record, dict)
    ]

    excluded = load_excluded_source_flows(path, source=source)
    excluded_uuids = {record.uuid for record in excluded}
    contradictory = excluded_uuids & {
        str(record.get("uuid") or "").strip() for record in records
    }
    if contradictory:
        raise ValueError(
            f"{path.name} both adds and excludes {', '.join(sorted(contradictory))}. "
            f"A uuid in one list or the other is a decision; in both it is none."
        )
    if excluded_uuids:
        # Whether this list's own fetch is supposed to produce the refused rows,
        # stated by the file rather than guessed at here.  It is false for
        # ecoinvent, whose exclusions name rows in a system model the adapter
        # does not read, and true for Stepwise, which ships every flow it has in
        # the one file the adapter opens -- so removal is a surprise on the one
        # list and the whole point on the other, and one log level cannot mean
        # both.
        in_the_fetch = payload.get("excluded_rows_are_in_the_fetch") is True
        removed = [
            flow for flow in flows
            if str(flow.get("uuid") or "").strip() in excluded_uuids
        ]
        for flow in removed:
            # Where the fetch is not supposed to carry the row, reaching this is
            # news: the exclusion still holds, but the reason it was written down
            # -- that the vendor ships the row somewhere the adapter does not
            # look -- has stopped being true, and the record's evidence is due a
            # re-check.  Where the fetch is supposed to carry it, this line is
            # the refusal being carried out, and a warning would cry wolf on
            # every build.
            emit = logger.info if in_the_fetch else logger.warning
            emit(
                "excluded_flow_removed_from_fetch",
                source=label or source, uuid=flow.get("uuid"), name=flow.get("name"),
            )
            flows.remove(flow)

    known = {
        flow.get("uuid")
        for flow in flows
        if isinstance(flow.get("uuid"), str) and flow["uuid"].strip()
    }
    units_index = build_units_index()

    added = 0
    superseded = 0
    for index, record in enumerate(records):
        for field in REQUIRED_FIELDS:
            value = record.get(field)
            if value is None or (isinstance(value, (str, list)) and not value):
                raise ValueError(
                    f"Additional flow {index} in {path.name} has no {field!r}. "
                    f"A record here adds a flow the fetch never saw, so it has to "
                    f"carry {', '.join(REQUIRED_FIELDS)}."
                )

        uuid = str(record["uuid"]).strip()
        if uuid in known:
            # The fetch has caught up with the file.  See the module docstring:
            # dropping is what lets the file outlive the gap it describes.
            logger.info(
                "additional_flow_already_fetched",
                source=label, index=index, uuid=uuid, name=record.get("name"),
            )
            superseded += 1
            continue

        row = {key: value for key, value in record.items() if key not in _CURATION_ONLY}
        row["uuid"] = uuid
        row.setdefault("identifier", uuid)
        row["source"] = source

        resolved = resolve_unit_notation(str(record["unit"]).strip(), units_index)
        if resolved is None:
            raise ValueError(
                f"Additional flow {index} in {path.name} has unit "
                f"{record['unit']!r}, which is not in units.json or UNIT_ALIASES."
            )
        canonical, unit_iri = resolved
        row["unit"] = canonical
        if unit_iri:
            row["unit_iri"] = unit_iri

        flows.append(row)
        known.add(uuid)
        added += 1
        logger.info(
            "additional_flow_added",
            source=label, index=index, uuid=uuid, name=row.get("name"),
            context=row.get("context"), comment=record["comment"],
        )

    logger.info(
        "additional_flows_complete",
        source=label, path=str(path),
        total=len(records), added=added, superseded=superseded,
        excluded=len(excluded_uuids),
    )
    return flows
