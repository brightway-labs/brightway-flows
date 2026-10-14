"""A case cannot borrow validation or approval from another revision."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from brightway_flows.webapps.app import create_app
from brightway_flows.webapps.app.curation import (
    Adoption,
    Document,
    Event,
    Evidence,
    Implementation,
    ImplementationRole,
    Proposal,
    ProposalKind,
    ProposalState,
    ReviewPackage,
    Result,
    ReviewScope,
    SignOff,
    Validation,
    Verdict,
    filter_cases,
    package_revision,
    read_register,
    review_packages,
    source_file,
)

from brightway_flows.webapps.app.curation_modules import module_catalogue

ROOT = Path(__file__).resolve().parents[1]
STAMP = datetime(2026, 10, 13, tzinfo=timezone.utc)
URL = "https://github.com/brightway-labs/brightway-flows/pull/387"


@pytest.fixture
def register():
    return read_register(ROOT / "docs/curation/register.json")


@pytest.fixture
def case(register):
    return next(c for c in register.cases if c.id == "same-unit-conversion")


def receipt(case, result=Result.PASSED, revision=None):
    return Validation(
        "Focused checks",
        result,
        revision or case.revision,
        "Public fixture only",
        STAMP,
        URL,
        "No full-build claim",
    )


def review(
    case,
    scope=ReviewScope.SCIENTIFIC,
    revision=None,
    verdict=Verdict.APPROVED,
    when=STAMP,
):
    return SignOff(
        "Fixture reviewer", scope, verdict, revision or case.revision, when, URL
    )


def test_old_test_run_cannot_validate_new_revision(case):
    changed = replace(case, validations=[receipt(case)], revision="a" * 40)
    assert changed.quality == "Validation stale"


def test_failure_and_incomplete_execution_are_not_hidden_by_a_pass(case):
    assert (
        replace(case, validations=[receipt(case), receipt(case, Result.FAILED)]).quality
        == "Check failed"
    )
    assert (
        replace(
            case, validations=[receipt(case), receipt(case, Result.BLOCKED)]
        ).quality
        == "Validation incomplete"
    )


def test_reported_tests_are_distinguished_from_executed_checks(case):
    assert (
        replace(case, validations=[receipt(case, Result.REPORTED)]).quality
        == "Checks reported"
    )


def test_code_review_is_not_scientific_signoff(case):
    assert (
        replace(case, signoffs=[review(case, ReviewScope.CODE)]).signoff_label
        == "Not recorded"
    )


def test_signoff_names_the_reviewed_revision_and_can_be_withdrawn(case):
    assert (
        replace(case, signoffs=[review(case, revision="a" * 40)]).signoff_label
        == "Stale revision"
    )
    later = datetime(2026, 10, 14, tzinfo=timezone.utc)
    signed = replace(
        case,
        signoffs=[review(case), review(case, verdict=Verdict.WITHDRAWN, when=later)],
    )
    assert signed.signoff_label == "Withdrawn · Fixture reviewer"


def test_another_reviewer_cannot_clear_requested_changes(case):
    objection = review(case, verdict=Verdict.CHANGES_REQUESTED)
    later = datetime(2026, 10, 14, tzinfo=timezone.utc)
    approval = replace(review(case, when=later), person="Another fixture reviewer")
    signed = replace(case, signoffs=[objection, approval])
    assert signed.signoff_label == "Changes requested · Fixture reviewer"


def test_search_and_filters_compose_and_sort_is_stable(register):
    selected = filter_cases(
        register.cases, query="water", source="BAFU", stage="implemented"
    )
    assert [c.id for c in selected] == ["bafu-water-units"]
    assert not filter_cases(register.cases, query="no-such-observation")
    ascending = filter_cases(register.cases, sort="title", direction="asc")
    descending = filter_cases(register.cases, sort="title", direction="desc")
    assert ascending == list(reversed(descending))


@pytest.mark.parametrize(
    "change",
    [
        "duplicate",
        "unsafe-url",
        "unsupported-version",
        "approval-mismatch",
        "no-evidence",
        "naive-date",
        "invalid-module",
    ],
)
def test_malformed_register_fails_explicitly(tmp_path, change):
    data = json.loads((ROOT / "docs/curation/register.json").read_text())
    if change == "duplicate":
        data["cases"].append(copy.deepcopy(data["cases"][0]))
    elif change == "unsafe-url":
        data["cases"][0]["evidence"][0]["url"] = "javascript:alert(1)"
    elif change == "unsupported-version":
        data["schema_version"] = 99
    elif change == "approval-mismatch":
        data["cases"][0]["adoption"] = dict(
            release="fixture",
            revision="a" * 40,
            evidence_url=URL,
            recorded_at=STAMP.isoformat(),
        )
    elif change == "naive-date":
        data["cases"][0]["updated_at"] = "2026-10-13T12:00:00"
    elif change == "invalid-module":
        data["cases"][0]["modules"] = ["../../private"]
    else:
        data["cases"][0]["evidence"] = []
    path = tmp_path / "register.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        read_register(path)


def test_modules_reuse_existing_register_and_do_not_duplicate_shared_reader(register):
    modules = module_catalogue(ROOT, register.cases)
    unit = next(m for m in modules if m.id == "brightway_flows.merge.unit_changes")
    assert "published-units.json" in unit.decision_files
    assert "created-flow-unit-decisions.json" in unit.decision_files
    assert "bafu-water-units" in [c.id for c in unit.cases]
    assert len({m.id for m in modules}) == len(modules)
    assert all((ROOT / m.path).is_file() for m in modules)
    consensus = next(
        m for m in modules if m.id == "brightway_flows.transformers.consensus_match"
    )
    assert consensus.path.endswith("/__init__.py")


def test_finding_classes_are_distinct_from_individual_source_and_processing_cases(
    register,
):
    classes = filter_cases(register.cases, view="classes")
    assert classes and all(c.origin.value == "finding-class" for c in classes)
    cases = filter_cases(register.cases, view="all")
    assert {"same-unit-conversion", "lookup-quantity", "bafu-water-units"} <= {
        c.id for c in cases
    }


def test_source_reader_cannot_escape_the_checkout(tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("private")
    root = tmp_path / "checkout"
    root.mkdir()
    assert source_file(root, "../outside.txt") is None
    (root / "link.py").symlink_to(outside)
    assert source_file(root, "link.py") is None


def test_curation_works_without_build_and_preserves_filter_links(tmp_path):
    app = create_app(database_path=tmp_path / "absent.sqlite3", docs_path=ROOT / "docs")
    client = app.test_client()
    response = client.get("/curation/?q=water&source=BAFU&group=stage")
    assert response.status_code == 200
    assert b"Keep BAFU water quantities" in response.data
    assert (
        b"q=water&amp;source=BAFU" in response.data
        or b"q=water&amp;stage=" in response.data
    )
    assert not (tmp_path / "absent.sqlite3").exists()
    for route in (
        "/curation/cases/lookup-quantity",
        "/curation/modules/",
        "/curation/modules/brightway_flows.lcia.conversion",
    ):
        assert client.get(route).status_code == 200
    assert client.get("/curation/cases/does-not-exist").status_code == 404
    assert client.get("/curation/modules/not.a.module").status_code == 404
    assert client.post("/curation/").status_code == 405
    exported = client.get("/curation/register.json")
    assert exported.status_code == 200
    assert exported.json["schema_version"] == 1


def test_missing_and_invalid_register_are_distinct(tmp_path):
    app = create_app(database_path=tmp_path / "absent.sqlite3", docs_path=tmp_path)
    assert b"No curation register published" in app.test_client().get("/curation/").data
    (tmp_path / "curation").mkdir()
    (tmp_path / "curation/register.json").write_text('{"schema_version": 99}')
    response = app.test_client().get("/curation/")
    assert response.status_code == 503
    assert b"Register unavailable" in response.data


def test_record_text_is_escaped_in_html(tmp_path):
    data = json.loads((ROOT / "docs/curation/register.json").read_text())
    data["cases"][0]["title"] = '<script>alert("fixture")</script>'
    (tmp_path / "curation").mkdir()
    (tmp_path / "curation/register.json").write_text(json.dumps(data))
    app = create_app(database_path=tmp_path / "absent.sqlite3", docs_path=tmp_path)
    response = app.test_client().get("/curation/")
    assert b"<script>alert(" not in response.data
    assert b"&lt;script&gt;" in response.data
    exported = app.test_client().get("/curation/register.json")
    assert exported.status_code == 200
    assert exported.json["cases"][0]["title"] == data["cases"][0]["title"]


@pytest.fixture
def local_register(tmp_path):
    data = json.loads((ROOT / "docs/curation/register.json").read_text())
    raw = b'{"rows": [{"name": "<script>source text</script>"}]}'
    directory = tmp_path / "sources"
    directory.mkdir()
    (directory / "record.json").write_bytes(raw)
    data["documents"] = [
        dict(
            id="source-record",
            title="Preserved source",
            filename="record.json",
            sha256=hashlib.sha256(raw).hexdigest(),
            generation="Test source generation",
        )
    ]
    path = tmp_path / "register.json"
    path.write_text(json.dumps(data))
    app = create_app(database_path=tmp_path / "absent.sqlite3", docs_path=ROOT / "docs")
    app.config["CURATION_REGISTER_PATH"] = path
    return app.test_client(), path, data


def test_local_evidence_requires_matching_hash_and_escapes_source(local_register):
    client, path, _data = local_register
    response = client.get("/curation/evidence/source-record?pointer=/rows/0")
    assert response.status_code == 200
    assert b"&lt;script&gt;source text&lt;/script&gt;" in response.data
    assert b"<script>source text" not in response.data
    assert (
        client.get("/curation/evidence/source-record?pointer=/rows/20").status_code
        == 404
    )
    assert (
        client.get("/curation/evidence/source-record?pointer=rows").status_code == 404
    )
    assert client.get("/curation/evidence/unknown").status_code == 404
    (path.parent / "sources/record.json").write_text("Changed after import")
    assert client.get("/curation/evidence/source-record").status_code == 503


def test_evidence_symlink_cannot_escape_bundle(local_register):
    client, path, _data = local_register
    source = path.parent / "sources/record.json"
    outside = path.parent / "outside.json"
    outside.write_bytes(source.read_bytes())
    source.unlink()
    source.symlink_to(outside)
    assert client.get("/curation/evidence/source-record").status_code == 404


@pytest.mark.parametrize("malformation", ["path", "duplicate", "related"])
def test_invalid_local_references_fail_at_read_boundary(local_register, malformation):
    _client, path, data = local_register
    if malformation == "path":
        data["documents"][0]["filename"] = "../outside.json"
    elif malformation == "duplicate":
        data["documents"].append(data["documents"][0])
    else:
        data["cases"][0]["related_cases"] = ["absent-case"]
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        read_register(path)


def test_pagination_shortlist_and_collection_filter_share_the_full_register(
    local_register,
):
    client, path, data = local_register
    original = data["cases"][0]
    data["cases"] = []
    for i in range(61):
        case = copy.deepcopy(original)
        case.update(
            id=f"page-test-{i:02}",
            title=f"Pagination case {i:02}",
            collection="Pagination test",
        )
        data["cases"].append(case)
    path.write_text(json.dumps(data))
    first = client.get("/curation/?collection=Pagination+test&sort=title&direction=asc")
    assert first.status_code == 200
    assert first.data.count(b"data-case-row=") == 50
    assert b'data-case-row="page-test-60"' not in first.data
    second = client.get(
        "/curation/?collection=Pagination+test&sort=title&direction=asc&page=2"
    )
    assert second.data.count(b"data-case-row=") == 11
    assert b'data-case-row="page-test-60"' in second.data
    saved = client.get(
        "/curation/?saved=page-test-00,page-test-60&collection=Pagination+test"
    )
    assert saved.data.count(b"data-case-row=") == 2
    assert b'data-case-row="page-test-60"' in saved.data
    assert b"migration-coverage" not in saved.data
    assert (
        client.get("/curation/?collection=another").data.count(b"data-case-row=") == 0
    )
    assert client.get("/curation/?page=not-an-integer").status_code == 200
    assert len(client.get("/curation/register.json").json["cases"]) == 61


def test_code_attribution_does_not_become_discovery_authorship(case):
    implementation = Implementation(
        "Original rule",
        URL,
        ImplementationRole.HISTORICAL,
        case.revision,
        "original.py",
        "Recorded code author",
        STAMP,
    )
    imported = replace(
        case, reported_by=None, reported_at=None, implementations=[implementation]
    )
    assert imported.contributor_label == "Code: Recorded code author"
    assert filter_cases([imported], author="Recorded code author") == [imported]
    assert imported.reported_by is None and imported.reported_at is None
    assert imported.signoff_label == case.signoff_label


def test_proposed_destination_is_not_an_implemented_case_link(case):
    proposed = replace(
        case, modules=[], proposed_modules=["brightway_flows.lcia.conversion"]
    )
    module = next(
        m
        for m in module_catalogue(ROOT, [proposed])
        if m.id == proposed.proposed_modules[0]
    )
    assert not module.cases


def package_for(case):
    return ReviewPackage(
        "review-unit-rule",
        "Unit rule",
        "Quantities",
        "Recorded quantity handling",
        "One explicit source quantity rule",
        "What evidence establishes the conversion?",
        [case.id],
    )


def test_package_fingerprint_reopens_for_evidence_and_membership_but_not_reindexing(
    register, case
):
    package = package_for(case)
    original = replace(register, cases=[case])
    fingerprint = package_revision(original, package)
    reindexed = replace(
        original,
        cases=[replace(case, updated_at=datetime(2026, 11, 1, tzinfo=timezone.utc))],
    )
    assert package_revision(reindexed, package) == fingerprint
    changed = replace(
        original, cases=[replace(case, original_record="changed source evidence")]
    )
    assert package_revision(changed, package) != fingerprint
    assert (
        package_revision(original, replace(package, decision="Another review question"))
        != fingerprint
    )
    another = replace(case, id="another-source-record")
    assert (
        package_revision(
            replace(original, cases=[case, another]),
            replace(package, case_ids=[case.id, another.id]),
        )
        != fingerprint
    )


def test_unassigned_cases_remain_visible_after_import(register, case):
    package = package_for(case)
    grouped = review_packages(replace(register, packages=[package]))
    inbox = next(p for p in grouped if p.id == "unassigned-cases")
    assert set(inbox.case_ids) == {c.id for c in register.cases if c.id != case.id}


@pytest.mark.parametrize(
    "citation_kind",
    [
        "finding",
        "proposal",
        "implementation",
        "validation",
        "signoff",
        "history",
        "adoption",
    ],
)
def test_package_triage_reopens_when_any_cited_document_changes(
    register, case, citation_kind
):
    """Synthetic receipt controls stay outside the actual example register."""
    url = "/curation/evidence/test-trace?pointer=/result"
    clean = replace(
        case,
        evidence=[],
        proposals=[],
        implementations=[],
        validations=[],
        signoffs=[],
        history=[],
        adoption=None,
    )
    citations = {
        "finding": dict(evidence=[Evidence("Test source", url, "Synthetic control")]),
        "proposal": dict(
            proposals=[
                Proposal(
                    "Test proposal",
                    url,
                    ProposalKind.ISSUE,
                    ProposalState.OPEN,
                    None,
                    None,
                )
            ]
        ),
        "implementation": dict(
            implementations=[
                Implementation(
                    "Test implementation",
                    url,
                    ImplementationRole.CANDIDATE,
                    case.revision,
                    "test.py",
                )
            ]
        ),
        "validation": dict(validations=[replace(receipt(case), evidence_url=url)]),
        "signoff": dict(signoffs=[replace(review(case), evidence_url=url)]),
        "history": dict(history=[Event("Test event", STAMP, "Test recorder", url)]),
        "adoption": dict(adoption=Adoption("Test release", case.revision, url, STAMP)),
    }
    cited = replace(clean, **citations[citation_kind])
    document = Document("test-trace", "Test trace", "trace.json", "0" * 64, "Synthetic")
    unrelated = replace(document, id="unrelated-trace", filename="unrelated.json")
    original = replace(register, cases=[cited], documents=[document, unrelated])
    package = package_for(cited)
    fingerprint = package_revision(original, package)
    assert (
        package_revision(
            replace(
                original, documents=[replace(document, sha256="1" * 64), unrelated]
            ),
            package,
        )
        != fingerprint
    )
    assert (
        package_revision(
            replace(
                original, documents=[document, replace(unrelated, sha256="1" * 64)]
            ),
            package,
        )
        == fingerprint
    )


@pytest.mark.parametrize(
    "problem", ["overlap", "missing-member", "duplicate-member", "no-question"]
)
def test_invalid_package_membership_is_rejected(local_register, problem):
    _client, path, data = local_register
    case_id = data["cases"][0]["id"]
    package = dict(
        id="review-package",
        title="A review",
        workstream="Quantity",
        summary="Recorded rules",
        grouping_rule="Same rule",
        decision="Review its scope",
        case_ids=[case_id],
    )
    data["packages"] = [package]
    if problem == "overlap":
        data["packages"].append(dict(package, id="second-package"))
    elif problem == "missing-member":
        package["case_ids"] = ["unknown-case"]
    elif problem == "duplicate-member":
        package["case_ids"].append(case_id)
    else:
        package["decision"] = ""
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        read_register(path)


def test_packages_are_default_and_members_remain_individually_browsable(local_register):
    client, path, data = local_register
    package = dict(
        id="review-package",
        title="Quantity rules package",
        workstream="Quantity",
        summary="Recorded rules",
        grouping_rule="One shared question",
        decision="Review the quantity scope",
        case_ids=[data["cases"][0]["id"]],
    )
    data["packages"] = [package]
    path.write_text(json.dumps(data))
    default = client.get("/curation/")
    assert default.status_code == 200
    assert b"Quantity rules package" in default.data
    assert b"Cases awaiting grouping" in default.data
    assert b"data-case-row=" not in default.data
    detail = client.get("/curation/packages/review-package")
    assert detail.status_code == 200 and b"Review the quantity scope" in detail.data
    members = client.get("/curation/?view=all&package=review-package")
    assert members.status_code == 200 and members.data.count(b"data-case-row=") == 1
    assert client.get("/curation/?package=unknown").status_code == 404
    assert client.get("/curation/packages/unknown").status_code == 404
