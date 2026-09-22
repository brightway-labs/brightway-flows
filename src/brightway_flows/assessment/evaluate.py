"""Resolving an expectation against a build, and saying what happened instead.

Grading is the easy half.  The half that matters is the *instead*: an
expectation that reports only "unmet" sends its reader back to the database to
find out why, and the database already knows.  So a failed `source_row`
expectation carries the merge's own trace -- the outcome, the reason, and every
candidate the selector scored with the score it gave -- which is the evidence a
matching change is designed from.

Four statuses, because "did it work" has four answers and only two of them are
about the code:

`met`         every claim holds.
`unmet`       the subject is there and a claim does not hold.
`unresolved`  the selector matched nothing.  Not a failure: the row may have
              been renamed upstream, or the list may not be in this build.  It
              means the expectation is stale and needs rewriting, which is a
              different job from fixing the pipeline, so it is reported apart.
`error`       the build cannot answer -- a table the claim needs is missing.

`unresolved` is the status this file exists to keep separate.  Folding it into
`unmet` is how an expectation quietly stops testing anything: rename the vendor
row and a strict checker still says "unmet", which reads as work to do rather
than as an expectation that has lost its subject.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

import orjson
import structlog

from brightway_flows.assessment.expectations import (
    AGGREGATE_CLAIMS,
    AMOUNT_CLAIMS,
    BOUND_KEYS,
    OUTCOME_ALIASES,
    Expectation,
    load_expectations,
    significant_figures,
)
from brightway_flows.assessment.measures import (
    MeasureValue,
    RunIdentity,
    collect_measures,
    latest_merge_run,
    run_identity,
)
from brightway_flows.domain.vocabulary import (
    CHEMINF_CAS_REGISTRY_NUMBER,
    CHEMINF_EC_NUMBER,
    CHEMROF_INCHI2D_KEY_STRING,
    CHEMROF_MOLECULAR_FORMULA,
    RDFS_LABEL_CURIE,
    RO_HAS_ROLE_IRI,
)

logger = structlog.get_logger(__name__)

#: How many rows of evidence a failing expectation carries.  Enough to see the
#: pattern, few enough that a report of fifty failures is still readable; the
#: JSON output carries the count, so a truncation is never silent.
EVIDENCE_ROWS = 5

#: How many scored candidates to keep per evidenced row.  The selector routinely
#: scores a dozen; the top few are what decided it.
EVIDENCE_CANDIDATES = 6


class Status(StrEnum):
    MET = "met"
    UNMET = "unmet"
    UNRESOLVED = "unresolved"
    ERROR = "error"


@dataclass(frozen=True)
class ClaimResult:
    """One claim, what it wanted, and what the build has."""

    claim: str
    expected: Any
    actual: Any
    met: bool
    #: A sentence a reader can act on, where the values alone do not say it.
    note: str = ""


@dataclass(frozen=True)
class ExpectationResult:
    expectation: Expectation
    status: Status
    claims: tuple[ClaimResult, ...] = ()
    matched_rows: int = 0
    #: The trace behind a failure: per row, what the merge decided and what it
    #: scored.  Empty for a met expectation -- nobody reads the evidence for
    #: something that worked, and it is the bulk of the JSON output.
    evidence: tuple[dict[str, Any], ...] = ()
    message: str = ""

    @property
    def failed(self) -> bool:
        """Unmet or unanswerable, and not excused by `pending`."""
        return self.status in (Status.UNMET, Status.ERROR) and not self.expectation.pending


@dataclass(frozen=True)
class Assessment:
    """Everything one run of `assess` found."""

    database: str
    run: RunIdentity
    results: tuple[ExpectationResult, ...] = ()
    measures: dict[str, MeasureValue] = field(default_factory=dict)

    def by_status(self, status: Status) -> tuple[ExpectationResult, ...]:
        return tuple(r for r in self.results if r.status is status)

    @property
    def counts(self) -> dict[str, int]:
        counts = {status.value: 0 for status in Status}
        for result in self.results:
            counts[result.status.value] += 1
        return counts

    @property
    def failures(self) -> tuple[ExpectationResult, ...]:
        return tuple(r for r in self.results if r.failed)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def assess(
    database: Path,
    expectations: tuple[Expectation, ...] | None = None,
    expectations_dir: Path | None = None,
) -> Assessment:
    """Measure *database* and grade every expectation against it.

    Read-only twice over, the same as the review application: `mode=ro` so
    SQLite refuses to create the file, and `query_only` so a mistake in a query
    here raises instead of writing to the artifact a build owns.
    """
    if not database.exists():
        raise FileNotFoundError(
            f"{database} is not there. `assess` reads what a build wrote; run "
            "`brightway-flows build` first."
        )
    expectations = (
        expectations if expectations is not None else load_expectations(expectations_dir)
    )
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    try:
        # Collected once and threaded through.  `_resolve_measure` used to call
        # `collect_measures` itself, so a run with six measure expectations ran
        # the whole registry seven times -- 0.40s each against the real build,
        # 2.4s of it repeated, and growing with every measure expectation added.
        measures = collect_measures(connection, db_path=database)
        return Assessment(
            database=str(database),
            run=run_identity(connection),
            results=tuple(_evaluate(connection, e, measures) for e in expectations),
            measures=measures,
        )
    finally:
        connection.close()


def _evaluate(
    connection: sqlite3.Connection,
    expectation: Expectation,
    measures: dict[str, MeasureValue],
) -> ExpectationResult:
    try:
        rows = _resolve(connection, expectation, measures)
    except _Unanswerable as exc:
        return ExpectationResult(expectation, Status.ERROR, message=str(exc))

    # A claim that a thing is absent is answered by an empty result set, so it
    # has to be evaluated before emptiness is called unresolved.
    if not rows and not _claims_absence(expectation):
        return ExpectationResult(
            expectation,
            Status.UNRESOLVED,
            message=(
                f"nothing in this build matches {_describe_selector(expectation)}. "
                "Either the subject has been renamed or removed upstream, or the "
                "expectation names it wrongly."
            ),
        )

    claims = _check_claims(expectation, rows)
    status = Status.MET if all(c.met for c in claims) else Status.UNMET
    evidence = () if status is Status.MET else _evidence(expectation, rows)
    return ExpectationResult(
        expectation,
        status,
        claims=tuple(claims),
        matched_rows=len(rows),
        evidence=evidence,
    )


class _Unanswerable(RuntimeError):
    """This build has no table that could answer the claim."""


def _claims_absence(expectation: Expectation) -> bool:
    """Whether "no rows" is itself an answer the expectation wanted."""
    claims = expectation.claims
    if claims.get("exists") is False:
        return True
    for key in ("count", "row_count", "target_count"):
        if key in claims and _bound_is_zero(claims[key]):
            return True
    return False


def _bound_is_zero(expected: Any) -> bool:
    if isinstance(expected, int):
        return expected == 0
    if isinstance(expected, dict):
        return expected.get("equals") == 0 or expected.get("at_most") == 0
    return False


# ---------------------------------------------------------------------------
# Resolving a subject to rows of facts
# ---------------------------------------------------------------------------

def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ?",
        (name,),
    ).fetchone() is not None


def _resolve(
    connection: sqlite3.Connection,
    expectation: Expectation,
    measures: dict[str, MeasureValue],
) -> list[dict[str, Any]]:
    match expectation.kind:
        case "source_row":
            return _resolve_source_rows(connection, expectation.selector)
        case "flow":
            return _resolve_flows(connection, expectation.selector)
        case "substance":
            return _resolve_substances(connection, expectation.selector)
        case "factor":
            return _resolve_factors(connection, expectation.selector)
        case "measure":
            return _resolve_measure(measures, expectation.selector)
    raise _Unanswerable(f"unknown subject kind {expectation.kind!r}")


def _resolve_source_rows(
    connection: sqlite3.Connection, selector: dict[str, Any]
) -> list[dict[str, Any]]:
    """Rows of a vendor list, as the most recent merge decided them.

    Restricted to the latest run: the merge tables keep every run, so an
    unrestricted query would grade this build's expectations against a mixture
    of this build and every one before it.

    Names match case-insensitively.  Vendor lists capitalise the same substance
    differently between releases -- `Copper Oxide` and `copper oxide` are one
    row to a reader -- and an expectation that broke on a capitalisation change
    would be noise.  Contexts match exactly: a context is a controlled term, and
    two spellings of one are a finding rather than a convenience.
    """
    if not _table_exists(connection, "merge_outcomes"):
        raise _Unanswerable("this database has no `merge_outcomes` table: nothing was merged")
    run_id = latest_merge_run(connection)
    if not run_id:
        raise _Unanswerable("this database records no merge run")

    clauses = ["mo.run_id = ?"]
    params: list[Any] = [run_id]
    if value := selector.get("list"):
        clauses.append("lower(mo.list_name) = lower(?)")
        params.append(str(value))
    if value := selector.get("version"):
        clauses.append("mo.list_version = ?")
        params.append(str(value))
    if value := selector.get("uuid"):
        clauses.append("mo.source_uuid = ?")
        params.append(str(value))
    if value := selector.get("name"):
        clauses.append("lower(mo.source_name) = lower(?)")
        params.append(str(value))
    if value := selector.get("name_contains"):
        clauses.append("lower(mo.source_name) LIKE lower(?)")
        params.append(f"%{value}%")
    if (value := selector.get("context")) is not None:
        clauses.append("mo.source_context_json = ?")
        params.append(orjson.dumps(value).decode())
    if value := selector.get("cas"):
        clauses.append("mo.source_cas = ?")
        params.append(str(value))
    if value := selector.get("unit"):
        clauses.append("mo.source_unit = ?")
        params.append(str(value))

    # Whether the row's decision reached the published list.  A correlated
    # EXISTS rather than a join: one source row may link to several elementary
    # flows, and a join would return the row once per link and make every count
    # claim about it wrong.
    has_links = _table_exists(connection, "elementary_flow_sources")
    published_sql = (
        "EXISTS (SELECT 1 FROM elementary_flow_sources efs "
        "WHERE efs.list_name = mo.list_name "
        "AND efs.list_version = mo.list_version "
        "AND efs.source_flow_uuid = mo.source_uuid)"
    )
    published_column = (
        f"{published_sql} AS published" if has_links else "NULL AS published"
    )
    # The factor this row's pair converts by, as the merge wrote it.  A scalar
    # subquery for the reason `published` is an EXISTS: a source row may link
    # to several elementary flows and a join would multiply the row.  `LIMIT 1`
    # is safe because a conversion is a property of the *row* -- one number for
    # its pair -- so every link the row made carries the same one.
    conversion_column = (
        "(SELECT json_extract(efs.source_metadata_json, "
        "'$.\"qudt:conversionMultiplier\"') FROM elementary_flow_sources efs "
        "WHERE efs.list_name = mo.list_name "
        "AND efs.list_version = mo.list_version "
        "AND efs.source_flow_uuid = mo.source_uuid LIMIT 1) AS conversion_factor"
        if has_links
        else "NULL AS conversion_factor"
    )
    if (value := selector.get("published")) is not None:
        if not has_links:
            raise _Unanswerable(
                "this database has no `elementary_flow_sources` table: "
                "nothing records which decisions reached the list"
            )
        # A row the merge never placed has no decision to publish, so it is not
        # what "missing from the list" is asking about.  Left in, every
        # unmatched row would answer a question about the writer.
        clauses.append(
            f"{'' if value else 'NOT '}{published_sql} AND mo.outcome != 'unmatched'"
        )
    has_flows = _table_exists(connection, "elementary_flows")
    target_columns = (
        "ef.unit AS target_unit, ef.context_iri AS target_context_iri, "
        "ef.context_display AS target_context_display, "
        "ef.lcia_factor_count AS target_factor_count, "
        "ef.is_deprecated AS target_is_deprecated, "
        "fo.pref_label_value AS target_name, "
        "fo.classifications_json AS target_classifications_json"
        if has_flows
        else "NULL AS target_unit, NULL AS target_context_iri, "
             "NULL AS target_context_display, NULL AS target_factor_count, "
             "NULL AS target_is_deprecated, NULL AS target_name, "
             "NULL AS target_classifications_json"
    )
    joins = (
        "LEFT JOIN elementary_flows ef ON ef.uuid = mo.target_elementary_flow_id "
        "LEFT JOIN flow_objects fo ON fo.flow_object_id = ef.flow_object_id"
        if has_flows
        else ""
    )
    rows = connection.execute(
        f"SELECT mo.source_uuid, mo.source_name, mo.source_context_json, mo.source_unit, "
        f"mo.source_cas, mo.outcome, mo.reason, mo.basis, mo.basis_value, "
        f"mo.matching_method, mo.target_elementary_flow_id, mo.flow_object_id, "
        f"mo.has_unit_mismatch, mo.has_context_inconsistency, mo.detail_json, "
        f"{published_column}, {conversion_column}, "
        f"{target_columns} "
        f"FROM merge_outcomes mo {joins} WHERE {' AND '.join(clauses)} "
        f"ORDER BY mo.source_name, mo.source_uuid",
        params,
    ).fetchall()

    return [
        {
            "source_uuid": row["source_uuid"],
            "source_name": row["source_name"] or "",
            "source_context": _load(row["source_context_json"], []),
            "source_unit": row["source_unit"] or "",
            "source_cas": row["source_cas"] or "",
            "outcome": row["outcome"] or "",
            "reason": row["reason"] or "",
            "basis": row["basis"] or "",
            "basis_value": row["basis_value"] or "",
            "matching_method": row["matching_method"] or "",
            "target_uuid": row["target_elementary_flow_id"] or "",
            "target_substance_id": row["flow_object_id"] or "",
            "target_name": row["target_name"] or "",
            "target_unit": row["target_unit"] or "",
            "target_context_iri": row["target_context_iri"] or "",
            "target_context_display": row["target_context_display"] or "",
            "target_cas": _classification_values(
                _load(row["target_classifications_json"], {}), CHEMINF_CAS_REGISTRY_NUMBER
            ),
            "target_characterised": bool(row["target_factor_count"] or 0),
            "target_deprecated": bool(row["target_is_deprecated"] or 0),
            "published": bool(row["published"] or 0),
            "conversion_factor": row["conversion_factor"],
            "unit_mismatch": bool(row["has_unit_mismatch"] or 0),
            "context_inconsistency": bool(row["has_context_inconsistency"] or 0),
            "_detail": _load(row["detail_json"], {}),
        }
        for row in rows
    ]


#: Which claim reads which implementation's factors.  Three names rather than a
#: nested value, because a claim compares one fact: `"jrc_factors": 0` is a
#: statement a reader can check, and `{"factors": {...}}` is a structure they have
#: to unpick.  `characterised` and `factor_count` are unchanged and remain the
#: JRC's non-zero factors, which is what `elementary_flows.lcia_factor_count`
#: holds and what a query written before `characterise` existed still means.
FACTOR_CLAIMS: dict[str, str] = {
    "jrc_factors": "European Commission — JRC",
    "ecoinvent_factors": "ecoinvent Centre",
    "consensus_factors": "brightway-flows",
}

#: What a flow carries where nothing has characterised anything -- a database
#: whose build predates `characterise`, which is the normal state of one that has
#: not been re-run. Zero rather than absent, because a claim of `0` there is true.
_NO_FACTORS: dict[str, int] = dict.fromkeys(FACTOR_CLAIMS, 0)


def _factors_by_implementation(
    connection: sqlite3.Connection, uuids: list[str]
) -> dict[str, dict[str, int]]:
    """How many factors each implementation states about each of *uuids*.

    Absent tables answer zero rather than raising: `assess` grades a build, and a
    build with no `characterise` run behind it has no factors under any
    implementation -- which is a fact about that database and not a reason to
    refuse the whole expectation.
    """
    if not uuids or not _table_exists(connection, "lcia_characterization_factors"):
        return {}
    reverse = {value: key for key, value in FACTOR_CLAIMS.items()}
    placeholders = ", ".join("?" * len(uuids))
    counts: dict[str, dict[str, int]] = {}
    for uuid, implemented_by, count in connection.execute(
        "SELECT f.elementary_flow_uuid, c.implemented_by, count(*) "
        "FROM lcia_characterization_factors f "
        "JOIN lcia_impact_categories c ON c.id = f.impact_category_id "
        f"WHERE f.elementary_flow_uuid IN ({placeholders}) "
        "GROUP BY f.elementary_flow_uuid, c.implemented_by",
        uuids,
    ):
        claim = reverse.get(str(implemented_by))
        if claim is None:
            continue
        counts.setdefault(str(uuid), dict(_NO_FACTORS))[claim] = int(count)
    return counts


def _resolve_flows(
    connection: sqlite3.Connection, selector: dict[str, Any]
) -> list[dict[str, Any]]:
    """Consensus elementary flows.

    Deprecated flows are excluded unless asked for.  "How many flows are named
    `Herbicides, Unspecified` in this context" is a question about the list
    somebody uses, and a deprecated row is not in it; counting them would make
    a successful deduplication look like it changed nothing.
    """
    if not _table_exists(connection, "elementary_flows"):
        raise _Unanswerable("this database has no `elementary_flows` table")

    clauses: list[str] = []
    params: list[Any] = []
    if not selector.get("include_deprecated"):
        clauses.append("ef.is_deprecated = 0")
    if value := selector.get("uuid"):
        clauses.append("ef.uuid = ?")
        params.append(str(value))
    if value := selector.get("name"):
        clauses.append("lower(fo.pref_label_value) = lower(?)")
        params.append(str(value))
    if value := selector.get("context_iri"):
        clauses.append("ef.context_iri = ?")
        params.append(str(value))
    if value := selector.get("context_display"):
        clauses.append("lower(ef.context_display) = lower(?)")
        params.append(str(value))
    if value := selector.get("unit"):
        clauses.append("ef.unit = ?")
        params.append(str(value))

    rows = connection.execute(
        "SELECT ef.uuid, ef.unit, ef.context_iri, ef.context_display, "
        "ef.lcia_factor_count, ef.is_deprecated, ef.replaced_by_uuid, "
        "ef.flow_object_id, fo.pref_label_value, fo.classifications_json "
        "FROM elementary_flows ef "
        "LEFT JOIN flow_objects fo ON fo.flow_object_id = ef.flow_object_id "
        f"WHERE {' AND '.join(clauses) if clauses else '1=1'} "
        "ORDER BY fo.pref_label_value, ef.context_display, ef.uuid",
        params,
    ).fetchall()
    by_implementation = _factors_by_implementation(
        connection, [row["uuid"] for row in rows]
    )
    return [
        {
            "uuid": row["uuid"],
            "name": row["pref_label_value"] or "",
            "unit": row["unit"] or "",
            "context_iri": row["context_iri"] or "",
            "context_display": row["context_display"] or "",
            "characterised": bool(row["lcia_factor_count"] or 0),
            "factor_count": int(row["lcia_factor_count"] or 0),
            **by_implementation.get(row["uuid"], _NO_FACTORS),
            "deprecated": bool(row["is_deprecated"] or 0),
            "replaced_by": row["replaced_by_uuid"] or "",
            "substance_id": row["flow_object_id"] or "",
            "substance_cas": _classification_values(
                _load(row["classifications_json"], {}), CHEMINF_CAS_REGISTRY_NUMBER
            ),
        }
        for row in rows
    ]


def _resolve_substances(
    connection: sqlite3.Connection, selector: dict[str, Any]
) -> list[dict[str, Any]]:
    """Flow objects: one row per substance identity.

    A CAS selector matches on the published classification rather than on any
    source row's number, because the question an expectation asks is about what
    the build concluded, not about what a vendor claimed.
    """
    if not _table_exists(connection, "flow_objects"):
        raise _Unanswerable("this database has no `flow_objects` table")

    clauses: list[str] = []
    params: list[Any] = []
    if value := selector.get("id"):
        clauses.append("fo.flow_object_id = ?")
        params.append(str(value))
    if value := selector.get("label"):
        clauses.append("lower(fo.pref_label_value) = lower(?)")
        params.append(str(value))
    cas = str(selector.get("cas") or "")
    if cas:
        # Narrow in SQL on the serialised payload, then confirm in Python: the
        # `LIKE` can match a longer number that contains this one, and a wrong
        # substance passing a CAS claim is exactly the class of error the
        # project's guards exist to catch.
        clauses.append("fo.classifications_json LIKE ?")
        params.append(f"%{cas}%")

    rows = connection.execute(
        "SELECT fo.flow_object_id, fo.pref_label_value, fo.classifications_json, "
        "fo.flow_object_json, fo.flow_type, fo.alt_label_json, fo.properties_json, "
        "(SELECT count(*) FROM elementary_flows ef "
        " WHERE ef.flow_object_id = fo.flow_object_id AND ef.is_deprecated = 0) AS flow_count, "
        "EXISTS(SELECT 1 FROM flow_object_payloads p "
        "       WHERE p.flow_object_id = fo.flow_object_id) AS has_payload "
        "FROM flow_objects fo "
        f"WHERE {' AND '.join(clauses) if clauses else '1=1'} "
        "ORDER BY fo.pref_label_value, fo.flow_object_id",
        params,
    ).fetchall()

    resolved = []
    for row in rows:
        classifications = _load(row["classifications_json"], {})
        numbers = _classification_values(classifications, CHEMINF_CAS_REGISTRY_NUMBER)
        if cas and cas not in numbers:
            continue
        resolved.append({
            "id": row["flow_object_id"],
            "label": row["pref_label_value"] or "",
            "cas": numbers,
            "ec": _classification_values(classifications, CHEMINF_EC_NUMBER),
            "flow_count": int(row["flow_count"] or 0),
            "has_payload": bool(row["has_payload"]),
            "flow_type": _flow_type_term(row["flow_type"]),
            "alt_label": _alt_label_values(_load(row["alt_label_json"], [])),
            "roles": _role_labels(_load(row["flow_object_json"], {})),
            "inchikey_count": _property_value_count(
                _load(row["properties_json"], {}), CHEMROF_INCHI2D_KEY_STRING
            ),
            "formula_count": _property_value_count(
                _load(row["properties_json"], {}), CHEMROF_MOLECULAR_FORMULA
            ),
        })
    return resolved


def _resolve_factors(
    connection: sqlite3.Connection, selector: dict[str, Any]
) -> list[dict[str, Any]]:
    """Published characterisation factors: one row per flow, category and publisher.

    The three implementations are kept apart rather than reduced to the
    consensus number, because the question #49 asks needs all three: EF's own
    figure, ecoinvent's implementation of it, and what this list publishes are
    three separate facts, and "ecoinvent states ten times the JRC here" cannot
    be said at all if only one of them is reachable.

    `substance_cas` is confirmed in Python after a `LIKE` narrows it in SQL, for
    the reason `_resolve_substances` does the same: the pattern can match a
    longer number containing this one, and a factor attributed to the wrong
    substance passing a claim is the error a guard is for.
    """
    for table in ("lcia_characterization_factors", "lcia_impact_categories"):
        if not _table_exists(connection, table):
            raise _Unanswerable(f"this database has no `{table}` table")

    clauses: list[str] = []
    params: list[Any] = []
    if value := selector.get("flow_uuid"):
        clauses.append("f.elementary_flow_uuid = ?")
        params.append(str(value))
    if value := selector.get("flow_name"):
        clauses.append("lower(fo.pref_label_value) = lower(?)")
        params.append(str(value))
    if value := selector.get("context_display"):
        clauses.append("lower(ef.context_display) = lower(?)")
        params.append(str(value))
    if value := selector.get("context_iri"):
        clauses.append("ef.context_iri = ?")
        params.append(str(value))
    if value := selector.get("category"):
        clauses.append("lower(ic.name) = lower(?)")
        params.append(str(value))
    if value := selector.get("implemented_by"):
        clauses.append("ic.implemented_by = ?")
        params.append(str(value))
    cas = str(selector.get("substance_cas") or "")
    if cas:
        clauses.append("fo.classifications_json LIKE ?")
        params.append(f"%{cas}%")

    rows = connection.execute(
        "SELECT f.elementary_flow_uuid, f.amount, f.derivation, "
        "ic.name AS category, ic.implemented_by, "
        "ef.context_display, ef.context_iri, "
        "fo.pref_label_value, fo.classifications_json "
        "FROM lcia_characterization_factors f "
        "JOIN lcia_impact_categories ic ON ic.id = f.impact_category_id "
        "LEFT JOIN elementary_flows ef ON ef.uuid = f.elementary_flow_uuid "
        "LEFT JOIN flow_objects fo ON fo.flow_object_id = ef.flow_object_id "
        f"WHERE {' AND '.join(clauses) if clauses else '1=1'} "
        "ORDER BY fo.pref_label_value, ef.context_display, ic.name, ic.implemented_by",
        params,
    ).fetchall()

    resolved = []
    for row in rows:
        numbers = _classification_values(
            _load(row["classifications_json"], {}), CHEMINF_CAS_REGISTRY_NUMBER
        )
        if cas and cas not in numbers:
            continue
        resolved.append({
            "flow_uuid": row["elementary_flow_uuid"],
            "flow_name": row["pref_label_value"] or "",
            "substance_cas": numbers,
            "context_display": row["context_display"] or "",
            "context_iri": row["context_iri"] or "",
            "category": row["category"] or "",
            "implemented_by": row["implemented_by"] or "",
            "derivation": row["derivation"] or "",
            "amount": row["amount"],
        })
    return resolved


def _property_value_count(properties: Any, iri: str) -> int:
    """How many values a substance publishes for one property.

    The claim #310 is about: a substance publishing two InChIKeys is publishing
    two identities, and a consumer joining on one matches twice.  Counted rather
    than compared, because the expectation that matters is *one*, and which one
    is the separate question `label` and `cas` already answer.
    """
    if not isinstance(properties, dict):
        return 0
    entry = properties.get(iri)
    if not isinstance(entry, dict):
        return 0
    raw = entry.get("@value")
    if isinstance(raw, list):
        return len([v for v in raw if str(v).strip()])
    return 1 if str(raw or "").strip() else 0


def _alt_label_values(payload: Any) -> list[str]:
    """The strings a substance publishes as alternative labels.

    The column holds the labels as language-tagged objects, and an expectation
    names the string -- `HFC-116`, not `{"@value": "HFC-116", ...}`. A bare
    string is accepted too, because the column is written from a record whose
    labels may not yet have been coerced.
    """
    if not isinstance(payload, list):
        return []
    values: list[str] = []
    for entry in payload:
        value = entry.get("@value") if isinstance(entry, dict) else entry
        if isinstance(value, str) and value.strip():
            values.append(value.strip())
    return values


def _flow_type_term(value: Any) -> str:
    """The published `flow_type` as the term a person would write.

    The column holds an IRI for a typed substance and the bare word
    `unclassified` for one the rules could not place.  An expectation names the
    term -- `MonoatomicIon`, `NeutralMolecule`, `unclassified` -- so the last
    segment is what is compared, for the same reason `roles` compares labels:
    `https://w3id.org/chemrof/MonoatomicIon` in a file somebody has to read is a
    URL where a word would do.
    """
    text = str(value or "").strip()
    if not text:
        return ""
    return text.rsplit("/", 1)[-1]


def _role_labels(payload: dict[str, Any]) -> list[str]:
    """The role labels a substance publishes, out of its serialised record.

    Read from `flow_object_json` rather than from a column, because `roles` has
    none: the field is published under its full predicate IRI in the record the
    export projects.  Labels rather than IRIs, because an expectation is a
    sentence somebody checks by reading -- `"roles": "insecticide"` says what
    `CHEBI_24852` does not.
    """
    return [
        str(entry.get(RDFS_LABEL_CURIE) or "")
        for entry in payload.get(RO_HAS_ROLE_IRI) or ()
        if isinstance(entry, dict) and entry.get(RDFS_LABEL_CURIE)
    ]


def _resolve_measure(
    measures: dict[str, MeasureValue], selector: dict[str, Any]
) -> list[dict[str, Any]]:
    """One measure, by name, out of the registry the run already collected.

    A selector may state `value_when_absent` for a measure that vanishes at
    zero: the stats tables write no row for nothing, so an `at_most: 0` claim
    on such a count would report unresolved at exactly the moment it is met.
    Only a stated number substitutes -- an absent key with no stated meaning
    is still "the subject went missing", which is what unresolved is for.
    """
    key = str(selector.get("key") or "")
    if key not in measures:
        absent = selector.get("value_when_absent")
        if isinstance(absent, (int, float)) and not isinstance(absent, bool):
            return [{"key": key, "value": absent}]
        return []
    return [{"key": key, "value": measures[key].value}]


def _load(raw: Any, default: Any) -> Any:
    if not raw:
        return default
    try:
        return orjson.loads(raw)
    except orjson.JSONDecodeError:
        return default


def _classification_values(classifications: Any, iri: str) -> list[str]:
    """The `@value` list under one classification IRI.

    Serialised payload, so it is read defensively -- the same shape the review
    application reads, and read here rather than imported from it because
    `assessment` must not depend on the Flask package.
    """
    if not isinstance(classifications, dict):
        return []
    entry = classifications.get(iri)
    if not isinstance(entry, dict):
        return []
    raw = entry.get("@value")
    if isinstance(raw, str):
        return [raw] if raw.strip() else []
    if isinstance(raw, list):
        return [str(v) for v in raw if isinstance(v, str) and v.strip()]
    return []


# ---------------------------------------------------------------------------
# Checking claims
# ---------------------------------------------------------------------------

#: Claims whose value is compared without regard to case.  Names are written by
#: people and recapitalised by vendors; identifiers, units and IRIs are not.
_CASE_INSENSITIVE = frozenset({
    "target_name", "target_context_display", "reason", "basis",
    "name", "label", "context_display", "alt_label",
})

#: Claims that read a list of values from the row and are met when the expected
#: value is one of them.
#:
#: `roles` is here rather than in `_CASE_INSENSITIVE` because a role label is a
#: vocabulary term copied out of ChEBI, like an IRI and unlike a substance name:
#: nobody recapitalises `insecticide` between releases, and matching loosely
#: would let `Insecticide` pass while naming a term that does not exist.
#:
#: `alt_label` is the opposite case and is in `_CASE_INSENSITIVE` as well: an
#: alternative label is a name a source list wrote, and the spelling is what
#: varies -- EF 3.1 ships `HFC-23` and `hfc-23` for one substance, so an
#: expectation that named one spelling would fail on the release that shipped
#: the other.
_MEMBERSHIP = frozenset({"target_cas", "substance_cas", "cas", "roles", "alt_label"})

#: Claim name -> the fact it reads, where the two differ.
_FACT_FOR_CLAIM: dict[str, str] = {
    "target_characterised": "target_characterised",
    "target_deprecated": "target_deprecated",
    "substance_id": "substance_id",
    "substance_cas": "substance_cas",
}


def _check_claims(expectation: Expectation, rows: list[dict[str, Any]]) -> list[ClaimResult]:
    return [
        _check_claim(expectation, claim, expected, rows)
        for claim, expected in expectation.claims.items()
    ]


def _check_claim(
    expectation: Expectation, claim: str, expected: Any, rows: list[dict[str, Any]]
) -> ClaimResult:
    if expectation.kind == "measure":
        # `equals`, `at_most` and `at_least` are three spellings of one
        # comparison against the single number a measure resolves to.
        value = rows[0]["value"] if rows else None
        return _check_bound(claim, {claim: expected}, value)
    if claim in AGGREGATE_CLAIMS or claim == "exists":
        return _check_aggregate(claim, expected, rows)
    if claim == "outcome":
        return _check_outcome(expected, rows, negate=False)
    if claim == "not_outcome":
        return _check_outcome(expected, rows, negate=True)
    return _check_per_row(claim, expected, rows)


def _check_aggregate(claim: str, expected: Any, rows: list[dict[str, Any]]) -> ClaimResult:
    match claim:
        case "exists":
            actual = bool(rows)
            return ClaimResult(claim, expected, actual, actual is bool(expected))
        case "count" | "row_count":
            return _check_bound(claim, expected, len(rows))
        case "target_count":
            targets = {r.get("target_uuid", "") for r in rows} - {""}
            return _check_bound(claim, expected, len(targets))
        case "substance_count":
            substances = {r.get("target_substance_id", "") for r in rows} - {""}
            return _check_bound(claim, expected, len(substances))
        case "same_substance":
            return _check_shared(claim, expected, rows, "target_substance_id", "substances")
        case "distinct_substances":
            return _check_unshared(claim, expected, rows, "target_substance_id", "substances")
        case "same_target":
            return _check_shared(claim, expected, rows, "target_uuid", "flows")
        case "distinct_targets":
            return _check_unshared(claim, expected, rows, "target_uuid", "flows")
    return ClaimResult(claim, expected, None, False, f"claim {claim!r} is not implemented")


def _check_shared(
    claim: str, expected: Any, rows: list[dict[str, Any]], fact: str, plural: str
) -> ClaimResult:
    """Every matched row reached the same thing, and every row reached one."""
    values = {row.get(fact, "") for row in rows}
    actual = len(values) == 1 and "" not in values
    note = ""
    if not actual:
        note = f"{len(values - {''})} distinct {plural}"
        if "" in values:
            note += f", and {sum(1 for r in rows if not r.get(fact))} rows reached none"
    return ClaimResult(claim, expected, actual, actual is bool(expected), note)


def _check_unshared(
    claim: str, expected: Any, rows: list[dict[str, Any]], fact: str, plural: str
) -> ClaimResult:
    """No two matched rows reached the same thing.

    Rows that reached nothing are left out rather than counted as sharing: an
    unmatched row has not been fused with anything, and calling it a collision
    would report the wrong defect.
    """
    values = [row.get(fact, "") for row in rows if row.get(fact)]
    actual = len(values) == len(set(values))
    note = "" if actual else f"{len(values)} rows share {len(set(values))} {plural}"
    return ClaimResult(claim, expected, actual, actual is bool(expected), note)


def _check_bound(claim: str, expected: Any, actual: int | None) -> ClaimResult:
    """`5`, or `{"at_most": 5}`, or `{"at_least": 1, "at_most": 3}`."""
    if actual is None:
        return ClaimResult(claim, expected, None, False, "this build has no such measure")
    if isinstance(expected, bool) or not isinstance(expected, (int, dict)):
        return ClaimResult(
            claim, expected, actual, False,
            "expected a number or a bound like {\"at_most\": 5}",
        )
    if isinstance(expected, int):
        return ClaimResult(claim, expected, actual, actual == expected)
    return ClaimResult(claim, expected, actual, _within_bound(expected, actual))


def _within_bound(bound: dict[str, Any], actual: Any) -> bool:
    """Fails closed on a bound it does not understand.

    `expectations` rejects an unrecognised bound key at load, so this cannot be
    reached from a file any more.  It returns `False` rather than `True` anyway,
    because the version that returned `True` here is what let `{"at_mst": 3}`
    report **met**, and a second reader of this function should not have to
    check the loader to know which way it fails.
    """
    if not isinstance(actual, int) or isinstance(actual, bool):
        return False
    if not set(bound) & BOUND_KEYS:
        return False
    if "equals" in bound and actual != bound["equals"]:
        return False
    if "at_most" in bound and actual > bound["at_most"]:
        return False
    if "at_least" in bound and actual < bound["at_least"]:
        return False
    return True


def _check_outcome(expected: Any, rows: list[dict[str, Any]], negate: bool) -> ClaimResult:
    """`outcome`, with the two aliases expanded.

    Every row must satisfy it.  `actual` reports the distribution rather than
    one row's value, because "3 of 11 rows are unmatched" is the finding and
    "unmatched" is not.
    """
    wanted: set[str] = set()
    for value in expected if isinstance(expected, list) else [expected]:
        wanted.update(OUTCOME_ALIASES.get(str(value), (str(value),)))
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["outcome"]] = counts.get(row["outcome"], 0) + 1
    hit = {outcome for outcome in counts if outcome in wanted}
    miss = {outcome for outcome in counts if outcome not in wanted}
    met = (not miss) if not negate else (not hit)
    claim = "not_outcome" if negate else "outcome"
    return ClaimResult(
        claim, expected, dict(sorted(counts.items(), key=lambda kv: -kv[1])), met,
        "" if met else f"{sum(counts[o] for o in (hit if negate else miss))} of {len(rows)} rows",
    )


def _check_per_row(claim: str, expected: Any, rows: list[dict[str, Any]]) -> ClaimResult:
    """A claim every matched row must satisfy.

    `actual` is the set of values found, not the first one: an expectation over
    eleven rows that fails on two is answered by "these are the values", and a
    single value would hide the split.
    """
    fact = _FACT_FOR_CLAIM.get(claim, claim)
    found: list[Any] = []
    failures = 0
    for row in rows:
        if fact not in row:
            return ClaimResult(
                claim, expected, None, False,
                f"this build records no {fact!r} for the subject",
            )
        value = row[fact]
        found.append(tuple(value) if isinstance(value, list) else value)
        if not _matches(claim, expected, value):
            failures += 1
    distinct = _distinct(found)
    return ClaimResult(
        claim, expected, distinct if len(distinct) != 1 else distinct[0],
        failures == 0,
        "" if not failures else f"{failures} of {len(rows)} rows",
    )


def _matches(claim: str, expected: Any, actual: Any) -> bool:
    # A bound reads the same on one row as on a set: `flow_count` of
    # `{"at_least": 1}` is a claim about each substance the selector matched.
    if isinstance(expected, dict) and expected and set(expected) <= BOUND_KEYS:
        return _within_bound(expected, actual)
    if claim in AMOUNT_CLAIMS:
        return _agrees_to_stated_precision(expected, actual)
    if claim in _MEMBERSHIP:
        values = actual if isinstance(actual, list) else [actual]
        if claim in _CASE_INSENSITIVE:
            wanted = str(expected).strip().lower()
            return wanted in [str(v).strip().lower() for v in values]
        return str(expected) in [str(v) for v in values]
    if isinstance(expected, bool):
        return bool(actual) is expected
    if isinstance(expected, list):
        return any(_scalar_equal(claim, item, actual) for item in expected)
    return _scalar_equal(claim, expected, actual)


def _agrees_to_stated_precision(expected: Any, actual: Any) -> bool:
    """The build's number, rounded to as many figures as the claim states.

    `"4.78E+03"` against 4775.290751488173 is met: to three significant figures
    the build says 4.78E+03, which is what JRC 130796's Table 6 prints.  The
    same claim against 4.7752 or 47752 is unmet, because rounding does not move
    a decimal point -- an order-of-magnitude error, which is the whole of #49,
    fails here rather than being absorbed by a tolerance.
    """
    if isinstance(actual, bool) or not isinstance(actual, (int, float)):
        return False
    figures = significant_figures(str(expected))
    if not figures:
        return False
    try:
        wanted = float(expected)
    except (TypeError, ValueError):
        return False
    return _to_significant_figures(float(actual), figures) == _to_significant_figures(
        wanted, figures
    )


def _to_significant_figures(value: float, figures: int) -> str:
    """*value* rendered to *figures* significant figures, canonically.

    Compared as strings rather than as floats because the point is the digits:
    `float(f"{x:.3e}")` reintroduces binary rounding at the boundary, and two
    numbers that print identically would be free to compare unequal.
    """
    return f"{value:.{max(figures - 1, 0)}e}"


def _scalar_equal(claim: str, expected: Any, actual: Any) -> bool:
    if isinstance(expected, str) and isinstance(actual, str):
        if claim in _CASE_INSENSITIVE:
            return expected.strip().lower() == actual.strip().lower()
        return expected.strip() == actual.strip()
    return expected == actual


def _distinct(values: list[Any]) -> list[Any]:
    seen: list[Any] = []
    for value in values:
        rendered = list(value) if isinstance(value, tuple) else value
        if rendered not in seen:
            seen.append(rendered)
    return seen


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------

def _evidence(
    expectation: Expectation, rows: list[dict[str, Any]]
) -> tuple[dict[str, Any], ...]:
    """Why the build did what it did, for the rows that failed.

    For a source row this is the merge's own trace, which already holds every
    candidate the selector considered with the score it gave.  That trace is
    what a matching change is designed against -- it is enough to replay a
    proposed rule over the last build and count what moves -- so a report that
    stopped at "unmet" would be throwing away the useful half.
    """
    if expectation.kind != "source_row":
        return tuple(_trim(row) for row in rows[:EVIDENCE_ROWS])

    out = []
    for row in rows[:EVIDENCE_ROWS]:
        detail = row.get("_detail") or {}
        algorithm = detail.get("algorithm_details") or {}
        candidates = (
            algorithm.get("top_candidates")
            or detail.get("candidate_elementary_flows")
            or []
        )
        out.append({
            "source_uuid": row["source_uuid"],
            "source_name": row["source_name"],
            "source_context": row["source_context"],
            "source_unit": row["source_unit"],
            "source_cas": row["source_cas"],
            "outcome": row["outcome"],
            "reason": row["reason"] or detail.get("selector_reason", ""),
            "basis": row["basis"],
            "target_uuid": row["target_uuid"],
            "target_name": row["target_name"],
            "target_context_display": row["target_context_display"],
            "target_unit": row["target_unit"],
            "target_characterised": row["target_characterised"],
            "published": row["published"],
            "selector_model": algorithm.get("selector_model", ""),
            "candidate_count": algorithm.get("elementary_candidate_count"),
            "scored_candidates": [
                {
                    "elementary_flow_id": c.get("elementary_flow_id", ""),
                    "score": c.get("score"),
                    "unit": c.get("unit", ""),
                    "context": c.get("context", []),
                }
                for c in candidates[:EVIDENCE_CANDIDATES]
                if isinstance(c, dict)
            ],
        })
    return tuple(out)


def _trim(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if not key.startswith("_")}


def _describe_selector(expectation: Expectation) -> str:
    parts = ", ".join(f"{key}={value!r}" for key, value in sorted(expectation.selector.items()))
    return f"{expectation.kind}({parts})"
