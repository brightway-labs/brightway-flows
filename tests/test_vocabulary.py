"""The term registry is the single definition point for vocabulary IRIs.

The drift guard is the point of this file: without it, nothing stops a module
from re-declaring an IRI literal and quietly diverging, which is how the CAS
classification IRI ended up defined in five places.
"""

import ast
import re
import unittest
from pathlib import Path

from brightway_flows.domain import vocabulary
from brightway_flows.domain.vocabulary import (
    EXPORT_LANGUAGE,
    LANGUAGE_TAGGED_TERMS,
    IRIS,
    JSONLD_CONTEXT,
    TERM_BY_IRI,
    TERM_DATATYPE,
    Datatype,
    MintedNamespace,
    curie,
    Namespace,
    Term,
    datatype_curie,
    ecoinvent_flow_iri_prefix,
    iri,
    term_for_iri,
)

SRC = Path(__file__).resolve().parent.parent / "src" / "brightway_flows"
VOCABULARY_MODULE = SRC / "domain" / "vocabulary.py"


class RegistryShapeTestCase(unittest.TestCase):
    def test_every_term_resolves_to_an_iri(self):
        for term in Term:
            with self.subTest(term=term.name):
                self.assertTrue(iri(term).startswith("http"), iri(term))

    def test_iris_are_unique(self):
        self.assertEqual(
            len(TERM_BY_IRI), len(Term),
            "two terms share an IRI, so term_for_iri() is ambiguous",
        )

    def test_term_for_iri_round_trips(self):
        for term in Term:
            with self.subTest(term=term.name):
                self.assertIs(term_for_iri(iri(term)), term)
        self.assertIsNone(term_for_iri("https://example.org/not-a-term"))

    def test_every_iri_starts_with_its_declared_namespace(self):
        namespaces = {ns.value for ns in Namespace}
        for term in Term:
            with self.subTest(term=term.name):
                self.assertTrue(
                    any(iri(term).startswith(ns) for ns in namespaces),
                    f"{term.name} -> {iri(term)} is in no declared namespace",
                )

    def test_ecoinvent_prefix_interpolates_version(self):
        self.assertEqual(
            ecoinvent_flow_iri_prefix("3.12"),
            "https://vocab.brightway.one/ecoinvent/3.12/flow/",
        )

    def test_minted_namespaces_are_recorded_not_normalised(self):
        """The .one/.dev split is real and load-bearing for published IRIs."""
        self.assertTrue(
            MintedNamespace.CONSENSUS_ELEMENTARY_FLOW.value.startswith(
                "https://vocab.brightway.dev/"
            )
        )
        self.assertTrue(
            MintedNamespace.EF31_FLOW.value.startswith("https://vocab.brightway.one/")
        )


class JSONLDContextTestCase(unittest.TestCase):
    def test_context_declares_every_term(self):
        """A term that is emitted but undeclared expands to nothing.

        A term with a declared datatype is an expanded term definition -- a dict
        carrying `@id` and `@type` -- rather than a bare IRI string, so the IRI
        is read from whichever form it takes.
        """
        for term in Term:
            with self.subTest(term=term.name):
                declared = JSONLD_CONTEXT.get(term.value)
                if isinstance(declared, dict):
                    declared = declared.get("@id")
                self.assertEqual(declared, iri(term))

    def test_a_typed_term_declares_its_xsd_datatype(self):
        """A term whose value is not a string must say what it is.

        Mostly ChemROF slots with a numeric range, plus `dcterms:created`,
        which is a timestamp rather than the plain string it would expand to
        undeclared.
        """
        for term, datatype in TERM_DATATYPE.items():
            with self.subTest(term=term.name):
                self.assertEqual(
                    JSONLD_CONTEXT[term.value],
                    {"@id": iri(term), "@type": datatype_curie(datatype)},
                )

    def test_a_text_term_declares_its_language(self):
        """PyST rejects an untagged literal, and these are published bare.

        The tag is on the term rather than in the document, so `prefLabel` stays
        the string a consumer reads and still expands tagged.
        """
        for term in LANGUAGE_TAGGED_TERMS:
            with self.subTest(term=term.name):
                self.assertEqual(
                    JSONLD_CONTEXT[term.value],
                    {"@id": iri(term), "@language": EXPORT_LANGUAGE},
                )

    def test_no_term_declares_both_a_language_and_a_datatype(self):
        """`@language` and `@type` are mutually exclusive in a term definition.

        Declaring both silently drops one, so the export would claim a datatype
        or a language it does not carry.
        """
        both = LANGUAGE_TAGGED_TERMS & set(TERM_DATATYPE)
        self.assertEqual(both, set(), f"cannot be both: {both}")

    def test_every_datatype_curie_resolves_through_a_declared_prefix(self):
        for datatype in Datatype:
            prefix, _, _local = datatype_curie(datatype).partition(":")
            with self.subTest(datatype=datatype.name):
                self.assertIn(prefix, JSONLD_CONTEXT)

    def test_context_declares_every_namespace_prefix(self):
        for namespace in Namespace:
            with self.subTest(namespace=namespace.name):
                self.assertEqual(
                    JSONLD_CONTEXT.get(namespace.name.lower()), namespace.value
                )

    def test_context_is_generated_not_hand_maintained(self):
        self.assertEqual(JSONLD_CONTEXT, vocabulary.build_jsonld_context())

    def test_curies_currently_emitted_can_be_expanded(self):
        """The output emits these as CURIEs; the context must resolve them."""
        for prefix in ("prov", "skos", "xkos", "qudt", "rdfs"):
            with self.subTest(prefix=prefix):
                self.assertIn(prefix, JSONLD_CONTEXT)


class NoDuplicateIRIDeclarationsTestCase(unittest.TestCase):
    """Drift guard: no module may re-declare an IRI that the registry owns."""

    IRI_ASSIGNMENT = re.compile(r'^\s*_?[A-Z][A-Z0-9_]*\s*=\s*"(https?://[^"]+)"')

    def _iri_assignments(self) -> list[tuple[Path, int, str]]:
        found = []
        for path in sorted(SRC.rglob("*.py")):
            if path == VOCABULARY_MODULE:
                continue
            for lineno, line in enumerate(path.read_text().splitlines(), start=1):
                match = self.IRI_ASSIGNMENT.match(line)
                if match:
                    found.append((path, lineno, match.group(1)))
        return found

    def test_no_module_redeclares_a_registry_iri(self):
        registry = set(IRIS.values()) | {ns.value for ns in Namespace}
        offenders = [
            f"{path.relative_to(SRC)}:{lineno} redeclares {value}"
            for path, lineno, value in self._iri_assignments()
            if value in registry
        ]
        self.assertEqual(
            offenders, [],
            "import these from brightway_flows.domain.vocabulary instead:\n  "
            + "\n  ".join(offenders),
        )

    def test_no_module_redeclares_a_minted_namespace(self):
        minted = {
            ns.value for ns in MintedNamespace if "{" not in ns.value
        }
        offenders = [
            f"{path.relative_to(SRC)}:{lineno} redeclares {value}"
            for path, lineno, value in self._iri_assignments()
            if value in minted
        ]
        self.assertEqual(offenders, [], "\n  ".join(offenders))

    #: A CURIE this project reads but deliberately never writes.  Empty today:
    #: the one entry was the consensus app recognising the deprecated
    #: `qudt:unit` to render a database built before #230, and #229 replaced
    #: that app.  Kept because the next legacy read wants a place to be
    #: declared rather than a reason to weaken the guard.
    CURIE_READ_ONLY: frozenset[str] = frozenset()

    def _curie_literals(self) -> list[tuple[Path, int, str]]:
        """Every `"prefix:localName"` written out under a registry prefix."""
        prefixes = {namespace.name.lower() for namespace in Namespace}
        pattern = re.compile(
            r"""["'](?P<curie>(%s):[A-Za-z_][A-Za-z0-9_]*)["']""" % "|".join(prefixes)
        )
        found = []
        for path in sorted(SRC.rglob("*.py")):
            relative = path.relative_to(SRC)
            if relative == Path("domain/vocabulary.py"):
                continue
            for lineno, line in enumerate(path.read_text().splitlines(), start=1):
                for match in pattern.finditer(line):
                    found.append((relative, lineno, match.group("curie")))
        return found

    def test_no_module_writes_an_undeclared_registry_curie(self):
        """The gap that let `qudt:unit` survive six call sites until #230.

        The IRI guards above match `"https://..."`, and a CURIE is neither -- so
        a term written as `"qudt:unit"`, on a prefix the registry owns but under
        a name it has never heard of, went unnoticed in five modules and a
        webapp. It was a predicate QUDT deprecates, carrying a bare string where
        the property ranges over `qudt:Unit`.

        The same shape hid five PROV activity terms the inputs app emitted
        without declaring, before #229 deleted that app. Both are the dangerous
        class: a prefix that resolves plus a local name nobody checked, which
        expands to a real-looking IRI that means nothing.
        """
        declared = {curie(term) for term in Term}
        offenders = [
            f"{path}:{lineno}: {found}"
            for path, lineno, found in self._curie_literals()
            if found not in declared and found not in self.CURIE_READ_ONLY
        ]
        self.assertEqual(
            offenders, [],
            "these use a registry prefix and a name the registry does not "
            "declare. Add the term, or if it is only ever read, add it to "
            "CURIE_READ_ONLY with a reason:\n  " + "\n  ".join(offenders),
        )

    def test_no_module_writes_a_declared_curie_as_a_literal(self):
        """#233: a declared term must be imported, not spelled out again.

        Not drift -- `"rdfs:label"` is exactly what `curie(Term.LABEL)` returns,
        so the two spellings cannot come to mean different things. It is the
        second cost the registry exists to remove: with 48 literals across 17
        modules, renaming a term meant grepping for two spellings and hoping.

        The `*_CURIE` constants are what to import. They sit beside the `*_IRI`
        ones in the registry, because the two levels are a real distinction --
        a record field is keyed by the expanded IRI, a `concept_associations`
        node by the CURIE -- and both should be one edit to change.
        """
        by_curie = {curie(term): term for term in Term}
        offenders = [
            f"{path}:{lineno}: {found} is curie(Term.{by_curie[found].name})"
            for path, lineno, found in self._curie_literals()
            if found in by_curie
        ]
        self.assertEqual(
            offenders, [],
            "import the matching constant from "
            "brightway_flows.domain.vocabulary instead:\n  "
            + "\n  ".join(offenders),
        )

    def test_no_inline_chemrof_or_cheminf_literals(self):
        """Vocabulary IRIs must not appear as inline string literals either."""
        pattern = re.compile(
            r'"(https://w3id\.org/chemrof/|http://semanticscience\.org/resource/CHEMINF_)'
        )
        offenders = []
        for path in sorted(SRC.rglob("*.py")):
            if path == VOCABULARY_MODULE:
                continue
            for lineno, line in enumerate(path.read_text().splitlines(), start=1):
                if pattern.search(line):
                    offenders.append(f"{path.relative_to(SRC)}:{lineno}: {line.strip()}")
        self.assertEqual(offenders, [], "\n  ".join(offenders))


class RegistryIsImportableEverywhereTestCase(unittest.TestCase):
    def test_vocabulary_module_has_no_project_imports(self):
        """Keep the registry a leaf so any module can import it without a cycle."""
        tree = ast.parse(VOCABULARY_MODULE.read_text())
        project_imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
                "brightway_flows"
            ):
                project_imports.append(node.module)
            elif isinstance(node, ast.Import):
                project_imports.extend(
                    alias.name for alias in node.names
                    if alias.name.startswith("brightway_flows")
                )
        self.assertEqual(project_imports, [])


if __name__ == "__main__":
    unittest.main()
