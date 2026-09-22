"""The LCIA methods this list publishes, and what each implementation calls each
category.

One file per method, and nothing in this module knows which method it is reading.
``data/lcia-impact-categories.json`` holds EF 3.1; a second method is a second
file of the same shape named in :data:`METHOD_FILEPATHS`, and no other module
changes.  That is the whole point of the file layout: two methods are not two
renderings of one thing.  EF 3.1's ``Acidification`` is counted in mol H+-eq from
the Accumulated Exceedance model and Stepwise 2006's is counted in ``m2 UES``
from another; a file that put them in one table would be inviting the mistake the
crosswalk exists to stop.

**Within one method, several publishers render it and no spelling is derivable
from another.**  The JRC's files say ``Ecotoxicity, freshwater``,
``EF-particulate Matter`` and ``Resource use, fossils``; ecoinvent's workbook says
``ecotoxicity: freshwater``, ``particulate matter formation`` and ``energy
resources: non-renewable``; GreenDelta's openLCA package says ``Ecotoxicity
freshwater``, ``Particulate matter`` and ``Resource use fossils``.  No case fold,
no punctuation rule and no synonym list gets from one to another, so each
category row states what every implementation calls it, under that
implementation's slug.

A publisher that kept somebody else's identifiers says so on its implementation
rather than in a check written for it: GreenDelta transcribed the ILCD files and
kept their UUIDs, so ``identifiers_from: "jrc"`` is on their row and
:func:`_check` holds every category to it.  A release that mints its own stops
the run instead of filing its factors under nothing.

Registered as a **vocabulary** rather than a ruling: nobody is overruling the
pipeline here.  This is what the words mean, in the same sense that
``units.json`` says what a kilogram is (rule 12).

Three fields of a category row are ours rather than any publisher's, because the
record the categories become needs them and no publisher's file states them:

* ``area_of_protection`` -- what the category is protecting.  EF's own
  ``impactCategory`` field is close but not it: it gives ``Cancer human health
  effects``, ``Aquatic eco-toxicity``, ``Abiotic resource depletion``, and for
  ``Water use`` it gives the string ``other``.  Each of EF's 25 carries a comment
  where the mapping is a judgement rather than a lookup, and water use carries an
  argument.
* ``midpoint_endpoint`` -- ``Midpoint`` on all 25 of EF's.  Stated on every row
  rather than left to the record's default, which is ``ENDPOINT``.
* ``unit_iri`` -- the reference unit as an IRI in ``units.json``.  Publishers
  write the unit as text, in two spellings (``CTUe`` and ``CTUe``, but ``mol H+
  equivalents`` against ``mol H+-Eq``), and neither is an identifier.

A fourth is ours only where a method's publishers are silent:

* ``indicator`` -- what the number means, with the ``source`` whose words those
  are.  Stepwise 2006's export gives a category a name and a unit and nothing
  else, so each of its categories carries the words of the model it was taken
  from -- EDIP 2003's ``area of unprotected ecosystem`` for acidification -- or
  of the method's own documentation.  Refused beside a publisher's indicator,
  which is the one published.

``parts`` says which categories an aggregate sums.  Four of EF's 25 are
aggregates: ``Climate change`` over its fossil, biogenic and land-use parts, and
the three toxicity families over their organic and inorganic halves.  Measured
against the build of 2026-08-16, over 137,621 flows where an aggregate and at
least one of its parts are both stated, the aggregate equals the sum of the parts
present **exactly** -- every time, to the last bit.  The difference report needs
this: without it, an aggregate and its two parts read as three unrelated
disagreements when one number moves.

**An implementation has a role, and the role is what the pipeline branches on.**
Never a name and never a slug (rule 10 by another route): ``reference`` is the
method's own publisher, whose silence about a flow makes adopting somebody else's
number a decision; ``transcription`` is somebody else's rendering of the same
method; ``consensus`` is ours, derived from the rest and labelled as such in every
artifact.  Exactly one of each of ``reference`` and ``consensus`` per method,
checked where the file is read.

**Being published and being evidence are two things, and ``decides`` is the
second.**  Every implementation in the file is transcribed, published and
compared.  Only the ones that decide are handed to the derivation: a number of
theirs can become one of ours or reach a curator's queue, and a number of
anybody else's cannot.  GreenDelta's is ingested to be *compared* -- their
package is a hand transcription nobody can re-run -- so their row says
``decides: false`` and the consensus implementation is derived from the JRC's and
ecoinvent's alone.  The reference always decides and ours never does, both
checked where the file is read.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any
from enum import StrEnum

import orjson

from brightway_flows.domain.lcia.records import (
    AreaOfProtection,
    MidpointEndpoint,
)
from brightway_flows.domain.units import known_unit_iris
from brightway_flows.filesystem import PACKAGE_DATA_DIR

#: EF 3.1: its 25 categories, and what each of its three implementations calls
#: each one.  Hand-maintained: every row pairs names two organisations chose
#: independently, plus three judgements of ours.
IMPACT_CATEGORIES_FILEPATH = PACKAGE_DATA_DIR / "lcia-impact-categories.json"

#: Stepwise 2006: its 19 categories, and the one publisher that states them.  A
#: method with a single implementation, so the ``stated`` block pairs nothing --
#: it is there because the crosswalk checks a category against what the export
#: says, and a release that renamed one or recounted it in another unit should
#: fail rather than file its factors under a row that stopped describing them.
STEPWISE_IMPACT_CATEGORIES_FILEPATH = (
    PACKAGE_DATA_DIR / "stepwise-2006-impact-categories.json"
)

#: Every method file, in the order the methods are published.  A method is added
#: here and nowhere else.
METHOD_FILEPATHS: tuple[Path, ...] = (
    IMPACT_CATEGORIES_FILEPATH,
    STEPWISE_IMPACT_CATEGORIES_FILEPATH,
)

#: What this list calls its own implementation of every method it publishes, and
#: the IRI segment that spells it.  One name across methods, because it is the
#: same publisher saying it -- the method is named by the rest of the IRI.
CONSENSUS_IMPLEMENTATION = "brightway-flows"
CONSENSUS_IMPLEMENTATION_SLUG = "brightway-flows"

#: The method slug EF 3.1 is published under, for the handful of readers that are
#: genuinely about EF and not about "whatever method this is": the workbook check
#: that ecoinvent's ``EF v3.1`` names the categories the crosswalk pairs, and the
#: USEtox comparison, which is about the model EF's toxicity categories are
#: derived from.
EF_METHOD_SLUG = "ef"


class ImplementationRole(StrEnum):
    """What an implementation is, to the method it implements."""

    #: The method's own publisher.  One per method.
    REFERENCE = "reference"
    #: Somebody else's rendering of the same method, against their own flow list.
    TRANSCRIPTION = "transcription"
    #: Ours, derived from the others and never overwriting either.  One per
    #: method.
    CONSENSUS = "consensus"


class FactorRoute(StrEnum):
    """How an implementation's numbers reach a consensus flow."""

    #: Already on them.  Its list is the base list, so a consensus flow *is* one
    #: of its flows under the same UUID and there is no matching to do; the
    #: factors are read off ``elementary_flows.flow_json``.
    PUBLISHED_FLOWS = "published-flows"
    #: In the file its source list's ``lcia`` adapter fetched, naming that list's
    #: own flows, which the merge has to resolve to consensus flows.
    SOURCE_LIST = "source-list"
    #: Nowhere.  Ours, derived from the implementations above.
    DERIVED = "derived"


@dataclass(frozen=True, slots=True)
class FactorSpec:
    """Where one implementation's factors are read from.

    Stated in the method file rather than in code, because it is the last thing
    that was method-specific: with it here, a second method is a second file and
    no module changes.
    """

    route: FactorRoute
    #: The registered source list, where the route needs one.
    source_list: str = ""
    #: What that list's own file calls the method: ecoinvent's ``EF v3.1``, in
    #: the workbook's ``Method`` column.  Checked against the list's manifest, so
    #: a method renamed in one file and not the other fails rather than reading
    #: nothing.
    stated_method: str = ""


@dataclass(frozen=True, slots=True)
class MethodImplementation:
    """Who rendered a method, and what that makes them.

    ``name`` is ``implemented_by`` verbatim -- the string every published category
    row, difference row and finding carries -- and ``slug`` is the IRI segment.
    Both are stated in the file rather than derived from one another, because both
    are published: a rename of the display name must not move an identifier.
    """

    slug: str
    name: str
    role: ImplementationRole
    #: Whether a number of theirs may become a number of ours.  Every
    #: implementation is published and compared; only a deciding one is evidence
    #: (`lcia.consensus.derive`).
    decides: bool
    #: Where its numbers are read from.
    factors: FactorSpec
    #: Where its numbers come from, in the words a reader of the section wants.
    source: str = ""
    #: The release of the implementer's own product the transcription was read
    #: from, where that is a fact about the artifact rather than about the
    #: method: ecoinvent 3.12 is *where* EF 3.1 was read, not what EF 3.1 is a
    #: version of.  Published in ``ImpactCategory.meta``.
    release: str = ""
    #: The implementation whose category identifiers this one kept, where it
    #: kept somebody's.  GreenDelta transcribed the JRC's ILCD files and left
    #: their UUIDs in place, so every one of their categories carries the JRC's
    #: and :func:`_check` says so out loud -- a package that mints its own is a
    #: join that has to be written before the row can change.
    identifiers_from: str = ""

    @property
    def ours(self) -> bool:
        return self.role is ImplementationRole.CONSENSUS


@dataclass(frozen=True, slots=True)
class StatedCategoryName:
    """What one implementation calls one category, and how its rows name it.

    One record for every publisher, because they state the same kinds of thing:
    the JRC's ILCD method-file UUID and ecoinvent's ``Method`` column are both
    "the identity this publisher's factor rows carry", and giving each publisher a
    record of its own promised a third class for every implementation added later.
    """

    #: The implementation's slug, so a row carries the answer to "whose words are
    #: these" without the caller having to remember where it came from.
    implementation: str
    #: The publisher's own name for the category: ``Ecotoxicity, freshwater``.
    name: str
    #: What the publisher says the number means.
    indicator: str = ""
    #: The reference unit as the publisher writes it.
    unit: str = ""
    #: The identifier the publisher's own factor rows carry, where it has one:
    #: the ILCD dataset UUID of the method file, for the JRC.
    identifier: str = ""
    #: The method name the publisher files the category under, where it has one:
    #: ``EF v3.1``, in ecoinvent's ``Method`` column.
    method: str = ""


@dataclass(frozen=True, slots=True)
class CategoryIndicator:
    """What a category's number means, where no publisher of the method says.

    Written into the file rather than read from a publisher's, and invented by
    nobody: the words are those of whoever defined the quantity the category is
    counted in, and ``source`` says who.  Stepwise 2006 is the case.  Its
    publisher ships it as a SimaPro export, where a category is ``name;unit``
    and nothing else, and takes most of its categories from EDIP 2003 and
    IMPACT 2002+, whose own documentation names each indicator; the method's
    own documentation names the rest.
    """

    #: The indicator as published: ``Area of unprotected ecosystem (UES)``.
    words: str
    #: Whose words they are and where they are written.  Never empty: words
    #: nobody is named as having written read as the publisher's.
    source: str


@dataclass(frozen=True, slots=True)
class ImpactCategoryDefinition:
    """One impact category, in every publisher's words and in ours."""

    #: The slug of the method this category belongs to.  A category is not
    #: identified by its own slug: EF 3.1 has an ``acidification`` counted in
    #: mol H+-eq from Accumulated Exceedance and Stepwise 2006 has one counted
    #: in ``m2 UES`` from EDIP, and anything holding categories of two methods
    #: in one mapping has to key on both or silently keep whichever it read
    #: last (#349).
    method: str
    #: The stable local name in the minted IRI.  Never regenerated from
    #: ``name``: it is published, so a rename of the display name must not move
    #: an identifier.
    slug: str
    #: Ours, and the method publisher's: where two implementations disagree on a
    #: name, the canonical one is the method's own publisher's.
    name: str
    description: str
    area_of_protection: AreaOfProtection
    midpoint_endpoint: MidpointEndpoint
    #: The family a category belongs to, where it is in one -- the value an
    #: aggregate and its parts share.
    category_group: str | None
    unit_iri: str
    #: The categories this one sums, by name.  Empty unless it is an aggregate.
    parts: tuple[str, ...]
    #: What each implementation calls it, by implementation slug.  An
    #: implementation with no entry states nothing about this category, which is
    #: the ordinary state of the consensus implementation: it has no words of its
    #: own, only the numbers it took from the others.
    stated: dict[str, StatedCategoryName]
    #: Why the area of protection is what it is, where that needed an argument.
    comment: str = ""
    #: What an implementation called this category under earlier versions of the
    #: method, by implementation slug, where a release still ships one.
    #: ecoinvent 3.8 carries ``EF v3.0``, and a score computed with it names
    #: ``photochemical ozone formation: human health`` where 3.1 says
    #: ``oxidant``.  Read by the unit-process score comparison, which scores a
    #: release with the method it ships, and by nothing that publishes a factor:
    #: the factors this list publishes are the ingested method's, and these
    #: spellings say only which of our categories an earlier score is *about*.
    #: Three EF 3.0 categories -- the ``metals`` halves of the toxicity families,
    #: folded into ``inorganics`` in 3.1 -- have no row, and the comparison
    #: reports them as such.
    earlier: dict[str, tuple[StatedCategoryName, ...]] = field(default_factory=dict)
    #: What the number means where no publisher of the method states it, and
    #: whose words those are.  ``None`` wherever the method's own publisher
    #: states one, which is checked: a row carrying both would publish the
    #: publisher's and never read ours.
    indicator: CategoryIndicator | None = None

    def stated_by(self, implementation: str) -> StatedCategoryName | None:
        """What *implementation* calls this category, or ``None``."""
        return self.stated.get(implementation)


@dataclass(frozen=True, slots=True)
class LCIAMethodDefinition:
    """One LCIA method, its implementations and its categories.

    Everything a method needs to be published is here, and nothing outside it is
    about this method in particular.  Two methods share no category list, no
    reference unit and no implementation set, so nothing joins them.
    """

    #: The IRI segment, and the prefix every one of this method's run statistics
    #: carries.  Two methods' ``brightway-flows`` rows are two different
    #: things, and a statistic that did not say which would be one of them
    #: silently overwriting the other.
    slug: str
    #: What the method is called: ``EF``.
    name: str
    #: What version of it this file states: ``3.1``.
    version: str
    #: The method's full name, for a reader: ``Environmental Footprint``.
    label: str
    description: str
    implementations: tuple[MethodImplementation, ...]
    categories: tuple[ImpactCategoryDefinition, ...]
    #: Where the file was read from, for an error message that can be acted on.
    read_from: str = ""

    def implementation(self, slug: str) -> MethodImplementation:
        """The implementation with this slug.

        :raises KeyError: if the method has none, which is a caller asking about
            an implementation of a different method.
        """
        for implementation in self.implementations:
            if implementation.slug == slug:
                return implementation
        raise KeyError(f"{self.label} has no implementation {slug!r}.")

    def implementation_named(self, name: str) -> MethodImplementation | None:
        """The implementation published under this ``implemented_by``, if any."""
        for implementation in self.implementations:
            if implementation.name == name:
                return implementation
        return None

    @property
    def reference(self) -> MethodImplementation:
        """The method's own publisher.  Exactly one, checked at load."""
        return self._of_role(ImplementationRole.REFERENCE)

    @property
    def consensus(self) -> MethodImplementation:
        """Ours.  Exactly one, checked at load."""
        return self._of_role(ImplementationRole.CONSENSUS)

    @property
    def deciding(self) -> tuple[MethodImplementation, ...]:
        """The implementations the consensus one is derived from.

        Not every published implementation, and not a set anything infers: a
        transcription ingested to be compared is published in full and is never
        evidence, which is `decides` on its own row.  The consensus
        implementation is absent for the opposite reason -- it is the thing being
        derived -- and the reference is always here.
        """
        return tuple(
            implementation
            for implementation in self.implementations
            if implementation.decides
        )

    @property
    def transcriptions(self) -> tuple[MethodImplementation, ...]:
        """Every implementation somebody else wrote, the reference included.

        What the difference report compares and what the consensus
        implementation is derived from: the numbers this list did not invent.
        """
        return tuple(
            implementation
            for implementation in self.implementations
            if implementation.role is not ImplementationRole.CONSENSUS
        )

    def _of_role(self, role: ImplementationRole) -> MethodImplementation:
        for implementation in self.implementations:
            if implementation.role is role:
                return implementation
        raise ValueError(  # pragma: no cover - checked when the file is read
            f"{self.label} declares no {role} implementation."
        )

    @property
    def label_with_version(self) -> str:
        return f"{self.name} {self.version}".strip()

    def by_stated_identifier(self, implementation: str) -> dict[str, ImpactCategoryDefinition]:
        """This method's categories, keyed by the identifier *implementation*
        states -- the JRC's ILCD method UUID, which every one of its factor rows
        names."""
        return _stated_indexes(self.slug, implementation)[0]

    def by_stated_name(self, implementation: str) -> dict[str, ImpactCategoryDefinition]:
        """This method's categories, keyed by the name *implementation* calls
        each one -- what ecoinvent's CF rows carry."""
        return _stated_indexes(self.slug, implementation)[1]

    def definition_for(
        self,
        *,
        implementation: MethodImplementation,
        identifier: str | None = None,
        name: str | None = None,
    ) -> ImpactCategoryDefinition | None:
        """The category a publisher's factor row names, or ``None``.

        A publisher is looked up in its own index and nobody else's: two
        implementations of one method call one category two things, and a lookup
        that fell through to the other's index would file a factor under a
        category its publisher never named.

        The consensus implementation is the exception, and it has to be: its rows
        are the other implementations' rows, so one carries whichever identity
        its publisher stated.  It is asked of every implementation, reference
        first.
        """
        if implementation.role is ImplementationRole.CONSENSUS:
            candidates = tuple(
                other.slug for other in (self.reference, *self.transcriptions)
            )
        else:
            candidates = (implementation.slug,)
        seen: set[str] = set()
        for slug in candidates:
            if slug in seen:
                continue
            seen.add(slug)
            if identifier:
                found = self.by_stated_identifier(slug).get(identifier)
                if found is not None:
                    return found
            if name:
                found = self.by_stated_name(slug).get(name)
                if found is not None:
                    return found
        return None


@lru_cache(maxsize=None)
def lcia_methods() -> tuple[LCIAMethodDefinition, ...]:
    """Every method this list publishes, in file order.

    :raises FileNotFoundError: if a registered file is absent.
    :raises ValueError: if a file is malformed, names an unknown unit IRI, or
        claims a part no row defines.  A method that half-loads is worse than one
        that does not load: a category silently missing here is a published
        implementation silently missing a slice of its factors.
    """
    methods = tuple(_read(path) for path in METHOD_FILEPATHS)
    slugs = [method.slug for method in methods]
    if len(set(slugs)) != len(slugs):
        raise ValueError(
            "Two LCIA method files declare one method slug, so their categories "
            "would be minted under one IRI."
        )
    return methods


@lru_cache(maxsize=None)
def lcia_method_by_slug() -> dict[str, LCIAMethodDefinition]:
    """The methods, keyed on the slug their IRIs carry."""
    return {method.slug: method for method in lcia_methods()}


def lcia_method(slug: str) -> LCIAMethodDefinition:
    """The method published under this slug.

    :raises KeyError: naming what is registered, because a caller that guessed a
        slug wrong would otherwise get an empty method and publish nothing.
    """
    try:
        return lcia_method_by_slug()[slug]
    except KeyError:
        known = ", ".join(sorted(lcia_method_by_slug()))
        raise KeyError(
            f"No LCIA method {slug!r} is registered; {known} are."
        ) from None


def ef_method() -> LCIAMethodDefinition:
    """EF 3.1, for the readers that are genuinely about EF."""
    return lcia_method(EF_METHOD_SLUG)


@lru_cache(maxsize=None)
def impact_categories() -> tuple[ImpactCategoryDefinition, ...]:
    """Every category of every method.

    For a caller that needs to turn a slug into a display name and does not care
    whose method it is.  Two methods may state one slug, and this is the reason
    nothing that has to *identify* a category may use it.
    """
    return tuple(
        category for method in lcia_methods() for category in method.categories
    )


@lru_cache(maxsize=None)
def _stated_indexes(
    method: str, implementation: str
) -> tuple[dict[str, ImpactCategoryDefinition], dict[str, ImpactCategoryDefinition]]:
    """One implementation's categories, by identifier and by name.

    Cached because the caller is a loop over hundreds of thousands of factor
    rows, each of which asks which category it is about.
    """
    definition = lcia_method(method)
    by_identifier: dict[str, ImpactCategoryDefinition] = {}
    by_name: dict[str, ImpactCategoryDefinition] = {}
    for category in definition.categories:
        stated = category.stated_by(implementation)
        if stated is None:
            continue
        if stated.identifier:
            by_identifier[stated.identifier] = category
        if stated.name:
            by_name[stated.name] = category
    return by_identifier, by_name


@lru_cache(maxsize=None)
def by_stated_method_category() -> dict[tuple[str, str], ImpactCategoryDefinition]:
    """Every category, keyed by the ``(method, category)`` names a publisher who
    has its own method names files it under -- the ingested method and the
    earlier ones.

    For a reader holding a score a release computed with whatever method it
    shipped, and asking which of our categories it is about, and for the ingest
    check that a workbook method still names the categories a method file pairs
    with it.  Only implementations that state a method of their own appear: the
    JRC's category rows carry a UUID rather than a method name, so they are not
    in here and nothing looks for them.
    """
    index: dict[tuple[str, str], ImpactCategoryDefinition] = {}
    for method in lcia_methods():
        for category in method.categories:
            for implementation in method.implementations:
                stated = category.stated_by(implementation.slug)
                if stated is not None and stated.method:
                    index[(stated.method, stated.name)] = category
                for earlier in category.earlier.get(implementation.slug, ()):
                    index[(earlier.method, earlier.name)] = category
    return index


def _read(path: Path) -> LCIAMethodDefinition:
    if not path.exists():
        raise FileNotFoundError(f"LCIA method file not found at {path}.")
    payload = orjson.loads(path.read_bytes())
    method = payload.get("method")
    if not isinstance(method, dict):
        raise ValueError(f"{path.name}: states no `method` block.")
    implementations = tuple(
        _implementation(entry, path=path)
        for entry in payload.get("implementations") or ()
    )
    method_slug = _text(method, "slug", path=path)
    categories = tuple(
        _definition(
            entry, method=method_slug, implementations=implementations, path=path
        )
        for entry in payload.get("categories") or ()
    )
    definition = LCIAMethodDefinition(
        slug=method_slug,
        name=_text(method, "name", path=path),
        version=_text(method, "version", path=path),
        label=_text(method, "label", path=path),
        description=str(method.get("description") or ""),
        implementations=implementations,
        categories=categories,
        read_from=path.name,
    )
    _check(definition, path=path)
    return definition


def _implementation(entry: Any, *, path: Path) -> MethodImplementation:
    if not isinstance(entry, dict):
        raise ValueError(f"{path.name}: each implementation must be an object.")
    try:
        role = ImplementationRole(entry["role"])
    except (KeyError, ValueError) as exc:
        raise ValueError(
            f"{path.name}: the implementation {entry.get('slug')!r} states a "
            f"role no implementation can have ({exc})."
        ) from exc
    decides = entry.get("decides")
    if not isinstance(decides, bool):
        raise ValueError(
            f"{path.name}: the implementation {entry.get('slug')!r} does not say "
            f"whether it decides, and whether a number of theirs may become one "
            f"of ours is not a thing to leave to a default."
        )
    return MethodImplementation(
        slug=_text(entry, "slug", path=path),
        name=_text(entry, "name", path=path),
        role=role,
        decides=decides,
        factors=_factors(entry.get("factors"), slug=entry.get("slug"), path=path),
        source=str(entry.get("source") or ""),
        release=str(entry.get("release") or ""),
        identifiers_from=str(entry.get("identifiers_from") or ""),
    )


def _factors(entry: Any, *, slug: Any, path: Path) -> FactorSpec:
    if not isinstance(entry, dict):
        raise ValueError(
            f"{path.name}: the implementation {slug!r} states no `factors` "
            f"block, so nothing knows where to read its numbers from."
        )
    try:
        route = FactorRoute(entry["from"])
    except (KeyError, ValueError) as exc:
        raise ValueError(
            f"{path.name}: the implementation {slug!r} states a factor route "
            f"nothing can read ({exc})."
        ) from exc
    source_list = str(entry.get("list") or "")
    if route is not FactorRoute.DERIVED and not source_list:
        raise ValueError(
            f"{path.name}: the implementation {slug!r} reads its factors "
            f"{route} and names no source list."
        )
    return FactorSpec(
        route=route,
        source_list=source_list,
        stated_method=str(entry.get("method") or ""),
    )


def _definition(
    entry: Any,
    *,
    method: str,
    implementations: tuple[MethodImplementation, ...],
    path: Path,
) -> ImpactCategoryDefinition:
    if not isinstance(entry, dict):
        raise ValueError(f"{path.name}: each category must be an object.")
    name = _text(entry, "name", path=path)
    try:
        area = AreaOfProtection(entry["area_of_protection"])
        midpoint = MidpointEndpoint(entry["midpoint_endpoint"])
    except (KeyError, ValueError) as exc:
        raise ValueError(
            f"{path.name}: {name!r} states an area of protection or "
            f"midpoint/endpoint the record has no value for ({exc})."
        ) from exc
    known = {implementation.slug for implementation in implementations}
    group = entry.get("category_group")
    return ImpactCategoryDefinition(
        method=method,
        slug=_text(entry, "slug", path=path),
        name=name,
        description=_text(entry, "description", path=path),
        area_of_protection=area,
        midpoint_endpoint=midpoint,
        category_group=str(group) if group else None,
        unit_iri=_text(entry, "unit_iri", path=path),
        parts=tuple(str(part) for part in entry.get("parts") or ()),
        stated={
            slug: _stated(stated, implementation=slug, category=name, path=path)
            for slug, stated in (entry.get("stated") or {}).items()
            if _known(slug, known, category=name, path=path)
        },
        comment=str(entry.get("comment") or ""),
        earlier={
            slug: tuple(
                _stated(item, implementation=slug, category=name, path=path)
                for item in items
            )
            for slug, items in (entry.get("earlier") or {}).items()
            if _known(slug, known, category=name, path=path)
        },
        indicator=_category_indicator(
            entry.get("indicator"), category=name, path=path
        ),
    )


def _category_indicator(
    entry: Any, *, category: str, path: Path
) -> CategoryIndicator | None:
    if entry is None:
        return None
    if not isinstance(entry, dict):
        raise ValueError(
            f"{path.name}: the indicator of {category!r} must be an object."
        )
    words = str(entry.get("words") or "").strip()
    source = str(entry.get("source") or "").strip()
    if not words or not source:
        raise ValueError(
            f"{path.name}: {category!r} states an indicator without both its "
            f"words and their source, and words nobody is named as having "
            f"written read as the publisher's."
        )
    return CategoryIndicator(words=words, source=source)


def _known(slug: str, known: set[str], *, category: str, path: Path) -> bool:
    if slug not in known:
        raise ValueError(
            f"{path.name}: {category!r} states what {slug!r} calls it, and the "
            f"file declares no such implementation."
        )
    return True


def _stated(
    entry: Any, *, implementation: str, category: str, path: Path
) -> StatedCategoryName:
    if not isinstance(entry, dict):
        raise ValueError(
            f"{path.name}: what {implementation!r} calls {category!r} must be an "
            f"object."
        )
    return StatedCategoryName(
        implementation=implementation,
        name=_text(entry, "name", path=path),
        indicator=str(entry.get("indicator") or ""),
        unit=str(entry.get("unit") or ""),
        identifier=str(entry.get("identifier") or ""),
        method=str(entry.get("method") or ""),
    )


def _text(entry: dict[str, Any], key: str, *, path: Path) -> str:
    value = str(entry.get(key) or "").strip()
    if not value:
        raise ValueError(f"{path.name}: a row states no {key!r}.")
    return value


def _check(method: LCIAMethodDefinition, *, path: Path) -> None:
    """What a method file has to be true of itself, checked where it is read."""
    for role in (ImplementationRole.REFERENCE, ImplementationRole.CONSENSUS):
        found = [
            implementation
            for implementation in method.implementations
            if implementation.role is role
        ]
        if len(found) != 1:
            raise ValueError(
                f"{path.name}: declares {len(found)} implementations with the "
                f"role {role}, and a method has exactly one."
            )
    if not method.reference.decides:
        raise ValueError(
            f"{path.name}: the method's own publisher does not decide. A number "
            f"of theirs is the method's own number, and nothing else can be "
            f"weighed against it."
        )
    if method.consensus.decides:
        raise ValueError(
            f"{path.name}: the consensus implementation decides, and it is the "
            f"thing being decided."
        )
    for implementation in method.implementations:
        borrowed = implementation.identifiers_from
        if borrowed:
            if borrowed not in {row.slug for row in method.implementations}:
                raise ValueError(
                    f"{path.name}: {implementation.slug!r} takes its identifiers "
                    f"from {borrowed!r}, which the file does not declare."
                )
            for category in method.categories:
                mine = category.stated_by(implementation.slug)
                theirs = category.stated_by(borrowed)
                if mine is None or theirs is None:
                    continue
                if mine.identifier != theirs.identifier:
                    raise ValueError(
                        f"{path.name}: {category.name!r} gives "
                        f"{implementation.slug!r} the identifier "
                        f"{mine.identifier!r}, and {borrowed!r} states "
                        f"{theirs.identifier!r}. Every one of this "
                        f"implementation's categories carries the other's "
                        f"identifier, and a factor of theirs is filed under our "
                        f"category by it; a release that mints its own needs "
                        f"that join written before this row can change."
                    )
        derived = implementation.factors.route is FactorRoute.DERIVED
        if derived is not implementation.ours:
            raise ValueError(
                f"{path.name}: {implementation.slug!r} is "
                f"{'not ' if implementation.ours else ''}the consensus "
                f"implementation and reads its factors "
                f"{implementation.factors.route}. Only ours is derived, and "
                f"ours is only derived."
            )
    if method.consensus.name != CONSENSUS_IMPLEMENTATION:
        raise ValueError(
            f"{path.name}: names its consensus implementation "
            f"{method.consensus.name!r}; this list publishes under "
            f"{CONSENSUS_IMPLEMENTATION!r} for every method it characterises."
        )
    for field_name, values in (
        ("slug", [row.slug for row in method.implementations]),
        ("name", [row.name for row in method.implementations]),
    ):
        if len(set(values)) != len(values):
            raise ValueError(
                f"{path.name}: two implementations share a {field_name}, so one "
                f"of them cannot be addressed."
            )
    for field_name, values in (
        ("slug", [category.slug for category in method.categories]),
        ("name", [category.name for category in method.categories]),
    ):
        if len(set(values)) != len(values):
            raise ValueError(
                f"{path.name}: two categories share a {field_name}, so one of "
                f"them cannot be addressed."
            )
    for implementation in method.implementations:
        identifiers = [
            stated.identifier
            for category in method.categories
            if (stated := category.stated_by(implementation.slug)) is not None
            and stated.identifier
        ]
        names = [
            stated.name
            for category in method.categories
            if (stated := category.stated_by(implementation.slug)) is not None
        ]
        for field_name, values in (("identifier", identifiers), ("name", names)):
            if len(set(values)) != len(values):
                raise ValueError(
                    f"{path.name}: two categories share the {field_name} "
                    f"{implementation.slug!r} states, so a factor row naming it "
                    f"is about two of them."
                )
        earlier_keys = [
            (earlier.method, earlier.name)
            for category in method.categories
            for earlier in category.earlier.get(implementation.slug, ())
        ]
        if len(set(earlier_keys)) != len(earlier_keys):
            raise ValueError(
                f"{path.name}: two categories claim one earlier "
                f"{implementation.slug!r} (method, category), so a score under "
                f"it is about two of ours."
            )
        stated_method = {
            stated.method
            for category in method.categories
            if (stated := category.stated_by(implementation.slug)) is not None
            and stated.method
        }
        for earlier in {
            earlier.method
            for category in method.categories
            for earlier in category.earlier.get(implementation.slug, ())
        }:
            if earlier in stated_method:
                raise ValueError(
                    f"{path.name}: {implementation.slug!r} lists {earlier!r} as "
                    f"an earlier method; it is the ingested one."
                )
    known = known_unit_iris()
    names = {category.name for category in method.categories}
    for category in method.categories:
        if category.unit_iri not in known:
            raise ValueError(
                f"{path.name}: {category.name!r} states the unit "
                f"{category.unit_iri!r}, which units.json does not have."
            )
        for part in category.parts:
            if part not in names:
                raise ValueError(
                    f"{path.name}: {category.name!r} sums {part!r}, which no row "
                    f"defines."
                )
            if part == category.name:
                raise ValueError(f"{path.name}: {category.name!r} sums itself.")
        stated = category.stated_by(method.reference.slug)
        if (
            category.indicator is not None
            and stated is not None
            and stated.indicator
        ):
            raise ValueError(
                f"{path.name}: {category.name!r} states an indicator of its own "
                f"beside the one {method.reference.slug!r} states. The "
                f"publisher's is the one published, so ours would never be read."
            )
