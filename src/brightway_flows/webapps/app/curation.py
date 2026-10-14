"""Read-only curation records joining evidence to existing executable modules.

The register explains decisions; nothing in the pipeline imports it. Validation
of the file happens once on reading. The rest of the application uses records.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated
from urllib.parse import urlsplit

from pydantic import AfterValidator, ConfigDict, StringConstraints, TypeAdapter

from brightway_flows.webapps.app import documentation


class Stage(StrEnum):
    RECORDED = "recorded"
    REVIEW = "review"
    IMPLEMENTED = "implemented"
    WITHDRAWN = "withdrawn"


STAGES = {
    Stage.RECORDED: "Finding recorded",
    Stage.REVIEW: "Proposal in review",
    Stage.IMPLEMENTED: "Module implemented",
    Stage.WITHDRAWN: "Withdrawn",
}


class Origin(StrEnum):
    SOURCE = "source"
    PROCESSING = "processing"
    FINDING_CLASS = "finding-class"


class Result(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    REPORTED = "reported"
    BLOCKED = "blocked"


class ReviewScope(StrEnum):
    CODE = "code"
    SCIENTIFIC = "scientific"


class ProposalKind(StrEnum):
    ISSUE = "Issue"
    DISCUSSION = "Discussion"
    PULL_REQUEST = "Pull request"


class ProposalState(StrEnum):
    OPEN = "open"
    CLOSED = "closed"
    MERGED = "merged"
    UNKNOWN = "not checked"


class ImplementationRole(StrEnum):
    HISTORICAL = "Historical local implementation"
    CURRENT = "Recorded implementation"
    CANDIDATE = "Candidate implementation"


class Verdict(StrEnum):
    APPROVED = "approved"
    CHANGES_REQUESTED = "changes-requested"
    WITHDRAWN = "withdrawn"


def _safe_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme == "https" and parsed.netloc and not parsed.username:
        return value
    if value.startswith("/") and not value.startswith("//") and "\\" not in value:
        return value
    raise ValueError("References must use HTTPS or an application-relative path")


Link = Annotated[str, AfterValidator(_safe_url)]
Revision = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]
Identifier = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]+$")]
Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


def _aware_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Record dates must carry a timezone")
    return value


RecordedAt = Annotated[datetime, AfterValidator(_aware_datetime)]


class _Record:
    __pydantic_config__ = ConfigDict(extra="forbid")


@dataclass(frozen=True)
class Evidence(_Record):
    label: str
    url: Link
    kind: str
    note: str = ""


@dataclass(frozen=True)
class Proposal(_Record):
    title: str
    url: Link
    kind: ProposalKind
    state: ProposalState
    author: str | None
    recorded_at: RecordedAt | None
    note: str = ""


@dataclass(frozen=True)
class Validation(_Record):
    label: str
    result: Result
    revision: Revision
    scope: str
    recorded_at: RecordedAt
    evidence_url: Link
    note: str


@dataclass(frozen=True)
class SignOff(_Record):
    person: str
    scope: ReviewScope
    verdict: Verdict
    revision: Revision
    recorded_at: RecordedAt
    evidence_url: Link
    note: str = ""


@dataclass(frozen=True)
class Event(_Record):
    label: str
    recorded_at: RecordedAt
    person: str
    evidence_url: Link
    note: str = ""


@dataclass(frozen=True)
class Adoption(_Record):
    release: str
    revision: Revision
    evidence_url: Link
    recorded_at: RecordedAt


@dataclass(frozen=True)
class Implementation(_Record):
    label: str
    url: Link
    role: ImplementationRole
    revision: Revision
    path: str
    author: str | None = None
    authored_at: RecordedAt | None = None
    note: str = ""


@dataclass(frozen=True)
class Document(_Record):
    id: Identifier
    title: str
    filename: str
    sha256: Digest
    generation: str
    origin_url: Link | None = None


@dataclass(frozen=True)
class Case(_Record):
    id: Identifier
    title: str
    summary: str
    reason: str
    origin: Origin
    stage: Stage
    sources: list[str]
    tags: list[str]
    revision: Revision
    updated_at: RecordedAt
    reported_by: str | None
    reported_at: RecordedAt | None
    owner: str | None
    next_action: str
    evidence: list[Evidence]
    proposals: list[Proposal] = field(default_factory=list)
    modules: list[str] = field(default_factory=list)
    test_paths: list[str] = field(default_factory=list)
    expectation_paths: list[str] = field(default_factory=list)
    validations: list[Validation] = field(default_factory=list)
    signoffs: list[SignOff] = field(default_factory=list)
    history: list[Event] = field(default_factory=list)
    adoption: Adoption | None = None
    collection: str = "Public examples"
    reference_id: str = ""
    disposition: str = ""
    original_record: str = ""
    implementations: list[Implementation] = field(default_factory=list)
    proposed_modules: list[str] = field(default_factory=list)
    related_cases: list[Identifier] = field(default_factory=list)

    @property
    def code_authors(self) -> tuple[str, ...]:
        return tuple(sorted({i.author for i in self.implementations if i.author}))

    @property
    def contributors(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                set(self.code_authors)
                | ({self.reported_by} if self.reported_by else set())
            )
        )

    @property
    def contributor_label(self) -> str:
        if self.reported_by:
            return self.reported_by
        return (
            "Code: " + ", ".join(self.code_authors)
            if self.code_authors
            else "Not recorded"
        )

    @property
    def stage_label(self) -> str:
        return STAGES[self.stage]

    @property
    def quality(self) -> str:
        current = [v for v in self.validations if v.revision == self.revision]
        if any(v.result == Result.FAILED for v in current):
            return "Check failed"
        if any(v.result == Result.BLOCKED for v in current):
            return "Validation incomplete"
        if any(v.result == Result.PASSED for v in current):
            return "Focused checks pass"
        if any(v.result == Result.REPORTED for v in current):
            return "Checks reported"
        if self.validations:
            return "Validation stale"
        return "Not validated here"

    @property
    def signoff_label(self) -> str:
        scientific = [s for s in self.signoffs if s.scope == ReviewScope.SCIENTIFIC]
        current = [s for s in scientific if s.revision == self.revision]
        if not scientific:
            return "Not recorded"
        if not current:
            return "Stale revision"
        latest_by_person = {}
        for review in sorted(current, key=lambda s: s.recorded_at):
            latest_by_person[review.person] = review
        # One person's approval cannot clear another person's requested changes.
        for verdict, label in (
            (Verdict.CHANGES_REQUESTED, "Changes requested"),
            (Verdict.APPROVED, "Approval recorded"),
            (Verdict.WITHDRAWN, "Withdrawn"),
        ):
            names = sorted(
                s.person for s in latest_by_person.values() if s.verdict == verdict
            )
            if names:
                return f"{label} · {', '.join(names)}"
        return "Not recorded"


@dataclass(frozen=True)
class ReviewPackage(_Record):
    id: Identifier
    title: str
    workstream: str
    summary: str
    grouping_rule: str
    decision: str
    case_ids: list[Identifier]


@dataclass(frozen=True)
class Register(_Record):
    schema_version: int
    recorded_at: RecordedAt
    source_revision: Revision
    coverage: str
    cases: list[Case]
    title: str = "Selected public examples and finding classes"
    documents: list[Document] = field(default_factory=list)
    packages: list[ReviewPackage] = field(default_factory=list)


def register_path(docs_root: Path, configured: str | Path | None = None) -> Path:
    """Documentation and Curation must read the same selected register."""
    return Path(configured) if configured else docs_root / "curation/register.json"


def documentation_slugs(case: Case, root: Path) -> tuple[str, ...]:
    """Explicit local documentation evidence, resolved by the ordinary docs reader.

    Matching titles or substances would invent a relationship. Only a cited
    page counts; aliases, Markdown suffixes and section anchors resolve together.
    """
    slugs = []
    for evidence in case.evidence:
        reference = urlsplit(evidence.url)
        if reference.netloc or not reference.path.startswith("/docs/"):
            continue
        found = documentation.resolve(root, reference.path.removeprefix("/docs/"))
        if found and found[0] == "page":
            slugs.append(
                found[1].relative_to(root.resolve()).with_suffix("").as_posix()
            )
    return tuple(dict.fromkeys(slugs))


def cases_for_document(register: Register, root: Path, slug: str) -> tuple[Case, ...]:
    """Cases citing this page, or pages beneath a documentation index."""
    prefix = slug.removesuffix("index") if slug.endswith("/index") else None
    return tuple(
        case
        for case in register.cases
        if any(
            reference == slug or (prefix and reference.startswith(prefix))
            for reference in documentation_slugs(case, root)
        )
    )


def read_register(path: Path) -> Register | None:
    """Missing is an explicit empty state; malformed never becomes an empty list."""
    if not path.exists():
        return None
    register = TypeAdapter(Register).validate_json(path.read_bytes())
    if register.schema_version != 1:
        raise ValueError("Unsupported curation register version")
    ids = [case.id for case in register.cases]
    known_ids = set(ids)
    if len(ids) != len(known_ids):
        raise ValueError("Duplicate curation case ID")
    document_ids = [document.id for document in register.documents]
    if len(document_ids) != len(set(document_ids)):
        raise ValueError("Duplicate evidence document ID")
    for document in register.documents:
        if Path(document.filename).name != document.filename or document.filename in (
            ".",
            "..",
        ):
            raise ValueError("Evidence document names cannot contain a path")
    package_ids = set()
    packaged_cases = set()
    for package in register.packages:
        if package.id in package_ids or package.id == "unassigned-cases":
            raise ValueError("Duplicate or reserved review package ID")
        package_ids.add(package.id)
        members = set(package.case_ids)
        if (
            not members
            or len(members) != len(package.case_ids)
            or not members <= known_ids
        ):
            raise ValueError(f"{package.id}: invalid package membership")
        if packaged_cases & members:
            raise ValueError("A case can have only one primary review package")
        packaged_cases.update(members)
        if not package.grouping_rule.strip() or not package.decision.strip():
            raise ValueError("A package needs a grouping rationale and review question")
    for case in register.cases:
        if not set(case.related_cases) <= known_ids:
            raise ValueError(f"{case.id}: related case is absent")
        if not case.evidence:
            raise ValueError(f"{case.id}: a finding must carry evidence")
        if case.stage == Stage.REVIEW and not case.proposals:
            raise ValueError(f"{case.id}: proposal stage requires a proposal")
        if (
            case.stage == Stage.IMPLEMENTED
            and not case.modules
            and not case.implementations
        ):
            raise ValueError(f"{case.id}: implemented stage requires a module")
        if any(
            not re.fullmatch(r"brightway_flows(?:\.[a-z_]+)+", name)
            for name in case.modules + case.proposed_modules
        ):
            raise ValueError(f"{case.id}: invalid module reference")
        for name in case.test_paths + case.expectation_paths:
            if name.startswith("/") or ".." in Path(name).parts:
                raise ValueError("Source references must remain inside the repository")
        if case.adoption and case.adoption.revision != case.revision:
            raise ValueError(f"{case.id}: release adoption names another revision")
    return register


def review_packages(register: Register) -> tuple[ReviewPackage, ...]:
    """Unassigned cases remain a visible inbox when new evidence arrives."""
    packages = list(register.packages)
    assigned = {identifier for package in packages for identifier in package.case_ids}
    missing = [case.id for case in register.cases if case.id not in assigned]
    if missing:
        packages.append(
            ReviewPackage(
                "unassigned-cases",
                "Cases awaiting grouping",
                "Intake",
                "These cases have not been assigned to a review package.",
                "All records without a primary package; this is an intake queue, not a shared scientific decision.",
                "Separate these records into packages with a common rule, source generation and review question.",
                missing,
            )
        )
    return tuple(packages)


def package_revision(register: Register, package: ReviewPackage) -> str:
    """Triage follows exact membership and evidence, not a mutable package name."""
    members = set(package.case_ids)
    cases = []
    documents = set()
    for case in sorted(register.cases, key=lambda c: c.id):
        if case.id not in members:
            continue
        record = asdict(case)
        record.pop("updated_at")  # Reindexing unchanged evidence is not a new finding.
        cases.append(record)
        for link in (*case.evidence, *case.implementations):
            path = urlsplit(link.url).path
            if path.startswith("/curation/evidence/"):
                documents.add(path.rsplit("/", 1)[-1])
    payload = dict(
        package=asdict(package),
        cases=cases,
        documents=sorted(
            (d.id, d.sha256) for d in register.documents if d.id in documents
        ),
    )
    payload["package"]["case_ids"] = sorted(package.case_ids)
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()


@dataclass(frozen=True)
class SourceFile:
    path: str
    sha256: str
    content: str
    truncated: bool


def source_file(root: Path, relative: str) -> SourceFile | None:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        return None
    raw = path.read_bytes()
    return SourceFile(
        relative,
        hashlib.sha256(raw).hexdigest(),
        raw[:18000].decode("utf-8", errors="replace"),
        len(raw) > 18000,
    )


def filter_cases(
    cases: list[Case],
    *,
    query: str = "",
    stage: str = "",
    quality: str = "",
    source: str = "",
    author: str = "",
    collection: str = "",
    view: str = "all",
    sort: str = "updated",
    direction: str = "desc",
) -> list[Case]:
    selected = []
    for case in cases:
        haystack = " ".join(
            [
                case.id,
                case.title,
                case.summary,
                case.reference_id,
                case.collection,
                case.original_record,
                *case.sources,
                *case.tags,
                *case.modules,
                *case.proposed_modules,
                *case.contributors,
            ]
        ).casefold()
        if query and query.casefold() not in haystack:
            continue
        if stage and case.stage != stage:
            continue
        if quality and case.quality != quality:
            continue
        if source and source not in case.sources:
            continue
        if author and author not in (case.contributors or ("Not recorded",)):
            continue
        if collection and case.collection != collection:
            continue
        if view == "proposals" and not case.proposals:
            continue
        if view == "individual" and case.origin == Origin.FINDING_CLASS:
            continue
        if view == "classes" and case.origin != Origin.FINDING_CLASS:
            continue
        selected.append(case)
    key = {
        "updated": lambda c: c.updated_at.timestamp(),
        "title": lambda c: c.title.casefold(),
        "stage": lambda c: list(Stage).index(c.stage),
        "author": lambda c: (", ".join(c.contributors) or "~").casefold(),
        "source": lambda c: ", ".join(c.sources).casefold(),
        "quality": lambda c: c.quality,
    }.get(sort, lambda c: c.updated_at.timestamp())
    return sorted(selected, key=lambda c: (key(c), c.id), reverse=direction != "asc")
