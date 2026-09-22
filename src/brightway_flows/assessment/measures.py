"""What this build counts, in numbers that mean the same thing every run.

A measure is a name, an integer, and a direction.  The name is stable across
builds so a baseline can be diffed against it; the direction says whether the
number going up is progress, so a diff can be read without knowing what each
counter means.

Three sources, in increasing order of how much code they cost:

1. **`run_stats`**, folded in wholesale under `stats.<stage>.<key>`.  The
   pipeline already counts a hundred-odd things about its own work and writes
   them to that table precisely so the question can be asked run over run.
   Restating any of them here would create two numbers that can disagree.

2. **The merge**, per source list, from `merge_outcomes`.  These are not in
   `run_stats` -- the merge writes outcomes, not counters -- and they are the
   headline: how much of a vendor list lands, and on what.

3. **The published shape**: flows, substances, deprecations, characterisation
   coverage, and the length of every review queue.  A review queue is a work
   list for a human, so its length is a progress measure like any other.

4. **`lcia_runs.stats_json`**, folded in under `factors.<key>` for the same
   reason `run_stats` is folded in under `stats.<stage>.<key>`: `characterise`
   already counts what it did, and a second count here could disagree with it.
   These are absent from a build nothing has characterised, which is a fact about
   the build rather than a zero.

**On `direction`.**  Only where it is unambiguous.  `unmatched` going down is
progress; `created` going down is not necessarily -- a genuinely new substance
*should* mint a flow -- so it is `neutral` and the judgement is left to an
expectation, which can say what should happen to a named row rather than to a
population.  A neutral measure still gets its delta reported; it just is not
labelled improved or regressed.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

import orjson
import structlog

from brightway_flows.domain.composition import contradicts_name
from brightway_flows.domain.elementary_flow import minted_elementary_flow_id
from brightway_flows.domain.labels import flow_label_value
from brightway_flows.domain.preferred_label_decisions import decision_key
from brightway_flows.domain.vocabulary import CHEMROF_MOLECULAR_FORMULA
from brightway_flows.pipeline.review_records import ReviewQueue
from brightway_flows.pipeline.sqlite import merge_object_payload
from brightway_flows.sources import known_source_lists

if TYPE_CHECKING:  # `lookup` is imported lazily below, never at module scope.
    from brightway_flows.lookup.matcher import FlowMatcher
    from brightway_flows.lookup.recorded import RecordedDecisions

logger = structlog.get_logger(__name__)


class Direction(StrEnum):
    """Which way is better."""

    LOWER = "lower"
    HIGHER = "higher"
    NEUTRAL = "neutral"


@dataclass(frozen=True)
class MeasureValue:
    """One counted thing about the build."""

    key: str
    value: int
    title: str
    direction: Direction = Direction.NEUTRAL
    #: Which section of the report it belongs to.
    group: str = "build"


# ---------------------------------------------------------------------------
# Reading the run
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RunIdentity:
    """Which build the numbers came from.

    Recorded beside a baseline so that "these are the numbers" is always "these
    are the numbers *from this run*".  The merge tables keep every run they have
    ever seen -- they are `CREATE TABLE IF NOT EXISTS` and are not dropped --
    so the run has to be chosen, not assumed.
    """

    pipeline_run_id: str = ""
    merge_run_id: str = ""
    timestamp: str = ""
    merge_finished_at: str = ""
    max_flows: int | None = None
    sources: tuple[str, ...] = ()
    #: The lists whose merge was bounded by `build --max-rows`, as
    #: `key: rows merged of rows shipped`.  The other half of `max_flows`: a
    #: run can be a prefix of the base list, a prefix of each source list, or
    #: both, and a measure taken from either is a measure of a sample.
    bounded_sources: tuple[str, ...] = ()


def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ?",
        (name,),
    ).fetchone() is not None


def _column_exists(connection: sqlite3.Connection, table: str, column: str) -> bool:
    """Whether *table* carries *column*.

    A measure that reads a column rather than counting rows needs this as well
    as `_table_exists`: the report is run against fixtures that build only the
    columns their own question needs, and a real build's schema is not what
    every caller has.
    """
    return any(
        row[1] == column
        for row in connection.execute(f"PRAGMA table_info({table})")
    )


def latest_merge_run(connection: sqlite3.Connection) -> str:
    """The most recently started merge run, or `""` if none has run.

    Ordered by `started_at` rather than taking the last row, because rows are
    keyed on a random `run_id` and SQLite's physical order is not a promise.

    A database with no merge tables at all returns the same empty string as one
    with no merge rows.  Both mean "nothing merged here", and a caller that has
    to distinguish a missing table from an empty one before it can ask the
    question would push that check into every call site.
    """
    if not _table_exists(connection, "merge_runs"):
        return ""
    row = connection.execute(
        "SELECT run_id FROM merge_runs ORDER BY started_at DESC, run_id DESC LIMIT 1"
    ).fetchone()
    return str(row[0]) if row else ""


def _column_exists(connection: sqlite3.Connection, table: str, column: str) -> bool:
    """Does *table* have *column* yet?

    The merge tables are `CREATE TABLE IF NOT EXISTS` and outlive the run that
    wrote them, so a database built before a column existed still answers
    questions here.  `create_merge_tables` adds the column when a merge next
    runs; until then this reports what is actually there.
    """
    return any(
        row[1] == column for row in connection.execute(f"PRAGMA table_info({table})")
    )


def run_identity(connection: sqlite3.Connection) -> RunIdentity:
    """Name the build these measures describe."""
    merge_run_id = latest_merge_run(connection)
    pipeline = (
        connection.execute(
            "SELECT run_id, timestamp, max_flows FROM pipeline_runs LIMIT 1"
        ).fetchone()
        if _table_exists(connection, "pipeline_runs")
        else None
    )
    finished = ""
    if merge_run_id:
        row = connection.execute(
            "SELECT finished_at FROM merge_runs WHERE run_id = ?", (merge_run_id,)
        ).fetchone()
        finished = str(row[0] or "") if row else ""
    sources = (
        tuple(
            f"{name}-{version}"
            for name, version in connection.execute(
                "SELECT list_name, list_version FROM merge_run_inputs WHERE run_id = ? "
                "ORDER BY sequence",
                (merge_run_id,),
            )
        )
        if merge_run_id and _table_exists(connection, "merge_run_inputs")
        else ()
    )
    bounded_sources = (
        tuple(
            f"{name}-{version}: {merged} of {available} rows"
            for name, version, merged, available in connection.execute(
                "SELECT list_name, list_version, row_count, available_row_count "
                "FROM merge_run_inputs WHERE run_id = ? AND max_rows IS NOT NULL "
                "ORDER BY sequence",
                (merge_run_id,),
            )
        )
        if merge_run_id
        and _table_exists(connection, "merge_run_inputs")
        and _column_exists(connection, "merge_run_inputs", "max_rows")
        else ()
    )
    return RunIdentity(
        pipeline_run_id=str(pipeline[0]) if pipeline else "",
        merge_run_id=merge_run_id,
        timestamp=str(pipeline[1]) if pipeline else "",
        merge_finished_at=finished,
        max_flows=pipeline[2] if pipeline else None,
        sources=sources,
        bounded_sources=bounded_sources,
    )


def _scalar(connection: sqlite3.Connection, sql: str, parameters: tuple = ()) -> int:
    row = connection.execute(sql, parameters).fetchone()
    return int(row[0] or 0) if row else 0


# ---------------------------------------------------------------------------
# The measures
# ---------------------------------------------------------------------------

def collect_measures(
    connection: sqlite3.Connection, *, db_path: Path | None = None
) -> dict[str, MeasureValue]:
    """Every measure this build supports, keyed by name.

    A missing table yields no measures rather than an error: a database built
    before a table existed is still worth assessing on the parts it does have,
    and the baseline comparison reports a measure that has gone away.

    *db_path* enables the `lookup.*` measures, which cannot be taken from a
    connection: they replay every recorded row through `FlowMatcher`, which opens
    the database itself.  Optional, so a caller that only wants the counted
    measures does not pay for the replay.
    """
    measures: dict[str, MeasureValue] = {}
    for measure in (
        *_published_measures(connection),
        *_curated_name_measures(connection),
        *_merge_measures(connection),
        *_unit_crossing_measures(connection),
        *_queue_measures(connection),
        *_run_stat_measures(connection),
        *_factor_measures(connection),
        *_score_measures(connection),
        *(_lookup_measures(db_path) if db_path is not None else ()),
    ):
        measures[measure.key] = measure
    return measures


#: What each replay bucket is called in a report, and which way is better.
#:
#: `evidence` is the only bucket whose agreement is a claim about correctness --
#: those rows matched on something a query carries, so the lookup had what the
#: build had. The curated buckets are reported because the number is worth
#: knowing, and neutral because a curator's decision the algorithm does not
#: reproduce is what a correspondence table is *for*.
_LOOKUP_BUCKET_TITLES: tuple[tuple[str, str, Direction], ...] = (
    ("evidence", "matched on evidence the query carries", Direction.HIGHER),
    ("material", "placed by a curated water material", Direction.NEUTRAL),
    ("land_class", "placed by a curated land class", Direction.NEUTRAL),
    ("prepared", "decided by a correspondence table", Direction.NEUTRAL),
    ("prepared-mapping", "mapped by a correspondence table", Direction.NEUTRAL),
    ("created", "given a flow the merge created", Direction.HIGHER),
)


def _lookup_measures(db_path: Path) -> list[MeasureValue]:
    """How much of this build the lookup API reproduces without running one.

    Every row the merge decided, asked again through `FlowMatcher` and counted
    by how the merge decided it.  Roughly twelve seconds against a three-list
    build, which is why it is opt-in rather than part of the connection-only
    set.

    `lookup.evidence.other_flow` is the one to watch and the reason these are
    measured at all: it counts rows the lookup places on a flow the build did
    not choose, and it should be nothing.  Where the lookup differs it should
    decline, because a wrong match is silent and an unmatched row is reviewable.

    Yields nothing rather than raising for a build the lookup refuses -- a
    bounded run, or one still being written -- for the reason a missing table
    yields nothing: the rest of the assessment is still worth having.
    """
    # Imported here rather than at module scope: `assess` is run against builds
    # this measure cannot read, and a module-level import would make the whole
    # assessment depend on the lookup being importable.
    from brightway_flows.lookup.index import UnusableBuildError
    from brightway_flows.lookup.matcher import FlowMatcher
    from brightway_flows.lookup.replay import replay

    try:
        # One matcher for both replays: building it reads the whole index and
        # parses the PubChem cache, which is the cost here, and the two ask the
        # same build the same kind of question.
        matcher = FlowMatcher.from_results(db_path)
        result = replay(db_path, matcher=matcher)
    except (UnusableBuildError, FileNotFoundError) as error:
        logger.info("lookup_measures_skipped", reason=str(error))
        return []
    if not result.rows:
        return []

    out: list[MeasureValue] = [
        MeasureValue(
            "lookup.rows",
            result.rows,
            "lookup: recorded source rows replayed",
            Direction.NEUTRAL,
            "lookup",
        ),
        MeasureValue(
            "lookup.same_flow",
            result.same_target,
            "lookup: rows reaching the flow the build chose",
            Direction.HIGHER,
            "lookup",
        ),
    ]
    for bucket, phrase, direction in _LOOKUP_BUCKET_TITLES:
        tally = result.tallies.get(bucket)
        if tally is None or not tally.rows:
            continue
        key = f"lookup.{bucket}"
        out.append(MeasureValue(
            f"{key}.rows", tally.rows, f"lookup: rows {phrase}", Direction.NEUTRAL, "lookup"
        ))
        out.append(MeasureValue(
            f"{key}.same_flow",
            tally.same_target,
            f"lookup: rows {phrase}, reaching the same flow",
            direction,
            "lookup",
        ))
        out.append(MeasureValue(
            f"{key}.other_flow",
            tally.other_target,
            f"lookup: rows {phrase}, reaching a different flow",
            Direction.LOWER,
            "lookup",
        ))
        out.append(MeasureValue(
            f"{key}.declined",
            tally.unmatched,
            f"lookup: rows {phrase}, which the lookup declined to place",
            Direction.LOWER,
            "lookup",
        ))
    out.extend(_shipped_name_measures(db_path, matcher=matcher))
    out.extend(_recorded_name_measures(matcher.recorded_decisions))
    return out


def _recorded_name_measures(decisions: RecordedDecisions) -> list[MeasureValue]:
    """The shape of the recorded-by-name index (#357, #359).

    Three counts over the ``(name, resolved context)`` keys the opt-in tier
    answers from: how many hold one recorded flow, how many hold two -- the
    genuine disagreements, which decline -- and how many of those a caller's
    ``source_label`` could settle because some merged list is unanimous there.
    The first is what #357 recovered by resolving the compartment out of the
    key; the gap between the last two is the residue nothing arbitrates.  A
    fourth counts the stored decisions whose place the build never wrote down
    and the index had to re-derive -- zero once #361's field is in the build.
    *decisions* is the enclosing matcher's own copy, so the index is built at
    most once per assessment.
    """
    try:
        counts = (
            decisions.context_keys,
            decisions.conflicted_context_keys,
            decisions.arbitrable_context_keys,
            decisions.resolved_without_recorded_context,
        )
    except sqlite3.OperationalError as error:  # a build without the tables
        logger.info("recorded_name_measures_skipped", reason=str(error))
        return []
    if not any(counts):
        return []
    return [
        MeasureValue(
            "lookup.recorded_name.context_keys",
            counts[0],
            "lookup: recorded name-and-place keys holding one flow",
            Direction.HIGHER,
            "lookup",
        ),
        MeasureValue(
            "lookup.recorded_name.conflicted_context_keys",
            counts[1],
            "lookup: recorded name-and-place keys two lists disagree about",
            Direction.NEUTRAL,
            "lookup",
        ),
        MeasureValue(
            "lookup.recorded_name.arbitrable_context_keys",
            counts[2],
            "lookup: disagreements a caller's source_label could settle",
            Direction.NEUTRAL,
            "lookup",
        ),
        MeasureValue(
            "lookup.recorded_name.resolved_without_recorded_context",
            counts[3],
            "lookup: stored decisions whose place had to be re-derived",
            Direction.LOWER,
            "lookup",
        ),
    ]


def _shipped_name_measures(
    db_path: Path, *, matcher: "FlowMatcher"
) -> list[MeasureValue]:
    """What a SimaPro-shaped list's *own* spellings reach (#328).

    The measures above replay the name `merge_outcomes` recorded, which is the
    name matching saw -- and for a SimaPro-shaped list a build has already taken
    the unit and the place out of it.  So none of them can see whether a caller
    holding the vendor's file gets an answer, which is the thing the lookup
    exists for.  These ask under the shipped name instead.

    `elsewhere` is the one to watch and is a bound of zero: preparation puts the
    rewritten name *in front of* the caller's rather than instead of it, so it
    can add a way for a row to match and must not be able to move one.

    Yields nothing where the vendor's file is not on disk, which an `assess` run
    against somebody else's build need not have.
    """
    from brightway_flows.lookup.index import UnusableBuildError
    from brightway_flows.lookup.replay import replay_shipped_names

    try:
        results = replay_shipped_names(db_path, matcher=matcher)
    except (UnusableBuildError, FileNotFoundError) as error:
        logger.info("lookup_shipped_measures_skipped", reason=str(error))
        return []

    out: list[MeasureValue] = []
    for result in results:
        key = f"lookup.shipped.{result.list_key}"
        out.append(MeasureValue(
            f"{key}.rewritten",
            result.rewritten,
            f"lookup: {result.list_key} rows whose shipped name carries a unit or a place",
            Direction.NEUTRAL,
            "lookup",
        ))
        out.append(MeasureValue(
            f"{key}.placed",
            result.placed,
            f"lookup: {result.list_key} rows that reach the build's flow "
            "under the name the vendor wrote",
            Direction.HIGHER,
            "lookup",
        ))
        out.append(MeasureValue(
            f"{key}.elsewhere",
            result.elsewhere,
            f"lookup: {result.list_key} rows preparation moved to a different flow",
            Direction.LOWER,
            "lookup",
        ))
    return out


def _label_disagreements(connection: sqlite3.Connection) -> int | None:
    """Live flows whose published name differs from their substance's.

    The comparison the #7 measurement used: the flow's own label, read the
    way the export reads it, against `flow_objects.pref_label_value`, folded
    the way label rulings fold names -- so a case or punctuation variant does
    not count, and a different name does.  `None` on a database without the
    tables, which `assess` reads as "not in this build" rather than as zero.
    """
    if not _table_exists(connection, "flow_objects"):
        return None
    has_payloads = _table_exists(connection, "flow_object_payloads")
    labels = {
        str(object_id): str(value or "").strip()
        for object_id, value in connection.execute(
            "SELECT flow_object_id, pref_label_value FROM flow_objects"
        )
    }
    query = (
        "SELECT ef.flow_object_id, ef.flow_json, p.payload_json "
        "FROM elementary_flows ef "
        "LEFT JOIN flow_object_payloads p ON p.flow_object_id = ef.flow_object_id "
        "WHERE ef.is_deprecated = 0 AND ef.flow_json IS NOT NULL"
        if has_payloads
        else
        "SELECT ef.flow_object_id, ef.flow_json, NULL "
        "FROM elementary_flows ef "
        "WHERE ef.is_deprecated = 0 AND ef.flow_json IS NOT NULL"
    )
    count = 0
    for object_id, flow_json, payload_json in connection.execute(query):
        target = labels.get(str(object_id or ""), "")
        if not target:
            continue
        flow = merge_object_payload(orjson.loads(flow_json), payload_json)
        current = flow_label_value(flow).strip()
        if not current:
            continue
        key = decision_key(current, target)
        if key[0] != key[1]:
            count += 1
    return count


def _minted_identifiers_not_from_the_flow(
    connection: sqlite3.Connection,
) -> int | None:
    """Flows the merge added whose identifier is not what the flow produces.

    A flow this project mints is named by its substance and its compartment
    (#102).  Until then it was named by whichever source row reached the
    compartment first, so every one of the 2,561 in the build of 805e72f
    counted here.  Base-list flows are not counted: their identifiers are EF
    3.1's own, this project does not mint them, and moving one would be a
    different and worse bug.
    """
    if not _table_exists(connection, "elementary_flows"):
        return None
    if not all(
        _column_exists(connection, "elementary_flows", column)
        for column in ("source", "flow_object_id", "context_iri")
    ):
        # A fixture, or a build from before a column existed.  `None` reads as
        # "not in this build" rather than as a clean zero, which is what an
        # unanswerable question is.
        return None
    minted = {
        source
        for entry in known_source_lists().values()
        for source in entry.addition_sources
    }
    if not minted:
        return 0
    placeholders = ", ".join("?" * len(minted))
    count = 0
    for identifier, object_id, context_iri in connection.execute(
        f"SELECT uuid, flow_object_id, context_iri FROM elementary_flows "
        f"WHERE source IN ({placeholders})",
        sorted(minted),
    ):
        expected = minted_elementary_flow_id(
            str(object_id or ""), str(context_iri or "")
        )
        if str(identifier or "") != expected:
            count += 1
    return count


def _published_measures(connection: sqlite3.Connection) -> list[MeasureValue]:
    if not _table_exists(connection, "elementary_flows"):
        return []
    active = "is_deprecated = 0"
    out = [
        MeasureValue(
            "flows.total", _scalar(connection, "SELECT count(*) FROM elementary_flows"),
            "Elementary flows", Direction.NEUTRAL, "published",
        ),
        MeasureValue(
            "flows.deprecated",
            _scalar(connection, "SELECT count(*) FROM elementary_flows WHERE is_deprecated = 1"),
            "Flows deprecated", Direction.NEUTRAL, "published",
        ),
        # A deprecation with nowhere to send its consumer is a hole in the
        # published list, which is unambiguous, unlike deprecation itself.
        MeasureValue(
            "flows.deprecated_without_replacement",
            _scalar(
                connection,
                "SELECT count(*) FROM elementary_flows WHERE is_deprecated = 1 "
                "AND coalesce(replaced_by_uuid, '') = ''",
            ),
            "Deprecated with no replacement", Direction.LOWER, "published",
        ),
        MeasureValue(
            "flows.characterised",
            _scalar(
                connection,
                f"SELECT count(*) FROM elementary_flows WHERE {active} AND lcia_factor_count > 0",
            ),
            "Active flows carrying a factor", Direction.HIGHER, "published",
        ),
        MeasureValue(
            "flows.uncharacterised",
            _scalar(
                connection,
                f"SELECT count(*) FROM elementary_flows WHERE {active} AND lcia_factor_count = 0",
            ),
            "Active flows carrying none", Direction.NEUTRAL, "published",
        ),
        MeasureValue(
            "flows.without_substance",
            _scalar(
                connection,
                "SELECT count(*) FROM elementary_flows WHERE coalesce(flow_object_id, '') = ''",
            ),
            "Flows with no substance", Direction.LOWER, "published",
        ),
    ]
    misnamed = _minted_identifiers_not_from_the_flow(connection)
    if misnamed is not None:
        out.append(MeasureValue(
            "flows.minted_identifier_not_from_the_flow",
            misnamed,
            "Minted flows not named after their substance and compartment",
            Direction.LOWER, "published",
        ))
    disagreeing = _label_disagreements(connection)
    if disagreeing is not None:
        # Read off the published payloads rather than restated from the pass
        # that repairs it, so a label writer added after `substance_label_v1`
        # shows up here instead of in the next export diff (#7).  Non-zero is
        # not automatically wrong: a flow in the `substance-label-conflict`
        # queue keeps its own name until a curator rules, and is counted.
        out.append(MeasureValue(
            "flows.label_disagrees_with_substance",
            disagreeing,
            "Flows whose published name is not their substance's",
            Direction.LOWER, "published",
        ))
    if _table_exists(connection, "flow_objects"):
        out.append(MeasureValue(
            "substances.total",
            _scalar(connection, "SELECT count(*) FROM flow_objects"),
            "Substances", Direction.NEUTRAL, "published",
        ))
        out.append(MeasureValue(
            "substances.unnamed",
            _scalar(
                connection,
                "SELECT count(*) FROM flow_objects WHERE coalesce(pref_label_value, '') = ''",
            ),
            "Substances with no preferred label", Direction.LOWER, "published",
        ))
    if _table_exists(connection, "flow_object_payloads"):
        out.append(MeasureValue(
            "substances.without_payload",
            _scalar(
                connection,
                "SELECT count(*) FROM flow_objects fo WHERE NOT EXISTS ("
                "SELECT 1 FROM flow_object_payloads p "
                "WHERE p.flow_object_id = fo.flow_object_id)",
            ),
            "Substances with no published payload", Direction.LOWER, "published",
        ))
    if _table_exists(connection, "flow_objects") and _column_exists(
        connection, "flow_objects", "properties_json"
    ):
        out.append(MeasureValue(
            "substances.structure_miscounts_the_name",
            _structures_miscounting_their_name(connection),
            "Substances stating a formula their own name contradicts",
            Direction.LOWER, "published",
        ))
    return out


def _structures_miscounting_their_name(connection: sqlite3.Connection) -> int:
    """Substances whose name counts its atoms and whose formula disagrees.

    `Antimony Trisulfide` published `SSb+` -- one sulfur where its name says
    three, and a different compound (#129).  Counted rather than merely fixed
    because the two ways a structure gets here are separate: a name the parser
    misread, which #129 stops, and a registry lookup that answered for another
    substance, which it does not.

    Two remain and are known: `Molybdenum Disulfide` states `MoS` and
    `Divanadium Trioxide` states `O3V`, both from PubChem records reached
    through a registry number, and molybdenum's number is not molybdenum
    disulfide's.  A third appearing is a new defect rather than a known one.
    """
    miscounting = 0
    rows = connection.execute(
        "SELECT pref_label_value, properties_json FROM flow_objects"
    )
    for label, properties_json in rows:
        if not properties_json:
            continue
        try:
            properties = orjson.loads(properties_json)
        except orjson.JSONDecodeError:
            continue
        entry = (properties or {}).get(CHEMROF_MOLECULAR_FORMULA)
        raw = entry.get("@value") if isinstance(entry, dict) else None
        formulas = raw if isinstance(raw, list) else [raw] if raw else []
        if any(contradicts_name(str(f), label or "") for f in formulas):
            miscounting += 1
    return miscounting


#: The five outcomes, and the measure suffix each is counted under.  Written as
#: a table so the report and the baseline cannot drift from the SQL.
_OUTCOME_MEASURES: tuple[tuple[str, str, str, Direction], ...] = (
    ("prepared", "prepared", "matched through the prepared correspondence", Direction.NEUTRAL),
    ("algorithm", "algorithm", "matched by the algorithm", Direction.NEUTRAL),
    ("manual-addition", "manual_addition", "placed by a manual addition", Direction.NEUTRAL),
    ("created", "created", "given a newly minted flow", Direction.NEUTRAL),
    ("unmatched", "unmatched", "reached nothing", Direction.LOWER),
)


def _merge_measures(connection: sqlite3.Connection) -> list[MeasureValue]:
    """Per source list: how much of it lands, and on what.

    Keyed `merge.<list>-<version>.*`.  The version is in the key because two
    versions of ecoinvent are merged into one build and their numbers are not
    interchangeable; it also means bumping a version starts a fresh series
    rather than silently continuing an old one under a new meaning.
    """
    if not _table_exists(connection, "merge_outcomes"):
        return []
    run_id = latest_merge_run(connection)
    if not run_id:
        return []

    out: list[MeasureValue] = []
    inputs = connection.execute(
        "SELECT list_name, list_version, row_count FROM merge_run_inputs "
        "WHERE run_id = ? ORDER BY sequence",
        (run_id,),
    ).fetchall()
    for list_name, list_version, _row_count in inputs:
        key = f"merge.{list_name}-{list_version}"
        where = "run_id = ? AND list_name = ? AND list_version = ?"
        args = (run_id, list_name, list_version)
        label = f"{list_name} {list_version}"

        total = _scalar(connection, f"SELECT count(*) FROM merge_outcomes WHERE {where}", args)
        out.append(MeasureValue(f"{key}.rows", total, f"{label}: source rows", Direction.NEUTRAL, "merge"))

        for outcome, suffix, phrase, direction in _OUTCOME_MEASURES:
            out.append(MeasureValue(
                f"{key}.{suffix}",
                _scalar(
                    connection,
                    f"SELECT count(*) FROM merge_outcomes WHERE {where} AND outcome = ?",
                    (*args, outcome),
                ),
                f"{label}: rows {phrase}",
                direction,
                "merge",
            ))

        # The composite the outcome counts do not give directly: landing on a
        # flow that already existed is the thing a merge is for, and it is the
        # measure a matching change is trying to move.
        out.append(MeasureValue(
            f"{key}.on_existing_flow",
            _scalar(
                connection,
                f"SELECT count(*) FROM merge_outcomes WHERE {where} AND outcome IN "
                "('prepared','algorithm','manual-addition')",
                args,
            ),
            f"{label}: rows landing on a flow that already existed",
            Direction.HIGHER,
            "merge",
        ))
        out.append(MeasureValue(
            f"{key}.distinct_targets",
            _scalar(
                connection,
                f"SELECT count(DISTINCT target_elementary_flow_id) FROM merge_outcomes "
                f"WHERE {where} AND coalesce(target_elementary_flow_id, '') <> ''",
                args,
            ),
            f"{label}: distinct consensus flows reached",
            Direction.NEUTRAL,
            "merge",
        ))
        out.append(MeasureValue(
            f"{key}.context_inconsistent",
            _scalar(
                connection,
                f"SELECT count(*) FROM merge_outcomes WHERE {where} AND has_context_inconsistency = 1",
                args,
            ),
            f"{label}: rows whose context the merge flagged",
            Direction.LOWER,
            "merge",
        ))
        out.append(MeasureValue(
            f"{key}.unit_mismatch",
            _scalar(
                connection,
                f"SELECT count(*) FROM merge_outcomes WHERE {where} AND has_unit_mismatch = 1",
                args,
            ),
            f"{label}: rows measured in one unit landing on a flow in another",
            Direction.LOWER,
            "merge",
        ))
        if _table_exists(connection, "elementary_flows"):
            out.append(MeasureValue(
                f"{key}.on_characterised_flow",
                _scalar(
                    connection,
                    "SELECT count(*) FROM merge_outcomes mo JOIN elementary_flows ef "
                    "ON ef.uuid = mo.target_elementary_flow_id "
                    "WHERE mo.run_id = ? AND mo.list_name = ? AND mo.list_version = ? "
                    "AND ef.lcia_factor_count > 0",
                    args,
                ),
                f"{label}: rows landing on a flow that carries a factor",
                Direction.HIGHER,
                "merge",
            ))

    if _table_exists(connection, "merge_conflicts"):
        out.append(MeasureValue(
            "merge.conflicts",
            _scalar(connection, "SELECT count(*) FROM merge_conflicts WHERE run_id = ?", (run_id,)),
            "Targets two lists disagree about",
            Direction.LOWER,
            "merge",
        ))
    return out


def _unit_crossing_measures(connection: sqlite3.Connection) -> list[MeasureValue]:
    """Mappings that cross from one kind of quantity to another, and how many
    of them somebody has written a reason for.

    A source row measured in one unit can land on a flow measured in another,
    and the two cases that produces are not alike.  A becquerel against a
    kilobecquerel is one quantity written at two scales, and `units.json`
    converts it without anybody's help.  A kilogram against a megajoule is a
    mass against an energy, and no table converts those, because how many
    megajoules a kilogram is depends on the substance: EF 3.1 accounts fossil
    energy carriers by energy content on purpose, so ecoinvent's `Coal, brown`
    in kilograms maps onto brown coal in megajoules and that mapping is right,
    while a mass mapped onto an energy for which no heating value exists is
    simply wrong -- and from inside the build the two look identical.

    `unit-change-allowlist.json` is where the difference is written down, one
    entry per pair with its reasoning.  These two measures make the file's
    coverage checkable: how many crossings this build publishes, and how many
    of them no entry accepts.  The second should be nothing, which is #171.

    Computed from the stored build against the ruling files as they stand
    rather than from a counter the merge wrote, and deliberately so: a curator
    who adds an entry can run `assess` and watch the number fall without
    rebuilding, and a build made before the entry was written is graded by it.
    """
    if not _table_exists(connection, "merge_outcomes"):
        return []
    if not _table_exists(connection, "elementary_flows"):
        return []
    run_id = latest_merge_run(connection)
    if not run_id:
        return []

    from brightway_flows.merge.unit_changes import (
        crosses_quantity_kinds,
        load_unit_change_allowlist,
    )

    allowed = load_unit_change_allowlist()
    rows = connection.execute(
        "SELECT mo.source_uuid, mo.source_unit, mo.target_elementary_flow_id, ef.unit "
        "FROM merge_outcomes mo JOIN elementary_flows ef "
        "ON ef.uuid = mo.target_elementary_flow_id "
        "WHERE mo.run_id = ? AND mo.outcome IN ('prepared','algorithm','manual-addition')",
        (run_id,),
    ).fetchall()

    crossings = 0
    unrecorded = 0
    for source_uuid, source_unit, target_id, target_unit in rows:
        if not crosses_quantity_kinds(str(source_unit or ""), str(target_unit or "")):
            continue
        crossings += 1
        if (str(source_uuid), str(target_id or "")) not in allowed:
            unrecorded += 1

    return [
        MeasureValue(
            "merge.unit_crossings",
            crossings,
            "Mappings from one kind of quantity to another",
            Direction.NEUTRAL,
            "merge",
        ),
        MeasureValue(
            "merge.unit_crossings_unrecorded",
            unrecorded,
            "Mappings from one kind of quantity to another with no ruling",
            Direction.LOWER,
            "merge",
        ),
    ]


def _queue_measures(connection: sqlite3.Connection) -> list[MeasureValue]:
    """How much human work each queue is holding.

    Lower is better for all of them: a queue is a list of decisions nobody has
    made yet.  That is true even when the queue grows because the build got
    better at finding cases -- which is exactly why the number is worth watching
    rather than asserting on.

    Every registered queue reports, zero included.  Counting only the rows the
    table holds made an *empty* queue produce no measure at all, so "this queue
    is finally clear" -- the endpoint every queue is worked towards -- was the
    one state an expectation could not claim: #114 wrote that down as a
    limitation, and #116's `substance-label-conflict equals 0` hit it again.  A
    queue name the table holds and the registry does not (a build written by a
    newer version) still reports, so nothing a build found is dropped.

    The three factor queues are the exception: `characterise` writes them, not
    the build, so on a database nothing has characterised their length is not
    zero -- it is unknown, and reporting 0 would grade a `queue.*-factor`
    expectation as "empty" on exactly the builds that never asked the question.
    They default to zero only where an LCIA run has happened, and are otherwise
    reported only if rows exist -- the same "absent is a fact about the build"
    rule the `factors.*` measures follow.
    """
    if not _table_exists(connection, "review_queue"):
        return []
    counts = {
        str(name): int(count)
        for name, count in connection.execute(
            "SELECT queue_name, count(*) FROM review_queue GROUP BY queue_name"
        )
    }
    factor_queues = {
        str(ReviewQueue.CONTESTED_FACTOR),
        str(ReviewQueue.PROPOSED_FACTOR),
        str(ReviewQueue.CONTRADICTED_FACTOR),
    }
    characterised = (
        _table_exists(connection, "lcia_runs")
        and _scalar(connection, "SELECT count(*) FROM lcia_runs") > 0
    )
    registered = {
        str(queue) for queue in ReviewQueue
        if characterised or str(queue) not in factor_queues
    }
    return [
        MeasureValue(
            f"queue.{name}", counts.get(name, 0),
            f"Review queue: {name}", Direction.LOWER, "queues",
        )
        for name in sorted(set(counts) | registered)
    ]


#: Stats `characterise` writes that `_queue_measures` already counts.  The two
#: factor queues are `review_queue` rows, so their length arrives as
#: `queue.contested-factor` and `queue.proposed-factor`; counting them again here
#: would be two measures of one thing that could drift apart in a report.
_QUEUE_STATS_ALREADY_COUNTED = ("_items",)


def _factor_measures(connection: sqlite3.Connection) -> list[MeasureValue]:
    """What the last `characterise` run counted about itself.

    Every one is `neutral`, and that is not laziness.  Two implementations of one
    method agreeing more often is not this pipeline getting better -- it is two
    other teams' files being closer together -- and a report that called
    `difference_over_100x` going up a regression would be blaming this build for
    somebody else's release.  What the numbers are for is noticing that they
    moved: a matching change that halves `difference_shared` has broken the
    comparison, and no expectation would have caught it.
    """
    if not _table_exists(connection, "lcia_runs"):
        return []
    row = connection.execute(
        "SELECT stats_json FROM lcia_runs ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return []
    try:
        stats = orjson.loads((row[0] or "{}").encode("utf-8"))
    except orjson.JSONDecodeError:  # pragma: no cover - a column nothing wrote
        return []
    if not isinstance(stats, dict):  # pragma: no cover - same
        return []
    return [
        MeasureValue(
            f"factors.{key}", int(value), f"characterise: {key.replace('_', ' ')}",
            Direction.NEUTRAL, "factors",
        )
        for key, value in sorted(stats.items())
        if isinstance(value, int)
        and not any(key.endswith(suffix) for suffix in _QUEUE_STATS_ALREADY_COUNTED)
    ]


def _score_measures(connection: sqlite3.Connection) -> list[MeasureValue]:
    """What the last `compare-scores` run counted, per release.

    `scores.<release>.pairs_within_tolerance` and its siblings, from
    `score_runs.stats_json`, where the keys are `<release>.<count>`.  Neutral
    like the factor measures: a vendor's scores and ours agreeing more often
    may be a fix of ours or a revision of theirs, and a report cannot tell.  An
    expectation can -- `at_least` on the within-2x count for a category the
    issue names is how a claim about #150's water finding is stated.
    """
    # Whether the build has been compared at all is itself a measure, and the
    # one this family always has: a build nobody has run `compare-scores`
    # against produces `scores.runs = 0` rather than no `scores.*` at all, so
    # the family exists to be named by an expectation before the run does.
    has_run = _table_exists(connection, "score_runs")
    row = (
        connection.execute(
            "SELECT stats_json FROM score_runs ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        if has_run
        else None
    )
    measures = [
        MeasureValue(
            "scores.runs", 1 if row is not None else 0,
            "compare-scores: whether this build has been compared",
            Direction.NEUTRAL, "scores",
        )
    ]
    if row is None:
        return measures
    try:
        stats = orjson.loads((row[0] or "{}").encode("utf-8"))
    except orjson.JSONDecodeError:  # pragma: no cover - a column nothing wrote
        return measures
    if not isinstance(stats, dict):  # pragma: no cover - same
        return measures
    measures.extend(
        MeasureValue(
            f"scores.{key}", int(value),
            f"compare-scores: {key.replace('.', ' ').replace('_', ' ')}",
            Direction.NEUTRAL, "scores",
        )
        for key, value in sorted(stats.items())
        if isinstance(value, int)
    )
    return measures


def _curated_name_measures(connection: sqlite3.Connection) -> list[MeasureValue]:
    """Curated names the build did not publish.  A bound of zero (#337).

    The one question about `flow-object-overrides.json`'s `names` rows that a
    layering pass cannot answer.  A pass resolves a single source list, so a row
    naming an object it did not build looks the same whether the id is a
    curator's typo or the row is about a substance another list mints -- and the
    second is ordinary: the base pass resolves EF 3.1, and both shipped rows name
    objects the merge mints out of ecoinvent rows.  Counting it there reported two
    correct rows as broken on every build.

    Here every object exists, so the question is exact: is there a published
    object with this id, and is it called what the row says it should be called?
    A mistyped id fails the first half, a rename that silently stopped happening
    fails the second, and a build where both hold reports zero.
    """
    if not _table_exists(connection, "flow_objects"):
        return []
    from brightway_flows.flow_layers.layering import curated_object_names

    names = curated_object_names()
    if not names:
        return []

    def _key(value: str) -> str:
        return " ".join(str(value or "").split()).casefold()

    unpublished = 0
    for name in names:
        row = connection.execute(
            "SELECT pref_label_value FROM flow_objects WHERE flow_object_id = ?",
            (name.flow_object_id,),
        ).fetchone()
        if row is None or _key(row[0]) != _key(name.preferred_label):
            unpublished += 1
            logger.info(
                "curated_name_not_published",
                flow_object_id=name.flow_object_id,
                wanted=name.preferred_label,
                found=(row[0] if row is not None else None),
            )
    return [
        MeasureValue(
            "names.rows_unpublished",
            unpublished,
            "curated names the build did not publish under the stated label",
            Direction.LOWER,
            "published",
        )
    ]


def _run_stat_measures(connection: sqlite3.Connection) -> list[MeasureValue]:
    """Everything the pipeline already counted about itself.

    Folded in rather than reimplemented.  `run_stats` exists because the
    question is run-over-run -- its own comment says so -- and this is the
    machinery that finally asks it.
    """
    if not _table_exists(connection, "run_stats"):
        return []
    return [
        MeasureValue(
            f"stats.{stage}.{key}", int(value), f"{stage}: {key.replace('_', ' ')}",
            Direction.NEUTRAL, "pipeline",
        )
        for stage, key, value in connection.execute(
            "SELECT stage, key, value FROM run_stats ORDER BY stage, key"
        )
    ]
