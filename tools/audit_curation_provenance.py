"""Audit source capture for every case without executing scientific corrections.

Example: uv run python tools/audit_curation_provenance.py --register PATH \
    --repository https://gitlab.com/eos-lci/lci-workbench=CHECKOUT
Only the sibling provenance-audit.json is written. Source content is data;
Python tables are interpreted with a bounded literal evaluator, never imported.
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import io
import json
import re
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from pydantic import TypeAdapter

from brightway_flows.webapps.app import curation, documentation
from brightway_flows.webapps.app import curation_mapping_provenance as mapping
from brightway_flows.webapps.app.curation_provenance import (
    ApplicationCheckReceipt,
    CaseAudit,
    ClaimReviewReceipt,
    ClaimState,
    CheckState as State,
    DocumentCheck,
    EvidenceGap,
    EvidenceRecoveryReceipt,
    EvidenceSupplementReceipt,
    GapKind,
    ProvenanceAudit,
    SourceFact,
    TraceCheck,
    case_identity_digest,
    summary_digest,
)

ROOT = Path(__file__).resolve().parents[1]


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def pointer(value, path):
    if not path.startswith("/"):
        raise ValueError("Expected a JSON pointer")
    for key in path[1:].split("/"):
        key = key.replace("~1", "/").replace("~0", "~")
        if isinstance(value, list):
            if not re.fullmatch(r"0|[1-9][0-9]*", key):
                raise ValueError("Invalid array index")
            value = value[int(key)]
        else:
            value = value[key]
    return value


def literals(raw):
    """Read only literals and references to earlier literal assignments."""
    env, result = {}, {}

    def read(node):
        if isinstance(node, ast.Name):
            return env[node.id]
        if isinstance(node, ast.Dict):
            return {read(k): read(v) for k, v in zip(node.keys, node.values)}
        if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            return [read(n) for n in node.elts]
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"frozenset", "set", "tuple"}
            and len(node.args) == 1
            and not node.keywords
        ):
            return read(node.args[0])
        return ast.literal_eval(node)

    for node in ast.parse(raw).body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        try:
            value = read(node.value)
        except ValueError, TypeError, KeyError:
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if isinstance(target, ast.Name):
                env[target.id] = value
                result[target.id] = (value, node)
    return result


class SourceAudit:
    def __init__(self, path, register, repositories):
        self.path = path
        self.register = register
        self.repositories = repositories
        self.docs = {d.id: d for d in register.documents}
        self.raw = {}
        self.json = {}
        self.tables = {}
        self.lines = {}
        self.checks = {}
        self.commits = {}
        self.claims = {}
        self.claim_documents = {}
        self.claim_times = {}
        self.recoveries = {}
        self.applications = {}
        self.supplements = {}
        self.mapping_manifest = None
        self.mapping_path = mapping.manifest_path(path, register)
        if self.mapping_path:
            if mapping.sha(self.mapping_path.read_bytes()) != self.docs["source-mapping-provenance"].sha256:
                raise ValueError("Mapping provenance manifest differs from its registered pin")
            self.mapping_manifest = mapping.verify_manifest(self.mapping_path, ROOT)
            mapping.verify_content(self.mapping_manifest, self.mapping_path.parent)
            known_cases = {c.id: c for c in register.cases}
            for identifier, digest in self.mapping_manifest.case_sha256.items():
                if identifier not in known_cases or case_identity_digest(known_cases[identifier]) != digest:
                    raise ValueError("Mapping provenance refers to a changed case")
        for doc in register.documents:
            source = (path.parent / "sources" / doc.filename).resolve()
            if not source.is_relative_to((path.parent / "sources").resolve()):
                raise ValueError("Source escapes evidence directory")
            raw = source.read_bytes()
            self.raw[doc.id] = raw
            self.lines[doc.id] = raw.decode().splitlines()
            integrity = State.MATCHED if sha(raw) == doc.sha256 else State.MISMATCH
            origin_state, detail = self.origin(doc, raw)
            self.checks[doc.id] = DocumentCheck(
                doc.id, sha(raw), integrity, origin_state, detail
            )
        self.csv_rows = (
            list(
                csv.DictReader(
                    io.StringIO(self.raw["fedefl-input"].decode("utf-8-sig"))
                )
            )
            if "fedefl-input" in self.raw
            else []
        )
        for identifier in ("policy-claim-review", "remaining-claim-review"):
            if identifier not in self.docs:
                continue
            receipt = TypeAdapter(ClaimReviewReceipt).validate_json(
                self.raw[identifier]
            )
            if receipt.schema_version != 1 or receipt.scientific_signoff:
                raise ValueError("Claim comparisons cannot record scientific approval")
            for source_id, digest in receipt.source_sha256.items():
                if (
                    source_id not in self.checks
                    or self.checks[source_id].sha256 != digest
                ):
                    raise ValueError(
                        f"{identifier}: claim comparison source changed: {source_id}"
                    )
            known = {c.id: c for c in register.cases}
            for claim in receipt.claims:
                if claim.id in self.claims or claim.id not in known:
                    raise ValueError("Duplicate or absent claim case")
                if claim.claim != known[
                    claim.id
                ].summary or claim.summary_sha256 != summary_digest(known[claim.id]):
                    raise ValueError(
                        f"{claim.id}: source comparison names another description"
                    )
                if not claim.sources:
                    raise ValueError("Source comparison must cite evidence")
                for url in claim.sources:
                    trace = self.anchor("Claim comparison citation", url)
                    if trace.state == State.MISMATCH:
                        raise ValueError(
                            f"{claim.id}: claim comparison locator does not resolve"
                        )
                    if (
                        trace.document_id
                        and trace.document_id not in receipt.source_sha256
                    ):
                        raise ValueError("Claim citation source hash is not pinned")
                self.claims[claim.id] = claim
                self.claim_documents[claim.id] = identifier
                self.claim_times[claim.id] = receipt.recorded_at

        if "original-evidence-recovery" in self.docs:
            receipt = TypeAdapter(EvidenceRecoveryReceipt).validate_json(
                self.raw["original-evidence-recovery"]
            )
            if receipt.schema_version != 1 or receipt.scientific_signoff:
                raise ValueError("Evidence recovery cannot record scientific approval")
            for source_id, digest in receipt.source_sha256.items():
                if (
                    source_id not in self.checks
                    or self.checks[source_id].sha256 != digest
                ):
                    raise ValueError(f"Recovery source changed: {source_id}")
            known = {c.id: c for c in register.cases}
            resolvable = {
                "lookup-quantity": {"receipt-receiving"},
                "wb-bafu-observation-bridge": {"comparison-body-unreceived"},
            }
            for event in receipt.entries:
                claim = event.review
                if claim.id in self.recoveries or claim.id not in self.claims:
                    raise ValueError("Recovery must name one previously compared case")
                if (
                    event.previous_document != self.claim_documents[claim.id]
                    or event.previous_document not in receipt.source_sha256
                ):
                    raise ValueError(
                        "Recovery must preserve and pin its prior comparison"
                    )
                if claim.claim != known[
                    claim.id
                ].summary or claim.summary_sha256 != summary_digest(known[claim.id]):
                    raise ValueError("Recovery names another original description")
                if not event.recovered or not claim.sources:
                    raise ValueError("Recovery must identify recovered evidence")
                if (
                    not self.claim_times[claim.id]
                    <= event.recorded_at
                    <= receipt.recorded_at
                ):
                    raise ValueError(
                        "Recovery chronology does not follow its prior comparison"
                    )
                if not set(event.resolved_gaps) <= resolvable.get(claim.id, set()):
                    raise ValueError(
                        "Recovery cannot clear scientific or unrelated gaps"
                    )
                for url in (
                    claim.sources
                    + [f.evidence_url for f in event.facts]
                    + [url for gap in event.remaining_gaps for url in gap.evidence_urls]
                ):
                    trace = self.anchor("Recovered original evidence", url)
                    if trace.state == State.MISMATCH or not trace.document_id:
                        raise ValueError(
                            "Recovery citation must resolve to preserved evidence"
                        )
                    if trace.document_id not in receipt.source_sha256:
                        raise ValueError("Recovery citation hash is not pinned")
                self.recoveries[claim.id] = event

        if "quantity-application-checks" in self.docs:
            receipt = TypeAdapter(ApplicationCheckReceipt).validate_json(
                self.raw["quantity-application-checks"]
            )
            if receipt.schema_version != 1 or receipt.scientific_signoff:
                raise ValueError("Application checks cannot record scientific approval")
            for source_id, digest in receipt.source_sha256.items():
                if (
                    source_id not in self.checks
                    or self.checks[source_id].sha256 != digest
                ):
                    raise ValueError(f"Application evidence changed: {source_id}")
            known = {c.id: c for c in register.cases}
            seen = set()
            for check in receipt.checks:
                if (
                    check.id in seen
                    or not check.case_ids
                    or len(set(check.case_ids)) != len(check.case_ids)
                ):
                    raise ValueError(
                        "Application check membership must be nonempty and unique"
                    )
                seen.add(check.id)
                if not set(check.case_ids) <= known.keys():
                    raise ValueError("Application check names an absent case")
                if any(
                    receipt.case_sha256.get(id) != case_identity_digest(known[id])
                    for id in check.case_ids
                ):
                    raise ValueError("Application check case identity changed")
                if check.validation.recorded_at > receipt.recorded_at:
                    raise ValueError("Application check is newer than its receipt")
                if not all(
                    (check.expected, check.observed, check.remaining, check.sources)
                ):
                    raise ValueError(
                        "Application checks must state evidence and limits"
                    )
                for url in check.sources + [check.validation.evidence_url]:
                    trace = self.anchor("Quantity application evidence", url)
                    if trace.state == State.MISMATCH or not trace.document_id:
                        raise ValueError(
                            "Application checks require preserved evidence"
                        )
                    if trace.document_id not in receipt.source_sha256:
                        raise ValueError("Application evidence hash is not pinned")
                for case_id in check.case_ids:
                    self.applications.setdefault(case_id, []).append(check)
            if set(receipt.case_sha256) != {
                id for check in receipt.checks for id in check.case_ids
            }:
                raise ValueError("Application case pins do not match its membership")

        if "historical-ipcc-evidence-supplement" in self.docs:
            receipt = TypeAdapter(EvidenceSupplementReceipt).validate_json(
                self.raw["historical-ipcc-evidence-supplement"]
            )
            if receipt.schema_version != 1 or receipt.scientific_signoff:
                raise ValueError("Evidence supplements cannot record scientific approval")
            for source_id, digest in receipt.source_sha256.items():
                if source_id not in self.checks or self.checks[source_id].sha256 != digest:
                    raise ValueError(f"Supplement source changed: {source_id}")
            known = {c.id: c for c in register.cases}
            for entry in receipt.entries:
                if entry.id in self.supplements or entry.id not in known:
                    raise ValueError("Supplement must name one existing case")
                if receipt.case_sha256.get(entry.id) != case_identity_digest(known[entry.id]):
                    raise ValueError("Supplement case identity changed")
                if not entry.facts or not entry.sources:
                    raise ValueError("Supplement must retain facts and preserved sources")
                for url in (entry.sources + [f.evidence_url for f in entry.facts]
                            + [url for gap in entry.gaps for url in gap.evidence_urls]):
                    trace = self.anchor("Supplementary source evidence", url)
                    if trace.state == State.MISMATCH or not trace.document_id:
                        raise ValueError("Supplement citation must resolve to preserved evidence")
                    if trace.document_id not in receipt.source_sha256:
                        raise ValueError("Supplement citation hash is not pinned")
                for fact in entry.facts:
                    parsed = urlsplit(fact.evidence_url)
                    identifier = parsed.path.rsplit("/", 1)[-1]
                    coordinates = parse_qs(parsed.query).get("pointer", [])
                    if len(coordinates) != 1:
                        raise ValueError("Supplement facts require one exact JSON pointer")
                    selected = pointer(self.decoded(identifier), coordinates[0])
                    if not isinstance(selected, str) or selected != fact.value:
                        raise ValueError("Supplement fact differs from its preserved value")
                self.supplements[entry.id] = entry
            if set(receipt.case_sha256) != set(self.supplements):
                raise ValueError("Supplement case pins do not match its membership")

    def git(self, repo, *args):
        return subprocess.check_output(
            ["git", "-C", str(repo), *args], stderr=subprocess.DEVNULL
        )

    def origin(self, doc, raw):
        for origin, repo in self.repositories.items():
            if not doc.origin_url or not doc.origin_url.startswith(
                origin.rstrip("/") + "/"
            ):
                continue
            suffix = doc.origin_url[len(origin.rstrip("/")) :]
            match = re.fullmatch(r"/(?:-/)?blob/([0-9a-f]{40})/(.+)", suffix)
            if match:
                revision, path = match.groups()
                try:
                    original = self.git(repo, "show", f"{revision}:{path}")
                except subprocess.CalledProcessError:
                    return (
                        State.INCOMPLETE,
                        "Pinned Git object could not be read in the supplied checkout.",
                    )
                if raw == original:
                    return (
                        State.MATCHED,
                        f"Bytes equal Git blob {revision}:{path}. This establishes code/report origin, not scientific truth.",
                    )
                return (
                    State.MISMATCH,
                    f"Bytes differ from declared Git blob {revision}:{path}.",
                )
            match = re.fullmatch(r"/(?:-/)?commit/([0-9a-f]{40})", suffix)
            if match:
                revision = match[1]
                # These receipts declare their exact path scope in the migration.
                if doc.id.startswith("integration-"):
                    original = self.git(
                        repo,
                        "show",
                        "--format=",
                        revision,
                        "--",
                        "src/lci_workbench/biosphere",
                        "scripts/*consensus*",
                    )
                    return (
                        (
                            State.MATCHED,
                            "Exact recorded biosphere/scripts diff matches its Git commit.",
                        )
                        if raw == original
                        else (
                            State.MISMATCH,
                            "Recorded diff does not match its declared Git commit and path scope.",
                        )
                    )
        return (
            State.NOT_ASSESSED,
            "Snapshot hash checked locally; origin has not been independently matched by this audit.",
        )

    def decoded(self, identifier):
        if identifier not in self.json:
            self.json[identifier] = json.loads(self.raw[identifier])
        return self.json[identifier]

    def anchor(self, label, url):
        parsed = urlsplit(url)
        if not parsed.netloc and parsed.path.startswith("/curation/evidence/"):
            identifier = parsed.path.rsplit("/", 1)[-1]
            if identifier not in self.docs:
                return TraceCheck(
                    label, url, State.MISMATCH, "Document is not registered."
                )
            check = self.checks[identifier]
            if check.state == State.MISMATCH or check.origin_state == State.MISMATCH:
                return TraceCheck(
                    label,
                    url,
                    State.MISMATCH,
                    "Source bytes differ from their recorded hash or Git origin.",
                    identifier,
                )
            query = parse_qs(parsed.query)
            try:
                if "pointer" in query:
                    pointer(self.decoded(identifier), query["pointer"][0])
                if "line" in query or "end" in query:
                    lines = self.lines[identifier]
                    start = int(query.get("line", ["1"])[0])
                    end = int(query.get("end", [str(start)])[0])
                    if not 1 <= start <= end <= len(lines):
                        raise ValueError("Range outside file")
            except ValueError, KeyError, IndexError, TypeError:
                return TraceCheck(
                    label,
                    url,
                    State.MISMATCH,
                    "Source locator does not resolve.",
                    identifier,
                )
            detail = "Preserved hash and source locator checked. "
            detail += check.detail
            return TraceCheck(label, url, State.MATCHED, detail, identifier)
        if not parsed.netloc and parsed.path.startswith("/docs/"):
            resolved = documentation.resolve(
                ROOT / "docs", parsed.path.removeprefix("/docs/")
            )
            if resolved:
                return TraceCheck(
                    label,
                    url,
                    State.MATCHED,
                    "Local documentation resolves. Citation supports reading the article; its claims were not re-evaluated here.",
                )
            return TraceCheck(
                label, url, State.MISMATCH, "Documentation reference does not resolve."
            )
        return TraceCheck(
            label,
            url,
            State.NOT_ASSESSED,
            "External reference retained. Link presence does not verify the claim, current status or authorship.",
        )

    def source_value(self, evidence):
        parsed = urlsplit(evidence.url)
        identifier = parsed.path.rsplit("/", 1)[-1]
        query = parse_qs(parsed.query)
        if identifier not in self.raw:
            return None
        if "pointer" in query:
            return pointer(self.decoded(identifier), query["pointer"][0])
        return None

    def commit_facts(self, case):
        facts, seen = [], set()
        for impl in case.implementations:
            if not impl.author:
                continue
            revision = re.search(r"commit ([0-9a-f]{40})", impl.note)
            revision = revision[1] if revision else impl.revision
            identifier = urlsplit(impl.url).path.rsplit("/", 1)[-1]
            doc = self.docs.get(identifier)
            if not doc or not doc.origin_url:
                continue
            for origin, repo in self.repositories.items():
                if not doc.origin_url.startswith(origin.rstrip("/") + "/"):
                    continue
                key = (str(repo), revision)
                if key in seen:
                    continue
                seen.add(key)
                if key not in self.commits:
                    try:
                        self.commits[key] = self.git(
                            repo, "show", "-s", "--format=%an%n%aI%n%B", revision
                        ).decode()
                    except subprocess.CalledProcessError:
                        self.commits[key] = ""
                message = self.commits[key]
                if not message:
                    continue
                parts = message.splitlines()
                url = (
                    origin.rstrip("/") + "/-/commit/" + revision
                    if "gitlab" in origin
                    else origin.rstrip("/") + "/commit/" + revision
                )
                facts.append(
                    SourceFact(
                        "Git author of cited change",
                        parts[0] + " · " + parts[1] + " · " + revision,
                        url,
                    )
                )
                for name in re.findall(
                    r"^Co-authored-by:\s*(.+)$", message, re.I | re.M
                ):
                    # Retain the literal named credit, without asserting it wrote a particular line.
                    facts.append(SourceFact("Git co-author trailer", name, url))
        return facts

    def case(self, case):
        traces = [
            self.anchor(e.label, e.url) for e in (*case.evidence, *case.implementations)
        ]
        facts, gaps = [], []
        first = case.evidence[0].url
        original = json.loads(case.original_record) if case.original_record else None
        kind = case.collection
        capture = State.NOT_ASSESSED
        detail = "References are preserved; semantic agreement of the description with its source has not been established automatically."
        derivation = "Imported description. Interpretive text must be checked against the cited original evidence."

        def fact(label, value, url=first):
            if value is not None and value != "" and value != []:
                facts.append(
                    SourceFact(
                        label, value if isinstance(value, str) else encoded(value), url
                    )
                )

        def gap(code, group, title, explanation, action, urls=None):
            gaps.append(
                EvidenceGap(code, group, title, explanation, action, urls or [first])
            )

        def equal(condition, description):
            nonlocal capture, detail
            capture = State.MATCHED if condition else State.MISMATCH
            detail = (
                description if condition else "Source comparison failed: " + description
            )

        if case.origin == curation.Origin.FINDING_CLASS:
            kind = "Documentation index"
            capture = State.NOT_APPLICABLE
            detail = "This record indexes a finding class; it is not an individual proposed fix."
            derivation = "Explicit link to the original findings article."
        elif case.collection == "Upstream issue reports":
            selected = self.source_value(case.evidence[0])
            if not isinstance(selected, dict):
                raise ValueError("Upstream reports require a preserved JSON issue record")
            reporter = selected["user"]["login"]
            reported_at = datetime.fromisoformat(selected["created_at"])
            if reported_at.tzinfo is None:
                raise ValueError("Upstream issue dates must carry a timezone")
            equal(
                encoded(original) == encoded(selected)
                and case.reported_by == reporter
                and case.reported_at == reported_at,
                "Original issue payload and reported attribution equal the pinned source. This is report custody, not verification of its claim or a discovery date.",
            )
            kind = "Upstream issue report"
            derivation = "Exact captured upstream issue. Code reproduction, full-build qualification and consumer adoption are separate evidence."
            fact("Upstream issue number", selected["number"])
            fact("Recorded issue reporter", reporter)
            fact("Issue filed at", selected["created_at"])
            gap(
                "upstream-build-unreceived", GapKind.REPRODUCTION,
                "Full-build and native applicability remain unreceived",
                "The source report and scoped API tests do not establish a same-input full-build comparison, native quantity application or consumer adoption.",
                "Receive the exact candidate build and assessment, then qualify affected native consumers before acceptance.",
            )
        elif case.collection == "Source provenance findings":
            selected = self.source_value(case.evidence[0])
            equal(original == selected, "Finding record equals its pinned source-check exhibit.")
            kind = "Source identifier integrity"
            derivation = "Complete original-row reproduction; missing source identities remain quarantined. No replacement flow identifiers are inferred."
            fact("Original rows with missing source identifiers", original["count"])
            gap("source-identifiers-unresolved", GapKind.TRACE,
                "Original flow identifiers are missing",
                "Distinct evidence records preserve every row; they cannot replace the missing source flow identities.",
                "Recover original source coordinates and identifiers from the source owner before proposing mappings.")
        elif case.collection == "Placeholder classification metadata":
            trace = self.anchor("Original classification metadata", first)
            if not trace.document_id:
                raise ValueError("Placeholder metadata requires a captured original")
            source = mapping.loads_original(self.raw[trace.document_id])
            metadata = source["metadata"]
            if not isinstance(metadata, dict):
                raise ValueError("Malformed original placeholder metadata")
            selected = self.source_value(case.evidence[0])
            equal(original == selected == metadata,
                  "Metadata record equals its pinned original classification.")
            kind = "Original classification metadata"
            derivation = "Original metadata and a literal name/category census; descriptions are not recovered flow identities."
            rows = source["mappings"]
            if not isinstance(rows, list) or any(
                not isinstance(row, dict)
                or not isinstance(row.get("placeholder_name"), str)
                or not isinstance(row.get("placeholder_categories"), list)
                or any(not isinstance(v, str) for v in row["placeholder_categories"])
                for row in rows
            ):
                raise ValueError("Malformed original placeholder classification")
            keys = {(row["placeholder_name"], tuple(row["placeholder_categories"])) for row in rows}
            rows_url = f"/curation/evidence/{trace.document_id}?pointer=%2Fmappings"
            fact("Retained mapping records", len(rows), rows_url)
            fact("Distinct literal name/category descriptions", len(keys), rows_url)
            fact("Original reported source population", metadata.get("total_placeholders"))
            fact("Original reported unmatched count", metadata.get("unmatched_v2"))
            total, unmatched = metadata.get("total_placeholders"), metadata.get("unmatched_v2")
            if (type(total) is not int or type(unmatched) is not int
                    or total < 0 or unmatched < 0 or total - len(keys) != unmatched):
                gap("placeholder-count-metadata", GapKind.CONTRADICTION,
                    "Original population metadata is inconsistent",
                    f"The original total is {total!r} and unmatched count is {unmatched!r}; the artifact retains {len(rows)} records and {len(keys)} literal descriptions. No source-flow total or identity is supplied from these counts.",
                    "Reconcile the original input populations and executed producer before issuing a corrected metadata generation.")
            gap("placeholder-input-generation", GapKind.REPRODUCTION,
                "Classification input generation is unreceived",
                "A recorded timestamp, source-code origin or matching later description cannot identify the original input/export generation. Name/category matches are not identity approval.",
                "Receive the exact workbook, native export and execution lineage; preserve missing IDs and competing generations until qualified.")
        elif case.collection == "Consumer method metadata":
            selected = self.source_value(case.evidence[0])
            equal(original == selected,
                  "Method record equals its pinned published artifact; current registration is not inferred.")
            kind = "Published method metadata"
            derivation = "Original method metadata and retained factor entries; no method value, unit or source ancestry is supplied by inference."
            metadata = original["metadata"]
            rows = original["cfs"]
            keys = []
            for row in rows:
                if (not isinstance(row, list) or len(row) != 2
                        or not isinstance(row[0], list) or len(row[0]) != 2
                        or any(not isinstance(v, str) or not v for v in row[0])):
                    raise ValueError("Malformed original method factor reference")
                keys.append(tuple(row[0]))
            fact("Retained factor entries", len(rows))
            fact("Distinct native factor keys", len(set(keys)))
            fact("Native factor namespaces", dict(Counter(k[0] for k in keys)))
            if len(keys) != len(set(keys)):
                gap("method-native-key-repeated", GapKind.CONTRADICTION,
                    "Original factor entries repeat a native key",
                    "Every original entry is retained. This audit does not deduplicate, add or select among their values.",
                    "Recover the producer's aggregation rule and assess repeated keys before a scalar method projection.")
            fact("Original impact unit", metadata.get("unit"))
            fact("Original source description", metadata.get("description"))
            if "num_cfs" in metadata:
                reported = metadata["num_cfs"]
                fact("Metadata factor count", reported)
                if type(reported) is not int or reported != len(rows):
                    gap("method-count-metadata", GapKind.CONTRADICTION,
                        "Metadata factor count differs from the retained payload",
                        f"The original num_cfs is {reported!r}; the retained artifact has {len(rows)} entries and {len(set(keys))} distinct native keys. This does not establish a numerical-impact defect or today's registered population.",
                        "Recover the method writer/copy receipt and explain the metadata census before issuing a corrected metadata generation.")
            if not isinstance(metadata.get("unit"), str) or not metadata["unit"].strip():
                gap("method-unit-unrecorded", GapKind.TRACE,
                    "Impact unit is not recorded in this method generation",
                    "An older generation or a familiar method name cannot fill a missing impact-unit declaration. Equal factor maps do not establish execution ancestry or quantity interpretation.",
                    "Recover the exact source-method unit and its generation-bound derivation; retain this omission until then.")
            gap("method-execution-ancestry", GapKind.REPRODUCTION,
                "Original method execution ancestry is unreceived",
                "Descriptions such as copied from Agribalyse-3.2 and a recorded rebuild date are source assertions. Source-code availability and matching archive bytes do not identify the executed provider route.",
                "Receive the exact source method, native keys, provider/implementation pins and copy/remap or rebuild receipt through the existing consumer owner.")
        elif case.collection == "External synonym assertions":
            kind = "Provider mapping assertion"
            row_number = original["csv_row"]
            row = self.csv_rows[row_number - 2]
            selected = self.source_value(case.evidence[0])
            equal(
                row == original["original"]
                and original == selected
                and original["source_sha256"] == self.checks["fedefl-input"].sha256,
                "Selected assertion equals the preserved CSV row and selected-record projection, including its source digest.",
            )
            url = f"/curation/evidence/fedefl-input?line={row_number}&end={row_number}"
            traces.insert(0, self.anchor("Original provider CSV row", url))
            derivation = "Legacy selection: MatchCondition “=”, ConversionFactor “1.0”, different lowercased names, and first unseen source name. UUIDs, units and compartments are not used by that predicate."
            for key, label in [
                ("SourceListName", "Provider source list"),
                ("SourceFlowName", "Source name"),
                ("SourceFlowUUID", "Source flow ID"),
                ("SourceFlowContext", "Source context"),
                ("SourceUnit", "Source unit"),
                ("TargetFlowName", "Target name"),
                ("TargetFlowUUID", "Target flow ID"),
                ("TargetFlowContext", "Target context"),
                ("TargetUnit", "Target unit"),
                ("MatchCondition", "Provider match condition"),
                ("ConversionFactor", "Provider conversion factor"),
                ("Mapper", "Provider mapper"),
                ("Verifier", "Provider verifier (not Curation sign-off)"),
                ("LastUpdated", "Provider date (verbatim)"),
            ]:
                fact(label, row[key], url)
            fact(
                "Rows in the preserved provider CSV",
                len(self.csv_rows),
                "/curation/evidence/fedefl-input",
            )
            fact(
                "Selected legacy assertions in this snapshot",
                len(self.decoded("fedefl-selections")),
                "/curation/evidence/fedefl-selections",
            )
            if "fedefl-provider-check" in self.docs:
                provider = self.decoded("fedefl-provider-check")
                if (
                    provider["upstream_sha256"]
                    == provider["local_sha256"]
                    == self.checks["fedefl-input"].sha256
                ):
                    fact(
                        "Recovered provider origin",
                        f"Pinned provider revision {provider['revision']}; exact byte comparison recorded on 13 October 2026.",
                        "/curation/evidence/fedefl-provider-check",
                    )
            gap(
                "mapping-scope",
                GapKind.SCOPE,
                "Name-only projection loses mapping scope",
                "The CSV is a relationship between specific source/target flows. Selecting two names does not establish a universal chemical synonym or a match in another compartment.",
                "Review the exact IDs, units, substance/class type and contexts before proposing any broader synonym.",
                [url],
            )
            if row["SourceUnit"] != row["TargetUnit"]:
                gap(
                    "unit-mismatch",
                    GapKind.CONTRADICTION,
                    "Selected mapping has different units",
                    f"SourceUnit={row['SourceUnit']!r}; TargetUnit={row['TargetUnit']!r}; ConversionFactor={row['ConversionFactor']!r}. The legacy selection still admits this row.",
                    "Keep this assertion out of a generic synonym/conversion proposal until its dimensional meaning is resolved with the provider.",
                    [url],
                )
            if not row["Verifier"].strip():
                gap(
                    "provider-verifier-missing",
                    GapKind.ATTRIBUTION,
                    "Provider verifier is blank",
                    "The original mapping names a mapper but no verifier.",
                    "Request or find the provider review record. Do not infer verification from a mapper name.",
                    [url],
                )
            gap(
                "runtime-input-unpinned",
                GapKind.REPRODUCTION,
                "Historical runtime input is not established",
                "This CSV is a later local snapshot. Reproducing the selection does not prove these bytes were used by the old build.",
                "Recover the historical input manifest, or run a new explicitly pinned comparison with these bytes.",
                [url],
            )
        elif case.collection in {"Legacy normalization rules", "Factor producer rules"}:
            kind = "Literal code rule"
            identifier = urlsplit(case.evidence[0].url).path.rsplit("/", 1)[-1]
            if identifier not in self.tables:
                self.tables[identifier] = literals(self.raw[identifier])
            value, node = self.tables[identifier][original["table"]]
            key = original["key"]
            actual = value[key] if isinstance(value, (dict, list)) else value
            literal_line = node.lineno
            if isinstance(node.value, ast.Dict):
                keys = list(value)
                literal_line = node.value.keys[keys.index(key)].lineno
            elif isinstance(node.value, (ast.List, ast.Tuple, ast.Set)):
                literal_line = node.value.elts[key].lineno
            equal(
                encoded(actual) == encoded(original["value"])
                and literal_line == original["line"],
                "Recorded key and value equal the pinned Python literal; source code was parsed, not executed.",
            )
            derivation = "One literal table entry extracted from the pinned source, retaining the original comments and code attribution."
            url = f"/curation/evidence/{identifier}?line={original['line']}&end={original['line']}"
            fact("Rule table", original["table"], url)
            fact("Input / selector", key, url)
            fact("Recorded output / parameter", original["value"], url)
            fact("Source revision", original["revision"], url)
            fact(
                "Entries in this source table",
                len(value) if isinstance(value, (dict, list)) else 1,
                url,
            )
            gap(
                "rule-applicability",
                GapKind.SCOPE,
                "Rule applicability is not independently established",
                "The literal proves what the code declares. Its intended quantity, compartment, geographic and method scope may be narrower than its name suggests.",
                "Document included and excluded cases, with a positive and a counterexample for this rule.",
                [url],
            )
            if identifier == "ef31-producer" and original["table"] in {
                "FOSSIL_NCV_DEFAULTS",
                "NATURAL_GAS_NCV_M3",
                "NATURAL_GAS_NCV_KG",
            }:
                gap(
                    "calibration-evidence",
                    GapKind.BASIS,
                    "Locally calibrated assumption",
                    "The adjacent source comments describe calibration to BAFU implied densities. A benchmark fit does not independently establish a universal heating value or density.",
                    "Recover calibration inputs, fitted quantity basis and residuals; cite the physical basis and define where this default is valid.",
                    ["/curation/evidence/ef31-producer?line=682&end=714"],
                )
            if original["table"] == "CFS_TO_ADD":
                gap(
                    "historical-method-source",
                    GapKind.BASIS,
                    "Historical factor lacks a primary row citation",
                    "The literal table names IPCC 2021 and the historical bafu_fresh project, but does not cite the exact method implementation or source row for this value.",
                    "Identify the precise published implementation and row. Check compartment fallback and method boundaries before carrying this value forward.",
                    [url],
                )
        elif case.collection in {
            "Historical comparisons",
            "Recorded factor amendments",
        }:
            kind = (
                "Historical observation"
                if case.collection == "Historical comparisons"
                else "Recorded factor application"
            )
            actual = self.source_value(case.evidence[0])
            expected = dict(original)
            if case.collection == "Recorded factor amendments":
                expected.pop("category")
                expected.pop("native_code")
            equal(
                actual == expected,
                "Imported record equals the exact historical JSON row; this does not repeat the scientific computation.",
            )
            derivation = "Exact historical output row, selected by its recorded classification/outcome. The output report is not an independent input source."
            for key, label in [
                ("bafu_name", "BAFU name"),
                ("bafu_context", "BAFU context"),
                ("unit", "Recorded unit"),
                ("our_bafu_codes", "BAFU native codes"),
                ("our_ef31", "Historical local target"),
                ("their_ef31", "Historical Consensus target"),
                ("joined_via", "Historical join basis"),
                ("refused", "Recorded refusal"),
                ("class", "Historical classification"),
                ("category", "Method category"),
                ("native_code", "BAFU native code"),
                ("ef31_uuid", "Selected EF 3.1 flow ID"),
                ("old_ef31_uuid", "Previous EF flow ID"),
                ("consensus_rows", "Source contexts"),
                ("location_key", "Location"),
                ("prior", "Previous factor"),
                ("cf", "Recorded factor"),
                ("outcome", "Recorded outcome"),
                ("policy", "Recorded policy"),
                ("redirect_followed", "Recorded redirect"),
            ]:
                if key == "prior" and key in original and original[key] is None:
                    fact(label, "No previous factor recorded")
                else:
                    fact(label, original.get(key))
            identifier = (
                "historical-comparisons"
                if case.collection == "Historical comparisons"
                else "factor-overlay"
            )
            parent = self.decoded(identifier)
            fact(
                "Historical run",
                parent["run_id"],
                f"/curation/evidence/{identifier}?pointer=%2Frun_id",
            )
            if case.collection == "Historical comparisons":
                fact(
                    "Original report rows in this classification",
                    parent["counts_by_class"].get(original["class"]),
                    "/curation/evidence/historical-comparisons?pointer=%2Fcounts_by_class",
                )
                fact(
                    "Original report rows evaluated",
                    parent["evaluated"],
                    "/curation/evidence/historical-comparisons?pointer=%2Fevaluated",
                )
                fact(
                    "Counting basis",
                    parent["counted_object"],
                    "/curation/evidence/historical-comparisons?pointer=%2Fcounted_object",
                )
                if original.get("our_bafu_codes"):
                    fact(
                        "Native BAFU codes in this observation",
                        len(original["our_bafu_codes"]),
                    )
            else:
                fact(
                    "Category outcomes in the original run",
                    parent["counts"].get(original["category"]),
                    "/curation/evidence/factor-overlay?pointer=%2Fcounts",
                )
                if isinstance(original.get("prior"), (float, int)) and isinstance(
                    original.get("cf"), (float, int)
                ):
                    fact(
                        "Recorded absolute factor change",
                        original["cf"] - original["prior"],
                    )
                    if original["prior"] != 0:
                        fact(
                            "Recorded factor ratio (new / previous)",
                            original["cf"] / original["prior"],
                        )
            if "inputs" in parent:
                fact(
                    "Recorded input references",
                    parent["inputs"],
                    "/curation/evidence/historical-comparisons?pointer=%2Finputs",
                )
            gap(
                "historical-inputs",
                GapKind.REPRODUCTION,
                "Historical result needs a reproducible input set",
                "A run ID and an output row do not pin every original source list, method implementation and build dependency.",
                "Recover input hashes and the original command, then compare a baseline and candidate from identical inputs.",
            )
            gap(
                "application-scope",
                GapKind.SCOPE,
                "Identity and quantity acceptance remain separate",
                "The recorded target/value does not itself prove the BAFU identity, substance form, quantity basis, compartment or geographic applicability.",
                "Attach original source observations and justify each identity/quantity/context decision before reapplying this result.",
            )
            if (
                case.collection == "Recorded factor amendments"
                and "jrc-factor-source-check" in self.docs
            ):
                receipt = self.decoded("jrc-factor-source-check")
                if not hasattr(self, "jrc_checks"):
                    self.jrc_checks = {
                        c["case_id"]: (i, c) for i, c in enumerate(receipt["checks"])
                    }
                position, check = self.jrc_checks[case.id]
                url = f"/curation/evidence/jrc-factor-source-check?pointer=%2Fchecks%2F{position}"
                exact = check["original_record_sha256"] == sha(
                    case.original_record.encode()
                )
                procedure_matches = (
                    receipt["script_sha256"]
                    == self.checks["jrc-factor-check-procedure"].sha256
                )
                if not exact or not procedure_matches:
                    gap(
                        "provider-check-stale",
                        GapKind.CONTRADICTION,
                        "Provider comparison receipt is stale",
                        "The recorded case or comparison procedure no longer matches the receipt.",
                        "Repeat the source comparison with the pinned workbook and current captured record.",
                        [url],
                    )
                elif check["exact_value_match"]:
                    row = check["selected_source_row"]
                    fact(
                        "Provider value corroborated",
                        f"Exact match to JRC {receipt['source_workbook']['sheet']}, Excel row {row['excel_row']}: {row['CF EF3.1']}",
                        url,
                    )
                    fact("Provider substance", row["FLOW_name"], url)
                    fact(
                        "Provider method and ID",
                        row["LCIAMethod_name"] + " · " + row["LCIAMethod_uuid EF3.1"],
                        url,
                    )
                    fact(
                        "Provider classes and direction",
                        [
                            row[k]
                            for k in [
                                "FLOW_class0",
                                "FLOW_class1",
                                "FLOW_class2",
                                "LCIAMethod_direction",
                            ]
                        ],
                        url,
                    )
                    fact(
                        "JRC workbook SHA-256",
                        receipt["source_workbook"]["sha256"],
                        "/curation/evidence/jrc-factor-source-check?pointer=%2Fsource_workbook",
                    )
                    gap(
                        "factor-quantity-evidence",
                        GapKind.BASIS,
                        "Provider value matched; quantity remains unverified",
                        check["unit_status"],
                        "Trace the source-flow definition and required substance quantity. Equal numerical values alone do not validate applying this row to the BAFU flow.",
                        [url, first],
                    )
                else:
                    gap(
                        "provider-value-mismatch",
                        GapKind.CONTRADICTION,
                        "Recorded factor differs from provider row",
                        "The pinned provider row comparison did not confirm the recorded value.",
                        "Investigate the selected implementation, original quantity and recorded calculation.",
                        [url],
                    )
        elif case.collection in {
            "Documented factor corrections",
            "Historical factor investigations",
        }:
            kind = "Historical change report"
            evidence = case.evidence[0]
            parsed = urlsplit(evidence.url)
            identifier = parsed.path.rsplit("/", 1)[-1]
            content = self.raw[identifier].decode()
            heading = "## " + original["heading"]
            match = re.search(
                r"^" + re.escape(heading) + r"\s*\n(.*?)(?=^## |\Z)",
                content,
                re.M | re.S,
            )
            equal(
                bool(match) and match[1].strip() == original["text"].strip(),
                "Heading and body equal the pinned change report. Reported measurements remain historical claims.",
            )
            derivation = "A section of the original change/status report, copied without turning its status words into validation receipts."
            fact("Original heading", original["heading"])
            gap(
                "reported-results",
                GapKind.REPRODUCTION,
                "Reported result is not an execution receipt",
                "Narrative terms such as “fixed”, “verified” or “reproducible” in an old report have not been independently reproduced by this audit.",
                "Locate the command, logs, original inputs and revision; reproduce the claimed result and register the receipt.",
            )
        elif case.collection == "Consensus integration changes":
            kind = "Recorded Git change"
            identifier = urlsplit(first).path.rsplit("/", 1)[-1]
            capture = self.checks[identifier].origin_state
            detail = (
                "Implementation diff checked against the exact Git revision and recorded path scope."
                if capture == State.MATCHED
                else "The source diff is preserved, but its Git origin could not be checked."
            )
            derivation = "A real Git commit in the recorded migration revision range. Change authorship does not establish finding discovery or scientific approval."
            for key, label in [
                ("commit", "Git revision"),
                ("author", "Git change author"),
                ("authored_at", "Git authored date"),
                ("body", "Commit message"),
            ]:
                fact(label, original.get(key))
        elif case.collection == "Normalization and cluster mechanisms":
            kind = "Code mechanism"
            parsed = urlsplit(first)
            identifier = parsed.path.rsplit("/", 1)[-1]
            nodes = [
                n
                for n in ast.walk(ast.parse(self.raw[identifier]))
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                and n.name == case.reference_id
            ]
            if nodes:
                query = parse_qs(parsed.query)
                start = int(query.get("line", ["1"])[0])
                end = int(query.get("end", [str(start)])[0])
                equal(
                    any(n.lineno >= start and n.end_lineno <= end for n in nodes),
                    "Named function/class exists inside the cited source range.",
                )
            elif case.reference_id.startswith("Phase "):
                query = parse_qs(parsed.query)
                start = int(query.get("line", ["1"])[0])
                end = int(query.get("end", [str(start)])[0])
                content = "\n".join(self.lines[identifier][start - 1 : end])
                label = case.title.removeprefix("Legacy phase ")
                equal(
                    any(
                        label.casefold() in line.casefold()
                        for line in content.splitlines()
                        if line.lstrip().startswith("#")
                    ),
                    "Named historical phase heading exists inside the cited source range. This confirms source capture only.",
                )
            derivation = "Named source mechanism. Its existence and source range can be checked; its intended scientific behavior still requires examples and review."
        elif case.collection in {"Method policy areas", "Identity evidence mechanisms"}:
            kind = (
                "Method policy"
                if case.collection == "Method policy areas"
                else "Matching heuristic"
            )
            derivation = "Interpretation inherited from the previous review. Linked code can ground the mechanism, but policy rationale must be traced separately."
            if case.id not in self.claims:
                gap(
                    "interpretation-not-verified",
                    GapKind.BASIS,
                    "Inherited interpretation needs corroboration",
                    "The earlier review is a derived explanation. Repeating it in this register is not independent support for the policy.",
                    "Compare the prose with its owning code and an authoritative method/source statement; retain uncertainties and counterexamples.",
                )
        else:
            kind = "Individually recorded case"
            derivation = "Existing individual record, with citations retained. No automatic claim-to-source equivalence is asserted."

        if original and case.collection in {
            "Migration cases",
            "Method policy areas",
            "Identity evidence mechanisms",
        }:
            originals = [
                self.source_value(e)
                for e in case.evidence
                if "pointer=" in e.url
                and urlsplit(e.url).path.startswith("/curation/evidence/")
            ]
            if original in originals:
                equal(
                    True,
                    "The exact inherited record equals its pinned ledger or prior-review entry. Interpretive support is assessed separately below.",
                )
            else:
                equal(
                    False,
                    "The inherited record does not equal the linked ledger or prior-review entry.",
                )

        if (
            case.collection == "Migration cases"
            and case.id == "lookup-quantity"
            and "quantity-reproduction" in self.docs
        ):
            receipt = self.decoded("quantity-reproduction")
            section = receipt["execution_pinned_candidate_reconciliation"]
            url = "/curation/evidence/quantity-reproduction?pointer=%2Fexecution_pinned_candidate_reconciliation"
            for key, label in [
                ("request_count", "Reported exact source requests"),
                ("known_quantity_factors", "Reported known quantity factors"),
                ("unknown_quantity_factors", "Reported unknown quantity factors"),
                ("lookup_code_revision", "Pinned lookup candidate revision"),
                ("database_sha256", "Pinned lookup database digest"),
            ]:
                fact(label, section[key], url)
            fact(
                "Original receipt verification scope",
                section["verification_scope"],
                url,
            )
            gap(
                "receipt-receiving",
                GapKind.REPRODUCTION,
                "Execution summary needs its underlying receipts",
                "The recovered summary matches the original ledger digest. Full request/result files and the command manifest are named by hash but have not been newly received by this audit.",
                "Receive and verify the complete command, input, request and result artifacts; keep older retrospectively attributed replay separate.",
                [url],
            )
        if (
            case.collection == "Migration cases"
            and case.id == "wb-bafu-observation-bridge"
            and "native-comparison-receipt" in self.docs
        ):
            receipt = self.decoded("native-comparison-receipt")
            url = "/curation/evidence/native-comparison-receipt?pointer=%2Fdeclared_coverage"
            for key, label in [
                ("observations", "Declared original observations"),
                ("unlinked_observations", "Declared unlinked observations"),
                ("historical_aliases", "Declared historical aliases"),
                ("native_comparison_rows", "Declared native comparison rows"),
            ]:
                fact(label, receipt["declared_coverage"][key], url)
            fact(
                "Declared overlapping review flags",
                receipt["declared_coverage"]["review_reasons"],
                url,
            )
            fact(
                "Body coverage recounted in the earlier summary receipt",
                str(
                    receipt["independent_receiving"]["actual_body_coverage_recomputed"]
                ),
                "/curation/evidence/native-comparison-receipt?pointer=%2Findependent_receiving",
            )
            gap(
                "comparison-body-unreceived",
                GapKind.REPRODUCTION,
                "Declared comparison coverage is not independently recounted",
                "The original receipt explicitly leaves actual comparison body coverage, exact dropped identities and quantity crosslinks unverified.",
                "Receive the complete export and comparison body, recount coverage and original identity membership, and verify quantity crosslinks.",
                [
                    url,
                    "/curation/evidence/native-comparison-receipt?pointer=%2Findependent_receiving",
                ],
            )
        if (
            case.id == "cf-bafu-mine-gas-volume"
            and "prior-mine-gas-catalog" in self.docs
        ):
            fact(
                "Reported retained Nm3 observations",
                self.decoded("prior-mine-gas-catalog")["independent_check"][
                    "retained_observation_count"
                ],
                "/curation/evidence/prior-mine-gas-catalog?pointer=%2Findependent_check",
            )
        if (
            case.collection == "Identity evidence mechanisms"
            and "mechanism-source-details" in self.docs
        ):
            details = self.decoded("mechanism-source-details")
            if (
                details["source_sha256"]
                != self.checks["prior-normalization-code"].sha256
            ):
                raise ValueError(
                    "Mechanism extraction no longer names the preserved builder"
                )
            entries = [
                (i, e)
                for i, e in enumerate(details["entries"])
                if e["tag"] == case.reference_id.removeprefix("RULE-")
            ]
            fact(
                "Occurrences in the preserved source",
                len(entries),
                "/curation/evidence/mechanism-source-details",
            )
            for i, entry in entries:
                fact(
                    "Recorded mechanism conditions",
                    entry["owner"] + ": " + " AND ".join(entry["conditions"]),
                    f"/curation/evidence/mechanism-source-details?pointer=%2Fentries%2F{i}",
                )

        historical_claim = self.claims.get(case.id)
        recovery = self.recoveries.get(case.id)
        claim = recovery.review if recovery else historical_claim
        if claim:
            if (
                case.collection == "Upstream reference cases"
                and claim.state == ClaimState.SUPPORTED
                and capture == State.NOT_ASSESSED
            ):
                capture = State.MATCHED
                detail = "The documented claim has a scoped source comparison against preserved pinned code or ruling records. This is separate from scientific receiving."
            if claim.state in {
                ClaimState.PARTIAL,
                ClaimState.NOT_ESTABLISHED,
                ClaimState.CONFLICTING,
            }:
                gap(
                    "description-support",
                    GapKind.CONTRADICTION
                    if claim.state == ClaimState.CONFLICTING
                    else GapKind.BASIS,
                    claim.label,
                    claim.conclusion,
                    claim.remaining,
                    claim.sources,
                )

        facts.extend(self.commit_facts(case))
        if (
            case.id
            in {"policy-06", "wb-rule-96ab1268f59f312d", "wb-rule-c65a6e7dfbf38d60"}
            and "water-method-note" in self.docs
        ):
            gap(
                "unmeasured-evaporation",
                GapKind.BASIS,
                "Cooling evaporation uncertainty is unmeasured",
                "The owning method note identifies the net-zero convention as a lower bound with an unmeasured evaporation error. Balanced provider intake/return factors do not prove balanced flows in each activity.",
                "Measure intake, return and separately reported evaporation by technology; document bounds and an explicit policy decision.",
                ["/curation/evidence/water-method-note"],
            )
        if case.id == "policy-12":
            gap(
                "provider-coverage",
                GapKind.TRACE,
                "Method-provider coverage remains partial",
                "Recovered Workbench sources cover several implementations. The separately owned AWARE convention is not established by the EF/GLAM code.",
                "Attach the exact AWARE implementation and its policy evidence from the owning water-scarcity project.",
            )
        if case.origin != curation.Origin.FINDING_CLASS:
            if not any(g.kind == GapKind.BASIS for g in gaps):
                gap(
                    "scientific-basis",
                    GapKind.BASIS,
                    "Scientific support needs claim-level review",
                    "This audit establishes what the preserved source says. It does not certify that a name equivalence, physical assumption or correction is scientifically valid.",
                    "Attach an exact authoritative passage or source row, explain its applicability and document alternatives or contradictory evidence.",
                )
            if not case.reported_by or not case.reported_at:
                gap(
                    "discovery-attribution",
                    GapKind.ATTRIBUTION,
                    "Discovery author or date is not recorded",
                    "Git author, co-author, provider mapper and migration operator describe different roles. None supplies a missing discovery attribution.",
                    "Recover the original issue, notebook or message where this observation was made; otherwise keep attribution explicitly unknown.",
                )
            if not case.validations and not any(
                g.kind == GapKind.REPRODUCTION for g in gaps
            ):
                gap(
                    "execution-receipt",
                    GapKind.REPRODUCTION,
                    "No case-specific execution receipt",
                    "A test file or implementation link is evidence of code presence, not evidence that this exact case passed.",
                    "Record the command, input hashes, code revision, expected/observed outputs and negative controls in a reproducible receipt.",
                )
            if not any(
                s.scope == curation.ReviewScope.SCIENTIFIC
                and s.revision == case.revision
                for s in case.signoffs
            ):
                gap(
                    "scientific-signoff",
                    GapKind.REVIEW,
                    "No revision-specific scientific review recorded",
                    "No named scientific review is attached to this case at its recorded revision.",
                    "Request review of the exact evidence and applicability. Preserve the reviewer, date, verdict, revision and review link.",
                )
        if any(t.state == State.MISMATCH for t in traces):
            capture = State.MISMATCH
            detail = "At least one evidence locator or source integrity check failed."
        if capture == State.MISMATCH:
            gap(
                "capture-mismatch",
                GapKind.CONTRADICTION,
                "Source capture does not match",
                detail,
                "Repair the capture from the authoritative original; preserve the discrepancy and rerun the audit.",
            )
        if capture in {State.INCOMPLETE, State.NOT_ASSESSED}:
            gap(
                "capture-incomplete",
                GapKind.TRACE,
                "Claim-to-source capture needs review",
                detail,
                "Check the exact source passage against the claimed observation and record the result.",
            )
        if recovery:
            facts.extend(recovery.facts)
            traces.extend(
                self.anchor("Recovered original evidence", url)
                for url in recovery.review.sources
            )
            gaps = [g for g in gaps if g.code not in recovery.resolved_gaps]
            gaps.extend(recovery.remaining_gaps)
        if supplement := self.supplements.get(case.id):
            facts.extend(supplement.facts)
            gaps.extend(supplement.gaps)
            traces.extend(self.anchor("Supplementary source evidence", url)
                          for url in supplement.sources)
        if (
            case.id
            in {
                "wb-factor-af8bc1926a017bd6",
                "wb-factor-cacf7c5e1102cf6c",
            }
            and "original-evidence-upstream-quantity-associations" in self.docs
        ):
            evidence = self.decoded("original-evidence-upstream-quantity-associations")
            titanium = next(r for r in evidence["records"] if r["name"] == "Titanium")
            index = evidence["records"].index(titanium)
            url = f"/curation/evidence/original-evidence-upstream-quantity-associations?pointer=%2Frecords%2F{index}"
            fact(
                "Related upstream quantity decision",
                "The recovered titanium associations retain TiO2→Ti conversion multipliers; equivalence to the historical Workbench export is not asserted.",
                url,
            )
            if not self.applications.get(case.id):
                gap(
                    "titanium-quantity-application",
                    GapKind.BASIS,
                    "TiO2-to-titanium quantity application needs receiving",
                    "The upstream correspondence retains a 0.599 multiplier, while the historical Workbench derivative omitted quantity and match-qualification fields. Matching the JRC factor value does not settle the source mass basis or whether conversion is applied exactly once.",
                    "Trace the exact original source correspondence and the consuming quantity ledger. Keep compound mass and elemental mass distinct; record application before accepting or changing this factor.",
                    [url, "/curation/cases/policy-09#provenance"],
                )
        application_checks = self.applications.get(case.id, [])
        if (
            application_checks
            and case.id
            in {"policy-09", "wb-factor-af8bc1926a017bd6", "wb-factor-cacf7c5e1102cf6c"}
            and "titanium-workbench-quantity-trace" in self.docs
        ):
            trace = self.decoded("titanium-workbench-quantity-trace")
            code = case.reference_id.split("/", 1)[-1] if case.reference_id else None
            selected = [
                row
                for row in trace["observations"]
                if case.id == "policy-09"
                or row["observation"]["native_input_key"][1] == code
            ]
            fact(
                "Pilot TiO2 observations traced",
                len(selected),
                "/curation/evidence/titanium-workbench-quantity-trace?pointer=%2Fobservations",
            )
            if "titanium-processed-quantity-trace" in self.docs:
                processed = self.decoded("titanium-processed-quantity-trace")
                checks = [
                    row
                    for p in processed["projects"]
                    for row in p["contributions"]
                    if case.id == "policy-09" or row["native_key"][1] == code
                ]
                fact(
                    "Direct TiO2 contribution checks",
                    len(checks),
                    "/curation/evidence/titanium-processed-quantity-trace?pointer=%2Fprojects",
                )
            if case.id == "policy-09":
                gaps = [
                    g
                    for g in gaps
                    if g.code != "recovery-policy-09-1-binding-application"
                ]
                gap(
                    "titanium-accepted-application",
                    GapKind.BASIS,
                    "Accepted source interpretation and mineral application remain open",
                    "The inspected current path now has a concrete readback: it omits 0.599. This answers the original receiving question for those rows; it does not establish the accepted supplier quantity interpretation or a qualified replacement application.",
                    "Review the original quantity convention and mineral relation policy, then receive a coherent quantity-aware application and its actual consumer readback.",
                    ["/curation/evidence/quantity-application-checks"],
                )
        for check in application_checks:
            traces.extend(
                self.anchor("Quantity application evidence", url)
                for url in check.sources
            )
            if check.validation.result in {
                curation.Result.FAILED,
                curation.Result.BLOCKED,
            }:
                gap(
                    "application-" + check.id,
                    GapKind.CONTRADICTION
                    if check.validation.result == curation.Result.FAILED
                    else GapKind.REPRODUCTION,
                    check.validation.label,
                    check.observed,
                    check.remaining,
                    check.sources,
                )
        if self.mapping_manifest and case.id in self.mapping_manifest.case_links:
            links = self.mapping_manifest.case_links[case.id]
            url = f"/curation/mappings/?case={case.id}"
            traces.append(TraceCheck("Pinned original mapping and alias traces", url, State.MATCHED,
                                     "All original rows and aliases were reproduced. Identifier occurrence links are reading aids, not acceptance or independent support.",
                                     "source-mapping-provenance"))
            fact("Linked original mapping assertions", len(links["assertions"]), url)
            fact("Linked historical aliases", len(links["aliases"]), url)
            gap("mapping-provenance-unqualified", GapKind.SCOPE,
                "Source custody is verified; mapping applicability remains unresolved",
                "Original bytes and row coordinates are verified. Historical generation, source-version compatibility, quantity/context applicability and review remain separately unqualified.",
                "Review the original assertions and disagreements before accepting a mapping or method application.", [url])
        return CaseAudit(
            case.id,
            kind,
            derivation,
            capture,
            detail,
            traces,
            facts,
            gaps,
            [historical_claim] if historical_claim else [],
            [recovery] if recovery else [],
            application_checks,
        )


def build(register_path, repositories):
    register = curation.read_register(register_path)
    if register is None:
        raise ValueError("Register does not exist")
    sources = SourceAudit(register_path, register, repositories)
    cases = [sources.case(c) for c in register.cases]
    return ProvenanceAudit(
        1,
        datetime.now(timezone.utc),
        sha(register_path.read_bytes()),
        sha(Path(__file__).read_bytes()),
        "tools/audit_curation_provenance.py",
        "Deterministic comparison of captured records, source locators and declared Git objects. No scientific code execution, new review approval or automatic claim of correctness.",
        list(sources.checks.values()),
        cases,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--register", type=Path, required=True)
    parser.add_argument("--repository", action="append", default=[], metavar="URL=PATH")
    args = parser.parse_args()
    repositories = dict(value.split("=", 1) for value in args.repository)
    audit = build(args.register, repositories)
    output = args.register.with_name("provenance-audit.json")
    raw = TypeAdapter(ProvenanceAudit).dump_json(audit, indent=2)
    temp = output.with_suffix(".json.tmp")
    temp.write_bytes(raw)
    temp.replace(output)
    print(
        json.dumps(
            dict(
                cases=len(audit.cases),
                documents=len(audit.documents),
                capture=dict(Counter(c.capture for c in audit.cases)),
                gaps=dict(Counter(g.code for c in audit.cases for g in c.gaps)),
                output=str(output),
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
