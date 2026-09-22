"""The impact categories of every method, one set of rows per implementation.

There is no correct implementation of an LCIA method.  EF 3.1 as the JRC
published it, as the ecoinvent Centre implemented it and as GreenDelta shipped it
for openLCA are three renderings of one method against three flow lists, and none
is another's mistake; this list publishes all three, transcribed, plus a fourth
that is its own judgement about what these flows should carry.
``implemented_by`` is not a concept threaded through a pipeline -- it is a field
on ``ImpactCategory``, so "four implementations" is literally four sets of
category rows.

Nothing here names a method or an implementation.  Both are read from the method
files (``domain.lcia.crosswalk``), so EF 3.1's four implementations are what is
loaded today rather than what this module knows about:

| ``implemented_by`` | categories | where its numbers come from |
|---|---:|---|
| ``European Commission — JRC`` | 25 | the 25 ILCD method files in ``EF-v3.1.zip`` |
| ``ecoinvent Centre`` | 25 | ``LCIA Implementation 3.12.xlsx``, method ``EF v3.1`` |
| ``GreenDelta`` | 25 | ``bafu-greendelta-lcia.zip``, ``EF 3.1 Method (adapted)`` |
| ``brightway-flows`` | 25 | ours, derived from the deciding two, each factor saying how |

**Three of the four are transcriptions, and only two of those decide anything.**
GreenDelta's is ingested to be compared and not to be weighed: it is published,
it is in the difference report, and it is kept out of the consensus derivation.
Which is which is `decides` on each implementation's row in the method file.

The categories are built here; the factors are not.  Every category this module
returns holds an empty ``characterization_factors`` list, and filling it is the
job of the passes that match a publisher's rows onto consensus flows.

**Identity is the five-segment IRI, and the id is a hash of it.**
``ImpactCategory.id`` is a ``uuid5`` over the category's own IRI, which spells
out the method, the version, the implementation and the timeframe as well as the
category.  Deriving the id from the IRI rather than from a tuple built beside it
means the two identifiers cannot come apart, and it holds for the JRC's 25 as
well: their ILCD method-file UUIDs are real UUIDs and would be the obvious
identity, but three implementations of one category cannot share one, so the
file's UUID is recorded in ``meta`` and the id is minted like every other.  It is
also what makes a second method free: two methods' ``Acidification`` differ in
the first two segments, so neither their IRIs nor their ids can collide.

Both are published, so both are pinned by ``tests/test_impact_categories.py``.
"""

from __future__ import annotations

import uuid
from functools import lru_cache

from brightway_flows.domain.lcia.crosswalk import (
    ImpactCategoryDefinition,
    LCIAMethodDefinition,
    MethodImplementation,
    lcia_methods,
)
from brightway_flows.domain.lcia.crosswalk import (
    lcia_method as method_definition,
)
from brightway_flows.domain.lcia.records import (
    ImpactCategory,
    ImpactTimeframe,
    LCIAMethod,
)
from brightway_flows.domain.vocabulary import MintedNamespace

#: ``LONG`` on all 100, and on every category of every method added later.  The field says which
#: emissions an implementation characterises rather than how far into the future
#: its model runs: ``SHORT`` is ecoinvent's ``no LT`` convention of excluding
#: emissions filed as long-term, and that set states no number the full set does
#: not, so it is asserted against at ingest and not published
#: (``plans/lcia-factors.md`` §2.4).
PUBLISHED_TIMEFRAME = ImpactTimeframe.LONG

_TIMEFRAME_SLUGS: dict[ImpactTimeframe, str] = {
    ImpactTimeframe.UNKNOWN: "unknown",
    ImpactTimeframe.SHORT: "short",
    ImpactTimeframe.LONG: "long",
}


def method_iri(method: LCIAMethodDefinition) -> str:
    """The IRI of the method all its categories belong to."""
    return f"{MintedNamespace.LCIA_METHOD.value}{method.slug}"


def impact_category_iri(
    method: LCIAMethodDefinition,
    definition: ImpactCategoryDefinition,
    implementation: MethodImplementation,
    timeframe: ImpactTimeframe = PUBLISHED_TIMEFRAME,
) -> str:
    """The published IRI of one category under one implementation."""
    return (
        f"{MintedNamespace.LCIA_IMPACT_CATEGORY.value}"
        f"{method.slug}/{method.version}/{implementation.slug}/"
        f"{_TIMEFRAME_SLUGS[timeframe]}/{definition.slug}"
    )


def impact_category_id(iri: str) -> uuid.UUID:
    """The id of the category *iri* names.

    ``uuid5`` in the URL namespace, over the IRI itself, so that the identifier
    a consumer dereferences and the identifier a table joins on are two
    spellings of one thing rather than two facts to keep in step.
    """
    return uuid.uuid5(uuid.NAMESPACE_URL, iri)


@lru_cache(maxsize=None)
def published_method(method_slug: str) -> LCIAMethod:
    """The published method record, once, for every version and implementation.

    The version lives on the category rather than here, so that ecoinvent's
    ``EF v3.0`` -- 28 more categories in the same workbook -- falls under this
    method with ``version: "3.0"`` and needs no second method row.
    """
    definition = method_definition(method_slug)
    iri = method_iri(definition)
    return LCIAMethod(
        id=uuid.uuid5(uuid.NAMESPACE_URL, iri),
        name=definition.name,
        meta={"iri": iri, "label": definition.label},
    )


def _meta(
    method: LCIAMethodDefinition,
    definition: ImpactCategoryDefinition,
    implementation: MethodImplementation,
    iri: str,
) -> dict[str, str]:
    """What is true of this category under this implementation and no other.

    The keys do not name the implementation, because the bag already does: this
    is `meta` on *its* category row, and `jrc_method_uuid` inside the JRC's own
    metadata says the same thing twice while promising a `foo_method_uuid` for
    every implementation added later.  Where two publishers state the same kind
    of thing -- what they call this category -- they state it under the same key,
    which is what makes the two comparable at all.
    """
    meta: dict[str, str] = {"iri": iri}
    if definition.indicator is not None and not _stated_indicator(
        method, definition, implementation
    ):
        # Words the method file wrote rather than read, so the row names whose
        # they are instead of leaving them to read as the publisher's.
        meta["indicator_source"] = definition.indicator.source
    stated = definition.stated_by(implementation.slug)
    if stated is None:
        # The consensus implementation, which has no words of its own: what it
        # publishes is somebody else's number, and each factor says whose.
        return meta
    if stated.identifier:
        # The identity the publisher's own files use, kept because every one of
        # the JRC's 319,575 factor rows names it and a reader holding one needs
        # the join.
        meta["method_uuid"] = stated.identifier
    if implementation.release:
        meta["release"] = implementation.release
    # The method name this publisher files the category under, wherever the
    # publisher states it.  ecoinvent's workbook states one on every category row
    # (`EF v3.1` in its `Method` column) and GreenDelta's package states one for
    # the whole file (`EF 3.1 Method (adapted)`, the word "adapted" theirs), so a
    # row's own comes first and the implementation's is the fallback.
    stated_method = stated.method or implementation.factors.stated_method
    if stated_method:
        meta["stated_method"] = stated_method
    meta["stated_name"] = stated.name
    return meta


def _stated_indicator(
    method: LCIAMethodDefinition,
    definition: ImpactCategoryDefinition,
    implementation: MethodImplementation,
) -> str:
    """What a publisher of the method says the number means, or ``""``.

    An implementation that states none borrows the method publisher's, which is
    the consensus implementation's case: the method *is* the publisher's, and our
    judgement is about which numbers to publish rather than about what the
    indicator is.  GreenDelta's package states no indicator either, and its 25
    categories carry the JRC's for the same reason.
    """
    stated = definition.stated_by(implementation.slug)
    if stated is not None and stated.indicator:
        return stated.indicator
    reference = definition.stated_by(method.reference.slug)
    return reference.indicator if reference is not None else ""


def _indicator(
    method: LCIAMethodDefinition,
    definition: ImpactCategoryDefinition,
    implementation: MethodImplementation,
) -> str | None:
    """What the number means, in the words of whoever states it.

    A publisher's words where there are any.  Where no publisher of the method
    states one -- Stepwise 2006, whose SimaPro export gives a category a name
    and a unit and nothing else -- the method file's, which are the words of the
    model the category was taken from, and which :func:`_meta` attributes.
    ``None`` where there are neither: an empty string reads as a publisher who
    stated an indicator and left it blank.
    """
    stated = _stated_indicator(method, definition, implementation)
    if stated:
        return stated
    if definition.indicator is not None:
        return definition.indicator.words
    return None


def _category(
    method: LCIAMethodDefinition,
    definition: ImpactCategoryDefinition,
    implementation: MethodImplementation,
    record: LCIAMethod,
) -> ImpactCategory:
    iri = impact_category_iri(method, definition, implementation)
    return ImpactCategory(
        id=impact_category_id(iri),
        method=record,
        name=definition.name,
        version=method.version,
        area_of_protection=definition.area_of_protection,
        implemented_by=implementation.name,
        unit_iri=definition.unit_iri,
        description=definition.description,
        characterization_factors=[],
        indicator=_indicator(method, definition, implementation),
        category_group=definition.category_group,
        # Stated on every row rather than left to the record's default, which is
        # `ENDPOINT`: all 25 EF categories are midpoint, and a default that
        # happens to be wrong for every row is not a default anybody checked.
        midpoint_endpoint=definition.midpoint_endpoint,
        timeframe=PUBLISHED_TIMEFRAME,
        meta=_meta(method, definition, implementation, iri),
    )


@lru_cache(maxsize=None)
def impact_categories_for(
    method_slug: str, implementation_slug: str
) -> tuple[ImpactCategory, ...]:
    """One method's categories under one implementation, in file order."""
    method = method_definition(method_slug)
    implementation = method.implementation(implementation_slug)
    record = published_method(method_slug)
    return tuple(
        _category(method, definition, implementation, record)
        for definition in method.categories
    )


def consensus_categories_for(method_slug: str) -> tuple[ImpactCategory, ...]:
    """The categories this list publishes under its own name for one method."""
    return impact_categories_for(
        method_slug, method_definition(method_slug).consensus.slug
    )


@lru_cache(maxsize=None)
def published_impact_categories() -> tuple[ImpactCategory, ...]:
    """Every category of every implementation of every method.

    75 today: EF 3.1's 25, three times over.
    """
    return tuple(
        category
        for method in lcia_methods()
        for implementation in method.implementations
        for category in impact_categories_for(method.slug, implementation.slug)
    )
