"""The original findings and upstream cases remain reachable through one register."""

import json
import re
from dataclasses import replace
from html import unescape
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from brightway_flows.webapps.app import create_app, curation, documentation

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"


@pytest.fixture
def app(tmp_path):
    return create_app(database_path=tmp_path / "absent.sqlite3", docs_path=DOCS)


@pytest.fixture
def register():
    return curation.read_register(DOCS / "curation/register.json")


def test_every_findings_article_keeps_a_single_class_and_its_original_body(
    app, register
):
    client = app.test_client()
    for path in (DOCS / "findings").glob("*.md"):
        if path.name == "index.md":
            continue
        slug = path.relative_to(DOCS).with_suffix("").as_posix()
        linked = curation.cases_for_document(register, DOCS, slug)
        classes = [c for c in linked if c.origin == curation.Origin.FINDING_CLASS]
        assert len(classes) == 1, slug
        response = client.get("/docs/" + slug)
        assert response.status_code == 200
        assert f"/curation/cases/{classes[0].id}" in response.text
        assert documentation.load_page(DOCS, slug).html in response.text
        detail = client.get(f"/curation/cases/{classes[0].id}")
        assert detail.status_code == 200
        assert "/docs/" + slug in detail.text
        assert "No executed validation receipt" not in detail.text
        assert "finding-class record indexes the documentation" in detail.text


def test_original_upstream_cases_are_visible_with_attribution_and_withdrawal(
    app, register
):
    expected = [c for c in register.cases if c.origin != curation.Origin.FINDING_CLASS]
    client = app.test_client()
    overview = client.get("/docs/findings").text
    browser = client.get("/curation/?document=findings/index&view=individual").text
    assert {c.id for c in expected} == set(
        re.findall(r'data-case-row="([^"]+)"', browser)
    )
    for case in expected:
        assert f"/curation/cases/{case.id}" in overview
        detail = client.get(f"/curation/cases/{case.id}")
        assert detail.status_code == 200
        for proposal in case.proposals:
            assert proposal.url in detail.text
            assert proposal.author in detail.text
        for receipt in case.validations:
            assert (
                receipt.revision in detail.text or receipt.revision[:12] in detail.text
            )
            assert receipt.evidence_url in detail.text
    assert (
        "Withdrawn" in overview
        and "Preserve the withdrawn vanadium interpretation" in overview
    )
    assert "Proposal in review" in overview and "jsvgoncalves" in overview
    assert "Individual cases" in browser


def test_documentation_scope_survives_filters_sort_and_reset(app):
    html = (
        app.test_client()
        .get("/curation/?document=findings/units.md&view=individual&q=water")
        .text
    )
    assert 'name="document" value="findings/units"' in html
    assert 'data-case-row="bafu-water-units"' in html
    assert 'data-case-row="finding-units"' not in html
    for destination in re.findall(r'href="([^"]+)"', html):
        args = parse_qs(urlsplit(unescape(destination)).query)
        if args.get("sort") == ["stage"]:
            assert args["document"] == ["findings/units"]
            assert args["view"] == ["individual"]
            assert args["q"] == ["water"]
    clear = re.search(r'class="curation-clear"[^>]*href="([^"]+)"', html).group(1)
    assert parse_qs(urlsplit(unescape(clear)).query)["document"] == ["findings/units"]
    assert (
        app.test_client().get("/curation/?document=missing-document").status_code == 404
    )


def test_case_relationships_follow_explicit_pages_and_not_title_similarity(register):
    case = next(c for c in register.cases if c.id == "bafu-water-units")
    cited = case.evidence[0]
    aliased = replace(
        case, evidence=[replace(cited, url="/docs/findings/units.md#water")]
    )
    assert curation.documentation_slugs(aliased, DOCS) == ("findings/units",)
    for url in (
        "https://example.org/docs/findings/units",
        "/docs/findings/not-present",
        "/docs/curation/register.json",
    ):
        other = replace(case, evidence=[replace(cited, url=url)])
        assert not curation.documentation_slugs(other, DOCS)
    assert not curation.cases_for_document(
        replace(register, cases=[aliased]), DOCS, "findings/names-and-numbers"
    )


def test_docs_use_selected_register_and_distinguish_missing_from_invalid(app, tmp_path):
    data = json.loads((DOCS / "curation/register.json").read_text())
    data["cases"] = [c for c in data["cases"] if c["id"] == "bafu-water-units"]
    path = tmp_path / "local.json"
    path.write_text(json.dumps(data))
    app.config["CURATION_REGISTER_PATH"] = path
    html = app.test_client().get("/docs/findings/units").text
    assert "1 registered individual case" in html
    assert "Finding-class record" not in html
    assert (
        app.test_client()
        .get("/curation/?document=findings/units&view=individual")
        .data.count(b"data-case-row=")
        == 1
    )
    path.write_text('{"schema_version": 99}')
    failed = app.test_client().get("/docs/findings/names-and-numbers")
    assert failed.status_code == 200
    assert "Curation links are temporarily unavailable" in failed.text
    assert (
        documentation.load_page(DOCS, "findings/names-and-numbers").html in failed.text
    )
    path.unlink()
    absent = app.test_client().get("/docs/findings/names-and-numbers")
    assert (
        absent.status_code == 200
        and "Curation links are temporarily unavailable" not in absent.text
    )


def test_class_with_its_own_proposal_retains_full_record_view(app, tmp_path):
    data = json.loads((DOCS / "curation/register.json").read_text())
    finding = next(c for c in data["cases"] if c["id"] == "finding-units")
    finding["proposals"] = next(
        c for c in data["cases"] if c["id"] == "bafu-water-units"
    )["proposals"]
    path = tmp_path / "class-proposal-fixture.json"
    path.write_text(json.dumps(data))
    app.config["CURATION_REGISTER_PATH"] = path
    html = app.test_client().get("/curation/cases/finding-units").text
    assert finding["proposals"][0]["url"] in html
    assert "Proposals &amp; discussion" in html or "Proposals & discussion" in html


def test_registered_test_and_expectation_paths_exist(register):
    for case in register.cases:
        for path in [*case.test_paths, *case.expectation_paths]:
            assert (ROOT / path).is_file(), (case.id, path)
