"""Resolving which consensus context a source row belongs in.

The source list uses its own context vocabulary, so every row has to be mapped
onto a consensus context IRI before it can match or create a flow. Where a row
cannot be placed confidently it is reported rather than guessed at.

The rules come from `context_mapping`, filtered to this list -- the same file
and the same loader the transform uses. They used to come from a generated
per-list projection of that file which `build` never regenerated (#11).
"""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from typing import Any

import structlog

from brightway_flows.context_mapping import (
    consensus_context_strings,
    context_iri_by_source_context,
    flow_context_iri,
    name_prefix_context_iri,
    normalize_mapping_text,
)
from brightway_flows.correspondence_contexts import publishable_coarsenings
from brightway_flows.domain.context import (
    Context,
    Dimension,
    Media,
    WaterBody,
)
from brightway_flows.domain.context_registry import (
    UnknownContextIRIError,
    context_for_iri,
    iri_for_context,
)
from brightway_flows.domain.land_flow_classes import land_class_for_source_flow
from brightway_flows.domain.materials import withdrawal_water_body
from brightway_flows.sources import SourceList

logger = structlog.get_logger(__name__)

#: Re-exported under the name the merge modules already import it by.  One
#: spelling, in `context_mapping`: the transform and the merge each used to
#: carry their own, and two normalisers that disagree place a row in one stage
#: and not the other.
_normalize_text = normalize_mapping_text

def _normalize_context_list(values: list[str]) -> tuple[str, ...]:
    return tuple(_normalize_text(str(v)) for v in values if isinstance(v, str) and str(v).strip())

@dataclass(frozen=True)
class ContextExpectations:
    """Which consensus context the merge expects a source row to land in.

    A single object rather than the bare ``compartment -> IRI`` dict this used
    to be, because there are three rules and the more specific one has to win.
    A dict cannot express that: every call site would have to remember to
    consult the per-flow and per-name rules first, and the one that forgot would
    place a flow on its compartment's context with nothing reporting the
    disagreement.  So the dict is private and :meth:`resolve` is the only way in.

    That matters most for water and for land.  EF 3.1 gives all six of its water
    bodies one compartment, so for those flows the compartment rule is not
    merely less specific -- it is the thing being corrected.  ecoinvent gives
    land occupation and land transformation one compartment and the name is what
    tells them apart, and the compartment rule says occupation, so every
    transformation flow that reaches this object without its name is filed as an
    occupation (#52).
    """

    #: Compartment rule: normalised ``source_context`` -> context IRI.
    _by_source_context: dict[tuple[str, ...], str]
    #: The list's own `source` string, for looking up its per-flow rules.
    _source_label: str

    def resolve(self, source_uuid: Any, source_context: Any, source_name: Any) -> str | None:
        """The context IRI for one row: its own rule, its name's, else its
        compartment's.

        *source_name* is required rather than optional.  A default would let a
        call site placing a row leave it out and get the compartment's answer,
        which for ecoinvent land is the wrong sibling for two flows in three,
        and nothing would say so; leaving it out now fails at the call.

        :raises FlowContextRuleError: if a per-flow rule names this flow but
            describes a compartment it is no longer in.
        :raises AmbiguousSourceContextError: if the compartment's contexts are
            told apart by name and this name matches no rule.
        """
        context = [
            str(x) for x in (source_context or []) if isinstance(x, str)
        ]
        # The land class first, because it is the most specific statement
        # anywhere: a curated row saying *this flow is an occupation of the
        # sea* outranks whatever compartment the vendor filed the row under
        # (#193).  `LandUse.land_use_class` derives the context value from the
        # direction, which is the agreement its own docstring demands --
        # before this, the class was consulted for the substance and ignored
        # for the context, so `Occupation, sea and ocean` filed under
        # `Resources / in water` was published as a water resource on a flow
        # the class had correctly named.  Measured before writing: no
        # per-flow context rule names a land row in any list, so nothing a
        # curator wrote is shadowed.
        land_use = land_class_for_source_flow(
            self._source_label, str(source_uuid or "")
        )
        if land_use is not None:
            by_class = iri_for_context(
                Context(
                    dimension=Dimension.LAND_USE,
                    land_use=land_use.land_use_class,
                )
            )
            if by_class:
                # The disagreement is the finding: log what the compartment
                # would have said, so the next vendor compartment nobody has
                # written a rule for is noticed on the build, not on a queue.
                otherwise = self._by_source_context.get(
                    _normalize_context_list(context)
                )
                if otherwise and otherwise != by_class:
                    logger.info(
                        "land_class_overrules_the_compartment",
                        source=self._source_label,
                        uuid=str(source_uuid or ""),
                        name=str(source_name or ""),
                        compartment=context,
                        compartment_said=otherwise,
                        published=by_class,
                    )
                return by_class
        override = flow_context_iri(self._source_label, str(source_uuid or ""), context)
        if override:
            return override
        by_name = name_prefix_context_iri(
            self._source_label, str(source_name or ""), context
        )
        if by_name:
            return by_name
        return self._by_source_context.get(_normalize_context_list(context))


def _load_context_expectation_indexes(
    source: SourceList,
) -> tuple[ContextExpectations, dict[str, list[str]]]:
    """What this list's rows are expected to land in, and what each context is
    called.

    The renderings come from `context_mapping` rather than being parsed here.
    They were read straight off the file, behind an `if it exists`, which is the
    shape #11 removed from the rules beside them: a missing vocabulary is not
    an empty one, it is every row scored against nothing.  One loader, and it
    raises.
    """
    # Keyed by the list's own `source` string, which is what the rules carry.
    by_source_context = dict(context_iri_by_source_context(source.source_label))

    expectations = ContextExpectations(
        _by_source_context=by_source_context,
        _source_label=source.source_label,
    )
    # Copied, because the merge hands this to a frozen index every reader shares
    # and the loader's answer is cached for the whole run.
    return expectations, {
        iri: list(strings) for iri, strings in consensus_context_strings().items()
    }

#: Every axis a context can state a value on, read off the dataclass rather
#: than listed, so an axis added to the vocabulary is compared without an edit
#: here -- a new axis nobody remembered to add would be an axis on which two
#: contexts are free to disagree silently.
_CONTEXT_AXES: tuple[str, ...] = tuple(field.name for field in fields(Context))

#: The value every axis but ``dimension`` uses for "not stated".  It is not a
#: place; it is the absence of a claim about the place, which is why a target
#: carrying it can never contradict anything.
_UNSTATED = "Unknown"


def context_contradicts(source_context_iri: str, target_context_iri: str) -> bool:
    """Whether publishing a row from *source* in *target* denies what the row said.

    A context is a record of axes -- media, water body, vertical strata,
    geography and the rest -- and each axis either names a value or says
    ``Unknown``, which is not a value but the absence of one.  So the two ways a
    target can differ from a source are not the same kind of thing:

    * The target leaves an axis out, or sets it to ``Unknown``.  That is a
      **coarsening**: a release to a lake published as a release to water,
      unspecified.  Detail is lost and nothing false is said, which is often
      exactly what is wanted, because the base list may have no lake.
    * The target names a *different* value on an axis the source also named.
      That is a **contradiction**: a release to a lake published as a release to
      groundwater.  Groundwater is not a vaguer way of saying lake; it is a
      different place, and publishing it asserts something the source denies.

    Only the second is reported here.  The rule is the whole of it -- there is
    no notion of two values being near each other, because nearness is what
    produced the defect this guards against (#85): the selector scored
    groundwater above lake for a lake row on the strength of two shared words.

    Pairs that may disagree anyway are the ones written down in
    ``correspondence-context-routing.json``, which is where the correspondence
    tables' permitted coarsenings already live -- and only the ones marked
    publishable, because permitting a table to state a pair and publishing a row
    on it are different acts.  A table pointing an ecoinvent forestry row at EF's
    non-agricultural soil, or an ecoinvent groundwater row at EF's fresh water,
    is naming the nearest flow EF has, which is the whole of what a
    correspondence table can do for a compartment EF lacks.  Nobody treats the
    pesticide as having been sprayed on non-agricultural soil, and the
    groundwater row said groundwater; publishing either on the target's
    compartment is the act refused (#84, #77).

    Unknown IRIs and the empty string are not contradictions.  A row whose
    context this project does not recognise is a different defect with a
    different fix, and failing it here would bury the routing errors this exists
    to find.
    """
    if not source_context_iri or not target_context_iri:
        return False
    if source_context_iri == target_context_iri:
        return False
    if (source_context_iri, target_context_iri) in publishable_coarsenings():
        return False
    try:
        source = context_for_iri(source_context_iri)
        target = context_for_iri(target_context_iri)
    except UnknownContextIRIError:
        return False
    for axis in _CONTEXT_AXES:
        stated = getattr(target, axis, None)
        if stated is None or stated == _UNSTATED:
            continue
        if getattr(source, axis, None) == stated:
            continue
        return True
    return False


def _context_taxonomy_distance(expected: list[str], candidate: list[str]) -> int:
    expected_norm = [_normalize_text(x) for x in expected if isinstance(x, str) and x.strip()]
    candidate_norm = [_normalize_text(x) for x in candidate if isinstance(x, str) and x.strip()]
    lcp = 0
    for left, right in zip(expected_norm, candidate_norm):
        if left != right:
            break
        lcp += 1
    return (len(expected_norm) - lcp) + (len(candidate_norm) - lcp)

def _same_taxonomy_root(expected: list[str], candidate: list[str]) -> bool:
    expected_norm = [_normalize_text(x) for x in expected if isinstance(x, str) and x.strip()]
    candidate_norm = [_normalize_text(x) for x in candidate if isinstance(x, str) and x.strip()]
    if not expected_norm or not candidate_norm:
        return False
    # Never cross dimensions.
    if expected_norm[0] != candidate_norm[0]:
        return False
    # If both have media, never cross media.
    if len(expected_norm) > 1 and len(candidate_norm) > 1 and expected_norm[1] != candidate_norm[1]:
        return False
    return True

def _context_for_new_flow(context_iri: str) -> Context | None:
    """The :class:`Context` for a newly created flow's record.

    Always resolved from the IRI.  An earlier version of this rebuilt the
    context by zipping ``Context.to_list()`` output positionally against a fixed
    key tuple, which mis-assigned fields (``to_list`` orders for reading and
    drops ``"Unknown"``) and corrupted the context of every merge-created flow.

    ``None`` when *context_iri* is missing or unregistered: an absent context
    beside an absent ``context_iri`` is self-consistent and detectable
    downstream, whereas a fabricated one is not.
    """
    iri = (context_iri or "").strip()
    if not iri:
        logger.warning("new_flow_missing_context_iri")
        return None
    try:
        return context_for_iri(iri)
    except UnknownContextIRIError:
        logger.warning("new_flow_unknown_context_iri", context_iri=iri)
        return None


def water_body_from_material(
    *, material: str | None, source_context_iri: str
) -> tuple[str, str]:
    """``(context_iri, body)`` for a withdrawal whose body the material names.

    BAFU withdraws water from a lake and writes the lake in the *name* --
    `Water, lake` -- while its compartment says `resources / in water`, which is
    water of no stated body.  The kind of water is read from the name into the
    material, and for a withdrawal the material says the body too: water taken
    from a lake was taken from a lake.

    **It refines an unstated body and never overrides a stated one.**  That is
    the whole of what makes it safe, and it is the same distinction #90 turns
    on: `Unknown` prints an answer without stating one.  A source that says
    which body it drew from is believed, even where the material disagrees --
    that disagreement is a curator's question and this is not the place it gets
    settled.

    Applied to withdrawals only.  Water discharged *into* a lake is plain water,
    and the lake is where it went rather than what it is, so a material can say
    nothing about an emission's body -- see
    :data:`~brightway_flows.domain.materials.WITHDRAWAL_WATER_BODY`.

    Returns the IRI unchanged, and an empty body, wherever any of that does not
    hold -- no material, no body for it, not a water resource, a body already
    stated, or a combination the context vocabulary does not carry.
    """
    body = withdrawal_water_body(material or "")
    if not body or not source_context_iri:
        return source_context_iri, ""
    try:
        context = context_for_iri(source_context_iri)
    except UnknownContextIRIError:
        return source_context_iri, ""
    if context.dimension != Dimension.RESOURCE or context.media != Media.WATER:
        return source_context_iri, ""
    if context.water_body != WaterBody.UNKNOWN:
        return source_context_iri, ""
    refined = replace(context, water_body=WaterBody(body))
    iri = iri_for_context(refined)
    return (iri, body) if iri else (source_context_iri, "")
