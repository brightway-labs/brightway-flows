"""The base list is a role, not a string literal.

That EF 3.1 is the fixed thing everything merges into is a defensible
architectural decision.  It used to be expressed as the string ``"EF 3.1"``
repeated across eight modules, plus one hard-coded path in `filesystem.py`, so
"which list is the base" was a grep rather than a line (#14).

It is now the one manifest in `data/sources/` with ``role: "base"``.  These
tests keep it that way: the enforcement is what makes the claim worth anything,
because a ninth literal costs nothing to write and is invisible in review.
"""

import ast
import unittest
from pathlib import Path

from brightway_flows.flow_layers.elements import BASE_REFERENCES_PROPERTY
from brightway_flows.pipeline.review_records import ElementStatus
from brightway_flows.sources import base_source_label, base_source_list

SRC = Path(__file__).resolve().parent.parent / "src" / "brightway_flows"

#: The EF 3.1 adapter may name EF 3.1.  Which list a file belongs to is the file
#: it sits in -- the principle `manual_fixes` already states -- and this module
#: parses EF 3.1's own ILCD archive and nothing else.
ALLOWED = {"integrations/ef31.py"}


def _string_literals(path: Path) -> list[str]:
    """Every string constant in *path* that is not a docstring.

    Parsed rather than grepped: the base list is named in prose all over the
    codebase, and prose is not the problem.  A comparison is.
    """
    tree = ast.parse(path.read_text())
    docstrings = {
        node.body[0].value
        for node in ast.walk(tree)
        if isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        )
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node not in docstrings
    ]


class TheLiteralIsGoneTestCase(unittest.TestCase):
    def test_no_module_hard_codes_the_base_list_source_string(self):
        offenders = []
        for path in sorted(SRC.rglob("*.py")):
            if str(path.relative_to(SRC)) in ALLOWED:
                continue
            if base_source_label() in _string_literals(path):
                offenders.append(str(path.relative_to(SRC)))
        self.assertEqual(
            offenders,
            [],
            "These name the base list directly. Compare against "
            "`sources.base_source_label()` instead, so that changing the base "
            "list stays a one-line change to its manifest.",
        )

    def test_the_base_list_flows_file_is_not_a_constant_either(self):
        """`filesystem.FLOWS_DATA_FILEPATH` was the other half of the decision."""
        from brightway_flows import filesystem

        self.assertFalse(hasattr(filesystem, "FLOWS_DATA_FILEPATH"))
        self.assertEqual(base_source_list().flows_path.name, "ef-31-flows.json")


class PublishedStringsDidNotMoveTestCase(unittest.TestCase):
    """Two of the eight sites are published, and had to stay put.

    Both name the base list of the day they were minted.  Renaming either is a
    data migration -- the slug is user-visible in the review application and
    stored in the database, and the property key is in every published flow
    object -- so #14 changed the code around them and left them alone.
    """

    def test_the_element_coverage_queue_slug_is_unchanged(self):
        self.assertEqual(ElementStatus.NOT_LINKED, "not-linked-to-ef31")

    def test_the_element_references_property_key_is_unchanged(self):
        self.assertEqual(BASE_REFERENCES_PROPERTY, "ef31_references")


if __name__ == "__main__":
    unittest.main()
