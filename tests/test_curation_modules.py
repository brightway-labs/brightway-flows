"""Inventory completeness and honest actual/proposed/version relationships."""

import ast
import json
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlencode

from brightway_flows.domain.rulings import CURATED_FILES, RULINGS
from brightway_flows.webapps.app import create_app
from brightway_flows.webapps.app.curation import (
    Implementation,
    ImplementationRole,
    read_register,
)
from brightway_flows.webapps.app.curation_modules import (
    module_catalogue,
    modules_for_cases,
    module_sources,
    imported_modules,
    test_references as discover_tests,
)

ROOT = Path(__file__).resolve().parents[1]


def test_all_rulings_and_inputs_preserve_every_description():
    modules = module_catalogue(ROOT, [])
    by_id = {m.id: m for m in modules}
    for ruling in RULINGS:
        assert ruling.applied_by in by_id
    for record in CURATED_FILES:
        assert record.applied_by in by_id
        if record.applied_by in by_id:
            matches = [
                i
                for i in by_id[record.applied_by].inputs
                if i.pattern == record.filename
            ]
            assert len(matches) == 1
            assert matches[0].description == record.decides
            assert matches[0].named_by_manifest == record.named_by_manifest
            assert matches[0].files == tuple(
                str(p.relative_to(ROOT))
                for p in sorted(
                    (ROOT / "src/brightway_flows/data").glob(record.filename)
                )
            )


def test_every_default_class_keeps_order_docs_and_classification_without_importing():
    tree = ast.parse(
        (ROOT / "src/brightway_flows/transformers/__init__.py").read_text()
    )
    chain = next(
        n.value.elts
        for n in tree.body
        if isinstance(n, ast.Assign)
        and any(
            isinstance(t, ast.Name) and t.id == "DEFAULT_TRANSFORMERS"
            for t in n.targets
        )
    )
    steps = sorted(
        (s for m in module_catalogue(ROOT, []) for s in m.steps), key=lambda s: s.order
    )
    assert [s.name for s in steps] == [n.id for n in chain]
    assert [s.order for s in steps] == list(range(1, len(chain) + 1))
    assert all(s.description and isinstance(s.answers_per_flow, bool) for s in steps)
    # This reader also has curated data: neither description is overwritten.
    match = next(
        m for m in module_catalogue(ROOT, []) if m.id.endswith("consensus_match")
    )
    assert match.documentation and match.steps[0].description
    overlapping = [m for m in module_catalogue(ROOT, []) if m.inputs and m.steps]
    assert overlapping
    assert all(m.documentation and m.steps[0].description for m in overlapping)
    assert any(p.endswith("/transformer.py") for p in module_sources(ROOT, match))


def test_recorded_versions_deduplicate_without_collapsing_revisions_or_roles():
    case = read_register(ROOT / "docs/curation/register.json").cases[0]
    path = "scripts/correction.py"
    first = Implementation(
        "Code",
        "https://example.org/team/repo/blob/" + "a" * 40 + "/" + path,
        ImplementationRole.HISTORICAL,
        "a" * 40,
        path,
    )
    second = replace(
        first, revision="b" * 40, url=first.url.replace("a" * 40, "b" * 40)
    )
    cases = [
        replace(
            case,
            id="one",
            modules=[],
            proposed_modules=["brightway_flows.lcia.rulings"],
            implementations=[first],
        ),
        replace(
            case,
            id="two",
            modules=[],
            proposed_modules=[],
            implementations=[first, second],
        ),
    ]
    modules = module_catalogue(ROOT, cases)
    local = next(m for m in modules if m.versions)
    assert len(local.versions) == 2
    assert len(local.cases) == 2
    assert all(len(v.references) == 1 for v in local.versions)
    proposed = next(m for m in modules if m.id == "brightway_flows.lcia.rulings")
    assert not proposed.cases and len(proposed.proposed_cases) == 1
    uses = modules_for_cases(modules, [cases[0]])
    assert sum(len(u.versions) for u in uses) == 1
    assert all(c.id == "one" for u in uses for v in u.versions for c in v.cases)
    assert sum(u.actual for u in uses) == 1
    assert sum(u.proposed for u in uses) == 1
    # A similarly named file in another repository must remain separate.
    third = replace(first, url=first.url.replace("/team/repo/", "/another/repo/"))
    mixed = module_catalogue(ROOT, [replace(cases[0], implementations=[first, third])])
    assert len([m for m in mixed if m.versions]) == 2


def test_proposed_cases_are_browsable_and_survive_filter_roundtrip(tmp_path):
    register = read_register(ROOT / "docs/curation/register.json")
    case = next(c for c in register.cases if c.modules)
    module = case.modules[0]
    payload = json.loads((ROOT / "docs/curation/register.json").read_text())
    row = next(c for c in payload["cases"] if c["id"] == case.id)
    row["proposed_modules"] = [module]
    row["modules"] = []
    row["stage"] = "recorded"
    path = tmp_path / "register.json"
    path.write_text(json.dumps(payload))
    app = create_app(database_path=tmp_path / "absent.sqlite3", docs_path=ROOT / "docs")
    app.config["CURATION_REGISTER_PATH"] = path
    client = app.test_client()
    response = client.get(
        "/curation/?" + urlencode(dict(view="all", module=module, relation="proposed"))
    )
    assert response.status_code == 200
    assert case.title.encode() in response.data
    assert f'name="module" value="{module}"'.encode() in response.data
    assert b'name="relation" value="proposed"' in response.data
    assert client.get("/curation/?module=missing-module").status_code == 404


def test_full_source_download_is_limited_to_catalogued_files(tmp_path):
    app = create_app(database_path=tmp_path / "absent.sqlite3", docs_path=ROOT / "docs")
    client = app.test_client()
    module = "brightway_flows.transformers.consensus_match"
    path = "src/brightway_flows/transformers/consensus_match/transformer.py"
    response = client.get(
        f"/curation/modules/{module}/source?" + urlencode(dict(path=path))
    )
    assert response.status_code == 200
    assert response.data == (ROOT / path).read_bytes()
    assert response.headers["Content-Disposition"].startswith("attachment;")
    for forbidden in (
        "../../private.txt",
        "AGENTS.md",
        "src/brightway_flows/webapps/app/curation.py",
    ):
        assert (
            client.get(
                f"/curation/modules/{module}/source?" + urlencode(dict(path=forbidden))
            ).status_code
            == 404
        )
    assert client.get("/curation/modules/unknown/source").status_code == 404


def test_discovered_test_sources_are_not_execution_receipts():
    module = next(
        m for m in module_catalogue(ROOT, []) if m.id.endswith("unit_normalization")
    )
    tests = discover_tests(ROOT, module)
    assert tests and all((ROOT / p).is_file() for p in tests)
    assert not module.cases  # Discovery does not create cases or validation.


def test_transformer_exposes_separate_registered_readers():
    catalogue = module_catalogue(ROOT, [])
    module = next(m for m in catalogue if m.id.endswith("apply_structure_corrections"))
    dependencies = imported_modules(ROOT, module, catalogue)
    assert any(m.inputs for m in dependencies)
    assert all(m.id != module.id for m in dependencies)
