"""Which method a curated factor file is about.

Every curated file under ``data/`` that names an impact category by slug --
rulings, approvals, moves, printings, the underlying
model's numbers -- is about one method's categories.  A slug is unique inside a
method and not across methods: EF 3.1 and Stepwise 2006 both have an
``acidification``, counted in different units from different models, and they
are not the same category.  A ruling about one of them, applied to the other
because the slugs matched, would publish a number no curator ever looked at.

So each file states the method it is about, once, at the top:

```json
{"schema_version": 1, "method": "ef", "description": "…", "rulings": [...]}
```

and every loader takes an optional method to be read for.  Asked for a method
the file is not about, it returns nothing -- which is what ``characterise``
wants as it works through the methods one at a time.  Asked for nothing, it
returns everything, which is what a test and the file's own checks want.

The method has to be one the crosswalk registers, checked here.  A file about
``stepwize`` would otherwise load, match no method, and quietly rule on nothing.
"""

from __future__ import annotations

from typing import Any

from brightway_flows.domain.lcia.crosswalk import lcia_method_by_slug


def curated_method(payload: dict[str, Any], *, filename: str) -> str:
    """The method slug a curated file states.

    :raises ValueError: if the file states none, or states one no method file
        declares.
    """
    slug = str(payload.get("method") or "").strip()
    if not slug:
        raise ValueError(
            f"{filename} states no `method`, so nothing knows whose impact "
            f"categories its slugs name."
        )
    known = lcia_method_by_slug()
    if slug not in known:
        raise ValueError(
            f"{filename} is about the method {slug!r}, and the registered "
            f"methods are {', '.join(sorted(known))}."
        )
    return slug


def out_of_scope(payload: dict[str, Any], *, filename: str, method: str | None) -> bool:
    """Whether this file has nothing to say about the method being read for.

    Validates the file's own method either way, so a typo fails when the file is
    read rather than by silently answering no question (rule 14).
    """
    stated = curated_method(payload, filename=filename)
    return method is not None and stated != method
