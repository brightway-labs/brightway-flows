"""Live browsing must preserve the same records, scope and URLs as ordinary GETs."""

import hashlib
import json
import re
from html import unescape
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from brightway_flows.webapps.app import create_app
from brightway_flows.webapps.app.curation import read_register, review_packages

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src/brightway_flows/webapps/app/static"


@pytest.fixture
def browsing(tmp_path):
    data = json.loads((ROOT / "docs/curation/register.json").read_text())
    data["packages"] = [
        dict(
            id="quantity-review",
            title="Quantity review",
            workstream="Quantities",
            summary="Review quantity scope",
            grouping_rule="Shared quantity question",
            decision="Which quantity is converted?",
            case_ids=[c["id"] for c in data["cases"][:2]],
        )
    ]
    path = tmp_path / "register.json"
    path.write_text(json.dumps(data))
    app = create_app(database_path=tmp_path / "absent.sqlite3", docs_path=ROOT / "docs")
    app.config["CURATION_REGISTER_PATH"] = path
    return app.test_client(), read_register(path)


def links(html):
    return [unescape(value) for value in re.findall(r'href="([^"]+)"', html)]


@pytest.mark.parametrize(
    "route", ["/curation/", "/curation/?view=all", "/curation/modules/"]
)
def test_partial_navigation_returns_same_workspace_without_duplicate_assets(
    browsing, route
):
    client, _register = browsing
    full = client.get(route)
    fragment = client.get(route, headers={"HX-Request": "true"})
    restored = client.get(route, headers={"HX-History-Restore-Request": "true"})
    assert full.status_code == fragment.status_code == restored.status_code == 200
    for response in (full, fragment, restored):
        assert response.data.count(b'id="curation-workspace"') == 1
        assert "HX-Request" in response.vary
        assert "HX-History-Restore-Request" in response.vary
        assert b'id="curation-query"' in response.data
        assert b'hx-trigger="curation-filter, submit"' in response.data
        assert not re.search(r"<button[^>]*>\s*Apply\b", response.text)
    assert b"<!DOCTYPE html>" not in fragment.data
    assert b"<script src=" not in fragment.data
    assert b"<title>" in fragment.data
    assert full.data == restored.data
    full_workspace = (
        full.data.split(b'<div class="curation"', 1)[1].split(b"</main>", 1)[0].strip()
    )
    assert fragment.data.split(b'<div class="curation"', 1)[1].strip() == full_workspace
    assert b'"historyCacheSize":0' in full.data
    assert b'hx-history="false"' in full.data


def test_shared_navigation_keeps_search_and_has_one_active_view(browsing):
    client, _register = browsing
    for route in (
        "/curation/?view=packages&q=water",
        "/curation/?view=all&q=water",
        "/curation/modules/?q=water",
    ):
        html = client.get(route).text
        nav = html.split('<nav class="curation-view-switcher"', 1)[1].split(
            "</nav>", 1
        )[0]
        destinations = links(nav)
        assert len(destinations) == 3
        assert all(
            parse_qs(urlsplit(url).query)["q"] == ["water"] for url in destinations
        )
        assert nav.count('aria-current="page"') == 1


def test_public_register_exposes_unassigned_intake_without_invented_groupings(tmp_path):
    register = read_register(ROOT / "docs/curation/register.json")
    assert register.cases and not register.packages
    app = create_app(database_path=tmp_path / "absent.sqlite3", docs_path=ROOT / "docs")
    client = app.test_client()
    html = client.get("/curation/").text
    nav = html.split('<nav class="curation-view-switcher"', 1)[1].split("</nav>", 1)[0]
    package_url = next(url for url in links(nav) if "view=packages" in url)
    intake = client.get(package_url)
    assert intake.status_code == 200
    assert 'data-package-row="unassigned-cases"' in intake.text
    assert "Cases awaiting grouping" in intake.text
    intake_nav = intake.text.split('<nav class="curation-view-switcher"', 1)[1].split(
        "</nav>", 1
    )[0]
    assert 'aria-current="page"' in intake_nav.split("Review packages", 1)[0]
    detail = client.get("/curation/packages/unassigned-cases")
    assert detail.status_code == 200
    assert all(case.id in detail.text for case in register.cases)
    for case in (register.cases[0], register.cases[-1]):
        assert (
            "/curation/packages/unassigned-cases"
            in client.get(f"/curation/cases/{case.id}").text
        )


def test_quality_filter_sort_and_clear_preserve_case_scope(browsing):
    client, register = browsing
    case = register.cases[0]
    args = dict(
        view="all",
        package="quantity-review",
        quality=case.quality,
        sort="title",
        direction="asc",
        q=case.title,
    )
    html = client.get("/curation/", query_string=args).text
    assert f'data-case-row="{case.id}"' in html
    for destination in links(html):
        query = parse_qs(urlsplit(destination).query)
        if query.get("sort") == ["stage"]:
            assert query["package"] == ["quantity-review"]
            assert query["quality"] == [case.quality]
            assert query["q"] == [case.title]
    clear = re.search(r'class="curation-clear"[^>]*href="([^"]+)"', html).group(1)
    cleared = parse_qs(urlsplit(unescape(clear)).query)
    assert cleared["package"] == ["quantity-review"]
    assert not {"quality", "q", "page"}.intersection(cleared)
    # An unrepresented validation state cannot inherit a different row's quality.
    assert (
        b"data-case-row=" not in client.get("/curation/?view=all&quality=unknown").data
    )


def test_package_sort_preserves_membership_and_all_filters(browsing):
    client, register = browsing
    html = client.get("/curation/?view=packages&sort=size&direction=desc").text
    ids = re.findall(r'data-package-row="([^"]+)"', html)
    packages = {p.id: p for p in review_packages(register)}
    assert set(ids) == set(packages)
    sizes = [len(packages[key].case_ids) for key in ids]
    assert sizes == sorted(sizes, reverse=True)
    filtered = client.get(
        "/curation/?view=packages&q=quantity&workstream=Quantities&triage=attention"
    ).text
    for destination in links(filtered):
        query = parse_qs(urlsplit(destination).query)
        if query.get("sort") == ["size"]:
            assert query["q"] == ["quantity"]
            assert query["workstream"] == ["Quantities"]
            assert query["triage"] == ["attention"]
    assert re.findall(r'data-package-row="([^"]+)"', filtered) == ["quantity-review"]


def test_module_sort_filters_and_empty_state_remain_browsable(browsing):
    client, _register = browsing

    def module_links(direction):
        html = client.get(
            f"/curation/modules/?sort=name&direction={direction}&linked=yes"
        ).text
        body = html.split("<tbody>", 1)[1].split("</tbody>", 1)[0]
        return [url for url in links(body) if url.startswith("/curation/modules/")]

    ascending, descending = module_links("asc"), module_links("desc")
    assert ascending and descending == ascending[::-1]
    empty = client.get(
        "/curation/modules/?q=does-not-exist&kind=Transformer&linked=yes"
    ).text
    assert "No modules match these filters" in empty
    assert 'id="curation-kind"' in empty and 'id="curation-query"' in empty
    for destination in links(empty):
        query = parse_qs(urlsplit(destination).query)
        if query.get("sort") == ["cases"]:
            assert query["q"] == ["does-not-exist"]
            assert query["kind"] == ["Transformer"]
            assert query["linked"] == ["yes"]


def test_vendored_transport_matches_the_pinned_official_release():
    import base64

    checksum = base64.b64encode(
        hashlib.sha384(
            (STATIC / "vendor/htmx/htmx-2.0.11.min.js").read_bytes()
        ).digest()
    ).decode()
    assert (
        checksum == "2OatzQy1H+Zd/IIrjr1TcuDGqLXeHhbooAyJY1KdQMKnr4LZ22k31GBLdYKHmVjg"
    )
    assert (STATIC / "vendor/htmx/LICENSE").read_text().strip()
