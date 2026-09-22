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

``data/lcia-factor-collision-rulings.json`` is where the answer is written.
One ruling names the substance, the category and the compartment the collision
is on, the source row whose number is taken, and -- as every factor ruling does
-- what every colliding row stated when the ruling was made, so a row that
changes its number is a new question rather than an old answer obeyed.  The
finding `settle` would have written is still written, with the ruling on it,
so a reader of the findings sees the collision and its answer in one place.

Keyed on the substance, the category slug and the compartment rather than on
the flow's identifier, for the reason `lcia.rulings` gives: a ruling written
against a uuid is a ruling that expires.  The file states the method its slugs
belong to, and is read for that method alone (`lcia.scope`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import orjson
import structlog

from brightway_flows.filesystem import PACKAGE_DATA_DIR
from brightway_flows.lcia.scope import curated_method, out_of_scope

logger = structlog.get_logger(__name__)

#: The curated file.
COLLISION_RULINGS_FILEPATH = PACKAGE_DATA_DIR / "lcia-factor-collision-rulings.json"

#: Bumped when the shape changes, and read rather than assumed.
COLLISION_RULINGS_SCHEMA_VERSION = 1


class CollisionRulingError(ValueError):
    """A ruling that cannot be read as one.

    Raised rather than skipped: a curator's decision that looks applied and is
    not is the failure every decisions file in this project is written to avoid.
    """


@dataclass(frozen=True)
class CollisionRuling:
    """One curator's answer to one collision."""

    method: str
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
    def key(self) -> tuple[str, str, str]:
        """What this ruling answers: a substance, a category and a place."""
        return (self.flow_object_id, self.category_slug, self.context_iri)

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
) -> dict[tuple[str, str, str], CollisionRuling]:
    """The rulings, keyed on the question each answers.

    Not cached, because the path is injectable: a test hands over a file of its
    own and must not be given another one's answers.  *method* is the method
    slug the caller is characterising; asked for a different one this returns
    nothing rather than ruling on categories nobody wrote it about.
    """
    filepath = path or COLLISION_RULINGS_FILEPATH
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
    rows = payload.get("rulings")
    _require(isinstance(rows, list), f"{filepath.name} carries no rulings list")
    index: dict[tuple[str, str, str], CollisionRuling] = {}
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
            f"ruling {position} does not name a substance, a category and a place",
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
