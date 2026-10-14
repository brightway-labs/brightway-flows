"""Findings, proposals and module provenance, without pipeline or GitHub writes."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import replace
from pathlib import Path

from flask import Blueprint, abort, current_app, g, render_template, request, url_for
from pydantic import TypeAdapter, ValidationError

from brightway_flows.webapps.app import (
    curation,
    documentation,
    curation_modules as inventory,
    curation_provenance as provenance,
    curation_mapping_provenance as mapping,
)
from brightway_flows.webapps.app.sections import REPOSITORY_URL

blueprint = Blueprint("curation", __name__, url_prefix="/curation")


def _register_path():
    return curation.register_path(
        Path(current_app.config["CONSENSUS_DOCS_PATH"]),
        current_app.config.get("CURATION_REGISTER_PATH"),
    )


def _load():
    root = Path(current_app.config["CONSENSUS_DOCS_PATH"])
    try:
        register = curation.read_register(_register_path())
    except ValidationError, ValueError, OSError:
        current_app.logger.warning("Invalid curation register", exc_info=True)
        abort(503, description="The curation register could not be validated.")
    return register, root.parent


@blueprint.errorhandler(503)
def unavailable(error):
    return render_template("curation_empty.html", invalid=True), 503


def _common(register):
    endpoint = request.endpoint or ""
    active = (
        "modules"
        if "module" in endpoint
        else "packages"
        if "package" in endpoint
        else "cases"
    )
    if (
        endpoint == "curation.index"
        and register.packages
        and (not request.args or request.args.get("view") == "packages")
    ):
        active = "packages"
    query = request.args.get("q", "").strip()
    root = Path(current_app.config["CONSENSUS_DOCS_PATH"]).parent
    if not hasattr(g, "curation_catalogue"):
        g.curation_catalogue = inventory.module_catalogue(
            root, register.cases, register.documents
        )
    return dict(
        register=register,
        stages=curation.STAGES,
        stage_enum=curation.Stage,
        browser_view=active,
        navigation_query=query,
        evidence_audit=_audit(register),
        gap_labels=provenance.GAP_LABELS,
        workspace_counts=dict(
            packages=len(curation.review_packages(register)),
            cases=len(register.cases),
            individual=sum(
                c.origin != curation.Origin.FINDING_CLASS for c in register.cases
            ),
            classes=sum(
                c.origin == curation.Origin.FINDING_CLASS for c in register.cases
            ),
            modules=len(g.curation_catalogue),
        ),
        packages_url=url_for(
            "curation.index", **({"view": "packages", "q": query} if query else {})
        ),
        cases_url=url_for(
            "curation.index", view="all", **({"q": query} if query else {})
        ),
        modules_url=url_for("curation.modules", **({"q": query} if query else {})),
    )


def _audit(register):
    if not hasattr(g, "curation_audit"):
        try:
            g.curation_audit = provenance.read_audit(
                _register_path(),
                register,
                Path(current_app.config["CONSENSUS_DOCS_PATH"]).parent,
            )
        except ValueError, OSError:
            current_app.logger.warning("Invalid provenance audit", exc_info=True)
            g.curation_audit = provenance.AuditView(
                None, "Evidence audit could not be validated"
            )
    return g.curation_audit


@blueprint.route("/provenance-audit.json")
def export_audit():
    register, _root = _load()
    if register is None:
        abort(404)
    audit = _audit(register)
    if not audit.cases:
        return current_app.response_class(
            json.dumps({"status": audit.status}),
            status=409,
            mimetype="application/json",
        )
    return current_app.response_class(
        TypeAdapter(provenance.ProvenanceAudit).dump_json(audit.audit, indent=2),
        mimetype="application/json",
    )


@blueprint.route("/mappings/")
def source_mappings():
    """Bounded original records; every row remains reachable by its stable ID."""
    register, root = _load()
    path = mapping.manifest_path(_register_path(), register) if register else None
    if path is None:
        abort(404)
    if not _audit(register).cases:
        abort(503, description="Mapping provenance is stale or unverified.")
    try:
        manifest = mapping.verify_manifest(path, root)
    except ValueError, OSError:
        abort(503, description="Mapping provenance could not be verified.")
    case_id = request.args.get("case", "")
    if case_id and case_id not in manifest.case_links:
        abort(404)
    kind = request.args.get("kind", "assertions")
    if kind not in {"assertions", "aliases"}:
        abort(400)
    source = request.args.get("source", "")
    state = request.args.get("status", "")
    identifier = request.args.get("id", "")
    page = max(1, request.args.get("page", 1, type=int))
    payload = manifest.assertions if kind == "assertions" else manifest.aliases
    allowed = set(manifest.case_links[case_id][kind]) if case_id else None
    rows, total = [], 0
    for line in (path.parent / payload.filename).open():
        row = json.loads(line)
        if (allowed is not None and row["id"] not in allowed
                or source and row.get("artifact_id") != source
                or state and row["status"] != state
                or identifier and row["id"] != identifier):
            continue
        total += 1
        if (page - 1) * 50 <= total - 1 < page * 50:
            if kind == "aliases":
                row["source_reading_links"] = [
                    {"label": ref["artifact_id"] + " · " + ref["locator"],
                     "url": url_for("curation.mapping_source_record", artifact=ref["artifact_id"], locator=ref["locator"])}
                    for ref in [row["original"], *row["members"]]
                ]
            else:
                row["source_reading_links"] = [{"label": "Original artifact row",
                    "url": url_for("curation.mapping_source_record", artifact=row["artifact_id"], locator=row["locator"])}]
            rows.append(row)
    if request.args.get("format") == "json":
        return current_app.response_class(json.dumps({"scope": "original assertion/alias traces; no scientific approval or adoption",
            "manifest_sha256": mapping.sha(path.read_bytes()), "total": total,
            "page": page, "rows": rows}, ensure_ascii=False, indent=2), mimetype="application/json")
    args = dict(request.args)
    args.pop("page", None)
    return render_template("curation_mapping_traces.html", **_common(register),
        rows=rows, total=total, page=page, kind=kind, manifest=manifest,
        previous=url_for("curation.source_mappings", **args, page=page - 1) if page > 1 else None,
        next_page=url_for("curation.source_mappings", **args, page=page + 1) if page * 50 < total else None)


@blueprint.route("/source-record/")
def mapping_source_record():
    """Resolve a retained coordinate inside a pinned source artifact only."""
    register, root = _load()
    path = mapping.manifest_path(_register_path(), register) if register else None
    if path is None:
        abort(404)
    if not _audit(register).cases:
        abort(503, description="Mapping provenance is stale or unverified.")
    try:
        manifest = mapping.verify_manifest(path, root)
        artifact = next((a for a in manifest.inputs.artifacts if a.id == request.args.get("artifact")), None)
        if artifact is None:
            abort(404)
        locator = request.args.get("locator", "")
        for coordinate, row in mapping.raw_rows(artifact, path.parent / "source-inputs"):
            if coordinate == locator:
                payload = {"scope": "Original artifact row; scientific applicability unresolved",
                    "artifact": TypeAdapter(mapping.Artifact).dump_python(artifact, mode="json"),
                    "locator": locator, "row_sha256": mapping.sha(mapping.encoded(row)), "original": row}
                return current_app.response_class(json.dumps(payload, indent=2, ensure_ascii=False), mimetype="application/json")
    except ValueError, OSError:
        abort(503, description="Original mapping source could not be verified.")
    abort(404)


@blueprint.after_request
def vary_fragment(response):
    response.vary.add("HX-Request")
    response.vary.add("HX-History-Restore-Request")
    return response


@blueprint.route("/register.json")
def export_register():
    register, _root = _load()
    if register is None:
        abort(404)
    return current_app.response_class(
        TypeAdapter(curation.Register).dump_json(register, indent=2),
        mimetype="application/json",
    )


@blueprint.route("/")
def index():
    register, root = _load()
    if register is None:
        return render_template("curation_empty.html", invalid=False)
    if register.packages and (
        not request.args or request.args.get("view") == "packages"
    ):
        return _packages(register)
    args = {
        key: request.args.get(key, "").strip()
        for key in (
            "q",
            "stage",
            "source",
            "author",
            "view",
            "sort",
            "direction",
            "group",
            "collection",
            "saved",
            "package",
            "module",
            "relation",
            "quality",
            "document",
            "gap",
            "capture",
            "claim",
        )
    }
    if "group" not in request.args:
        args["group"] = "collection" if register.documents else "kind"
    args["view"] = (
        args["view"]
        if args["view"] in ("all", "individual", "classes", "proposals")
        else "all"
    )
    args["sort"] = (
        args["sort"]
        if args["sort"]
        in ("updated", "title", "stage", "author", "source", "quality", "evidence")
        else "updated"
    )
    args["direction"] = "asc" if args["direction"] == "asc" else "desc"
    args["group"] = (
        args["group"]
        if args["group"] in ("kind", "stage", "source", "author", "collection")
        else ""
    )
    selected = curation.filter_cases(
        register.cases,
        query=args["q"],
        stage=args["stage"],
        quality=args["quality"],
        source=args["source"],
        author=args["author"],
        collection=args["collection"],
        view=args["view"],
        sort=args["sort"],
        direction=args["direction"],
    )
    audit = _audit(register)
    if args["gap"]:
        selected = [
            c
            for c in selected
            if c.id in audit.cases
            and any(g.kind == args["gap"] for g in audit.cases[c.id].gaps)
        ]
    if args["capture"]:
        selected = [
            c
            for c in selected
            if c.id in audit.cases and audit.cases[c.id].label == args["capture"]
        ]
    if args["sort"] == "evidence":
        selected.sort(
            key=lambda c: (
                audit.cases[c.id].label if c.id in audit.cases else "Not audited",
                c.id,
            ),
            reverse=args["direction"] == "desc",
        )
    if args["claim"]:
        selected = [
            c
            for c in selected
            if c.id in audit.cases
            and (
                audit.cases[c.id].claims
                if args["claim"] == "compared"
                else audit.cases[c.id].current_review is not None
                and audit.cases[c.id].current_review.state == args["claim"]
            )
        ]
    docs_root = Path(current_app.config["CONSENSUS_DOCS_PATH"])
    selected_document = None
    if args["document"]:
        selected_document = documentation.load_page(docs_root, args["document"])
        if selected_document is None:
            abort(404)
        if selected_document.title == "Overview":
            group = documentation.group_of(
                documentation.navigation(docs_root), selected_document.slug
            )
            if group:
                selected_document = replace(selected_document, title=group.title)
        args["document"] = selected_document.slug
        members = {
            c.id
            for c in curation.cases_for_document(
                register, docs_root, selected_document.slug
            )
        }
        selected = [case for case in selected if case.id in members]
    if args["saved"]:
        wanted = set(args["saved"].split(","))
        selected = [case for case in selected if case.id in wanted]
    selected_package = next(
        (p for p in curation.review_packages(register) if p.id == args["package"]), None
    )
    if args["package"]:
        if selected_package is None:
            abort(404)
        members = set(selected_package.case_ids)
        selected = [case for case in selected if case.id in members]
    selected_module = None
    if args["module"]:
        selected_module = next(
            (
                m
                for m in inventory.module_catalogue(
                    root, register.cases, register.documents
                )
                if m.id == args["module"]
            ),
            None,
        )
        if selected_module is None:
            abort(404)
        linked = (
            selected_module.proposed_cases
            if args["relation"] == "proposed"
            else selected_module.cases
            if args["relation"] == "actual"
            else selected_module.related_cases
        )
        members = {c.id for c in linked}
        selected = [c for c in selected if c.id in members]
    total = len(selected)
    page_count = max(1, (total + 49) // 50)
    page = max(1, min(request.args.get("page", 1, type=int), page_count))
    visible = selected[(page - 1) * 50 : page * 50]
    groups = defaultdict(list)
    for case in visible:
        key = {
            "kind": "Finding classes"
            if case.origin == curation.Origin.FINDING_CLASS
            else "Individual cases",
            "collection": case.collection,
            "stage": case.stage_label,
            "source": ", ".join(case.sources),
            "author": case.contributor_label,
        }.get(args["group"], "All cases")
        groups[key].append(case)
    if args["group"] == "kind":
        groups = {
            key: groups[key]
            for key in ("Individual cases", "Finding classes")
            if key in groups
        }

    def link(**updates):
        return url_for(
            "curation.index",
            **{k: v for k, v in (args | updates).items() if v or k == "group"},
        )

    def sort_link(key):
        direction = (
            "asc" if args["sort"] != key or args["direction"] == "desc" else "desc"
        )
        return link(sort=key, direction=direction)

    return render_template(
        "curation_index.html",
        **_common(register),
        args=args,
        groups=dict(groups),
        selected_package=selected_package,
        selected_module=selected_module,
        selected_document=selected_document,
        selected=visible,
        matched_count=total,
        page=page,
        page_count=page_count,
        qualities=sorted({case.quality for case in register.cases}),
        capture_labels=sorted({c.label for c in audit.cases.values()}),
        collections=sorted({case.collection for case in register.cases}),
        link=link,
        sort_link=sort_link,
        sources=sorted({source for case in register.cases for source in case.sources}),
        authors=sorted(
            {
                person
                for case in register.cases
                for person in (case.contributors or ("Not recorded",))
            }
        ),
        has_migration_coverage=any(
            d.id == "migration-coverage" for d in register.documents
        ),
    )


@blueprint.route("/cases/<case_id>")
def detail(case_id):
    register, root = _load()
    case = (
        next((c for c in register.cases if c.id == case_id), None) if register else None
    )
    if case is None:
        abort(404)
    docs_root = Path(current_app.config["CONSENSUS_DOCS_PATH"])
    # An index has a shorter reading view. If evidence is later registered on
    # the class itself, retain the full record view so none of it is hidden.
    if case.origin == curation.Origin.FINDING_CLASS and not any(
        (
            case.proposals,
            case.modules,
            case.implementations,
            case.proposed_modules,
            case.test_paths,
            case.expectation_paths,
            case.validations,
            case.signoffs,
            case.adoption,
            case.history,
            case.related_cases,
        )
    ):
        slugs = curation.documentation_slugs(case, docs_root)
        linked_ids = {
            related.id
            for slug in slugs
            for related in curation.cases_for_document(register, docs_root, slug)
            if related.origin != curation.Origin.FINDING_CLASS
        }
        return render_template(
            "curation_finding_class.html",
            **_common(register),
            case=case,
            documented_cases=[c for c in register.cases if c.id in linked_ids],
            source_pages=[documentation.load_page(docs_root, slug) for slug in slugs],
            review_package=next(
                (
                    p
                    for p in curation.review_packages(register)
                    if case.id in p.case_ids
                ),
                None,
            )
            if register.packages
            else None,
        )
    catalogue = inventory.module_catalogue(root, register.cases, register.documents)
    return render_template(
        "curation_detail.html",
        **_common(register),
        case=case,
        module_uses=inventory.modules_for_cases(catalogue, [case]),
        related_cases=[c for c in register.cases if c.id in case.related_cases],
        review_package=next(
            (p for p in curation.review_packages(register) if case.id in p.case_ids),
            None,
        )
        if register.packages
        else None,
        history=sorted(case.history, key=lambda e: e.recorded_at, reverse=True),
        code_url=f"{REPOSITORY_URL}/blob/{case.revision}/",
    )


def _packages(register):
    packages = curation.review_packages(register)
    query = request.args.get("q", "").strip()
    workstream = request.args.get("workstream", "")
    sort = request.args.get("sort", "workstream")
    if sort not in ("workstream", "title", "size"):
        sort = "workstream"
    direction = "desc" if request.args.get("direction") == "desc" else "asc"
    triage = request.args.get("triage", "all")
    gap = request.args.get("gap", "")
    audit = _audit(register)
    if triage not in ("all", "attention", "acknowledged", "split"):
        triage = "all"

    def link(**updates):
        args = (
            dict(
                view="packages",
                q=query,
                workstream=workstream,
                sort=sort,
                direction=direction,
                triage=triage,
                gap=gap,
            )
            | updates
        )
        return url_for("curation.index", **{k: v for k, v in args.items() if v})

    def sort_link(key):
        return link(
            sort=key, direction="desc" if sort == key and direction == "asc" else "asc"
        )

    selected = [
        p
        for p in packages
        if (not workstream or p.workstream == workstream)
        and (not gap or audit.counts(p.case_ids)[gap])
        and (
            not query
            or query.casefold()
            in " ".join((p.title, p.summary, p.decision, p.workstream)).casefold()
        )
    ]
    selected.sort(
        key=lambda p: (
            (len(p.case_ids), p.title)
            if sort == "size"
            else (p.title, p.id)
            if sort == "title"
            else (p.workstream, p.title)
        ),
        reverse=direction == "desc",
    )
    return render_template(
        "curation_packages.html",
        **_common(register),
        packages=selected,
        package_count=len(packages),
        workstreams=Counter(p.workstream for p in packages),
        query=query,
        workstream=workstream,
        sort=sort,
        direction=direction,
        triage=triage,
        gap=gap,
        gap_counts={p.id: audit.counts(p.case_ids) for p in selected},
        link=link,
        sort_link=sort_link,
        revisions={p.id: curation.package_revision(register, p) for p in selected},
        has_migration_coverage=any(
            d.id == "migration-coverage" for d in register.documents
        ),
    )


@blueprint.route("/packages/<package_id>")
def package_detail(package_id):
    register, root = _load()
    package = (
        next(
            (p for p in curation.review_packages(register) if p.id == package_id), None
        )
        if register
        else None
    )
    if package is None:
        abort(404)
    members = set(package.case_ids)
    cases = [c for c in register.cases if c.id in members]
    revision = curation.package_revision(register, package)
    return render_template(
        "curation_package.html",
        **_common(register),
        package=package,
        module_uses=inventory.modules_for_cases(
            inventory.module_catalogue(root, register.cases, register.documents), cases
        ),
        quality_counts=Counter(c.quality for c in cases),
        signoff_counts=Counter(c.signoff_label for c in cases),
        package_gap_counts=_audit(register).counts(package.case_ids),
        revision=revision,
        collections=Counter(c.collection for c in cases),
        sources=sorted({source for c in cases for source in c.sources}),
        cases=sorted(cases, key=lambda c: c.title.casefold())[:8],
        manifest={
            "id": package.id,
            "title": package.title,
            "revision": revision,
            "members": [{"id": c.id, "title": c.title} for c in cases],
        },
    )


@blueprint.route("/modules/")
def modules():
    register, root = _load()
    if register is None:
        return render_template("curation_empty.html", invalid=False)
    catalogue = inventory.module_catalogue(root, register.cases, register.documents)
    query = request.args.get("q", "").strip()
    kind = request.args.get("kind", "")
    linked = request.args.get("linked") == "yes"
    sort = request.args.get("sort", "name")
    if sort not in ("name", "cases", "kind", "decisions"):
        sort = "name"
    direction = "desc" if request.args.get("direction") == "desc" else "asc"

    def link(**updates):
        args = (
            dict(
                q=query,
                kind=kind,
                linked="yes" if linked else "",
                sort=sort,
                direction=direction,
            )
            | updates
        )
        return url_for("curation.modules", **{k: v for k, v in args.items() if v})

    def sort_link(key):
        return link(
            sort=key, direction="desc" if sort == key and direction == "asc" else "asc"
        )

    selected = [
        m
        for m in catalogue
        if (
            not query
            or query.casefold()
            in (
                m.id
                + m.title
                + m.path
                + m.source_scope
                + m.summary
                + " ".join(i.description for i in m.inputs)
            ).casefold()
        )
        and (not kind or m.kind == kind)
        and (not linked or m.related_cases)
    ]
    selected.sort(
        key=lambda m: (
            (len(m.related_cases), m.title)
            if sort == "cases"
            else (len(m.decision_files), m.title)
            if sort == "decisions"
            else (m.kind, m.title)
            if sort == "kind"
            else (m.title, m.id)
        ),
        reverse=direction == "desc",
    )
    return render_template(
        "curation_modules.html",
        **_common(register),
        modules=selected,
        catalogue_count=len(catalogue),
        source_count=sum(bool(m.versions) for m in catalogue),
        version_count=sum(len(m.versions) for m in catalogue),
        step_count=sum(len(m.steps) for m in catalogue),
        ruling_count=sum(i.kind == "Ruling" for m in catalogue for i in m.inputs),
        decision_file_count=len(
            {f for m in catalogue for f in m.resolved_decision_files}
        ),
        kinds=sorted({m.kind for m in catalogue}),
        query=query,
        kind=kind,
        linked=linked,
        sort=sort,
        direction=direction,
        link=link,
        sort_link=sort_link,
    )


@blueprint.route("/modules/<path:module_id>")
def module_detail(module_id):
    register, root = _load()
    if register is None:
        abort(404)
    catalogue = inventory.module_catalogue(root, register.cases, register.documents)
    module = next((m for m in catalogue if m.id == module_id), None)
    if module is None:
        abort(404)
    related = {c.id for c in module.related_cases}
    return render_template(
        "curation_module.html",
        **_common(register),
        module=module,
        module_gap_counts=_audit(register).counts(related),
        imported_modules=inventory.imported_modules(root, module, catalogue),
        source=curation.source_file(root, module.path) if not module.versions else None,
        source_paths=inventory.module_sources(root, module),
        tests=inventory.test_references(root, module),
        source_history=inventory.source_history(
            root, module.path, register.source_revision
        )
        if not module.versions
        else (),
        packages=[
            p
            for p in curation.review_packages(register)
            if related.intersection(p.case_ids)
        ],
        code_url=f"{REPOSITORY_URL}/blob/{register.source_revision}/",
    )


@blueprint.route("/modules/<module_id>/source")
def module_source(module_id):
    register, root = _load()
    if register is None:
        abort(404)
    module = next(
        (
            m
            for m in inventory.module_catalogue(
                root, register.cases, register.documents
            )
            if m.id == module_id
        ),
        None,
    )
    if module is None or module.versions:
        abort(404)
    path = request.args.get("path", module.path)
    allowed = {
        *inventory.module_sources(root, module),
        *(f for i in module.inputs for f in i.files),
    }
    if path not in allowed:
        abort(404)
    resolved = (root / path).resolve()
    if not resolved.is_relative_to(root.resolve()) or not resolved.is_file():
        abort(404)
    return current_app.response_class(
        resolved.read_bytes(),
        mimetype="text/plain",
        headers={
            "Content-Disposition": f'attachment; filename="{resolved.name}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@blueprint.route("/evidence/<document_id>")
def evidence(document_id):
    register, _root = _load()
    document = (
        next((d for d in register.documents if d.id == document_id), None)
        if register
        else None
    )
    if document is None:
        abort(404)
    directory = (_register_path().parent / "sources").resolve()
    path = (directory / document.filename).resolve()
    if not path.is_relative_to(directory) or not path.is_file():
        abort(404)
    try:
        raw = path.read_bytes()
        content = raw.decode("utf-8")
    except OSError, UnicodeDecodeError:
        abort(503, description="The evidence snapshot could not be read.")
    if hashlib.sha256(raw).hexdigest() != document.sha256:
        abort(
            503,
            description="The evidence snapshot no longer matches its recorded hash.",
        )
    if request.args.get("download") == "1":
        return current_app.response_class(
            raw,
            mimetype="text/plain",
            headers={
                "Content-Disposition": f'attachment; filename="{path.name}"',
                "X-Content-Type-Options": "nosniff",
            },
        )
    pointer = request.args.get("pointer", "")
    if pointer:
        try:
            if not pointer.startswith("/"):
                raise ValueError("Expected a JSON pointer")
            value = json.loads(content)
            for part in pointer[1:].split("/"):
                part = part.replace("~1", "/").replace("~0", "~")
                value = (
                    value[int(part)]
                    if isinstance(value, list) and part.isdecimal()
                    else value[part]
                )
            content = json.dumps(value, indent=2, ensure_ascii=False)
        except ValueError, KeyError, IndexError, TypeError:
            abort(404)
    start = max(1, request.args.get("line", 1, type=int))
    end = max(start, min(start + 399, request.args.get("end", start + 399, type=int)))
    lines = content.splitlines()
    return render_template(
        "curation_evidence.html",
        **_common(register),
        document=document,
        lines=list(enumerate(lines[start - 1 : end], start)),
        total_lines=len(lines),
        pointer=pointer,
        start=start,
        end=end,
    )
