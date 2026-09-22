"""Pieces every query module needs: paging, sorting, and JSON columns.

Small on purpose. The applications this replaces each carried their own copy of
`_order_by`, `_json_loads_text` and a page-count calculation, so the same
operation behaved three ways on three pages.
"""

from __future__ import annotations

import math
import random
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

import orjson

#: Rows per page. One number, because the reader's sense of "a page" should not
#: depend on which table they are looking at.
PAGE_SIZE = 50

T = TypeVar("T")


def load_json(raw: Any, default: Any) -> Any:
    """A JSON column as Python, or *default*.

    A SQLite row is an external payload, parsed where it is read (`AGENTS.md`),
    and these columns hold whatever the pipeline serialised into them. A column
    that is null, empty or malformed is a rendering decision, not a crash: the
    page shows the rest of the row.
    """
    if not isinstance(raw, str) or not raw.strip():
        return default
    try:
        return orjson.loads(raw.encode("utf-8"))
    except orjson.JSONDecodeError:
        return default


def alphabetical(
    options: Iterable[tuple[str, str, int]],
) -> list[tuple[str, str]]:
    """`(value, name, count)` triples as sorted `(value, label)` options.

    Every filter dropdown in this application was ordered by how many rows its
    value has, which is the order the `GROUP BY` came back in and reads as no
    order at all: `Type` offers 47 values on the build of 2026-08-20, and
    finding one of them meant reading all 47.  Alphabetical is how somebody
    looks a value up, and the count stays in the label, so the popular value is
    still recognisable -- it is just no longer the only one that is easy to
    find.

    Case-folded, because the names come from three vocabularies and only some of
    them capitalise; a case-sensitive sort files every capital before every
    lower-case letter and splits the list in two.
    """
    return [
        (value, f"{name} ({count:,})")
        for value, name, count in sorted(
            options, key=lambda option: (option[1].lower(), option[0].lower())
        )
    ]


def order_by(sort: str, columns: dict[str, str], default: str) -> str:
    """An `ORDER BY` expression from a `sort` query parameter.

    `-name` is descending, `name` ascending, anything unrecognised is *default*
    -- so a hand-edited URL cannot produce a SQL error, and cannot silently
    return rows in an order the header does not claim.

    *columns* maps a sort key to an expression, and only those expressions are
    ever interpolated: the parameter itself never reaches the query.
    """
    descending = sort.startswith("-")
    key = sort[1:] if descending else sort
    expression = columns.get(key, default)
    return f"{expression} {'DESC' if descending else 'ASC'}"


@dataclass
class Page(Generic[T]):
    """One page of rows, and enough to render the pager.

    `total` is a separate `COUNT(*)`, so "1,204 matching" is the number of rows
    the filters select rather than the number on this page.
    """

    rows: list[T] = field(default_factory=list)
    total: int = 0
    number: int = 1
    size: int = PAGE_SIZE

    @property
    def pages(self) -> int:
        return max(1, math.ceil(self.total / self.size))

    @property
    def has_previous(self) -> bool:
        return self.number > 1

    @property
    def has_next(self) -> bool:
        return self.number < self.pages

    @property
    def first_row(self) -> int:
        """1-based index of the first row on this page, for "51-100 of 1,204"."""
        return 0 if not self.total else (self.number - 1) * self.size + 1

    @property
    def last_row(self) -> int:
        return min(self.number * self.size, self.total)


def clamp_page(number: int, total: int, size: int = PAGE_SIZE) -> int:
    """A page number that exists.

    Page 9999 of 3 is the last page, not an error and not an empty table with a
    pager claiming otherwise.
    """
    pages = max(1, math.ceil(total / size))
    return max(1, min(number, pages))


#: The sentinel a view passes as `page` to mean "somewhere in the middle".
#:
#: A page number rather than a second parameter, because it travels through the
#: same argument every caller already threads, and because it cannot collide
#: with a real request: `clamp_page` turns every number below 1 into 1, so 0 has
#: never been a page anybody could ask for.
RANDOM_PAGE = 0


def resolve_page(number: int, total: int, size: int = PAGE_SIZE) -> int:
    """The page to show, opening somewhere other than the first when asked.

    Both list pages open on page 1 of a list sorted by name, so the flow objects
    a reader has seen are the ones beginning with a digit and the letter A, and
    7,700 substances behind them have never been looked at by anybody.  Landing
    somewhere else is how a browsable list gets browsed.

    Only when the reader asked for nothing at all: the moment there is a filter,
    a sort or a page in the query string, the answer to "which page" is the one
    they asked for.  The view decides that; this only carries it out.
    """
    if number != RANDOM_PAGE:
        return clamp_page(number, total, size)
    pages = max(1, math.ceil(total / size))
    return random.randint(1, pages)
