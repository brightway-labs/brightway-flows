"""Read-only module inventory and case relationships. Never imports executable steps."""

from __future__ import annotations

import ast
import hashlib
import subprocess
from collections import defaultdict
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from urllib.parse import urlsplit

from brightway_flows.domain.rulings import RULINGS, VOCABULARIES, REFERENCE_DATA
from brightway_flows.webapps.app.curation import (
    Case,
    Document,
    Implementation,
    ImplementationRole,
)


class InputKind(StrEnum):
    RULING = "Ruling"
    VOCABULARY = "Vocabulary"
    REFERENCE = "Reference data"


class ModuleKind(StrEnum):
    TRANSFORMER = "Transformer"
    RULING = "Curated decisions"
    LINKED = "Case-linked code"
    RECORDED = "Recorded source code"
    INPUT = "Supporting inputs"


@dataclass(frozen=True)
class Step:
    name: str
    order: int
    description: str
    answers_per_flow: bool | None


@dataclass(frozen=True)
class CuratedInput:
    pattern: str
    kind: InputKind
    description: str
    named_by_manifest: bool
    files: tuple[str, ...]


@dataclass(frozen=True)
class Version:
    revision: str
    role: ImplementationRole
    references: tuple[Implementation, ...]
    cases: tuple[Case, ...]

    @property
    def latest_code_attribution(self):
        return max(
            (r.authored_at for r in self.references if r.authored_at), default=None
        )

    @property
    def test_evidence(self):
        return tuple(
            {
                e.url: e
                for c in self.cases
                for e in c.evidence
                if e.kind == "Test source"
            }.values()
        )

    @property
    def authors(self):
        return tuple(sorted({r.author for r in self.references if r.author}))


@dataclass(frozen=True)
class Module:
    id: str
    title: str
    kind: ModuleKind
    summary: str
    path: str
    cases: tuple[Case, ...]
    proposed_cases: tuple[Case, ...] = ()
    versions: tuple[Version, ...] = ()
    steps: tuple[Step, ...] = ()
    inputs: tuple[CuratedInput, ...] = ()
    documentation: str = ""
    source_scope: str = "Consensus Flows checkout"

    @property
    def order(self):
        return self.steps[0].order if self.steps else None

    @property
    def decision_files(self):
        return tuple(i.pattern for i in self.inputs if i.kind == "Ruling")

    @property
    def resolved_decision_files(self):
        return tuple(
            sorted({f for i in self.inputs if i.kind == "Ruling" for f in i.files})
        )

    @property
    def related_cases(self):
        return tuple({c.id: c for c in (*self.cases, *self.proposed_cases)}.values())


def _module_path(root, name):
    stem = "src/" + name.replace(".", "/")
    return (
        stem + "/__init__.py"
        if (root / stem / "__init__.py").is_file()
        else stem + ".py"
    )


def _tree(root, path):
    resolved = (root / path).resolve()
    if not resolved.is_relative_to(root.resolve()) or not resolved.is_file():
        return None
    return ast.parse(resolved.read_text())


def _class_node(root, module, name):
    """Follow an explicit package re-export, without executing its imports."""
    tree = _tree(root, _module_path(root, module))
    if tree is None:
        return None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
        if (
            isinstance(node, ast.ImportFrom)
            and node.module
            and node.module.startswith(module + ".")
        ):
            for alias in node.names:
                if (alias.asname or alias.name) == name:
                    return _class_node(root, node.module, alias.name)
    return None


def _step(root, module, name, order):
    node = _class_node(root, module, name)
    per_flow = None
    if node:
        for statement in node.body:
            if (
                isinstance(statement, ast.Assign)
                and any(
                    isinstance(t, ast.Name) and t.id == "answers_per_flow"
                    for t in statement.targets
                )
                and isinstance(statement.value, ast.Constant)
            ):
                per_flow = (
                    statement.value.value
                    if isinstance(statement.value.value, bool)
                    else None
                )
    return Step(name, order, ast.get_docstring(node) or "" if node else "", per_flow)


def _source_identity(implementation, documents):
    url = urlsplit(implementation.url)
    document = next(
        (d for d in documents if url.path == f"/curation/evidence/{d.id}"), None
    )
    origin = (
        document.origin_url if document and document.origin_url else implementation.url
    )
    for separator in ("/-/blob/", "/blob/"):
        if separator in origin:
            return origin.split(separator, 1)[0]
    # An unproven origin is kept separate, even when paths happen to match.
    return url.path


def module_catalogue(
    root: Path, cases: list[Case], documents: list[Document] = ()
) -> tuple[Module, ...]:
    """All registered rulings, default steps, and actual/proposed case code links.

    Local versions are grouped by source origin and file; their revisions and
    roles remain distinct. A proposed destination never becomes an implementation.
    """
    actual, proposed = defaultdict(list), defaultdict(list)
    for case in cases:
        for name in case.modules:
            actual[name].append(case)
        for name in case.proposed_modules:
            proposed[name].append(case)
    names = (
        set(actual)
        | set(proposed)
        | {r.applied_by for r in (*RULINGS, *VOCABULARIES, *REFERENCE_DATA)}
    )
    steps = defaultdict(list)
    tree = _tree(root, "src/brightway_flows/transformers/__init__.py")
    if tree:
        imports = {
            a.asname or a.name: (n.module, a.name)
            for n in tree.body
            if isinstance(n, ast.ImportFrom)
            for a in n.names
        }
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "DEFAULT_TRANSFORMERS"
                for t in node.targets
            ):
                for order, item in enumerate(node.value.elts, 1):
                    module, name = imports[item.id]
                    names.add(module)
                    steps[module].append(_step(root, module, name, order))
    modules = []
    for name in sorted(names):
        path = _module_path(root, name)
        tree = _tree(root, path)
        description = ast.get_docstring(tree) or "" if tree else ""
        inputs = tuple(
            CuratedInput(
                r.filename,
                kind,
                r.decides,
                r.named_by_manifest,
                tuple(
                    str(p.relative_to(root))
                    for p in sorted(
                        (root / "src/brightway_flows/data").glob(r.filename)
                    )
                ),
            )
            for kind, entries in (
                (InputKind.RULING, RULINGS),
                (InputKind.VOCABULARY, VOCABULARIES),
                (InputKind.REFERENCE, REFERENCE_DATA),
            )
            for r in entries
            if r.applied_by == name
        )
        summary = (
            description.split("\n\n")[0]
            if description
            else next(
                (i.description for i in inputs),
                "Purpose not documented in this source file.",
            )
        )
        kind = (
            ModuleKind.TRANSFORMER
            if steps[name]
            else ModuleKind.RULING
            if any(i.kind == "Ruling" for i in inputs)
            else ModuleKind.INPUT
            if inputs
            else ModuleKind.LINKED
        )
        modules.append(
            Module(
                name,
                name.rsplit(".", 1)[-1].replace("_", " ").capitalize(),
                kind,
                summary,
                path,
                tuple(actual[name]),
                tuple(proposed[name]),
                steps=tuple(steps[name]),
                inputs=inputs,
                documentation=description,
            )
        )
    recorded = defaultdict(lambda: defaultdict(list))
    for case in cases:
        for implementation in case.implementations:
            source = _source_identity(implementation, documents)
            recorded[(source, implementation.path)][
                (implementation.revision, implementation.role)
            ].append((case, implementation))
    for (source, path), versions in sorted(recorded.items()):
        key = hashlib.sha256(f"{source}\n{path}".encode()).hexdigest()[:20]
        versions = tuple(
            Version(
                revision,
                role,
                tuple(dict.fromkeys(i for _, i in pairs)),
                tuple({c.id: c for c, _ in pairs}.values()),
            )
            for (revision, role), pairs in sorted(versions.items())
        )
        versions = tuple(
            sorted(
                versions,
                key=lambda v: (
                    v.latest_code_attribution.timestamp()
                    if v.latest_code_attribution
                    else float("-inf"),
                    v.revision,
                    v.role,
                ),
                reverse=True,
            )
        )
        linked = tuple({c.id: c for v in versions for c in v.cases}.values())
        modules.append(
            Module(
                "recorded-" + key,
                Path(path).stem.replace("_", " ").capitalize(),
                ModuleKind.RECORDED,
                "Preserved implementation linked by the imported cases. Each code revision and its recorded role are retained.",
                path,
                linked,
                versions=versions,
                source_scope=source,
            )
        )
    return tuple(sorted(modules, key=lambda m: (m.kind, m.title, m.id)))


@dataclass(frozen=True)
class ModuleUse:
    module: Module
    actual: int
    proposed: int
    versions: tuple[Version, ...]


def modules_for_cases(modules, cases):
    """Contextual projection used by both a package and an individual case."""
    wanted = {c.id for c in cases}
    uses = []
    for module in modules:
        actual = sum(c.id in wanted for c in module.cases)
        proposed = sum(c.id in wanted for c in module.proposed_cases)
        if actual or proposed:
            uses.append(
                ModuleUse(
                    module,
                    actual,
                    proposed,
                    tuple(
                        replace(
                            v,
                            cases=tuple(c for c in v.cases if c.id in wanted),
                            references=tuple(
                                dict.fromkeys(
                                    i
                                    for c in v.cases
                                    if c.id in wanted
                                    for i in c.implementations
                                    if i in v.references
                                )
                            ),
                        )
                        for v in module.versions
                        if any(c.id in wanted for c in v.cases)
                    ),
                )
            )
    return tuple(
        sorted(uses, key=lambda u: (not u.actual, not bool(u.versions), u.module.title))
    )


@dataclass(frozen=True)
class SourceHistory:
    revision: str
    author: str
    authored_at: str
    subject: str


def source_history(root, path, revision):
    """Git records code changes; they do not identify scientific reviewers."""
    try:
        result = subprocess.run(
            ["git", "log", revision, "--format=%H%x00%an%x00%aI%x00%s", "--", path],
            cwd=root,
            text=True,
            capture_output=True,
            timeout=5,
            check=True,
        )
        return tuple(
            SourceHistory(*line.split("\0", 3)) for line in result.stdout.splitlines()
        )
    except OSError, subprocess.SubprocessError, ValueError:
        return ()


def module_sources(root, module):
    if module.versions:
        return ()
    path = root / module.path
    paths = sorted(path.parent.rglob("*.py")) if path.name == "__init__.py" else [path]
    return tuple(
        str(p.relative_to(root))
        for p in paths
        if p.is_file() and p.resolve().is_relative_to(root.resolve())
    )


def test_references(root, module):
    """Static references only: not test execution, coverage, or scientific approval."""
    if module.versions:
        return ()
    references = []
    for path in sorted((root / "tests").rglob("*.py")):
        if not path.resolve().is_relative_to(root.resolve()):
            continue
        content = path.read_text()
        try:
            tree = ast.parse(content)
        except SyntaxError:
            continue
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.extend(
                    [node.module, *(node.module + "." + a.name for a in node.names)]
                )
        if any(n == module.id or n.startswith(module.id + ".") for n in imports) or any(
            f in content for f in module.decision_files
        ):
            references.append(str(path.relative_to(root)))
    return tuple(references)


def imported_modules(root, module, catalogue):
    """Direct registered imports, including separate readers of curated files."""
    names = set()
    for path in module_sources(root, module):
        for node in ast.walk(_tree(root, path)):
            if isinstance(node, ast.Import):
                names.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                names.add(node.module)
                names.update(node.module + "." + a.name for a in node.names)
    return tuple(
        m
        for m in catalogue
        if m.id != module.id
        and not m.versions
        and any(n == m.id or n.startswith(m.id + ".") for n in names)
    )
