"""A test fixture that says "context" must hold a context.

Twenty-one fixtures across nine test files did not, and nothing noticed for as
long as `Flow.context` was `list[Any] | dict[str, Any]`: air contexts with a
stratum but not the population density that stratum requires, `Freshwater` and
`Surface water` sitting in `strata` where a water body belongs, one
`{"dimension": "emission"}` in the merge's own vocabulary rather than the
consensus one, and thirteen turpentine contexts that disagreed with the IRIs
written beside them on nine of the thirteen.

Typing the field as a `Context` (#97) caught them, because the record now
builds one and the constructor validates.  This keeps them caught, and covers
the fixtures that never reach a record at all -- a payload dict written straight
into SQLite by a webapp test is exactly where the next one would appear.

The rule is deliberately narrow: whatever ends up *in a context position* --
the value of a `"context"` key, a `context=` argument to a record constructor, or
the argument to `context_from_dict` -- must be a context the vocabulary would
accept.  A module-level constant named in such a position counts, since that is
how many of these fixtures are written.  A dict that only ever supplies a common
prefix to other dicts is not in a context position and is not checked, and
neither is `FlowFilters(context=...)`, whose argument is a facet selection over
contexts rather than one.
"""

import ast
import unittest
from pathlib import Path

from brightway_flows.domain.context_registry import (
    InvalidContextError,
    context_from_dict,
)

TESTS_DIR = Path(__file__).resolve().parent

#: Keyword arguments named `context` that are not a flow's context.
#: `Finding.context` is what a `characterise` finding was found *with* -- the two
#: numbers that collided, the multiplier a unit crossing used -- and has nothing
#: to do with a compartment.
NOT_A_FLOW_CONTEXT = frozenset({"FlowFilters", "Finding"})

#: The one file whose invalid contexts are the point: it tests that they are
#: refused.  Named rather than inferred, so adding a second such file is a
#: decision someone takes rather than a check that quietly stops applying.
TESTS_OF_REFUSAL = frozenset({"test_context_validation.py"})


def _module_dicts(tree: ast.Module) -> dict[str, dict]:
    """Module-level ``NAME = {...}`` literals, for resolving ``{**NAME, ...}``."""
    out: dict[str, dict] = {}
    for node in tree.body:
        if not (isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict)):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                try:
                    out[target.id] = ast.literal_eval(node.value)
                except ValueError:
                    pass
    return out


def _resolve(node: ast.AST, bases: dict[str, dict]) -> dict | None:
    """What a literal evaluates to, or None if it cannot be read statically.

    Resolves a bare module-level name as well as a dict literal, because
    `context=_AIR_CTX` is how most of these fixtures spell it.
    """
    if isinstance(node, ast.Name):
        return bases.get(node.id)
    if isinstance(node, ast.Call) and _called_name(node) == "dict" and len(node.args) == 1:
        return _resolve(node.args[0], bases)  # `dict(CONTEXT)`
    if not isinstance(node, ast.Dict):
        return None
    out: dict = {}
    for key, value in zip(node.keys, node.values):
        if key is None:  # `{**BASE, ...}`
            if isinstance(value, ast.Name) and value.id in bases:
                out.update(bases[value.id])
                continue
            return None
        if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
            return None
        try:
            out[key.value] = ast.literal_eval(value)
        except ValueError:
            return None
    return out


def _called_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def context_literals(tree: ast.Module) -> list[tuple[int, dict]]:
    """Every dict literal this module puts in a context position."""
    bases = _module_dicts(tree)
    found: list[tuple[int, dict]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and key.value == "context":
                    resolved = _resolve(value, bases)
                    if resolved:
                        found.append((value.lineno, resolved))
        elif isinstance(node, ast.Call):
            # `context_from_dict({...})` builds one, so its argument is one.
            if _called_name(node) == "context_from_dict" and len(node.args) == 1:
                resolved = _resolve(node.args[0], bases)
                if resolved:
                    found.append((node.args[0].lineno, resolved))
            if _called_name(node) in NOT_A_FLOW_CONTEXT:
                continue
            for keyword in node.keywords:
                if keyword.arg == "context":
                    resolved = _resolve(keyword.value, bases)
                    if resolved:
                        found.append((keyword.value.lineno, resolved))
    return found


class FixtureContextsAreContextsTestCase(unittest.TestCase):
    def test_every_fixture_context_is_one_the_vocabulary_accepts(self):
        checked = 0
        for path in sorted(TESTS_DIR.glob("test_*.py")):
            if path.name in TESTS_OF_REFUSAL:
                continue
            tree = ast.parse(path.read_text())
            for lineno, literal in context_literals(tree):
                checked += 1
                with self.subTest(fixture=f"{path.name}:{lineno}"):
                    try:
                        context_from_dict(literal)
                    except InvalidContextError as error:
                        self.fail(f"{path.name}:{lineno} {literal!r}: {error}")
        # A floor, not a count: it is here so that a change which makes the
        # scan match nothing fails instead of passing vacuously.
        self.assertGreater(
            checked, 20, "the scan found almost nothing; it has stopped working"
        )

    def test_the_file_that_is_allowed_invalid_contexts_uses_them(self):
        """An exemption nobody exercises is an exemption nobody removed."""
        for name in TESTS_OF_REFUSAL:
            tree = ast.parse((TESTS_DIR / name).read_text())
            refused = [
                literal
                for _, literal in context_literals(tree)
                if not self._constructible(literal)
            ]
            self.assertTrue(
                refused,
                f"{name} is exempt from the context check but has no invalid "
                "context left in it; drop it from TESTS_OF_REFUSAL",
            )

    @staticmethod
    def _constructible(literal: dict) -> bool:
        try:
            context_from_dict(literal)
        except InvalidContextError:
            return False
        return True


if __name__ == "__main__":
    unittest.main()
