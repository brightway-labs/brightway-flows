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
from typing import Any

_CHAIN = "brightway_flows.transformers.chain"


def __getattr__(name: str) -> Any:
    # `chain` itself arrives here too, while it is being imported: `from
    # package import module` asks the package for the name before it looks for
    # the module, so answering by importing it would never return.
    if name.startswith("__") or name == "chain":
        raise AttributeError(name)
    try:
        return getattr(import_module(_CHAIN), name)
    except AttributeError:
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r}"
        ) from None


def __dir__() -> list[str]:
    return sorted(import_module(_CHAIN).__all__)
