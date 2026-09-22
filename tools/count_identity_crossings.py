"""The census of numbers that crossed from one substance to another (#156).

    uv run python tools/count_identity_crossings.py .data/consensus-flows.sqlite3
    uv run python tools/count_identity_crossings.py DB --csv crossings.csv

Reads one build and writes to nothing but the optional CSV.  For every factor of
the consensus implementation whose derivation is `restated` and whose
substance publishes no other context of the category within 2 % -- the rows
`_twin_in_the_category` settled by finding the same digits on **another
substance** -- it names the recipient, every candidate donor (a flow of the
category publishing the identical number, on a different substance), and the
relationship between the two as far as the build records it:

* ``ion-of`` / ``isotope-of``: the build's own relationship record, written by
  the element enrichment (`properties.relationships`), in either direction;
* ``same-element``: two ions of one element -- `Arsenic, Ion` and `Arsenic(5+)`
  both record arsenic as their element;
* ``origin-variant``: one is the other's `parent_flow_object_id`, or they share
  one -- fossil and biogenic carbon dioxide;
* ``land-parent``: the donor is the recipient's `parent_intervention_id`, the
  land class one qualifier up;
* ``same-cas``: the two carry a registry number in common;
* ``same-skeleton``: the same 2-D InChIKey skeleton with a different stereo
  layer -- which is what every one of #131's substituted relatives is;
* ``catch-all``: the donor is a grouping class or an imprecise mixture --
  `Herbicides, Unspecified`, `Oils, Unspecified`;
* ``unrelated``: none of the above.

The same is done for every row still on the `proposed-factor` queue, so the
curator writing `lcia-factor-adoptions.json`
(``plans/lcia-consensus-decisions.md`` §4.2 and §6) has every candidate pair in
one list.  The tool decides nothing; ``unrelated`` is a fact about the record,
not a verdict.
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from operator import itemgetter
from pathlib import Path

from brightway_flows.domain.lcia.crosswalk import CONSENSUS_IMPLEMENTATION
from brightway_flows.domain.vocabulary import CHEMINF_CAS_REGISTRY_NUMBER
from brightway_flows.lcia.consensus import RESTATED_PRECISION
from brightway_flows.flow_layers.contested_cas import FACTOR_TOLERANCE

INCHIKEY = "https://w3id.org/chemrof/inchi2d_key_string"
CATCH_ALL_TYPES = {
    "https://w3id.org/chemrof/MoleculeGroupingClass",
    "https://w3id.org/chemrof/ImpreciseChemicalMixture",
}


def _objects(connection: sqlite3.Connection) -> dict[str, dict]:
    objects: dict[str, dict] = {}
    for (
        identifier, label, classifications, properties, flow_type, parent, intervention,
    ) in connection.execute(
        "SELECT flow_object_id, pref_label_value, classifications_json, "
        "properties_json, flow_type, parent_flow_object_id, parent_intervention_id "
        "FROM flow_objects"
    ):
        classes = json.loads(classifications or "{}")
        props = json.loads(properties or "{}")
        relationship = props.get("relationships") or {}
        objects[identifier] = {
            "label": label or "",
            "cas": set((classes.get(CHEMINF_CAS_REGISTRY_NUMBER) or {}).get("@value") or ()),
            "inchikey": next(iter((props.get(INCHIKEY) or {}).get("@value") or ()), ""),
            "flow_type": flow_type or "",
            "parent": parent,
            "intervention_parent": intervention,
            "related_to": relationship.get("parent_element_flow_object_id"),
            "relationship": relationship.get("relationship_type"),
        }
    return objects


def relationship(recipient: dict, donor: dict, *, recipient_id: str, donor_id: str) -> str:
    """The recorded relationship between two substances, one word."""
    for a, b in ((recipient, donor), (donor, recipient)):
        if a["related_to"] == (donor_id if a is recipient else recipient_id):
            return {"ion_of": "ion-of", "isotope_of": "isotope-of"}.get(
                a["relationship"] or "", a["relationship"] or "related"
            )
    if recipient["related_to"] and recipient["related_to"] == donor["related_to"]:
        return "same-element"
    if recipient["parent"] == donor_id or donor["parent"] == recipient_id or (
        recipient["parent"] and recipient["parent"] == donor["parent"]
    ):
        return "origin-variant"
    if recipient["intervention_parent"] == donor_id:
        return "land-parent"
    if donor["intervention_parent"] == recipient_id:
        return "land-child"
    if recipient["cas"] & donor["cas"]:
        return "same-cas"
    if (
        recipient["inchikey"] and donor["inchikey"]
        and recipient["inchikey"] != donor["inchikey"]
        and recipient["inchikey"].split("-")[0] == donor["inchikey"].split("-")[0]
    ):
        return "same-skeleton"
    if donor["flow_type"] in CATCH_ALL_TYPES:
        return "catch-all"
    return "unrelated"


def _one_number(a: float, b: float) -> bool:
    if a == b:
        return True
    if a == 0 or b == 0 or (a > 0) != (b > 0):
        return False
    low, high = sorted((abs(a), abs(b)))
    return high / low - 1 <= FACTOR_TOLERANCE


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("database", type=Path, help="a build's consensus-flows.sqlite3")
    parser.add_argument("--csv", type=Path, help="write every (recipient, donor) row here")
    arguments = parser.parse_args(argv)
    connection = sqlite3.connect(f"file:{arguments.database}?mode=ro", uri=True)

    objects = _objects(connection)
    flows = {
        uuid: (flow_object_id, context, bool(deprecated))
        for uuid, flow_object_id, context, deprecated in connection.execute(
            "SELECT uuid, flow_object_id, context_display, is_deprecated FROM elementary_flows"
        )
    }
    categories = {
        identifier: (name, implemented_by)
        for identifier, name, implemented_by in connection.execute(
            "SELECT c.id, c.name || ' (' || m.name || ')', c.implemented_by "
            "FROM lcia_impact_categories c JOIN lcia_methods m ON m.id = c.method_id"
        )
    }
    #: (category, geography) → sorted (amount, uuid); and per substance the
    #: published contexts, to find same-substance donors first.
    published: dict[tuple[str, str], list[tuple[float, str]]] = defaultdict(list)
    by_substance: dict[tuple[str, str, str], dict[str, float]] = defaultdict(dict)
    restated: list[tuple[str, str, str, float]] = []
    for category_id, uuid, geography, amount, derivation in connection.execute(
        "SELECT impact_category_id, elementary_flow_uuid, geography, amount, derivation "
        "FROM lcia_characterization_factors"
    ):
        name, implemented_by = categories[category_id]
        if implemented_by != CONSENSUS_IMPLEMENTATION:
            continue
        substance, context, _ = flows[uuid]
        published[(name, geography or "")].append((amount, uuid))
        by_substance[(name, geography or "", substance)][uuid] = amount
        if derivation == "restated":
            restated.append((name, geography or "", uuid, amount))
    for entries in published.values():
        entries.sort()

    rows: list[dict] = []
    for name, geography, uuid, amount in restated:
        substance, context, _ = flows[uuid]
        others = by_substance[(name, geography, substance)]
        if any(other != uuid and _one_number(value, amount) for other, value in others.items()):
            continue  # the same substance next door: a context restatement, not this census
        if not amount:
            continue
        entries = published[(name, geography)]
        low, high = sorted((amount * (1 - RESTATED_PRECISION), amount * (1 + RESTATED_PRECISION)))
        start = bisect_left(entries, low, key=itemgetter(0))
        end = bisect_right(entries, high, key=itemgetter(0))
        donors = {
            flows[other][0] for _, other in entries[start:end] if flows[other][0] != substance
        }
        for donor in sorted(donors):
            rows.append({
                "category": name,
                "geography": geography,
                "recipient_id": substance,
                "recipient": objects.get(substance, {}).get("label", substance),
                "context": context,
                "amount": amount,
                "donor_id": donor,
                "donor": objects.get(donor, {}).get("label", donor),
                "relationship": relationship(
                    objects.get(substance, {}), objects.get(donor, {}),
                    recipient_id=substance, donor_id=donor,
                ) if substance in objects and donor in objects else "unknown-object",
                "candidates": len(donors),
                "source": "restated",
            })

    # And the queue: what is still proposed, and whose number each row could be.
    for item_key, payload in connection.execute(
        "SELECT item_key, payload_json FROM review_queue WHERE queue_name = 'proposed-factor'"
    ):
        data = json.loads(payload)
        for row in data.get("rows") or ():
            uuid = row.get("elementary_flow_uuid") or ""
            if uuid not in flows:
                continue
            substance, context, _ = flows[uuid]
            for stated in row.get("stated") or ():
                amount = stated.get("amount")
                if not amount:
                    continue
                for (name, geography), entries in published.items():
                    if not name.startswith(str(data.get("category") or "")):
                        continue
                    if geography != (row.get("geography") or ""):
                        continue
                    low, high = sorted((amount * (1 - RESTATED_PRECISION), amount * (1 + RESTATED_PRECISION)))
                    start = bisect_left(entries, low, key=itemgetter(0))
                    end = bisect_right(entries, high, key=itemgetter(0))
                    donors = {flows[o][0] for _, o in entries[start:end] if flows[o][0] != substance}
                    for donor in sorted(donors):
                        rows.append({
                            "category": name, "geography": geography,
                            "recipient_id": substance,
                            "recipient": objects.get(substance, {}).get("label", substance),
                            "context": context, "amount": amount,
                            "donor_id": donor, "donor": objects.get(donor, {}).get("label", donor),
                            "relationship": relationship(
                                objects[substance], objects[donor],
                                recipient_id=substance, donor_id=donor,
                            ) if substance in objects and donor in objects else "unknown-object",
                            "candidates": len(donors), "source": f"queue:{item_key}",
                        })

    by_relationship: Counter[str] = Counter()
    substances: dict[str, set[str]] = defaultdict(set)
    factors: dict[str, set[tuple[str, str, str, str]]] = defaultdict(set)
    for row in rows:
        key = (row["category"], row["geography"], row["recipient_id"], row["context"])
        factors[row["relationship"]].add(key)
        substances[row["relationship"]].add(row["recipient_id"])
    header = f"{'relationship':16s} {'factors':>8s} {'substances':>11s}"
    print(header)
    print("-" * len(header))
    for name in sorted(factors, key=lambda k: -len(factors[k])):
        print(f"{name:16s} {len(factors[name]):8d} {len(substances[name]):11d}")
    print(f"{'pairs':16s} {len(rows):8d}")
    multi = {k for k in {(r['category'], r['geography'], r['recipient_id'], r['context']) for r in rows if r['candidates'] > 1}}
    print(f"rows with more than one candidate donor: {len(multi)}")

    if arguments.csv:
        with arguments.csv.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else ["category"])
            writer.writeheader()
            writer.writerows(rows)
        print(f"wrote {len(rows)} rows to {arguments.csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
