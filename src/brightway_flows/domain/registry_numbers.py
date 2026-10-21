"""How a registry number is read, whoever wrote it.

A CAS number is up to seven digits, a hyphen, two digits, a hyphen and a check
digit: `108-90-7`.  Some writers pad the first segment with zeros to a fixed
width -- openLCA's LCIA package writes `000108-90-7` on 51,173 of its 55,630
numbers, SimaPro exports do the same -- and `000108-90-7` and `108-90-7` are
one number.  Every list's adapter reads its numbers through
:func:`normalize_cas_number`, and so does a lookup query, so the padding never
reaches an index (#375).

Only the padding is touched.  A value that is not three hyphenated digit
groups -- an EC number written without hyphens, `2025884`, or openLCA's
`E1730135` -- is returned as it came, for the check-digit step to report.
"""

from __future__ import annotations


def normalize_cas_number(value: str) -> str:
    """*value* with the leading zeros taken off its first segment.

    ``000108-90-7`` becomes ``108-90-7``; ``108-90-7`` is returned unchanged,
    and so is anything that is not three hyphen-separated digit groups.
    """
    value = (value or "").strip()
    parts = value.split("-")
    if len(parts) != 3:
        return value
    first, second, third = parts
    if not (first.isdigit() and second.isdigit() and third.isdigit()):
        return value
    first = first.lstrip("0") or "0"
    return f"{first}-{second}-{third}"
