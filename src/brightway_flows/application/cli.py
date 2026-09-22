"""Download, parse, and extract EF 3.1 ILCD flow and LCIA data."""

import asyncio
from datetime import datetime, timezone
from uuid import uuid4
from pathlib import Path
from typing import Any

import orjson
import structlog
import typer

from brightway_flows.filesystem import CHEBI_JSON_GZ_FILEPATH, PACKAGE_DATA_DIR
from brightway_flows.integrations.ef31 import download_ef31
from brightway_flows.integrations.glad_mapping import (
    download_glad_ilcd_to_simapro,
    parse_glad_ilcd_to_simapro_workbook,
)
from brightway_flows.settings import save_commonchemistry_api_key
from brightway_flows.sources import base_source_list

logger = structlog.get_logger(__name__)

app = typer.Typer(help="Download and extract EF 3.1 ILCD flow data.")


def _log_merge_run_stats(run_id: str) -> None:
    """Report what the run did, counted from the database.

    The counts used to be read back out of a `stats` block in the JSON report,
    which meant they could disagree with the rows beside them. They are now
    aggregates over `merge_outcomes`, so they cannot.
    """
    from brightway_flows.filesystem import CONSENSUS_DB_FILEPATH
    from brightway_flows.merge.store import run_stats

    stats = run_stats(CONSENSUS_DB_FILEPATH, run_id)
    if not stats:
        logger.warning("merge_run_stats_missing", run_id=run_id)
        return
    logger.info("merge_run_stats", **stats)


def _log_run_timings(timings: Any, limit: int = 12) -> None:
    """End a build with the stages that cost it the most.

    The table is the record; this is so that the answer is in the terminal the
    build ran in, without a query.  Slowest first and truncated, because the
    question a reader has at the end of a half-hour build is which stage to
    look at and not what all thirty of them cost.
    """
    slowest = timings.slowest(limit)
    if not slowest:
        return
    logger.info(
        "build_timings",
        measured_seconds=timings.total_seconds(),
        stages=len(timings.records()),
        slowest=[
            {
                "stage": row.stage,
                "detail": row.detail,
                "duration_seconds": row.duration_seconds,
            }
            for row in slowest
        ],
    )


@app.command()
def download(
    force: bool = typer.Option(False, "--force", "-f", help="Re-download even if the file exists."),
) -> None:
    """Download the EF 3.1 ZIP archive."""
    download_ef31(force=force)


@app.command("fetch-source")
def fetch_source(
    key: str = typer.Argument(
        ...,
        help="Source list key, e.g. ecoinvent-3.12 or EF-3.1. One of the "
             "manifests in data/sources/.",
    ),
    force: bool = typer.Option(
        False, "--force", "-f", help="Re-download even if the archive exists."
    ),
) -> None:
    """Fetch one source list's flows, whichever list it is.

    The command #15 asked for.  A list used to need its own: a module, a CLI
    command, a `filesystem.py` path function and a registry edit, which is why
    `docs/operating/sources.md` could say "write an adapter" with nowhere for one
    to live.  A manifest names its adapter by dotted path; this runs it and
    checks that it wrote where the manifest says its flows live.

    The base list is fetchable here too.  `role: "base"` says which list is
    merged into, not that it arrives by a different route.
    """
    from brightway_flows.sources import fetch_source_flows, registered_source_list

    source = registered_source_list(key)
    path = fetch_source_flows(source, force=force)
    logger.info("saved source flows", source=source.key, path=str(path))


@app.command()
def characterise(
    db_path: str = typer.Option(
        None,
        "--db-path",
        help="The build to characterise. Defaults to consensus-flows.sqlite3 in "
             "the data directory.",
    ),
) -> None:
    """Match the published characterisation factors onto the consensus flows.

    Runs after `build` and reads what it wrote: EF 3.1 as the JRC published it,
    which is already on the flows, and EF 3.1 as the ecoinvent Centre implemented
    it, which `fetch-lcia ecoinvent-3.12` fetched. Both are transcriptions --
    nothing here changes a number either of them stated.

    Writes the `lcia_*` tables into the same database, and touches none of the
    tables `build` owns.
    """
    from brightway_flows.lcia import characterise as run_characterise

    stats = run_characterise(Path(db_path) if db_path else None)
    logger.info("characterised", **stats)


@app.command("compare-scores")
def compare_scores(
    db_path: str = typer.Option(
        None,
        "--db-path",
        help="The build to compare against. Defaults to consensus-flows.sqlite3 "
             "in the data directory.",
    ),
    release: list[str] = typer.Option(
        None,
        "--release",
        help="A configured release key, e.g. ecoinvent-3.8-apos. Repeatable; "
             "every configured release when omitted.",
    ),
) -> None:
    """Score each release's unit processes our way and against the vendor's.

    Runs after `characterise`. Reads the artifacts
    `tools/export_unit_process_scores.py` wrote under brightway -- the
    vendor's inventories, factors and scores -- re-scores the same
    inventories through the consensus flows and this list's own factors, and
    writes the `score_*` tables: every (unit process, category) both ways,
    every flow whose contribution differs and why, and the flows ranked by
    how much of a category they move.
    """
    from brightway_flows.lcia.scores import compare_scores as run_compare

    stats = run_compare(Path(db_path) if db_path else None, releases=release or None)
    logger.info("compared_scores", **{k: v for k, v in stats.items() if "." not in k})


@app.command("score-comparison-config")
def score_comparison_config() -> None:
    """Print the unit-process score comparison's settings as JSON.

    For `tools/export_unit_process_scores.py`, which runs under a brightway
    Python that cannot import this package's settings: which releases to
    score, how many unit processes, with what seed, and where to put the
    artifact. One source of truth, read from two Pythons.
    """
    from brightway_flows.settings import get_settings

    typer.echo(get_settings().score_comparison.model_dump_json(indent=2))


@app.command("fetch-lcia")
def fetch_lcia(
    key: str = typer.Argument(
        ...,
        help="Source list key whose manifest declares an `lcia` block, e.g. "
             "ecoinvent-3.12.",
    ),
    force: bool = typer.Option(
        False, "--force", "-f", help="Re-download the release rather than "
        "reading what is cached."
    ),
) -> None:
    """Fetch one source list's characterisation factors.

    `fetch-source` for the other thing a list can publish. ecoinvent ships an
    implementation of every method it supports in a workbook beside its flows,
    and EF 3.1 as the ecoinvent Centre implements it is the second rendering of
    that method this project holds -- the first that is not the method's own
    publisher's.

    What it writes is read by `characterise`, never by a build.
    """
    from brightway_flows.sources import fetch_source_lcia, registered_source_list

    source = registered_source_list(key)
    path = fetch_source_lcia(source, force=force)
    logger.info("saved source lcia factors", source=source.key, path=str(path))


@app.command()
def extract(
    force: bool = typer.Option(False, "--force", "-f", help="Re-download even if the file exists."),
    keep_zip: bool = typer.Option(False, "--keep-zip", "-k", help="Keep the ZIP archive after extraction."),
    ingest_glad_mapping: bool = typer.Option(
        False,
        "--ingest-glad-mapping/--no-ingest-glad-mapping",
        help=(
            "Also download and parse the GLAD ILCD->SimaPro correspondence "
            "table. Off by default: it is read only by a build that merges a "
            "list whose flows originate in SimaPro. `ingest-glad-mapping` does "
            "the same thing on its own."
        ),
    ),
) -> None:
    """Deprecated alias for `fetch-source EF-3.1`; extracts the base list.

    Kept because it is in the README quick start and in every existing runbook.
    It is the base list's adapter and nothing else, so the two commands cannot
    drift -- what was ~55 lines of extraction here now lives in
    `integrations/ef31.py:fetch` (#15).

    Two options survive that `fetch-source` does not carry, because neither is a
    property of fetching a list:

    `--keep-zip` keeps the vendor archive, for reading the XML behind a
    surprising flow.

    `--ingest-glad-mapping` also pulls the GLAD correspondence table. Extracting
    EF 3.1 used to do that unconditionally -- an 11 MB, 124,318-row download on
    every run, for a builder no build registered. It is now read by a build that
    merges a list whose flows originate in SimaPro, and `ingest-glad-mapping`
    does the same thing on its own (#244).
    """
    from brightway_flows.integrations.ef31 import fetch as fetch_ef31

    base = base_source_list()
    output_path = fetch_ef31(base, force=force, keep_zip=keep_zip)
    logger.info("saved source flows", source=base.key, path=str(output_path))

    if ingest_glad_mapping:
        glad_workbook = download_glad_ilcd_to_simapro(force=force)
        glad_json = parse_glad_ilcd_to_simapro_workbook(glad_workbook)
        logger.info("saved_glad_mapping_json", path=str(glad_json))


@app.command("ingest-glad-mapping")
def ingest_glad_mapping(
    force: bool = typer.Option(False, "--force", "-f", help="Re-download even if the file exists."),
) -> None:
    """Download and parse GLAD ILCD->SimaPro mapping workbook to JSON."""
    workbook = download_glad_ilcd_to_simapro(force=force)
    output = parse_glad_ilcd_to_simapro_workbook(workbook)
    logger.info("saved_glad_mapping_json", path=str(output))


@app.command()
def pubchem(
    limit: int | None = typer.Option(None, help="Max unique names/CAS numbers to query (default: all)."),
) -> None:
    """Query PubChem for compound data matching EF 3.1 flow names and CAS numbers."""
    from brightway_flows.integrations.pubchem import fetch_and_store_pubchem

    asyncio.run(fetch_and_store_pubchem(limit=limit))


def _run_transform(
    sources: list[Any],
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        "-n",
        help=(
            "Write no artifact: run the transform without its writes, and skip "
            "the merge entirely. The RDKit and OPSIN diagnostic logs are still "
            "rewritten."
        ),
    ),
    max_flows: int | None = typer.Option(
        None,
        "--max-flows",
        help="Only process the first N flows (for quick testing).",
    ),
    include_uuid: list[str] = typer.Option(
        [],
        "--include-uuid",
        help=(
            "Keep this base-list flow in a --max-flows run whatever its position. "
            "Repeatable. The prefix --max-flows takes is a sample nobody chose, "
            "so a run about particular flows has to name them or it may not "
            "contain any of them."
        ),
    ),
    timings: Any = None,
) -> list[Any]:
    """First stage of `build`: apply every transformer to the EF 3.1 flows.

    Returns the transformer instances.  They are built here and `setup()`-ed by
    `run_pipeline`, and the merge needs the same ones: setting them up again per
    source list would reload ChEBI and PubChem each time.

    There used to be five blocks after the run, each finding one transformer by
    `isinstance` and asking it to write a review file.  `run_pipeline` collects
    those queues into the `review_queue` table itself, from every transformer it
    was handed, so a transformer that grows a queue no longer needs a sixth
    block here to be seen.

    There used to be three ways to add flows here as well -- `--input`, a
    `transform-sources.json`, and auto-discovery of the data directory -- so a
    list could enter a build either as an input or as a `--source`, meaning two
    different things.  A list is a `--source` (#210).

    *sources* are not transformed -- the merge does that, later and per list --
    but they are needed here because the mappings this build publishes are
    attached during the transform, and which ones to build is a property of the
    run rather than of the code (#244).
    """
    from brightway_flows.pipeline import run_pipeline
    from brightway_flows.transformers import DEFAULT_TRANSFORMERS

    instances = [t() for t in DEFAULT_TRANSFORMERS]
    run_pipeline(
        instances,
        dry_run=dry_run,
        max_flows=max_flows,
        keep_uuids=include_uuid,
        sources=sources,
        timings=timings,
    )
    return instances


@app.command("download-ecoinvent-flows")
def ecoinvent(
    version: str = typer.Option("3.12", "--version", "-v", help="ecoinvent version to fetch (e.g. 3.12)."),
) -> None:
    """Deprecated alias for `fetch-source ecoinvent-<version>`.

    Kept because it is in the README quick start and in every existing runbook.
    It routes through the same registry lookup and the same adapter, so a version
    with no manifest is now refused here rather than downloading a release and
    writing it to a path nothing reads (#15).
    """
    from brightway_flows.sources import fetch_source_flows, registered_source_list

    source = registered_source_list(f"ecoinvent-{version}")
    output_path = fetch_source_flows(source)
    logger.info("saved ecoinvent elementary flows", version=version, path=str(output_path))


@app.command()
def build(
    source: list[str] = typer.Option(
        [],
        "--source",
        "-s",
        help=(
            "Source list to merge, e.g. ecoinvent-3.12. Repeatable. None by "
            "default: a build transforms the base list and merges nothing."
        ),
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        "-n",
        help=(
            "Write no artifact: run the transform without its writes, and skip "
            "the merge entirely. The RDKit and OPSIN diagnostic logs are still "
            "rewritten."
        ),
    ),
    max_flows: int | None = typer.Option(
        None, "--max-flows", help="Only process the first N flows (for quick testing)."
    ),
    include_uuid: list[str] = typer.Option(
        [],
        "--include-uuid",
        help=(
            "Keep this base-list flow in a --max-flows run whatever its position. "
            "Repeatable. Without it the sample is a prefix in file order, which "
            "may contain none of the flows the run is about."
        ),
    ),
    max_rows: int | None = typer.Option(
        None,
        "--max-rows",
        help=(
            "Only merge the first N rows of each source list. The merge is the "
            "one stage --max-flows does not bound."
        ),
    ),
    include_source_uuid: list[str] = typer.Option(
        [],
        "--include-source-uuid",
        help=(
            "Keep this source row in a --max-rows run whatever its position. "
            "Repeatable, and the same rule as --include-uuid on the other side."
        ),
    ),
) -> None:
    """Build the Brightway flows list: transform EF 3.1, then merge each source list.

    Merges nothing unless asked. `--source` used to default to
    `ecoinvent-3.12`, which made the ordinary invocation of the ordinary command
    a build that needed a licence -- and the base list is deliberately not a
    valid `--source`, so there was no spelling of "just build the consensus
    list" at all (#99). Every list that can be merged needs either an ecoinvent
    licence or an archive obtained from BAFU by hand, so the previous default
    put every one of them behind a credential the project does not require of a
    reader.

    The base list on its own is the product: 94,000 flows with names, synonyms,
    registry numbers, structures, semantic typing and provenance. Merging a
    vendor list adds that vendor's flows and the translation table between
    them, which is a thing to ask for rather than a thing to opt out of.

    This was two commands, `transform` and `merge-ecoinvent`, ordered by
    convention. Running them out of order, or only one of them, left the
    database describing a state that never existed. One command makes that
    unrepresentable, and gives the whole pipeline invocation a single run id
    rather than one that identifies only the merge.

    Preparing inputs stays separate: `download`, `extract`,
    `download-ecoinvent-flows`, `pubchem`, `chebi` and `ingest-glad-mapping`
    all feed a later build.
    """
    from brightway_flows.filesystem import CONSENSUS_DB_FILEPATH
    from brightway_flows.merge.pipeline import merge_source_list
    from brightway_flows.pipeline.review_tables import write_run_timings
    from brightway_flows.pipeline.sqlite import (
        check_context_iris_are_written,
        check_filter_option_counts,
        recompute_filter_option_counts,
    )
    from brightway_flows.pipeline.timings import RunTimings
    from brightway_flows.sources import merge_order, resolve_source_list
    from brightway_flows.merge.store import detect_conflicts, finish_run, start_run

    # Resolved before any work, so an unknown source list fails immediately
    # rather than after a transform that would then be thrown away.
    #
    # Then ordered by the manifests rather than by the order the flags were
    # typed.  The first list to reach a substance mints its flow object, and
    # everything merged after it matches against what that list created -- so
    # the order is a property of the lists, not of the invocation, and a run
    # could previously get it wrong in a way nothing reported.  `merge_order`
    # settles the ties too, which a plain sort on priority did not: five
    # ecoinvent releases share one, and `-s ecoinvent-3.8 -s ecoinvent-3.12`
    # merged them oldest first (#100).
    requested = [resolve_source_list(key) for key in source]
    sources = merge_order(requested)
    if [s.key for s in sources] != [s.key for s in requested]:
        logger.info(
            "source_order_set_by_manifests",
            requested=[s.key for s in requested],
            merging=[s.key for s in sources],
        )

    run_id = uuid4().hex
    started_at = datetime.now(timezone.utc).isoformat()
    logger.info("build_started", run_id=run_id, sources=[s.key for s in sources])

    # One recorder for the whole build, handed to the transform and then to each
    # merge, and written once at the end. A build that cannot say which of its
    # stages cost half an hour is one whose next speed-up is a guess: what a
    # stopwatch outside the process could measure was the shape of a run --
    # extraction 61 s, a 400-flow transform 42 s -- and never which of the
    # twenty-odd steps inside `build` spent the time.
    timings = RunTimings()

    transformers = _run_transform(
        sources,
        dry_run=dry_run,
        max_flows=max_flows,
        include_uuid=include_uuid,
        timings=timings,
    )

    if dry_run:
        # `--dry-run` was fixed once, in the transform, because a bounded smoke
        # run had replaced multi-GB artifacts with 400-flow ones. The merge was
        # not part of that fix and `build` merged the two commands afterwards,
        # so the flag went on guarding half the run: the merge still wrote the
        # four `merge_*` tables and rewrote `harmonised-flows-simple.json.gz`,
        # the one artifact with a downstream consumer (#235).
        #
        # Skipped rather than run write-free, because there is nothing left for
        # it to merge into: the transform wrote no database, so the merge would
        # match this source list against whatever the *previous* build left
        # there. Said out loud for the same reason the transform says it -- a
        # reader who passed `--dry-run --source` is owed the news that the
        # source list was not merged.
        logger.info(
            "dry_run_skipped_merge",
            run_id=run_id,
            sources=[s.key for s in sources],
        )
        _log_run_timings(timings)
        logger.info("build_finished", run_id=run_id, dry_run=True, conflicts=None)
        return

    if not sources:
        # Said out loud for the reason `dry_run_skipped_merge` is: this is the
        # ordinary invocation, and a reader who expected ecoinvent from it --
        # because that is what it used to do -- is owed the news that the
        # published list is the base list alone (#99).
        logger.info("no_source_lists_to_merge", run_id=run_id)

    # Opened even when nothing is merged, so the merge tables describe *this*
    # build rather than being absent: a run that merged nothing is an answer,
    # and the checks below are over the whole database either way.
    start_run(CONSENSUS_DB_FILEPATH, run_id=run_id, started_at=started_at)
    for sequence, source_list in enumerate(sources):
        # The same instances the transform used, already `setup()`-ed: each
        # source list is enriched with them before it is matched, which is what
        # the two-pass workflow used a second build for.
        merge_source_list(
            source_list,
            run_id=run_id,
            sequence=sequence,
            transformers=transformers,
            max_rows=max_rows,
            keep_uuids=include_source_uuid,
            timings=timings,
            # `--max-flows` bounds the transform but not the merge: every
            # source row is still matched -- unless `--max-rows` above bounds
            # this side too -- against a consensus list holding only the
            # first N base-list flows.  A curated grouping onto a flow object
            # outside that slice is then unplaceable through no fault of the
            # groupings file, and the merge is told so it can say that rather
            # than fail (#228).
            consensus_is_partial=max_flows is not None,
        )
    finish_run(
        CONSENSUS_DB_FILEPATH,
        run_id=run_id,
        finished_at=datetime.now(timezone.utc).isoformat(),
        stats={"source_lists": [s.key for s in sources]},
    )

    # After every list, because the merge adds flows and the transform's copy of
    # the filter facets describes only the base list it was written from.  On
    # the 2026-08-06 run that left the source filter totalling 93,993 of 94,429
    # flows, with the two ecoinvent labels -- 247 and 189 flows -- offered
    # nowhere, and `EUR` a unit the dropdown had never heard of (#248).
    #
    # `element_coverage` is written by the transform and stays there: it
    # describes the transform, which is what it claims to describe.  The facets
    # are the one table that claims to describe the whole database -- and so is
    # the collision queue, which is why the merge rewrites that one and files
    # its counters under a `run_stats` stage of its own beside the transform's,
    # rather than over them (#60).
    recompute_filter_option_counts(CONSENSUS_DB_FILEPATH)

    # Once, after every list: a conflict is a disagreement between lists, so it
    # is a property of the set and cannot be seen while merging any one of them.
    conflicts = detect_conflicts(CONSENSUS_DB_FILEPATH, run_id)
    _log_merge_run_stats(run_id)

    # Guards the ordering rather than any one stage: whatever runs between the
    # recompute above and here, the published facets must still add up to the
    # published flows.  A stage added later that writes flows fails the build
    # instead of shipping a landing page that cannot select what it wrote.
    check_filter_option_counts(CONSENSUS_DB_FILEPATH)

    # Beside it, and for the same reason: whatever wrote flows between the
    # transform and here wrote them whole.  A context has a printed name and an
    # address, both read off one object, and the merge's writer filled the name
    # alone on every flow it created -- so the queries that ask "same context?"
    # by identity answered for 93,993 flows and not for 1,200 (#295).
    check_context_iris_are_written(CONSENSUS_DB_FILEPATH)
    # Last, so that every stage above is in the table, including the merges and
    # the checks that follow them.  One table for the run, replacing what the
    # transform wrote of it partway through.
    write_run_timings(CONSENSUS_DB_FILEPATH, timings=timings.records())
    _log_run_timings(timings)
    logger.info(
        "build_finished", run_id=run_id, dry_run=False, conflicts=len(conflicts)
    )


@app.command()
def chebi(
    force: bool = typer.Option(False, "--force", "-f", help="Re-download even if the file exists."),
) -> None:
    """Download ChEBI JSON (.gz) and report graph.nodes type statistics."""
    import gzip
    from collections import Counter

    import httpx

    url = "https://ftp.ebi.ac.uk/pub/databases/chebi/ontology/chebi.json.gz"

    if CHEBI_JSON_GZ_FILEPATH.exists() and not force:
        logger.info("using_cached_chebi", path=str(CHEBI_JSON_GZ_FILEPATH))
    else:
        logger.info("downloading_chebi", url=url, destination=str(CHEBI_JSON_GZ_FILEPATH))
        with httpx.stream("GET", url, follow_redirects=True, timeout=300) as response:
            response.raise_for_status()
            with CHEBI_JSON_GZ_FILEPATH.open("wb") as f:
                for chunk in response.iter_bytes(chunk_size=1024 * 64):
                    f.write(chunk)
        logger.info("saved_chebi", path=str(CHEBI_JSON_GZ_FILEPATH))

    with gzip.open(CHEBI_JSON_GZ_FILEPATH, "rb") as f:
        data = orjson.loads(f.read())

    if isinstance(data.get("graph"), dict):
        nodes = data.get("graph", {}).get("nodes", [])
    elif isinstance(data.get("graphs"), list) and data["graphs"]:
        nodes = data["graphs"][0].get("nodes", [])
    else:
        nodes = []
    type_counts = Counter((node.get("type") or "(missing)") for node in nodes)
    logger.info(
        "chebi_node_type_stats",
        node_count=len(nodes),
        distinct_types=len(type_counts),
        type_counts=dict(sorted(type_counts.items(), key=lambda kv: (-kv[1], kv[0]))),
    )


def _human_bytes(size: int) -> str:
    """A size a reader can check against `ls`.

    `size / 1e9` printed `0.00 GB` for every archive under 5 MB, which is what
    a machine holding only the small JSON caches produces -- a success that
    reads as a failure.
    """
    for unit in ("B", "kB", "MB"):
        if size < 1000:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1000
    return f"{size:.2f} GB"


@app.command("fetch-cache")
def fetch_cache_command(
    url: str | None = typer.Option(
        None,
        "--url",
        help=(
            "Where the cache archive is published. Defaults to the "
            "BRIGHTWAY_FLOWS_CACHE_URL environment variable. A local path "
            "or a file:// URL is read where it lies."
        ),
    ),
    overwrite: bool = typer.Option(
        False,
        "--overwrite",
        help=(
            "Replace cache files the data directory already has. Off by "
            "default: a local cache holds lookups the archive may not."
        ),
    ),
) -> None:
    """Unpack a published cache archive into the data directory.

    The first run is several hours of rate-limited requests to PubChem, ChEBI,
    Common Chemistry, Wikidata and Wikipedia, and every answer is cached. This
    is the way to start from somebody else's answers instead: point
    `BRIGHTWAY_FLOWS_CACHE_URL` at an archive `pack-cache` wrote and run
    this before `build`.

    Only the files in `cache_archive.CACHED_FILES` are written, whatever the
    archive contains, so an archive fetched from elsewhere cannot write outside
    the data directory or over the settings file that holds the API key.
    """
    from brightway_flows.cache_archive import fetch_cache

    result = fetch_cache(url, overwrite=overwrite)
    logger.info(
        "fetched_cache",
        written=result.written,
        kept=result.kept,
        ignored=result.ignored,
    )

    if result.written:
        typer.echo(f"Wrote {len(result.written)} cache file(s): {', '.join(result.written)}")
    # Nothing written has two causes and they need opposite responses, so the
    # counts say which one this was rather than the likelier one.
    elif result.kept:
        typer.echo(
            "No cache file written: the data directory already has every cache "
            "the archive holds. Pass --overwrite to replace them."
        )
    else:
        typer.echo(
            "No cache file written: the archive holds nothing this project "
            "caches. Was it packed by `pack-cache`?"
        )
    if result.kept and result.written:
        typer.echo(f"Kept {len(result.kept)} already here: {', '.join(result.kept)}")
    if result.ignored:
        typer.echo(f"Ignored {len(result.ignored)} member(s) that are not caches.")


@app.command("pack-cache")
def pack_cache_command(
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help=(
            "Archive to write, or a directory to write it in. Defaults to "
            "brightway-flows-cache.tar.gz in the working directory."
        ),
    ),
    list_only: bool = typer.Option(
        False,
        "--list",
        help="Report what would be packed, and where each file came from.",
    ),
) -> None:
    """Compress this machine's reference-data caches into one uploadable archive.

    The other half of `fetch-cache`: what this writes is what that reads. The
    licensed source lists -- ecoinvent's flows, BAFU's ecoSpold export -- and
    the settings file are not in it, and neither are build outputs.
    """
    from brightway_flows.cache_archive import (
        CACHED_FILES,
        pack_cache,
        present_cache_files,
    )
    from brightway_flows.filesystem import DATA_DIR

    if list_only:
        present = {entry.name for entry in present_cache_files()}
        for entry in CACHED_FILES:
            typer.echo(
                f"[{'x' if entry.name in present else ' '}] {entry.name} -- {entry.origin}"
            )
        typer.echo(f"{len(present)} of {len(CACHED_FILES)} present in {DATA_DIR}")
        return

    archive = pack_cache(output)
    typer.echo(f"Wrote {archive} ({_human_bytes(archive.stat().st_size)})")


@app.command("set-commonchemistry-token")
def set_commonchemistry_token(
    token: str = typer.Option(
        ...,
        "--token",
        prompt=True,
        hide_input=True,
        help=(
            "Common Chemistry API key. "
            "Also read from env variable COMMONCHEMISTRY_API_KEY at runtime."
        ),
    ),
) -> None:
    """Persist Common Chemistry API token in platformdirs settings."""
    save_commonchemistry_api_key(token)
    from brightway_flows.filesystem import APP_SETTINGS_FILEPATH

    logger.info("saved_commonchemistry_token", path=str(APP_SETTINGS_FILEPATH))


@app.command()
def webapp(
    host: str = typer.Option("127.0.0.1", help="Host to bind to."),
    port: int = typer.Option(5000, help="Port to listen on."),
    debug: bool = typer.Option(False, help="Run in Flask debug mode."),
) -> None:
    """Start the review application.

    One command, where there were five.  `webapp-inputs`, `webapp-consensus`,
    `webapp-run-report` and `webapp-etl` are gone with the applications they
    started; `webapp` was an alias for the first of them and is now the whole
    thing.
    """
    from brightway_flows.webapps.app import create_app

    logger.info("starting_review_webapp", host=host, port=port, debug=debug)
    create_app().run(host=host, port=port, debug=debug)


@app.command()
def contexts(
    contexts_file: Path = typer.Option(
        PACKAGE_DATA_DIR / "consensus-flow-contexts.json",
        help="Source of truth context definitions JSON.",
    ),
    strings_file: Path = typer.Option(
        PACKAGE_DATA_DIR / "consensus-flows-as-strings.json",
        help="Output file mapping context_iri to list-of-strings context expression.",
    ),
) -> None:
    """Validate context definitions and export their string expressions.

    It used to also split `context-manual-mapping.json` by source into files
    the merge read back. Both stages now read that file directly, so there is
    nothing to split (#11).
    """
    from brightway_flows.application.context_commands import (
        validate_contexts_and_generate_strings,
    )

    mapping = validate_contexts_and_generate_strings(
        contexts_path=contexts_file,
        strings_path=strings_file,
    )
    logger.info(
        "validated_contexts",
        contexts_file=str(contexts_file),
        strings_file=str(strings_file),
        context_count=len(mapping),
    )


@app.command()
def assess(
    database: Path | None = typer.Option(
        None,
        "--database",
        help="Which build to read. Defaults to the data directory's consensus-flows.sqlite3.",
    ),
    expectations_dir: Path | None = typer.Option(
        None,
        "--expectations",
        help="Where the expectation files are. Defaults to `expectations/` in this repository.",
    ),
    json_path: Path | None = typer.Option(
        None, "--json", help="Also write the whole result, including every measure, here."
    ),
    html_path: Path | None = typer.Option(
        None, "--html", help="Also write a standalone build-review page here."
    ),
    record: bool = typer.Option(
        False,
        "--record",
        help=(
            "Rewrite expectations/baseline.json from this build, so the next run "
            "reports what moved. Commit the result."
        ),
    ),
    compare: bool = typer.Option(
        True, "--compare/--no-compare", help="Report what moved since the recorded baseline."
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="List the expectations that hold, as well as those that do not."
    ),
    strict: bool = typer.Option(
        False,
        "--strict",
        help=(
            "Exit non-zero if any expectation is unmet or unanswerable. Expectations "
            "marked `pending` never fail the run."
        ),
    ),
) -> None:
    """Grade this build against what the repository says it should do.

    `build` produces the artifacts; this reads them.  It answers the question
    the test suite does not: not "is the code broken" but "is the output getting
    better, and did the change we just made do the thing we said it would do".

    Three sections.  **Where each list lands** is how much of each vendor list
    reaches a consensus flow and what kind of flow it reaches.
    **Expectations** are the statements in `expectations/` -- one file per issue,
    added by the pull request that claims to fix it -- each graded against this
    build, with the merge's own trace behind every failure.  **Since the
    baseline** is every measure that has moved since somebody last ran
    `--record`.

    Reads only; a build is the only thing that writes the database.
    """
    from brightway_flows.assessment import assess as run_assessment
    from brightway_flows.assessment import compare_to_baseline, write_baseline
    from brightway_flows.assessment.report import as_html, as_json, terminal_lines
    from brightway_flows.filesystem import CONSENSUS_DB_FILEPATH

    database = database or CONSENSUS_DB_FILEPATH
    assessment = run_assessment(database, expectations_dir=expectations_dir)
    comparison = (
        compare_to_baseline(assessment, directory=expectations_dir) if compare else None
    )

    for line in terminal_lines(assessment, comparison, verbose=verbose, style=typer.style):
        typer.echo(line)

    if json_path:
        json_path.write_bytes(as_json(assessment, comparison))
        typer.echo(f"Wrote {json_path}")
    if html_path:
        html_path.write_text(as_html(assessment, comparison), encoding="utf-8")
        typer.echo(f"Wrote {html_path}")
    if record:
        written = write_baseline(assessment, directory=expectations_dir)
        typer.echo(f"Recorded this build as the baseline in {written}. Commit it.")

    logger.info(
        "assessed_build",
        database=str(database),
        **assessment.counts,
        measures=len(assessment.measures),
    )
    if strict and assessment.failures:
        raise typer.Exit(code=1)


@app.command("release-snapshot")
def release_snapshot(
    database: Path | None = typer.Option(
        None,
        "--database",
        help="Which build to read. Defaults to the data directory's consensus-flows.sqlite3.",
    ),
    version: str | None = typer.Option(
        None,
        "--version",
        help=(
            "Name the release yourself. By default the build's commit is named by "
            "its git tag, or described as a development build where there is none."
        ),
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        help="Where to write. Defaults to <data dir>/releases/<version>.json.gz.",
    ),
) -> None:
    """Record what this build publishes, so a later release can say what changed.

    A build drops and recreates its tables, so nothing in a database says what
    the release before it published.  This writes the part a migration
    compares -- the published fields of every substance and flow, the
    redirects, the factors, and the source rows that align one build's
    identifiers with another's -- to a file named by the release.  Run it once
    per release, after `build` and `characterise`; `release-migrations` reads
    two of them.

    Reads only.
    """
    from brightway_flows.filesystem import CONSENSUS_DB_FILEPATH
    from brightway_flows.releases import (
        build_snapshot,
        named_version,
        snapshot_path,
        write_snapshot,
    )
    from brightway_flows.releases.snapshot import SnapshotError
    from brightway_flows.releases.version import ReleaseVersionError

    database = database or CONSENSUS_DB_FILEPATH
    try:
        snapshot = build_snapshot(
            database, version=named_version(version) if version else None
        )
    except (ReleaseVersionError, SnapshotError) as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(code=2) from error
    path = write_snapshot(snapshot, output or snapshot_path(snapshot.stamp.version))
    stamp = snapshot.stamp
    typer.echo(
        f"Recorded {stamp.randonneur_id} from run {stamp.run_id} "
        f"(commit {stamp.revision[:12] or 'unknown'}): "
        f"{len(snapshot.flow_objects)} substances, {len(snapshot.elementary_flows)} flows "
        f"({len(snapshot.redirects)} redirects), "
        f"{len(snapshot.characterization_factors)} factors, "
        f"{len(snapshot.source_rows)} source rows."
    )
    if stamp.development:
        typer.echo(
            "This is a development build -- no tag names its commit -- so the "
            "snapshot is named by `git describe` and carries the `-dev` modifier."
        )
    typer.echo(f"Wrote {path}")
    logger.info(
        "release_snapshot_written",
        database=str(database),
        version=stamp.version,
        development=stamp.development,
        path=str(path),
        flow_objects=len(snapshot.flow_objects),
        elementary_flows=len(snapshot.elementary_flows),
        characterization_factors=len(snapshot.characterization_factors),
    )


def _release_side(text: str, *, version: str | None):
    """A snapshot from a recorded version, a snapshot file, or a build."""
    from brightway_flows.releases import (
        build_snapshot,
        load_snapshot,
        named_version,
        snapshot_path,
    )
    from brightway_flows.releases.snapshot import SnapshotError

    path = Path(text)
    if path.exists():
        if path.suffix == ".sqlite3":
            return build_snapshot(path, version=named_version(version) if version else None)
        return load_snapshot(path)
    recorded = snapshot_path(text)
    if recorded.exists():
        return load_snapshot(recorded)
    raise SnapshotError(
        f"{text!r} is neither a recorded release (no {recorded}), a snapshot file, "
        "nor a build database"
    )


@app.command("release-migrations")
def release_migrations(
    from_release: str = typer.Option(
        ...,
        "--from",
        help="The earlier release: a version recorded with release-snapshot, or a snapshot file.",
    ),
    to_release: str = typer.Option(
        ...,
        "--to",
        help=(
            "The later release: a recorded version, a snapshot file, or a build's "
            "consensus-flows.sqlite3, which is snapshotted without being recorded."
        ),
    ),
    to_version: str | None = typer.Option(
        None, "--to-version", help="Name for --to when it is a build database."
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        help="Directory to write under. Defaults to <data dir>/releases/migrations.",
    ),
    allow_different_sources: bool = typer.Option(
        False,
        "--allow-different-sources",
        help=(
            "Proceed when the two releases merged different source lists. Every "
            "row of a list only one side merged is then unresolved rather than deleted."
        ),
    ),
) -> None:
    """Write the randonneur migrations from one release to the next.

    Three files, for a consumer who loaded the earlier release into their own
    database: the substances, the flows, and the characterisation factors,
    each as `create`, `update`, `replace` and `delete` entries.  A fourth,
    `unresolved.json`, lists what the migration could not decide -- a flow
    whose source rows split, a unit that changed, a redirect the export tells
    a consumer to refuse -- for a ruling in `release-migration-rulings.json`.

    Reads only.
    """
    from brightway_flows.filesystem import RELEASES_DIR
    from brightway_flows.releases import (
        DeltaKind,
        EntityKind,
        diff_releases,
        load_release_migration_rulings,
        write_migration_files,
    )
    from brightway_flows.releases.alignment import AlignmentError
    from brightway_flows.releases.rulings import MigrationRulingError
    from brightway_flows.releases.snapshot import SnapshotError
    from brightway_flows.releases.version import ReleaseVersionError

    try:
        before = _release_side(from_release, version=None)
        after = _release_side(to_release, version=to_version)
        diff = diff_releases(
            before,
            after,
            rulings=load_release_migration_rulings(),
            allow_different_sources=allow_different_sources,
        )
    except (AlignmentError, MigrationRulingError, ReleaseVersionError, SnapshotError) as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(code=2) from error

    files = write_migration_files(diff, output or RELEASES_DIR / "migrations")
    counts = diff.counts()
    typer.echo(f"{diff.before.randonneur_id} -> {diff.after.randonneur_id}")
    header = f"{'':28}" + "".join(f"{kind.value:>12}" for kind in DeltaKind)
    typer.echo(header)
    for entity in EntityKind:
        row = "".join(f"{counts[(entity.value, kind.value)]:>12}" for kind in DeltaKind)
        typer.echo(f"{entity.value + 's':28}{row}")
    if diff.minted_identifiers_checked:
        typer.echo(
            f"{diff.minted_identifiers_checked} source-row answers agreed with the "
            "minted-identifier arithmetic."
        )
    for path in (*files.migrations, files.unresolved):
        typer.echo(f"Wrote {path}")
    logger.info(
        "release_migrations_written",
        from_version=diff.before.version,
        to_version=diff.after.version,
        directory=str(files.directory),
        unresolved=len(diff.unresolved),
        **{f"{entity}.{kind}": n for (entity, kind), n in counts.items() if n},
    )


def main() -> None:
    """Entry point for the ``brightway-flows`` console script."""
    from brightway_flows.filesystem import DATA_DIR

    # To stderr: `score-comparison-config` prints JSON for another program to
    # read, and a greeting on stdout ahead of it is not JSON.
    typer.echo(f"Data caching directory: {DATA_DIR}", err=True)
    app()
