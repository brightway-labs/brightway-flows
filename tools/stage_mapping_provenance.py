"""Preserve and verify original mapping assertions; no harmonisation or adoption.

The input manifest's files live in its sibling source-inputs directory. Output
must be new. Every original is copied and checked before and after processing.
"""

from __future__ import annotations

import argparse
import json
import shutil
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from pydantic import TypeAdapter

from brightway_flows.webapps.app import curation
from brightway_flows.webapps.app import curation_mapping_provenance as mapping
from brightway_flows.webapps.app.curation_provenance import case_identity_digest

ROOT = Path(__file__).resolve().parents[1]


def _payload(path, rows, model):
    count = 0
    adapter = TypeAdapter(model)
    with path.open("xb") as stream:
        for row in rows:
            stream.write(mapping.encoded(adapter.dump_python(row, mode="json")) + b"\n")
            count += 1
    return mapping.Payload(path.name, mapping.sha(path.read_bytes()), count)


def stage(input_manifest: Path, register_path: Path, output: Path):
    raw = input_manifest.read_bytes()
    inputs = TypeAdapter(mapping.Inputs).validate_json(raw)
    if inputs.schema_version != 1 or inputs.scientific_signoff:
        raise ValueError(
            "Only version-one custody inputs without scientific sign-off are accepted"
        )
    if len({a.id for a in inputs.artifacts}) != len(inputs.artifacts):
        raise ValueError("Duplicate source artifact identity")
    register = curation.read_register(register_path)
    if register is None:
        raise ValueError("Register is unavailable")
    procedures = {
        name: mapping.sha((ROOT / name).read_bytes())
        for name in sorted(mapping.PROCEDURE_PATHS)
    }
    output.mkdir(parents=True, exist_ok=False)
    custody = output / "source-inputs"
    custody.mkdir()
    for artifact in inputs.artifacts:
        source = mapping._safe_path(
            input_manifest.parent / "source-inputs", artifact.filename
        )
        if mapping.sha(source.read_bytes()) != artifact.sha256:
            raise ValueError("Original input does not match its pin")
        target = mapping._safe_path(custody, artifact.filename)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        if mapping.sha(target.read_bytes()) != artifact.sha256:
            raise ValueError("Preservation changed original bytes")
    (output / "mapping-source-inputs.json").write_bytes(raw)
    rows = mapping.assertions_from_inputs(inputs, custody)
    assertions = _payload(output / "mapping-assertions.jsonl", rows, mapping.Assertion)
    aliases = list(mapping.aliases_from_inputs(inputs, custody, rows))
    alias_payload = _payload(
        output / "historical-mapping-traces.jsonl", aliases, mapping.AliasTrace
    )
    row_by_code, alias_by_code = defaultdict(set), defaultdict(set)
    for row in rows:
        if row.status == mapping.Status.QUARANTINED:
            continue
        for code in [row.source.identifier, *(t.identifier for t in row.targets)]:
            if code:
                row_by_code[code].add(row.id)
    original = next(
        a for a in inputs.artifacts if a.adapter == mapping.Adapter.HISTORICAL
    )
    history = mapping.loads_original(
        mapping._safe_path(custody, original.filename).read_text()
    )
    for index in history["index"].values():
        for code, alias in index.items():
            if mapping.valid_identifier(code):
                alias_by_code[code].add(alias)
    known_codes = set(row_by_code) | set(alias_by_code)
    precise_rows = {(r.artifact_id, r.locator): r.id for r in rows}

    def identifiers(value):
        result = set()
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"csv_row", "reference_id", "case_id"}:
                    continue
                if isinstance(item, str) and item in known_codes:
                    result.add(item)
                elif isinstance(item, (dict, list)):
                    result.update(identifiers(item))
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str) and item in known_codes:
                    result.add(item)
                elif isinstance(item, (dict, list)):
                    result.update(identifiers(item))
        return result

    links = {}
    for case in register.cases:
        original = json.loads(case.original_record) if case.original_record else {}
        codes = identifiers(original)
        linked_rows = set().union(*(row_by_code[c] for c in codes))
        linked_aliases = set().union(*(alias_by_code[c] for c in codes))
        # For the selected FEDEFL assertions the precise original CSV row is
        # stronger than other rows sharing that identifier.
        if case.collection == "External synonym assertions":
            linked_rows = {precise_rows["fedefl", f"csv-row:{original['csv_row']}"]}
        if case.collection == "Source provenance findings":
            matched = [
                r
                for r in rows
                if r.artifact_id == original["artifact_id"]
                and original["issue"] in r.issues
            ]
            linked_rows = {r.id for r in matched}
            if len(linked_rows) != original["count"]:
                raise ValueError("Source provenance finding population changed")
            if (
                sorted(int(r.locator.rsplit("/", 1)[-1]) for r in matched)
                != original["original_row_indexes"]
                or next(
                    a.sha256
                    for a in inputs.artifacts
                    if a.id == original["artifact_id"]
                )
                != original["original_source_sha256"]
            ):
                raise ValueError(
                    "Source provenance finding coordinates or original digest differ"
                )
        if linked_rows or linked_aliases:
            links[case.id] = {
                "assertions": sorted(linked_rows),
                "aliases": sorted(linked_aliases),
            }
    manifest = mapping.Manifest(
        1,
        datetime.now(timezone.utc),
        inputs,
        mapping.sha(raw),
        procedures,
        mapping.runtime(),
        assertions,
        alias_payload,
        links,
        {c.id: case_identity_digest(c) for c in register.cases if c.id in links},
        mapping.counts(rows),
        False,
        False,
    )
    mapping.verify_content(manifest, output)
    for name, digest in procedures.items():
        if mapping.sha((ROOT / name).read_bytes()) != digest:
            raise ValueError("Source mapping verifier changed during execution")
    for artifact in inputs.artifacts:
        if (
            mapping.sha(
                mapping._safe_path(
                    input_manifest.parent / "source-inputs", artifact.filename
                ).read_bytes()
            )
            != artifact.sha256
        ):
            raise ValueError("Original input changed during execution")
    path = output / "mapping-provenance-manifest.json"
    path.write_bytes(TypeAdapter(mapping.Manifest).dump_json(manifest, indent=2))
    mapping.verify_manifest(path, ROOT)
    (output / "COMPLETE.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "manifest_sha256": mapping.sha(path.read_bytes()),
                "assertions": assertions.rows,
                "historical_aliases": alias_payload.rows,
                "full_original_row_reproduction": True,
                "scientific_signoff": False,
                "consumer_adoption": False,
            },
            indent=2,
        )
        + "\n"
    )
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--register", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = stage(args.inputs, args.register, args.output)
    print(
        json.dumps(
            {
                "assertions": manifest.assertions.rows,
                "aliases": manifest.aliases.rows,
                "counts": manifest.counts,
                "output": str(args.output),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
