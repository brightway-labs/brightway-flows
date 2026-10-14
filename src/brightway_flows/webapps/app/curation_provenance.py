"""Read an evidence audit bound to the exact register and preserved source bytes.

An audit checks capture and exposes missing support. It never supplies a
scientific approval or changes a case's lifecycle or the harmonisation build.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from pydantic import TypeAdapter

from .curation import (
    Digest,
    Identifier,
    Link,
    RecordedAt,
    Register,
    Validation,
    _Record,
)


class CheckState(StrEnum):
    MATCHED = "matched"
    INCOMPLETE = "incomplete"
    MISMATCH = "mismatch"
    NOT_ASSESSED = "not-assessed"
    NOT_APPLICABLE = "not-applicable"


class GapKind(StrEnum):
    TRACE = "trace"
    SCOPE = "scope"
    BASIS = "basis"
    REPRODUCTION = "reproduction"
    ATTRIBUTION = "attribution"
    REVIEW = "review"
    CONTRADICTION = "contradiction"


class ClaimState(StrEnum):
    SUPPORTED = "supported"
    PARTIAL = "partial"
    CONFLICTING = "conflicting"
    NOT_ESTABLISHED = "not-established"


CLAIM_LABELS = {
    ClaimState.SUPPORTED: "Supported within stated scope",
    ClaimState.PARTIAL: "Partially supported",
    ClaimState.CONFLICTING: "Description conflicts with source",
    ClaimState.NOT_ESTABLISHED: "Not established",
}


GAP_LABELS = {
    GapKind.TRACE: "Source trace",
    GapKind.SCOPE: "Applicability & scope",
    GapKind.BASIS: "Scientific basis",
    GapKind.REPRODUCTION: "Reproduction",
    GapKind.ATTRIBUTION: "Attribution",
    GapKind.REVIEW: "Scientific review",
    GapKind.CONTRADICTION: "Conflicting evidence",
}


@dataclass(frozen=True)
class SourceFact(_Record):
    label: str
    value: str
    evidence_url: Link


@dataclass(frozen=True)
class EvidenceGap(_Record):
    code: Identifier
    kind: GapKind
    title: str
    detail: str
    action: str
    evidence_urls: list[Link] = field(default_factory=list)


@dataclass(frozen=True)
class TraceCheck(_Record):
    label: str
    url: Link
    state: CheckState
    detail: str
    document_id: Identifier | None = None


@dataclass(frozen=True)
class DocumentCheck(_Record):
    id: Identifier
    sha256: Digest
    state: CheckState
    origin_state: CheckState
    detail: str


@dataclass(frozen=True)
class ClaimReview(_Record):
    id: Identifier
    claim: str
    summary_sha256: Digest
    state: ClaimState
    conclusion: str
    supported_scope: str
    remaining: str
    sources: list[Link]

    @property
    def label(self) -> str:
        return CLAIM_LABELS[self.state]


@dataclass(frozen=True)
class ClaimReviewReceipt(_Record):
    schema_version: int
    recorded_at: RecordedAt
    method: str
    source_sha256: dict[Identifier, Digest]
    scientific_signoff: bool
    claims: list[ClaimReview]


@dataclass(frozen=True)
class EvidenceRecovery(_Record):
    previous_document: Identifier
    recorded_at: RecordedAt
    review: ClaimReview
    recovered: list[str]
    resolved_gaps: list[Identifier]
    facts: list[SourceFact]
    remaining_gaps: list[EvidenceGap] = field(default_factory=list)


@dataclass(frozen=True)
class EvidenceRecoveryReceipt(_Record):
    schema_version: int
    recorded_at: RecordedAt
    method: str
    source_sha256: dict[Identifier, Digest]
    scientific_signoff: bool
    entries: list[EvidenceRecovery]


@dataclass(frozen=True)
class EvidenceSupplement(_Record):
    id: Identifier
    facts: list[SourceFact]
    gaps: list[EvidenceGap]
    sources: list[Link]


@dataclass(frozen=True)
class EvidenceSupplementReceipt(_Record):
    schema_version: int
    recorded_at: RecordedAt
    method: str
    source_sha256: dict[Identifier, Digest]
    case_sha256: dict[Identifier, Digest]
    scientific_signoff: bool
    entries: list[EvidenceSupplement]


@dataclass(frozen=True)
class ApplicationCheck(_Record):
    id: Identifier
    case_ids: list[Identifier]
    validation: Validation
    expected: str
    observed: str
    remaining: str
    sources: list[Link]


@dataclass(frozen=True)
class ApplicationCheckReceipt(_Record):
    schema_version: int
    recorded_at: RecordedAt
    method: str
    source_sha256: dict[Identifier, Digest]
    case_sha256: dict[Identifier, Digest]
    scientific_signoff: bool
    checks: list[ApplicationCheck]


@dataclass(frozen=True)
class CaseAudit(_Record):
    id: Identifier
    kind: str
    derivation: str
    capture: CheckState
    capture_detail: str
    traces: list[TraceCheck]
    facts: list[SourceFact]
    gaps: list[EvidenceGap]
    claims: list[ClaimReview] = field(default_factory=list)
    recoveries: list[EvidenceRecovery] = field(default_factory=list)
    applications: list[ApplicationCheck] = field(default_factory=list)

    @property
    def label(self) -> str:
        if self.capture == CheckState.MISMATCH or any(
            g.kind == GapKind.CONTRADICTION for g in self.gaps
        ):
            return "Conflicting evidence"
        if self.capture == CheckState.INCOMPLETE:
            return "Trace incomplete"
        if self.capture == CheckState.NOT_APPLICABLE:
            return "Documentation index"
        if self.capture == CheckState.NOT_ASSESSED:
            return "Claim not checked"
        return "Source record matched"

    @property
    def claim_label(self) -> str:
        review = self.current_review
        return review.label if review else "Description not compared"

    @property
    def current_review(self) -> ClaimReview | None:
        if self.recoveries:
            return self.recoveries[-1].review
        return self.claims[-1] if self.claims else None


def summary_digest(case) -> str:
    """A source comparison names the exact descriptive claim it inspected."""
    return hashlib.sha256(case.summary.encode()).hexdigest()


def case_identity_digest(case) -> str:
    """Bind application evidence to the original record and descriptive identity."""
    raw = json.dumps(
        {
            name: getattr(case, name)
            for name in ("id", "reference_id", "revision", "summary", "original_record")
        },
        sort_keys=True,
        ensure_ascii=False,
    ).encode()
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class ProvenanceAudit(_Record):
    schema_version: int
    recorded_at: RecordedAt
    register_sha256: Digest
    tool_sha256: Digest
    tool_path: str
    method: str
    documents: list[DocumentCheck]
    cases: list[CaseAudit]


@dataclass(frozen=True)
class AuditView:
    audit: ProvenanceAudit | None
    status: str
    cases: dict[str, CaseAudit] = field(default_factory=dict)

    def counts(self, case_ids) -> Counter:
        return Counter(
            kind
            for identifier in case_ids
            if identifier in self.cases
            for kind in {g.kind for g in self.cases[identifier].gaps}
        )


def read_audit(register_path: Path, register: Register, root: Path) -> AuditView:
    """A changed register, tool or source invalidates the entire audit visibly.

    Rehashing is intentional: preserved bytes can change without the register
    changing. No cached success should survive that edit.
    """
    path = register_path.with_name("provenance-audit.json")
    if not path.exists():
        return AuditView(None, "No evidence audit recorded")
    audit = TypeAdapter(ProvenanceAudit).validate_json(path.read_bytes())
    if audit.schema_version != 1:
        raise ValueError("Unsupported provenance audit version")
    ids = [c.id for c in audit.cases]
    if len(ids) != len(set(ids)) or set(ids) != {c.id for c in register.cases}:
        return AuditView(audit, "Audit is stale: case membership changed")
    if hashlib.sha256(register_path.read_bytes()).hexdigest() != audit.register_sha256:
        return AuditView(audit, "Audit is stale: register changed")
    tool = (root / audit.tool_path).resolve()
    if not tool.is_relative_to(root.resolve()) or not tool.is_file():
        return AuditView(audit, "Audit tool is unavailable")
    if hashlib.sha256(tool.read_bytes()).hexdigest() != audit.tool_sha256:
        return AuditView(audit, "Audit is stale: verification procedure changed")
    documents = {d.id: d for d in audit.documents}
    if len(documents) != len(audit.documents) or set(documents) != {
        d.id for d in register.documents
    }:
        raise ValueError("Audit document coverage does not match the register")
    for document in register.documents:
        source = (register_path.parent / "sources" / document.filename).resolve()
        if not source.is_relative_to((register_path.parent / "sources").resolve()):
            raise ValueError("Source path escapes evidence directory")
        if (
            not source.is_file()
            or hashlib.sha256(source.read_bytes()).hexdigest()
            != documents[document.id].sha256
        ):
            return AuditView(audit, "Audit is stale: preserved source changed")
    from . import curation_mapping_provenance as mapping

    mapping_path = mapping.manifest_path(register_path, register)
    if mapping_path:
        try:
            manifest = mapping.verify_manifest(mapping_path, root)
            known = {c.id: c for c in register.cases}
            for identifier, digest in manifest.case_sha256.items():
                if identifier not in known or case_identity_digest(known[identifier]) != digest:
                    return AuditView(audit, "Audit is stale: mapping case identity changed")
        except ValueError, OSError:
            return AuditView(audit, "Audit is stale: original mapping inputs or verification changed")
    return AuditView(audit, "Current evidence audit", {c.id: c for c in audit.cases})
