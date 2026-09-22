"""Grouping flows into shared flow objects and context-specific flows.

The layering itself: one pass over the input flows that decides, for each, which
flow object it belongs to -- by UUID override, by CAS, by normalised name, and
by origin qualifier, with guards for the cases where those disagree -- and emits
one `ElementaryFlow` per input flow.  The element, isotope and ion enrichments
run afterwards, on the objects this produced.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import orjson

from brightway_flows.domain.elementary_flow import ElementaryFlow
from brightway_flows.domain.flow import Flow
from brightway_flows.domain.flow_object import FlowObject, stable_flow_object_id
from brightway_flows.domain.labels import (
    coerce_alt_labels,
    coerce_pref_label,
    flow_label_value,
)
from brightway_flows.domain.nuclides import parse_nuclide_label
from brightway_flows.domain.source_ref import SourceRef
from brightway_flows.domain.vocabulary import (
    CHEMINF_CAS_REGISTRY_NUMBER,
    CHEMINF_EC_NUMBER,
)
from brightway_flows.flow_layers.contested_cas import (
    ContestedCas,
    Verdict,
    cas_supplied_by_manual_fixes,
    commonchemistry_details,
    contested_cas_index,
    load_decisions,
)
from brightway_flows.flow_layers.classifications import (
    _build_classifications,
    _classification_values,
)
from brightway_flows.flow_layers.elements import (
    _augment_with_element_and_isotope_flow_objects,
)
from brightway_flows.flow_layers.roles import (
    assign_chebi_roles,
    assign_curated_roles,
)
from brightway_flows.flow_layers.labels import (
    _definition_key,
    _label_entry,
    _merge_label_rows,
    _norm_text,
    _object_pref_label_value,
    _reference_key,
    _strip_definition_markup,
)
from brightway_flows.sources import base_source_label
from brightway_flows.domain.land_flow_classes import land_class_for_source_flow
from brightway_flows.domain.land_use import LandUse
from brightway_flows.flow_layers.land_hierarchy import land_object_id
from brightway_flows.domain.materials import (
    flow_object_basis_for,
    material_concepts,
    material_for_source_flow,
)
from brightway_flows.domain.particulate_size import (
    SizeClass,
    size_class_for_source_flow,
)
from brightway_flows.qualifiers import (
    detect_origin_qualifier,
    is_delayed_emission_correction,
)
from brightway_flows.sources import BASE_ROLE, SourceList
from brightway_flows.filesystem import PACKAGE_DATA_DIR

CONTEXT_KEYS = (
    "dimension",
    "media",
    "strata",
    "indoor",
    "population_density",
    "geography",
    "water_body",
    "land_use",
)

# `parents[1]`, not `parent`: the file this names is packaged under
# `brightway_flows/data/`, and this module is now one directory deeper than
# the one that used to read it.
OVERRIDES_FILEPATH = (
    PACKAGE_DATA_DIR / "flow-object-overrides.json"
)


def _norm_cas(values: list[Any]) -> tuple[str, ...]:
    return tuple(sorted({
        str(v).strip()
        for v in values
        if isinstance(v, str) and v.strip()
    }))


#: Kept as a local name because this module says `_stable_object_id` in a dozen
#: places and the convention it implements is now shared with the element
#: enrichment.  See `domain.flow_object.stable_flow_object_id`.
_stable_object_id = stable_flow_object_id


def _material_for(flow: Any, base_label: str, source_label: str = "") -> str | None:
    """Which environmental material *flow* is made of, or None.

    Looked up, never inferred.  The flow's own uuid is the base list's -- most
    of the list is EF 3.1 rows that no source list has been merged onto -- and
    `source_refs` carry the uuids of the lists that have.  Both are consulted,
    because a consensus flow is whichever of those reached it.

    *source_label* is the list the flows were **read from**, and it is consulted
    for the same uuid.  Without it the axis is invisible to the merge's creation
    path: a flow the merge is about to mint an object for has not been given a
    `source_ref` yet -- `resolve_flow_layers` derives those further down, after
    the axes are computed -- so its own uuid is looked up under `EF 3.1`, misses,
    and a curated material is read as no material at all.  That is how ecoinvent's
    fossil-well withdrawal fell back to the bare CAS, landed on the shared water
    object, and had its creation blocked as an object that already exists.

    Two lists disagreeing about one consensus flow returns None rather than
    picking: the merge has put two materials on one flow, and quietly choosing
    the first is how a collapse gets papered over.  The pair is reported by the
    caller's stats instead.
    """
    found: set[str] = set()
    for label in (base_label, source_label):
        if not label:
            continue
        material = material_for_source_flow(label, flow.uuid)
        if material:
            found.add(material)
    for ref in flow.source_refs or ():
        if not isinstance(ref, dict):
            continue
        name, version = ref.get("list_name"), ref.get("list_version")
        source = f"{name}-{version}" if name and version else str(name or "")
        material = material_for_source_flow(source, ref.get("source_flow_uuid") or "")
        if material:
            found.add(material)
    return next(iter(found)) if len(found) == 1 else None


def _land_class_for(flow: Any, base_label: str, source_label: str = "") -> LandUse | None:
    """Which land class *flow* is, or None.

    The same shape as :func:`_material_for`, and for the same reasons: the
    flow's own uuid is the base list's, `source_refs` carry the uuids of the
    lists merged onto it, *source_label* covers the merge's creation path where
    a flow has no `source_ref` yet, and two lists disagreeing returns None
    rather than picking one.

    Looked up, never read off the name.  A land class is a comma-separated
    string in three spellings, and a rule that split it here would decide,
    unsupervised, that `heterogeneous, agricultural` is agricultural mosaic --
    which is what `land-flow-classes.json` exists to stop.  See
    `plans/land-class-taxonomy.md` §3.8.
    """
    found: set[LandUse] = set()
    for label in (base_label, source_label):
        if not label:
            continue
        land_use = land_class_for_source_flow(label, flow.uuid)
        if land_use:
            found.add(land_use)
    for ref in flow.source_refs or ():
        if not isinstance(ref, dict):
            continue
        name, version = ref.get("list_name"), ref.get("list_version")
        source = f"{name}-{version}" if name and version else str(name or "")
        land_use = land_class_for_source_flow(source, ref.get("source_flow_uuid") or "")
        if land_use:
            found.add(land_use)
    return next(iter(found)) if len(found) == 1 else None


def _particulate_size_for(
    flow: Any, base_label: str, source_label: str = ""
) -> SizeClass | None:
    """Which particle size window *flow* was cut at, or None.

    The same shape as :func:`_material_for` and :func:`_land_class_for`, and for
    the same reasons: the flow's own uuid is the base list's, `source_refs`
    carry the uuids of the lists merged onto it, *source_label* covers the
    merge's creation path where a flow has no `source_ref` yet, and two lists
    disagreeing returns None rather than picking one.

    Looked up, never read off the name -- and the reason is sharper here than
    for water.  BAFU ships `Particulates` and `Particulates, unspecified` and
    Stepwise 2006 characterises them differently, so a rule reading `< 10 um`
    out of a label would be deciding, unsupervised, a question two vendors
    answer two ways.  See `plans/particulate-taxonomy.md` §3.5.
    """
    found: set[SizeClass] = set()
    for label in (base_label, source_label):
        if not label:
            continue
        size = size_class_for_source_flow(label, flow.uuid)
        if size:
            found.add(size)
    for ref in flow.source_refs or ():
        if not isinstance(ref, dict):
            continue
        name, version = ref.get("list_name"), ref.get("list_version")
        source = f"{name}-{version}" if name and version else str(name or "")
        size = size_class_for_source_flow(source, ref.get("source_flow_uuid") or "")
        if size:
            found.add(size)
    return next(iter(found)) if len(found) == 1 else None


def _nuclide_object_basis(display_name: str) -> str | None:
    """The grouping key for a flow named after a nuclide, or ``None``.

    A CAS registry number identifies a *substance*, and for a nuclide the
    source lists do not agree on what that means.  Technetium-99 and
    Technetium-99m have their own numbers and separate cleanly; uranium-238,
    thorium-232 and praseodymium-147 are shipped by both EF 3.1 and ecoinvent
    carrying the *element's* number -- `7440-61-1` is uranium, and U-238's own
    is `24678-82-8` -- so the CAS merged each of them into the element.  One
    flow object then stood for two substances: uranium in kg and MJ, an ore,
    resolved to an object labelled `Uranium-238` and typed `Isotope` with a
    nucleon number and a decay mode, while elemental uranium had no object at
    all and the three uranium isotopes had no element to link to
    (`#17 <https://github.com/brightway-labs/brightway-flows/issues/17>`_).

    Keying on the nuclide instead is the same move the origin qualifiers make,
    and for the same reason: the CAS is not wrong, it is simply not the
    identity of this flow.  It stays on the object, where a consumer can still
    read it, and stops deciding what the object is.

    Deliberately narrow.  ``None`` for every name that is not exactly a nuclide,
    including `Thorium` and `Plutonium` themselves -- an element keeps its CAS
    key, which is what separates it from its own isotopes rather than what
    merges them.
    """
    nuclide = parse_nuclide_label(display_name)
    return f"nuclide:{nuclide.key}" if nuclide is not None else None


def _source_ref_for(
    source_list: SourceList,
    flow_uuid: str,
    flow_name: str,
    *,
    original_context: list[str] | None = None,
) -> SourceRef:
    """The source reference for a flow that arrived without one.

    The identity is *given*: `source_list` is the list these flows were read
    from, and `(list_name, list_version)` is what it is.  This used to recover
    the pair from `flow.source` -- a display string -- by special-casing the
    base label, prefix-matching `ecoinvent-`, and otherwise splitting on the
    first dash when the tail contained a digit (#13).  `ecoinvent-3.12`
    survived that; `US LCI` and `Stepwise 2006` would not have, and the guess is
    published: it lands in `source_refs` and in `elementary_flow_sources`.  A
    list whose name contains a space would have silently shipped a blank
    version.
    """
    source_metadata: dict[str, Any] = {}
    if source_list.role == BASE_ROLE:
        # Only the base list's rows carry it: it is what the vendor's own
        # compartment strings were before the context step replaced them, and
        # nothing else is merged with vendor contexts still intact.
        source_metadata["original_context"] = original_context or []

    return SourceRef(
        list_name=source_list.list_name,
        list_version=source_list.list_version,
        source_flow_uuid=flow_uuid,
        source_flow_name=flow_name,
        source_metadata=source_metadata,
    )


def _context_as_string_list(value: Any) -> list[str]:
    """Convert context payload to an ordered list of display strings."""
    out: list[str] = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str) and item.strip():
                out.append(item.strip())
        return out
    if isinstance(value, tuple):
        for item in value:
            if isinstance(item, str) and item.strip():
                out.append(item.strip())
        return out
    if isinstance(value, dict):
        for key in CONTEXT_KEYS:
            part = value.get(key)
            if isinstance(part, str) and part.strip():
                out.append(part.strip())
        return out
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return out


@dataclass(frozen=True)
class _UuidOverride:
    """One source flow placed on a stated object, whatever the axes decide."""

    source_uuid: str
    flow_object_id: str
    comment: str = ""


@dataclass(frozen=True)
class _MergeGroup:
    """Source flows joined onto one object that no rule would have joined.

    ``preferred_label`` is what the object is published as.  A group is written
    exactly because the members' names disagree -- if they agreed the name axis
    would have grouped them -- so without a stated label the length rule below
    picks, which is not a decision anybody made; see :func:`_merge_group_labels`.
    """

    flow_object_id: str
    source_uuids: tuple[str, ...]
    preferred_label: str = ""
    comment: str = ""


@dataclass(frozen=True)
class _ObjectName:
    """What to call an object whose members agree on a name this list will not use.

    The gap this fills.  A merge group can state a label because it exists in the
    first place to settle a disagreement between names.  An object minted from one
    source list has no disagreement to settle: every member row carries the same
    vendor name, the layering takes it, and there is nowhere to say that the
    *consensus* list calls it something else.  So a substance this project created
    is published under a vendor's spelling, and no field on any source flow can
    correct that -- which is the same reason `uuid_overrides` and `merge_groups`
    are in this file.

    ``current_label`` is what the object is called without this row, and it is
    required for the reason `lcia-factor-rulings.json` requires `ruled_about`: a
    rename written against a name the vendor has since changed is a decision about
    something that no longer exists, and applying it silently is worse than not
    applying it.  A row whose `current_label` does not match is skipped and
    counted, not obeyed.
    """

    flow_object_id: str
    current_label: str
    preferred_label: str
    comment: str = ""


@dataclass(frozen=True)
class _FlowObjectOverrides:
    """The curator's placements, as `flow-object-overrides.json` states them."""

    uuid_overrides: tuple[_UuidOverride, ...] = ()
    merge_groups: tuple[_MergeGroup, ...] = ()
    names: tuple[_ObjectName, ...] = ()


def _load_overrides(path: Path | None = None) -> _FlowObjectOverrides:
    """The overrides in *path*, or the shipped file.

    A missing file is not an error: no override is the normal state, and the
    layering places every flow on its own without one.

    A row this cannot read is dropped rather than guessed at.  These are
    hand-edited entries and not records yet, so a `flow_object_id` that is not a
    string is a typo in the file; placing a flow on `None` would be worse than
    leaving it where the axes put it, and the shipped file is checked by
    `tests/test_ef31_renewable_energy_duplicates.py`.
    """
    target = path or OVERRIDES_FILEPATH
    if not target.exists():
        return _FlowObjectOverrides()
    payload = orjson.loads(target.read_bytes())
    if not isinstance(payload, dict):
        return _FlowObjectOverrides()

    uuid_overrides: list[_UuidOverride] = []
    for row in payload.get("uuid_overrides") or ():
        if not isinstance(row, dict):
            continue
        source_uuid = row.get("source_uuid")
        flow_object_id = row.get("flow_object_id")
        if not isinstance(source_uuid, str) or not isinstance(flow_object_id, str):
            continue
        if not source_uuid or not flow_object_id:
            continue
        uuid_overrides.append(_UuidOverride(
            source_uuid=source_uuid,
            flow_object_id=flow_object_id,
            comment=str(row.get("comment") or ""),
        ))

    merge_groups: list[_MergeGroup] = []
    for row in payload.get("merge_groups") or ():
        if not isinstance(row, dict):
            continue
        flow_object_id = row.get("flow_object_id")
        source_uuids = row.get("source_uuids")
        if not isinstance(flow_object_id, str) or not isinstance(source_uuids, list):
            continue
        label = row.get("preferred_label")
        merge_groups.append(_MergeGroup(
            flow_object_id=flow_object_id,
            source_uuids=tuple(
                uuid for uuid in source_uuids if isinstance(uuid, str) and uuid
            ),
            preferred_label=label.strip() if isinstance(label, str) else "",
            comment=str(row.get("comment") or ""),
        ))

    names: list[_ObjectName] = []
    for row in payload.get("names") or ():
        if not isinstance(row, dict):
            continue
        flow_object_id = row.get("flow_object_id")
        current = row.get("current_label")
        preferred = row.get("preferred_label")
        comment = row.get("comment")
        # Raised rather than dropped, unlike the two shapes above.  Those place a
        # flow and a malformed row leaves it where the axes put it, which is a
        # recoverable non-decision; this one *renames a published substance*, and
        # a row that silently does nothing is a rename a curator believes happened.
        # Same argument as `lcia-factor-rulings.json`, which refuses a ruling with
        # no comment for the same reason.
        if not all(
            isinstance(value, str) and value.strip()
            for value in (flow_object_id, current, preferred, comment)
        ):
            raise ValueError(
                f"{target.name}: a `names` row needs flow_object_id, current_label, "
                f"preferred_label and comment, all non-empty strings; got {row!r}"
            )
        names.append(_ObjectName(
            flow_object_id=flow_object_id.strip(),
            current_label=current.strip(),
            preferred_label=preferred.strip(),
            comment=comment.strip(),
        ))

    return _FlowObjectOverrides(
        uuid_overrides=tuple(uuid_overrides),
        merge_groups=tuple(merge_groups),
        names=tuple(names),
    )


def _deep_merge(existing: Any, incoming: Any) -> Any:
    if isinstance(existing, dict) and isinstance(incoming, dict):
        merged = dict(existing)
        for key, value in incoming.items():
            if key in merged:
                merged[key] = _deep_merge(merged[key], value)
            else:
                merged[key] = value
        return merged
    if isinstance(existing, list) and isinstance(incoming, list):
        seen: set[str] = set()
        out: list[Any] = []
        for item in [*existing, *incoming]:
            marker = orjson.dumps(item).decode("utf-8")
            if marker in seen:
                continue
            seen.add(marker)
            out.append(item)
        return out
    return incoming if incoming not in (None, "", [], {}) else existing


def _uuid_overrides(overrides: _FlowObjectOverrides) -> dict[str, str]:
    """Which flow object each hand-placed source flow belongs to."""
    uuid_override: dict[str, str] = {}
    for row in overrides.uuid_overrides:
        uuid_override[row.source_uuid] = row.flow_object_id
    for group in overrides.merge_groups:
        for source_uuid in group.source_uuids:
            uuid_override[source_uuid] = group.flow_object_id
    return uuid_override


def _merge_group_labels(overrides: _FlowObjectOverrides) -> dict[str, str]:
    """The label a merge group states for the object it builds, by object id.

    A merge group joins flows that no rule would have joined, which means their
    names disagree -- if they agreed the name axis would have grouped them and
    no group would have been needed.  So one of the names has to win, and
    without a statement here that is decided by the length rule below, which
    prefers the longer string: it keeps `Energy, Potential (in Hydropower
    Reservoir), Converted` over `Primary Energy From Hydro Power` and then
    replaces `Energy, Geothermal, Converted` with `Primary Energy From
    Geothermics`.  Neither outcome is a decision, and one of them renames the
    object three other lists reach (#73).

    Where a group states a label, every member name that is not that label
    becomes an alternative label on the object rather than a second preferred
    one, so the name a source list published is still searchable.
    """
    return {
        group.flow_object_id: group.preferred_label
        for group in overrides.merge_groups
        if group.preferred_label
    }


#: The activity that publishes a curated name, in `prov:wasGeneratedBy`.  Named
#: for the shape in the overrides file rather than for this function, because
#: the file is where a reader who meets the string in an artifact has to go.
_NAME_OVERRIDE_ACTIVITY = "flow_object_names"

#: What a curated name is derived from, in `prov:hadPrimarySource`.  Every other
#: label in the published list came from a source flow or an enricher; this one
#: came from a decision written down in a file, and the provenance has to be able
#: to say which file.
_NAME_OVERRIDE_SOURCE = "flow-object-overrides.json"

#: What a particle window's guaranteed alternative labels say wrote them, and
#: from where.  Their own activity rather than the layering's, so a reader of
#: the provenance can tell a spelling the scheme promises from one a member
#: row happened to bring (#196).
_SIZE_CLASS_LABEL_ACTIVITY = "particulate_size_class"
_SIZE_CLASS_LABEL_SOURCE = "particulate-size-classes.json"


def _label_row_provenance(rows: Any, *, value: str) -> dict[str, Any] | None:
    """The provenance already on the label row for *value*, or None.

    Read from the row rather than through `coerce_label`, which looks for a
    `source` key: that is what an *elementary flow's* labels carry, while a flow
    object's carry `provenance`, so coercing here would report the fallback
    string `legacy_prefLabel` as though it were an attribution.
    """
    if not isinstance(rows, list):
        return None
    for row in rows:
        if not isinstance(row, dict):
            continue
        if _norm_text(str(row.get("@value") or "")) != _norm_text(value):
            continue
        provenance = row.get("provenance")
        return provenance if isinstance(provenance, dict) else None
    return None


def _rename_object(obj: FlowObject, *, preferred: str, demoted: str) -> None:
    """Publish *obj* as *preferred*, keeping *demoted* findable as an alt label.

    The vendor's own spelling is never dropped.  A consumer who knows a substance
    by the name the source list published still finds it, which is the same
    promise `strip_qualifier_altlabels` makes and the reason a merge group's
    stated label demotes rather than replaces.

    Both rows are written through :func:`_label_entry`, so both carry provenance.
    A curated name is the one string in the published list that no source list
    supplied and no enricher fetched -- it is a decision this project made -- so
    it is the label that can least afford to arrive with nothing saying who made
    it.  The first version of this function wrote a bare `{"@value", "@language"}`
    pair, which published that decision anonymously among labels that all name
    their origin.

    The demoted name keeps whatever provenance it already had.  It is still the
    vendor's name, and who wrote it did not change by being moved.
    """
    language = "en"
    pref = coerce_pref_label(obj.prefLabel)
    if pref is not None and pref.language:
        language = pref.language
    demoted_provenance = _label_row_provenance(obj.prefLabel, value=demoted)
    obj.prefLabel = [
        _label_entry(
            value=preferred,
            language=language,
            resolver_name=_NAME_OVERRIDE_ACTIVITY,
            seed_source=_NAME_OVERRIDE_SOURCE,
            was_derived_from="curated name override",
        )
    ]
    if _norm_text(demoted) != _norm_text(preferred):
        existing = list(obj.altLabel or [])
        already = any(
            _norm_text(str(row.get("@value") or "")) == _norm_text(demoted)
            for row in existing
            if isinstance(row, dict)
        )
        if not already:
            existing.append(
                _label_entry(
                    value=demoted,
                    language=language,
                    resolver_name=_NAME_OVERRIDE_ACTIVITY,
                    seed_source=_NAME_OVERRIDE_SOURCE,
                    was_derived_from="prefLabel the name override replaced",
                    label_source=demoted_provenance,
                )
            )
        obj.altLabel = existing


def curated_object_names() -> tuple[_ObjectName, ...]:
    """The curated names this project ships, for a caller checking the artifact.

    Public because the question "did every one of these reach the build?" cannot
    be answered by the layering.  A pass resolves one source list, so a row about
    an object some other list mints is invisible to it and indistinguishable from
    a typo; only the finished artifact holds every object at once.  See
    `assessment.measures.names.rows_unpublished`, which is the caller.
    """
    return _load_overrides().names


def _object_names(overrides: _FlowObjectOverrides) -> dict[str, _ObjectName]:
    """Curated names for objects the layering would otherwise call what a vendor does.

    Separate from :func:`_merge_group_labels` because the two answer different
    questions and only one of them can go stale.  A merge group's label settles a
    disagreement between names the group itself lists, so it is checkable from the
    group.  A name override renames an object whose members all agree, so the only
    thing that can invalidate it is the vendor changing the name it agreed on --
    which is what `current_label` is for.
    """
    return {name.flow_object_id: name for name in overrides.names}


@dataclass(frozen=True)
class _Axes:
    """Which of the exclusive identity axes claim one flow, and its CAS and name.

    Everything `resolve_flow_layers` needs to know about a flow before it starts
    grouping.  A record rather than five locals because it is now computed in a
    pass of its own: the contested-CAS index has to be built from the flows that
    reach the CAS branch, and that is not knowable until the qualifier, material
    and nuclide axes have been asked.
    """

    display_name: str
    norm_name: str
    qualifier: str
    material: str | None
    #: The land class this flow is, where a curated row says so.  A fifth
    #: exclusive axis beside the material: a land flow carries no registry
    #: number and its name is the only thing that ever held its class, which is
    #: what put `Occupation, Forest, Unspecified` and `Transformation, From
    #: Forest, Unspecified` on two objects held apart by the words `From`.
    land_use: LandUse | None
    #: The particle size window this flow was cut at, where a curated row says
    #: so.  A sixth exclusive axis, on the same terms as the land class and for
    #: the same reason: an airborne-particle row carries no registry number --
    #: not one of the 200 in `particulate-flow-classes.json` ships a CAS or an
    #: EC number -- so its name was the only thing that ever held the window.
    #: That is what let BAFU's 2.5-10 um rows reach `Particles (PM10)` on a
    #: label, and what left its PM10 rows minting a substance of their own
    #: beside the PM10 the list already published (#153).
    size_class: SizeClass | None
    cas_key: tuple[str, ...]
    nuclide_basis: str | None


def _axes_for(flow: Flow, source_label: str = "") -> _Axes:
    display_name = flow_label_value(flow).strip()
    # Detect qualifier from the display name first.  After transformers
    # normalise the name (e.g. "carbon dioxide (biogenic)" → "Carbon
    # Dioxide"), fall back to the source_refs' original flow names.
    #
    # The source names are also consulted when the display name gave a
    # qualifier but not a delayed-emission one.  Every correction flow's
    # name contains the word a coarser check reads -- "of fossil methane"
    # detects `fossil` -- so a rename to `Methane (fossil)` would send the
    # correction back to the substance object it must stay off, silently
    # and with nothing to review.  The name the flow arrived under is the
    # one that knows (#268).
    qualifier = detect_origin_qualifier(display_name)
    if not is_delayed_emission_correction(qualifier):
        qualifiers_from_refs: set[str] = set()
        for _ref in flow.source_refs:
            if isinstance(_ref, dict):
                _q = detect_origin_qualifier(str(_ref.get("source_flow_name") or ""))
                if _q:
                    qualifiers_from_refs.add(_q)
        corrections = {
            _q for _q in qualifiers_from_refs if is_delayed_emission_correction(_q)
        }
        if len(corrections) == 1:
            qualifier = next(iter(corrections))
        elif not qualifier and len(qualifiers_from_refs) == 1:
            qualifier = next(iter(qualifiers_from_refs))
    return _Axes(
        display_name=display_name,
        norm_name=_norm_text(display_name) if display_name else "",
        qualifier=qualifier,
        # The material is looked up, never inferred.  A name-reading rule of
        # the kind `detect_origin_qualifier` uses for qualifiers is exactly what
        # `water-flow-materials.json` exists to avoid: no algorithm reads
        # `Water, salt, sole` and knows it is brine.  The flow's own uuid is the
        # base list's; `source_refs` carry the other lists'.
        material=_material_for(flow, base_source_label(), source_label),
        # The land class, on the same terms and for a stronger version of the
        # same reason: water at least has a CAS to fall back on, and a land
        # flow has nothing but its name.
        land_use=_land_class_for(flow, base_source_label(), source_label),
        # The size window, on exactly the same terms.  Disjoint from the other
        # two by construction: nothing in `particulate-flow-classes.json` is a
        # water flow or a piece of ground, so the three axes cannot both claim
        # a flow and the order they are asked in decides nothing.
        size_class=_particulate_size_for(flow, base_source_label(), source_label),
        cas_key=_norm_cas(flow.cas_numbers),
        nuclide_basis=_nuclide_object_basis(display_name),
    )


def _resolves_by_cas(flow: Flow, axes: _Axes, uuid_override: dict[str, str]) -> bool:
    """Would this flow be grouped by its registry number?

    False for a flow with no number, for one placed by hand, and for every flow
    an exclusive axis claims first -- a nuclide, a named material, or a
    qualified flow, each of which is looked up in its own table and can no more
    be fused by a CAS than separated by one.  This is the population the
    contested-CAS question is *about*; see `flow_layers.contested_cas`.
    """
    return bool(
        axes.cas_key
        and flow.uuid.strip() not in uuid_override
        and not axes.nuclide_basis
        and not axes.material
        and not axes.land_use
        and not axes.qualifier
    )


def contested_cas_verdicts(
    flows: list[Flow],
    *,
    source_list: SourceList,
    overrides_path: Path | None = None,
) -> dict[str, ContestedCas]:
    """One verdict per registry number more than one name in *flows* claims.

    Public because two callers need the same answer and neither may guess it:
    `resolve_flow_layers` acts on it, and the pipeline turns the undecided ones
    into review items.  The filtering is the part that must not be duplicated --
    only the flows that reach the CAS branch are asked about, and which those
    are is this module's knowledge.
    """
    uuid_override = _uuid_overrides(_load_overrides(overrides_path))
    prepared = [
        (flow, _axes_for(flow, source_list.source_label))
        for flow in flows
        if flow.uuid.strip()
    ]
    return _verdicts_for(prepared, source_list=source_list, uuid_override=uuid_override)


def _verdicts_for(
    prepared: list[tuple[Flow, _Axes]],
    *,
    source_list: SourceList,
    uuid_override: dict[str, str],
) -> dict[str, ContestedCas]:
    """The index, from flows whose axes have already been worked out.

    Split from `contested_cas_verdicts` so that `resolve_flow_layers`, which
    computes `prepared` for its own loop, does not pay for a second pass over
    every flow -- `_axes_for` asks the material taxonomy about each one.
    """
    return contested_cas_index(
        [flow for flow, axes in prepared if _resolves_by_cas(flow, axes, uuid_override)],
        decisions=load_decisions(),
        supplied_by_us=cas_supplied_by_manual_fixes(source_list.manual_fixes_path),
        commonchemistry=commonchemistry_details(),
        list_name=source_list.list_name,
        list_version=source_list.list_version,
    )


def resolve_flow_layers(
    flows: list[Flow],
    *,
    source_list: SourceList,
    overrides_path: Path | None = None,
    include_pubchem_isotopes: bool = False,
    original_context_by_uuid: dict[str, Any] | None = None,
    apply_curated_names: bool = False,
) -> tuple[list[FlowObject], list[ElementaryFlow], dict[str, Any]]:
    """Resolve flows into shared flow objects and context-specific elementary flows.

    *source_list* is the list *flows* were read from.  It is asked for rather
    than worked out: a flow that reaches here without a `source_refs` entry gets
    one built from that list's `(list_name, list_version)`, and those two values
    are published (#13).  Every caller has the list in hand -- the transform
    the base list, the merge the list it is consuming -- so nothing is served by
    re-deriving it from `flow.source`, which is a display string.
    """
    overrides = _load_overrides(overrides_path)
    uuid_override = _uuid_overrides(overrides)
    stated_labels = _merge_group_labels(overrides)
    object_names = _object_names(overrides)
    #: `(object id, the name the row was written about, the name found)` per
    #: curated rename that no longer applies.  Logged below, so that a rename
    #: which silently stopped happening is still counted.
    stale_object_names: list[tuple[str, str, str]] = []

    object_by_id: dict[str, dict[str, Any]] = {}
    object_id_by_name: dict[str, str] = {}
    object_id_by_cas_set: dict[tuple[str, ...], str] = {}
    object_id_by_cas: dict[str, str] = {}
    # Qualified flows (biogenic/fossil/land_use_change) share a CAS with the
    # base substance but must resolve to separate flow objects.  The key is
    # (qualifier, *sorted_cas_numbers).
    object_id_by_qual_cas: dict[tuple[str, ...], str] = {}
    # A flow whose name is a nuclide is keyed by *that nuclide*, in place of
    # its CAS.  See `_nuclide_object_basis`.
    object_id_by_nuclide: dict[str, str] = {}
    # Flows of a named environmental material share a CAS with unqualified
    # water and must not merge with it: `sea water`, `cooling water` and brine
    # are all H2O.  Keyed by the concept alone rather than by (concept, CAS),
    # because the concept *is* the identity here -- brine carries no CAS at all,
    # its being a mixture rather than the molecule.
    object_id_by_material: dict[str, str] = {}
    # One object per land class, keyed by `LandUse.key`.  The class *is* the
    # identity here, more completely than for a material: a land flow carries no
    # registry number at all, and the only thing that has ever separated
    # `Transformation, from forest, primary` from `Transformation, to forest,
    # primary` -- a balanced pair EF characterises at -396.7 and +396.7 -- is
    # the words `from` and `to` inside a name that `pipeline/deduplication.py`
    # does not sign on.  Keying on the class makes them two values, which mints
    # two objects, which is what holds the pair apart (#66 §1.7).
    object_id_by_land_class: dict[str, str] = {}
    # One object per particle size window, keyed by the size class id.  The
    # window *is* the identity here, on the same terms as the land class and
    # for the same reason: not one of the 200 airborne-particle rows in the six
    # registered lists carries a registry number, so the only thing that has
    # ever separated `Particles (PM10)` from `Particles (PM2.5 - PM10)` is words
    # inside a name -- and a name is what let BAFU's coarse rows reach PM10 on a
    # synonym, and left its PM10 rows minting a substance of their own (#153).
    object_id_by_size_class: dict[str, str] = {}
    # Set of object IDs that have at least one CAS number registered.  Used
    # by the CAS-disjoint name-match guard below.
    objects_with_cas: set[str] = set()
    cas_quality_by_object: dict[str, set[str]] = {}
    cas_sources_by_object: dict[str, dict[str, dict[str, Any]]] = {}
    elementary_flows: list[dict[str, Any]] = []
    override_hits = 0
    cas_conflict_guard_hits = 0
    nuclide_object_hits = 0
    # Flows that arrived with no `source_refs` and had one built from
    # *source_list*.  Counted because it is the only place the identity is not
    # already on the record, and a build where that number moves is a build
    # where something upstream stopped attaching references.
    derived_source_refs = 0

    # Which axis claims each flow, worked out once.  This used to be the head of
    # the loop below and is lifted out because two passes need it: the loop, and
    # the contested-CAS index, which must be built from the flows that actually
    # reach the CAS branch.  Including the others would manufacture contests
    # that cannot happen -- EF's fourteen waters disagree on `Water use` by a
    # factor of 450 and are already separated by the material axis, and reading
    # that as a contest would move unqualified water off its own identifier.
    prepared: list[tuple[Flow, _Axes]] = [
        (flow, _axes_for(flow, source_list.source_label))
        for flow in flows
        if flow.uuid.strip()
    ]

    contested = _verdicts_for(
        prepared, source_list=source_list, uuid_override=uuid_override
    )
    separated_cas = {
        cas for cas, verdict in contested.items() if verdict.verdict is Verdict.SEPARATE
    }
    contested_cas_separations = 0

    for flow, axes in prepared:
        uuid = flow.uuid.strip()
        display_name = axes.display_name
        norm_name = axes.norm_name
        qualifier = axes.qualifier
        material = axes.material
        land_use = axes.land_use
        size_class = axes.size_class
        cas_key = axes.cas_key
        nuclide_basis = axes.nuclide_basis
        ec_numbers = sorted({
            str(v).strip()
            for v in flow.ec_numbers
            if isinstance(v, str) and v.strip()
        })

        # A contested number this flow carries, ruled `separate`.  Computed once
        # because the grouping below and the index registration further down
        # must agree about it: an object minted off the CAS must not then be
        # registered under the CAS.
        separated_here = bool(
            norm_name
            and _resolves_by_cas(flow, axes, uuid_override)
            and separated_cas & set(cas_key)
        )

        object_id = uuid_override.get(uuid)
        if object_id:
            override_hits += 1
        elif nuclide_basis:
            # Exclusive, like the qualifier branch below it: a nuclide is
            # looked up only among nuclides, so no CAS and no name can merge it
            # with anything else.  Both source lists spell these the same way,
            # so the two `Uranium-238` rows still meet -- on the nuclide rather
            # than on the element's registry number.
            object_id = object_id_by_nuclide.get(nuclide_basis) or _stable_object_id(
                "fo", nuclide_basis
            )
            nuclide_object_hits += 1
        elif separated_here:
            # A registry number ruled contested groups nothing: the name does.
            # Exclusive like the two branches above it, and for the same reason
            # -- the number these flows share is the thing that has been judged
            # untrustworthy, so leaving them reachable through the CAS tables
            # would let the next flow carrying it merge them back together.
            # The CAS stays in the basis so that two lists spelling the
            # substance the same way still meet, and so that the id says which
            # contested number it came from.  See `flow_layers.contested_cas`.
            object_id = _stable_object_id(
                "fo", f"name:{norm_name}|cas:{'|'.join(cas_key)}"
            )
            contested_cas_separations += 1
        else:
            candidate_ids: set[str] = set()
            # Subset of candidate_ids that were found via a CAS lookup (as
            # opposed to a name lookup).  Used by the CAS-disjoint guard.
            cas_candidate_ids: set[str] = set()
            if land_use:
                # Exclusive, and first, because it is the strongest claim any
                # axis makes: a curator has said which land class this flow is,
                # and nothing about a name or a number gets to overrule it.
                oid = object_id_by_land_class.get(land_use.key)
                if oid:
                    candidate_ids.add(oid)
                    cas_candidate_ids.add(oid)
            elif material:
                # Exclusive, like the qualifier and nuclide branches: a named
                # material is looked up only among materials, so neither a
                # shared CAS nor a shared name can merge it with anything else.
                # That is the whole fix -- #31's collapse is two materials
                # meeting on CAS 7732-18-5 with nothing to tell them apart.
                oid = object_id_by_material.get(material)
                if oid:
                    candidate_ids.add(oid)
                    cas_candidate_ids.add(oid)
            elif size_class:
                # Exclusive, like the three above it, and the exclusivity is the
                # fix.  These flows are reachable by name today -- that is how
                # ecoinvent's coarse-fraction spelling, left on `Particles
                # (PM10)` as an alternative label by #37's override, pulled
                # four BAFU coarse rows onto PM10 with nothing recorded but
                # `basis=label`.  Looked up only among size windows, a name
                # cannot do that: a row reaches the flow its window names or it
                # reaches nothing.
                oid = object_id_by_size_class.get(size_class.id)
                if oid:
                    candidate_ids.add(oid)
                    cas_candidate_ids.add(oid)
            elif qualifier and cas_key:
                # Qualified flows are looked up exclusively in the qualifier
                # index so they never merge with the base-substance object.
                qual_key = (qualifier,) + cas_key
                if qual_key in object_id_by_qual_cas:
                    oid = object_id_by_qual_cas[qual_key]
                    candidate_ids.add(oid)
                    cas_candidate_ids.add(oid)
            else:
                if cas_key and cas_key in object_id_by_cas_set:
                    oid = object_id_by_cas_set[cas_key]
                    candidate_ids.add(oid)
                    cas_candidate_ids.add(oid)
                if norm_name and norm_name in object_id_by_name:
                    candidate_ids.add(object_id_by_name[norm_name])
                if cas_key:
                    for cas in cas_key:
                        existing = object_id_by_cas.get(cas)
                        if existing:
                            candidate_ids.add(existing)
                            cas_candidate_ids.add(existing)

            if len(candidate_ids) == 1:
                candidate_id = next(iter(candidate_ids))
                # CAS-disjoint name-match guard: if the sole candidate was
                # found by name only (no CAS overlap) yet the candidate
                # already owns CAS numbers, the current flow's CAS must be
                # entirely disjoint — indicating a chemically distinct
                # substance that shares a normalised name (e.g. stereoisomers
                # whose names were simplified to a common parent by an
                # upstream transformer).  Create a new flow object instead of
                # merging so chemical identity is preserved.
                if (
                    cas_key
                    and candidate_id not in cas_candidate_ids
                    and candidate_id in objects_with_cas
                ):
                    object_id = _stable_object_id("fo", f"cas:{'|'.join(cas_key)}")
                    cas_conflict_guard_hits += 1
                else:
                    object_id = candidate_id
            elif len(candidate_ids) > 1:
                # CAS uniqueness guard: if there is ambiguity across objects, prefer CAS mappings.
                cas_mapped = {
                    object_id_by_cas[cas]
                    for cas in cas_key
                    if cas in object_id_by_cas
                } if cas_key else set()
                if len(cas_mapped) == 1:
                    object_id = next(iter(cas_mapped))
                    cas_conflict_guard_hits += 1
                else:
                    basis = f"name:{norm_name}" if norm_name else f"uuid:{uuid}"
                    if cas_key:
                        basis += f"|cas:{'|'.join(cas_key)}"
                    object_id = _stable_object_id("fo", basis)
                    cas_conflict_guard_hits += 1
            else:
                if land_use:
                    # The key and nothing else.  Two spellings of one class --
                    # EF's `arable, non-irrigated, intensive`, ecoinvent's and
                    # BAFU's `annual crop, non-irrigated, intensive` -- produce
                    # one key, mint one id and meet on one object, with no
                    # crosswalk row required.  That is the whole of §3.4.
                    object_id = land_object_id(land_use)
                elif material:
                    # From the taxonomy rather than composed here, so the basis
                    # a concept mints under is stated in one place and checked
                    # against the ids already published.
                    basis = flow_object_basis_for(material)
                    object_id = _stable_object_id("fo", basis) if basis else None
                    if object_id is None:
                        # A concept nothing maps onto has no basis, so a row
                        # pointing at one is an authoring error rather than a
                        # flow to place quietly.
                        raise ValueError(
                            f"material {material!r} mints no flow object, but "
                            f"flow {uuid} is assigned to it"
                        )
                elif size_class:
                    # The window and nothing else.  `Particulates, < 10 um` and
                    # `particles (PM10)` state one window, mint one id and meet
                    # on one object; `Particulates, > 2.5 um, and < 10um` states
                    # a different one and cannot arrive at PM10 by resembling
                    # it.  That is the whole of `plans/particulate-taxonomy.md`
                    # §3.1, and it is what #153 needed.
                    #
                    # Six of the seven classes declare the `name:` basis they
                    # are minted from today, so the objects EF 3.1 already
                    # publishes keep their identifiers: giving the window a
                    # field is not a reason for PM10 to change id.
                    object_id = _stable_object_id(
                        "fo", size_class.flow_object_basis
                    )
                elif qualifier and cas_key:
                    object_id = _stable_object_id("fo", f"qual:{qualifier}|cas:{'|'.join(cas_key)}")
                elif cas_key:
                    object_id = _stable_object_id("fo", f"cas:{'|'.join(cas_key)}")
                elif norm_name:
                    object_id = _stable_object_id("fo", f"name:{norm_name}")
                else:
                    object_id = _stable_object_id("fo", f"uuid:{uuid}")

        pref = coerce_pref_label(flow.prefLabel)
        pref_value = pref.value.strip() if pref is not None else ""
        if not pref_value:
            pref_value = display_name
        # The name the source list published, kept where the class renames the
        # object below.  A published name is a name the list answers to (#113),
        # so it is demoted to an alternative rather than dropped -- the same
        # thing a stated merge-group label does further down, and the reason
        # that mechanism exists.
        renamed_from = ""
        if land_use:
            # The class names the object, for the reason the material does and
            # then some: the members are three lists' spellings of one thing,
            # and letting one win would publish `Occup. As Forest Land` as the
            # name of natural forest because it sorted first.  `LandUse.label`
            # is built from the fields, so the name and the identity cannot
            # disagree, and all three lists' rows read as one class rather than
            # as whichever spelling reached it first.
            if pref_value and _norm_text(pref_value) != _norm_text(land_use.label):
                renamed_from = pref_value
            pref_value = land_use.label
        if material:
            # The concept names the object, not whichever member reached it
            # first.  This is #251 section 1: the object standing for every kind
            # of water published as `Water From Cooling` because the label rule
            # had 35 candidate names and no reason to prefer one.  Splitting the
            # materials shrinks each group but does not settle it -- `Water to
            # Cooling` and `Water Cooling sea` are one object and one of their
            # names would still have to win.  The taxonomy already states the
            # label, so nothing has to choose.
            concept_label = material_concepts()[material]["label"]
            if concept_label:
                pref_value = concept_label
        if size_class:
            # The window names the object, for the reason the material and the
            # land class do: the members are five lists' spellings of one cut,
            # and letting one win would publish PM10 under whichever of
            # `Particulates, < 10 um` and `particles (PM10)` happened to reach
            # it first.  The scheme states the label, so nothing has to choose,
            # and the five existing labels are exactly what the scheme states --
            # so this renames only the size-unstated total, which today is four
            # objects under four vendor spellings.
            if pref_value and _norm_text(pref_value) != _norm_text(size_class.label):
                renamed_from = pref_value
            pref_value = size_class.label
        # For qualified flow objects whose prefLabel was stripped of its
        # qualifier by an upstream transformer, recover the original qualified
        # name from source_refs so the flow object is self-describing.
        if qualifier and not detect_origin_qualifier(pref_value):
            for _ref in flow.source_refs:
                if isinstance(_ref, dict):
                    _sname = str(_ref.get("source_flow_name") or "").strip()
                    if detect_origin_qualifier(_sname) == qualifier:
                        pref_value = _sname
                        break
        # A merge group that states its object's label names it here, and the
        # member's own name is kept as an alternative.  Last, so that it is the
        # statement and not the length rule that settles a group somebody had
        # to write down; a group that states nothing is untouched.
        demoted_pref_value = renamed_from
        stated_label = stated_labels.get(object_id)
        if stated_label and _norm_text(pref_value) != _norm_text(stated_label):
            demoted_pref_value = pref_value
            pref_value = stated_label

        properties = flow.properties if isinstance(flow.properties, dict) else {}
        definitions: list[dict[str, Any]] = []
        if isinstance(flow.skos_definition, list):
            seen_defs: set[tuple[str, str]] = set()
            # A definition entry is a serialised `{"@value": ...}` mapping the
            # record carries verbatim, so this guard is a real check.
            for row in flow.skos_definition or []:
                if not isinstance(row, dict):
                    continue
                key = _definition_key(row)
                if not key[1] or key in seen_defs:
                    continue
                seen_defs.add(key)
                definitions.append(_strip_definition_markup(row))
        references: list[Any] = []
        if isinstance(flow.references, list):
            seen_reference_keys: set[str] = set()
            for entry in flow.references:
                key = _reference_key(entry)
                if not key or key in seen_reference_keys:
                    continue
                seen_reference_keys.add(key)
                if isinstance(entry, dict):
                    references.append(entry)
                elif isinstance(entry, str):
                    references.append(entry.strip())
        cas_match_labels = flow.cas_match_labels
        if isinstance(cas_match_labels, dict):
            valid_qualities = {
                str(v).strip()
                for k, v in cas_match_labels.items()
                if isinstance(k, str)
                and isinstance(v, str)
                and k in cas_key
                and str(v).strip()
            }
            if valid_qualities:
                cas_quality_by_object.setdefault(object_id, set()).update(valid_qualities)
        cas_number_sources = flow.cas_number_sources
        if isinstance(cas_number_sources, dict):
            bucket = cas_sources_by_object.setdefault(object_id, {})
            for cas, prov in cas_number_sources.items():
                if isinstance(cas, str) and cas.strip() and isinstance(prov, dict):
                    bucket.setdefault(cas, prov)

        created_from = {
            "resolver": "hybrid_name_cas_v1",
            "seed_uuid": uuid,
            "seed_source": flow.source or "",
        }
        pref_language = pref.language.strip() if pref is not None and isinstance(pref.language, str) and pref.language.strip() else "en"
        # Only the flow's own prefLabel carries the flow's prefLabel provenance.
        # `pref_value` above falls back to `display_name` or to a qualified name
        # recovered from `source_refs`, and neither is the string the label's
        # provenance describes, so those keep the layering's own attribution.
        pref_source = (
            pref.source
            if pref is not None and pref.value.strip() == pref_value
            else None
        )
        pref_label_rows = [
            _label_entry(
                value=pref_value,
                language=pref_language,
                resolver_name=str(created_from.get("resolver") or ""),
                seed_source=str(created_from.get("seed_source") or ""),
                was_derived_from="prefLabel",
                label_source=pref_source,
            )
        ] if pref_value else []
        alt_label_rows: list[dict[str, Any]] = []
        for item in coerce_alt_labels(flow.altLabel):
            alt_value = item.value.strip()
            if not alt_value:
                continue
            alt_lang = item.language.strip() if isinstance(item.language, str) and item.language.strip() else "en"
            alt_label_rows.append(
                _label_entry(
                    value=alt_value,
                    language=alt_lang,
                    resolver_name=str(created_from.get("resolver") or ""),
                    seed_source=str(created_from.get("seed_source") or ""),
                    was_derived_from="altLabel",
                    label_source=item.source,
                )
            )
        if demoted_pref_value:
            # The name this flow was published under, kept where a reader and a
            # search will still find it.  `wasDerivedFrom` says `prefLabel`
            # because that is where it came from, and the flow's own label
            # provenance travels with it.
            alt_label_rows.append(
                _label_entry(
                    value=demoted_pref_value,
                    language=pref_language,
                    resolver_name=str(created_from.get("resolver") or ""),
                    seed_source=str(created_from.get("seed_source") or ""),
                    was_derived_from="prefLabel",
                    label_source=(
                        pref.source
                        if pref is not None and pref.value.strip() == demoted_pref_value
                        else None
                    ),
                )
            )
        if size_class:
            # The window's `Particulates` spellings, always.  Stated by the
            # scheme rather than left to `carry_member_names`, which keeps a
            # member's name only where no other substance claims it: on the
            # build of 2 September 2026 PM10 published `Particulates, < 10 um
            # (stationary)` and not the plain spelling, because Stepwise's
            # stray substance held that one as its own name.  A reader
            # searching the export for the ecoinvent-2 spelling finds the
            # window whichever vendor's rows reached it (#196).
            present = {_norm_text(pref_value)} | {
                _norm_text(str(row.get("@value") or "")) for row in alt_label_rows
            }
            for spelling in size_class.alt_labels:
                if _norm_text(spelling) in present:
                    continue
                present.add(_norm_text(spelling))
                alt_label_rows.append(
                    _label_entry(
                        value=spelling,
                        language="en",
                        resolver_name=_SIZE_CLASS_LABEL_ACTIVITY,
                        seed_source=_SIZE_CLASS_LABEL_SOURCE,
                        was_derived_from="particulate-size-classes.json alt_labels",
                    )
                )
        classifications = _build_classifications(
            cas_numbers=list(cas_key),
            ec_numbers=ec_numbers,
            seed_source=str(created_from.get("seed_source") or ""),
            resolver_name=str(created_from.get("resolver") or ""),
            cas_quality_values=cas_quality_by_object.get(object_id, set()),
            cas_number_sources=cas_sources_by_object.get(object_id),
        )

        # For qualified flows, look up the parent (unqualified) flow object.
        parent_foid = object_id_by_cas_set.get(cas_key) if qualifier and cas_key else None

        if object_id not in object_by_id:
            object_by_id[object_id] = (
                FlowObject(
                    flow_object_id=object_id,
                    prefLabel=pref_label_rows,
                    altLabel=alt_label_rows,
                    properties=dict(properties),
                    references=references,
                    created_from=created_from,
                    classifications=classifications,
                    origin_qualifier=qualifier,
                    parent_flow_object_id=parent_foid,
                )
            )
            if definitions:
                object_by_id[object_id].skos_definition = definitions
        else:
            obj = object_by_id[object_id]
            current_pref = _object_pref_label_value(obj)
            if qualifier:
                # For qualified flows prefer the shorter canonical form so that
                # "Correction flow for delayed emission of biogenic ..." never
                # replaces "carbon dioxide (biogenic)" as the prefLabel.
                if pref_value and len(pref_value) < len(current_pref):
                    obj.prefLabel = pref_label_rows
                else:
                    obj.prefLabel = _merge_label_rows(obj.prefLabel, pref_label_rows)
            elif pref_value and len(pref_value) > len(current_pref):
                obj.prefLabel = pref_label_rows
            else:
                obj.prefLabel = _merge_label_rows(obj.prefLabel, pref_label_rows)
            obj.altLabel = _merge_label_rows(obj.altLabel, alt_label_rows)
            merged_references: dict[str, Any] = {}
            for entry in obj.references + references:
                key = _reference_key(entry)
                if not key:
                    continue
                if key not in merged_references:
                    merged_references[key] = entry
                elif isinstance(entry, dict):
                    # Prefer richer dictionary references over plain strings.
                    merged_references[key] = entry
            obj.references = [merged_references[key] for key in sorted(merged_references)]
            merged_definitions: dict[tuple[str, str], dict[str, Any]] = {}
            for entry in (obj.skos_definition or []) + definitions:
                key = _definition_key(entry)
                if not key[1]:
                    continue
                if key not in merged_definitions:
                    merged_definitions[key] = entry
                else:
                    existing_prov = merged_definitions[key].get("provenance")
                    new_prov = entry.get("provenance")
                    rows: list[dict[str, Any]] = []
                    if isinstance(existing_prov, dict):
                        rows.append(existing_prov)
                    elif isinstance(existing_prov, list):
                        rows.extend([x for x in existing_prov if isinstance(x, dict)])
                    if isinstance(new_prov, dict):
                        marker = orjson.dumps(new_prov, option=orjson.OPT_SORT_KEYS).decode("utf-8")
                        seen = {
                            orjson.dumps(row, option=orjson.OPT_SORT_KEYS).decode("utf-8")
                            for row in rows
                        }
                        if marker not in seen:
                            rows.append(new_prov)
                    merged_definitions[key]["provenance"] = rows[0] if len(rows) == 1 else rows
            if merged_definitions:
                obj.skos_definition = [
                    merged_definitions[key]
                    for key in sorted(merged_definitions.keys(), key=lambda x: (x[0], x[1].lower()))
                ]
            obj.properties = _deep_merge(obj.properties, properties)
            existing_classifications = obj.classifications
            merged_cas = sorted(
                set(_classification_values(existing_classifications, CHEMINF_CAS_REGISTRY_NUMBER))
                | set(cas_key)
            )
            merged_ec = sorted(
                set(_classification_values(existing_classifications, CHEMINF_EC_NUMBER))
                | set(ec_numbers)
            )
            rebuilt = _build_classifications(
                cas_numbers=merged_cas,
                ec_numbers=merged_ec,
                seed_source=str((obj.created_from or {}).get("seed_source") or ""),
                resolver_name=str((obj.created_from or {}).get("resolver") or "hybrid_name_cas_v1"),
                cas_quality_values=cas_quality_by_object.get(object_id, set()),
                cas_number_sources=cas_sources_by_object.get(object_id),
            )
            obj.classifications = rebuilt

        if land_use:
            # Registered under the class alone, and in neither the CAS nor the
            # name table -- the same exclusivity a material gets, and needed
            # more here.  Fifteen land classes arrive under two names from one
            # list, and every one of the 353 objects this replaces was reachable
            # by a name that another class also spells.
            object_id_by_land_class.setdefault(land_use.key, object_id)
        elif nuclide_basis:
            # Registered in the nuclide table and in *no other*.  Putting a
            # nuclide's CAS in the CAS table is what merged elemental uranium
            # into U-238: the element's own kg and MJ flows arrive later, look
            # up `7440-61-1`, and find the nuclide already sitting on it.  The
            # name table is skipped for the same reason -- `Uranium-238`
            # reaches this object through the nuclide key, and nothing that is
            # not that nuclide should reach it at all.
            object_id_by_nuclide.setdefault(nuclide_basis, object_id)
        elif material:
            # Registered under the concept alone, and in neither the CAS nor the
            # name table.  Both would let unqualified water reach this object:
            # every one of these shares CAS 7732-18-5, and several share a
            # normalised name with it.  Reaching it by the concept is the only
            # way in, which is what makes the identity hold.
            object_id_by_material.setdefault(material, object_id)
        elif size_class:
            # Registered under the window alone, and in neither the CAS nor the
            # name table.  The name table is the one that matters: every source
            # spelling of a size band -- `Particulates, < 10 um`, `particles
            # (PM10)`, `Particulate Matter, < 2.5 um` -- would otherwise be a
            # way in, and a spelling left on a *neighbouring* flow as an
            # alternative label is a way into the wrong one. That is exactly
            # what happened to `Particles (PM10)`, which carries both of
            # ecoinvent's coarse-fraction names and collected four BAFU coarse
            # rows through them. Reaching these objects by the window is the
            # only way in, which is what makes the identity hold (#153).
            object_id_by_size_class.setdefault(size_class.id, object_id)
        elif separated_here:
            # Registered nowhere, like the two above.  The CAS tables are the
            # point: a number ruled contested has been judged not to identify
            # anything, so a later flow carrying it must not find this object
            # through it.  The name table is skipped too -- the id is a function
            # of name and CAS together, so every flow that belongs here reaches
            # it by minting the same id, and a flow that shares only the name
            # belongs somewhere else.
            pass
        else:
            # Only register in the name lookup when the name actually contains
            # the qualifier (or there is no qualifier), so that a normalized
            # name like "carbon dioxide" from a fossil flow never pollutes the
            # name table and causes it to match against unqualified flows.
            if norm_name and (not qualifier or detect_origin_qualifier(norm_name)):
                object_id_by_name.setdefault(norm_name, object_id)
            if qualifier and cas_key:
                qual_key = (qualifier,) + cas_key
                object_id_by_qual_cas.setdefault(qual_key, object_id)
            elif cas_key:
                object_id_by_cas_set.setdefault(cas_key, object_id)
                for cas in cas_key:
                    object_id_by_cas.setdefault(cas, object_id)
                objects_with_cas.add(object_id)

        src = (flow.source or "").strip()
        source_refs = flow.source_refs
        # The compartment the source list shipped.  The caller's snapshot when
        # there is one, and otherwise the flow's own copy of it -- which is
        # `provided.context`, not `context`: `context` is the consensus answer
        # and saying "originally" of it would be false (#97).
        raw_original_context = (
            original_context_by_uuid.get(uuid)
            if isinstance(original_context_by_uuid, dict)
            else flow.provided.context
        )
        original_context = _context_as_string_list(raw_original_context)
        if not isinstance(source_refs, list) or not source_refs:
            derived_source_refs += 1
            source_refs = [
                _source_ref_for(
                    source_list,
                    uuid,
                    display_name,
                    original_context=original_context,
                ).to_dict()
            ]
        else:
            if source_list.role == BASE_ROLE:
                patched_refs: list[dict[str, Any]] = []
                for ref in source_refs:
                    if not isinstance(ref, dict):
                        continue
                    metadata = ref.get("source_metadata")
                    if not isinstance(metadata, dict):
                        metadata = {}
                    if "original_context" not in metadata:
                        metadata["original_context"] = original_context
                    row = dict(ref)
                    row["source_metadata"] = metadata
                    patched_refs.append(row)
                if patched_refs:
                    source_refs = patched_refs

        elementary_flows.append(
            (
                ElementaryFlow(
                    elementary_flow_id=uuid,
                    flow_object_id=object_id,
                    source=src,
                    source_refs=source_refs,
                    context=flow.context,
                    context_iri=flow.context_iri or "",
                    unit=flow.unit,
                    unit_iri=flow.unit_iri or None,
                    lcia_methods=flow.lcia_methods if isinstance(flow.lcia_methods, list) else [],
                    general_comment=flow.general_comment,
                    cas_match_labels=flow.cas_match_labels if isinstance(flow.cas_match_labels, dict) else {},
                )
            )
        )

    # Post-processing: fill in parent_flow_object_id for qualified flow objects
    # whose parent was created AFTER them in the iteration order.
    for obj in object_by_id.values():
        if obj.origin_qualifier and obj.parent_flow_object_id is None:
            obj_classifications = obj.classifications
            obj_cas = tuple(sorted(_classification_values(obj_classifications, CHEMINF_CAS_REGISTRY_NUMBER)))
            if obj_cas:
                parent = object_id_by_cas_set.get(obj_cas)
                if parent and parent != obj.flow_object_id:
                    obj.parent_flow_object_id = parent

    # What each substance is *used for*, from ChEBI's `RO:0000087 has role`.
    # After the loop rather than inside it because an object's CAS set is only
    # complete once every flow that grouped onto it has been seen, and the role
    # lookup keys on CAS.
    role_stats = assign_chebi_roles(list(object_by_id.values()))
    # The curator's half, second and additive.  ChEBI has no `has role` edge for
    # roughly half the substances a source list collapses into a group bucket,
    # and asserting after the generated pass rather than before it means a
    # substance can hold both -- ChEBI's `agrochemical` and a curated
    # `fungicide` are two true statements about laminarin, not a conflict.
    curated_role_stats = assign_curated_roles(list(object_by_id.values()))

    # Curated names, and `apply_curated_names` is why they are opt-in.
    #
    # A name is a *publication* concern; an axis is an *identity* one, and this
    # rename is the one place they can collide.  `_axes_for` reads a flow's
    # prefLabel, so a qualified object renamed to something no qualifier pattern
    # matches loses the axis that keeps it off the base substance -- which is the
    # failure #268's comment describes two hundred lines above: "a rename to
    # `Methane (fossil)` would send the correction back to the substance object
    # it must stay off, silently and with nothing to review".
    #
    # It is not hypothetical.  `pipeline.engine` runs a *pre-pass* layering to
    # hand `consensus_match` its groupings, and that transformer carries an
    # object's prefLabel onto its member flows.  Rename there and the flows
    # themselves come back renamed, so the next pass reads
    # `Carbon Dioxide (sequestration from land management)`, finds no qualifier
    # in it, and mints on the bare CAS -- an id unqualified carbon dioxide
    # already owns, so the substance is not created at all.  Measured: eight rows
    # lost, one object short, `flow_object_creation_blocked_by_existing_object`.
    #
    # So the pre-pass leaves names alone and only the passes whose objects are
    # written ask for them.  A name that reaches nothing but the artifact cannot
    # move a flow.
    applied_object_names = 0
    stated_object_names = 0
    for object_id, name in (object_names if apply_curated_names else {}).items():
        row = object_by_id.get(object_id)
        if row is None:
            # Not this pass's row, and *not* countable as an error here.  A
            # layering pass resolves one source list, so an id it built no object
            # for looks exactly the same whether it is a curator's typo or a row
            # about a substance some other list mints -- and both are ordinary:
            # the base pass resolves EF 3.1 and neither shipped row names an EF
            # object, because the merge mints both out of ecoinvent rows.
            #
            # Counting it anyway is what the first version of this loop did, and
            # it reported two correct rows as broken on every build while the
            # `applied` count beside it said the renames had not happened.  That
            # is the same misreading the count was added to prevent, inverted.
            #
            # The question is answerable, just not here: a `names` row should
            # name an object *the finished artifact* publishes under the
            # preferred label, and every object exists by then.  It is asked once
            # as `names.rows_unpublished` in `assessment.measures`.
            continue
        stated_object_names += 1
        current = _object_pref_label_value(row)
        if _norm_text(current) != _norm_text(name.current_label):
            # Written about a name that is no longer there.  Counted, not obeyed.
            stale_object_names.append((object_id, name.current_label, current))
            continue
        _rename_object(row, preferred=name.preferred_label, demoted=current)
        applied_object_names += 1

    flow_objects = sorted(
        object_by_id.values(),
        key=lambda row: _object_pref_label_value(row).lower(),
    )
    elementary_flows = sorted(
        elementary_flows,
        key=lambda row: row.elementary_flow_id,
    )
    stats = {
        "flow_object_count": len(flow_objects),
        "elementary_flow_count": len(elementary_flows),
        "override_hits": override_hits,
        "cas_conflict_guard_hits": cas_conflict_guard_hits,
        "nuclide_object_hits": nuclide_object_hits,
        "contested_cas_numbers": len(contested),
        "contested_cas_separated": len(separated_cas),
        "contested_cas_undecided": sum(
            1 for v in contested.values() if v.verdict is Verdict.UNDECIDED
        ),
        # Flows kept off a shared object by a `separate` verdict.  Reported
        # because a run where this moves is a run where a ruling, a manual fix
        # or the source list's own factors changed.
        "contested_cas_separations": contested_cas_separations,
        "nuclide_object_count": len(object_id_by_nuclide),
        "material_object_count": len(object_id_by_material),
        # One per land class a source flow reached. The published scheme is the
        # *reached* space, not the legal one: the axes permit thousands of
        # combinations and three lists between them ship 336.
        "land_class_object_count": len(object_id_by_land_class),
        # One per size window a source flow reached. Seven is the whole scheme,
        # so a smaller number means a window nothing landed on -- a concept
        # minting an object for nobody, which is worth being able to see.
        "size_class_object_count": len(object_id_by_size_class),
        "derived_source_refs": derived_source_refs,
        "role_objects_assigned": role_stats.get("assigned", 0),
        "role_objects_without_chebi_role": role_stats.get("no_role", 0),
        "role_objects_without_cas": role_stats.get("no_cas", 0),
        "role_objects_curated": role_stats.get("curated_present", 0),
        "curated_role_objects_assigned": curated_role_stats.get("objects_assigned", 0),
        "curated_roles_added": curated_role_stats.get("roles_added", 0),
        # A curated row ChEBI had already asserted.  Not an error -- the two
        # agreeing is the good case -- but a number that should stay small,
        # because a curated row that says nothing new is a row to retire.
        "curated_roles_already_generated": curated_role_stats.get(
            "already_generated", 0
        ),
        # Curated rows whose registry number reaches no flow object.  These are
        # the substances still collapsed into a group bucket, so this counts
        # down as #76 is worked through rather than up.
        "curated_roles_unmatched": curated_role_stats.get("unmatched", 0),
    }
    if include_pubchem_isotopes:
        flow_objects, isotope_stats = _augment_with_element_and_isotope_flow_objects(
            flow_objects,
            elementary_flows,
        )
        stats.update(isotope_stats)
        stats["flow_object_count"] = len(flow_objects)
    # Curated renames: how many rows this pass was in a position to apply, how
    # many it did, and the one way a row it *could* have applied can fail.
    # Reported through `stats` rather than a logger, which is this module's
    # convention -- it is a transform and says what it did in its return value.
    # It also makes a rename that stopped happening show up in a build comparison
    # rather than in nobody's scrollback: `object_names_stale` should be 0, and a
    # 1 names the file to go and read.
    #
    # `stated` counts rows whose object is *here*, so `stated == applied + stale`
    # always, and a pass with none of the objects reports three zeros rather than
    # a number a reader would take for a rename that did not happen.  Whether the
    # file as a whole reached the artifact is a question about the artifact, and
    # `names.rows_unpublished` asks it there.
    stats["object_names_stated"] = stated_object_names
    stats["object_names_applied"] = applied_object_names
    stats["object_names_stale"] = len(stale_object_names)
    return flow_objects, elementary_flows, stats
