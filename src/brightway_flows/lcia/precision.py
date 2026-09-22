"""One number, printed to three significant figures in one place and four in another.

AR6 states CFC-11's hundred-year global warming potential twice.  Table 7.15, in
the body of Chapter 7, prints ``6226 ±2297``.  Table 7.SM.7, in the supplementary
material, prints ``6230``.  They are not two assessments; the supplement rounds
the table the chapter states, and the report says so -- 7.SM.7's caption calls
itself the full table and 7.15's caption points at it.

Both of this list's implementations transcribed AR6 faithfully and landed on
different sides of that rounding.  The JRC's EF 3.1 carries 6230; ecoinvent's
implementation of the same method carries 6226.  Where both speak the merge
already resolves it -- the numbers agree inside ``FACTOR_TOLERANCE`` and
``agreed`` keeps the more precise one, the same judgement ``deduplication`` makes
about two rows that turn out to be one flow.  Where only the JRC has a flow, the
rounded number goes out unopposed, and this list ends up publishing 6230 for
CFC-11 released at aircraft cruise height and 6226 for CFC-11 released anywhere
else: one substance, one category, two numbers, and a reader with no way to tell
that they are the same number.

**This file is not a tolerance rule, and it must not become one.**  Measured on
the 2026-08-25 build, 97 (substance, category) groups publish two values that
agree within 2% -- and 93 of them are freshwater ecotoxicity, where the values
differ because the *compartments* differ and both numbers are stated, computed
and correct.  ``Alanycarb`` at 134083 in silvicultural soil and 135091 in
unspecified soil is a model saying two things about two places, not one number
printed twice.  Nothing here can tell those apart; only the documents can.  So a
row is written by hand, cites the two printings, and is applied to one substance
and one category.

**Only the consensus implementation is touched.**  The JRC's implementation goes
on saying 6230, because that is what the JRC published and a reader comparing
this list against EF 3.1 has to see the difference rather than have it quietly
reconciled -- the stance `lcia.misattributions` takes about a moved factor and
`lcia.contradictions` takes about biphenyl.

**A row records what every implementation stated when it was written**, and is
not applied when the build states something else.  Borrowed from
`lcia-factor-rulings.json` and for the same reason: EF restating the factor at
four digits, or at a third value, ends the claim rather than silently outliving
it.

See #342.  Its sibling case is not here and cannot be: sulfur hexafluoride's
two numbers, 25200 and 24300, are not one number printed twice.  AR6 assesses
SF6 with a 3200-year lifetime and prints 25200; ecoinvent's 24300 is that same
radiative efficiency with a lifetime near 1000 years, which reproduces their
GWP-20, GWP-100 and GWP-500 to three significant figures and AR6's do not.  That
is a disagreement about the atmosphere, and it was answered by a ruling.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import orjson
import structlog

from brightway_flows.filesystem import PACKAGE_DATA_DIR
from brightway_flows.lcia.consensus import Derivation
from brightway_flows.lcia.scope import out_of_scope

logger = structlog.get_logger(__name__)

ROUNDED_PRINTINGS_FILEPATH = PACKAGE_DATA_DIR / "lcia-rounded-printings.json"

ROUNDED_PRINTINGS_SCHEMA_VERSION = 1

#: What a refined factor's `derivation` says.  Its own word rather than `agreed`,
#: because nobody agreed with anybody here -- one implementation stated a rounded
#: printing and this list published the precise one its own source states.
REFINED = str(Derivation.REFINED)


class RoundedPrintingError(ValueError):
    """A row that cannot be read as a printing.

    Raised rather than skipped, for the same reason `lcia.rulings` raises: a
    malformed curated decision that is quietly ignored is a decision that looks
    applied and is not.
    """


@dataclass(frozen=True)
class RoundedPrinting:
    """That an implementation's amount is a rounded printing of a stated value."""

    category_slug: str
    flow_object_id: str
    #: Whose transcription carries the rounded number.
    implemented_by: str
    #: The amount that implementation states, and the value the source it
    #: transcribes states.  Exact equality on `prints`, because the whole claim
    #: is about a specific printed number: a row that matched approximately
    #: would rewrite factors it was never written about.
    prints: float
    states: float
    #: Where the precise value is printed, for a reader checking the claim.
    primary_source: str
    #: What every implementation stated about this substance and category when
    #: the row was written.
    stated_about: dict[str, tuple[float, ...]]
    #: Not optional.  This publishes a number one implementation does not state,
    #: on the strength of a document, and an assertion with no stated reasoning
    #: cannot be re-checked against the next release of either.
    comment: str
    substance: str = ""
    category: str = ""

    @property
    def key(self) -> tuple[str, str]:
        return (self.category_slug, self.flow_object_id)

    def covers(self, *, stated: Mapping[str, tuple[float, ...]]) -> bool:
        """Whether this row was written about what the build now states.

        *stated* is, per implementation, every amount stated for this substance
        in this category across all of its flows.  Compared as sets because one
        substance has many compartments and the row is about the substance.

        Three ways this says no, and each ends the claim rather than bending it:
        an implementation states a number the row never saw, one speaks that the
        row never heard from, or one it was written about has gone silent.
        """
        if set(stated) != set(self.stated_about):
            return False
        return all(
            set(amounts) == set(self.stated_about[implementation])
            for implementation, amounts in stated.items()
        )


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RoundedPrintingError(message)


def _amounts(raw: object, *, position: int) -> tuple[float, ...]:
    _require(
        isinstance(raw, list) and all(isinstance(v, (int, float)) for v in raw),
        f"printing {position}: stated_about values must be a list of numbers",
    )
    return tuple(float(value) for value in raw)  # type: ignore[union-attr]


def load_rounded_printings(
    path: Path | None = None, *, method: str | None = None
) -> dict[tuple[str, str], RoundedPrinting]:
    """The curated printings, keyed on (category slug, substance).

    *method* is the method slug the caller is characterising: the file states
    which method its category slugs belong to, and asked for a different one this
    returns nothing rather than ruling on categories nobody wrote it about.

    :raises RoundedPrintingError: on a row that cannot be read as one, on a
        duplicate key, or on a schema version this code does not know.
    """
    source = path or ROUNDED_PRINTINGS_FILEPATH
    if not source.exists():
        return {}
    document = orjson.loads(source.read_bytes())
    version = document.get("schema_version")
    _require(
        version == ROUNDED_PRINTINGS_SCHEMA_VERSION,
        f"{source.name} states schema_version {version!r}; this reads "
        f"{ROUNDED_PRINTINGS_SCHEMA_VERSION}",
    )
    if out_of_scope(document, filename=source.name, method=method):
        return {}
    printings: dict[tuple[str, str], RoundedPrinting] = {}
    for position, row in enumerate(document.get("printings") or (), start=1):
        for field in (
            "category_slug",
            "flow_object_id",
            "implemented_by",
            "primary_source",
            "comment",
        ):
            _require(
                bool(str(row.get(field) or "").strip()),
                f"printing {position}: {field} is required",
            )
        for field in ("prints", "states"):
            _require(
                isinstance(row.get(field), (int, float)),
                f"printing {position}: {field} must be a number",
            )
        _require(
            float(row["prints"]) != float(row["states"]),
            f"printing {position}: prints and states are the same number, so "
            f"there is nothing to refine",
        )
        about = row.get("stated_about")
        _require(
            isinstance(about, dict) and bool(about),
            f"printing {position}: stated_about is required -- it is what stops "
            f"a row being obeyed after the numbers it was written about have "
            f"moved",
        )
        printing = RoundedPrinting(
            category_slug=str(row["category_slug"]),
            flow_object_id=str(row["flow_object_id"]),
            implemented_by=str(row["implemented_by"]),
            prints=float(row["prints"]),
            states=float(row["states"]),
            primary_source=str(row["primary_source"]),
            stated_about={
                str(name): _amounts(values, position=position)
                for name, values in about.items()  # type: ignore[union-attr]
            },
            comment=str(row["comment"]),
            substance=str(row.get("substance") or ""),
            category=str(row.get("category") or ""),
        )
        _require(
            printing.implemented_by in printing.stated_about,
            f"printing {position}: stated_about does not record what "
            f"{printing.implemented_by} stated; it records "
            f"{sorted(printing.stated_about)}",
        )
        _require(
            printing.prints in printing.stated_about[printing.implemented_by],
            f"printing {position}: {printing.implemented_by} is recorded as "
            f"stating {sorted(printing.stated_about[printing.implemented_by])}, "
            f"which does not include the {printing.prints} this row refines",
        )
        _require(
            printing.key not in printings,
            f"printing {position}: {printing.key} is written twice",
        )
        printings[printing.key] = printing
    logger.info(
        "loaded_rounded_printings", path=str(source), printings=len(printings)
    )
    return printings


def refine_factors(
    published: list[Any],
    *,
    printings: Mapping[tuple[str, str], RoundedPrinting],
    slug_of: Any,
    flows: Mapping[str, Mapping[str, Any]],
    stated: Mapping[tuple[str, str], Mapping[str, tuple[float, ...]]],
) -> tuple[list[Any], dict[str, int]]:
    """*published* with each printing applied, and a tally of what each row did.

    *published* is the consensus implementation's factors as
    :func:`~brightway_flows.lcia.consensus.derive` returned them, *slug_of*
    reads a row's category slug, and *stated* is what every implementation says
    per (category, substance) -- :func:`~brightway_flows.lcia.rulings.
    stated_by_substance`.

    Only a row publishing the rounded amount is rewritten.  The compartments
    where both implementations spoke already carry the precise value, as
    ``agreed``, and rewriting those would trade a record of two publishers
    agreeing for a record of this file acting.
    """
    if not printings:
        return published, {}

    counts: dict[str, int] = {}
    applicable: dict[tuple[str, str], RoundedPrinting] = {}
    for key, printing in printings.items():
        if printing.covers(stated=stated.get(key, {})):
            applicable[key] = printing
            continue
        counts["not_about_this_build"] = counts.get("not_about_this_build", 0) + 1
        logger.warning(
            "rounded_printing_not_applied",
            category=printing.category_slug,
            substance=printing.substance or printing.flow_object_id,
            stated_now=dict(stated.get(key, {})),
            recorded=printing.stated_about,
        )

    if not applicable:
        return published, counts

    out: list[Any] = []
    for row in published:
        substance = str(
            (flows.get(row.elementary_flow_uuid) or {}).get("flow_object_id") or ""
        )
        printing = applicable.get((slug_of(row), substance))
        if printing is None or row.factor.amount != printing.prints:
            out.append(row)
            continue
        counts["refined"] = counts.get("refined", 0) + 1
        out.append(
            replace(
                row,
                factor=replace(row.factor, amount=printing.states),
                derivation=REFINED,
            )
        )
    return out, counts
