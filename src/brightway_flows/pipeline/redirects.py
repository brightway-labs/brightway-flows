"""Where a deprecated identifier resolves to, and whether that is safe.

`harmonised-flows-simple.json.gz` carries only non-deprecated flows, so an
identifier this project published and later deprecated used to be
indistinguishable from one it never harmonised: both are a lookup miss.  That
ambiguity is what #39 asked to close, and it is not cosmetic -- downstream,
9.1% of EF 3.1's characterisation factors were silently dropped because the flow
they name had been merged into another one and nothing said so.

Two properties are what a consumer needs, and both are produced here rather than
left to be reimplemented per consumer:

**Every deprecated identifier resolves.**  One record per deprecated flow, not
one per flow someone is thought likely to hold -- which identifiers are still in
circulation is not something this project knows.

**Redirects are terminal.**  A survivor that is itself deprecated later would
otherwise make a consumer chase a chain, and write the same cycle guard.

The third thing published is *why*, and it is the reason this module is not
three lines long.  Following a redirect is not always right: the deprecation
pass merges flows whose every semantic field agrees, but agreement is judged
after source contexts have been mapped onto the consensus vocabulary, so two
distinct source contexts that collapse onto one consensus context yield two
flows that look identical and whose factors legitimately disagree (#1, #36).
Comparing the source contexts on the two sides is what separates those from the
merges of a flow with itself, and it is the difference between a redirect a
consumer should follow and one it should refuse.  The comparison is made within
each source list the two flows share, because a list only the survivor is in
tells you the survivor is better attested, not that its identity moved (#59).

## The one retirement no build can work out for itself

A deprecated flow is in the export, so its identifier and its survivor are both
in hand.  A *retired* identifier is not: #102 changed how the merge names the
flows it mints, from the source row that reached the compartment first to the
substance and the compartment, and that renamed all 2,561 minted flows in one
build.  Nothing in the new build carries the old names -- working them out again
would mean keeping the very rule that made them move -- so they are recorded
once, in ``retired-minted-flow-ids.json``, and published from there.  A
retirement is emitted only where this build publishes the flow it points at,
because a build that merges fewer lists mints fewer of them.

## The one deprecation that resolves to nothing

A withdrawal is a deprecation with no survivor, and it is the reason
`dcterms:isReplacedBy` is optional on a record here.  It arises when this list
decides that a source row should never have been mapped at all: the flow minted
from it stops being minted, and there is nothing for its identifier to point at,
because the substance did not move -- it was never a substance of ours.  #115's
three ecoinvent 3.8 rows are the worked example, and they are products rather
than elementary flows.

That is not the same as the `deprecated_without_replacement` case below, which
is a flow marked deprecated whose replacement is missing.  There, the absence is
a fault in the data and no record is written, because publishing a deprecation
with an unexplained hole replaces one silent miss with another.  Here the
absence *is* the finding, it is stated as `source-row-withdrawn`, and what was
withdrawn and why is published on the source list's `xkos:Correspondence`.

Like a retirement, a withdrawal cannot be worked out by a build: nothing in a
build that no longer mints the flow remembers that it used to.  It is recorded
in the source list's ``-additional-flows.json``, beside the excluded row it
belongs to, and read from there.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import orjson
import structlog

from brightway_flows.additional_flows import ExcludedSourceFlow
from brightway_flows.domain.elementary_flow import minted_elementary_flow_id
from brightway_flows.domain.simple_flow import FlowRedirect
from brightway_flows.domain.vocabulary import (
    CONSENSUS_ELEMENTARY_FLOW_IRI_PREFIX,
    DCTERMS_IS_REPLACED_BY,
    DCTERMS_IS_REPLACED_BY_CURIE,
    OWL_DEPRECATED,
    OWL_DEPRECATED_CURIE,
    deprecation_reason_iri,
)
from brightway_flows.filesystem import PACKAGE_DATA_DIR

logger = structlog.get_logger(__name__)

#: A source list both flows are in put them in different contexts, so the
#: redirect crosses a distinction the consensus vocabulary cannot express.
CONTEXT_COLLAPSE = "context-collapse"
#: Every source list both flows are in put them in the same contexts: the same
#: flow twice.
IDENTITY_MERGE = "identity-merge"
#: The two share no source list that records a context, so nothing about them
#: can be compared.
UNCLASSIFIED = "unclassified"
#: The flow did not change; the scheme that names it did.
IDENTIFIER_SCHEME_CHANGE = "identifier-scheme-change"
#: The source row the flow was minted from is one this list refuses to map, so
#: the flow is gone and nothing replaces it.  The only reason whose record
#: carries no `dcterms:isReplacedBy`.
SOURCE_ROW_WITHDRAWN = "source-row-withdrawn"

#: The `run_stats` stage the retirement counts are filed under.  One name, used
#: by the transform-only build and by every merge, because the merge's answer
#: supersedes the transform's rather than sitting beside it: a merge mints the
#: flows the retired identifiers point at, so only it can say how many resolve.
FLOW_RETIREMENT_STAGE = "flow_retirements"

RETIREMENTS_FILEPATH = PACKAGE_DATA_DIR / "retired-minted-flow-ids.json"

#: This file's own on-disk format, not the version of the published list; see
#: `domain/rulings.py` on why the two are never spelled the same.
RETIREMENTS_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class RetiredIdentifier:
    """One identifier this project published and no longer mints.

    *flow_object_id* and *context_iri* are what the flow is, and they are
    recorded rather than left implicit so that *replaced_by* can be checked
    against them at load: a retirement whose replacement is not what those two
    produce points somewhere nobody decided, and is refused rather than
    published.
    """

    identifier: str
    replaced_by: str
    flow_object_id: str
    context_iri: str
    name: str


class RetiredIdentifierError(ValueError):
    """A retirement that cannot be read as one, or that points somewhere else.

    Raised rather than skipped: a retirement that is silently dropped is an
    identifier that disappears from the export, which is the whole failure #102
    is about.
    """


def load_retired_minted_flow_ids(
    path: Path | None = None,
) -> tuple[RetiredIdentifier, ...]:
    """Every minted identifier a change of scheme retired, in file order.

    Each record's *replaced_by* is recomputed from its substance and context and
    must agree, so the file cannot drift away from
    :func:`~brightway_flows.domain.elementary_flow.minted_elementary_flow_id`
    without saying so.
    """
    filepath = path or RETIREMENTS_FILEPATH
    if not filepath.exists():
        return ()
    payload = orjson.loads(filepath.read_bytes())
    if not isinstance(payload, dict):
        raise RetiredIdentifierError(f"{filepath.name} is not an object")
    version = payload.get("schema_version")
    if version != RETIREMENTS_SCHEMA_VERSION:
        raise RetiredIdentifierError(
            f"{filepath.name} is schema version {version!r}; this reads "
            f"{RETIREMENTS_SCHEMA_VERSION}"
        )
    rows = payload.get("retirements")
    if not isinstance(rows, list):
        raise RetiredIdentifierError(f"{filepath.name} carries no retirements list")

    out: list[RetiredIdentifier] = []
    seen: set[str] = set()
    for position, row in enumerate(rows):
        if not isinstance(row, dict):
            raise RetiredIdentifierError(f"retirement {position} is not an object")
        record = RetiredIdentifier(
            identifier=str(row.get("identifier") or "").strip(),
            replaced_by=str(row.get("replaced_by") or "").strip(),
            flow_object_id=str(row.get("flow_object_id") or "").strip(),
            context_iri=str(row.get("context_iri") or "").strip(),
            name=str(row.get("name") or "").strip(),
        )
        if not record.identifier:
            raise RetiredIdentifierError(f"retirement {position} retires nothing")
        if not (record.flow_object_id and record.context_iri):
            raise RetiredIdentifierError(
                f"retirement {position} ({record.identifier}) does not say which "
                f"substance in which context it names"
            )
        expected = minted_elementary_flow_id(
            record.flow_object_id, record.context_iri
        )
        if record.replaced_by != expected:
            raise RetiredIdentifierError(
                f"retirement {position} ({record.identifier}) is replaced by "
                f"{record.replaced_by!r}, but {record.flow_object_id} in "
                f"{record.context_iri} is minted as {expected!r}"
            )
        if record.identifier in seen:
            raise RetiredIdentifierError(
                f"retirement {position} retires {record.identifier} a second time"
            )
        if record.identifier == record.replaced_by:
            raise RetiredIdentifierError(
                f"retirement {position} retires {record.identifier} onto itself"
            )
        seen.add(record.identifier)
        out.append(record)
    return tuple(out)


def published_flow_identifier(flow: dict[str, Any]) -> str:
    """The identifier this flow is published under, or ``""``.

    EF flows carry ``identifier`` directly; flows the merge added carry only
    ``elementary_flow_id``, aliased to ``uuid``.  Both the export and the
    redirects have to agree on which key wins, or a redirect would point at an
    identifier no flow in the same document uses.
    """
    for key in ("identifier", "uuid", "elementary_flow_id"):
        value = flow.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def is_deprecated(flow: dict[str, Any]) -> bool:
    """Whether this payload is marked deprecated, under either key spelling."""
    return flow.get(OWL_DEPRECATED) is True or flow.get(OWL_DEPRECATED_CURIE) is True


def _strip_urn_uuid(value: str) -> str:
    return value[len("urn:uuid:"):] if value.lower().startswith("urn:uuid:") else value


def _replacement_identifier(flow: dict[str, Any]) -> str:
    """The bare UUID this flow was replaced by, or ``""``.

    Three spellings reach the export -- the plain ``is_replaced_by_uuid`` the
    duplicate pass writes, and the IRI and CURIE forms of
    ``dcterms:isReplacedBy``, whose values are ``urn:uuid:`` links rather than
    bare identifiers.  Reading only the first would have worked today and
    silently produced nothing the day a flow arrives already deprecated from its
    source list.
    """
    for key in (
        "is_replaced_by_uuid",
        DCTERMS_IS_REPLACED_BY_CURIE,
        DCTERMS_IS_REPLACED_BY,
    ):
        value = flow.get(key)
        if isinstance(value, str) and value.strip():
            return _strip_urn_uuid(value.strip())
        if isinstance(value, dict):
            nested = value.get("@id")
            if isinstance(nested, str) and nested.strip():
                return _strip_urn_uuid(nested.strip())
    return ""


def _classify(
    deprecated: Mapping[str, frozenset[tuple[str, ...]]],
    survivor: Mapping[str, frozenset[tuple[str, ...]]],
) -> str:
    """Which reason applies to one redirect.

    Asked once per source list both flows are in, and only of those: within one
    list, equal context sets mean the same flow arrived twice, and any
    difference means the redirect crosses a distinction that list drew -- a
    partial overlap included, since it still loses whatever the deprecated flow
    had that the survivor does not.

    A list only one side carries says nothing about the other, so it is not
    compared.  Pooling every list into one set per flow instead is what made
    all 46 of the 2026-08-12 build's context collapses spurious (#59): in
    every one the deprecated flow was in EF only, its survivor in EF and
    ecoinvent, and their EF contexts were identical.  The survivor being
    attested by a second list was read as the identity having moved.

    Sharing no list at all leaves nothing to compare, which is `unclassified`
    like having no contexts at all.
    """
    shared = deprecated.keys() & survivor.keys()
    if not shared:
        return UNCLASSIFIED
    if any(deprecated[name] != survivor[name] for name in shared):
        return CONTEXT_COLLAPSE
    return IDENTITY_MERGE


def _resolve_terminal(start: str, replaced_by: dict[str, str]) -> tuple[str, bool]:
    """Follow the replacement chain to its end.

    Returns the terminal identifier and whether the walk hit a cycle.  A cycle
    stops on the last identifier before the repeat rather than raising: one
    unusable redirect should be reported and counted, not made to fail an
    otherwise complete export.
    """
    target = start
    seen = {start}
    while (nxt := replaced_by.get(target)) is not None:
        if nxt in seen:
            return target, True
        seen.add(nxt)
        target = nxt
    return target, False


def classify_replacements(
    replaced_by: Mapping[str, str],
    source_contexts: Mapping[str, Mapping[str, frozenset[tuple[str, ...]]]]
    | None = None,
    *,
    published: Collection[str] | None = None,
) -> dict[str, tuple[str, str]]:
    """Where each deprecated identifier ends up, and what its redirect means.

    The two judgements :func:`build_redirects` makes about a deprecation --
    walking the chain to its end and comparing the two flows' source contexts --
    without projecting the export.  Split out for a reader inside the pipeline
    that has to *act* on a redirect rather than publish it: `lcia.matching` is
    the first, and a build whose factors followed a redirect the export did not
    publish, or refused one it did, would be the two halves of one build
    disagreeing about the same flow (#163).

    *replaced_by* maps a deprecated identifier to the one it names as its
    replacement -- one hop, as the payload states it.  *published* is the set of
    identifiers this build publishes and does not deprecate; a chain ending
    outside it resolves to ``""``, because following it lands nowhere.  Omit it
    and every chain end is taken on trust, which is what a caller holding only
    the map knows.

    Returns ``{identifier: (target, reason)}`` for every identifier in
    *replaced_by*, with *reason* one of the constants above -- and ``""`` as the
    target where the walk hit a cycle or ended somewhere unpublished.  A caller
    deciding whether to follow one wants both: `identity-merge` is the same flow
    reached twice and safe to follow, while `context-collapse` crosses a
    distinction a source list drew and the consensus vocabulary cannot express,
    which is the redirect #1 and #36 say to refuse.
    """
    contexts: Mapping[str, Mapping[str, frozenset[tuple[str, ...]]]] = (
        source_contexts or {}
    )
    chain = dict(replaced_by)
    out: dict[str, tuple[str, str]] = {}
    for identifier in chain:
        target, cycle = _resolve_terminal(chain[identifier], chain)
        if cycle or (published is not None and target not in published):
            logger.warning(
                "replacement_resolves_nowhere",
                flow=identifier,
                stopped_at=target,
                cycle=cycle,
            )
            target = ""
        out[identifier] = (
            target,
            _classify(contexts.get(identifier, {}), contexts.get(target, {})),
        )
    return out


def build_redirects(
    flows: list[dict[str, Any]],
    source_contexts: Mapping[str, Mapping[str, frozenset[tuple[str, ...]]]]
    | None = None,
    retirements: tuple[RetiredIdentifier, ...] | None = None,
    withdrawals: tuple[ExcludedSourceFlow, ...] | None = None,
) -> tuple[list[FlowRedirect], Counter]:
    """Build one :class:`FlowRedirect` per deprecated flow, and a tally.

    *flows* is the same payload list the export is projected from, so the two
    cannot disagree about which flows are published and under which identifiers.
    Records are emitted in payload order, like ``flows``, so a rebuild over
    unchanged inputs produces an identical document.

    *source_contexts* maps a flow identifier to the contexts it was built from,
    per source list, and is what the reason is decided by --
    :func:`brightway_flows.pipeline.sqlite.read_source_contexts` produces it
    from `elementary_flow_sources`, which since #30 is the only place a flow's
    references live.  Per list, because a survivor two lists agree on has a
    context its deprecated flow does not, and pooled that reads as an identity
    that moved (#59).  Deliberately a parameter and not something read off the
    payload: the payload's copy was short on 7,794 of 94,433 flows before it was
    removed, and a *short* copy is the direction that misclassifies -- a
    survivor missing one of its contexts makes a context collapse look like a
    merge of a flow with itself, which is the redirect a consumer would follow
    when it should refuse.

    Omit it and every redirect is published as ``unclassified``, which is what
    is genuinely known without it.

    *retirements* are the identifiers a change of naming scheme retired, which
    no build can work out for itself; see the module docstring.  They are
    emitted after the deprecations, each pointing at the flow it named, and only
    where this build publishes that flow.  Default ``None`` reads the recorded
    file; pass ``()`` for a caller that wants the deprecations alone.

    *withdrawals* are the identifiers this project published for source rows it
    has since decided not to map, from the ``excluded`` records in the source
    lists' curated files.  They are emitted last, each with no replacement; see
    the module docstring.  Default ``None`` reads the registry; pass ``()`` to
    leave them out.
    """
    if withdrawals is None:
        # Imported here, not at module scope: `sources` reaches back into
        # `pipeline`, and this module is on that path.
        from brightway_flows.sources import excluded_source_flows

        withdrawals = tuple(
            record
            for records in excluded_source_flows().values()
            for record in records
        )
    contexts: Mapping[str, Mapping[str, frozenset[tuple[str, ...]]]] = (
        source_contexts or {}
    )
    published: set[str] = set()
    replaced_by: dict[str, str] = {}
    deprecated_order: list[str] = []
    counts: Counter = Counter()

    for flow in flows:
        if not isinstance(flow, dict):
            continue
        identifier = published_flow_identifier(flow)
        if not identifier:
            continue
        if not is_deprecated(flow):
            published.add(identifier)
            continue
        replacement = _replacement_identifier(flow)
        if not replacement:
            # Nothing to redirect to, so no record can be written: publishing
            # the deprecation alone would replace one silent miss with another.
            counts["deprecated_without_replacement"] += 1
            logger.warning("deprecated_flow_without_replacement", flow=identifier)
            continue
        replaced_by[identifier] = replacement
        deprecated_order.append(identifier)

    out: list[FlowRedirect] = []
    for identifier in deprecated_order:
        target, cycle = _resolve_terminal(replaced_by[identifier], replaced_by)
        if cycle:
            counts["replacement_cycle"] += 1
            logger.warning("replacement_cycle", flow=identifier, stopped_at=target)
        if target not in published:
            # The chain ends on an identifier the export does not carry, so
            # following the redirect is still a miss.  Counted and logged rather
            # than dropped: a consumer that can see *why* its lookup failed is
            # the point of the whole record.
            counts["target_not_published"] += 1
            logger.warning(
                "redirect_target_not_published", flow=identifier, target=target
            )
        reason = _classify(contexts.get(identifier, {}), contexts.get(target, {}))
        counts[f"reason_{reason}"] += 1
        out.append(FlowRedirect(
            identifier=identifier,
            replaced_by_identifier=target,
            jsonld_id=f"{CONSENSUS_ELEMENTARY_FLOW_IRI_PREFIX}{identifier}",
            replaced_by={"@id": f"{CONSENSUS_ELEMENTARY_FLOW_IRI_PREFIX}{target}"},
            deprecation_reason={"@id": deprecation_reason_iri(reason)},
        ))

    retired_records, retired_counts = retirement_redirects(
        published,
        load_retired_minted_flow_ids() if retirements is None else retirements,
    )
    out.extend(retired_records)
    counts.update(retired_counts)

    withdrawn_records, withdrawn_counts = withdrawal_redirects(published, withdrawals)
    out.extend(withdrawn_records)
    counts.update(withdrawn_counts)

    counts["redirects"] = len(out)
    logger.info("built_flow_redirects", **{k: v for k, v in counts.items() if v})
    return out, counts


def retirement_redirects(
    published: set[str],
    retirements: tuple[RetiredIdentifier, ...],
    *,
    unresolved: list[RetiredIdentifier] | None = None,
) -> tuple[list[FlowRedirect], Counter]:
    """One record per retired identifier this build can still resolve, and a tally.

    Split out of :func:`build_redirects` so that
    :func:`~brightway_flows.pipeline.exporting.retirement_stats` can count
    the same thing from the database without projecting the whole export a
    second time.  *published* is the set of identifiers this build publishes and
    does not deprecate.

    *unresolved*, when given, is filled with the retirements this build cannot
    answer, in file order, so a caller can report them.  Passing a list rather
    than returning one keeps every existing call site unchanged: the two counts
    are what most of them want, and the records are only needed where a queue
    is being written (#344).
    """
    out: list[FlowRedirect] = []
    counts: Counter = Counter()
    if unresolved is None:
        unresolved = []
    for retired in retirements:
        if retired.replaced_by not in published:
            # This build does not mint the flow, so there is nothing for the old
            # identifier to resolve to and a record would be a redirect into a
            # hole.  The entry stays in the file for the build that does mint it.
            #
            # Two reasons a build does not, and they are not the same news
            # (#344).  A build merging fewer source lists mints fewer flows,
            # and that is what this count was written for.  The other is
            # curation taking the flow away -- #117's cooling water is the
            # worked example: the ground filing was a slip, the row went where
            # its siblings go, the minted flow correctly stopped being minted,
            # and a published identifier went with it while the substance is
            # still there three contexts over.  `unresolved_details` separates
            # them by asking whether the substance still publishes anything.
            counts["not_in_this_build"] += 1
            unresolved.append(retired)
            continue
        if retired.identifier in published:
            # The retired identifier is live again, which the renumbering cannot
            # produce and a hand-edited file can.  Publishing the redirect would
            # tell a consumer that a flow this build publishes has been replaced
            # by a different one.
            counts["still_published"] += 1
            logger.warning(
                "retired_identifier_still_published", flow=retired.identifier
            )
            continue
        counts["redirects_published"] += 1
        out.append(FlowRedirect(
            identifier=retired.identifier,
            replaced_by_identifier=retired.replaced_by,
            jsonld_id=(
                f"{CONSENSUS_ELEMENTARY_FLOW_IRI_PREFIX}{retired.identifier}"
            ),
            replaced_by={
                "@id": (
                    f"{CONSENSUS_ELEMENTARY_FLOW_IRI_PREFIX}{retired.replaced_by}"
                )
            },
            deprecation_reason={
                "@id": deprecation_reason_iri(IDENTIFIER_SCHEME_CHANGE)
            },
        ))
    return out, counts


def withdrawal_redirects(
    published: set[str],
    withdrawals: tuple[ExcludedSourceFlow, ...],
) -> tuple[list[FlowRedirect], Counter]:
    """One record per withdrawn identifier, and a tally.

    A withdrawal names no survivor, so unlike a retirement there is no target to
    check against *published* -- and unlike a retirement it is emitted whether
    or not this build merges the list the excluded row belongs to.  The claim is
    about an identifier this project published, which stays true of every build;
    a build merging fewer lists does not un-withdraw it.

    *published* is still needed for the one thing that can go wrong: an
    identifier that is live again.  That cannot happen while the row stays
    excluded, so it means the exclusion has been undone in one file and not the
    other, and publishing the record would tell a consumer that a flow this very
    document carries has been withdrawn.

    A record with no ``withdrew_identifier`` is skipped rather than counted as a
    fault: a row excluded before it ever reached a build has no published
    identifier to withdraw, and that is the ordinary case for every exclusion
    written from now on.
    """
    out: list[FlowRedirect] = []
    counts: Counter = Counter()
    for record in withdrawals:
        identifier = record.withdrew_identifier
        if not identifier:
            counts["withdrawn_never_published"] += 1
            continue
        if identifier in published:
            counts["withdrawn_still_published"] += 1
            logger.warning(
                "withdrawn_identifier_still_published",
                flow=identifier, source=record.source, uuid=record.uuid,
            )
            continue
        counts["withdrawals_published"] += 1
        out.append(FlowRedirect(
            identifier=identifier,
            jsonld_id=f"{CONSENSUS_ELEMENTARY_FLOW_IRI_PREFIX}{identifier}",
            deprecation_reason={
                "@id": deprecation_reason_iri(SOURCE_ROW_WITHDRAWN)
            },
        ))
    return out, counts
