"""The census of our taxonomy's blanks, per class and per pair of contexts.

    uv run python tools/count_context_blanks.py .data/consensus-flows.sqlite3
    uv run python tools/count_context_blanks.py DB --method ef --class "fresh water"
    uv run python tools/count_context_blanks.py DB --csv census.csv

Reads one build and writes to nothing but the optional CSV.  For every method
and every class of our context taxonomy -- soil, fresh water, air, resource
water -- it prints one table of ordered (donor → recipient) pairs:

* ``blanks``: substances published in the donor with a live flow in the
  recipient and nothing stated there by any deciding implementation;
* ``both`` / ``agree``: where both contexts are published, how often the two
  numbers are one number within 2 %;
* ``restated``: where the recipient's number is ecoinvent's own statement for a
  compartment EF cannot express (`derivation: restated`), how many of those
  match the donor's number -- which context ecoinvent actually copied from;
* ``relation``: what the taxonomy says -- the donor is broader, narrower, or a
  sibling.

And one table per class of recipients: how many blanks each context holds over
every donor, and how many of those have exactly one published context to copy
from.

Then, per method, the blanks beside a *substance* rather than a context: every
ion with a live flow, no factor on it, and its element characterised in the same
context and category -- `Zinc(2+)` beside `Zinc` under Stepwise 2006 (#197).
Those are the input to an `ion-of` entry in the adoptions file, not to the
convention: a number crossing a substance is signed or not published.

The tables are the input to ``data/context-carry-rules.json``
(``plans/lcia-consensus-decisions.md`` §4.1 and §5); the tool decides nothing.
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path

from brightway_flows.domain.lcia.crosswalk import (
    CONSENSUS_IMPLEMENTATION,
    lcia_method_by_slug,
)
from brightway_flows.lcia.census import (
    ARROW,
    BlankContext,
    ContextPair,
    IdentityBlank,
    PublishedFactor,
    context_census,
    identity_census,
)
from brightway_flows.lcia.sources import substance_relatives


def _flows(connection: sqlite3.Connection) -> dict[str, dict]:
    return {
        uuid: {
            "flow_object_id": flow_object_id,
            "label": label or "",
            "context_display": context,
            "context_iri": context_iri or "",
            "deprecated": bool(deprecated),
        }
        for uuid, flow_object_id, label, context, context_iri, deprecated in connection.execute(
            "SELECT uuid, flow_object_id, pref_label_value, context_display, "
            "context_iri, is_deprecated FROM elementary_flows"
        )
    }


def _deciding_names() -> dict[str, set[str]]:
    """Which implementation names decide, per method slug, from the method files."""
    return {
        slug: {implementation.name for implementation in method.deciding}
        for slug, method in lcia_method_by_slug().items()
    }


def _factors(
    connection: sqlite3.Connection,
) -> tuple[dict[str, list[PublishedFactor]], dict[str, set[tuple[str, str, str]]]]:
    """Per method slug: the consensus factors, and what the deciding
    implementations state."""
    deciding = _deciding_names()
    #: category id → (method slug, category slug, implemented_by)
    categories: dict[str, tuple[str, str, str]] = {}
    for identifier, iri, implemented_by in connection.execute(
        "SELECT c.id, c.iri, c.implemented_by FROM lcia_impact_categories c"
    ):
        # …/impact-category/<method>/<version>/<implementation>/<timeframe>/<slug>
        parts = iri.rsplit("/", 5)
        categories[identifier] = (parts[1], parts[5], implemented_by)
    published: dict[str, list[PublishedFactor]] = defaultdict(list)
    stated: dict[str, set[tuple[str, str, str]]] = defaultdict(set)
    for category_id, uuid, geography, amount, derivation in connection.execute(
        "SELECT impact_category_id, elementary_flow_uuid, geography, amount, "
        "derivation FROM lcia_characterization_factors"
    ):
        method, slug, implemented_by = categories[category_id]
        if implemented_by == CONSENSUS_IMPLEMENTATION:
            published[method].append(
                PublishedFactor(uuid, slug, geography or "", amount, derivation)
            )
        elif implemented_by in deciding.get(method, set()):
            stated[method].add((uuid, slug, geography or ""))
    return published, stated


def _short(display: str) -> str:
    return ARROW.join(display.split(ARROW)[2:])


def _print_pairs(rows: list[ContextPair]) -> None:
    header = (
        f"{'donor':44s} {'recipient':44s} {'relation':9s} {'blanks':>7s} "
        f"{'both':>7s} {'agree':>6s} {'restated':>9s} {'match':>6s}"
    )
    print(header)
    print("-" * len(header))
    for row in rows:
        agreement = f"{row.agreement:.0%}" if row.agreement is not None else "—"
        print(
            f"{_short(row.donor):44s} {_short(row.recipient):44s} "
            f"{str(row.relation):9s} {row.blanks:7d} {row.both:7d} {agreement:>6s} "
            f"{row.restated_rows:9d} {row.restated_matches:6d}"
        )


def _print_recipients(rows: list[BlankContext]) -> None:
    header = f"{'recipient':60s} {'blanks':>7s} {'one donor':>10s}"
    print(header)
    print("-" * len(header))
    for row in rows:
        print(f"{_short(row.recipient):60s} {row.blanks:7d} {row.single_donor:10d}")
    print(f"{'total':60s} {sum(row.blanks for row in rows):7d}")


def _print_identity(rows: list[IdentityBlank]) -> None:
    header = f"{'substance':28s} {'takes from':20s} {'blanks':>7s} {'contexts':>9s} {'categories':>11s}"
    print(header)
    print("-" * len(header))
    for row in rows:
        print(
            f"{row.recipient_label:28s} {row.relationship + ' ' + row.donor_label:20s} "
            f"{row.blanks:7d} {row.contexts:9d} {row.categories:11d}"
        )
    print(f"{'total':28s} {'':20s} {sum(row.blanks for row in rows):7d}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("database", type=Path, help="a build's consensus-flows.sqlite3")
    parser.add_argument("--method", action="append", help="only this method slug; repeatable")
    parser.add_argument(
        "--class", dest="classes", action="append",
        help="only this class: soil, 'fresh water', air, 'resource water'; repeatable",
    )
    parser.add_argument("--csv", type=Path, help="also write every pair row here")
    arguments = parser.parse_args(argv)

    connection = sqlite3.connect(f"file:{arguments.database}?mode=ro", uri=True)
    flows = _flows(connection)
    published, stated = _factors(connection)
    relatives = substance_relatives(arguments.database)

    every_pair: list[ContextPair] = []
    for method in sorted(published):
        if arguments.method and method not in arguments.method:
            continue
        pairs, recipients = context_census(
            method=method,
            published=published[method],
            stated=stated.get(method, set()),
            flows=flows,
        )
        every_pair.extend(pairs)
        classes = sorted({row.context_class for row in pairs}, key=str)
        for context_class in classes:
            if arguments.classes and str(context_class) not in arguments.classes:
                continue
            print(f"\n== {method}: {context_class} ==\n")
            _print_pairs([row for row in pairs if row.context_class == context_class])
            print()
            _print_recipients(
                [row for row in recipients if row.context_class == context_class]
            )
        if not arguments.classes:
            print(f"\n== {method}: blank beside the element ==\n")
            _print_identity(
                identity_census(
                    method=method,
                    published=published[method],
                    stated=stated.get(method, set()),
                    flows=flows,
                    relatives=relatives,
                )
            )

    if arguments.csv:
        with arguments.csv.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(asdict(every_pair[0])) + ["agreement"])
            writer.writeheader()
            for row in every_pair:
                writer.writerow({**asdict(row), "agreement": row.agreement})
        print(f"\nwrote {len(every_pair)} pair rows to {arguments.csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
