"""Families of intervention that are not a release of matter.

BAFU files six traffic-noise rows under a compartment it calls ``non material
emissions``, measured per person-kilometre for passenger transport and per
tonne-kilometre for freight.  They are noise from an aircraft, a lorry, a
passenger car, a freight train and a passenger train -- five modes and six
measurements of one thing, and the thing they are all noise *of* has no flow in
any source list (#70).

This pass mints it.  Each member keeps its own flow object, because each is a
distinct measurement with its own unit and its own characterisation factors, and
collapsing them onto one object would put six flows on one object in one
context -- which is what the review app's duplicate check exists to find.  What
they gain is a link to a common parent, published as
``brightway:baseIntervention``.

Not ``brightway:baseSubstance``
-------------------------------

That term already means the undifferentiated substance a qualified flow was
split from, and it says "substance" because it means it.  A noise flow has no
base substance: noise is not matter, which is why
:mod:`brightway_flows.pipeline.semantic_typing` can give it no chemical
class at all.  A second term was minted rather than the first one widened.

What decides membership
-----------------------

Two questions, answered in different places on purpose.  *Is this a candidate*
is answered by the context, through
:func:`~brightway_flows.domain.context.counts_a_non_material_intervention` --
the same question the semantic typing asks, so an object cannot be a
non-material intervention here and chemistry there.  *Which family* is answered
by ``data/non-material-interventions.json``, by name.

A candidate matching no family is counted and returned rather than swept into
the nearest one: a second kind of non-material flow arriving -- ionising
radiation, say -- is a decision to make, and inheriting noise's parent by
default would make it silently.

A family with a single member mints nothing.  One member *is* the intervention,
and a parent above it would be a concept that groups one thing, which is the
rule the material taxonomy already follows for its intermediates.

When it runs
------------

Immediately before :func:`~brightway_flows.pipeline.semantic_typing.assign_semantic_types`,
at both of that function's call sites, and never inside ``resolve_flow_layers``.
Both passes read the contexts off the elementary flows, and the merge does not
put the harmonised context on a created flow until *after* the layering has run
-- so a family pass inside the layering saw no contexts, found no candidates,
and left every one of BAFU's noise flows without a family.  Nothing failed; the
tally simply read zero, which is why what caught it was a test that ran BAFU's
own rows through the merge rather than one that called this module directly.
"""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass

import orjson

from brightway_flows.domain.context import counts_a_non_material_intervention
from brightway_flows.domain.elementary_flow import ElementaryFlow
from brightway_flows.domain.flow_object import FlowObject, stable_flow_object_id
from brightway_flows.flow_layers.labels import _label_entry, _object_pref_label_value
from brightway_flows.filesystem import PACKAGE_DATA_DIR

FAMILIES_FILEPATH = (
    PACKAGE_DATA_DIR / "non-material-interventions.json"
)

#: What ``created_from.resolver`` says on a family object this pass minted, so
#: the object names the pass that made it rather than a source flow it came
#: from.  The same convention as ``MINTED_ELEMENT_RESOLVER``.
MINTED_INTERVENTION_RESOLVER = "non_material_intervention_family_v1"


class NonMaterialFamilyError(ValueError):
    """A ``families`` row is unusable."""


#: What a family has to carry.  ``definition`` is not decoration: it is the
#: whole of what the minted object says about itself, and an object that is not
#: a substance and says nothing else is the failure this file exists to fix.
#: ``comment`` is the reasoning, which is a different thing from the definition
#: -- one is published and one is for whoever re-reads the decision.
_FAMILY_FIELDS = ("id", "label", "definition", "name_pattern", "comment")


@dataclass(frozen=True)
class NonMaterialFamily:
    """One family of interventions that are not substances, and what names it.

    ``pattern`` is ``name_pattern`` compiled, and is what decides membership.
    Compiled once here rather than at every call: the file is read once per
    process and every family is matched against every candidate.
    """

    id: str
    label: str
    definition: str
    name_pattern: str
    comment: str
    pattern: re.Pattern[str]


@functools.cache
def _families() -> tuple[NonMaterialFamily, ...]:
    """The declared families, in file order, with their patterns compiled.

    Compiled here rather than at every call: the file is read once per process
    and every family is matched against every candidate.

    :raises NonMaterialFamilyError: if a family is missing a field, declares an
        unusable pattern, or repeats an id.  These are hand-written decisions
        about what this list publishes; one that cannot say what it is, or why,
        is not a decision anyone can re-check.
    """
    payload = orjson.loads(FAMILIES_FILEPATH.read_bytes())
    rows = payload.get("families")
    if rows is None:
        return ()
    if not isinstance(rows, list):
        raise NonMaterialFamilyError(
            f"{FAMILIES_FILEPATH}: 'families' must be a list"
        )

    families: list[NonMaterialFamily] = []
    by_id: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        missing = [
            field for field in _FAMILY_FIELDS
            if not str(row.get(field) or "").strip()
        ]
        if missing:
            raise NonMaterialFamilyError(
                f"{FAMILIES_FILEPATH}: family {row.get('id')!r} is missing {missing}"
            )
        family_id = str(row["id"]).strip()
        if family_id in by_id:
            # Last-wins would pick one of two curated statements about the same
            # family by file order, which is the arbitration
            # `flow_specific_context_mappings` refuses for the same reason.
            raise NonMaterialFamilyError(
                f"{FAMILIES_FILEPATH}: two families are called {family_id!r}. "
                f"One family, one row."
            )
        try:
            pattern = re.compile(str(row["name_pattern"]), re.IGNORECASE)
        except re.error as exc:
            raise NonMaterialFamilyError(
                f"{FAMILIES_FILEPATH}: family {family_id!r} declares an unusable "
                f"name_pattern {row['name_pattern']!r}: {exc}"
            ) from exc
        by_id.add(family_id)
        families.append(NonMaterialFamily(
            id=family_id,
            label=str(row["label"]).strip(),
            definition=str(row["definition"]).strip(),
            name_pattern=str(row["name_pattern"]),
            comment=str(row["comment"]).strip(),
            pattern=pattern,
        ))
    return tuple(families)


def _family_for(label: str) -> NonMaterialFamily | None:
    """The family *label* names, or None if no family claims it.

    :raises NonMaterialFamilyError: if two families claim it.  First-match-wins
        would let the order two curators happened to write their families in
        decide which one a flow joins, and a flow that two families both
        describe is a question about the families rather than about the flow.
    """
    claimed = [family for family in _families() if family.pattern.search(label)]
    if len(claimed) > 1:
        raise NonMaterialFamilyError(
            f"{label!r} is claimed by more than one non-material intervention "
            f"family: {[family.id for family in claimed]}. One flow, one family."
        )
    return claimed[0] if claimed else None


def _non_material_object_ids(elementary_flows: list[ElementaryFlow]) -> set[str]:
    """The objects whose *every* context counts something other than matter.

    Every, not any: a substance that happens to have one occurrence on
    ``Environmental / Other`` is still a substance, and the semantic typing
    draws the line in the same place for the same reason.
    """
    slots: dict[str, set[tuple[str, str]]] = {}
    for row in elementary_flows:
        object_id = str(getattr(row, "flow_object_id", "") or "").strip()
        if not object_id:
            continue
        context = row.context
        # A merge-created flow whose context IRI resolved to nothing has no
        # context, and contributes no slot rather than an empty one.
        if context is None:
            continue
        slots.setdefault(object_id, set()).add(
            (context.dimension.value, context.media.value if context.media else "")
        )
    return {
        object_id
        for object_id, object_slots in slots.items()
        if object_slots
        and all(counts_a_non_material_intervention(*slot) for slot in object_slots)
    }


def _mint_family_object(family: NonMaterialFamily) -> FlowObject:
    """The flow object standing for one family, which no source list carries."""
    object_id = stable_flow_object_id("fo", f"intervention:{family.id}")
    obj = FlowObject(
        flow_object_id=object_id,
        prefLabel=[
            _label_entry(
                value=family.label,
                language="en",
                resolver_name=MINTED_INTERVENTION_RESOLVER,
                seed_source="",
                was_derived_from=f"non-material-interventions.{family.id}.label",
            )
        ],
        altLabel=[],
        properties={},
        references=[],
        created_from={
            "resolver": MINTED_INTERVENTION_RESOLVER,
            "reason": "non_material_intervention_family_with_more_than_one_member",
            "family": family.id,
        },
    )
    if family.definition:
        obj.skos_definition = [{"@value": family.definition, "@language": "en"}]
    return obj


def attach_non_material_families(
    flow_objects: list[FlowObject],
    elementary_flows: list[ElementaryFlow],
) -> tuple[list[FlowObject], dict[str, int]]:
    """Group the non-material objects into their declared families.

    Returns *flow_objects* with one minted object appended per family that has
    more than one member, and a tally.  ``non_material_unfamilied`` counts the
    candidates no family claimed, which is the number to watch: it is zero
    today, and a run where it is not is a run that met a kind of non-material
    flow this file has never been told about.
    """
    candidates = _non_material_object_ids(elementary_flows)
    members: dict[str, list[FlowObject]] = {}
    unfamilied = 0
    for obj in flow_objects:
        if obj.flow_object_id not in candidates:
            continue
        family = _family_for(_object_pref_label_value(obj) or "")
        if family is None:
            unfamilied += 1
            continue
        members.setdefault(family.id, []).append(obj)

    minted: list[FlowObject] = []
    linked = 0
    for family in _families():
        family_members = members.get(family.id, [])
        if len(family_members) < 2:
            continue
        parent = _mint_family_object(family)
        minted.append(parent)
        for obj in family_members:
            obj.parent_intervention_id = parent.flow_object_id
            linked += 1

    return flow_objects + minted, {
        "non_material_candidates": len(candidates),
        "non_material_families_minted": len(minted),
        "non_material_members_linked": linked,
        "non_material_unfamilied": unfamilied,
    }
