"""A test that is defined twice is a test that does not run.

`tests/test_factor_pages.py` defined `test_a_build_without_a_characterisation_says_so`
twice inside one class, so Python kept the second and the first had not run since
it was written.  It asserted that a category page renders "No factors yet" rather
than three zeros on an uncharacterised build; renaming it and running it shows it
passes, so nothing was broken behind it.  What was broken is that the suite was
reporting success for a check that did not exist (#325).

That is the failure this directory exists to prevent everywhere else.
`tests/test_expectations.py` refuses a misspelled claim because "a typo that turns
a check into a pass looks exactly like a check that holds"; `test_documentation.py`
checks numbers copied out of `data/` because nothing else stops them drifting.
A shadowed test is the same shape, one level up.

`ruff --select F811` finds it, and rule 23 says to run ruff -- which is how it was
found, twice, by two branches on the same afternoon.  But nothing runs ruff on its
own: there is no CI in this repository, so every automated check there is lives in
this directory.  A rule that depends on somebody remembering is the rule that was
not remembered when the duplicate was written, so this is the same question asked
by something that always runs.

Deliberately about *any* duplicated method in a test class, not only one whose
name starts with `test_`.  A helper defined twice shadows exactly as silently, and
the version the class actually uses is whichever came last.
"""

from __future__ import annotations

import ast
import unittest
from collections import Counter
from pathlib import Path

TESTS = Path(__file__).resolve().parent


def _duplicate_names(body: list[ast.stmt]) -> list[str]:
    """Function names defined more than once directly in *body*.

    Only the statements of this body, so a method of a nested class is not
    confused with one of the class around it.
    """
    counts = Counter(
        statement.name
        for statement in body
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
    )
    return sorted(name for name, count in counts.items() if count > 1)


class NoTestIsDefinedTwiceTestCase(unittest.TestCase):
    """Every test file, every class in it, and the module level of each."""

    @classmethod
    def setUpClass(cls):
        cls.modules = sorted(TESTS.glob("test_*.py"))

    def test_the_suite_is_being_read_at_all(self):
        """So that a glob that stops matching cannot make the check below
        vacuous -- the same guard the nitrogen case in `test_manual_fixes.py`
        puts in front of its own subjects."""
        self.assertGreater(len(self.modules), 100)

    def test_no_class_defines_a_method_twice(self):
        for path in self.modules:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                for name in _duplicate_names(node.body):
                    with self.subTest(file=path.name, cls=node.name, method=name):
                        self.fail(
                            f"{path.name}: {node.name}.{name} is defined more than "
                            f"once, so only the last one runs. Rename them for the "
                            f"two things they check, or delete the one that is a "
                            f"copy."
                        )

    def test_no_module_defines_a_test_function_twice(self):
        """The same defect outside a class, where a bare `test_` function is
        collected directly."""
        for path in self.modules:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for name in _duplicate_names(tree.body):
                if not name.startswith("test_"):
                    continue
                with self.subTest(file=path.name, function=name):
                    self.fail(
                        f"{path.name}: {name} is defined more than once at module "
                        f"level, so only the last one runs."
                    )


class TheGuardCatchesTheShapeItIsForTestCase(unittest.TestCase):
    """Asked of source it constructs, because the repository is now clean.

    Without this the case above would pass just as well with `_duplicate_names`
    returning nothing at all, which is the failure mode it exists to prevent.
    """

    def _names(self, source: str) -> list[str]:
        tree = ast.parse(source)
        node = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef))
        return _duplicate_names(node.body)

    def test_it_finds_a_method_defined_twice(self):
        self.assertEqual(
            self._names(
                "class C:\n"
                "    def test_a(self): pass\n"
                "    def test_b(self): pass\n"
                "    def test_a(self): pass\n"
            ),
            ["test_a"],
        )

    def test_it_passes_a_class_that_defines_each_once(self):
        self.assertEqual(
            self._names(
                "class C:\n"
                "    def test_a(self): pass\n"
                "    def test_b(self): pass\n"
            ),
            [],
        )

    def test_one_name_in_two_classes_is_not_a_duplicate(self):
        """Which is the other half, and why #325 was three definitions and one
        defect: `TheCategoryComparisonTestCase` uses the same name for its own
        page, and a name may repeat across classes."""
        source = (
            "class A:\n"
            "    def test_a(self): pass\n"
            "class B:\n"
            "    def test_a(self): pass\n"
        )
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                self.assertEqual(_duplicate_names(node.body), [])

    def test_a_nested_class_is_not_confused_with_the_one_around_it(self):
        source = (
            "class Outer:\n"
            "    def test_a(self): pass\n"
            "    class Inner:\n"
            "        def test_a(self): pass\n"
        )
        tree = ast.parse(source)
        outer = next(
            n for n in ast.walk(tree)
            if isinstance(n, ast.ClassDef) and n.name == "Outer"
        )
        self.assertEqual(_duplicate_names(outer.body), [])


if __name__ == "__main__":
    unittest.main()
