"""When the model a method says it is built on states something else entirely.

EF 3.1's three toxicity categories are USEtox 2.1.  The JRC's report says so, and
describes the deliberate adjustments made on top of it -- the metals, most of all,
where 27 substances were re-derived from EU data sources and each change is
tabulated.  Everything else was supposed to arrive unchanged.

For **four substances it did not**, and the gap is not a rounding or a fate
model: it is more than a hundredfold in every compartment at once, and past a
millionfold for biphenyl.  Biphenyl -- two benzene rings, used in dyes, plastics
and citrus fungicide -- is characterised at 0.19957 CTUh for a kilogram emitted
to urban air, which
says that emitting a tonne of it into a city causes two hundred cases of disease.
That number ranks it **third of the 3,380 substances** EF characterises for
non-cancer human toxicity in that compartment, above mercury.  USEtox 2.1 gives
0.00000014.  The other three are o-phenylphenol, which is biphenyl with a
hydroxyl group added, benfluralin and the 2,4/2,6-toluenediisocyanate mixture.

The two published transcriptions cannot see this.  The JRC's implementation says
0.19957 because that is what EF 3.1 states, and the ecoinvent Centre's says
0.19957 where it says anything, because it transcribed the same file.  Two
implementations agreeing is not evidence when both are copying one source, and
`consensus.Derivation.AGREED` would call it agreement.

**So this is the third question the consensus implementation asks.**  Not "which
of two readings is right" (`contested-factor`) and not "should this list adopt a
number the method's publisher never stated" (`proposed-factor`), but: *the model
this method is derived from states something more than a hundredfold away, in
every compartment -- should this list publish the method's number?*  Until a
curator answers, the consensus implementation publishes nothing for that substance
and category, and the two transcriptions are untouched.  EF 3.1 says 0.19957 and
this list goes on publishing that under the JRC's name, because that is what the
JRC published.

**The evidence is data and the rule is code.**  `data/lcia-underlying-model-factors.json`
holds what USEtox 2.1 states, per substance, category and compartment, converted
from LC-Impact's damage unit into EF's midpoint one by the three measured
constants the file records.  It states no verdict.  What makes a row a
contradiction is :data:`COMPARABLE_CATEGORIES`, :data:`CONTRADICTION_RATIO` and
:data:`MINIMUM_COMPARTMENTS` applied here, **against the numbers this build
states** -- so a re-transcription that fixes biphenyl publishes it again with
nobody editing the file, exactly as a `FactorRuling` written about numbers that
have moved stops being obeyed.

**Only human toxicity is compared**, which is :data:`COMPARABLE_CATEGORIES` and
the reason it exists.  For the two human-health categories the workbook is the
same computation as EF's: cases of disease, published as the years of healthy
life those cases cost, and the divisor that turns one into the other is USEtox's
own severity constant.  For freshwater ecotoxicity it is not.  There the
workbook publishes LC-Impact's ecosystem-quality result -- a potentially
*disappeared* fraction of species, beside marine and terrestrial numbers EF has
no counterpart for at all -- and EF's CTUe is a potentially *affected* fraction.
Those are two models of what damage to a river means, and the third divisor is a
constant fitted between them rather than a unit conversion.  A ratio computed
across it does not say the method departed from the model it cites; it says the
two were never the same number, which is true of every substance and is not a
finding about any of them.

**What is deliberately not in the file.**  The 27 metals, all of which disagree
completely -- typically 25x to 75x -- because the JRC report says EF replaced
USEtox's metal factors and tabulates each change.  That is a decision, not a
defect.  And any substance disagreeing in one compartment and not another: that
is the two models routing an emission differently, most visibly for air, and no
fate difference explains a gap in all six at once.

``plans/lcia-factors.md`` §4.5 is the design.  #107 is the finding.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import orjson
import structlog

from brightway_flows.domain.lcia.crosswalk import lcia_method
from brightway_flows.filesystem import PACKAGE_DATA_DIR
from brightway_flows.lcia.matching import MatchedFactor
from brightway_flows.lcia.scope import curated_method, out_of_scope

logger = structlog.get_logger(__name__)

#: The measured evidence.  Reference data rather than a ruling: nobody is
#: overruling the pipeline in it, and every number in it was published by
#: somebody else (rule 12).
UNDERLYING_MODEL_FILEPATH = PACKAGE_DATA_DIR / "lcia-underlying-model-factors.json"

#: Bumped when the file's shape changes.  Module-local and checked where the file
#: is read, because unqualified `SCHEMA_VERSION` means the published list's
#: (rule 13).
MODEL_SCHEMA_VERSION = 1

#: The categories where a ratio against the model means anything, which is the
#: two human-health ones.  There the LC-Impact workbook and EF state the same
#: quantity -- expected cases of disease per kilogram -- one as damage and one as
#: a midpoint, and the divisor between them is USEtox's published severity
#: constant, 11.5 years of healthy life per cancer case and 2.7 per non-cancer
#: case.  Nothing is being reconciled, so a gap is the method departing from the
#: model it cites.
#:
#: Freshwater ecotoxicity is not that.  The workbook's ecotoxicity numbers are
#: LC-Impact's own ecosystem-quality result in potentially disappeared fraction,
#: published beside marine and terrestrial numbers EF does not characterise at
#: all; EF's CTUe is a potentially affected fraction.  The third divisor,
#: 0.0175906, is a constant fitted between two models rather than a conversion
#: within one -- and it shows: over the substances not in dispute, 55.3% of the
#: cancer factors and 32.5% of the non-cancer ones land within 1% of the model,
#: against 20.0% for freshwater ecotoxicity, whose middle half spans 0.45x to
#: 1.06x where cancer's spans 0.9996x to 1.043x.  A hundredfold gap measured
#: across that is not evidence that EF's number is wrong, and a queue asking a
#: curator to withdraw a published factor on it is asking for a decision on the
#: strength of a scale mismatch (2026-08-21, over 14,921 ecotoxicity and 6,312
#: human-toxicity comparisons on the build of 2026-08-20).
#:
#: The ecotoxicity rows stay in the file.  They were measured, they are somebody
#: else's published numbers, and dropping them would leave the measurement
#: unrepeatable; what changed is that nothing is asked about them.
#:
#: By method, because a category slug belongs to one: EF 3.1's
#: `human-toxicity-cancer` is USEtox with the JRC's adjustments on top, and a
#: method that happened to spell a slug the same way is not that.  A method with
#: no entry compares nothing, which is the right default -- a model file has to
#: be measured against a method before anything can be asked about it.
COMPARABLE_CATEGORIES: dict[str, frozenset[str]] = {
    "ef": frozenset({"human-toxicity-cancer", "human-toxicity-non-cancer"}),
}


def comparable_categories(method: str) -> frozenset[str]:
    """The categories of *method* where a ratio to the model means something."""
    return COMPARABLE_CATEGORIES.get(method, frozenset())

#: How far apart the two have to be before a factor is a question.  A hundredfold,
#: which is not a threshold anybody tuned: `FACTOR_TOLERANCE` at 2% is what
#: separates two readings of one number, and a factor of a hundred is past every
#: explanation short of the two models disagreeing about the substance.  The
#: narrowest gap among the four compared rows is benfluralin at 133x and the
#: widest is biphenyl at 1,381,461x, so nothing in it is near the line.
CONTRADICTION_RATIO = 100.0

#: How many compartments have to disagree before the disagreement is about the
#: substance rather than about where the emission goes.  Two models routing an
#: air emission differently is ordinary and shows up in one compartment or two;
#: all six is not a fate difference.  Four is the floor, and all 38 rows of the
#: file state six.
MINIMUM_COMPARTMENTS = 4


@dataclass(frozen=True, slots=True)
class UnderlyingModel:
    """The model an implementation's factors are supposed to come from.

    Named and versioned, with the files and the sheet it was read out of: every
    number here is a claim about somebody else's release, and a claim about a
    release nobody can find again is not reviewable.
    """

    name: str
    read_from: tuple[str, ...]
    sheet: str
    block: str
    measured_on: str


@dataclass(frozen=True, slots=True)
class ModelAmount:
    """What the model states for one substance, category and compartment.

    ``reference_amount`` is what the method's own publisher stated when this was
    measured.  It is not what the comparison uses -- that comes from the build, so
    a re-transcription is noticed -- and it is here so a reader of the file can see
    both numbers without a database, and so a build stating something else can say
    that it does.
    """

    compartment: str
    context_iri: str
    model_amount: float
    reference_amount: float


@dataclass(frozen=True, slots=True)
class ModelEvidence:
    """One substance and category, as the underlying model states it."""

    cas_number: str
    substance: str
    model_substance: str
    #: The method whose category ``category_slug`` names, from the file's own
    #: `method`.  Carried on every row because a slug belongs to a method and a
    #: row that lost it could be compared against the wrong category.
    method: str
    category_slug: str
    category: str
    unit: str
    stated: tuple[ModelAmount, ...]
    model: UnderlyingModel
    comment: str = ""


@dataclass(frozen=True, slots=True)
class Comparison:
    """One compartment, both numbers, and how far apart they are.

    ``published_amount`` is what **this build** states, which is the whole point
    of recomputing rather than trusting the file: the ratio is a fact about the
    data in front of the run.
    """

    compartment: str
    context_iri: str
    elementary_flow_uuid: str
    model_amount: float
    published_amount: float
    ratio: float


@dataclass(frozen=True, slots=True)
class Contradiction:
    """A substance and category the underlying model contradicts, and by how much.

    Keyed on the substance rather than the flow, because that is the unit a
    curator decides in and the unit a `FactorRuling` is written about: biphenyl's
    non-cancer human toxicity is one question asked about thirteen compartments.
    """

    flow_object_id: str
    category_slug: str
    cas_number: str
    substance: str
    category: str
    model: str
    read_from: tuple[str, ...]
    compared: tuple[Comparison, ...]
    comment: str = ""

    @property
    def narrowest(self) -> float:
        """The smallest gap among the compartments, which is the weakest claim."""
        return min(comparison.ratio for comparison in self.compared)

    @property
    def widest(self) -> float:
        return max(comparison.ratio for comparison in self.compared)

    def as_evidence(self) -> dict[str, Any]:
        """The contradiction as a queue row carries it.

        Both numbers per compartment and the file they came from, because a
        curator ruling on this is being asked to believe a third party's model
        against the method's own publisher, and a row that said only "contradicted"
        would be asking them to take our word for it.
        """
        return {
            "model": self.model,
            "read_from": list(self.read_from),
            "narrowest_ratio": self.narrowest,
            "widest_ratio": self.widest,
            "comment": self.comment,
            "compared": [
                {
                    "compartment": comparison.compartment,
                    "context_iri": comparison.context_iri,
                    "elementary_flow_uuid": comparison.elementary_flow_uuid,
                    "model_amount": comparison.model_amount,
                    "published_amount": comparison.published_amount,
                    "ratio": comparison.ratio,
                }
                for comparison in self.compared
            ],
        }


class UnderlyingModelError(ValueError):
    """A file that cannot be read as measured evidence.

    Raised rather than skipped, for the reason every curated file is: evidence
    that is quietly ignored is a question this list stops asking without anybody
    deciding to stop asking it (rule 14).
    """


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise UnderlyingModelError(message)


def _number(raw: object, *, position: int, field: str) -> float:
    _require(
        isinstance(raw, (int, float)) and not isinstance(raw, bool),
        f"row {position}: {field} is {raw!r}, which is not a number",
    )
    return float(raw)  # type: ignore[arg-type]


def load_underlying_model_factors(
    path: Path | None = None, *, method: str | None = None
) -> tuple[ModelEvidence, ...]:
    """What the underlying model states, as records.

    *method* is the method slug the caller is characterising: the file states
    which method its category slugs belong to, and asked for a different one this
    returns nothing rather than ruling on categories nobody wrote it about.

    Not cached, because the path is injectable (rule 13): a test hands over a file
    of its own and must not be given the curated one's numbers.

    :raises UnderlyingModelError: on anything malformed, including a category slug
        the crosswalk does not define -- evidence filed under a category this list
        cannot name is evidence nothing will ever compare.
    """
    filepath = path or UNDERLYING_MODEL_FILEPATH
    if not filepath.exists():
        return ()
    payload = orjson.loads(filepath.read_bytes())
    _require(isinstance(payload, dict), f"{filepath.name} is not an object")
    version = payload.get("schema_version")
    _require(
        version == MODEL_SCHEMA_VERSION,
        f"{filepath.name} is schema version {version!r}; this reads "
        f"{MODEL_SCHEMA_VERSION}",
    )
    if out_of_scope(payload, filename=filepath.name, method=method):
        return ()
    block = payload.get("model")
    _require(
        isinstance(block, dict),
        f"{filepath.name} names no model, so its numbers are nobody's",
    )
    assert isinstance(block, dict)
    model = UnderlyingModel(
        name=str(block.get("name") or "").strip(),
        read_from=tuple(str(name) for name in block.get("read_from") or ()),
        sheet=str(block.get("sheet") or "").strip(),
        block=str(block.get("block") or "").strip(),
        measured_on=str(block.get("measured_on") or "").strip(),
    )
    _require(
        bool(model.name and model.read_from),
        f"{filepath.name}: the model states no name, or no file it was read "
        f"from; both are what makes a number in it checkable",
    )
    rows = payload.get("substances")
    _require(isinstance(rows, list), f"{filepath.name} carries no substances list")
    assert isinstance(rows, list)

    stated_method = curated_method(payload, filename=filepath.name)
    slugs = {category.slug for category in lcia_method(stated_method).categories}
    evidence: list[ModelEvidence] = []
    seen: set[tuple[str, str]] = set()
    for position, row in enumerate(rows):
        _require(isinstance(row, dict), f"row {position} is not an object")
        cas = str(row.get("cas_number") or "").strip()
        slug = str(row.get("category_slug") or "").strip()
        _require(
            bool(cas and slug),
            f"row {position} does not name a substance and a category",
        )
        _require(
            slug in slugs,
            f"row {position} states the category {slug!r}, which the method "
            f"{stated_method!r} does not define",
        )
        _require(
            (cas, slug) not in seen,
            f"row {position} states {cas} and {slug} a second time",
        )
        seen.add((cas, slug))
        stated_rows = row.get("stated")
        _require(
            isinstance(stated_rows, list) and bool(stated_rows),
            f"row {position} states no numbers",
        )
        assert isinstance(stated_rows, list)
        amounts: list[ModelAmount] = []
        for entry in stated_rows:
            _require(
                isinstance(entry, dict), f"row {position} holds a malformed amount"
            )
            context_iri = str(entry.get("context_iri") or "").strip()
            _require(
                bool(context_iri),
                f"row {position} states an amount for no compartment; a number "
                f"with nowhere to apply cannot be compared with anything",
            )
            model_amount = _number(
                entry.get("model_amount"), position=position, field="model_amount"
            )
            _require(
                model_amount > 0,
                f"row {position} states {model_amount!r} for the model in "
                f"{context_iri}; a ratio is not defined across zero, and a model "
                f"stating nothing should not have a row",
            )
            amounts.append(
                ModelAmount(
                    compartment=str(entry.get("compartment") or "").strip(),
                    context_iri=context_iri,
                    model_amount=model_amount,
                    reference_amount=_number(
                        entry.get("reference_amount"),
                        position=position,
                        field="reference_amount",
                    ),
                )
            )
        evidence.append(
            ModelEvidence(
                cas_number=cas,
                substance=str(row.get("substance") or "").strip(),
                model_substance=str(row.get("model_substance") or "").strip(),
                method=stated_method,
                category_slug=slug,
                category=str(row.get("category") or "").strip(),
                unit=str(row.get("unit") or "").strip(),
                stated=tuple(amounts),
                model=model,
                comment=str(row.get("comment") or "").strip(),
            )
        )
    logger.info(
        "loaded_underlying_model_factors",
        path=str(filepath),
        model=model.name,
        substances=len(evidence),
        amounts=sum(len(row.stated) for row in evidence),
    )
    return tuple(evidence)


def _slugs_of_group(slug: str, *, method: str) -> tuple[str, ...]:
    """The category the evidence names, and the halves it is split into.

    The model states one number for a substance; EF publishes it twice, under the
    aggregate category and under whichever of the organic and inorganic halves the
    substance falls in, and both spellings carry the same number.  A contradiction
    about `Ecotoxicity, freshwater` that left `Ecotoxicity, freshwater_organics`
    published would withhold half of a question and publish the other half.

    Each slug is still compared on its **own** numbers below -- this widens what is
    looked at, and decides nothing.
    """
    categories = lcia_method(method).categories
    by_name = {category.name: category for category in categories}
    definition = next(
        (category for category in categories if category.slug == slug), None
    )
    if definition is None:  # pragma: no cover - the loader refuses an unknown slug
        return (slug,)
    parts = tuple(
        by_name[part].slug for part in definition.parts if part in by_name
    )
    return (slug, *parts)


def _ratio(published: float, model: float) -> float | None:
    """How far apart two numbers are, or ``None`` where that is not defined.

    A stated zero against a number is not a hundredfold of anything -- it is one
    side saying the substance does nothing -- and a sign change is two models
    disagreeing about the direction of an effect.  Neither is what this measures,
    so both drop out of the comparison rather than counting as agreement.
    """
    if not published or not model or (published > 0) != (model > 0):
        return None
    smallest, largest = sorted((abs(published), abs(model)))
    return largest / smallest


def contradictions(
    evidence: Iterable[ModelEvidence],
    *,
    stated: Mapping[tuple[str, str, str], MatchedFactor],
    flows: Mapping[str, Mapping[str, Any]],
    substances: Mapping[str, list[str]],
) -> dict[tuple[str, str], Contradiction]:
    """Which (substance, category) pairs the model contradicts in this build.

    *stated* is the reference implementation's factors -- the method's own
    publisher's -- keyed the way `consensus.derive` keys them, on (flow, category
    slug, place).  *flows* is `sources.flow_descriptions`, which says which
    substance and compartment a flow is.  *substances* maps a registry number to
    the flow objects carrying it, which is how a file about somebody else's model
    reaches this list's substances: CAS is what both publications key on, and it
    is the join the comparison was made over.

    The rule, applied per category slug and per substance:

    * compare only the categories in :data:`COMPARABLE_CATEGORIES`, where the two
      publications state the same quantity and a ratio between them is a fact
      about the substance rather than about the two models' units;
    * compare only where the build states a number for a compartment the model
      states one for, and only the placeless rows -- the model's numbers are for
      a global average continent, and EF's 180 located toxicity factors are a
      different question;
    * require :data:`MINIMUM_COMPARTMENTS` such comparisons, so a substance
      characterised in one place is never withdrawn on one number;
    * require **every** one of them to exceed :data:`CONTRADICTION_RATIO`.

    A row failing any of those is not a contradiction and is logged rather than
    dropped silently: the file said these numbers were more than a hundredfold
    apart, and a build where they are not is either a re-transcription or a bug,
    and both are worth a line.
    """
    rows_of_evidence = tuple(evidence)
    found: dict[tuple[str, str], Contradiction] = {}
    by_flow: dict[tuple[str, str, str], MatchedFactor] = {}
    for (uuid, slug, geography), matched in stated.items():
        if geography:
            continue
        flow = flows.get(uuid) or {}
        context = str(flow.get("context_iri") or "")
        substance = str(flow.get("flow_object_id") or "")
        if substance and context:
            by_flow[(substance, slug, context)] = matched

    not_comparable = 0
    for row in rows_of_evidence:
        if row.category_slug not in comparable_categories(row.method):
            # Measured, kept, and asked nothing about.  The two publications are
            # not stating one quantity in this category, so the ratio is between
            # two models rather than between a method and the model it cites.
            not_comparable += 1
            continue
        objects = substances.get(row.cas_number) or []
        if not objects:
            logger.warning(
                "underlying_model_substance_not_found",
                cas_number=row.cas_number,
                substance=row.substance,
                model=row.model.name,
            )
            continue
        if len(objects) > 1:
            # Two substances carrying one registry number is #34's question, and
            # it is not answered here.  Both are withheld, because the evidence is
            # about the number the CAS names and this list cannot say which of the
            # two is meant.
            logger.info(
                "underlying_model_substance_is_contested",
                cas_number=row.cas_number,
                substance=row.substance,
                flow_objects=sorted(objects),
            )
        for flow_object_id in sorted(objects):
            for slug in _slugs_of_group(row.category_slug, method=row.method):
                compared: list[Comparison] = []
                unmatched = 0
                for amount in row.stated:
                    matched = by_flow.get(
                        (flow_object_id, slug, amount.context_iri)
                    )
                    if matched is None:
                        unmatched += 1
                        continue
                    ratio = _ratio(matched.factor.amount, amount.model_amount)
                    if ratio is None:
                        unmatched += 1
                        continue
                    compared.append(
                        Comparison(
                            compartment=amount.compartment,
                            context_iri=amount.context_iri,
                            elementary_flow_uuid=matched.elementary_flow_uuid,
                            model_amount=amount.model_amount,
                            published_amount=matched.factor.amount,
                            ratio=ratio,
                        )
                    )
                if len(compared) < MINIMUM_COMPARTMENTS:
                    # A warning where the file's own claim went unmatched, and a
                    # debug line where our widening did.  The group above is both
                    # halves of the category and a substance is in one of them, so
                    # every organic substance misses `..._inorganics` by
                    # construction -- 38 warnings a run for a structural
                    # non-event, which is how a log stops being read.  The named
                    # category is different: the file said this substance is
                    # characterised there, and a build where it is not is either a
                    # re-transcription or a defect.
                    log = (
                        logger.warning
                        if slug == row.category_slug or compared
                        else logger.debug
                    )
                    log(
                        "underlying_model_evidence_unmatched",
                        cas_number=row.cas_number,
                        substance=row.substance,
                        category_slug=slug,
                        compared=len(compared),
                        unmatched=unmatched,
                        required=MINIMUM_COMPARTMENTS,
                    )
                    continue
                narrowest = min(comparison.ratio for comparison in compared)
                if narrowest <= CONTRADICTION_RATIO:
                    logger.warning(
                        "underlying_model_agrees_now",
                        cas_number=row.cas_number,
                        substance=row.substance,
                        category_slug=slug,
                        narrowest_ratio=narrowest,
                        threshold=CONTRADICTION_RATIO,
                    )
                    continue
                found[(flow_object_id, slug)] = Contradiction(
                    flow_object_id=flow_object_id,
                    category_slug=slug,
                    cas_number=row.cas_number,
                    substance=row.substance,
                    category=row.category,
                    model=row.model.name,
                    read_from=row.model.read_from,
                    compared=tuple(compared),
                    comment=row.comment,
                )
    logger.info(
        "underlying_model_contradictions",
        evidence=len(rows_of_evidence),
        not_comparable=not_comparable,
        contradicted=len(found),
        substances=len({key[0] for key in found}),
    )
    return found
