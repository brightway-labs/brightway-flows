"""Where one implementation's factors are read from.

Three routes, and which one an implementation takes is stated in its method file
(``domain.lcia.crosswalk``) rather than known here.  Nothing in this module names
a method, an implementation or a publisher.

**``published-flows``.**  The implementation's own list is the base list, so
``extract`` parsed its method files and the transform carried every factor onto
the flow it characterises; a consensus flow of the base list *is* one of its
flows, under the same UUID.  There is no matching to do -- reading
``elementary_flows.flow_json`` is reading that implementation against consensus
flows -- and where this list holds one flow where the source held two,
``pipeline.deduplication`` already decided which factor survives and recorded the
other under ``superseded_values`` (#283).  EF 3.1's JRC implementation takes this
route.

**``source-list``.**  The factors arrive as a file naming somebody's own flows.
``fetch-lcia`` resolved them to a source flow UUID -- the first of §2.3's two
hops -- and the second hop, that UUID to a consensus flow, is
``elementary_flow_sources`` and belongs to
:mod:`brightway_flows.lcia.matching`.  ecoinvent's workbook names ecoinvent's
own flows; GreenDelta's openLCA package ships no flow list at all and names the
ecoinvent UUID it was built against, so it walks the manifest's
``resolve_through`` through whichever release has that UUID.  Which lists to
walk is the manifest's; which list to read is the method file's.

**``derived``.**  Ours.  It has no source at all: §4.3 derives it from the
implementations the method file says decide, so there is nothing here to read and
this module is never asked.

**Two files have to agree, and this is where they are held to it.**  A method
file's implementation names the list its factors come from; that list's manifest
names the publisher whose file format it ships and the methods it ingests.  A
list declaring an ``lcia`` block that no method reads, or a method naming a
method name the manifest does not ingest, is caught here rather than publishing
an implementation with nothing in it.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import orjson
import structlog

from brightway_flows.domain.lcia.crosswalk import (
    FactorRoute,
    MethodImplementation,
)
from brightway_flows.domain.lcia.records import StatedFactor, stated_factors
from brightway_flows.domain.vocabulary import CHEMINF_CAS_REGISTRY_NUMBER
from brightway_flows.integrations.ecoinvent_lcia import load_factors
from brightway_flows.lcia.census import SubstanceRelative
from brightway_flows.sources import (
    SourceList,
    base_source_list,
    known_source_lists,
)

logger = structlog.get_logger(__name__)

@dataclass(frozen=True, slots=True)
class FactorSource:
    """One implementation's factors, and what the flows they name are.

    ``flows_are_consensus`` is the whole difference between the two routes that
    read anything: factors read off the published flows already name a consensus
    flow, and factors read from a source list name somebody else's, which has to
    be resolved.  A boolean rather than two classes, because everything else
    about them is the same -- a category, a flow, an amount.
    """

    implementation: MethodImplementation
    #: Factors by the flow uuid they name.
    by_flow: dict[str, list[StatedFactor]]
    flows_are_consensus: bool
    #: Where they were read from, for the run's own record.
    read_from: str
    #: What the publisher calls each flow it states a factor for -- name,
    #: compartment, unit.  Only the source flows are described, and only for an
    #: implementation whose flows are its own: a factor that reaches no consensus
    #: flow is reported by uuid otherwise, and `a57cb19d-…` is not a substance
    #: anybody can act on.  Empty where the flows already *are* consensus flows,
    #: which the database describes.
    descriptions: dict[str, dict[str, str]] = field(default_factory=dict)

    @property
    def factor_count(self) -> int:
        return sum(len(factors) for factors in self.by_flow.values())


def published_factors(
    db_path: Path, implementation: MethodImplementation
) -> FactorSource:
    """The factors the build published onto consensus flows, as one
    implementation's.

    The ``published-flows`` route: this implementation's own list is the base
    list, so ``extract`` wrote its factors into the flow record and reading them
    back is reading the implementation against consensus flows.

    Every flow, including the deprecated ones: a factor on a flow this list has
    withdrawn is still what the publisher said about it, and dropping it here
    would make the count disagree with `lcia_factor_count` on the same row.
    Which flows are active is a question the tables answer by joining, not one
    this loses the ability to ask.
    """
    by_flow: dict[str, list[StatedFactor]] = {}
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = connection.execute("SELECT uuid, flow_json FROM elementary_flows")
        for uuid, payload in rows:
            entries = orjson.loads(payload).get("lcia_methods") or []
            if not entries:
                continue
            by_flow[str(uuid)] = list(stated_factors(entries))
    finally:
        connection.close()
    source = FactorSource(
        implementation=implementation,
        by_flow=by_flow,
        flows_are_consensus=True,
        read_from=f"{db_path.name}:elementary_flows.flow_json",
    )
    logger.info(
        "read_published_factors",
        implementation=implementation.slug,
        flows=len(by_flow),
        factors=source.factor_count,
    )
    return source


def flow_descriptions(db_path: Path) -> dict[str, dict[str, str]]:
    """What a reader needs to recognise a consensus flow: substance, name, place.

    Read once and handed to whatever renders a question about a flow, because a
    queue row that says only `8354bde6-…` is a row nobody can rule on.
    """
    flows: dict[str, dict[str, str]] = {}
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT ef.uuid, ef.flow_object_id, ef.pref_label_value, "
            "ef.context_display, ef.context_iri, ef.unit, ef.is_deprecated, "
            "ef.context_dimension, ef.context_media "
            "FROM elementary_flows ef"
        )
        for (
            uuid,
            object_id,
            label,
            context,
            context_iri,
            unit,
            deprecated,
            dimension,
            media,
        ) in rows:
            flows[str(uuid)] = {
                "flow_object_id": str(object_id or ""),
                "deprecated": bool(deprecated),
                "label": str(label or ""),
                "context_display": str(context or ""),
                "context_iri": str(context_iri or ""),
                "unit": str(unit or ""),
                # What kind of place the flow is in, as fields rather than as a
                # substring of the display name: `lcia.context_carry` asks
                # whether a flow is an emission to air, and a renamed context
                # must not silently change the answer.
                "context_dimension": str(dimension or ""),
                "context_media": str(media or ""),
            }
    finally:
        connection.close()
    return flows


def substances_by_registry_number(db_path: Path) -> dict[str, list[str]]:
    """Which flow objects carry each CAS registry number.

    The join a statement about somebody else's data arrives on.  USEtox 2.1 and
    EF 3.1 share no identifier for a substance except this one, so a file
    comparing them is keyed on it (`lcia.contradictions`), and this is where a
    registry number becomes a substance of this list.

    A list per number rather than one, because two flow objects sharing a CAS is a
    real state of this build and a question of its own (`contested-cas`): reading
    it as a mapping would silently drop one of them.
    """
    numbers: dict[str, list[str]] = defaultdict(list)
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT flow_object_id, classifications_json FROM flow_objects"
        )
        for flow_object_id, payload in rows:
            classifications = orjson.loads(payload or "{}")
            entry = classifications.get(CHEMINF_CAS_REGISTRY_NUMBER) or {}
            for value in entry.get("@value") or ():
                numbers[str(value)].append(str(flow_object_id))
    finally:
        connection.close()
    return dict(numbers)


#: The relationship the element enrichment writes on an ion's flow object
#: (`flow_layers.ions`), and the words the census prints for it.
_ION_OF = "ion_of"
_ION_OF_IN_WORDS = "ion of"


def substance_relatives(db_path: Path) -> dict[str, SubstanceRelative]:
    """Which substances the build records as an ion of an element, and of which.

    Read off ``properties.relationships`` of every flow object, which is where
    `flow_layers.ions` wrote it: `Zinc(2+)` names zinc as its parent element
    with ``relationship_type: ion_of``.  Ions only, today.  Isotopes point at
    their element by the same field and are not here: a nuclide's factor is a
    fact about the nuclide, and no LCIA method gives an isotope its element's
    number.

    The census (`lcia.census.identity_census`) asks one thing of this: is the
    element characterised where the ion is not?
    """
    relatives: dict[str, SubstanceRelative] = {}
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = connection.execute("SELECT flow_object_id, properties_json FROM flow_objects")
        for flow_object_id, payload in rows:
            properties = orjson.loads(payload or "{}")
            relationship = properties.get("relationships") or {}
            if relationship.get("relationship_type") != _ION_OF:
                continue
            donor = str(relationship.get("parent_element_flow_object_id") or "")
            if donor and donor != str(flow_object_id):
                relatives[str(flow_object_id)] = SubstanceRelative(
                    donor=donor, relationship=_ION_OF_IN_WORDS
                )
    finally:
        connection.close()
    return relatives


def flows_reached_by(db_path: Path, *, list_name: str, list_version: str) -> set[str]:
    """The consensus flows one source list has a reference on.

    A set, not a mapping, and that is the whole difference from
    `matching.merge_targets`: placing a factor needs to know *which* flow a source
    row became, and holds an invariant about there being one, but the coverage
    question only asks whether an implementation's own list reaches a flow at all.

    The invariant does not hold here anyway. 30 of EF 3.1's 93,993 referenced
    flows reach two consensus flows, because a deprecated flow's reference is
    carried onto the survivor that replaced it while the original row keeps its
    own -- which is right, and is not something a factor has to choose between.
    """
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return {
            str(uuid)
            for (uuid,) in connection.execute(
                "SELECT DISTINCT elementary_flow_uuid FROM elementary_flow_sources "
                "WHERE list_name = ? AND list_version = ?",
                (list_name, list_version),
            )
        }
    finally:
        connection.close()


def registered_lists() -> dict[str, SourceList]:
    """Every registered list, base included.

    `known_source_lists` leaves the base list out, which is right for a merge and
    wrong here: the implementation whose factors are already on the published
    flows is exactly the one whose list is the base.
    """
    base = base_source_list()
    return {**known_source_lists(), base.key: base}


def source_list_for(implementation: MethodImplementation) -> SourceList:
    """The registered list an implementation reads its factors from.

    :raises ValueError: if the list is not registered, if it declares no ``lcia``
        block where the route needs one, if its manifest does not ingest the
        method the implementation names, or if it says it ships somebody else's
        file.  All four are the method file and a source manifest disagreeing,
        and a run that read nothing because of it would publish an
        implementation with no numbers in it and say nothing.
    """
    key = implementation.factors.source_list
    registry = registered_lists()
    try:
        source = registry[key]
    except KeyError:
        known = ", ".join(sorted(registry))
        raise ValueError(
            f"No source list {key!r} is registered, so there is nowhere to read "
            f"{implementation.name}'s implementation from; {known} are."
        ) from None
    if implementation.factors.route is not FactorRoute.SOURCE_LIST:
        # The `published-flows` route names its list so the coverage question can
        # be asked -- which consensus flows that list reaches -- and that is a
        # fact about the merge rather than about an `lcia` block, which such a
        # list does not have and does not need.
        return source
    if source.lcia is None:
        raise ValueError(
            f"{key} declares no lcia block, and {implementation.name} reads its "
            f"factors from it."
        )
    if source.lcia.implemented_by != implementation.name:
        raise ValueError(
            f"{key} says it ships {source.lcia.implemented_by!r}'s factors and "
            f"the method file reads it for {implementation.name!r}. One of the "
            f"two names the wrong publisher."
        )
    stated = implementation.factors.stated_method
    if stated and stated not in {method.name for method in source.lcia.methods}:
        ingested = ", ".join(sorted(method.name for method in source.lcia.methods))
        raise ValueError(
            f"{implementation.name} reads the method {stated!r} from {key}, "
            f"which ingests {ingested}."
        )
    return source


def factors_for(
    implementation: MethodImplementation,
    *,
    db_path: Path,
    source: SourceList | None = None,
) -> FactorSource:
    """One implementation's factors, by whichever route its method file names.

    *source* is the registered list by default, and is a parameter so a test can
    hand over a manifest of its own rather than the data directory's.

    :raises ValueError: if asked for an implementation this list derives.  The
        consensus implementation has no source, and a caller that asked for one
        is a caller that would publish a transcription's numbers under our name.
    """
    route = implementation.factors.route
    if route is FactorRoute.PUBLISHED_FLOWS:
        return published_factors(db_path, implementation)
    if route is FactorRoute.SOURCE_LIST:
        return source_list_factors(
            implementation, source or source_list_for(implementation)
        )
    raise ValueError(
        f"{implementation.name} derives its factors from the implementations "
        f"that decide; there is no source to read."
    )


def source_flow_descriptions(source: SourceList) -> dict[str, dict[str, str]]:
    """What a source list calls each of its own flows.

    Read from the list's own extracted flows -- the same file the merge reads --
    so a finding about a row that reached no consensus flow can name it. Missing
    file is an empty mapping and not an error: a `characterise` run must not stop
    because the thing that makes a *finding* readable is not there.
    """
    path = source.flows_path
    if not path.exists():  # pragma: no cover - the merge would have failed first
        logger.warning("no_source_flows_to_describe", path=str(path))
        return {}
    described: dict[str, dict[str, str]] = {}
    for flow in orjson.loads(path.read_bytes()):
        context = flow.get("context")
        described[str(flow.get("uuid") or flow.get("identifier") or "")] = {
            "name": str(flow.get("name") or ""),
            "context": (
                " / ".join(str(part) for part in context)
                if isinstance(context, list)
                else str(context or "")
            ),
            "unit": str(flow.get("unit") or ""),
        }
    return described


def lcia_source_lists() -> tuple[SourceList, ...]:
    """Every registered list whose manifest declares an implementation.

    What makes a third transcription a manifest rather than a branch: `characterise`
    reads this instead of naming ecoinvent, so a list that declares an `lcia`
    block is ingested by existing in ``data/sources/``.

    In key order, so a run's statistics and its findings come out in the same
    order twice running.
    """
    return tuple(
        source
        for _key, source in sorted(known_source_lists().items())
        if source.lcia is not None
    )


def greendelta_factors(
    implementation: MethodImplementation, source: SourceList
) -> FactorSource:
    """EF 3.1 as GreenDelta ships it, as ``fetch-lcia`` wrote it.

    Keyed by the flow UUID their package states, which is somebody else's:
    `matching.chained_merge_targets` walks the manifest's `resolve_through` to
    find whose.

    :raises FileNotFoundError: if nothing has fetched them, naming the command
        that does.
    """
    from brightway_flows.integrations.greendelta_lcia import (
        flow_descriptions as greendelta_flow_descriptions,
        load_factors as load_greendelta_factors,
    )

    assert source.lcia is not None
    path = source.lcia.factors_path
    if not path.exists():
        raise FileNotFoundError(
            f"{implementation.name}'s implementation is not at {path}. Run "
            f"`brightway-flows fetch-lcia {source.key}` first."
        )
    method = implementation.factors.stated_method or source.lcia.methods[0].name
    by_method = load_greendelta_factors(path)
    by_flow: dict[str, list[StatedFactor]] = defaultdict(list)
    for factor in by_method.get(method, ()):
        by_flow[factor.flow_uuid].append(factor)
    result = FactorSource(
        implementation=implementation,
        by_flow=dict(by_flow),
        flows_are_consensus=False,
        read_from=path.name,
        descriptions=greendelta_flow_descriptions(path),
    )
    logger.info(
        "read_greendelta_factors",
        implementation=implementation.slug,
        method=method,
        flows=len(result.by_flow),
        factors=result.factor_count,
    )
    return result


def ecoinvent_factors(
    implementation: MethodImplementation, source: SourceList
) -> FactorSource:
    """The ecoinvent Centre's factors, as ``fetch-lcia`` wrote them.

    Keyed by ecoinvent flow UUID, which is what the file states and what
    `elementary_flow_sources` joins on.

    :raises FileNotFoundError: if nothing has fetched them, naming the command
        that does. A `characterise` run that quietly published one implementation
        because another's file was missing would be worse than one that stops.
    """
    assert source.lcia is not None
    path = source.lcia.factors_path
    if not path.exists():
        raise FileNotFoundError(
            f"{implementation.name}'s implementation is not at {path}. Run "
            f"`brightway-flows fetch-lcia {source.key}` first."
        )
    method = implementation.factors.stated_method or source.lcia.methods[0].name
    by_method = load_factors(path)
    by_flow: dict[str, list[StatedFactor]] = defaultdict(list)
    for factor in by_method.get(method, ()):
        by_flow[factor.flow_uuid].append(factor)
    result = FactorSource(
        implementation=implementation,
        by_flow=dict(by_flow),
        flows_are_consensus=False,
        read_from=path.name,
        descriptions=source_flow_descriptions(source),
    )
    logger.info(
        "read_ecoinvent_factors",
        implementation=implementation.slug,
        method=method,
        flows=len(result.by_flow),
        factors=result.factor_count,
    )
    return result


def stepwise_factors(
    implementation: MethodImplementation, source: SourceList
) -> FactorSource:
    """2.-0 LCA consultants' factors, as ``fetch-lcia`` wrote them.

    Keyed by the flow uuid ``integrations.stepwise`` mints, which is what the
    file states and what `elementary_flow_sources` joins on -- the same
    arrangement as ecoinvent's, and unlike GreenDelta's, whose package names
    somebody else's identifiers and needs a ``resolve_through`` chain.

    :raises FileNotFoundError: if nothing has fetched them, naming the command
        that does.
    """
    from brightway_flows.integrations.stepwise_lcia import (
        load_factors as load_stepwise_factors,
    )

    assert source.lcia is not None
    path = source.lcia.factors_path
    if not path.exists():
        raise FileNotFoundError(
            f"{implementation.name}'s implementation is not at {path}. Run "
            f"`brightway-flows fetch-lcia {source.key}` first."
        )
    method = implementation.factors.stated_method or source.lcia.methods[0].name
    by_method = load_stepwise_factors(path)
    by_flow: dict[str, list[StatedFactor]] = defaultdict(list)
    for factor in by_method.get(method, ()):
        by_flow[factor.flow_uuid].append(factor)
    result = FactorSource(
        implementation=implementation,
        by_flow=dict(by_flow),
        flows_are_consensus=False,
        read_from=path.name,
        descriptions=source_flow_descriptions(source),
    )
    logger.info(
        "read_stepwise_factors",
        implementation=implementation.slug,
        method=method,
        flows=len(result.by_flow),
        factors=result.factor_count,
    )
    return result


#: How each implementation's factors are read, by who states them.  The method
#: file says *that* an implementation reads a list and *which* list; this says
#: which reader turns that list's file into records, because three publishers
#: ship three file formats and none is a general case of another.
_READERS: dict[str, Any] = {
    "ecoinvent Centre": ecoinvent_factors,
    "GreenDelta": greendelta_factors,
    "2.-0 LCA consultants": stepwise_factors,
}


def source_list_factors(
    implementation: MethodImplementation, source: SourceList
) -> FactorSource:
    """One registered list's implementation, whichever it is.

    :raises ValueError: if nothing here knows the file format the publisher ships.
        An implementation reading a list and being skipped would publish 24
        categories of 25 with nothing saying so.
    """
    reader = _READERS.get(implementation.name)
    if reader is None:
        known = ", ".join(sorted(_READERS))
        raise ValueError(
            f"{implementation.name} reads its factors from {source.key}, and no "
            f"reader in `lcia.sources` knows that publisher's file format; "
            f"{known} are known."
        )
    return reader(implementation, source)
