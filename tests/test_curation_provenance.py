"""Evidence capture must never silently survive changed sources or imply approval."""

import importlib.util
import json
from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from brightway_flows.webapps.app import create_app, curation
from brightway_flows.webapps.app import curation_provenance as provenance

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "capture_audit", ROOT / "tools/audit_curation_provenance.py"
)
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


@pytest.fixture
def bundle(tmp_path):
    payload = json.loads((ROOT / "docs/curation/register.json").read_text())
    public = payload["cases"][1]
    public.update(
        id="provider-assertion",
        collection="External synonym assertions",
        origin="processing",
        stage="recorded",
        modules=[],
        validations=[],
        proposals=[],
        test_paths=[],
        expectation_paths=[],
    )
    row = dict(
        SourceListName="openLCA",
        SourceFlowName="Occupation",
        SourceFlowUUID="source-id",
        SourceFlowContext="land",
        SourceUnit="m2",
        MatchCondition="=",
        ConversionFactor="1.0",
        TargetFlowName="Land use",
        TargetFlowUUID="target-id",
        TargetFlowContext="land",
        TargetUnit="m2*a",
        Mapper="Recorded provider mapper",
        Verifier="",
        LastUpdated="2/14/2020",
    )
    import csv, io

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=row)
    writer.writeheader()
    writer.writerow(row)
    csv_raw = buffer.getvalue().encode()
    original = dict(
        csv_row=2,
        source_sha256=tool.sha(csv_raw),
        source_name="occupation",
        target_name="land use",
        original=row,
    )
    public.update(
        original_record=json.dumps(original),
        evidence=[
            dict(
                label="Selected provider assertion",
                url="/curation/evidence/fedefl-selections?pointer=%2F0",
                kind="Preserved source record",
            )
        ],
        reported_by=None,
        reported_at=None,
        implementations=[],
    )
    sources = tmp_path / "sources"
    sources.mkdir()
    documents = []
    for identifier, filename, raw in [
        ("fedefl-input", "input.csv", csv_raw),
        ("fedefl-selections", "selection.json", json.dumps([original]).encode()),
    ]:
        (sources / filename).write_bytes(raw)
        documents.append(
            dict(
                id=identifier,
                title=identifier,
                filename=filename,
                sha256=tool.sha(raw),
                generation="Fixture for rejection behavior",
                origin_url=None,
            )
        )
    payload.update(cases=[public], documents=documents, packages=[])
    path = tmp_path / "register.json"
    path.write_text(json.dumps(payload))
    audit = tool.build(path, {})
    path.with_name("provenance-audit.json").write_bytes(
        TypeAdapter(provenance.ProvenanceAudit).dump_json(audit)
    )
    return path, audit


def test_provider_metadata_and_dimensional_conflict_do_not_become_approval(bundle):
    path, audit = bundle
    case = audit.cases[0]
    assert case.capture == provenance.CheckState.MATCHED
    assert case.label == "Conflicting evidence"
    assert any(g.code == "unit-mismatch" for g in case.gaps)
    assert any(
        f.label == "Provider mapper" and f.value == "Recorded provider mapper"
        for f in case.facts
    )
    register = curation.read_register(path)
    assert register.cases[0].reported_by is None
    assert not register.cases[0].signoffs and not register.cases[0].validations


def captured_metadata_fixture(bundle, identifier, source, collection, original_record, pointer):
    """Capture a synthetic test source and its precise case anchor."""
    path, _ = bundle
    filename = identifier + ".json"
    raw = json.dumps(source).encode()
    (path.parent / "sources" / filename).write_bytes(raw)
    payload = json.loads(path.read_bytes())
    payload["documents"].append(dict(id=identifier, title="Test-only metadata source",
        filename=filename, sha256=tool.sha(raw),
        generation="Synthetic rejection control", origin_url=None))
    payload["cases"][0].update(collection=collection,
        original_record=json.dumps(original_record), evidence=[dict(label="Original test source",
        url=f"/curation/evidence/{identifier}?pointer={pointer}", kind="Test-only source")])
    path.write_text(json.dumps(payload))
    return path


def method_metadata_fixture(bundle, metadata, rows):
    """Synthetic intake controls; never copied to the actual Curation register."""
    original = {"name": ["Explicit test method"], "metadata": metadata, "cfs": rows}
    return captured_metadata_fixture(bundle, "test-method", [original],
        "Consumer method metadata", original, "%2F0")


def test_method_metadata_conflicts_keep_actual_counts_and_missing_unit(bundle):
    path = method_metadata_fixture(bundle, {"num_cfs": 1},
        [[["test-native", "one"], 0], [["test-native", "two"], 1]])
    case = tool.build(path, {}).cases[0]
    assert case.capture == provenance.CheckState.MATCHED
    facts = {f.label: f.value for f in case.facts}
    assert facts["Retained factor entries"] == "2"
    assert facts["Metadata factor count"] == "1"
    assert {"method-count-metadata", "method-unit-unrecorded", "method-execution-ancestry"} <= {g.code for g in case.gaps}
    assert case.label == "Conflicting evidence"
    assert not curation.read_register(path).cases[0].signoffs


def test_method_empty_factor_population_is_an_explicit_zero_count(bundle):
    path = method_metadata_fixture(bundle, {"num_cfs": 0, "unit": "test-unit"}, [])
    case = tool.build(path, {}).cases[0]
    assert next(f.value for f in case.facts if f.label == "Retained factor entries") == "0"
    assert not {"method-count-metadata", "method-unit-unrecorded"} & {g.code for g in case.gaps}
    assert "method-execution-ancestry" in {g.code for g in case.gaps}


def test_method_duplicate_keys_are_preserved_even_when_count_matches(bundle):
    path = method_metadata_fixture(bundle, {"num_cfs": 2, "unit": "test-unit"},
        [[["test-native", "one"], 0], [["test-native", "one"], 1]])
    case = tool.build(path, {}).cases[0]
    assert "method-native-key-repeated" in {g.code for g in case.gaps}
    assert next(f.value for f in case.facts if f.label == "Distinct native factor keys") == "1"


def test_method_malformed_native_reference_cannot_be_silently_skipped(bundle):
    path = method_metadata_fixture(bundle, {"num_cfs": 1}, [[[None, "one"], 0]])
    with pytest.raises(ValueError, match="Malformed original method"):
        tool.build(path, {})


def test_method_changed_original_record_does_not_match_retained_source(bundle):
    path = method_metadata_fixture(bundle, {"num_cfs": 1, "unit": "test-unit"},
        [[["test-native", "one"], 0]])
    payload = json.loads(path.read_bytes())
    changed = json.loads(payload["cases"][0]["original_record"])
    changed["metadata"]["unit"] = "fabricated-unit"
    payload["cases"][0]["original_record"] = json.dumps(changed)
    path.write_text(json.dumps(payload))
    assert tool.build(path, {}).cases[0].capture == provenance.CheckState.MISMATCH


def placeholder_metadata_fixture(bundle, metadata, rows):
    """Synthetic metadata controls; no real finding or source input is created."""
    return captured_metadata_fixture(bundle, "test-placeholders",
        {"metadata": metadata, "mappings": rows},
        "Placeholder classification metadata", metadata, "%2Fmetadata")


@pytest.mark.parametrize("metadata", [
    {"total_placeholders": 1, "unmatched_v2": -1},
    {"total_placeholders": True, "unmatched_v2": 0},
    {"total_placeholders": 2, "unmatched_v2": 1},
    {},
])
def test_placeholder_inconsistent_counts_preserve_actual_source_records(bundle, metadata):
    rows = [{"placeholder_name": name, "placeholder_categories": ["test-context"]}
            for name in ["test-one", "test-two"]]
    path = placeholder_metadata_fixture(bundle, metadata, rows)
    case = tool.build(path, {}).cases[0]
    assert case.capture == provenance.CheckState.MATCHED
    facts = {f.label: f.value for f in case.facts}
    assert facts["Retained mapping records"] == "2"
    assert facts["Distinct literal name/category descriptions"] == "2"
    assert next(f.evidence_url for f in case.facts if f.label == "Retained mapping records") == "/curation/evidence/test-placeholders?pointer=%2Fmappings"
    assert {"placeholder-count-metadata", "placeholder-input-generation"} <= {g.code for g in case.gaps}
    source_case = curation.read_register(path).cases[0]
    assert source_case.stage == curation.Stage.RECORDED and not source_case.signoffs


def test_placeholder_zero_count_does_not_establish_source_generation(bundle):
    path = placeholder_metadata_fixture(bundle, {"total_placeholders": 0, "unmatched_v2": 0}, [])
    case = tool.build(path, {}).cases[0]
    assert next(f.value for f in case.facts if f.label == "Retained mapping records") == "0"
    assert "placeholder-count-metadata" not in {g.code for g in case.gaps}
    assert "placeholder-input-generation" in {g.code for g in case.gaps}


def test_placeholder_repeated_descriptions_do_not_deduplicate_records(bundle):
    rows = [{"placeholder_name": "test-one", "placeholder_categories": ["test-context"],
             "placeholder_code": code} for code in ["test-a", "test-b"]]
    path = placeholder_metadata_fixture(bundle, {"total_placeholders": 1, "unmatched_v2": 0}, rows)
    case = tool.build(path, {}).cases[0]
    facts = {f.label: f.value for f in case.facts}
    assert facts["Retained mapping records"] == "2"
    assert facts["Distinct literal name/category descriptions"] == "1"
    assert tool.SourceAudit(path, curation.read_register(path), {}).decoded("test-placeholders")["mappings"] == rows


def test_placeholder_malformed_original_rows_are_not_skipped(bundle):
    path = placeholder_metadata_fixture(bundle, {"total_placeholders": 1, "unmatched_v2": 0},
        [{"placeholder_name": "test-one", "placeholder_categories": [None]}])
    with pytest.raises(ValueError, match="Malformed original placeholder classification"):
        tool.build(path, {})


def test_placeholder_changed_case_metadata_cannot_supply_source_facts(bundle):
    path = placeholder_metadata_fixture(bundle, {"total_placeholders": 1, "unmatched_v2": 0},
        [{"placeholder_name": "test-one", "placeholder_categories": []}])
    payload = json.loads(path.read_bytes())
    payload["cases"][0]["original_record"] = json.dumps({"total_placeholders": 999, "unmatched_v2": 998})
    path.write_text(json.dumps(payload))
    case = tool.build(path, {}).cases[0]
    assert case.capture == provenance.CheckState.MISMATCH
    assert next(f.value for f in case.facts if f.label == "Original reported source population") == "1"


@pytest.mark.parametrize("change", ["register", "source", "tool", "membership"])
def test_changed_artifacts_invalidate_audit(bundle, change):
    path, audit = bundle
    register = curation.read_register(path)
    assert provenance.read_audit(path, register, ROOT).cases
    if change == "register":
        path.write_text(path.read_text() + "\n")
    if change == "source":
        (path.parent / "sources/input.csv").write_text("changed")
    if change == "tool":
        audit = replace(audit, tool_sha256="0" * 64)
        path.with_name("provenance-audit.json").write_bytes(
            TypeAdapter(provenance.ProvenanceAudit).dump_json(audit)
        )
    if change == "membership":
        register = replace(register, cases=[])
    result = provenance.read_audit(path, register, ROOT)
    assert not result.cases and "stale" in result.status


def test_case_package_and_export_filters_expose_actual_evidence_gaps(bundle):
    path, _audit = bundle
    app = create_app(
        database_path=path.parent / "absent.sqlite3", docs_path=ROOT / "docs"
    )
    app.config["CURATION_REGISTER_PATH"] = path
    client = app.test_client()
    detail = client.get("/curation/cases/provider-assertion")
    assert detail.status_code == 200
    assert "Selected mapping has different units" in detail.text
    assert (
        "Provider mapper" in detail.text
        and "No revision-specific scientific review" in detail.text
    )
    results = client.get("/curation/?view=all&gap=contradiction")
    assert 'data-case-row="provider-assertion"' in results.text
    assert (
        'data-case-row="provider-assertion"'
        not in client.get("/curation/?view=all&gap=scope-missing").text
    )
    assert client.get("/curation/provenance-audit.json").status_code == 200
    (path.parent / "sources/input.csv").write_text("changed")
    assert client.get("/curation/provenance-audit.json").status_code == 409
    stale = client.get("/curation/cases/provider-assertion").text
    assert "Audit is stale" in stale and "Source record matched" not in stale


def test_navigation_counts_name_the_actual_register(bundle):
    path, _ = bundle
    app = create_app(
        database_path=path.parent / "absent.sqlite3", docs_path=ROOT / "docs"
    )
    app.config["CURATION_REGISTER_PATH"] = path
    html = app.test_client().get("/curation/?view=all").text
    assert 'Cases <span class="curation-nav-count">1</span>' in html
    assert "1 individual · 0 finding classes" in html


def test_literal_reader_never_executes_calls(tmp_path):
    marker = tmp_path / "executed"
    table = tool.literals(
        f"A={{'safe':1}}\nB=__import__('pathlib').Path({str(marker)!r}).touch()\n"
    )
    assert table["A"][0] == {"safe": 1} and "B" not in table
    assert not marker.exists()


def add_claim_receipt(bundle, *, state="partial", mutation=None):
    """Test-only source comparison; no production review fixture is written."""
    path, _ = bundle
    register = curation.read_register(path)
    case = register.cases[0]
    receipt = dict(
        schema_version=1,
        recorded_at="2026-10-13T16:00:00Z",
        method="Source comparison by coding agent; no scientific sign-off",
        source_sha256={d.id: d.sha256 for d in register.documents},
        scientific_signoff=False,
        claims=[
            dict(
                id=case.id,
                claim=case.summary,
                summary_sha256=provenance.summary_digest(case),
                state=state,
                conclusion="The source assertion exists; dimensional compatibility remains unresolved.",
                supported_scope="Exact provider row only.",
                remaining="Review the original quantities and contexts.",
                sources=["/curation/evidence/fedefl-selections?pointer=%2F0"],
            )
        ],
    )
    if mutation:
        mutation(receipt)
    raw = json.dumps(receipt).encode()
    filename = "remaining-claim-review.json"
    (path.parent / "sources" / filename).write_bytes(raw)
    payload = json.loads(path.read_text())
    payload["documents"].append(
        dict(
            id="remaining-claim-review",
            title="Test claim comparison",
            filename=filename,
            sha256=tool.sha(raw),
            generation="Test-only rejection fixture",
            origin_url=None,
        )
    )
    path.write_text(json.dumps(payload))
    return path


@pytest.mark.parametrize("state", ["supported", "partial"])
def test_scoped_claim_support_cannot_approve_or_clear_a_source_conflict(bundle, state):
    path = add_claim_receipt(bundle, state=state)
    audit = tool.build(path, {})
    result = audit.cases[0]
    assert result.claims[0].state == state
    assert result.capture == provenance.CheckState.MATCHED
    assert result.label == "Conflicting evidence"
    assert any(g.code == "unit-mismatch" for g in result.gaps)
    source = curation.read_register(path).cases[0]
    assert source.signoff_label == "Not recorded" and not source.validations
    assert source.stage == curation.Stage.RECORDED


@pytest.mark.parametrize(
    "mutation",
    [
        lambda r: r.update(scientific_signoff=True),
        lambda r: r["claims"][0].update(claim="Another claim"),
        lambda r: r["claims"][0].update(summary_sha256="0" * 64),
        lambda r: r["source_sha256"].update({"fedefl-selections": "0" * 64}),
        lambda r: r["claims"][0].update(sources=[]),
        lambda r: r["claims"][0].update(
            sources=["/curation/evidence/fedefl-selections?pointer=%2F99"]
        ),
        lambda r: r["source_sha256"].pop("fedefl-selections"),
        lambda r: r["claims"].append(r["claims"][0].copy()),
    ],
)
def test_invalid_claim_receiving_fails_explicitly(bundle, mutation):
    path = add_claim_receipt(bundle, mutation=mutation)
    with pytest.raises(ValueError):
        tool.build(path, {})


def test_claim_state_filters_and_source_comparison_remain_visible(bundle):
    path = add_claim_receipt(bundle)
    audit = tool.build(path, {})
    path.with_name("provenance-audit.json").write_bytes(
        TypeAdapter(provenance.ProvenanceAudit).dump_json(audit)
    )
    app = create_app(
        database_path=path.parent / "absent.sqlite3", docs_path=ROOT / "docs"
    )
    app.config["CURATION_REGISTER_PATH"] = path
    client = app.test_client()
    assert (
        'data-case-row="provider-assertion"'
        in client.get("/curation/?view=all&claim=partial").text
    )
    assert (
        'data-case-row="provider-assertion"'
        not in client.get("/curation/?view=all&claim=supported").text
    )
    html = client.get("/curation/cases/provider-assertion").text
    assert (
        "Description compared with source" in html
        and "Exact provider row only." in html
    )
    assert "Partially supported" in html and "scientific sign-off" in html


def add_recovery_receipt(bundle, *, state="supported", mutation=None):
    path = add_claim_receipt(bundle)
    register = curation.read_register(path)
    prior = json.loads(
        (path.parent / "sources/remaining-claim-review.json").read_bytes()
    )
    review = prior["claims"][0].copy()
    review.update(state=state, conclusion="New evidence narrows the original claim.")
    event = dict(
        previous_document="remaining-claim-review",
        recorded_at="2026-10-13T18:00:00Z",
        review=review,
        recovered=["Original source row was recovered and compared."],
        resolved_gaps=[],
        facts=[
            dict(
                label="Recovered source row",
                value="2",
                evidence_url=review["sources"][0],
            )
        ],
    )
    receipt = dict(
        schema_version=1,
        recorded_at=event["recorded_at"],
        method="Original evidence receiving",
        source_sha256={d.id: d.sha256 for d in register.documents},
        scientific_signoff=False,
        entries=[event],
    )
    if mutation:
        mutation(receipt)
    raw = json.dumps(receipt).encode()
    filename = "recovery.json"
    (path.parent / "sources" / filename).write_bytes(raw)
    payload = json.loads(path.read_bytes())
    payload["documents"].append(
        dict(
            id="original-evidence-recovery",
            title="Test recovery",
            filename=filename,
            sha256=tool.sha(raw),
            generation="Test-only rejection fixture",
            origin_url=None,
        )
    )
    path.write_text(json.dumps(payload))
    return path


@pytest.mark.parametrize("state", ["supported", "conflicting"])
def test_recovery_updates_current_assessment_preserves_history_and_cannot_approve(
    bundle, state
):
    path = add_recovery_receipt(bundle, state=state)
    audit = tool.build(path, {})
    result = audit.cases[0]
    assert result.claims[0].state == provenance.ClaimState.PARTIAL
    assert result.current_review.state == state
    assert result.recoveries and any(g.code == "unit-mismatch" for g in result.gaps)
    case = curation.read_register(path).cases[0]
    assert not case.signoffs and not case.validations
    assert case.stage == curation.Stage.RECORDED
    path.with_name("provenance-audit.json").write_bytes(
        TypeAdapter(provenance.ProvenanceAudit).dump_json(audit)
    )
    app = create_app(
        database_path=path.parent / "absent.sqlite3", docs_path=ROOT / "docs"
    )
    app.config["CURATION_REGISTER_PATH"] = path
    client = app.test_client()
    assert (
        'data-case-row="provider-assertion"'
        in client.get(f"/curation/?view=all&claim={state}").text
    )
    assert (
        'data-case-row="provider-assertion"'
        not in client.get("/curation/?view=all&claim=partial").text
    )
    html = client.get("/curation/cases/provider-assertion").text
    assert "Earlier source comparison preserved" in html
    assert "Original source row was recovered" in html
    if state == "conflicting":
        assert "Original description superseded by recovered evidence" in html


@pytest.mark.parametrize(
    "mutation",
    [
        lambda r: r.update(scientific_signoff=True),
        lambda r: r["source_sha256"].pop("remaining-claim-review"),
        lambda r: r["source_sha256"].update({"fedefl-selections": "0" * 64}),
        lambda r: r["entries"][0].update(previous_document="fedefl-input"),
        lambda r: r["entries"][0]["review"].update(summary_sha256="0" * 64),
        lambda r: r["entries"][0].update(resolved_gaps=["unit-mismatch"]),
        lambda r: r["entries"][0].update(resolved_gaps=["scientific-signoff"]),
        lambda r: r["entries"][0].update(recorded_at="2026-10-14T18:00:00Z"),
        lambda r: r["entries"][0]["review"].update(
            sources=["/curation/evidence/fedefl-selections?pointer=%2F99"]
        ),
        lambda r: r["entries"][0]["facts"][0].update(
            evidence_url="https://example.org/uncaptured"
        ),
        lambda r: r["entries"].append(r["entries"][0].copy()),
    ],
)
def test_invalid_or_overreaching_recovery_fails_explicitly(bundle, mutation):
    path = add_recovery_receipt(bundle, mutation=mutation)
    with pytest.raises(ValueError):
        tool.build(path, {})


def add_application_checks(bundle, *, result="passed", mutation=None):
    """Test-only receipt for separating scoped execution from scientific approval."""
    path, _ = bundle
    register = curation.read_register(path)
    check = dict(
        id="unit-application-probe",
        case_ids=[register.cases[0].id],
        validation=dict(
            label="Test-only bounded application check",
            result=result,
            revision=register.cases[0].revision,
            scope="Selected fixture row only",
            recorded_at="2026-10-13T18:00:00Z",
            evidence_url="/curation/evidence/fedefl-selections?pointer=%2F0",
            note="Mechanism evidence does not validate source quantity interpretation.",
        ),
        expected="The exact source unit remains visible.",
        observed="The source row retains its units; dimensional conflict remains.",
        remaining="Original scientific unit interpretation requires review.",
        sources=["/curation/evidence/fedefl-selections?pointer=%2F0"],
    )
    receipt = dict(
        schema_version=1,
        recorded_at="2026-10-13T18:00:00Z",
        method="Test-only source check",
        source_sha256={d.id: d.sha256 for d in register.documents},
        scientific_signoff=False,
        case_sha256={
            register.cases[0].id: provenance.case_identity_digest(register.cases[0])
        },
        checks=[check],
    )
    if mutation:
        mutation(receipt)
    raw = json.dumps(receipt).encode()
    filename = "application-checks.json"
    (path.parent / "sources" / filename).write_bytes(raw)
    payload = json.loads(path.read_bytes())
    payload["documents"].append(
        dict(
            id="quantity-application-checks",
            title="Test application evidence",
            filename=filename,
            sha256=tool.sha(raw),
            generation="Test-only rejection fixture",
            origin_url=None,
        )
    )
    path.write_text(json.dumps(payload))
    return path


@pytest.mark.parametrize("result", ["passed", "failed", "blocked"])
def test_application_checks_preserve_independent_conflicts_and_cannot_approve(
    bundle, result
):
    path = add_application_checks(bundle, result=result)
    source = curation.read_register(path).cases[0]
    audit = tool.build(path, {})
    case = audit.cases[0]
    assert case.applications[0].validation.result == result
    assert any(g.code == "unit-mismatch" for g in case.gaps)
    assert (
        source.stage == curation.Stage.RECORDED
        and not source.signoffs
        and not source.validations
    )
    assert any(g.code == "application-unit-application-probe" for g in case.gaps) == (
        result != "passed"
    )
    path.with_name("provenance-audit.json").write_bytes(
        TypeAdapter(provenance.ProvenanceAudit).dump_json(audit)
    )
    app = create_app(
        database_path=path.parent / "absent.sqlite3", docs_path=ROOT / "docs"
    )
    app.config["CURATION_REGISTER_PATH"] = path
    html = app.test_client().get("/curation/cases/provider-assertion").text
    assert "Quantity application checks" in html and "Selected fixture row only" in html
    assert "Original scientific unit interpretation requires review" in html
    assert "No revision-specific scientific review" in html


@pytest.mark.parametrize(
    "mutation",
    [
        lambda r: r.update(scientific_signoff=True),
        lambda r: r["checks"][0].update(case_ids=[]),
        lambda r: r.update(case_sha256={}),
        lambda r: r["case_sha256"].update({"provider-assertion": "0" * 64}),
        lambda r: r["case_sha256"].update({"absent-case": "0" * 64}),
        lambda r: r["checks"][0].update(case_ids=["absent-case"]),
        lambda r: r["checks"][0].update(
            case_ids=["provider-assertion", "provider-assertion"]
        ),
        lambda r: r["source_sha256"].update({"fedefl-selections": "0" * 64}),
        lambda r: r["source_sha256"].pop("fedefl-selections"),
        lambda r: r["checks"][0].update(sources=["https://example.org/uncaptured"]),
        lambda r: r["checks"][0]["validation"].update(
            evidence_url="/curation/evidence/fedefl-selections?pointer=%2F99"
        ),
        lambda r: r["checks"][0].update(remaining=""),
        lambda r: r["checks"][0]["validation"].update(
            recorded_at="2026-10-14T18:00:00Z"
        ),
        lambda r: r["checks"].append(r["checks"][0].copy()),
    ],
)
def test_application_check_rejects_missing_identity_evidence_or_limits(
    bundle, mutation
):
    path = add_application_checks(bundle, mutation=mutation)
    with pytest.raises(ValueError):
        tool.build(path, {})


def test_application_evidence_cannot_follow_rebound_original_case(bundle):
    path = add_application_checks(bundle)
    payload = json.loads(path.read_bytes())
    payload["cases"][0]["reference_id"] = "another-original-source"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="case identity changed"):
        tool.build(path, {})


def supplement_fixture(bundle, mutation=None):
    """Isolated rejection controls; no synthetic case enters the real register."""
    path, _ = bundle
    payload = json.loads(path.read_bytes())
    fact_value = "A preserved source observation, without approval."
    source_raw = json.dumps({"observation": fact_value}).encode()
    source_id = "test-supplement-source"
    source_url = f"/curation/evidence/{source_id}?pointer=%2Fobservation"
    receipt = dict(
        schema_version=1,
        recorded_at="2026-10-14T16:00:00Z",
        method="Test-only exact source binding",
        source_sha256={source_id: tool.sha(source_raw)},
        case_sha256={
            "provider-assertion": provenance.case_identity_digest(
                curation.read_register(path).cases[0]
            )
        },
        scientific_signoff=False,
        entries=[dict(
            id="provider-assertion",
            facts=[dict(label="Recovered source fact", value=fact_value,
                        evidence_url=source_url)],
            gaps=[dict(code="test-remaining-scope", kind="scope",
                       title="Scope remains unresolved", detail="Test-only gap",
                       action="Receive the actual native binding",
                       evidence_urls=[source_url])],
            sources=[source_url],
        )],
    )
    if mutation:
        mutation(receipt)
    for identifier, raw in [
        (source_id, source_raw),
        ("historical-ipcc-evidence-supplement", json.dumps(receipt).encode()),
    ]:
        filename = identifier + ".json"
        (path.parent / "sources" / filename).write_bytes(raw)
        payload["documents"].append(dict(
            id=identifier, title="Synthetic supplement rejection control",
            filename=filename, sha256=tool.sha(raw),
            generation="Isolated test fixture", origin_url=None,
        ))
    path.write_text(json.dumps(payload))
    return path


def test_source_supplement_preserves_original_gaps_and_cannot_approve(bundle):
    path, before = bundle
    original_case = curation.read_register(path).cases[0]
    path = supplement_fixture(bundle)
    result = tool.build(path, {}).cases[0]
    assert result.facts[:-1] == before.cases[0].facts
    assert result.facts[-1].label == "Recovered source fact"
    assert result.gaps[:-1] == before.cases[0].gaps
    assert result.gaps[-1].code == "test-remaining-scope"
    assert result.claims == before.cases[0].claims
    assert result.capture == before.cases[0].capture
    assert result.label == "Conflicting evidence"
    assert curation.read_register(path).cases[0] == original_case
    assert original_case.stage == curation.Stage.RECORDED
    assert not original_case.signoffs and original_case.reported_by is None


@pytest.mark.parametrize("mutation", [
    lambda r: r.update(schema_version=2),
    lambda r: r.update(scientific_signoff=True),
    lambda r: r["source_sha256"].update({"test-supplement-source": "0" * 64}),
    lambda r: r["source_sha256"].clear(),
    lambda r: r["case_sha256"].clear(),
    lambda r: r["case_sha256"].update({"provider-assertion": "0" * 64}),
    lambda r: r["case_sha256"].update({"unregistered-case": "0" * 64}),
    lambda r: r["entries"][0].update(id="unregistered-case"),
    lambda r: r["entries"].append(r["entries"][0].copy()),
    lambda r: r["entries"][0].update(facts=[]),
    lambda r: r["entries"][0].update(sources=[]),
    lambda r: r["entries"][0]["facts"][0].update(value="Unsupported replacement"),
    lambda r: r["entries"][0]["facts"][0].update(
        evidence_url="/curation/evidence/test-supplement-source"),
    lambda r: r["entries"][0]["facts"][0].update(
        evidence_url="/curation/evidence/test-supplement-source?pointer=%2Fmissing"),
    lambda r: r["entries"][0]["facts"][0].update(
        evidence_url="https://example.org/uncaptured"),
    lambda r: r["entries"][0]["gaps"][0].update(
        evidence_urls=["https://example.org/uncaptured"]),
    lambda r: r["entries"][0].update(resolved_gaps=["unit-mismatch"]),
])
def test_source_supplement_rejects_changed_or_unbound_evidence(bundle, mutation):
    path = supplement_fixture(bundle, mutation)
    with pytest.raises((ValueError, KeyError)):
        tool.build(path, {})


def test_source_supplement_cannot_follow_rebound_original_case(bundle):
    path = supplement_fixture(bundle)
    payload = json.loads(path.read_bytes())
    payload["cases"][0]["original_record"] = "A changed assertion"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="Supplement case identity changed"):
        tool.build(path, {})


def upstream_issue_fixture(bundle, mutation=None):
    """Isolated custody tests; these records never enter the review register."""
    path, _ = bundle
    report = dict(number=388, user=dict(login="cmutel"),
                  created_at="2026-10-13T20:48:11Z", body="Unit resolution needs a prefix guard",
                  locked=False)
    payload = json.loads(path.read_bytes())
    case = payload["cases"][0]
    case.update(collection="Upstream issue reports", reported_by="cmutel",
                reported_at=report["created_at"], original_record=json.dumps(report),
                evidence=[dict(label="Original issue report", kind="Captured report",
                    url="/curation/evidence/unit-issue?pointer=%2Freport")])
    if mutation:
        mutation(case, report)
    raw = json.dumps(dict(report=report)).encode()
    (path.parent / "sources" / "unit-issue.json").write_bytes(raw)
    payload["documents"].append(dict(id="unit-issue", title="Isolated custody control",
        filename="unit-issue.json", sha256=tool.sha(raw), generation="Isolated test only",
        origin_url=None))
    path.write_text(json.dumps(payload))
    return path


def test_upstream_report_custody_preserves_reporter_and_separate_native_gap(bundle):
    audit = tool.build(upstream_issue_fixture(bundle), {})
    case = audit.cases[0]
    assert case.capture == provenance.CheckState.MATCHED
    assert case.kind == "Upstream issue report"
    assert any(f.label == "Recorded issue reporter" and f.value == "cmutel" for f in case.facts)
    assert {"upstream-build-unreceived", "scientific-basis", "scientific-signoff"} <= {
        gap.code for gap in case.gaps}


@pytest.mark.parametrize("mutation", [
    lambda c, r: c.update(reported_by="Different reporter"),
    lambda c, r: c.update(reported_at="2026-10-13T20:48:12Z"),
    lambda c, r: c.update(original_record=json.dumps(dict(r, body="Changed claim"))),
    lambda c, r: c.update(original_record=json.dumps(dict(r, locked=0))),
    lambda c, r: c.update(original_record=json.dumps(dict(r, number=388.0))),
])
def test_upstream_report_cannot_supply_changed_payload_or_attribution(bundle, mutation):
    case = tool.build(upstream_issue_fixture(bundle, mutation), {}).cases[0]
    assert case.capture == provenance.CheckState.MISMATCH
    assert any(g.code == "capture-mismatch" for g in case.gaps)


def test_upstream_report_date_without_timezone_is_not_accepted(bundle):
    path = upstream_issue_fixture(bundle, lambda c, r: r.update(created_at="2026-10-13T20:48:11"))
    with pytest.raises(ValueError, match="dates must carry a timezone"):
        tool.build(path, {})
