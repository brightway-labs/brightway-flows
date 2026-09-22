"""The review tables: schema, builders and writer.

Phase 0 of `plans/webapp-consolidation.md`.  Six side-car JSON files described
what a run did and what still needs a curator, and the review web applications
read them directly -- one of them 1.26 GB, parsed on every request.  Three of
those files stopped being written at all, and the pages reading them have shown
an empty state ever since without anyone noticing, because a missing file and
an empty file look the same from a Flask route.

They are now tables in `consensus-flows.sqlite3`, written by the same run that
writes `elementary_flows`.  A table cannot silently not exist: it is either
there with rows or there with none, and the difference is a query.

The records are in :mod:`brightway_flows.pipeline.review_records`; this
module holds the SQL, the builders that derive rows from what the run already
has in memory, and the writer.

Sizing.  `changelog` is the one table large enough to matter -- the file it
replaces is 1.26 GB for the `consensus_match` transformer alone.  Three
decisions keep it as small as it can honestly be: it holds one row per *edit*
rather than per affected flow, with `changelog_flows` naming the flows;
`provenance_activities` is a view over those two rather than a third copy of
their columns; and no table repeats the run id per row, because the database is
rewritten per run and `pipeline_runs` holds exactly one.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import orjson
import structlog

from brightway_flows.domain.context_registry import (
    UnknownContextIRIError,
    context_dict_for_iri,
    context_display_parts,
)
from brightway_flows.domain.labels import flow_label_value
from brightway_flows.domain.vocabulary import (
    CHEMROF_MOLECULAR_FORMULA,
    PROV_HAD_PRIMARY_SOURCE_CURIE,
)
from brightway_flows.filesystem import PUBCHEM_ELEMENTS_CACHE_FILEPATH
from brightway_flows.flow_layers.elements import BASE_REFERENCES_PROPERTY
from brightway_flows.pipeline.review_records import (
    ChangeEvent,
    ContextDefaultMapping,
    change_value_json,
    ElementCoverage,
    ElementStatus,
    FormulaMismatch,
    PipelineRun,
    ProvenanceActivity,
    ReviewQueue,
    RunStat,
    ReviewQueueItem,
    ReviewQueueProvider,
    Severity,
    StageTiming,
)
from brightway_flows.context_mapping import MANUAL_MAPPING_FILEPATH
from brightway_flows.pipeline.sqlite_schema import (
    insert_statement,
    recreate,
)

logger = structlog.get_logger(__name__)

#: Bumped when any table in this module changes shape.  Stored on the
#: `pipeline_runs` row, so a database can say which version wrote it.
REVIEW_SCHEMA_VERSION = 1

#: Below this, a flow object's formula and a ChEBI record's formula are treated
#: as describing different substances.  The same value the enrichment
#: transformer uses to reject a ChEBI-direct match, and the same one the webapp
#: hard-coded: Li vs HLi scores about 0.5, stereoisomers score 1.0.
FORMULA_MISMATCH_THRESHOLD = 0.55

#: ChEBI records are cited in a flow object's references as a primary source.
_CHEBI_IRI_PREFIX = "http://purl.obolibrary.org/obo/CHEBI_"

#: The mapping rules, a package data file rather than a run artifact.
#:
#: Imported rather than restated.  This module declared its own constant for the
#: same file, so `data/context-manual-mapping.json` had two paths pointing at it
#: -- and that file is the one the architecture doc already tells a story about,
#: where two stages reading different copies of a mapping is how the last one
#: went stale (#92).
CONTEXT_MAPPING_FILEPATH = MANUAL_MAPPING_FILEPATH

TABLES = (
    "pipeline_runs",
    "run_stats",
    "run_timings",
    "changelog",
    "changelog_flows",
    "review_queue",
    "formula_mismatches",
    "element_coverage",
    "context_default_mappings",
)

SCHEMA = (
    # Exactly one row.  `run_pipeline` deletes the database before it writes, so
    # a second row would mean two runs produced one file.
    """
    CREATE TABLE pipeline_runs (
        run_id TEXT PRIMARY KEY,
        timestamp TEXT NOT NULL,
        schema_version INTEGER NOT NULL,
        dry_run INTEGER NOT NULL DEFAULT 0,
        max_flows INTEGER,
        input_files_json TEXT NOT NULL DEFAULT '[]',
        transformer_names_json TEXT NOT NULL DEFAULT '[]',
        flow_count INTEGER NOT NULL DEFAULT 0,
        change_count INTEGER NOT NULL DEFAULT 0,
        git_commit TEXT NOT NULL DEFAULT '',
        git_dirty INTEGER NOT NULL DEFAULT 0
    )
    """,
    # What each stage of the run counted about its own work. Rows rather than a
    # blob on `pipeline_runs`, because the question is run-over-run: "386 of 387
    # objects typed" against last week's number is a regression detector, and
    # rows can be selected and charted where a blob has to be parsed and diffed.
    """
    CREATE TABLE run_stats (
        stage TEXT NOT NULL,
        key TEXT NOT NULL,
        value INTEGER NOT NULL,
        PRIMARY KEY (stage, key)
    )
    """,
    # How long each stage took.  A separate table from `run_stats` and not a
    # fourth column on it, because a count and a clock are compared in opposite
    # ways: two runs of the same code must produce identical counts, and cannot
    # produce identical durations.  Keeping them apart leaves `run_stats`
    # comparable row for row, and puts every volatile number in the one table
    # `tools/verify_run.py` masks -- which it does by column name, so the column
    # is called `duration_seconds` (`VOLATILE_KEYS`) and a build that reports
    # its own timings does not thereby report a difference between two runs of
    # identical code.
    """
    CREATE TABLE run_timings (
        stage TEXT NOT NULL,
        detail TEXT NOT NULL DEFAULT '',
        duration_seconds REAL NOT NULL,
        PRIMARY KEY (stage, detail)
    )
    """,
    # Every field change from every transformer, one row per *edit*.  The two
    # largest fields in the log belong to the flow object, and 94,433 flows
    # share 7,730 objects, so a row per affected flow stored the same payload a
    # dozen times over: 4.63 GiB of an 8.13 GiB file, 91.5% of it duplicate
    # (#253).  `number_change_events` explains the grouping.
    #
    # `flow_object_id` answers "what happened to this substance" directly.
    # "What happened to this flow" is `changelog_flows`, which is a join but a
    # cheap one -- it holds a uuid and a name, not a payload.
    """
    CREATE TABLE changelog (
        change_index INTEGER PRIMARY KEY,
        transformer TEXT NOT NULL,
        flow_object_id TEXT NOT NULL DEFAULT '',
        field TEXT NOT NULL,
        old_value_json TEXT NOT NULL,
        new_value_json TEXT NOT NULL,
        comment TEXT NOT NULL DEFAULT ''
    )
    """,
    # Which flows one edit landed on.  One row per (change, flow): 1,407,835
    # rows against `changelog`'s 273,384 on the 2026-08-07 build, and 88 MiB
    # against the 3.7 GiB it displaces.
    #
    # `entity_version` is the position of this edit in *this flow's* history,
    # counting from 1, and it is stored rather than derived.  The obvious
    # alternative -- `row_number() OVER (PARTITION BY flow ORDER BY
    # change_index)` -- is wrong, because `change_index` orders by an edit's
    # first appearance anywhere, not by when it reached this flow.  Measured on
    # the 2026-08-07 log that reorders 29,280 of 1,407,835 activities across
    # 14,539 flows: one flow's `prefLabel`, `name` and `synonyms` changes come
    # back as v2, v3, v1.  Since the versions chain -- each activity consumes
    # what the previous one produced -- a permuted order is not a cosmetic
    # difference, it asserts a history that did not happen.
    """
    CREATE TABLE changelog_flows (
        change_index INTEGER NOT NULL,
        elementary_flow_uuid TEXT NOT NULL,
        flow_name TEXT NOT NULL DEFAULT '',
        entity_version INTEGER NOT NULL,
        PRIMARY KEY (change_index, elementary_flow_uuid)
    )
    """,
    # One activity per (change, flow) -- a view, not a table.  `field` and
    # `transformer` were copies of `changelog` columns and `change_index` and
    # the flow uuid were copies of `changelog_flows` columns, so the only thing
    # the table held that its two sources did not was `entity_version` -- which
    # is one integer, and now lives on `changelog_flows`.  1,407,835 rows and
    # 0.17 GiB with its index, for one column (#253).
    #
    # Two flows touched by one edit share a `change_index`, and so an activity
    # IRI, which is what PROV-O means by one activity generating several
    # entities.
    """
    CREATE VIEW provenance_activities AS
    SELECT c.change_index AS change_index,
           f.elementary_flow_uuid AS elementary_flow_uuid,
           c.field AS field,
           c.transformer AS transformer,
           f.entity_version AS entity_version
    FROM changelog c
    JOIN changelog_flows f ON f.change_index = c.change_index
    """,
    """
    CREATE TABLE review_queue (
        queue_name TEXT NOT NULL,
        item_key TEXT NOT NULL,
        item_index INTEGER NOT NULL DEFAULT 0,
        title TEXT NOT NULL DEFAULT '',
        severity TEXT NOT NULL DEFAULT 'info',
        elementary_flow_uuid TEXT NOT NULL DEFAULT '',
        flow_object_id TEXT NOT NULL DEFAULT '',
        cas TEXT NOT NULL DEFAULT '',
        payload_json TEXT NOT NULL DEFAULT '{}',
        PRIMARY KEY (queue_name, item_key)
    )
    """,
    """
    CREATE TABLE formula_mismatches (
        flow_object_id TEXT NOT NULL,
        chebi_id TEXT NOT NULL,
        pref_label TEXT NOT NULL DEFAULT '',
        flow_formula TEXT NOT NULL DEFAULT '',
        chebi_label TEXT NOT NULL DEFAULT '',
        chebi_formula TEXT NOT NULL DEFAULT '',
        chebi_cas_numbers_json TEXT NOT NULL DEFAULT '[]',
        similarity_score REAL NOT NULL,
        threshold REAL NOT NULL,
        PRIMARY KEY (flow_object_id, chebi_id)
    )
    """,
    """
    CREATE TABLE element_coverage (
        atomic_number INTEGER PRIMARY KEY,
        symbol TEXT NOT NULL DEFAULT '',
        name TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL,
        flow_object_id TEXT NOT NULL DEFAULT '',
        pubchem_page_url TEXT NOT NULL DEFAULT ''
    )
    """,
    # Keyed on (source, raw context) because that is what the transformer looks
    # a flow up by; a second rule for the same pair would be unreachable.
    """
    CREATE TABLE context_default_mappings (
        source TEXT NOT NULL,
        source_context_json TEXT NOT NULL,
        context_iri TEXT NOT NULL,
        context_display TEXT NOT NULL DEFAULT '',
        comment TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (source, source_context_json)
    )
    """,
)

INDEXES = (
    "CREATE INDEX idx_run_stats_stage ON run_stats(stage)",
    # The flow lookup moves with the column.  The primary key on
    # `changelog_flows` leads with `change_index`, so the other direction --
    # "which edits touched this flow" -- needs its own index.
    "CREATE INDEX idx_changelog_flows_uuid ON changelog_flows(elementary_flow_uuid)",
    "CREATE INDEX idx_changelog_object ON changelog(flow_object_id)",
    "CREATE INDEX idx_changelog_transformer ON changelog(transformer)",
    "CREATE INDEX idx_changelog_field ON changelog(field)",
    # No index for `provenance_activities`: it is a view over `changelog_flows`,
    # whose own `idx_changelog_flows_uuid` is the index the one query that
    # filters it -- "the trail for this flow" -- needs.
    "CREATE INDEX idx_review_queue_name ON review_queue(queue_name, item_index)",
    "CREATE INDEX idx_review_queue_flow ON review_queue(elementary_flow_uuid)",
    "CREATE INDEX idx_review_queue_object ON review_queue(flow_object_id)",
    "CREATE INDEX idx_review_queue_cas ON review_queue(cas)",
    "CREATE INDEX idx_formula_mismatches_score ON formula_mismatches(similarity_score)",
    "CREATE INDEX idx_element_coverage_status ON element_coverage(status)",
    "CREATE INDEX idx_context_default_mappings_source "
    "ON context_default_mappings(source)",
)


#: Derived relations.  `provenance_activities` was a table until #253, so a
#: database written before that has it as one -- see :func:`_drop`.
VIEWS = ("provenance_activities",)


def create_review_tables(connection: sqlite3.Connection) -> None:
    """Drop and recreate every table and view in this module.

    The same call the flow tables are created by, and for the same reason: both
    are rewritten by every build, so both are dropped rather than emptied.  See
    `pipeline.sqlite_schema`, which also holds the reason the merge tables are
    not.
    """
    recreate(connection, relations=(*VIEWS, *TABLES), schema=SCHEMA)


# --------------------------------------------------------------------------
# builders -- deriving rows from what the run already holds


def number_change_events(
    changes: list[ChangeEvent],
    *,
    flow_object_id_by_uuid: dict[str, str],
) -> list[ChangeEvent]:
    """Assign `change_index` and `flow_object_id` to an applied change log.

    Both are properties of the run rather than of the change: the index is the
    position in the whole log, and the substance is resolved by the layering
    that runs after the transformer chain.  Mutates and returns the same list,
    because the caller has already paid to build it and nothing else holds a
    reference to the elements.

    One index per *edit*, not per affected flow
    -------------------------------------------
    `change_index` used to be `enumerate(changes)`, so every element got its
    own.  But the two largest fields in the log -- `altLabel` and `properties`,
    87% of its bytes -- belong to the flow object, and 94,433 elementary flows
    share 7,730 objects.  A transformer that edits one substance's synonym list
    therefore produced a dozen elements holding byte-identical payloads, and
    numbering them separately made them a dozen rows.  Stripping the catalogue
    labels off `Silicon Dioxide` wrote its 2.9 MiB before-and-after thirteen
    times: 37.6 MiB to record a single edit.

    So changes that agree on substance, field, transformer, both values *and*
    comment share an index.  They are one edit; the flows it landed on are
    recorded by `changelog_flows`, which stores a uuid and a name rather than a
    payload.  Grouping on the values as well as the field is what keeps this
    lossless: two flows of one substance whose `context` genuinely went to
    different places disagree on `new_value`, so they stay separate rows.

    The index is still dense, still 1-based, and still ordered by first
    application, so "later steps win" reads the same way it did.

    A change whose `flow_object_id` is empty cannot be grouped by substance and
    falls back to its own flow's identity.  No row on the 2026-08-07 build has
    one -- the layering resolves every flow -- but a change applied to a flow
    the layering dropped would, and silently merging those into one group would
    be wrong.
    """
    index_by_group: dict[tuple[str, ...], int] = {}
    for change in changes:
        change.flow_object_id = flow_object_id_by_uuid.get(change.uuid, "")
        group = (
            change.flow_object_id or f"uuid:{change.uuid}",
            change.field_name,
            change.transformer,
            change_value_json(change.old_value),
            change_value_json(change.new_value),
            change.comment,
        )
        if group not in index_by_group:
            index_by_group[group] = len(index_by_group) + 1
        change.change_index = index_by_group[group]
    return changes


def collect_review_queue_items(transformers: list[Any]) -> list[ReviewQueueItem]:
    """Every queue item the transformers in this run produced.

    Asks each transformer rather than naming them: the CLI used to call
    `export_review()` on four specific classes, found by `isinstance`, so a
    transformer that grew a queue produced nothing until someone added a fifth
    branch.  A transformer opts in by implementing
    :class:`~brightway_flows.pipeline.review_records.ReviewQueueProvider`.

    `item_index` is assigned here, per queue, so that a page can restore the
    order the run produced without the transformer having to count.
    """
    items: list[ReviewQueueItem] = []
    index_by_queue: dict[str, int] = {}
    for transformer in transformers:
        if not isinstance(transformer, ReviewQueueProvider):
            continue
        for item in transformer.review_queue_items():
            queue = str(item.queue_name)
            index_by_queue[queue] = index_by_queue.get(queue, 0) + 1
            item.item_index = index_by_queue[queue]
            items.append(item)
    return items


def _molecular_formula(properties: dict[str, Any]) -> str:
    """The molecular formula a flow object asserts, or an empty string.

    `properties` is a serialised flow-object payload, so it is read as a dict --
    an I/O boundary, per `AGENTS.md`.  The value may be a bare string or a list
    of them depending on which transformer wrote it last.
    """
    entry = properties.get(CHEMROF_MOLECULAR_FORMULA)
    if not isinstance(entry, dict):
        return ""
    raw = entry.get("@value")
    if isinstance(raw, list):
        return next((v for v in raw if isinstance(v, str) and v.strip()), "")
    return raw.strip() if isinstance(raw, str) else ""


def _cited_chebi_ids(references: Any) -> set[str]:
    """ChEBI identifiers a flow object cites as a primary source."""
    if not isinstance(references, list):
        return set()
    chebi_ids: set[str] = set()
    for reference in references:
        if not isinstance(reference, dict):
            continue
        provenance = reference.get("provenance")
        if not isinstance(provenance, dict):
            continue
        sources = provenance.get(PROV_HAD_PRIMARY_SOURCE_CURIE, [])
        if isinstance(sources, str):
            sources = [sources]
        if not isinstance(sources, list):
            continue
        for source in sources:
            if isinstance(source, str) and _CHEBI_IRI_PREFIX in source:
                chebi_ids.add(source.strip())
    return chebi_ids


def build_formula_mismatches(
    flow_objects: list[dict[str, Any]],
    *,
    threshold: float = FORMULA_MISMATCH_THRESHOLD,
) -> list[FormulaMismatch]:
    """Flow objects whose formula disagrees with a ChEBI record they cite.

    Returns an empty list when the ChEBI index is not on disk.  Precomputing
    this is the point of the table: the webapp loaded the whole index -- tens of
    thousands of records -- on every request to a page whose answer only changes
    when the pipeline runs.
    """
    # Imported here, not at module scope: `integrations.chebi` and
    # `transformers.enrich_references` both import from
    # `brightway_flows.pipeline`, which imports this module's caller.  A
    # module-level import would be a cycle.
    from brightway_flows.integrations.chebi import load_chebi_index
    from brightway_flows.transformers.enrich_references import (
        formula_similarity_score,
    )

    try:
        chebi_records = load_chebi_index()["records"]
    except FileNotFoundError:
        logger.info("skipped_formula_mismatches", reason="chebi index not downloaded")
        return []

    mismatches: list[FormulaMismatch] = []
    for row in flow_objects:
        properties = row.get("properties")
        flow_formula = _molecular_formula(properties if isinstance(properties, dict) else {})
        if not flow_formula:
            continue
        chebi_ids = _cited_chebi_ids(row.get("references"))
        if not chebi_ids:
            continue
        pref_label = flow_label_value(row) or ""
        flow_object_id = str(row.get("flow_object_id") or "")
        for chebi_id in sorted(chebi_ids):
            record = chebi_records.get(chebi_id, {})
            chebi_formula = record.get("formula") or ""
            if not chebi_formula:
                continue
            score = formula_similarity_score(flow_formula, chebi_formula)
            if score >= threshold:
                continue
            mismatches.append(
                FormulaMismatch(
                    flow_object_id=flow_object_id,
                    chebi_id=chebi_id,
                    similarity_score=round(score, 3),
                    threshold=threshold,
                    pref_label=pref_label,
                    flow_formula=flow_formula,
                    chebi_label=record.get("label") or "",
                    chebi_formula=chebi_formula,
                    chebi_cas_numbers=list(record.get("cas_numbers", [])),
                )
            )
    return mismatches


def build_element_coverage(
    flow_objects: list[dict[str, Any]],
) -> list[ElementCoverage]:
    """Every chemical element PubChem knows, and how the consensus list covers it.

    Returns an empty list when the PubChem element cache is not on disk.  An
    element is `linked` when some flow object carries its atomic number *and*
    that object references the base list; a flow object that references nothing
    is `not-linked-to-ef31`, and no flow object at all is `missing-flow-object`.

    That queue slug names the base list of the day it was minted.  It is
    user-visible in the review application and stored in the database, so
    renaming it is a data migration rather than a refactor (#14): the code
    around it stopped naming EF 3.1, the slug did not.
    """
    if not PUBCHEM_ELEMENTS_CACHE_FILEPATH.exists():
        logger.info(
            "skipped_element_coverage",
            reason="pubchem element cache not downloaded",
            path=str(PUBCHEM_ELEMENTS_CACHE_FILEPATH),
        )
        return []
    payload = orjson.loads(PUBCHEM_ELEMENTS_CACHE_FILEPATH.read_bytes())
    elements = payload.get("elements") if isinstance(payload, dict) else None
    if not isinstance(elements, list):
        return []

    objects_by_atomic_number: dict[int, list[dict[str, Any]]] = {}
    for row in flow_objects:
        properties = row.get("properties")
        if not isinstance(properties, dict):
            continue
        element = properties.get("element")
        if not isinstance(element, dict):
            continue
        atomic_number = element.get("atomic_number")
        if isinstance(atomic_number, int):
            objects_by_atomic_number.setdefault(atomic_number, []).append(row)

    coverage: list[ElementCoverage] = []
    for element in elements:
        if not isinstance(element, dict):
            continue
        atomic_number = element.get("atomic_number")
        if not isinstance(atomic_number, int):
            continue
        candidates = objects_by_atomic_number.get(atomic_number, [])
        status = ElementStatus.MISSING if not candidates else ElementStatus.NOT_LINKED
        flow_object_id = ""
        for candidate in candidates:
            candidate_id = str(candidate.get("flow_object_id") or "").strip()
            if not flow_object_id and candidate_id:
                flow_object_id = candidate_id
            if _references_base_list(candidate):
                status = ElementStatus.LINKED
                if candidate_id:
                    flow_object_id = candidate_id
                break
        coverage.append(
            ElementCoverage(
                atomic_number=atomic_number,
                symbol=str(element.get("symbol") or ""),
                name=str(element.get("name") or ""),
                status=status,
                flow_object_id=flow_object_id,
                pubchem_page_url=str(element.get("page_url") or ""),
            )
        )
    coverage.sort(key=lambda row: row.atomic_number)
    return coverage


def _references_base_list(flow_object: dict[str, Any]) -> bool:
    """Whether a flow-object payload points back at a base-list flow.

    The property key it reads is published, so it still says `ef31`; see the
    note on the queue slug in `build_element_coverage`.
    """
    properties = flow_object.get("properties")
    if not isinstance(properties, dict):
        return False
    references = properties.get(BASE_REFERENCES_PROPERTY)
    if not isinstance(references, dict):
        return False
    return bool(
        references.get("flow_object_ids") or references.get("elementary_flow_ids")
    )


def load_context_default_mappings(
    path: Path = CONTEXT_MAPPING_FILEPATH,
) -> list[ContextDefaultMapping]:
    """The default context-mapping rules, as records.

    Reads the same file and the same key as
    :class:`~brightway_flows.transformers.default_context_mapping.DefaultContextMappingTransformer`,
    so what the page shows is what the run applied.  Rules missing a source or a
    target IRI are dropped here exactly as the transformer drops them.
    """
    if not path.exists():
        logger.warning("context_mapping_file_missing", path=str(path))
        return []
    payload = orjson.loads(path.read_bytes())
    rules = payload.get("default_context_mappings") if isinstance(payload, dict) else None
    if not isinstance(rules, list):
        return []

    mappings: list[ContextDefaultMapping] = []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        source = rule.get("source")
        context_iri = rule.get("context_iri")
        if not (isinstance(source, str) and isinstance(context_iri, str) and context_iri):
            continue
        raw_context = rule.get("source_context")
        source_context = (
            [str(part) for part in raw_context if isinstance(part, str)]
            if isinstance(raw_context, list)
            else []
        )
        if not source_context:
            continue
        mappings.append(
            ContextDefaultMapping(
                source=source,
                source_context=source_context,
                context_iri=context_iri,
                context_display=_context_display(context_iri),
                comment=str(rule.get("comment") or ""),
            )
        )
    return mappings


def _context_display(context_iri: str) -> str:
    """The consensus context an IRI names, rendered for a table cell.

    Resolved through the context registry rather than from the mapping file's
    own copy of the context, so the page shows the vocabulary's answer -- the
    same one the transformer applies.  An IRI the vocabulary does not know is
    a rule that cannot fire; it renders as empty rather than raising, because
    the mapping file is curated by hand and a stale entry should be visible on
    the page rather than fatal to the build.
    """
    try:
        return " → ".join(context_display_parts(context_dict_for_iri(context_iri)))
    except UnknownContextIRIError:
        logger.warning("context_mapping_unknown_iri", context_iri=context_iri)
        return ""


# --------------------------------------------------------------------------
# writing


#: The columns each `INSERT` in `write_review_tables` fills, beside the
#: builder that produces the row.  One declaration rather than a list restated
#: inside the statement, which is a second copy of the `CREATE TABLE` and can
#: disagree with it in silence; `merge.store._OUTCOME_COLUMNS` has done it this
#: way since it was written.  See `pipeline.sqlite_schema.insert_statement`.
_RUN_COLUMNS = (
    "run_id", "timestamp", "schema_version", "dry_run", "max_flows",
    "input_files_json", "transformer_names_json", "flow_count", "change_count",
    "git_commit", "git_dirty",
)


def _run_row(run: PipelineRun) -> tuple[Any, ...]:
    return (
        run.run_id,
        run.timestamp,
        run.schema_version,
        int(run.dry_run),
        run.max_flows,
        orjson.dumps(run.input_files).decode(),
        orjson.dumps(run.transformer_names).decode(),
        run.flow_count,
        run.change_count,
        run.git_commit,
        int(run.git_dirty),
    )


_STAT_COLUMNS = ("stage", "key", "value")


def _stat_row(stat: RunStat) -> tuple[Any, ...]:
    return (stat.stage, stat.key, stat.value)


_TIMING_COLUMNS = ("stage", "detail", "duration_seconds")


def _timing_row(timing: StageTiming) -> tuple[Any, ...]:
    return (timing.stage, timing.detail, timing.duration_seconds)


_CHANGE_COLUMNS = (
    "change_index", "transformer", "flow_object_id", "field", "old_value_json",
    "new_value_json", "comment",
)


def _change_row(change: ChangeEvent) -> tuple[Any, ...]:
    return (
        change.change_index,
        change.transformer,
        change.flow_object_id,
        change.field_name,
        change_value_json(change.old_value),
        change_value_json(change.new_value),
        change.comment,
    )


_CHANGELOG_FLOW_COLUMNS = (
    "change_index", "elementary_flow_uuid", "flow_name", "entity_version",
)


def _changelog_flow_rows(changes: list[ChangeEvent]) -> list[tuple[Any, ...]]:
    """One row per (edit, flow), numbered by this flow's own history.

    Iterated in *application* order -- the order `apply_transformers` returned,
    which is the order things happened to the flow -- and not by
    `change_index`, which orders by an edit's first appearance anywhere.  That
    number becomes `entity_version`, and the PROV activities chain through it,
    so it has to be the order the flow actually changed.

    Deduplicated on `(change_index, uuid)` because that is the table's primary
    key: one edit reaching one flow is one row however many elements of the log
    carry it.  No pair repeats on the 2026-08-07 build.
    """
    rows: list[tuple[Any, ...]] = []
    version_by_uuid: dict[str, int] = {}
    seen: set[tuple[int, str]] = set()
    for change in changes:
        pair = (change.change_index, change.uuid)
        if pair in seen:
            continue
        seen.add(pair)
        version = version_by_uuid.get(change.uuid, 0) + 1
        version_by_uuid[change.uuid] = version
        rows.append((change.change_index, change.uuid, change.flow_name, version))
    return rows


def _deduplicated_change_rows(changes: list[ChangeEvent]) -> list[tuple[Any, ...]]:
    """One row per `change_index`, in index order.

    `number_change_events` gives every change of one edit the same index, so the
    list arriving here has a dozen elements per row to be written.  Taking the
    first of each is what turns 1,407,835 elements into 273,384 rows; they agree
    on every column this table keeps, by construction of the group key.
    """
    rows: dict[int, tuple[Any, ...]] = {}
    for change in changes:
        if change.change_index not in rows:
            rows[change.change_index] = _change_row(change)
    return [rows[index] for index in sorted(rows)]


_QUEUE_COLUMNS = (
    "queue_name", "item_key", "item_index", "title", "severity",
    "elementary_flow_uuid", "flow_object_id", "cas", "payload_json",
)


def _queue_row(item: ReviewQueueItem) -> tuple[Any, ...]:
    return (
        str(item.queue_name),
        item.item_key,
        item.item_index,
        item.title,
        str(item.severity),
        item.uuid,
        item.flow_object_id,
        item.cas,
        orjson.dumps(item.payload).decode(),
    )


_MISMATCH_COLUMNS = (
    "flow_object_id", "chebi_id", "pref_label", "flow_formula", "chebi_label",
    "chebi_formula", "chebi_cas_numbers_json", "similarity_score", "threshold",
)


def _mismatch_row(mismatch: FormulaMismatch) -> tuple[Any, ...]:
    return (
        mismatch.flow_object_id,
        mismatch.chebi_id,
        mismatch.pref_label,
        mismatch.flow_formula,
        mismatch.chebi_label,
        mismatch.chebi_formula,
        orjson.dumps(mismatch.chebi_cas_numbers).decode(),
        mismatch.similarity_score,
        mismatch.threshold,
    )


_COVERAGE_COLUMNS = (
    "atomic_number", "symbol", "name", "status", "flow_object_id",
    "pubchem_page_url",
)


def _coverage_row(coverage: ElementCoverage) -> tuple[Any, ...]:
    return (
        coverage.atomic_number,
        coverage.symbol,
        coverage.name,
        str(coverage.status),
        coverage.flow_object_id,
        coverage.pubchem_page_url,
    )


_MAPPING_COLUMNS = (
    "source", "source_context_json", "context_iri", "context_display", "comment",
)


def _mapping_row(mapping: ContextDefaultMapping) -> tuple[Any, ...]:
    return (
        mapping.source,
        orjson.dumps(mapping.source_context).decode(),
        mapping.context_iri,
        mapping.context_display,
        mapping.comment,
    )


def write_review_tables(
    db_path: Path,
    *,
    run: PipelineRun,
    stats: list[RunStat],
    changes: list[ChangeEvent],
    queue_items: list[ReviewQueueItem],
    formula_mismatches: list[FormulaMismatch],
    element_coverage: list[ElementCoverage],
    context_mappings: list[ContextDefaultMapping],
    timings: list[StageTiming] | None = None,
) -> None:
    """Write every review table for one run, replacing whatever was there.

    Takes the rows rather than deriving them, so that the expensive builders can
    be called (or not called) by the caller that knows what the run produced,
    and so that a test can write a fixture database without a pipeline run.

    There was an `activities` parameter.  `provenance_activities` is a view now,
    so passing its rows in would have meant accepting a list and dropping it --
    and a caller that still built one would have paid to derive 1.4M records the
    database no longer wants.
    """
    started = time.monotonic()
    connection = sqlite3.connect(db_path)
    try:
        create_review_tables(connection)
        connection.execute(
            insert_statement("pipeline_runs", _RUN_COLUMNS), _run_row(run)
        )
        connection.executemany(
            insert_statement("run_stats", _STAT_COLUMNS),
            [_stat_row(stat) for stat in stats],
        )
        # What is known *here*, which is the transform's stages and not the
        # merge's: the merge runs after this and adds its own rows with
        # `write_run_timings`.  A build that merges nothing therefore still
        # says where its half hour went.
        connection.executemany(
            insert_statement("run_timings", _TIMING_COLUMNS),
            [_timing_row(timing) for timing in timings or []],
        )
        connection.executemany(
            insert_statement("changelog", _CHANGE_COLUMNS),
            _deduplicated_change_rows(changes),
        )
        connection.executemany(
            insert_statement("changelog_flows", _CHANGELOG_FLOW_COLUMNS),
            _changelog_flow_rows(changes),
        )
        # No insert for `provenance_activities`: it is a view over the two
        # tables above.
        connection.executemany(
            insert_statement("review_queue", _QUEUE_COLUMNS),
            [_queue_row(item) for item in queue_items],
        )
        connection.executemany(
            insert_statement("formula_mismatches", _MISMATCH_COLUMNS),
            [_mismatch_row(mismatch) for mismatch in formula_mismatches],
        )
        connection.executemany(
            insert_statement("element_coverage", _COVERAGE_COLUMNS),
            [_coverage_row(coverage) for coverage in element_coverage],
        )
        connection.executemany(
            insert_statement("context_default_mappings", _MAPPING_COLUMNS),
            [_mapping_row(mapping) for mapping in context_mappings],
        )
        # After the inserts, not during: per-row index maintenance over a change
        # log this size is the difference between seconds and minutes.
        for statement in INDEXES:
            connection.execute(statement)
        connection.commit()
    finally:
        connection.close()

    logger.info(
        "wrote_review_tables",
        path=str(db_path),
        run_id=run.run_id,
        stats=len(stats),
        changes=len(changes),
        queue_items=len(queue_items),
        formula_mismatches=len(formula_mismatches),
        elements=len(element_coverage),
        context_mappings=len(context_mappings),
        ms_total=round((time.monotonic() - started) * 1000),
    )


# --------------------------------------------------------------------------
# rewriting one stage's rows -- for a stage that runs after the transform


def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
        ).fetchone()
        is not None
    )


def _replace_rows(
    db_path: Path,
    *,
    table: str,
    column: str,
    value: str,
    columns: tuple[str, ...],
    rows: list[tuple[Any, ...]],
    log_event: str,
) -> None:
    """Swap every row of *table* where *column* is *value* for *rows*.

    The two tables this serves are written whole by `write_review_tables`, which
    drops and recreates them, and that is right for the transform: it is the
    stage that produces the run.  A stage that runs *after* it and changes the
    flows -- the merge -- has to be able to say so without rewriting a run it
    did not perform, and the scoped delete is what makes the write idempotent
    across the several source lists one build merges in sequence.

    A database with no review tables is one no transform wrote -- a fixture
    seeded through `_write_consensus_sqlite` alone, which is what several tests
    hand the merge.  Reported and skipped rather than raised: the report was
    computed and logged either way, and failing a merge over where its counters
    are filed would be the tail wagging the dog.
    """
    connection = sqlite3.connect(db_path)
    try:
        if not _table_exists(connection, table):
            logger.warning(
                "review_table_absent",
                table=table,
                wanted=log_event,
                path=str(db_path),
            )
            return
        connection.execute(f"DELETE FROM {table} WHERE {column} = ?", (value,))
        placeholders = ", ".join("?" * len(columns))
        connection.executemany(
            f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
            rows,
        )
        connection.commit()
    finally:
        connection.close()
    logger.info(log_event, path=str(db_path), **{column: value}, rows=len(rows))


def replace_stage_stats(db_path: Path, *, stage: str, counts: Mapping[str, int]) -> None:
    """Rewrite one stage's rows in `run_stats`.

    `stage` is the function that counted, as everywhere else in this table, so a
    stage that runs after the transform files its numbers beside the
    transform's instead of over them: two rows called `collision_groups` under
    two stage names is the comparison #60 needed, where one number that the
    merge overwrote would have hidden it.
    """
    _replace_rows(
        db_path,
        table="run_stats",
        column="stage",
        value=stage,
        columns=("stage", "key", "value"),
        rows=[(stage, key, int(value)) for key, value in counts.items()],
        log_event="replaced_stage_stats",
    )


def write_run_timings(db_path: Path, *, timings: list[StageTiming]) -> None:
    """Rewrite `run_timings` with everything one recorder measured.

    The whole table, not one stage of it, because a build has exactly one
    :class:`~brightway_flows.pipeline.timings.RunTimings`: `build` makes it,
    hands it to the transform and then to each merge, and writes it once at the
    end, when it is the only account of the run there is.  A `--dry-run` writes
    no database and so writes no timings; it still logs them.

    Called again by a stage that owns its own recorder -- a bare
    `merge_source_list`, a test -- which replaces the table with that stage's
    measurements alone.  That is the honest outcome: the rows say what was
    measured by the run that wrote them, and nothing here merges one run's
    stages into another run's.
    """
    _replace_all_rows(
        db_path,
        table="run_timings",
        columns=_TIMING_COLUMNS,
        rows=[_timing_row(timing) for timing in timings],
        log_event="wrote_run_timings",
    )


def _replace_all_rows(
    db_path: Path,
    *,
    table: str,
    columns: tuple[str, ...],
    rows: list[tuple[Any, ...]],
    log_event: str,
) -> None:
    """Replace every row of *table*, or say why it could not be written."""
    connection = sqlite3.connect(db_path)
    try:
        if not _table_exists(connection, table):
            logger.warning(
                "review_table_absent", table=table, wanted=log_event, path=str(db_path)
            )
            return
        connection.execute(f"DELETE FROM {table}")
        placeholders = ", ".join("?" * len(columns))
        connection.executemany(
            f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
            rows,
        )
        connection.commit()
    finally:
        connection.close()
    logger.info(log_event, path=str(db_path), rows=len(rows))


def replace_queue_items(
    db_path: Path, *, queue: ReviewQueue, items: list[ReviewQueueItem]
) -> None:
    """Rewrite one queue's rows in `review_queue`.

    Every item must belong to *queue*: the delete is scoped to it, so an item
    of another queue would be inserted beside rows this call did not clear and
    would double on the next one.
    """
    wrong = sorted({str(item.queue_name) for item in items} - {str(queue)})
    if wrong:
        raise ValueError(
            f"items for queue(s) {wrong} cannot be written as {queue}: the "
            "delete this replaces them with is scoped to one queue name."
        )
    _replace_rows(
        db_path,
        table="review_queue",
        column="queue_name",
        value=str(queue),
        columns=(
            "queue_name", "item_key", "item_index", "title", "severity",
            "elementary_flow_uuid", "flow_object_id", "cas", "payload_json",
        ),
        rows=[_queue_row(item) for item in items],
        log_event="replaced_queue_items",
    )


# --------------------------------------------------------------------------
# reading -- rows back out as records, for tests and for the app's queries


def _connect_readonly(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def read_pipeline_run(db_path: Path) -> PipelineRun | None:
    """The run that wrote this database, or None if it holds no review tables."""
    connection = _connect_readonly(db_path)
    try:
        row = connection.execute("SELECT * FROM pipeline_runs LIMIT 1").fetchone()
    except sqlite3.OperationalError:
        return None
    finally:
        connection.close()
    if row is None:
        return None
    return PipelineRun(
        run_id=row["run_id"],
        timestamp=row["timestamp"],
        schema_version=row["schema_version"],
        dry_run=bool(row["dry_run"]),
        max_flows=row["max_flows"],
        input_files=orjson.loads(row["input_files_json"]),
        transformer_names=orjson.loads(row["transformer_names_json"]),
        flow_count=row["flow_count"],
        change_count=row["change_count"],
        git_commit=_optional_column(row, "git_commit", ""),
        git_dirty=bool(_optional_column(row, "git_dirty", False)),
    )


def _optional_column(row: sqlite3.Row, name: str, default: Any) -> Any:
    """*name* from *row*, or *default* where the column predates the reader.

    A database written before a field existed is still readable: the review app
    and `assess` both open whatever is in the data directory, which is not
    always a build of the code reading it.
    """
    return row[name] if name in row.keys() else default


def read_run_stats(db_path: Path) -> list[RunStat]:
    """Every stage's tally, in stage then key order."""
    connection = _connect_readonly(db_path)
    try:
        rows = connection.execute(
            "SELECT * FROM run_stats ORDER BY stage, key"
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        connection.close()
    return [
        RunStat(stage=row["stage"], key=row["key"], value=int(row["value"]))
        for row in rows
    ]


def read_changelog(
    db_path: Path,
    *,
    uuid: str | None = None,
    flow_object_id: str | None = None,
    transformer: str | None = None,
    field_name: str | None = None,
) -> list[ChangeEvent]:
    """Applied changes, optionally narrowed to one flow, substance, step or field.

    `field_name` narrows on the `field` column, which has its own index: the
    full log runs to 1.4M events and the question "what did this step do to the
    preferred label" is 9.5k of them, so a caller that filters in Python pays
    for the whole table to be read and turned into records first.

    One record per (edit, flow), which is what it has always returned.  The
    table underneath now stores one row per edit, so this joins `changelog_flows`
    and hands back one `ChangeEvent` per affected flow -- callers that ask "what
    changed on this flow" see exactly what they saw before the table was
    deduplicated.  Records of one edit share a `change_index` and are ordered
    by flow uuid within it, so the sequence is stable run to run.
    """
    clauses: list[str] = []
    params: list[Any] = []
    if uuid is not None:
        clauses.append("f.elementary_flow_uuid = ?")
        params.append(uuid)
    if flow_object_id is not None:
        clauses.append("c.flow_object_id = ?")
        params.append(flow_object_id)
    if transformer is not None:
        clauses.append("c.transformer = ?")
        params.append(transformer)
    if field_name is not None:
        clauses.append("c.field = ?")
        params.append(field_name)
    where = f"WHERE {' AND '.join(clauses)} " if clauses else ""

    connection = _connect_readonly(db_path)
    try:
        rows = connection.execute(
            "SELECT c.change_index, c.transformer, c.flow_object_id, c.field, "
            "c.old_value_json, c.new_value_json, c.comment, "
            "f.elementary_flow_uuid, f.flow_name "
            "FROM changelog c "
            "JOIN changelog_flows f ON f.change_index = c.change_index "
            f"{where}ORDER BY c.change_index, f.elementary_flow_uuid",
            params,
        ).fetchall()
    finally:
        connection.close()
    return [
        ChangeEvent(
            uuid=row["elementary_flow_uuid"],
            field_name=row["field"],
            old_value=orjson.loads(row["old_value_json"]),
            new_value=orjson.loads(row["new_value_json"]),
            transformer=row["transformer"],
            flow_name=row["flow_name"],
            comment=row["comment"],
            change_index=row["change_index"],
            flow_object_id=row["flow_object_id"],
        )
        for row in rows
    ]


def read_provenance_activities(
    db_path: Path, *, uuid: str | None = None
) -> list[ProvenanceActivity]:
    """The PROV-O activity trail, optionally for one flow.

    Ordered by `entity_version` within a flow, because that is what a trail is:
    each activity consumes the version the previous one produced.  It used to
    order by `change_index`, which was the same thing while the index was the
    position in the log -- it is now the position of an *edit*, which for one
    flow can run backwards (#253).
    """
    where = "WHERE elementary_flow_uuid = ? " if uuid is not None else ""
    params = [uuid] if uuid is not None else []
    connection = _connect_readonly(db_path)
    try:
        rows = connection.execute(
            f"SELECT * FROM provenance_activities {where}"
            "ORDER BY elementary_flow_uuid, entity_version",
            params,
        ).fetchall()
    finally:
        connection.close()
    return [
        ProvenanceActivity(
            change_index=row["change_index"],
            uuid=row["elementary_flow_uuid"],
            field_name=row["field"],
            transformer=row["transformer"],
            entity_version=row["entity_version"],
        )
        for row in rows
    ]


def read_review_queue(db_path: Path, queue_name: str | None = None) -> list[ReviewQueueItem]:
    """Queue items, in the order the run produced them."""
    where = "WHERE queue_name = ? " if queue_name is not None else ""
    params = [str(queue_name)] if queue_name is not None else []
    connection = _connect_readonly(db_path)
    try:
        rows = connection.execute(
            f"SELECT * FROM review_queue {where}ORDER BY queue_name, item_index", params
        ).fetchall()
    finally:
        connection.close()
    return [
        ReviewQueueItem(
            queue_name=ReviewQueue(row["queue_name"]),
            item_key=row["item_key"],
            title=row["title"],
            severity=Severity(row["severity"]),
            uuid=row["elementary_flow_uuid"],
            flow_object_id=row["flow_object_id"],
            cas=row["cas"],
            item_index=row["item_index"],
            payload=orjson.loads(row["payload_json"]),
        )
        for row in rows
    ]
