"""The records a characterisation is made of.

A characterisation factor arrives as a sentence in somebody else's words: *this
substance, in this compartment, has this number under this category, and here is
what we call the category*.  Only after the crosswalk
(``data/lcia-impact-categories.json``) has said which of our impact categories
that is, and the matching has said which of our flows, is it a
:class:`CharacterizationFactor` -- which carries identifiers on both sides,
because by then both are ours.

So this module has two halves, and the difference between them is who the words
belong to:

* :class:`StatedCategory`, :class:`StatedFactor` and :class:`SupersededValue`
  are what a publisher said.  A factor's flow is named by the publisher's own
  identifier and its category by the publisher's own name.
* :class:`LCIAMethod`, :class:`ImpactCategory` and
  :class:`CharacterizationFactor` are what this list publishes, joined by our
  identifiers.

The stated half exists because it has been a dict since the beginning.  Measured over the build of
2026-08-16, ``lcia_methods`` on the flow record holds 319,575 dicts across
89,070 flows in exactly three shapes: the six keys EF's files state, those plus
``superseded_values``, and those plus ``provenance``.  Nothing else -- no nested
factor list, no ``characterisation_factor`` spelling, no entry that is not a
dict -- and yet every reader defends against all of them, because a dict has no
way to say which shapes exist.  ``flow_layers.contested_cas`` decides which CAS
number a substance keeps by comparing two flows' factors, and its defence
against an unexpected shape is a silent skip: a decision made on no evidence.

Nothing reads the stated records yet.  The conversion of ``lcia_methods`` and its
six readers is its own change, and it has to prove that the published bytes did
not move; see ``plans/lcia-factors.md`` §3.8.

Three things about their shape, each of which is why it is this one:

* **The category is a record and factors share it.**  Twenty-five
  :class:`StatedCategory` objects stand behind 319,575 factors, where the dict
  repeated the same five strings on every one of them.  It is also the record
  ``lcia-methods.json`` is written from -- that file is a category plus a count
  -- so making it a record removes a second spelling rather than adding a first.
* **A factor is mutable.**  ``pipeline.deduplication.settle_factor_values``
  edits the surviving row in place on purpose, so that the harmonised flow and
  the elementary flow that share it cannot state one factor two ways.  A frozen
  record would forbid the thing that pass exists to do.
* **A declined number is a record too.**  :class:`SupersededValue` is #63's
  entry: the number a collapse did not keep, naming the flow that published it,
  so that a value a merge refused to write is as findable as one it wrote.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from functools import lru_cache
from typing import Any
from uuid import UUID

from brightway_flows.domain.common import Provenance

#: Written into every LCIA artifact, and into `lcia_runs.schema_version`.
#:
#: Its own number, module-local as rule 13 asks: unqualified `SCHEMA_VERSION`
#: means the published flow list's, and a flow-list bump has nothing to say about
#: a factor.  One number for the artifacts *and* the tables, because both are
#: renderings of the records below -- a change to a record moves both, and two
#: numbers that always move together are one number with a chance to disagree.
LCIA_SCHEMA_VERSION = 2

#: The key a factor's amount is published under inside the flow record, and the
#: only spelling any shipped file uses -- measured across the two that carry
#: factors, EF 3.1's 319,575 rows and the Stepwise input's 9,629.
FACTOR_AMOUNT_KEY = "characterization_factor"

#: The other spelling, read but never written.  Nothing states it today; it is
#: accepted because a record that silently renamed a source list's key would
#: publish different bytes than the file it read, and
#: :attr:`StatedFactor.amount_key` is what keeps a row spelled the way its
#: publisher spelled it.
FACTOR_AMOUNT_KEY_ALTERNATIVE = "characterisation_factor"

#: Where the numbers a collapse declined are published, per #63.
SUPERSEDED_VALUES_KEY = "superseded_values"

#: Where the place a factor is about is published.  EF 3.1 states one on 42,871
#: of its 319,575 factors -- 223 codes, from `AT` to `ES-CA` -- and until #314's
#: PR 3b nothing read it, so those rows reached the flow record as numbers with
#: nothing to tell them apart: 213 `Land use` factors on one flow, all of them
#: `Land use`, none of them the same number.
GEOGRAPHY_KEY = "geography"

#: The keys a factor row states about its category, in the order every shipped
#: file writes them.  Every row in both files states all five; a row that states
#: fewer keeps its own set, because the row is re-published from this record and
#: a key filled in here is a key that appears in an artifact from nowhere.
CATEGORY_KEYS: tuple[str, ...] = (
    "method_uuid",
    "name",
    "methodology",
    "impact_category",
    "impact_indicator",
)


_CATEGORY_KEY_SET = frozenset(CATEGORY_KEYS)


@dataclass(frozen=True, slots=True)
class StatedCategory:
    """An impact category as its own publisher names it.

    Frozen and shared: :func:`stated_category` returns one instance per distinct
    category, so two factors of one category are two objects pointing at a third
    rather than two copies of five strings -- 25 objects behind EF 3.1's 319,575
    factors.

    ``None`` and ``""`` are different answers and both are kept.  The Stepwise
    input states ``"methodology": null`` on all 9,629 of its factor rows, and a
    record that turned that into an empty string would re-publish the file with
    a value it does not have.
    """

    #: The ILCD dataset UUID of the method file, under which every one of that
    #: method's factor rows is filed.  ``None`` where a publisher states none.
    uuid: str | None
    #: What the publisher calls it: ``Ecotoxicity, freshwater``.
    name: str | None
    #: The methodology the category belongs to: ``Environmental Footprint``.
    methodology: str | None = None
    #: ILCD's ``impactCategory`` -- ``Aquatic eco-toxicity``.  A grouping in the
    #: publisher's own taxonomy, not ours, and for ``Water use`` EF gives the
    #: string ``other``.
    impact_category: str | None = None
    #: What the number means: ``Comparative Toxic Unit for ecosystems (CTUe)``.
    impact_indicator: str | None = None
    #: The unit as the publisher writes it, before it is resolved against
    #: ``units.json``.  Stated by a method file and not by a factor row, so a
    #: category rebuilt from a flow's factors does not carry it.
    reference_unit: str | None = None
    #: The publisher's own comment on the method, on the same terms.
    general_comment: str | None = None

    def to_flow_entry_fields(self, keys: tuple[str, ...]) -> dict[str, Any]:
        """What a factor row states about its category, in the row's own order."""
        values = {
            "method_uuid": self.uuid,
            "name": self.name,
            "methodology": self.methodology,
            "impact_category": self.impact_category,
            "impact_indicator": self.impact_indicator,
        }
        return {key: values[key] for key in keys}

    def to_method_entry(self, factor_count: int) -> dict[str, Any]:
        """One entry of ``lcia-methods.json``: the category, and how many
        factors its file states.

        The count is passed in rather than held on the record because it is a
        fact about a file rather than about a category -- the same category read
        from a later release states a different number of factors.
        """
        return {
            "uuid": self.uuid,
            "name": self.name,
            "methodology": self.methodology,
            "impact_category": self.impact_category,
            "impact_indicator": self.impact_indicator,
            "reference_unit": self.reference_unit,
            "general_comment": self.general_comment,
            "factor_count": factor_count,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> StatedCategory:
        """Read one entry of ``lcia-methods.json``."""
        return stated_category(
            uuid=payload.get("uuid"),
            name=payload.get("name"),
            methodology=payload.get("methodology"),
            impact_category=payload.get("impact_category"),
            impact_indicator=payload.get("impact_indicator"),
            reference_unit=payload.get("reference_unit"),
            general_comment=payload.get("general_comment"),
        )


@lru_cache(maxsize=None)
def stated_category(
    *,
    uuid: str | None,
    name: str | None,
    methodology: str | None = None,
    impact_category: str | None = None,
    impact_indicator: str | None = None,
    reference_unit: str | None = None,
    general_comment: str | None = None,
) -> StatedCategory:
    """The category with these fields, built once and shared.

    Interned rather than merely constructed, because the caller is a loop over
    hundreds of thousands of factor rows that between them name a couple of
    dozen categories.  The cache is unbounded, which is safe on the shape of the
    data: it is keyed on a category, and a run holds 25 of them.
    """
    return StatedCategory(
        uuid=uuid,
        name=name,
        methodology=methodology,
        impact_category=impact_category,
        impact_indicator=impact_indicator,
        reference_unit=reference_unit,
        general_comment=general_comment,
    )


@dataclass(slots=True)
class SupersededValue:
    """A number a collapse declined, and the flow that published it.

    Written by ``pipeline.deduplication`` when two rows that turned out to be
    one flow state one factor differently, and by a curated collision ruling
    doing the same under its own name.
    """

    #: The number not kept.
    amount: float
    #: Who declined it and where it came from.
    provenance: Provenance | None = None
    #: How far apart the two numbers were, as a fraction of the smaller.
    #: ``None`` where the question does not arise -- across zero, or across a
    #: sign change, where a relative difference is not defined.
    relative_difference: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """The published shape.

        All 204 of these in the build carry all three keys in this order, which
        is the order ``settle_factor_values`` builds them in.
        """
        payload: dict[str, Any] = {FACTOR_AMOUNT_KEY: self.amount}
        if self.provenance is not None:
            payload["provenance"] = self.provenance.to_dict()
        if self.relative_difference is not None:
            payload["relative_difference"] = self.relative_difference
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> SupersededValue:
        provenance = payload.get("provenance")
        return cls(
            amount=float(payload[FACTOR_AMOUNT_KEY]),
            provenance=(
                Provenance.from_dict(provenance)
                if isinstance(provenance, dict)
                else None
            ),
            relative_difference=payload.get("relative_difference"),
        )


@dataclass(slots=True)
class StatedFactor:
    """That a publisher stated this amount for this flow in this category.

    ``amount`` is exactly what the file said, including a stated ``0.0``:
    EF 3.1 declares 52,088 of those and they are kept, because "assessed, and
    the factor is zero" and "never assessed" are different statements, and #48
    is what it cost to spell them the same way (#47).
    """

    #: The category, shared with every other factor stating it.
    category: StatedCategory
    #: The publisher's own identifier for the flow -- an ILCD UUID for EF.
    #: Empty on a factor read from inside a flow record, which does not restate
    #: the flow it is on.
    flow_uuid: str
    #: The number, in the category's reference unit, per unit of that flow.
    amount: float
    #: Where the number applies, as the publisher spells it -- `ES-CA`, `YE`,
    #: `RER`.  ``None`` where the publisher states none, which is the ordinary
    #: case: a factor is about a substance in a compartment, and only a model
    #: whose result depends on where the land or the water is needs a third.
    #:
    #: This is what makes the row unique. EF states one factor per (flow,
    #: geography, category) -- checked over all 25 of its method files, where
    #: `(flow, location)` names one factor every time -- and the upstream model
    #: says the same thing. Without it, `Land use` states 213 numbers about one
    #: flow and no reader can tell which is which.
    geography: str | None = None
    #: The key the amount was published under, so that a row this pipeline
    #: rewrites goes on being spelled the way its source list spelled it.
    amount_key: str = FACTOR_AMOUNT_KEY
    #: Which of :data:`CATEGORY_KEYS` the row stated, in its order.  All five in
    #: every row of both shipped files; a row that states fewer is re-published
    #: with the same few rather than gaining keys it never had.
    stated_keys: tuple[str, ...] = CATEGORY_KEYS
    #: Set where a pass or a ruling rewrote the number, saying which.
    provenance: Provenance | None = None
    #: Numbers another row published for this factor that were not kept.
    superseded_values: list[SupersededValue] = field(default_factory=list)
    #: Keys the publisher states that this record does not declare, kept in the
    #: order they arrived so that a row re-published from this record is the row
    #: that was read (rule 3).  The Stepwise input's
    #: ``characterization_factor_flow_unit`` is the one in the wild.
    extra: dict[str, Any] = field(default_factory=dict)

    def to_flow_entry(self) -> dict[str, Any]:
        """The published shape, as the flow record has always carried it.

        Key order is the order EF's parser wrote it in and the order the
        artifacts have, so a record round-trips to the same bytes.  Measured: of
        the 319,575 rows in the build, 146 carry ``superseded_values`` and 50
        carry ``provenance`` as well, and in all 50 ``provenance`` comes first --
        so the optional keys are appended in that order rather than in the order
        two passes happened to write them.  This is the I/O boundary rule 2
        allows a dict at, and the only place one belongs.
        """
        payload: dict[str, Any] = self.category.to_flow_entry_fields(
            self.stated_keys
        )
        payload[self.amount_key] = self.amount
        # Only where the publisher states one, so the 276,704 rows that state
        # none are the rows they were.
        if self.geography is not None:
            payload[GEOGRAPHY_KEY] = self.geography
        payload.update(self.extra)
        if self.provenance is not None:
            payload["provenance"] = self.provenance.to_dict()
        if self.superseded_values:
            payload[SUPERSEDED_VALUES_KEY] = [
                value.to_dict() for value in self.superseded_values
            ]
        return payload

    @classmethod
    def from_flow_entry(
        cls, payload: dict[str, Any], *, flow_uuid: str = ""
    ) -> StatedFactor:
        """One entry of a flow's ``lcia_methods`` list, as a record.

        :raises ValueError: if the entry states no amount.  A factor without a
            number is not a factor, and every one of the 329,204 rows in the two
            files that carry them states one -- so this is a shape nobody has,
            and failing on it is better than publishing a row whose number this
            record had to invent.
        """
        amount_key = FACTOR_AMOUNT_KEY
        if amount_key not in payload:
            amount_key = FACTOR_AMOUNT_KEY_ALTERNATIVE
        amount = payload.get(amount_key)
        if not isinstance(amount, (int, float)) or isinstance(amount, bool):
            raise ValueError(
                f"A characterisation factor states no amount: {payload!r}"
            )
        provenance = payload.get("provenance")
        declared = {
            *CATEGORY_KEYS,
            amount_key,
            GEOGRAPHY_KEY,
            "provenance",
            SUPERSEDED_VALUES_KEY,
        }
        return cls(
            category=stated_category(
                uuid=payload.get("method_uuid"),
                name=payload.get("name"),
                methodology=payload.get("methodology"),
                impact_category=payload.get("impact_category"),
                impact_indicator=payload.get("impact_indicator"),
            ),
            flow_uuid=flow_uuid,
            amount=float(amount),
            geography=payload.get(GEOGRAPHY_KEY),
            amount_key=amount_key,
            stated_keys=tuple(key for key in payload if key in _CATEGORY_KEY_SET),
            provenance=(
                Provenance.from_dict(provenance)
                if isinstance(provenance, dict)
                else None
            ),
            superseded_values=[
                SupersededValue.from_dict(value)
                for value in payload.get(SUPERSEDED_VALUES_KEY) or ()
            ],
            extra={
                key: value for key, value in payload.items() if key not in declared
            },
        )


def non_zero_factor_count(factors: Any) -> int:
    """How many of these state a number that is not zero.

    The size of a flow's characterisation, as the pipeline counts it in the two
    places the number decides something: which of two duplicate rows survives a
    collapse, and what the review application shows as a group's factor count.

    A stated zero is ingested and kept (#47) and deliberately does not count.
    Counting it would change which flow survives a collision as a side effect of
    an ingest fix; whether an explicit zero should count is the question #36 and
    #44 are already asking, and it is theirs to answer.
    """
    if not isinstance(factors, list):
        return 0
    return sum(1 for factor in factors if factor.amount != 0)


def non_zero_factor_count_of_entries(entries: Any) -> int:
    """:func:`non_zero_factor_count`, for a caller holding the serialised rows.

    The SQLite writer works on the payload a record was serialised to rather
    than on the record -- it is assembling a column out of two dicts, the
    layered row and the flow it was layered from -- so it asks the same question
    of the same rows in the form it has them.  One rule, two spellings of the
    row it is asked about; a third spelling of the rule would be the bug.
    """
    if not isinstance(entries, list):
        return 0
    return sum(
        1
        for entry in entries
        if isinstance(entry, dict) and entry.get(FACTOR_AMOUNT_KEY) != 0
    )


def flow_entries(factors: Any) -> Any:
    """A flow's factors, as the list the record serialises to.

    The encode half of the codec :class:`~brightway_flows.domain.flow.Flow`
    and :class:`~brightway_flows.domain.elementary_flow.ElementaryFlow`
    declare for ``lcia_methods``.  Tolerant of a value that is not a list of
    records, because the field is built directly by a dozen callers and several
    of them pass something else.
    """
    if not isinstance(factors, list):
        return factors
    return [
        factor.to_flow_entry() if isinstance(factor, StatedFactor) else factor
        for factor in factors
    ]


#: The published shape of a flow's ``lcia_methods``, for the schema generator.
#: A list of objects, and no more than that: what a row holds is the source
#: list's own five category keys plus its amount, and two source lists already
#: state a sixth between them, so a schema naming the keys would refuse a
#: publisher this one has not met.  Tightening it is a question for the change
#: that publishes the factors as their own artifact, where the shape is ours.
FLOW_ENTRIES_SCHEMA: dict[str, Any] = {
    "items": {"additionalProperties": True, "type": "object"},
    "title": "Lcia Methods",
    "type": "array",
}


def stated_factors(payload: Any) -> Any:
    """A flow's ``lcia_methods`` payload, as records.

    The decode half.  A value that is not a list of dicts is left alone: the
    codec runs on whatever the payload held, and a record that has already been
    built -- which is what ``Flow.from_dict(elementary.to_dict())`` hands it on
    the way through the merge -- is not re-parsed.
    """
    if not isinstance(payload, list):
        return payload
    return [
        StatedFactor.from_flow_entry(entry) if isinstance(entry, dict) else entry
        for entry in payload
    ]


# ─── What this list publishes ────────────────────────────────────────────────
# A method holds impact categories, a category holds characterisation factors,
# and the category is where the interesting fields are: it is the category, not
# the factor, that knows who implemented it, what it protects, what unit its
# numbers are in and which emissions it counts.


class AreaOfProtection(StrEnum):
    """What a category is protecting.

    ``ASSETS`` is availability rather than damage: a resource or a service that
    somebody else no longer has.  ``CLIMATE_CHANGE`` is its own value rather
    than being split across the three it acts on, because that is how every
    method that reports it reports it.
    """

    UNKNOWN = "Unknown"
    HUMAN_HEALTH = "Human Health"
    ASSETS = "Resources and ecosystem services"
    ECOSYSTEM_QUALITY = "Ecosystem Quality"
    CLIMATE_CHANGE = "Climate Change"


class MidpointEndpoint(StrEnum):
    """Where along the cause-and-effect chain the number is stated."""

    UNKNOWN = "Unknown"
    MIDPOINT = "Midpoint"
    ENDPOINT = "Endpoint"


class UncertaintyLevel(StrEnum):
    """Which factors an implementation kept, where its method grades them."""

    UNKNOWN = "Unknown"
    CERTAIN = "Only certain impacts"
    ALL = "All uncertainty levels"


class ImpactTimeframe(StrEnum):
    """Which emissions a category characterises.

    Not how far into the future the model runs: ``SHORT`` is the convention of
    excluding emissions a source list files as long-term, and ``LONG`` is
    including every one the implementer could reach.
    """

    UNKNOWN = "Unknown"
    SHORT = "Short term impacts (<100 years after emission)"
    LONG = "Long term impacts (no time horizon)"


@dataclass
class LCIAMethod:
    """A method, which is a container for impact categories.

    One row per method, for every version and implementation of it: the version
    is the category's field, so that two releases of one method are two sets of
    categories rather than two methods with one name.
    """

    id: UUID
    name: str
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """The published shape: the identifier as a string, in field order."""
        return {"id": str(self.id), "name": self.name, "meta": dict(self.meta)}


@dataclass
class CharacterizationFactor:
    """What one unit of a flow is worth under one impact category.

    There is one factor per combination of flow, geography and impact category.
    Where two source rows reach one consensus flow and disagree, that is not a
    factor to average -- it is evidence about the matching, and the pass that
    finds it reports rather than reconciles.

    **There is no ``id`` field, and that is deliberate.**  A factor is identified
    by the three things that make it one -- the category, the flow and the place --
    which is exactly the primary key ``lcia_characterization_factors`` declares.
    Minting a fourth identifier would publish two identities for one row, in two
    artifacts of the same run, which is #13's mistake about units repeated about
    factors.  A reader citing a factor cites the triple.

    ``elementary_flow_uuid`` is a string because a consensus elementary flow's
    identifier is one, and ``geography`` is one because the codes are the
    publisher's own:
    EF states 223 of them on 42,871 of its factors, ISO 3166-1 alpha-2 with four
    sub-country codes among them (``ES-CA``, ``PT-MA``, ``BQ-SB``, ``BQ-SE``).
    They are published verbatim rather than resolved: this list has no geography
    vocabulary, and inventing an identifier for a place would be minting a second
    identity for something that already has one -- which is what ``unit_iri``
    exists to avoid on the category.
    """

    elementary_flow_uuid: str
    impact_category_id: UUID
    amount: float
    #: Where the number applies, as the publisher spells it.  ``None`` on the
    #: 276,704 EF factors that are about a substance in a compartment and nothing
    #: more, and on every ecoinvent factor -- its workbook states no place.
    geography: str | None = None
    #: How this list arrived at the number, on the implementation that is ours.
    #: ``None`` on a transcription, which arrives at nothing: it says what its
    #: publisher said.
    derivation: str | None = None
    #: The source-list flow the number was read off, where that is not the
    #: consensus flow itself.  What makes a number traceable back to the file it
    #: came from without a join.  Named as the tables name it, because an artifact
    #: and the table beside it describing one row two ways is a translation step
    #: nobody should have to make.
    source_flow_uuid: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """The published shape.  Every field, in declaration order."""
        return {
            "elementary_flow_uuid": self.elementary_flow_uuid,
            "impact_category_id": str(self.impact_category_id),
            "amount": self.amount,
            "geography": self.geography,
            "derivation": self.derivation,
            "source_flow_uuid": self.source_flow_uuid,
        }


@dataclass
class ImpactCategory:
    """One category, as one implementer renders it.

    ``implemented_by`` is the field the LCIA section turns on.  There is no
    correct implementation of a method: EF 3.1 as the JRC published it and EF
    3.1 as the ecoinvent Centre implemented it are two renderings of one method
    against two flow lists, and this list publishes both plus its own judgement.
    Three implementations of one category is therefore three of these, differing
    in this field and in the numbers they hold.
    """

    id: UUID
    method: LCIAMethod
    name: str
    #: The method's version -- ``3.1`` -- not the file's.
    version: str
    area_of_protection: AreaOfProtection
    #: Who rendered it: ``European Commission — JRC``, ``ecoinvent Centre``.
    implemented_by: str
    #: The reference unit, as an IRI in ``units.json``.  An IRI rather than a
    #: local identifier because that is how every other unit reference in this
    #: project is spelled, and two identities on one unit is #13's mistake.
    unit_iri: str
    description: str
    characterization_factors: list[CharacterizationFactor]
    #: What the number means: ``global warming potential (GWP100)``.
    indicator: str | None = None
    #: The family a category belongs to, where it is in one: the value an
    #: aggregate and its parts share.
    category_group: str | None = None
    midpoint_endpoint: MidpointEndpoint = MidpointEndpoint.ENDPOINT
    uncertainty_cutoff: UncertaintyLevel = UncertaintyLevel.ALL
    timeframe: ImpactTimeframe = ImpactTimeframe.UNKNOWN
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """The published shape.

        ``characterization_factors`` is emitted here and dropped by the document
        that publishes the categories, which carries the factors under a key of
        their own: a category holding a quarter of a million of them is not a row
        anybody can read, and `elementary-flows.json` sets the precedent with
        ``source_refs``.  The schema omits it for the same reason, so the artifact
        and the schema that describes it agree.
        """
        return {
            "id": str(self.id),
            "method": self.method.to_dict(),
            "name": self.name,
            "version": self.version,
            "area_of_protection": str(self.area_of_protection),
            "implemented_by": self.implemented_by,
            "unit_iri": self.unit_iri,
            "description": self.description,
            "characterization_factors": [
                factor.to_dict() for factor in self.characterization_factors
            ],
            "indicator": self.indicator,
            "category_group": self.category_group,
            "midpoint_endpoint": str(self.midpoint_endpoint),
            "uncertainty_cutoff": str(self.uncertainty_cutoff),
            "timeframe": str(self.timeframe),
            "meta": dict(self.meta),
        }

    def __post_init__(self) -> None:
        """Every factor held here names this category.

        The weak half of the uniqueness rule, and the half a record can check
        for itself: a factor listed under one category and linked to another is
        a factor nobody can find.  That there is only one factor per (flow,
        geography, category) is the strong half, and belongs where the rows are
        written rather than where one category is built.
        """
        for factor in self.characterization_factors:
            if factor.impact_category_id != self.id:
                raise ImpactCategoryCharacterizationFactorMismatch(
                    f"Characterization factor has impact category id "
                    f"{factor.impact_category_id}, but this impact category "
                    f"has id {self.id}."
                )


# ─── What a comparison of two implementations says ───────────────────────────
# Report rows rather than a third rendering of a factor: `lcia.differences`
# computes them and `lcia.publish` writes them, and they live here because a
# published document is assembled from records and the domain cannot import the
# pipeline to find them.


class Band(StrEnum):
    """How far apart two implementations are about one factor.

    Bands rather than the ratio alone, because the ratio is what a reader sorts
    by and the band is what they filter on: "show me everything over ten times"
    is the question, and 2% is the line `contested_cas` already draws between a
    rounding and a disagreement.
    """

    IDENTICAL = "identical"
    WITHIN_TOLERANCE = "within-tolerance"
    UP_TO_2X = "2x"
    UP_TO_10X = "10x"
    UP_TO_100X = "100x"
    OVER_100X = "over-100x"
    #: A relative difference is not defined across zero or a sign change, so
    #: these are neither ranked nor rounded away.  A stated zero against a number
    #: is two implementations disagreeing about whether something has an effect.
    INCOMPARABLE = "incomparable"


def only_stated_by(implemented_by: str, *, zero: bool = False) -> str:
    """The count key for a triple only one implementation states.

    Built from the implementation rather than declared per list, because there
    will be more than two: `jrc-only` and `ecoinvent-only` as constants meant that
    a third implementation could be compared and not counted, and nothing would
    have said so.
    """
    return f"only:{implemented_by}" + (":stated-zero" if zero else "")


@dataclass(frozen=True, slots=True)
class Difference:
    """What one implementation says about a triple two or more of them state.

    **One row per implementation, not one row per pair.**  The first shape of this
    record had a `jrc` column and an `ecoinvent` column, which works for exactly
    two implementations and silently cannot hold a third -- and this project
    expects many, since every source list that ships factors is one.  Long form
    holds any number, sorts and groups in SQL without a pivot, and loads into a
    dataframe as it stands.

    ``band``, ``ratio`` and ``derivation`` are properties of the triple rather
    than of this row, and repeat across the rows that share it.  That is the cost
    of the shape and it is the right one to pay: the alternative is a second table
    to join for the two columns anybody filtering this report filters on.
    """

    #: Which method's category ``category_slug`` names.  A slug is unique inside
    #: a method and not across methods -- two methods can both have an
    #: ``acidification``, counted in different units from different models -- so a
    #: row without it is a number nobody can place.
    method: str
    elementary_flow_uuid: str
    category_slug: str
    geography: str
    #: Who states this number.
    implemented_by: str
    amount: float
    #: The source-list flow the number was read off, where that is not the
    #: consensus flow itself.
    source_flow_uuid: str | None
    #: How far apart the implementations are about this triple, from the widest
    #: pair among them.
    band: Band
    #: The larger over the smaller, or ``None`` where that is not defined.
    ratio: float | None
    #: What the consensus implementation did about it: a derivation where it
    #: published, and ``None`` where it asked instead (§4.3).
    derivation: str | None

    def to_dict(self) -> dict[str, Any]:
        """The published shape.  Every field, in declaration order."""
        return {
            "method": self.method,
            "elementary_flow_uuid": self.elementary_flow_uuid,
            "category_slug": self.category_slug,
            "geography": self.geography,
            "implemented_by": self.implemented_by,
            "amount": self.amount,
            "source_flow_uuid": self.source_flow_uuid,
            "band": str(self.band),
            "ratio": self.ratio,
            "derivation": self.derivation,
        }


@dataclass(frozen=True, slots=True)
class CoverageGap:
    """How often one implementation skips a context of a substance it characterises.

    A summary, not a list, and that is a measured decision.  Asked per (substance,
    category) over every flow, the population is 36,007 -- and most of it is the
    two flow lists being different sizes rather than anything either team did.
    Restricted to flows the implementation's *own* list has, it is 5,668: 3,766 the
    JRC's and 1,902 ecoinvent's.

    Even then a "gap" is not a defect.  The JRC's largest are photochemical ozone
    formation (881), climate change (808) and its fossil part (801), which is what
    it looks like when a substance has no global-warming potential: absence is the
    right answer and nobody should be asked to fill it in.  What the summary is
    for is finding the asymmetries worth a question -- a substance characterised in
    one soil and not the soil beside it -- so it counts by compartment and by
    category and lists nothing.
    """

    #: Which method the implementation is one of.  Two methods' gaps are two
    #: reports, and one implementer can render both.
    method: str
    implemented_by: str
    #: What the count is grouped by: a compartment, or an impact category.
    dimension: str
    value: str
    flows: int

    def to_dict(self) -> dict[str, Any]:
        """The published shape.  Every field, in declaration order."""
        return {
            "method": self.method,
            "implemented_by": self.implemented_by,
            "dimension": self.dimension,
            "value": self.value,
            "flows": self.flows,
        }


#: Where a factor's absence is the right answer rather than a gap: our long-term
#: compartments, which EF has no factors for by construction (§2.4).
LONG_TERM = "long-term"


# ─── The published documents ─────────────────────────────────────────────────
# Two files, because they answer two questions and one of them is small.  A
# reader who wants the numbers takes `lcia-factors.json.gz`; a reader comparing
# two implementations takes `lcia-differences.json`, which is a deliverable in
# its own right (§5) and 22,107 rows rather than 665,487.


@dataclass
class PublishedFactors:
    """Root object of ``lcia-factors.json.gz``.

    Three implementations of EF 3.1 in one document: the JRC's, the ecoinvent
    Centre's, and this list's.  ``implemented_by`` on a category is the field that
    separates them, and a factor names its category -- so the question "what does
    this list say phosphate in fresh water is worth" is answered by joining two
    arrays and reading one number, and the question "and what do the other two
    say" is the same join with a different filter.

    ``impact_categories`` carries no factors: the categories are 75 rows and the
    factors are 665,487, and nesting them would make the file unreadable in
    anything but a streaming parser for no gain.  The category's ``id`` is on
    every factor.
    """

    schema_version: int
    #: One row per method, and exactly one today.  The method is `EF`; its
    #: version and its implementer are the category's fields, so three
    #: implementations of EF 3.1 are 75 categories under one method rather than
    #: three methods with one name (§3.1).
    methods: list[LCIAMethod]
    impact_categories: list[ImpactCategory]
    characterization_factors: list[CharacterizationFactor]
    #: What the run counted, as `lcia_runs.stats_json` holds it.  A reader should
    #: be able to check the file against the numbers its publisher quoted without
    #: recomputing them.
    stats: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialise, dropping each category's empty factor list.

        See :meth:`ImpactCategory.to_dict`: the factors are published once, under
        their own key, and a category that repeated them -- or, worse, carried an
        empty list beside them -- would be saying something untrue about what it
        holds.
        """
        categories = []
        for category in self.impact_categories:
            row = category.to_dict()
            row.pop("characterization_factors", None)
            categories.append(row)
        return {
            "schema_version": self.schema_version,
            "methods": [method.to_dict() for method in self.methods],
            "impact_categories": categories,
            "characterization_factors": [
                factor.to_dict() for factor in self.characterization_factors
            ],
            "stats": dict(self.stats),
        }


@dataclass
class PublishedDifferences:
    """Root object of ``lcia-differences.json``: both of §5's reports.

    ``differences`` is the one the section is named for -- one row per (triple,
    implementation) where two or more published implementations state a factor for
    the triple.  Where only one speaks there is no comparison to record and it is
    counted in ``stats`` instead, because 297,468 rows of "nobody disagreed,
    because nobody else spoke" is a fact about differently sized flow lists.

    ``coverage`` is the second report and the reason this file is not called
    `lcia-comparison`: it is per implementation rather than between them, and it
    counts where one of them characterises a substance in one context and skips
    the context beside it.  A summary by compartment and by category, never a list
    of flows -- :class:`CoverageGap` says why.
    """

    schema_version: int
    differences: list[Difference]
    coverage: list[CoverageGap]
    stats: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """The published shape."""
        return {
            "schema_version": self.schema_version,
            "differences": [row.to_dict() for row in self.differences],
            "coverage": [row.to_dict() for row in self.coverage],
            "stats": dict(self.stats),
        }


class LCIAError(Exception):
    """Anything that goes wrong with a method, a category or a factor."""


class ImpactCategoryCharacterizationFactorMismatch(LCIAError):
    """Factors listed in one impact category, but linked to a different one."""
