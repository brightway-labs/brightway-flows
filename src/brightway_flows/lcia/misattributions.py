"""A factor the method states about the wrong substance, moved to the right one.

`lcia.rulings` answers a question the pipeline asked, and every answer it can give
is a number some implementation already stated for the flow in question.  This is
the case that machinery cannot express, because nothing here is inconsistent as
far as the pipeline can see.

EF 3.1 states an ozone-depletion factor of 0.14 for 1,1,2-trichloroethane.  Both
transcriptions agree, so no queue item is written, so there is nothing for a
ruling to be keyed on -- and no verdict could express it anyway: `publish` names
an implementation whose number to take, and **no implementation states this factor
for 1,1,1-trichloroethane at all**.  What is wrong is not the number but the
substance it is stated against: 1,1,2-trichloroethane is a suspected carcinogen
that depletes no ozone, is in none of the Montreal Protocol's annexes and has no
published ozone-depletion potential, while its isomer is the controlled solvent
the factor describes.  See #126, and #121 for the same split found in the name.

**A move, not an assertion of a number.**  A file saying "publish 0.14 for
1,1,1-trichloroethane" would be this project inventing a characterisation factor,
and would go on saying 0.14 after EF restated it as something else.  What is
actually known is narrower and checkable: *this factor, the one EF states over
there, belongs here*.  So a row names two substances and a category and moves what
it finds, context by context -- the amount, the unit and the geography stay EF's
throughout.

That also bounds it.  A moved factor lands on the destination substance's flow
**in the compartment the source factor was stated for and nowhere else**, so a
move cannot reach a compartment the source never covered, and a row cannot
characterise a substance more widely than the evidence it is borrowing.  Where the
destination has no active flow in that compartment the factor is dropped rather
than relocated, and the drop is counted: publishing an air factor against a soil
flow because that is the only one available would be the move inventing coverage.

**The transcriptions are not touched.**  The JRC's implementation goes on saying
0.14 for 1,1,2-trichloroethane, because that is what the JRC published, and a
reader comparing this list against EF 3.1 has to be able to see the difference
rather than have it quietly reconciled.  Only the consensus implementation moves
the factor, and the row it publishes carries `derivation: moved` so a reader can
tell it from a number nobody disputed.  That is the stance `lcia.contradictions`
already takes about biphenyl (#107).

**A row records what every implementation stated when it was written**, on both
substances, and is not applied when the build states something else.  Borrowed
from `lcia-factor-rulings.json`, which learned it the hard way: a re-transcription
that fixes this at source -- EF restating the factor against the solvent, or
withdrawing it -- undoes the move with nobody editing the file, exactly as a
ruling written about numbers that have moved stops being obeyed.  The guard is
what makes this a claim about a specific published state rather than a standing
instruction.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import orjson
import structlog

from brightway_flows.domain.lcia.crosswalk import MethodImplementation
from brightway_flows.filesystem import PACKAGE_DATA_DIR
from brightway_flows.lcia.consensus import Derivation
from brightway_flows.lcia.scope import out_of_scope

logger = structlog.get_logger(__name__)

MISATTRIBUTED_FACTORS_FILEPATH = PACKAGE_DATA_DIR / "lcia-misattributed-factors.json"

MISATTRIBUTIONS_SCHEMA_VERSION = 1

#: What a moved factor's `derivation` says.  Its own word rather than `ruled`,
#: because a ruling picks between numbers implementations stated for the flow and
#: this states that none of them is about the flow it is on.
MOVED = str(Derivation.MOVED)


class MisattributedFactorError(ValueError):
    """A row that cannot be read as a move.

    Raised rather than skipped, for the same reason `lcia.rulings` raises: a
    malformed curated decision that is quietly ignored is a decision that looks
    applied and is not.
    """


@dataclass(frozen=True)
class MisattributedFactor:
    """One category's factor, stated against one substance and belonging to another."""

    category_slug: str
    #: The substance EF states the factor against, and the one it belongs to.
    #: Flow objects rather than flows, because the claim is about a substance in
    #: every compartment it is published in, the same way a ruling is.
    from_flow_object_id: str
    to_flow_object_id: str
    #: What every implementation stated, when the row was written, about each of
    #: the two substances in this category.  Both halves are required: the whole
    #: argument is that one of them carries the number and the other carries
    #: nothing, and a row that recorded only the first could not notice EF
    #: putting the factor where it belongs.
    stated_about_the_source: dict[str, tuple[float, ...]]
    stated_about_the_destination: dict[str, tuple[float, ...]]
    #: Not optional. This overrules the method's own publisher about which
    #: substance a number describes, and an assertion with no stated reasoning
    #: cannot be re-checked against EF's next release.
    comment: str
    from_substance: str = ""
    to_substance: str = ""
    category: str = ""

    @property
    def key(self) -> tuple[str, str]:
        return (self.category_slug, self.from_flow_object_id)

    def covers(
        self,
        *,
        source: Mapping[str, tuple[float, ...]],
        destination: Mapping[str, tuple[float, ...]],
    ) -> bool:
        """Whether this row was written about what the build now states.

        *source* and *destination* are, per implementation, every amount stated
        for that substance in this category across all of its flows.  Compared as
        sets because one substance has many compartments and the row is about the
        substance: EF states 0.14 in five air compartments and the row records
        `[0.14]`, not the number five.

        Says no in the two ways that matter, and both are the move undoing
        itself.  The destination gaining a number means somebody -- EF, most
        likely -- has put the factor where it belongs, and moving it again would
        be this project asserting a duplicate.  The source stating something the
        row never saw means the number this row is about is not the number that
        is there.
        """
        return _same(source, self.stated_about_the_source) and _same(
            destination, self.stated_about_the_destination
        )


def _same(
    stated: Mapping[str, tuple[float, ...]],
    recorded: Mapping[str, tuple[float, ...]],
) -> bool:
    """Whether the amounts stated now are the amounts the row recorded."""
    if set(stated) != set(recorded):
        return False
    return all(set(stated[key]) == set(recorded[key]) for key in stated)


def load_misattributed_factors(
    path: Path | None = None, *, method: str | None = None
) -> dict[tuple[str, str], MisattributedFactor]:
    """The moves, keyed on the category and the substance the factor is stated on.

    Not cached, because the path is injectable (rule 13): a test hands over a file
    of its own and must not be given another one's decisions.
    
    *method* is the method slug the caller is characterising: the file states
    which method its category slugs belong to, and asked for a different one this
    returns nothing rather than ruling on categories nobody wrote it about.
    """
    filepath = path or MISATTRIBUTED_FACTORS_FILEPATH
    if not filepath.exists():
        return {}
    payload = orjson.loads(filepath.read_bytes())
    _require(isinstance(payload, dict), f"{filepath.name} is not an object")
    version = payload.get("schema_version")
    _require(
        version == MISATTRIBUTIONS_SCHEMA_VERSION,
        f"{filepath.name} is schema version {version!r}; this reads "
        f"{MISATTRIBUTIONS_SCHEMA_VERSION}",
    )
    if out_of_scope(payload, filename=filepath.name, method=method):
        return {}
    rows = payload.get("moves")
    _require(isinstance(rows, list), f"{filepath.name} carries no moves list")

    index: dict[tuple[str, str], MisattributedFactor] = {}
    for position, row in enumerate(rows):
        _require(isinstance(row, dict), f"move {position} is not an object")
        for field in ("category_slug", "from_flow_object_id", "to_flow_object_id"):
            _require(
                bool(str(row.get(field) or "").strip()),
                f"move {position} has no {field!r}",
            )
        _require(
            row["from_flow_object_id"] != row["to_flow_object_id"],
            f"move {position} moves a factor from a substance to itself",
        )
        _require(
            bool(str(row.get("comment") or "").strip()),
            f"move {position} has no comment; a row here overrules the method's "
            f"own publisher about which substance a number describes, and one "
            f"with no stated reasoning cannot be re-checked against EF's next "
            f"release",
        )
        move = MisattributedFactor(
            category_slug=str(row["category_slug"]).strip(),
            from_flow_object_id=str(row["from_flow_object_id"]).strip(),
            to_flow_object_id=str(row["to_flow_object_id"]).strip(),
            stated_about_the_source=_stated(
                row.get("stated_about_the_source"),
                position=position,
                field="stated_about_the_source",
            ),
            stated_about_the_destination=_stated(
                row.get("stated_about_the_destination"),
                position=position,
                field="stated_about_the_destination",
            ),
            comment=str(row["comment"]),
            from_substance=str(row.get("from_substance") or ""),
            to_substance=str(row.get("to_substance") or ""),
            category=str(row.get("category") or ""),
        )
        _require(
            move.key not in index,
            f"move {position} is the second about {move.category_slug!r} on "
            f"{move.from_flow_object_id!r}; one substance and category, one "
            f"decision",
        )
        index[move.key] = move
    return index


def _stated(
    raw: object, *, position: int, field: str
) -> dict[str, tuple[float, ...]]:
    """One side's recorded amounts, per implementation.

    An empty mapping is meaningful and allowed -- it is what "no implementation
    states this factor for that substance" looks like, which is the destination's
    ordinary state and half of what makes the move necessary.  ``None`` is not:
    a row that says nothing about a side could never fail the guard.
    """
    _require(
        isinstance(raw, dict),
        f"move {position}: {field} must be an object of implementation to "
        f"amounts, and is required -- it is what stops the move being applied "
        f"after the numbers move, and a row without it could never fail that "
        f"check",
    )
    out: dict[str, tuple[float, ...]] = {}
    for implementation, amounts in raw.items():  # type: ignore[union-attr]
        _require(
            isinstance(amounts, list),
            f"move {position}: {field}[{implementation!r}] must be a list of "
            f"numbers",
        )
        out[str(implementation)] = tuple(float(amount) for amount in amounts)
    return out


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise MisattributedFactorError(message)


def stated_by_substance(
    stated: Mapping[MethodImplementation, Mapping[tuple[str, str, str], Any]],
    *,
    flows: Mapping[str, Mapping[str, Any]],
) -> dict[tuple[str, str], dict[str, tuple[float, ...]]]:
    """Every amount each implementation states, per substance and category.

    The shape :meth:`MisattributedFactor.covers` asks about.  Keyed on the
    substance rather than the flow for the same reason a ruling is: EF states one
    factor in thirteen compartments and the decision is one decision.

    The inner key is ``implemented_by`` -- the name the curated file writes and
    every other row of this layer carries -- and it is read off the record rather
    than by stringifying it: a curated file names a publisher, not a record.
    """
    out: dict[tuple[str, str], dict[str, list[float]]] = {}
    for implementation, factors in stated.items():
        name = implementation.name
        for (flow_uuid, slug, _geography), matched in factors.items():
            substance = str((flows.get(flow_uuid) or {}).get("flow_object_id") or "")
            if not substance:
                continue
            out.setdefault((slug, substance), {}).setdefault(name, []).append(
                matched.factor.amount
            )
    return {
        key: {name: tuple(amounts) for name, amounts in per.items()}
        for key, per in out.items()
    }


def move_factors(
    published: list[Any],
    *,
    moves: Mapping[tuple[str, str], MisattributedFactor],
    slug_of: Any,
    flows: Mapping[str, Mapping[str, Any]],
    stated: Mapping[tuple[str, str], Mapping[str, tuple[float, ...]]],
) -> tuple[list[Any], dict[str, int]]:
    """*published* with each move applied, and a tally of what each row did.

    *published* is the consensus implementation's factors as
    :func:`~brightway_flows.lcia.consensus.derive` returned them, *slug_of*
    reads a row's category slug, and *stated* is what every implementation says
    per (category, substance) -- :func:`stated_by_substance`.

    A row is applied only where :meth:`MisattributedFactor.covers` holds for both
    substances.  Where it does not the move is skipped whole rather than in part:
    a decision taken about one published state is not a decision about a different
    one, and applying half of it would leave the factor on neither substance.
    """
    if not moves:
        return published, {}

    counts: dict[str, int] = {}
    applicable: dict[tuple[str, str], MisattributedFactor] = {}
    for key, move in moves.items():
        holds = move.covers(
            source=stated.get(move.key, {}),
            destination=stated.get(
                (move.category_slug, move.to_flow_object_id), {}
            ),
        )
        if holds:
            applicable[key] = move
            continue
        counts["not_about_this_build"] = counts.get("not_about_this_build", 0) + 1
        logger.warning(
            "misattributed_factor_not_applied",
            category=move.category_slug,
            substance=move.from_substance or move.from_flow_object_id,
            stated_now=dict(stated.get(move.key, {})),
            recorded=move.stated_about_the_source,
            destination_now=dict(
                stated.get((move.category_slug, move.to_flow_object_id), {})
            ),
        )

    if not applicable:
        return published, counts

    # Where each destination substance publishes a flow, by compartment, so a
    # moved factor can only land in the compartment it came from.  Deprecated
    # flows are skipped: a redirect is not somewhere to publish a number.
    destinations: dict[tuple[str, str], str] = {}
    for uuid, flow in flows.items():
        if flow.get("deprecated"):
            continue
        substance = str(flow.get("flow_object_id") or "")
        context = str(flow.get("context_iri") or "")
        if substance and context:
            destinations.setdefault((substance, context), uuid)

    out: list[Any] = []
    for row in published:
        source = str(
            (flows.get(row.elementary_flow_uuid) or {}).get("flow_object_id") or ""
        )
        move = applicable.get((slug_of(row), source))
        if move is None:
            out.append(row)
            continue
        context = str(
            (flows.get(row.elementary_flow_uuid) or {}).get("context_iri") or ""
        )
        landing = destinations.get((move.to_flow_object_id, context))
        if landing is None:
            # The destination has no active flow in this compartment, so there is
            # nowhere the factor can go that the evidence covers.  Dropped rather
            # than left behind: leaving it would publish the number against the
            # substance this row says it is not about.
            counts["no_flow_in_that_compartment"] = (
                counts.get("no_flow_in_that_compartment", 0) + 1
            )
            logger.warning(
                "misattributed_factor_has_nowhere_to_land",
                category=move.category_slug,
                to=move.to_substance or move.to_flow_object_id,
                context=context,
            )
            continue
        counts["moved"] = counts.get("moved", 0) + 1
        out.append(
            replace(row, elementary_flow_uuid=landing, derivation=MOVED)
        )
    return out, counts
