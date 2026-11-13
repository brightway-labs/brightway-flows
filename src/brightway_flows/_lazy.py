"""Names a package offers without importing the modules they live in.

`from brightway_flows.pipeline import Change` has always worked, and for it to
work the package used to import every module it re-exported a name from -- so
importing any one module of `pipeline` imported the whole of a build, and with
it the packages only a build needs. A program that only asks where a row goes
(`brightway_flows.lookup`) or only reads a finished build (the review
application) then needed all of them installed.

A package that lists its names here still offers every one of them, and imports
the module a name lives in when the name is first asked for.
`tests/test_install_boundaries.py` is what holds the result.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from importlib import import_module
from typing import Any


def lazy_exports(
    package: str, exports: Mapping[str, str]
) -> tuple[Callable[[str], Any], Callable[[], list[str]]]:
    """The `__getattr__` and `__dir__` of a package whose names load on demand.

    :param package: the package's own `__name__`
    :param exports: each offered name, and the module of *package* it lives in
    """

    def __getattr__(name: str) -> Any:
        try:
            module = exports[name]
        except KeyError:
            raise AttributeError(
                f"module {package!r} has no attribute {name!r}"
            ) from None
        return getattr(import_module(f"{package}.{module}"), name)

    def __dir__() -> list[str]:
        return sorted(exports)

    return __getattr__, __dir__
