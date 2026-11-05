"""Verify retained JRC provider rows against their original workbook.

This checks source custody and copied statements, not scientific application.
Provide independently reviewed profile/workbook hashes with their paths and a
new output directory. See docs/curation/source-mapping-provenance.md.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import platform
import re

import openpyxl
import pydantic
from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, TypeAdapter


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class FactorPayload(BaseModel):
    """Original external profile fields remain in the hash-pinned payload."""

    model_config = ConfigDict(strict=True, extra="allow")
    value: StrictFloat | StrictInt
    provider_flow_metadata: dict
    provider_factor_rows: list[dict]


class ProfilePayload(BaseModel):
    model_config = ConfigDict(strict=True, extra="allow")
    profile_schema: str = Field(alias="schema")
    source_pins: dict
    factors: list[FactorPayload]
    method_metadata: list[dict]


@dataclass(frozen=True)
class RowTrace:
    profile_pointer: str
    sheet: str
    row: int
    row_sha256: str


@dataclass(frozen=True)
class SourceVerification:
    schema_version: int
    recorded_at: datetime
    profile_sha256: str
    workbook_sha256: str
    factors: int
    unique_original_rows: int
    traces: list[RowTrace]
    scope: str
    unresolved: list[str]
    scientific_acceptance: bool = False
    consumer_adoption: bool = False


def _coordinate(record: dict, sheet: str, pointer: str):
    row = record.get("workbook_row")
    if isinstance(row, bool) or not isinstance(row, int) or row < 2:
        raise ValueError(f"Missing original workbook coordinate: {pointer}")
    return sheet, row


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate profile JSON key: {key}")
        result[key] = value
    return result


def verify(profile_path: Path, workbook_path: Path, *, expected_profile_sha256: str,
           expected_workbook_sha256: str) -> SourceVerification:
    """Compare every declared original cell without executing formulas.

    A factor's literal value must occur in its retained original factor rows.
    Which method should win, context/unit interpretation and downstream
    application remain separate review questions.
    """
    pins = {profile_path: sha(profile_path), workbook_path: sha(workbook_path)}
    expected_pins = {profile_path: expected_profile_sha256,
                     workbook_path: expected_workbook_sha256}
    if any(not re.fullmatch(r"[0-9a-f]{64}", value) for value in expected_pins.values()):
        raise ValueError("Independent source pins must be full SHA-256 digests")
    if pins != expected_pins:
        raise ValueError("Provider bytes differ from independent expected pins")
    raw = json.loads(profile_path.read_bytes(), object_pairs_hook=_unique_keys)
    profile = ProfilePayload.model_validate(raw)
    if profile.profile_schema != "consensus-method-profile/v1":
        raise ValueError("Unsupported method profile")
    if profile.source_pins.get("workbook_sha256") != pins[workbook_path]:
        raise ValueError("Workbook differs from the profile source pin")
    if not profile.factors or not profile.method_metadata:
        raise ValueError("Provider profile needs original factors and methods")
    expected = {}
    claims = []

    def add(record, sheet, pointer):
        key = _coordinate(record, sheet, pointer)
        original = {k: v for k, v in record.items() if k != "workbook_row"}
        if key in expected and expected[key] != original:
            raise ValueError(f"Conflicting copies of original row: {pointer}")
        expected[key] = original
        claims.append((key, pointer))

    for index, record in enumerate(profile.method_metadata):
        add(record, "lciamethods", f"/method_metadata/{index}")
    for index, factor in enumerate(profile.factors):
        prefix = f"/factors/{index}"
        if not math.isfinite(factor.value):
            raise ValueError(f"Non-finite profile factor: {prefix}")
        add(factor.provider_flow_metadata, "flows", prefix + "/provider_flow_metadata")
        if not factor.provider_factor_rows:
            raise ValueError(f"No original provider factor rows: {prefix}")
        identity = factor.provider_flow_metadata.get("FLOW_uuid")
        if not isinstance(identity, str) or not identity:
            raise ValueError(f"Missing original provider identity: {prefix}")
        original_values = []
        for offset, record in enumerate(factor.provider_factor_rows):
            pointer = prefix + f"/provider_factor_rows/{offset}"
            add(record, "lciamethods_CF", pointer)
            if record.get("FLOW_uuid") != identity:
                raise ValueError(f"Factor and flow have different original identities: {pointer}")
            value = record.get("CF EF3.1")
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value)):
                raise ValueError(f"Original factor is not a finite literal: {pointer}")
            original_values.append(value)
        if factor.value not in original_values:
            raise ValueError(f"Profile value absent from its original factor rows: {prefix}")

    actual = {}
    workbook = openpyxl.load_workbook(workbook_path, read_only=True, data_only=False)
    try:
        for sheet in sorted({key[0] for key in expected}):
            if sheet not in workbook:
                raise ValueError(f"Missing original worksheet: {sheet}")
            records = workbook[sheet].iter_rows(values_only=True)
            headers = next(records, ())
            if (not headers or any(not isinstance(h, str) or not h for h in headers)
                    or len(set(headers)) != len(headers)):
                raise ValueError(f"Missing or duplicate original headers: {sheet}")
            last = max(row for name, row in expected if name == sheet)
            for number, cells in enumerate(records, 2):
                key = sheet, number
                if key in expected:
                    row = dict(zip(headers, cells, strict=True))
                    if row != expected[key]:
                        raise ValueError(f"Retained provider row differs from original: {sheet}:{number}")
                    actual[key] = row
                if number >= last:
                    break
    finally:
        workbook.close()
    if actual.keys() != expected.keys():
        raise ValueError("Declared original workbook rows are absent")
    if pins != {path: sha(path) for path in pins}:
        raise ValueError("Provider inputs changed during verification")
    traces = [RowTrace(pointer, *key, hashlib.sha256(json.dumps(actual[key],
                  sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest())
              for key, pointer in claims]
    return SourceVerification(
        1, datetime.now(timezone.utc), pins[profile_path], pins[workbook_path],
        len(profile.factors), len(actual), traces,
        "All retained original provider rows and literal factor values compared with the pinned workbook; formulas never executed.",
        ["Target identity/context/unit interpretation is not recomputed by this check.",
         "Method priority, regional selection and scientific policy acceptance remain unreviewed here.",
         "Historical execution ancestry and current registered/served consumer generations remain unverified."],
    )


def run(profile: Path, workbook: Path, output: Path, *, expected_profile_sha256: str,
        expected_workbook_sha256: str):
    """Publish source verification only after all original-row checks pass."""
    procedure = Path(__file__).resolve()
    procedure_sha256 = sha(procedure)
    output.mkdir(parents=True, exist_ok=False)
    verification = verify(profile, workbook, expected_profile_sha256=expected_profile_sha256,
                          expected_workbook_sha256=expected_workbook_sha256)
    if sha(procedure) != procedure_sha256:
        raise ValueError("Verification procedure changed")
    raw = TypeAdapter(SourceVerification).dump_json(verification, indent=2)
    (output / "source-verification.json").write_bytes(raw)
    procedure_raw = procedure.read_bytes()
    (output / "verification-procedure.py").write_bytes(procedure_raw)
    lock = procedure.parent.parent / "uv.lock"
    lock_raw = lock.read_bytes()
    (output / "uv.lock").write_bytes(lock_raw)
    receipt = {
        "schema": "method-provider-source-verification/v1",
        "procedure_sha256": procedure_sha256,
        "runtime": {"python": platform.python_version(), "openpyxl": openpyxl.__version__,
                    "pydantic": pydantic.__version__},
        "files": {"source-verification.json": hashlib.sha256(raw).hexdigest(),
                  "verification-procedure.py": hashlib.sha256(procedure_raw).hexdigest(),
                  "uv.lock": hashlib.sha256(lock_raw).hexdigest()},
        "profile_path": str(profile.resolve()), "workbook_path": str(workbook.resolve()),
        "scientific_acceptance": False, "consumer_adoption": False,
    }
    if (sha(profile) != verification.profile_sha256
            or sha(workbook) != verification.workbook_sha256
            or sha(procedure) != procedure_sha256
            or sha(lock) != receipt["files"]["uv.lock"]):
        raise ValueError("Provider inputs or procedure changed before publication")
    (output / "COMPLETE.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return verification


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--workbook", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-profile-sha256", required=True)
    parser.add_argument("--expected-workbook-sha256", required=True)
    args = parser.parse_args()
    receipt = run(args.profile, args.workbook, args.output,
                  expected_profile_sha256=args.expected_profile_sha256,
                  expected_workbook_sha256=args.expected_workbook_sha256)
    print(json.dumps({"factors": receipt.factors, "original_rows": receipt.unique_original_rows,
                      "references": len(receipt.traces), "scientific_acceptance": False}))


if __name__ == "__main__":
    main()
