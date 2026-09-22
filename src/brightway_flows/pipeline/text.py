"""Name and unit predicates shared by transformers.

These are pure string tests with no pipeline state. They live here rather than in
the engine because every transformer needs them and none of them needs the
engine.
"""

from __future__ import annotations

import re
from typing import Any

_STEREO_DESCRIPTOR_RE = re.compile(
    r"""
    [αβγδεζηθ]              # Greek letters used as IUPAC stereo descriptors
    | \b(?:alpha|beta|gamma|delta|cis|trans)-  # ASCII stereo prefixes
    """,
    re.IGNORECASE | re.VERBOSE,
)

def normalize(s: str) -> str:
    """Lowercase and strip all whitespace -- used for name comparison."""
    return "".join(s.lower().split())

def has_stereo_descriptor(name: str) -> bool:
    """Return True when *name* contains a stereochemical descriptor.

    Detects Greek letters (α β γ δ …) and ASCII equivalents used as
    stereo prefixes in IUPAC chemical names (alpha-, beta-, cis-, trans-,
    etc.).  Used to guard against stripping stereo information from a flow
    name when a database returns a less-specific parent compound name.
    """
    return bool(_STEREO_DESCRIPTOR_RE.search(name))

def is_becquerel_unit(unit: Any) -> bool:
    """Return True when *unit* represents becquerel-based radioactivity units."""
    if not isinstance(unit, str):
        return False
    text = unit.strip().lower()
    if not text:
        return False
    text = text.replace("μ", "u").replace("µ", "u")
    if "becquerel" in text:
        return True
    token_set = {
        "bq",
        "fbq",
        "pbq",
        "nbq",
        "ubq",
        "mbq",
        "cbq",
        "dbq",
        "kbq",
        "hbq",
        "gbq",
        "tbq",
    }
    tokens = [tok for tok in re.split(r"[^a-z0-9]+", text) if tok]
    return any(tok in token_set for tok in tokens)
