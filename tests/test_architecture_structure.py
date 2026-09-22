import ast
import importlib.util
import unittest
from pathlib import Path


class ArchitectureStructureTestCase(unittest.TestCase):
    def test_new_logical_packages_import(self):
        from brightway_flows.application import app as cli_app
        from brightway_flows.integrations import fetch_and_store_pubchem
        from brightway_flows.merge import merge_source_list
        from brightway_flows.webapps.app import create_app

        self.assertIsNotNone(cli_app)
        # Not a re-export: `application.cli` is the CLI. Asserting a shim is
        # importable is what made `merge_ecoinvent` look maintained, and this
        # file says so about that case two tests down (#92).
        self.assertEqual(cli_app.__module__.split(".")[:2], ["typer", "main"])
        self.assertTrue(
            any(
                command.callback.__module__
                == "brightway_flows.application.cli"
                for command in cli_app.registered_commands
            ),
            "application.cli should define the commands, not re-export them",
        )
        self.assertTrue(callable(fetch_and_store_pubchem))
        self.assertTrue(callable(merge_source_list))
        self.assertTrue(callable(create_app))

    def test_the_merge_has_one_entry_point(self):
        """`merge_ecoinvent(version)` went with the report it was named for.

        It resolved a version string into a `SourceList` and handed it to
        `merge_source_list`, so the merge had two entry points and one of them
        could name only ecoinvent. Nothing called it -- this test asserted it was
        callable, which is what made it look maintained (#243).
        """
        import brightway_flows.merge as merge
        import brightway_flows.merge.pipeline as pipeline

        self.assertFalse(hasattr(merge, "merge_ecoinvent"))
        self.assertFalse(hasattr(pipeline, "merge_ecoinvent"))

    def test_removed_unused_modules_not_present(self):
        removed_modules = (
            "brightway_flows.properties",
            "brightway_flows.ion_input_code",
            "brightway_flows.flow_context",
            "brightway_flows.webapp",
            "brightway_flows.merge_pipeline",
            "brightway_flows.generate_context_template",
            "brightway_flows.ec_inventory",
            "brightway_flows.ecoinvent",
            "brightway_flows.chebi",
            "brightway_flows.extract_ef31",
            "brightway_flows.pubchem",
            "brightway_flows.fetch_pubchem_identifiers",
            # #21.  A PubChem record title, one source with no agreement
            # requirement, on 17,942 published labels a run.  Named here rather
            # than only dropped from `DEFAULT_TRANSFORMERS` because the module
            # was importable and re-adding one line would have brought it back.
            "brightway_flows.transformers.pubchem_readable_name",
            # #92.  `application/pipeline.py` re-exported `run_pipeline` in
            # five lines and had no importer anywhere -- src, tests, tools or
            # wsgi.  `brightway_flows.cli` was the real 628-line CLI, with
            # a five-line `application/cli.py` shim over it that this file then
            # asserted was importable; the CLI is now the module in
            # `application/` and the shim is what went.
            "brightway_flows.application.pipeline",
            "brightway_flows.cli",
        )
        for module_name in removed_modules:
            self.assertIsNone(importlib.util.find_spec(module_name))

    def test_there_is_one_webapp(self):
        """Four applications, four ports and 47 shared templates became one.

        Pinned so that a second app package is a deliberate decision rather
        than the path of least resistance. The four each carried their own
        navigation, their own copy of "no data", and their own idea of which
        file to read; three of them had pages that could not render at all.
        """
        webapps = (
            Path(__file__).resolve().parent.parent
            / "src" / "brightway_flows" / "webapps"
        )
        packages = sorted(
            path.name for path in webapps.iterdir()
            if path.is_dir() and (path / "__init__.py").exists()
        )
        self.assertEqual(packages, ["app"])

    def test_the_replaced_apps_are_gone(self):
        """`merge_review` went when `run_report` read the merge tables instead
        of a JSON report per source version; the other four went when the
        consolidated app took over.
        """
        for name in (
            "brightway_flows.webapps.merge_review",
            "brightway_flows.webapps.consensus",
            "brightway_flows.webapps.inputs",
            "brightway_flows.webapps.etl_review",
            "brightway_flows.webapps.run_report",
            "brightway_flows.webapps.core",
        ):
            with self.subTest(name):
                self.assertIsNone(importlib.util.find_spec(name))


SRC = Path(__file__).resolve().parent.parent / "src" / "brightway_flows"


def _imported_modules(tree: ast.AST) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            modules.add(node.module)
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


class NoTestReadsThePlatformDataDirTestCase(unittest.TestCase):
    """A worktree has its own data directory, and a test is not exempt.

    Three modules here spelled out `Path.home() / ".local/share/brightway-flows"`
    and read past `BRIGHTWAY_FLOWS_DATA_DIR` to whatever the last branch to
    build left in the shared directory -- one of them the 207 MB extracted base
    list, which is exactly the file two branches write different versions of
    (#82).  The suite passed either way, which is what makes this worth a test
    rather than a note: nothing about the run says which list was read.

    Ask the source list where its flows are, or `filesystem` for a cache.
    """

    TESTS = Path(__file__).resolve().parent

    @staticmethod
    def _calls_path_home(source: str) -> bool:
        """Is `Path.home()` *called* anywhere in *source*?

        Parsed rather than searched, so that this file and the docstring in
        `test_flow_specific_contexts.py` can both say what the mistake looked
        like without becoming instances of it.
        """
        for node in ast.walk(ast.parse(source)):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "home"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "Path"
            ):
                return True
        return False

    def test_no_test_module_reads_from_the_home_directory(self):
        offenders = sorted(
            path.name
            for path in self.TESTS.glob("test_*.py")
            if self._calls_path_home(path.read_text())
        )
        self.assertEqual(
            offenders,
            [],
            "these tests read the shared data directory rather than this "
            "worktree's; see AGENTS.md rule 32",
        )


class QualifierLossStaysAShortlistTestCase(unittest.TestCase):
    """The pattern over chemical names may rank work. It may not decide any.

    #220 tried a heuristic that refused a replacement dropping a locant, a
    designation or a scope qualifier, and abandoned it: three iterations to stop
    reading `C4-6` as an isotope, and the version that stopped misfiring still
    blocked `Barbituric acid` and `δ-Hexachlorocyclohexane`. #224 brought the
    same detectors back as a *shortlist* -- a chemist reads the rows it ranks
    first -- and that is only defensible while nothing published depends on
    them.

    So the rule is structural: `curation.qualifier_loss` is imported by tools and
    by tests, and by nothing that runs in a build.
    """

    def test_nothing_in_the_pipeline_imports_the_shortlist_heuristic(self):
        offenders: list[str] = []
        for path in sorted(SRC.rglob("*.py")):
            if path.parent.name == "curation":
                continue
            imported = _imported_modules(ast.parse(path.read_text()))
            if "brightway_flows.curation.qualifier_loss" in imported:
                offenders.append(str(path.relative_to(SRC.parent.parent)))
        self.assertEqual(
            offenders, [],
            "qualifier_loss shortlists renames for a reader and must not gate "
            "one; these modules import it:\n  " + "\n  ".join(offenders),
        )

#: Attribute names only a record has.  `.get()`, `.items()` and subscripting are
#: the payload tell, and a name showing both is what needs reading.
_RECORD_ATTRS = frozenset({
    "uuid", "name", "context", "unit", "source", "cas_numbers", "ec_numbers",
    "prefLabel", "altLabel", "properties", "flow_object_id", "types",
    "elementary_flow_id", "source_refs", "skos_definition", "classifications",
    "references", "reason", "outcome", "detail", "context_iri", "synonyms",
})
_PAYLOAD_METHODS = frozenset({"get", "items", "keys", "values", "setdefault", "pop"})


def _getattr_field(node: ast.AST, name: str) -> str | None:
    """The field name in ``getattr(<name>, "field")``, if that is what this is.

    Only a literal field name counts.  ``getattr(flow, key)`` is a lookup by a
    computed name, which is a legitimate thing to do to a payload and says
    nothing about whether the value is a record.
    """
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
        return None
    if node.func.id != "getattr" or len(node.args) < 2:
        return None
    target, field = node.args[0], node.args[1]
    if not (isinstance(target, ast.Name) and target.id == name):
        return None
    if isinstance(field, ast.Constant) and isinstance(field.value, str):
        return field.value
    return None


def _dict_guards_over_records(tree: ast.AST) -> list[tuple[int, str, str]]:
    """`isinstance(<name>, dict)` where <name> is read as a record nearby."""
    functions = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    ]
    found: list[tuple[int, str, str]] = []
    for func in functions:
        for node in ast.walk(func):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
                continue
            if node.func.id != "isinstance" or len(node.args) != 2:
                continue
            target, kind = node.args
            if not isinstance(target, ast.Name):
                continue
            types = kind.elts if isinstance(kind, ast.Tuple) else [kind]
            if not any(isinstance(t, ast.Name) and t.id == "dict" for t in types):
                continue

            attrs: set[str] = set()
            payload = False
            for use in ast.walk(func):
                if isinstance(use, ast.Attribute) and isinstance(use.value, ast.Name):
                    if use.value.id != target.id:
                        continue
                    if use.attr in _PAYLOAD_METHODS:
                        payload = True
                    else:
                        attrs.add(use.attr)
                elif isinstance(use, ast.Subscript) and isinstance(use.value, ast.Name):
                    if use.value.id == target.id:
                        payload = True
                elif (field := _getattr_field(use, target.id)) is not None:
                    # `getattr(flow, "uuid", "")` is a record read written the
                    # long way, and it is how the one live instance of this bug
                    # escaped the detector: `pipeline.engine._flow_uuid` guarded
                    # a `Flow` as a dict and read it through `getattr`, so the
                    # loop above saw no attribute at all (#92).
                    attrs.add(field)
            if attrs & _RECORD_ATTRS and not payload:
                found.append((node.lineno, target.id, func.name))
    return found


class DictGuardsOverRecordsTestCase(unittest.TestCase):
    """A dict guard on a record is false forever, and silently.

    Flows became dataclass records while dict-shaped guards stayed behind. Each
    one skips its block on every run: no test fails and nothing is logged, so it
    reads as "this case never occurs". Seven were found this way, one of which
    had disabled `consensus_match` outright and another the whole element and
    isotope enrichment.

    The signal is a name that is guarded as a dict and read as a record in the
    same function. Names used both ways -- external payloads with a field that
    happens to share a record's name -- are excluded rather than reported,
    because those are the legitimate majority.
    """

    def test_no_guard_treats_a_record_as_a_dict(self):
        offenders: list[str] = []
        for path in sorted(SRC.rglob("*.py")):
            if "webapps" in path.parts:
                continue
            tree = ast.parse(path.read_text())
            for line, name, func in _dict_guards_over_records(tree):
                offenders.append(
                    f"{path.relative_to(SRC.parent.parent)}:{line} "
                    f"isinstance({name}, dict) in {func}()"
                )
        self.assertEqual(
            offenders, [],
            "dict guard on a value read as a record; the guarded block never "
            "runs:\n  " + "\n  ".join(offenders),
        )

    def test_the_detector_recognises_the_bug_it_is_guarding_against(self):
        """Without this, an over-narrow detector would pass by finding nothing."""
        source = (
            "def transform(flows):\n"
            "    return {f.uuid: f for f in flows if isinstance(f, dict)}\n"
        )
        self.assertEqual(
            [(2, "f", "transform")], _dict_guards_over_records(ast.parse(source))
        )

    def test_the_detector_sees_a_record_read_through_getattr(self):
        """The shape `pipeline.engine._flow_uuid` had until #92.

        It guarded a value as a dict and read it with `getattr(flow, "uuid")`,
        so the dict branch was dead on every run and the detector -- which only
        looked for `flow.uuid` -- reported nothing.
        """
        source = (
            "def sample(flows):\n"
            "    return [f for f in flows if isinstance(f, dict)"
            " or getattr(f, 'uuid', '')]\n"
        )
        self.assertEqual(
            [(2, "f", "sample")], _dict_guards_over_records(ast.parse(source))
        )

    def test_a_computed_getattr_is_not_a_record_read(self):
        """`getattr(row, key)` says nothing about the shape of `row`."""
        source = (
            "def load(rows):\n"
            "    for row in rows:\n"
            "        if isinstance(row, dict):\n"
            "            use(getattr(row, key))\n"
        )
        self.assertEqual([], _dict_guards_over_records(ast.parse(source)))

    def test_a_payload_guard_is_not_reported(self):
        source = (
            "def load(rows):\n"
            "    for row in rows:\n"
            "        if not isinstance(row, dict):\n"
            "            continue\n"
            "        use(row.get('uuid'))\n"
        )
        self.assertEqual([], _dict_guards_over_records(ast.parse(source)))


if __name__ == "__main__":
    unittest.main()
