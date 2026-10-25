"""A curator's answer to two rows of one implementation colliding on one flow.

`lcia.collisions.settle` publishes nothing where two source rows of one
publisher reach one consensus flow and state numbers too far apart to be one
number written twice, because there is no faithful answer between them: the gap
is evidence about the matching.  Usually.  Stepwise 2006 ships `Particulates`
at 0.157 kg PM2.5-eq and `Particulates, unspecified` at 0.536, both read as the
size-unstated total by #153, and the matching is right: neither row states a
cut, and the method scored the two spellings differently because its authors
took "unspecified" to mean PM10.  That is a characterisation choice a curator
can read and answer, and until this file the answer was that the flow carried
nothing.

``data/lcia-factor-collision-rulings.json`` is where the answer is written for
EF 3.1, and ``lcia-factor-collision-rulings-stepwise-2006.json`` for Stepwise.
One ruling names the implementation whose rows collided, the substance, the
category and the compartment the collision is on, the source row whose number
is taken, and -- as every factor ruling does
-- what every colliding row stated when the ruling was made, so a row that
changes its number is a new question rather than an old answer obeyed.  The
finding `settle` would have written is still written, with the ruling on it,
so a reader of the findings sees the collision and its answer in one place.

Keyed on the substance, the category slug and the compartment rather than on
the flow's identifier, for the reason `lcia.rulings` gives: a ruling written
against a uuid is a ruling that expires.  One file per method, because a slug is
a name inside a method; each states its method and is read for that method
alone (`lcia.scope`).

The implementation is part of the key because EF 3.1 has three that ship rows,
and two of them -- GreenDelta and the JRC -- file every category under the same
ILCD identifier.  GreenDelta's two `Chromium III` rows in rural air state 333.75
and 4,292.06 for freshwater ecotoxicity (#445); an answer about those two rows
is not an answer about anything the JRC states.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import orjson
import structlog

from brightway_flows.domain.lcia.crosswalk import lcia_method_by_slug
from brightway_flows.filesystem import PACKAGE_DATA_DIR
from brightway_flows.lcia.scope import curated_method, out_of_scope

logger = structlog.get_logger(__name__)

#: The curated file for EF 3.1.
COLLISION_RULINGS_FILEPATH = PACKAGE_DATA_DIR / "lcia-factor-collision-rulings.json"

#: The curated file for Stepwise 2006: its two numbers for particles of unstated
#: size (#196).
STEPWISE_COLLISION_RULINGS_FILEPATH = (
    PACKAGE_DATA_DIR / "lcia-factor-collision-rulings-stepwise-2006.json"
)

#: Every collision-rulings file, one per method.  Each states the method it is
#: about and is read for that one (`lcia.scope`).
COLLISION_RULINGS_FILEPATHS: tuple[Path, ...] = (
    COLLISION_RULINGS_FILEPATH,
    STEPWISE_COLLISION_RULINGS_FILEPATH,
)

#: Bumped when the shape changes, and read rather than assumed.  Version 2 names
#: the implementation whose rows collided (#444).
COLLISION_RULINGS_SCHEMA_VERSION = 2


class CollisionRulingError(ValueError):
    """A ruling that cannot be read as one.

    Raised rather than skipped: a curator's decision that looks applied and is
    not is the failure every decisions file in this project is written to avoid.
    """


@dataclass(frozen=True)
class CollisionRuling:
    """One curator's answer to one collision."""

    method: str
    #: The implementation whose rows collided, as every finding spells it:
    #: ``GreenDelta``, ``European Commission — JRC``.
    implemented_by: str
    flow_object_id: str
    category_slug: str
    context_iri: str
    #: The source row whose number is published.
    publish_source_flow_uuid: str
    #: What every colliding row stated when the ruling was made, keyed by the
    #: source row's uuid.  Required, and checked exactly: a row stating
    #: something else is not what this ruling was about.
    ruled_about: dict[str, float] = field(default_factory=dict)
    comment: str = ""
    #: The names, for a reader of the file.  Not the key.
    substance: str = ""
    category: str = ""
    context: str = ""

    @property
    def key(self) -> tuple[str, str, str, str]:
        """What this ruling answers: one implementation's rows of a substance,
        in a category and a place."""
        return (
            self.implemented_by,
            self.flow_object_id,
            self.category_slug,
            self.context_iri,
        )

    def covers(self, *, stated: dict[str, float]) -> bool:
        """Whether this ruling was made about exactly these rows and numbers."""
        if set(stated) != set(self.ruled_about):
            return False
        return all(
            stated[source_uuid] == amount for source_uuid, amount in self.ruled_about.items()
        )


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise CollisionRulingError(message)


def load_collision_rulings(
    path: Path | None = None, *, method: str | None = None
) -> dict[tuple[str, str, str, str], CollisionRuling]:
    """The rulings, keyed on the question each answers.

    Not cached, because the path is injectable: a test hands over a file of its
    own and must not be given another one's answers.  *method* is the method
    slug the caller is characterising; asked for a different one a file returns
    nothing rather than ruling on categories nobody wrote it about.

    Given no *path*, every registered file is read
    (:data:`COLLISION_RULINGS_FILEPATHS`), each for the method asked for.  The
    key carries no method, so asked for none, two files answering one question
    raise rather than either being kept.
    """
    if path is not None:
        return _load_one(path, method=method)
    index: dict[tuple[str, str, str, str], CollisionRuling] = {}
    for filepath in COLLISION_RULINGS_FILEPATHS:
        for key, ruling in _load_one(filepath, method=method).items():
            _require(
                key not in index,
                f"{filepath.name} answers {key}, which another collision-rulings "
                f"file also answers; read the files for one method at a time",
            )
            index[key] = ruling
    return index


def _load_one(
    filepath: Path, *, method: str | None
) -> dict[tuple[str, str, str, str], CollisionRuling]:
    """One collision-rulings file, checked, for the method asked for."""
    if not filepath.exists():
        return {}
    payload = orjson.loads(filepath.read_bytes())
    _require(isinstance(payload, dict), f"{filepath.name} is not an object")
    version = payload.get("schema_version")
    _require(
        version == COLLISION_RULINGS_SCHEMA_VERSION,
        f"{filepath.name} is schema version {version!r}; this reads "
        f"{COLLISION_RULINGS_SCHEMA_VERSION}",
    )
    if out_of_scope(payload, filename=filepath.name, method=method):
        return {}
    stated_method = curated_method(payload, filename=filepath.name)
    definition = lcia_method_by_slug()[stated_method]
    # Who can collide: an implementation somebody else wrote.  Ours derives its
    # numbers and has no source rows to collide.
    implementations = {
        implementation.name: implementation
        for implementation in definition.transcriptions
    }
    categories = {category.slug: category for category in definition.categories}
    rows = payload.get("rulings")
    _require(isinstance(rows, list), f"{filepath.name} carries no rulings list")
    index: dict[tuple[str, str, str, str], CollisionRuling] = {}
    for position, row in enumerate(rows):
        _require(isinstance(row, dict), f"ruling {position} is not an object")
        about = row.get("ruled_about")
        _require(
            isinstance(about, dict) and len(about) >= 2,
            f"ruling {position} must say what every colliding row stated, at "
            "least two of them; `ruled_about` is what stops a ruling being "
            "obeyed after the numbers move",
        )
        ruled_about: dict[str, float] = {}
        for source_uuid, amount in about.items():  # type: ignore[union-attr]
            _require(
                isinstance(amount, (int, float)) and not isinstance(amount, bool),
                f"ruling {position}: {amount!r} is not a number",
            )
            ruled_about[str(source_uuid)] = float(amount)
        ruling = CollisionRuling(
            method=stated_method,
            implemented_by=str(row.get("implemented_by") or "").strip(),
            flow_object_id=str(row.get("flow_object_id") or "").strip(),
            category_slug=str(row.get("category_slug") or "").strip(),
            context_iri=str(row.get("context_iri") or "").strip(),
            publish_source_flow_uuid=str(row.get("publish_source_flow_uuid") or "").strip(),
            ruled_about=ruled_about,
            comment=str(row.get("comment") or "").strip(),
            substance=str(row.get("substance") or "").strip(),
            category=str(row.get("category") or "").strip(),
            context=str(row.get("context") or "").strip(),
        )
        _require(
            all(ruling.key),
            f"ruling {position} does not name an implementation, a substance, a "
            "category and a place",
        )
        # Checked here rather than left to match nothing: a ruling naming an
        # implementation or a category the method does not have is a ruling
        # that looks applied and is not (rule 14).
        implementation = implementations.get(ruling.implemented_by)
        _require(
            implementation is not None,
            f"ruling {position} is about {ruling.implemented_by!r}, and the "
            f"implementations of {stated_method} that state rows are "
            f"{sorted(implementations)}",
        )
        category = categories.get(ruling.category_slug)
        _require(
            category is not None
            and category.stated_by(implementation.slug) is not None,  # type: ignore[union-attr]
            f"ruling {position} names the category {ruling.category_slug!r}, "
            f"which {ruling.implemented_by} does not state in {stated_method}",
        )
        _require(
            ruling.publish_source_flow_uuid in ruling.ruled_about,
            f"ruling {position} publishes {ruling.publish_source_flow_uuid!r}, "
            f"which is not among the rows it was made about: {sorted(ruling.ruled_about)}",
        )
        _require(
            ruling.comment != "",
            f"ruling {position} carries no comment; a ruling about somebody "
            "else's science is unreviewable without one",
        )
        _require(
            ruling.key not in index,
            f"ruling {position} answers {ruling.key} a second time",
        )
        index[ruling.key] = ruling
    logger.info(
        "loaded_collision_rulings", path=str(filepath), rulings=len(index)
    )
    return index
