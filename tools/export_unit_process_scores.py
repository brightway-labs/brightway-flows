"""Score a sample of a release's unit processes with the vendor's own factors.

Run under a brightway Python, not this project's::

    uv run brightway-flows score-comparison-config > config.json
    ~/venvs/bw25/bin/python tools/export_unit_process_scores.py config.json \\
        --release ecoinvent-3.8-apos

It imports nothing from ``brightway_flows``: brightway is not a dependency
of the list and this script is not a dependency of the build.  The contract
between the two is the checked-in JSON Schema,
``src/brightway_flows/data/schemas/unit-process-scores.schema.json``,
which this validates against before it writes and ``load_score_artifact``
validates against when it reads.  The records the schema describes are in
``domain/lcia/unit_process_scores.py``, and their docstrings say what each
field is for.

What it does, in order:

1. Opens the brightway project named in the config, importing the release
   with ``bw2io.import_ecoinvent_release`` if the database is not there yet
   (``ecoinvent_interface`` credentials come from its own settings).
2. Draws the sample: every process of the database sorted by code,
   ``random.Random(seed).sample(n)``, plus the release's
   ``reference_activities``.  Same seed, same release, same unit processes.
3. Takes every method under the release's namespace and the configured
   ``method_family`` -- ``('ecoinvent-3.8', 'EF v3.0', …)`` -- and refuses if
   there are none, because a release scored with no factors is not an artifact.
4. One ``LCA`` with the technosphere factorised once, and each method's
   characterisation vector loaded once -- ``switch_method`` per unit process
   and per category accumulates state in bw2calc 2.1 and the loop went
   quadratic, 4 s for the first 25 unit processes and 88 s for the twelfth 25.
   Per unit process: the inventory for one unit of the reference product, and
   the score as that inventory against each vector.
5. Keeps the factors on flows the sample actually emits, checks that
   inventory × factors reproduces every score, validates against the schema,
   and writes.

``--only-codes`` restricts the sample to named activities: it is how the
committed test fixture was cut from a real export.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import random
import sys
import time
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
RECOMPUTE_TOLERANCE = 1e-6
REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = (
    REPO_ROOT / "src" / "brightway_flows" / "data" / "schemas"
    / "unit-process-scores.schema.json"
)
PROCESS_TYPES = {"process", "processwithreferenceproduct"}


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", file=sys.stderr, flush=True)


def read_config(source: str) -> dict[str, Any]:
    if source == "-":
        return json.load(sys.stdin)
    return json.loads(Path(source).read_text())


def release_from(config: dict[str, Any], key: str) -> dict[str, Any]:
    for release in config["releases"]:
        if f"{release['list_name']}-{release['list_version']}-{release['system_model']}" == key:
            return release
    known = ", ".join(
        f"{r['list_name']}-{r['list_version']}-{r['system_model']}" for r in config["releases"]
    )
    raise SystemExit(f"{key!r} is not a configured release; configured: {known}")


def ensure_database(release: dict[str, Any]) -> None:
    import bw2data as bd

    bd.projects.set_current(release["brightway_project"])
    if release["brightway_database"] in bd.databases:
        return
    import bw2io

    log(
        f"database {release['brightway_database']!r} is not in project "
        f"{release['brightway_project']!r}; importing ecoinvent "
        f"{release['list_version']} {release['system_model']} with bw2io"
    )
    bw2io.import_ecoinvent_release(
        version=release["list_version"],
        system_model=release["system_model"],
        lci=True,
        lcia=True,
    )
    if release["brightway_database"] not in bd.databases:
        raise SystemExit(
            f"bw2io imported the release but the database is not called "
            f"{release['brightway_database']!r}; it wrote {sorted(bd.databases)}"
        )


def methods_for(release: dict[str, Any]) -> list[tuple]:
    import bw2data as bd

    namespace = f"{release['list_name']}-{release['list_version']}"
    family = release["method_family"]
    found = sorted(
        m for m in bd.methods if len(m) >= 2 and m[0] == namespace and m[1] == family
    )
    if not found:
        families = sorted({m[1] for m in bd.methods if len(m) >= 2 and m[0] == namespace})
        raise SystemExit(
            f"no method under ({namespace!r}, {family!r}); this release ships "
            f"{families}"
        )
    return found


def category_key(method: tuple) -> str:
    return "|".join(method[1:])


def select(database: Any, *, size: int, seed: int, always: list[str], only: list[str]) -> list:
    processes = sorted(
        (node for node in database if node.get("type", "process") in PROCESS_TYPES),
        key=lambda node: node["code"],
    )
    by_code = {node["code"]: node for node in processes}
    if only:
        missing = [code for code in only if code not in by_code]
        if missing:
            raise SystemExit(f"--only-codes names activities not in the database: {missing}")
        return [by_code[code] for code in only]
    chosen = random.Random(seed).sample(processes, min(size, len(processes)))
    codes = {node["code"] for node in chosen}
    for code in always:
        if code not in by_code:
            raise SystemExit(f"reference activity {code!r} is not in the database")
        if code not in codes:
            chosen.append(by_code[code])
            codes.add(code)
    return sorted(chosen, key=lambda node: node["code"])


def flow_record(node: Any) -> dict[str, Any]:
    cas = node.get("CAS number") or node.get("cas_number") or None
    return {
        "source_flow_uuid": node["code"],
        "name": node["name"],
        "unit": node.get("unit", ""),
        "context": list(node.get("categories", ())),
        "cas_number": str(cas).strip() if cas else None,
    }


def recompute(inventory: list[dict[str, Any]], factors: dict[str, float], *, stated: float, where: str) -> None:
    computed = 0.0
    scale = 0.0
    for line in inventory:
        factor = factors.get(line["source_flow_uuid"])
        if factor is None:
            continue
        contribution = line["amount"] * factor
        computed += contribution
        scale = max(scale, abs(contribution))
    if abs(computed - stated) > RECOMPUTE_TOLERANCE * max(abs(stated), scale):
        raise SystemExit(
            f"{where}: brightway scored {stated!r} but inventory x factors give "
            f"{computed!r}; the factors read are not the ones the score used"
        )


def export(release: dict[str, Any], config: dict[str, Any], *, only: list[str], size: int | None) -> dict[str, Any]:
    import bw2calc as bc
    import bw2data as bd

    ensure_database(release)
    database = bd.Database(release["brightway_database"])
    methods = methods_for(release)
    log(f"{len(methods)} methods under {release['method_family']!r}")

    sample_size = size or int(config["sample_size"])
    processes = select(
        database,
        size=sample_size,
        seed=int(config["sample_seed"]),
        always=list(release.get("reference_activities", [])),
        only=only,
    )
    log(f"{len(processes)} unit processes selected")

    lca = bc.LCA({processes[0]: 1}, method=methods[0])
    lca.lci(factorize=True)
    log("technosphere factorised")

    # One characterisation vector per method, aligned with the biosphere rows,
    # loaded once.  The score is inventory . vector, which is exactly what the
    # artifact's own recompute check does -- so the factors written are the
    # factors the scores used, by construction rather than by reconciliation.
    vectors: dict[str, Any] = {}
    for method in methods:
        lca.switch_method(method)
        lca.lcia()
        vectors[category_key(method)] = lca.characterization_matrix.diagonal().copy()
    log(f"{len(vectors)} characterisation vectors loaded")

    # Biosphere row -> node id -> node, once.  The importer sets a biosphere
    # node's `code` to the vendor's flow uuid, which is what the artifact keys on.
    biosphere_nodes: dict[int, Any] = {}
    flows: dict[str, dict[str, Any]] = {}

    def node_for(node_id: int) -> Any:
        node = biosphere_nodes.get(node_id)
        if node is None:
            node = bd.get_node(id=node_id)
            biosphere_nodes[node_id] = node
        return node

    unit_processes: list[dict[str, Any]] = []
    started = time.monotonic()
    for index, process in enumerate(processes, start=1):
        lca.lci({process.id: 1})
        column = lca.inventory.sum(axis=1)
        vector = column.A1 if hasattr(column, "A1") else column.ravel()
        inventory: list[dict[str, Any]] = []
        for row, amount in enumerate(vector):
            if amount == 0 or not math.isfinite(amount):
                if not math.isfinite(amount):
                    raise SystemExit(f"{process['code']}: non-finite inventory amount")
                continue
            node = node_for(lca.dicts.biosphere.reversed[row])
            flows.setdefault(node["code"], flow_record(node))
            inventory.append({"source_flow_uuid": node["code"], "amount": float(amount)})
        scores = {key: float(vector @ cf) for key, cf in vectors.items()}
        classifications: dict[str, str] = {}
        for scheme, value in process.get("classifications", ()) or ():
            classifications.setdefault(str(scheme), str(value))
        unit_processes.append({
            "activity_code": process["code"],
            "activity_uuid": str(process.get("activity") or process.get("filename") or ""),
            "name": process["name"],
            "reference_product": str(process.get("reference product") or ""),
            "product_amount": float(process.get("production amount") or 1.0),
            "product_unit": str(process.get("unit") or ""),
            "geography": str(process.get("location") or ""),
            "classifications": classifications,
            "inventory": inventory,
            "scores": scores,
        })
        if index % 25 == 0 or index == len(processes):
            elapsed = time.monotonic() - started
            log(f"{index}/{len(processes)} scored, {elapsed:.0f}s")

    # Rows in the sample's inventories, and the vendor's uuid for each.
    rows = {
        lca.dicts.biosphere[node_id]: node["code"] for node_id, node in biosphere_nodes.items()
    }
    factors: list[dict[str, Any]] = []
    categories: list[dict[str, Any]] = []
    for method in methods:
        key = category_key(method)
        meta = bd.Method(method).metadata
        categories.append({
            "key": key,
            "method_family": method[1],
            "category": method[2] if len(method) > 2 else "",
            "indicator": method[3] if len(method) > 3 else "",
            "unit": str(meta.get("unit", "")),
        })
        cf = vectors[key]
        by_flow = {code: float(cf[row]) for row, code in rows.items() if cf[row] != 0}
        for code, amount in sorted(by_flow.items()):
            factors.append({"category_key": key, "source_flow_uuid": code, "amount": amount})
        for process in unit_processes:
            recompute(
                process["inventory"], by_flow,
                stated=process["scores"][key],
                where=f"{process['activity_code']} / {key}",
            )
    log(f"{len(factors)} factors on {len(flows)} flows; every score recomputes")

    import bw2io

    return {
        "schema_version": SCHEMA_VERSION,
        "release": {
            "list_name": release["list_name"],
            "list_version": release["list_version"],
            "system_model": release["system_model"],
            "brightway_project": release["brightway_project"],
            "brightway_database": release["brightway_database"],
            "method_family": release["method_family"],
            "generator": {
                "python": sys.version.split()[0],
                "bw2data": _version(bd),
                "bw2calc": _version(bc),
                "bw2io": _version(bw2io),
            },
            "created_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "sample_size": sample_size,
            "sample_seed": int(config["sample_seed"]),
        },
        "categories": categories,
        "flows": [flows[code] for code in sorted(flows)],
        "factors": factors,
        "unit_processes": unit_processes,
    }


def _version(module: Any) -> str:
    version = getattr(module, "__version__", "")
    if isinstance(version, (tuple, list)):
        return ".".join(str(part) for part in version)
    return str(version)


def validate(document: dict[str, Any]) -> None:
    try:
        import jsonschema
    except ImportError:
        log("jsonschema is not installed here; skipping schema validation")
        return
    schema = json.loads(SCHEMA_PATH.read_text())
    errors = sorted(
        jsonschema.Draft202012Validator(schema).iter_errors(document),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        error = errors[0]
        where = "/".join(str(part) for part in error.absolute_path) or "document"
        raise SystemExit(f"the export does not match {SCHEMA_PATH.name}: {where}: {error.message}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("config", help="JSON from `brightway-flows score-comparison-config`, or - for stdin")
    parser.add_argument("--release", required=True, help="e.g. ecoinvent-3.8-apos")
    parser.add_argument("--out", help="where to write; defaults to artifact_dir/artifact from the config")
    parser.add_argument("--sample-size", type=int, help="override the config's sample size")
    parser.add_argument(
        "--only-codes", action="append", default=[], metavar="CODE",
        help="score only these brightway activity codes (repeatable); for cutting a fixture",
    )
    args = parser.parse_args(argv)

    config = read_config(args.config)
    release = release_from(config, args.release)
    out = Path(args.out) if args.out else Path(config["artifact_dir"]) / release["artifact"]

    document = export(release, config, only=args.only_codes, size=args.sample_size)
    validate(document)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(document, indent=1) + "\n")
    log(
        f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB): "
        f"{len(document['unit_processes'])} unit processes, "
        f"{len(document['categories'])} categories, {len(document['flows'])} flows"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
