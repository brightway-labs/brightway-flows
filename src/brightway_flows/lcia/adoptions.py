"""A number crossing from one substance to another, signed.

`Copper, Ion` is a substance this list has only because ecoinvent shipped it.
EF 3.1 characterises copper and has no ion flow; ecoinvent gives the ion
copper's numbers; so every factor the ion carries is a number stated *about
another substance*.  Whether that is right is a question about the two
substances -- an ion and its element, a salt and its acid, a named pesticide and
the catch-all bucket its correspondence put it in, a subtype of land and its
family -- and it is not a question a rule can answer by reading the digits: the
same digits carried lindane's number onto its manufacturing contaminants, which
EF's own numbers hold 21 to 34 times apart (#131, #156).

So **no number crosses a substance boundary without a signature.**  This file,
``data/lcia-factor-adoptions.json``, is where the signatures are.  One entry per
recipient substance: the donor whose number it takes, the relationship between
the two in one word, the categories covered, the implementations it is about,
and a verdict -- **adopt** or **decline** -- with a mandatory comment.  A factor
published from an adoption carries ``derivation: adopted``; a declined row stays
on the `proposed-factor` page as a record rather than a question.

**What an adoption can and cannot do.**  It answers a row that *only a
transcription states*: the method's own publisher is silent, nobody disputes
the number, and the question is whether this list publishes it at all.  It
never overwrites a value -- a factor the reference states, or two
implementations agree on, is settled before this file is read, and a row the
same substance already publishes next door is `restated` first.  It never
crosses a wall of the context convention, because it is not about contexts.
And it is scoped to the categories it names: a category arriving later is a new
question rather than an automatic yes.

**Where nobody states the recipient at all, the number is the donor's.**
Stepwise 2006 has one implementation and its export names no zinc ion, so for
`Zinc(2+)` there is no stated row for a signature to answer -- and every
ecoinvent zinc emission lands on the ion (#197).  An entry with ``number_from:
donor`` says the recipient takes the donor's *published* number, context for
context: zinc's water number onto the zinc ion's water flow, zinc's air number
onto its air flow.  That is :mod:`brightway_flows.lcia.donors`, which runs
before the context convention so the ion's own river and forestry-soil flows
then take the number the way the element's do.  The default,
``number_from: transcription``, is the shape above: the amount is always the
transcription's own stated row.  One file per method, because a category slug
is a name inside a method: ``lcia-factor-adoptions.json`` is EF 3.1's and
``lcia-factor-adoptions-stepwise-2006.json`` is Stepwise's.

**Pinned or not, by what the reason is.**  Most entries are about a
relationship and survive a revision of the number: a revised factor for copper
is still copper's factor reaching its ion.  The twenty-three minerals whose
number is the JRC's element factors weighted by the mineral's formula (#155)
record the number in ``adopted_about``, because their reason *is* that
arithmetic, checked against today's element factors -- a row stating another
number asks again, the way a ruling's ``ruled_about`` does.

The relationships are a closed set, so the page can say "the ion takes its
element's number" without a reader opening the file:

==================  ==========================================================
``ion-of``          the recipient is an ion of the donor element
``salt-of``         the recipient is the free compound of the donor salt, or its salt
``conjugate-of``    the recipient is the donor's anion or acid
``catch-all``       the donor is a grouping class -- `Herbicides, Unspecified`
``land-family``     the recipient is a subtype or variant of the donor land class
``formula-weighted`` the number is the JRC's element factors weighted by the formula
``trade-name``      two names for one substance
``substitute``      a relative ecoinvent's implementation stood in for the recipient
``own-number``      nobody's but the transcription's, adopted on a cited source
==================  ==========================================================

The first shape of this file (`lcia-catch-all-factor-approvals.json`, #76,
#155) held the catch-all pesticides and the minerals only, and a rule in
`lcia.consensus` published everything else that matched digits.  Its 85 entries
are the first 85 here; the rule is gone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

import orjson

from brightway_flows.filesystem import PACKAGE_DATA_DIR
from brightway_flows.lcia.scope import out_of_scope

#: The curated file for EF 3.1, and the first of them.
FACTOR_ADOPTIONS_FILEPATH = PACKAGE_DATA_DIR / "lcia-factor-adoptions.json"

#: The curated file for Stepwise 2006: 23 metal ions taking their element's
#: published number where the export names no ion (#197).
STEPWISE_FACTOR_ADOPTIONS_FILEPATH = (
    PACKAGE_DATA_DIR / "lcia-factor-adoptions-stepwise-2006.json"
)

#: Every adoptions file, one per method.  Each states the method it is about
#: and is read for that one (`lcia.scope`).
FACTOR_ADOPTIONS_FILEPATHS: tuple[Path, ...] = (
    FACTOR_ADOPTIONS_FILEPATH,
    STEPWISE_FACTOR_ADOPTIONS_FILEPATH,
)

#: Bumped when the shape changes, and read rather than assumed.  Version 1 was
#: the approvals file; version 2 adds the donor, the relationship and the
#: verdict.
ADOPTIONS_SCHEMA_VERSION = 2


class FactorAdoptionError(ValueError):
    """An adoption that cannot be read as one.

    Raised rather than skipped, for the reason `lcia.rulings` gives: a malformed
    curator decision that is quietly ignored is a decision that looks applied and
    is not.
    """


class Verdict(StrEnum):
    ADOPT = "adopt"
    DECLINE = "decline"


class NumberFrom(StrEnum):
    """Whose number an adopted factor carries."""

    #: The transcription's own stated row, on the recipient.  The default, and
    #: the only shape until #197.
    TRANSCRIPTION = "transcription"
    #: The donor's published factor in the same context, copied onto a
    #: recipient nobody states anything for.
    DONOR = "donor"


class Relationship(StrEnum):
    ION_OF = "ion-of"
    SALT_OF = "salt-of"
    CONJUGATE_OF = "conjugate-of"
    CATCH_ALL = "catch-all"
    LAND_FAMILY = "land-family"
    FORMULA_WEIGHTED = "formula-weighted"
    TRADE_NAME = "trade-name"
    SUBSTITUTE = "substitute"
    OWN_NUMBER = "own-number"


@dataclass(frozen=True)
class Donor:
    """The substance whose number the recipient takes."""

    flow_object_id: str
    substance: str


@dataclass(frozen=True)
class FactorAdoption:
    """One substance whose proposed factors a person accepted or refused, and why."""

    flow_object_id: str
    substance: str
    relationship: Relationship
    verdict: Verdict
    #: The category slugs this covers.  Explicit, so a category a publisher
    #: adds later is a question rather than an automatic yes.
    categories: frozenset[str]
    #: The donor substance, where the number is another substance's; empty for
    #: a catch-all (named in `catch_all`) and for an own number.
    donor: Donor | None = None
    #: The catch-all whose numbers these are, for a reader of the record.
    catch_all: str = ""
    comment: str = ""
    #: Every implementation this was written about.  One name today, and stated
    #: rather than assumed: an adoption of ecoinvent's number is not an adoption
    #: of a third implementation's arriving later.
    implemented_by: frozenset[str] = field(default_factory=frozenset)
    #: The numbers this was made about, keyed by `implemented_by`, where the
    #: adoption is about the numbers.  Empty where the reason is a relationship
    #: that survives a revision; stated for the minerals, whose reason is an
    #: arithmetic checked against today's element factors.  Checked the way a
    #: ruling's `ruled_about` is: exactly, and every implementation the row
    #: hears from.
    adopted_about: dict[str, tuple[float, ...]] = field(default_factory=dict)
    #: Whose number the factor carries: the transcription's stated row, or the
    #: donor's published one where nobody states the recipient (#197).
    number_from: NumberFrom = NumberFrom.TRANSCRIPTION

    @property
    def donor_name(self) -> str:
        return self.donor.substance if self.donor else self.catch_all

    def takes_donor_number(self, *, category_slug: str, speaking: set[str]) -> bool:
        """Whether this entry copies the donor's published number for this
        category, given who stated the donor's row.

        The other route.  An entry answering stated rows never copies, and one
        copying never answers a stated row -- there is none for its recipient.
        """
        return (
            self.number_from is NumberFrom.DONOR
            and category_slug in self.categories
            and speaking == set(self.implemented_by)
        )

    def covers(
        self, *, category_slug: str, speaking: set[str], stated: dict[str, float]
    ) -> bool:
        """Whether this entry answers a row of this category from these lists.

        *stated* is every implementation's amount for the row.  An entry that
        recorded its numbers answers only rows stating one of them; one that did
        not is about the substance and answers whatever number the named
        implementations state.  An entry taking the donor's number answers no
        stated row at all: see :meth:`takes_donor_number`.
        """
        if self.number_from is not NumberFrom.TRANSCRIPTION:
            return False
        if category_slug not in self.categories or speaking != set(self.implemented_by):
            return False
        if not self.adopted_about:
            return True
        return set(stated) == set(self.adopted_about) and all(
            amount in self.adopted_about[implementation]
            for implementation, amount in stated.items()
        )


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise FactorAdoptionError(message)


def load_factor_adoptions(
    path: Path | None = None, *, method: str | None = None
) -> dict[str, FactorAdoption]:
    """The adoptions, keyed on the flow object each is about.

    Not cached, for the reason `load_factor_rulings` is not: the path is
    injectable, and a test's file must not be answered with the curated one.

    *method* is the method slug the caller is characterising: the file states
    which method its category slugs belong to, and asked for a different one this
    returns nothing rather than ruling on categories nobody wrote it about.

    Given no *path*, every registered file is read
    (:data:`FACTOR_ADOPTIONS_FILEPATHS`), each for the method asked for.  Asked
    for no method that is every file at once, which a test of one file's shape
    should not want: a substance signed in two methods' files -- copper's ion
    under EF 3.1 and under Stepwise -- is two entries, and reading both under
    one key raises rather than keeping either.
    """
    if path is not None:
        return _load_one(path, method=method)
    index: dict[str, FactorAdoption] = {}
    for filepath in FACTOR_ADOPTIONS_FILEPATHS:
        for flow_object_id, adoption in _load_one(filepath, method=method).items():
            _require(
                flow_object_id not in index,
                f"{filepath.name} signs {adoption.substance} ({flow_object_id}), "
                f"which another adoptions file also signs; read the files for one "
                f"method at a time",
            )
            index[flow_object_id] = adoption
    return index


def _load_one(filepath: Path, *, method: str | None) -> dict[str, FactorAdoption]:
    """One adoptions file, checked, for the method asked for."""
    if not filepath.exists():
        return {}
    payload = orjson.loads(filepath.read_bytes())
    _require(isinstance(payload, dict), f"{filepath.name} is not an object")
    version = payload.get("schema_version")
    _require(
        version == ADOPTIONS_SCHEMA_VERSION,
        f"{filepath.name} is schema version {version!r}; this reads "
        f"{ADOPTIONS_SCHEMA_VERSION}",
    )
    if out_of_scope(payload, filename=filepath.name, method=method):
        return {}
    rows = payload.get("adoptions")
    _require(isinstance(rows, list), f"{filepath.name} carries no adoptions list")

    index: dict[str, FactorAdoption] = {}
    for position, row in enumerate(rows):
        _require(isinstance(row, dict), f"adoption {position} is not an object")
        flow_object_id = str(row.get("flow_object_id") or "").strip()
        _require(bool(flow_object_id), f"adoption {position} names no flow object")
        categories = row.get("categories")
        _require(
            isinstance(categories, list) and bool(categories),
            f"adoption {position} names no categories",
        )
        implemented_by = row.get("implemented_by")
        _require(
            isinstance(implemented_by, list) and bool(implemented_by),
            f"adoption {position} names no implementation",
        )
        comment = str(row.get("comment") or "").strip()
        _require(
            bool(comment),
            f"adoption {position} carries no comment; see the file's description",
        )
        _require(
            flow_object_id not in index,
            f"adoption {position} is the second for {flow_object_id}",
        )
        try:
            verdict = Verdict(str(row.get("verdict") or ""))
        except ValueError:
            raise FactorAdoptionError(
                f"adoption {position}: verdict must be one of "
                f"{[str(v) for v in Verdict]}, not {row.get('verdict')!r}"
            ) from None
        try:
            relationship = Relationship(str(row.get("relationship") or ""))
        except ValueError:
            raise FactorAdoptionError(
                f"adoption {position}: relationship must be one of "
                f"{[str(r) for r in Relationship]}, not {row.get('relationship')!r}"
            ) from None
        catch_all = str(row.get("catch_all") or "").strip()
        raw_donor = row.get("donor")
        donor = None
        if raw_donor is not None:
            _require(
                isinstance(raw_donor, dict)
                and bool(str(raw_donor.get("flow_object_id") or "").strip()),
                f"adoption {position}: donor must name a flow object",
            )
            donor = Donor(
                flow_object_id=str(raw_donor["flow_object_id"]).strip(),
                substance=str(raw_donor.get("substance") or ""),
            )
            _require(
                donor.flow_object_id != flow_object_id,
                f"adoption {position}: {flow_object_id} cannot be its own donor",
            )
        about = row.get("adopted_about")
        _require(
            about is None or isinstance(about, dict),
            f"adoption {position}: adopted_about must map an implementation to "
            f"a list of numbers",
        )
        adopted_about = {
            str(name): _amounts(values, position=position)
            for name, values in (about or {}).items()
        }
        # Who the number belongs to is what makes an entry reviewable: a donor,
        # a catch-all, or -- for a number that is nobody's but the
        # transcription's -- the numbers themselves, pinned.
        if relationship is Relationship.CATCH_ALL:
            _require(bool(catch_all), f"adoption {position} names no catch-all")
        elif relationship in (Relationship.OWN_NUMBER, Relationship.FORMULA_WEIGHTED):
            _require(
                bool(adopted_about),
                f"adoption {position}: a {relationship} entry records the numbers "
                f"it was made about, or it says only that somebody said yes",
            )
        else:
            _require(donor is not None, f"adoption {position} names no donor")
        _require(
            set(adopted_about) <= {str(name) for name in implemented_by},
            f"adoption {position} records numbers of an implementation it is "
            f"not about: {sorted(set(adopted_about) - set(implemented_by))}",
        )
        try:
            number_from = NumberFrom(
                str(row.get("number_from") or NumberFrom.TRANSCRIPTION)
            )
        except ValueError:
            raise FactorAdoptionError(
                f"adoption {position}: number_from must be one of "
                f"{[str(v) for v in NumberFrom]}, not {row.get('number_from')!r}"
            ) from None
        if number_from is NumberFrom.DONOR:
            # The number is the donor's published factor, so there has to be a
            # donor, and there is no transcription's number to pin.
            _require(
                donor is not None,
                f"adoption {position}: number_from is donor, and no donor is named",
            )
            _require(
                not adopted_about,
                f"adoption {position}: number_from is donor, so the number is "
                f"whatever the donor publishes and `adopted_about` cannot pin it",
            )
        index[flow_object_id] = FactorAdoption(
            flow_object_id=flow_object_id,
            substance=str(row.get("substance") or ""),
            relationship=relationship,
            verdict=verdict,
            categories=frozenset(str(slug) for slug in categories),
            donor=donor,
            catch_all=catch_all,
            comment=comment,
            implemented_by=frozenset(str(name) for name in implemented_by),
            adopted_about=adopted_about,
            number_from=number_from,
        )
    return index


def _amounts(raw: object, *, position: int) -> tuple[float, ...]:
    _require(
        isinstance(raw, list) and bool(raw),
        f"adoption {position}: adopted_about values must be a list of numbers",
    )
    out = []
    for value in raw:  # type: ignore[union-attr]
        _require(
            isinstance(value, (int, float)) and not isinstance(value, bool),
            f"adoption {position}: {value!r} is not a number",
        )
        out.append(float(value))
    return tuple(out)
