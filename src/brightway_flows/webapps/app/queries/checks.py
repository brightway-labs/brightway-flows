"""Six checks over the finished list, each looking for one kind of error.

Two of them -- shared labels and formula mismatches -- are false-merge
detectors: a name on two substances, or a formula that does not match the
substance, means an identity resolution went wrong upstream. Anything they find
is a real error rather than a stylistic one.

Three test invariants: one row per substance and context, no substance claiming
another's identifiers, and a radioactive flow knowing which isotope it is.

The sixth reads the merge's own report rather than the list: a source row
measured in something other than the flow it landed on. The merge has recorded
that on every outcome since long before there was a page for it, and nothing
displayed it, so 143 flagged rows a curator was meant to look at had nowhere to
be looked at (#78).

`formula_mismatches` reads the table Phase 0 precomputed. The consensus app
loaded the whole ChEBI index on every request to this page, over data that only
changes when the pipeline runs.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any

from brightway_flows.domain.vocabulary import (
    CHEMINF_CAS_REGISTRY_NUMBER,
    CHEMROF_MOLECULAR_FORMULA,
    PROV_HAD_PRIMARY_SOURCE_CURIE,
    PROV_WAS_DERIVED_FROM_CURIE,
    PROV_WAS_GENERATED_BY_CURIE,
)
from brightway_flows.pipeline.review_tables import FORMULA_MISMATCH_THRESHOLD
from brightway_flows.webapps.app.db import table_exists
from brightway_flows.webapps.app.labels import local_name, predicate_label
from brightway_flows.webapps.app.queries.common import (
    PAGE_SIZE,
    Page,
    clamp_page,
    load_json,
)
from brightway_flows.webapps.app.queries.flows import _classification_values
# The one answer to "which run is the latest", rather than a second one that
# could disagree with the merge section about which run a page is describing.
from brightway_flows.webapps.app.queries.merge import (
    _latest_run_id as latest_merge_run_id,
)

#: A name is shared when it is the preferred label of one substance and the
#: preferred or alternative label of another. Both sides are folded to lower
#: case and trimmed, because `HCFC-140` and `Hcfc-140` are the same claim.
_ALL_LABELS = """
    WITH all_labels AS (
        SELECT lower(trim(pref_label_value)) AS norm,
               pref_label_value AS label,
               flow_object_id,
               'preferred' AS kind
        FROM flow_objects
        WHERE coalesce(trim(pref_label_value), '') <> ''
        UNION ALL
        SELECT lower(trim(CASE j.type WHEN 'object'
                   THEN json_extract(j.value, '$."@value"') ELSE j.value END)) AS norm,
               CASE j.type WHEN 'object'
                   THEN json_extract(j.value, '$."@value"') ELSE j.value END AS label,
               fo.flow_object_id,
               'alternative' AS kind
        FROM flow_objects fo, json_each(fo.alt_label_json) j
        WHERE fo.alt_label_json IS NOT NULL
          AND coalesce(CASE j.type WHEN 'object'
                  THEN json_extract(j.value, '$."@value"') ELSE j.value END, '') <> ''
    )
"""


@dataclass
class Check:
    """One entry on the checks index."""

    key: str
    title: str
    finds: str
    count: int | None = None
    available: bool = True


@dataclass
class LabelClaim:
    flow_object_id: str
    name: str = ""
    kind: str = ""


@dataclass
class SharedLabel:
    label: str
    claims: list[LabelClaim] = field(default_factory=list)

    @property
    def substances(self) -> int:
        return len({claim.flow_object_id for claim in self.claims})


@dataclass
class FormulaOrigin:
    """One formula a substance carries, and where it came from.

    The check compares two strings and says they disagree.  It cannot say why,
    and without that the page is a list of pairs a reader has no way to rule
    on: `H2` against `T2` on hydrogen-3 is PubChem describing the bulk gas and
    ChEBI describing the nuclide, which is a real answer, and `CH8N2O3` against
    `CO3.2H4N` on ammonium carbonate is two spellings of one salt, which is a
    different one.

    *attested_by* is every pass that arrived at this same string; *derived_from*
    is the field of the external record each of them read, which is the level of
    detail that distinguishes "ChEBI's stated formula" from "computed from a
    SMILES we hold".
    """

    formula: str
    attested_by: list[str] = field(default_factory=list)
    derived_from: list[str] = field(default_factory=list)
    #: Whether this is the formula the check compared.  A substance whose
    #: structure is not settled carries several and the check reads the first,
    #: so marking it says which of the two columns the row is about.
    published: bool = False


@dataclass
class FormulaMismatchRow:
    flow_object_id: str
    name: str = ""
    flow_formula: str = ""
    threshold: float = FORMULA_MISMATCH_THRESHOLD
    matches: list[dict[str, Any]] = field(default_factory=list)
    #: Every formula this substance holds and the pass that put it there.  Read
    #: at request time from `flow_objects.properties_json` rather than stored in
    #: `formula_mismatches`: it is 50 rows a page and one JSON column, and a
    #: column of its own would be a schema change and a rebuild for something
    #: the database already says.
    origins: list[FormulaOrigin] = field(default_factory=list)

    @property
    def worst_score(self) -> float:
        return min((m["score"] for m in self.matches), default=1.0)


@dataclass
class DuplicateContext:
    """Several flows for one substance in one context, which must not happen."""

    flow_object_id: str
    name: str = ""
    context_display: str = ""
    #: What "one context" means here.  The group is keyed on this and not on
    #: `context_display`, which is a rendering: `envi-air-indr-unkn` and
    #: `envi-air-unkn` both printed "Environmental → Air → Unknown", so a
    #: substance's indoor and unspecified air flows -- two contexts, correctly
    #: kept apart everywhere else -- were read as duplicates of each other
    #: (#284).
    context_iri: str = ""
    flows: list[dict[str, Any]] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.flows)


@dataclass
class DuplicationIssue:
    """A substance whose identifiers or labels collide with themselves."""

    flow_object_id: str
    name: str = ""
    duplicate_cas: list[str] = field(default_factory=list)
    duplicate_alt_labels: list[str] = field(default_factory=list)
    cas_in_alt_labels: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return (
            len(self.duplicate_cas)
            + len(self.duplicate_alt_labels)
            + len(self.cas_in_alt_labels)
        )


@dataclass
class IsotopeGap:
    uuid: str
    name: str = ""
    flow_object_id: str = ""
    source: str = ""
    unit: str = ""
    context_display: str = ""
    #: Why the flow has no isotope record, from `isotope_lookup.reason`.  The
    #: gaps are not one kind of thing: an aggregate has no nuclide to name and
    #: never will, a label naming a nuclide that does not exist is a correction
    #: someone can write, and a record withheld by a consistency check is a
    #: disagreement between two sources.  Listing all three together with no
    #: reason is what left `Palladium-234m` in this table for months.
    reason: str = ""
    #: The nuclide the label claimed, where it claimed one.
    claimed_nuclide: str = ""


def index(connection: sqlite3.Connection) -> list[Check]:
    """Every check and what it currently finds, for the section landing page.

    Counted up front so a reader can see where the work is without opening five
    pages. `available` is False where the database predates a table, and the
    page says so rather than showing a zero.
    """
    formula_available = table_exists(connection, "formula_mismatches")
    merge_available = table_exists(connection, "merge_outcomes")
    return [
        Check(
            key="shared-labels",
            title="Shared labels",
            finds="A name claimed by more than one substance",
            count=_shared_label_total(connection),
        ),
        Check(
            key="formula-mismatches",
            title="Formula mismatches",
            finds="A substance whose formula disagrees with a ChEBI record it cites",
            count=(
                int(
                    connection.execute(
                        "SELECT count(DISTINCT flow_object_id) FROM formula_mismatches"
                    ).fetchone()[0]
                )
                if formula_available
                else None
            ),
            available=formula_available,
        ),
        Check(
            key="duplicate-contexts",
            title="Duplicate contexts",
            finds="More than one flow for a substance in one context",
            count=_duplicate_context_total(connection),
        ),
        Check(
            key="unit-disagreements",
            title="Unit disagreements",
            finds="A source row measured in something other than the flow it landed on",
            count=(
                _unit_disagreement_total(connection)
                if merge_available else None
            ),
            available=merge_available,
        ),
        Check(
            key="duplication-report",
            title="Duplication report",
            finds="Repeated CAS numbers and labels within one substance",
            count=None,
        ),
        Check(
            key="isotope-gaps",
            title="Isotope gaps",
            finds="A kBq flow carrying no isotope metadata",
            count=_isotope_gap_total(connection),
        ),
    ]


def _shared_label_total(connection: sqlite3.Connection) -> int:
    return int(
        connection.execute(
            f"{_ALL_LABELS} SELECT count(*) FROM ("
            "SELECT norm FROM all_labels GROUP BY norm "
            "HAVING count(DISTINCT flow_object_id) > 1)"
        ).fetchone()[0]
    )


def shared_labels(
    connection: sqlite3.Connection, *, query: str = "", page: int = 1
) -> Page[SharedLabel]:
    where, params = ("WHERE norm LIKE ?", [f"%{query.lower()}%"]) if query else ("", [])
    total = int(
        connection.execute(
            f"{_ALL_LABELS} SELECT count(*) FROM ("
            f"SELECT norm FROM all_labels {where} GROUP BY norm "
            "HAVING count(DISTINCT flow_object_id) > 1)",
            params,
        ).fetchone()[0]
    )
    number = clamp_page(page, total)
    groups = connection.execute(
        f"{_ALL_LABELS} SELECT norm, min(label) AS label FROM all_labels {where} "
        "GROUP BY norm HAVING count(DISTINCT flow_object_id) > 1 "
        "ORDER BY lower(min(label)) LIMIT ? OFFSET ?",
        [*params, PAGE_SIZE, (number - 1) * PAGE_SIZE],
    ).fetchall()

    rows: list[SharedLabel] = []
    for group in groups:
        # `owner`, not `fo`: the CTE above already binds `fo`, and reusing it
        # here resolved `fo.alt_label_json` against the wrong scope.
        claims = connection.execute(
            f"{_ALL_LABELS} "
            "SELECT DISTINCT all_labels.flow_object_id, all_labels.kind, "
            "owner.pref_label_value FROM all_labels "
            "JOIN flow_objects owner ON owner.flow_object_id = all_labels.flow_object_id "
            "WHERE all_labels.norm = ? ORDER BY lower(owner.pref_label_value)",
            (group["norm"],),
        ).fetchall()
        rows.append(SharedLabel(
            label=group["label"],
            claims=[
                LabelClaim(
                    flow_object_id=claim["flow_object_id"],
                    name=claim["pref_label_value"] or "",
                    kind=claim["kind"],
                )
                for claim in claims
            ],
        ))
    return Page(rows=rows, total=total, number=number)


def formula_mismatches(
    connection: sqlite3.Connection, *, query: str = "", page: int = 1
) -> Page[FormulaMismatchRow]:
    """Precomputed pairs, grouped back under their substance for display."""
    if not table_exists(connection, "formula_mismatches"):
        return Page()

    where, params = "", []
    if query:
        like = f"%{query.lower()}%"
        where = (
            "WHERE lower(pref_label) LIKE ? OR lower(flow_object_id) LIKE ? "
            "OR lower(chebi_label) LIKE ? OR lower(chebi_formula) LIKE ?"
        )
        params = [like, like, like, like]

    ids = connection.execute(
        "SELECT flow_object_id, min(similarity_score) AS worst, min(pref_label) AS name "
        f"FROM formula_mismatches {where} GROUP BY flow_object_id "
        "ORDER BY worst, lower(min(pref_label))",
        params,
    ).fetchall()
    total = len(ids)
    number = clamp_page(page, total)
    window = ids[(number - 1) * PAGE_SIZE : number * PAGE_SIZE]

    rows: list[FormulaMismatchRow] = []
    for entry in window:
        matches = connection.execute(
            "SELECT * FROM formula_mismatches WHERE flow_object_id = ? "
            "ORDER BY similarity_score",
            (entry["flow_object_id"],),
        ).fetchall()
        first = matches[0]
        supplied = _supplied_by_source(connection, entry["flow_object_id"])
        rows.append(FormulaMismatchRow(
            flow_object_id=entry["flow_object_id"],
            name=first["pref_label"] or "",
            flow_formula=first["flow_formula"] or "",
            threshold=float(first["threshold"]),
            origins=_formula_origins(
                connection, entry["flow_object_id"], first["flow_formula"] or ""
            ),
            matches=[
                {
                    "chebi_id": match["chebi_id"],
                    "label": match["chebi_label"] or "",
                    "formula": match["chebi_formula"] or "",
                    "cas_numbers": load_json(match["chebi_cas_numbers_json"], []),
                    "score": float(match["similarity_score"]),
                    "url": _chebi_url(match["chebi_id"]),
                    # Why this record is cited at all.  The check compares the
                    # substance against every ChEBI record it names as a primary
                    # source, and a reader deciding whether the citation is the
                    # error needs to know what else was taken from it.
                    "supplied": supplied.get(match["chebi_id"], []),
                }
                for match in matches
            ],
        ))
    return Page(rows=rows, total=total, number=number)


def _chebi_url(chebi_id: Any) -> str:
    """The ChEBI page for an accession, so the record can be read rather than
    reconstructed from an IRI printed on the page."""
    accession = str(chebi_id or "").rsplit("/", 1)[-1].replace("_", ":")
    if not accession.startswith("CHEBI:"):
        return ""
    return f"https://www.ebi.ac.uk/chebi/searchId.do?chebiId={accession}"


def _formula_origins(
    connection: sqlite3.Connection, flow_object_id: str, published: str
) -> list[FormulaOrigin]:
    """Every molecular formula on one substance, and the pass behind each.

    Read from the serialised property, which is an external payload and parsed
    where it is read (`AGENTS.md`).  Three keys matter and all three are
    optional: `@value` is one string or a list of them, `attested_by` maps each
    of them to the passes that arrived at it, and `provenance` says what each of
    those passes read.  A substance written before any of them existed has a
    bare string and no story, and the page shows the string.
    """
    row = connection.execute(
        "SELECT properties_json FROM flow_objects WHERE flow_object_id = ?",
        (flow_object_id,),
    ).fetchone()
    if row is None:
        return []
    entry = load_json(row["properties_json"], {}).get(CHEMROF_MOLECULAR_FORMULA)
    if not isinstance(entry, dict):
        return []

    raw = entry.get("@value")
    values = (
        [raw] if isinstance(raw, str)
        else [value for value in (raw or []) if isinstance(value, str)]
    )
    attested = entry.get("attested_by")
    attested = attested if isinstance(attested, dict) else {}
    # Keyed by the pass name, which is what `attested_by` names a value with.
    by_pass: dict[str, dict[str, Any]] = {}
    for record in entry.get("provenance") or []:
        if isinstance(record, dict) and record.get(PROV_WAS_GENERATED_BY_CURIE):
            by_pass[str(record[PROV_WAS_GENERATED_BY_CURIE])] = record

    origins: list[FormulaOrigin] = []
    for value in values:
        passes = [str(name) for name in (attested.get(value) or [])]
        records = [by_pass[name] for name in passes if name in by_pass]
        origins.append(FormulaOrigin(
            formula=value,
            attested_by=passes,
            derived_from=[
                str(record[PROV_WAS_DERIVED_FROM_CURIE])
                for record in records
                if record.get(PROV_WAS_DERIVED_FROM_CURIE)
            ],
            published=value == published,
        ))
    return origins


def _supplied_by_source(
    connection: sqlite3.Connection, flow_object_id: str
) -> dict[str, list[str]]:
    """What each cited record gave this substance, keyed by the record's IRI.

    Read off the provenance the enrichment already writes on every property and
    every cross-reference: a record named as `prov:hadPrimarySource` supplied
    whatever that entry is.  Answering "why is this ChEBI record on this
    substance at all?" is most of deciding whether a formula mismatch is a bad
    formula or a bad citation.
    """
    row = connection.execute(
        "SELECT properties_json, references_json FROM flow_objects "
        "WHERE flow_object_id = ?",
        (flow_object_id,),
    ).fetchone()
    if row is None:
        return {}

    supplied: dict[str, set[str]] = {}

    def record(provenance: Any, what: str) -> None:
        if not isinstance(provenance, dict):
            return
        for source in provenance.get(PROV_HAD_PRIMARY_SOURCE_CURIE) or []:
            supplied.setdefault(str(source), set()).add(what)

    for predicate, entry in (load_json(row["properties_json"], {}) or {}).items():
        if not isinstance(entry, dict):
            continue
        for provenance in entry.get("provenance") or []:
            record(provenance, predicate_label(predicate) or local_name(predicate))

    references = load_json(row["references_json"], [])
    for reference in references if isinstance(references, list) else []:
        if isinstance(reference, dict):
            record(reference.get("provenance"), "a cross-reference")

    return {source: sorted(what) for source, what in supplied.items()}


def _duplicate_context_total(connection: sqlite3.Connection) -> int:
    return int(
        connection.execute(
            "SELECT count(*) FROM (SELECT flow_object_id, context_iri "
            "FROM elementary_flows WHERE coalesce(is_deprecated, 0) = 0 "
            "AND coalesce(flow_object_id, '') <> '' "
            "GROUP BY flow_object_id, context_iri HAVING count(*) > 1)"
        ).fetchone()[0]
    )


def duplicate_contexts(
    connection: sqlite3.Connection, *, query: str = "", page: int = 1
) -> Page[DuplicateContext]:
    """The invariant: one substance, one context, one flow.

    Deprecated flows are excluded. A duplicate that has already been deprecated
    is a duplicate that was found and dealt with, and leaving it here would make
    the page report its own fixes.

    "One context" is the context IRI. It was the printed name until #284, and
    two contexts shared one: `Environmental → Air → Unknown` stood for both
    indoor air and air of unstated height. Every substance holding one of each
    -- 6,750 of them -- was reported here, 98.6% of the page, and 14 real
    duplicates were swallowed into those oversized groups rather than listed as
    their own rows.
    """
    where = [
        "coalesce(ef.is_deprecated, 0) = 0",
        "coalesce(ef.flow_object_id, '') <> ''",
    ]
    params: list[Any] = []
    if query:
        like = f"%{query.lower()}%"
        where.append(
            "(lower(fo.pref_label_value) LIKE ? OR lower(ef.flow_object_id) LIKE ? "
            "OR lower(ef.context_display) LIKE ?)"
        )
        params.extend([like, like, like])
    where_sql = " AND ".join(where)

    groups = connection.execute(
        "SELECT ef.flow_object_id, ef.context_iri, "
        "min(ef.context_display) AS context_display, "
        "min(fo.pref_label_value) AS name, count(*) AS n "
        "FROM elementary_flows ef "
        "LEFT JOIN flow_objects fo ON fo.flow_object_id = ef.flow_object_id "
        f"WHERE {where_sql} GROUP BY ef.flow_object_id, ef.context_iri "
        "HAVING count(*) > 1 ORDER BY n DESC, lower(min(fo.pref_label_value))",
        params,
    ).fetchall()
    total = len(groups)
    number = clamp_page(page, total)
    window = groups[(number - 1) * PAGE_SIZE : number * PAGE_SIZE]

    rows: list[DuplicateContext] = []
    for group in window:
        flows = connection.execute(
            "SELECT uuid, source, unit, pref_label_value FROM elementary_flows "
            "WHERE flow_object_id = ? AND context_iri = ? "
            "AND coalesce(is_deprecated, 0) = 0 ORDER BY lower(source), uuid",
            (group["flow_object_id"], group["context_iri"]),
        ).fetchall()
        rows.append(DuplicateContext(
            flow_object_id=group["flow_object_id"],
            name=group["name"] or "",
            context_display=group["context_display"] or "",
            context_iri=group["context_iri"] or "",
            flows=[
                {
                    "uuid": flow["uuid"],
                    "source": flow["source"] or "",
                    "unit": flow["unit"] or "",
                    "name": flow["pref_label_value"] or "",
                }
                for flow in flows
            ],
        ))
    return Page(rows=rows, total=total, number=number)


def duplication_report(
    connection: sqlite3.Connection, *, query: str = "", page: int = 1
) -> Page[DuplicationIssue]:
    """A substance colliding with itself.

    Three findings, all of them signals that two substances were merged into
    one: the same CAS listed twice, the same alternative label twice, or a CAS
    number sitting in the label list where a name should be.

    Computed in Python rather than SQL because it compares list members within a
    JSON column, which SQL can do but not readably. The set is 7,660 rows.
    """
    where, params = "", []
    if query:
        like = f"%{query.lower()}%"
        where = "WHERE lower(pref_label_value) LIKE ? OR lower(flow_object_id) LIKE ?"
        params = [like, like]

    issues: list[DuplicationIssue] = []
    for row in connection.execute(
        "SELECT flow_object_id, pref_label_value, classifications_json, alt_label_json "
        f"FROM flow_objects {where} ORDER BY lower(pref_label_value)",
        params,
    ):
        classifications = load_json(row["classifications_json"], {})
        cas = _classification_values(classifications, CHEMINF_CAS_REGISTRY_NUMBER)
        alt_values = [
            item.get("@value") if isinstance(item, dict) else item
            for item in load_json(row["alt_label_json"], [])
        ]
        alt_values = [str(v) for v in alt_values if isinstance(v, str) and v.strip()]

        duplicate_cas = sorted({v for v in cas if cas.count(v) > 1})
        lowered = [v.lower() for v in alt_values]
        duplicate_alt = sorted({v for v in alt_values if lowered.count(v.lower()) > 1})
        cas_as_label = sorted(set(cas) & {v.strip() for v in alt_values})

        if duplicate_cas or duplicate_alt or cas_as_label:
            issues.append(DuplicationIssue(
                flow_object_id=row["flow_object_id"],
                name=row["pref_label_value"] or "",
                duplicate_cas=duplicate_cas,
                duplicate_alt_labels=duplicate_alt,
                cas_in_alt_labels=cas_as_label,
            ))

    issues.sort(key=lambda issue: (-issue.total, issue.name.lower()))
    total = len(issues)
    number = clamp_page(page, total)
    return Page(
        rows=issues[(number - 1) * PAGE_SIZE : number * PAGE_SIZE],
        total=total,
        number=number,
    )


_ISOTOPE_GAP_WHERE = (
    "lower(trim(ef.unit)) = 'kbq' AND ("
    "json_type(fo.properties_json, '$.isotope') IS NULL "
    "OR json_type(fo.properties_json, '$.isotope') = 'null')"
)


def _isotope_gap_total(connection: sqlite3.Connection) -> int:
    return int(
        connection.execute(
            "SELECT count(*) FROM elementary_flows ef "
            "LEFT JOIN flow_objects fo ON fo.flow_object_id = ef.flow_object_id "
            f"WHERE {_ISOTOPE_GAP_WHERE}"
        ).fetchone()[0]
    )


def isotope_gaps(
    connection: sqlite3.Connection, *, query: str = "", source: str = "", page: int = 1
) -> Page[IsotopeGap]:
    """A flow measured in becquerels that does not say which isotope it is.

    The unit is the tell: an activity has to be an activity *of* something, and
    a kBq flow with no isotope metadata cannot be converted, characterised or
    compared.
    """
    where = [_ISOTOPE_GAP_WHERE]
    params: list[Any] = []
    if source:
        where.append("ef.source = ?")
        params.append(source)
    if query:
        like = f"%{query.lower()}%"
        where.append(
            "(lower(ef.pref_label_value) LIKE ? OR lower(ef.uuid) LIKE ? "
            "OR lower(ef.flow_object_id) LIKE ?)"
        )
        params.extend([like, like, like])
    where_sql = " AND ".join(where)

    total = int(
        connection.execute(
            "SELECT count(*) FROM elementary_flows ef "
            "LEFT JOIN flow_objects fo ON fo.flow_object_id = ef.flow_object_id "
            f"WHERE {where_sql}",
            params,
        ).fetchone()[0]
    )
    number = clamp_page(page, total)
    rows = connection.execute(
        "SELECT ef.uuid, ef.pref_label_value, ef.flow_object_id, ef.source, "
        "ef.unit, ef.context_display, "
        "json_extract(fo.properties_json, '$.isotope_lookup.reason') AS reason, "
        "json_extract(fo.properties_json, '$.isotope_lookup.claimed_nuclide') "
        "  AS claimed_nuclide "
        "FROM elementary_flows ef "
        "LEFT JOIN flow_objects fo ON fo.flow_object_id = ef.flow_object_id "
        f"WHERE {where_sql} ORDER BY lower(ef.pref_label_value) LIMIT ? OFFSET ?",
        [*params, PAGE_SIZE, (number - 1) * PAGE_SIZE],
    ).fetchall()
    return Page(
        rows=[
            IsotopeGap(
                uuid=row["uuid"],
                name=row["pref_label_value"] or "",
                flow_object_id=row["flow_object_id"] or "",
                source=row["source"] or "",
                unit=row["unit"] or "",
                context_display=row["context_display"] or "",
                reason=row["reason"] or "",
                claimed_nuclide=row["claimed_nuclide"] or "",
            )
            for row in rows
        ],
        total=total,
        number=number,
    )


def isotope_gap_sources(connection: sqlite3.Connection) -> list[str]:
    return [
        row["source"]
        for row in connection.execute(
            "SELECT DISTINCT ef.source AS source FROM elementary_flows ef "
            "LEFT JOIN flow_objects fo ON fo.flow_object_id = ef.flow_object_id "
            f"WHERE {_ISOTOPE_GAP_WHERE} AND coalesce(ef.source, '') <> '' "
            "ORDER BY lower(ef.source)"
        )
    ]


@dataclass
class UnitDisagreement:
    """One source row whose unit is not the unit of the flow it landed on."""

    source_uuid: str
    source_name: str = ""
    source_unit: str = ""
    source_list: str = ""
    outcome: str = ""
    target_uuid: str = ""
    target_name: str = ""
    target_unit: str = ""
    #: Every unit the rows of a created flow offered, where this row is one of
    #: them.  Empty for a matched row: there was no group, only a target.
    offered_units: list[str] = field(default_factory=list)
    #: `curator`, `published_unit`, `unit_table` or `unresolved` for a created
    #: flow; empty for a matched one.
    decided_by: str = ""

    @property
    def kind(self) -> str:
        """Which question this row failed, in the words the two ask.

        A matched row disagrees with a flow that already existed.  A created
        row's group disagreed with itself and one unit had to be chosen.
        """
        return "created" if self.outcome == "created" else "matched"

    @property
    def needs_a_decision(self) -> bool:
        """Nobody has chosen, and the unit table could not."""
        return self.decided_by == "unresolved"

    @property
    def badge(self) -> str:
        """The tag this row carries, which is also what the quick filter selects.

        One property read by the template and by the filter, so a chip reading
        "23 needs a decision" cannot select a different 23 from the rows drawing
        that badge.
        """
        return "needs-a-decision" if self.needs_a_decision else "settled"


def _unit_disagreement_total(connection: sqlite3.Connection) -> int:
    run_id = latest_merge_run_id(connection)
    if not run_id:
        return 0
    return int(
        connection.execute(
            "SELECT count(*) FROM merge_outcomes "
            "WHERE run_id = ? AND has_unit_mismatch = 1",
            (run_id,),
        ).fetchone()[0]
    )


#: The badges the unit-disagreement table draws, as quick filters.
#:
#: `settled` is every row that is not `needs-a-decision`, rather than a list of
#: the three ways a row can be settled: which of them settled it is the `Settled
#: by` column's job, and the question this control answers is the one the page
#: opens with -- "only `needs a decision` is asking for anything".
UNIT_DISAGREEMENT_BADGES: tuple[tuple[str, str], ...] = (
    ("needs-a-decision", "Needs a decision"),
    ("settled", "Settled"),
)


def unit_disagreement_badges(
    connection: sqlite3.Connection,
) -> tuple[list[tuple[str, str, int]], int]:
    """Each badge, its label and how many rows carry it, plus the total.

    Counted over the same rows the table pages through, so a chip reading 23
    selects 23 rows.  That means reading them: the badge is decided in Python
    off the outcome's payload, not by a column SQL can group on.
    """
    rows = _unit_disagreement_rows(connection)
    counted = {
        badge: sum(1 for row in rows if row.badge == badge)
        for badge, _ in UNIT_DISAGREEMENT_BADGES
    }
    return (
        [(badge, label, counted[badge]) for badge, label in UNIT_DISAGREEMENT_BADGES],
        len(rows),
    )


def _unit_disagreement_rows(
    connection: sqlite3.Connection, *, query: str = ""
) -> list[UnitDisagreement]:
    """Every flagged row of the latest run, in the order the page shows them."""
    run_id = latest_merge_run_id(connection)
    if not run_id:
        return []

    where = ["mo.run_id = ?", "mo.has_unit_mismatch = 1"]
    params: list[Any] = [run_id]
    if query:
        like = f"%{query.lower()}%"
        where.append(
            "(lower(mo.source_name) LIKE ? OR lower(mo.source_unit) LIKE ? "
            "OR lower(mo.list_name) LIKE ?)"
        )
        params.extend([like, like, like])
    where_sql = " AND ".join(where)

    # Joined rather than looked up per row: the flagged set is small but it is
    # the whole set, because the sort below reads a field only the payload has.
    rows = connection.execute(
        "SELECT mo.source_uuid, mo.source_name, mo.source_unit, mo.list_name, "
        "mo.list_version, mo.outcome, mo.target_elementary_flow_id, mo.detail_json, "
        "ef.pref_label_value AS target_name, ef.unit AS target_unit "
        "FROM merge_outcomes mo "
        "LEFT JOIN elementary_flows ef ON ef.uuid = mo.target_elementary_flow_id "
        f"WHERE {where_sql} "
        "ORDER BY lower(mo.list_name), lower(mo.source_name), mo.source_uuid",
        params,
    ).fetchall()

    disagreements: list[UnitDisagreement] = []
    for row in rows:
        decision = load_json(row["detail_json"], {}).get("unit_decision") or {}
        disagreements.append(UnitDisagreement(
            source_uuid=row["source_uuid"] or "",
            source_name=row["source_name"] or "",
            source_unit=row["source_unit"] or "",
            source_list=f"{row['list_name']} {row['list_version']}".strip(),
            outcome=row["outcome"] or "",
            target_uuid=row["target_elementary_flow_id"] or "",
            target_name=row["target_name"] or "",
            # The flow's own unit where the flow reached the list, and what the
            # merge decided where it did not: a run whose flows were never
            # written still says what it would have declared.
            target_unit=row["target_unit"] or str(decision.get("declared") or ""),
            offered_units=[str(u) for u in (decision.get("units") or [])],
            decided_by=str(decision.get("decided_by") or ""),
        ))

    # Undecided first: those are the only ones asking for anything.  Stable
    # within each group, because the SQL already ordered them.
    disagreements.sort(key=lambda row: not row.needs_a_decision)
    return disagreements


def unit_disagreements(
    connection: sqlite3.Connection,
    *,
    query: str = "",
    badge: str = "",
    page: int = 1,
) -> Page[UnitDisagreement]:
    """Source rows measured in something other than the flow they landed on.

    Scoped to the most recent run: an outcome is a statement about one merge,
    and showing every run at once would report the same row once per build.

    The ones that need a person are at the top -- a created flow whose rows
    disagreed and whose units the table could not choose between.  Everything
    below it has an answer already: a curated decision, the unit table's
    reference unit, or a reviewed entry in `unit-change-allowlist.json` for a
    matched row that was accepted rather than fixed.

    *badge* narrows to one of those two groups.  Sorting them to the top made
    the work findable on the first page and nowhere else; on page 4 of 143 rows
    a reader is reading settled rows and cannot tell how many are left.
    """
    disagreements = _unit_disagreement_rows(connection, query=query)
    if badge:
        disagreements = [row for row in disagreements if row.badge == badge]
    total = len(disagreements)
    number = clamp_page(page, total)
    window = disagreements[(number - 1) * PAGE_SIZE : number * PAGE_SIZE]
    return Page(rows=window, total=total, number=number)
