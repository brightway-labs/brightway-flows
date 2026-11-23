"""The steps of the harmonisation chain.

`DEFAULT_TRANSFORMERS` and every step's class are offered here, as they always
were, and defined in :mod:`brightway_flows.transformers.chain`, which is
imported the first time one of them is asked for. Importing a single step's
module -- which is what `brightway_flows.lookup` does for the four it runs --
therefore does not import the other steps, or the packages only they need.
`tests/test_install_boundaries.py` holds it to that.
"""

from __future__ import annotations

from importlib import import_module
from importlib.machinery import PathFinder
from typing import Any

_CHAIN = "brightway_flows.transformers.chain"


def __getattr__(name: str) -> Any:
    # `from brightway_flows.transformers import pubchem` asks the package for
    # `pubchem` before it imports the module of that name. Answering from the
    # chain would import every step to find one, so a name that is one of our
    # modules -- `chain` itself included, which arrives here while it is being
    # imported -- is left to the import system.
    if (
        name.startswith("__") and name != "__all__"
    ) or PathFinder.find_spec(f"{__name__}.{name}", __path__) is not None:
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r}"
        )
    try:
        return getattr(import_module(_CHAIN), name)
    except AttributeError:
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r}"
        ) from None


def __dir__() -> list[str]:
    return sorted(import_module(_CHAIN).__all__)
