#!/usr/bin/env python
"""Every published name whose case is not the case its source list shipped.

`bootstrap_labels` copies a source list's own name onto a flow object that has
no label.  `normalize_name_case` then rewrites it: each whitespace-separated
word whose first character is a letter is capitalised and the rest of the word
is lowercased, unless the word already carries a capital beyond its first
character.  That rule is right for `potassium chloride` and wrong for most of
chemical nomenclature, because a chemical name is not a title:

    (2,4-dichlorophenoxy)acetic acid   ->  (2,4-dichlorophenoxy)acetic Acid
    trans-nonachlor                    ->  Trans-nonachlor
    p-toluidine                        ->  P-toluidine
    pcb-18                             ->  Pcb-18
    carbon dioxide (land use change)   ->  Carbon Dioxide (land Use Change)

The last one is the shape that gives the pass away: `(land` begins with a
parenthesis, so the rule leaves it alone, and capitalises the two words after
it.

This tool does not fix anything.  It counts what a fix would touch and groups
it by the decision the group needs, because the groups do not want the same
answer -- `N-nitroso` is a capital in IUPAC and `n-butyl` is not, and both
reach here as one source word beginning `n-`.

    uv run python tools/survey_name_case.py
    uv run python tools/survey_name_case.py --write survey.md

It reads a build's database and the source list's own extract, so what it
reports is a property of that build; name the build when quoting a number from
it (`AGENTS.md` rule 31).
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from brightway_flows.filesystem import CONSENSUS_DB_FILEPATH  # noqa: E402
from brightway_flows.sources import base_source_list, resolve_source_list  # noqa: E402

#: Words that stay lowercase wherever they appear in a chemical name.
STEREO_WORDS = (
    "cis", "trans", "alpha", "beta", "gamma", "delta", "ortho", "meta", "para",
    "sec", "tert", "exo", "endo", "syn", "anti", "iso", "neo", "epi", "erythro",
    "threo", "rac", "racemic", "ar", "tri", "bis", "tris",
)
#: Single-letter prefixes that stay lowercase: `n-butane`, `p-xylene`.
LOWERCASE_PREFIXES = set("nopmdl")
#: Single-letter prefixes that are capitals: `N-nitroso`, `R-`, `E-`, `Z-`.
CAPITAL_PREFIXES = set("nosrezc")
#: Acronyms and codes a word-by-word capitalisation flattens.
ACRONYMS = {
    "pcb", "pcdd", "pcdf", "pah", "ddt", "ddd", "dde", "hch", "hcb", "hcfc",
    "cfc", "hfc", "pfc", "voc", "nmvoc", "pm", "tsp", "bod", "cod", "doc",
    "toc", "aox", "mtbe", "edta", "nta", "dehp", "las", "tbt", "tcdd", "btex",
    "pcp", "pbde", "pfos", "pfoa", "hbcd", "bpa", "dnoc", "mcpa", "mcpb",
}

GROUPS = {
    "A": "one-word name, first letter capitalised",
    "A2": "first word of a multi-word name capitalised",
    "B": "interior word capitalised (…acetic Acid)",
    "C": "stereo or position prefix capitalised (Cis-, Alpha-)",
    "C2": "single-letter prefix that stays lowercase (p-, m-)",
    "C3": "single-letter prefix where the capital may be right (N-, R-)",
    "D": "acronym or code flattened (Pcb-1254)",
    "E": "parenthetical left lowercase beside capitalised words",
    "F": "capitals the source shipped were flattened",
    "Y": "unclassified",
    "Z": "word count changed",
}

_LEADING_NON_LETTERS = re.compile(r"^[^A-Za-z]+")
_MIXED_PARENTHETICAL = re.compile(r"\([a-z][^)]*?\b[A-Z][a-z]")
_STEREO_PARENTHETICAL = re.compile(r"\((?:[+-]?)[rsez]{1,2}\)")
_ACRONYM_SHAPED = re.compile(r"[a-z]{2,5}\d+")


def _stem(word: str) -> str:
    """The word without its leading brackets, signs and locants."""
    return _LEADING_NON_LETTERS.sub("", word)


def groups_for(shipped: str, published: str) -> set[str]:
    """Which review groups this one name belongs in.

    A name can be in several: `2-butenedioic acid (2e)-, di-c16-18 (even
    numbered)-alkyl esters` has an interior word capitalised *and* two
    parentheticals the rule could not reach.
    """
    found: set[str] = set()
    before_words, after_words = shipped.split(), published.split()
    if len(before_words) != len(after_words):
        return {"Z"}

    for index, (before, after) in enumerate(zip(before_words, after_words)):
        if before == after:
            continue
        stem = _stem(before)
        head = stem.split("-", 1)[0].lower()

        if any(character.isupper() for character in before) and before.lower() == after.lower():
            found.add("F")
        if head in ACRONYMS or _ACRONYM_SHAPED.fullmatch(head):
            found.add("D")
        elif head in STEREO_WORDS and "-" in stem:
            found.add("C")
        elif len(head) == 1 and "-" in stem:
            if head in LOWERCASE_PREFIXES and head not in CAPITAL_PREFIXES:
                found.add("C2")
            else:
                found.add("C3")
        elif index > 0:
            found.add("B")
        elif len(before_words) == 1:
            found.add("A")
        else:
            found.add("A2")

    if _MIXED_PARENTHETICAL.search(published) or _STEREO_PARENTHETICAL.search(published):
        found.add("E")
    return found or {"Y"}


def shipped_names(source_key: str | None) -> tuple[str, dict[str, str]]:
    """The list's name, and uuid -> the name it ships, from its own extract."""
    source = resolve_source_list(source_key) if source_key else base_source_list()
    flows = json.loads(source.flows_path.read_text())
    if isinstance(flows, dict):
        flows = flows.get("flows", [])
    return str(source), {
        flow["uuid"]: flow["name"]
        for flow in flows
        if flow.get("uuid") and flow.get("name")
    }


def published_names(database: Path) -> tuple[dict[str, str], dict[str, str]]:
    """uuid -> published flow-object label, and uuid -> flow object id."""
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            """
            select elementary_flows.uuid,
                   elementary_flows.flow_object_id,
                   flow_objects.pref_label_value
            from elementary_flows
            join flow_objects
              on flow_objects.flow_object_id = elementary_flows.flow_object_id
            """
        ).fetchall()
    finally:
        connection.close()
    return (
        {uuid: label or "" for uuid, _object_id, label in rows},
        {uuid: object_id for uuid, object_id, _label in rows},
    )


def sibling_disagreements(
    shipped: dict[str, str], labels: dict[str, str], objects: dict[str, str]
) -> list[tuple[int, str, str]]:
    """Flow objects the source list itself already spells better.

    The source ships one substance twice -- once with the capitals a chemist
    would write, once flattened -- and the published label followed the
    flattened row.  Nothing has to be decided to correct these.
    """
    spellings: dict[str, set[str]] = collections.defaultdict(set)
    rows: collections.Counter = collections.Counter()
    for uuid, name in shipped.items():
        object_id = objects.get(uuid)
        if object_id is None:
            continue
        spellings[object_id].add(name)
        rows[object_id] += 1

    found = []
    for object_id, names in spellings.items():
        if len(names) < 2 or len({name.lower() for name in names}) != 1:
            continue
        label = next(
            (labels[uuid] for uuid, oid in objects.items() if oid == object_id), ""
        )
        best = max(names, key=lambda name: sum(1 for c in name if c.isupper()))
        if label != best and label.lower() == best.lower():
            found.append((rows[object_id], label, best))
    return sorted(found, key=lambda entry: -entry[0])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database", type=Path, default=CONSENSUS_DB_FILEPATH)
    parser.add_argument("--source", help="the source list to compare against; the base list by default")
    parser.add_argument("--write", type=Path, help="write the full list to this Markdown file")
    args = parser.parse_args(argv)

    if not args.database.is_file():
        print(f"no database at {args.database}; run a build first")
        return 1

    source_name, shipped = shipped_names(args.source)
    labels, objects = published_names(args.database)

    pairs: collections.Counter = collections.Counter()
    identical = renamed = unpublished = 0
    for uuid, name in shipped.items():
        label = labels.get(uuid)
        if label is None:
            unpublished += 1
        elif label == name:
            identical += 1
        elif label.lower() == name.lower():
            pairs[(name, label)] += 1
        else:
            renamed += 1

    print(f"{source_name}: {len(shipped)} rows in the source extract")
    print(f"  published exactly as shipped:            {identical}")
    print(f"  published under a different name:        {renamed}")
    print(f"  not published:                           {unpublished}")
    print(f"  published in another case:               {sum(pairs.values())}"
          f" rows, {len(pairs)} distinct names\n")

    grouped: dict[str, list[tuple[str, str, int]]] = collections.defaultdict(list)
    for (name, label), rows in pairs.items():
        for group in groups_for(name, label):
            grouped[group].append((name, label, rows))

    for key in sorted(grouped):
        entries = grouped[key]
        print(f"{len(entries):5d} names {sum(r for _n, _l, r in entries):7d} rows  "
              f"{key}. {GROUPS.get(key, key)}")

    siblings = sibling_disagreements(shipped, labels, objects)
    print(f"\n{len(siblings)} flow objects, {sum(rows for rows, *_ in siblings)} rows, "
          "where the source list itself ships a better case")

    if args.write:
        with args.write.open("w") as handle:
            handle.write(f"# {source_name} names published in another case\n\n")
            handle.write(f"{len(pairs)} distinct names, {sum(pairs.values())} flow rows, "
                         f"from `{args.database}`.\n")
            for key in sorted(grouped):
                entries = sorted(grouped[key], key=lambda entry: -entry[2])
                handle.write(f"\n## {key}. {GROUPS.get(key, key)} — {len(entries)} names, "
                             f"{sum(r for _n, _l, r in entries)} rows\n\n")
                handle.write("| rows | shipped | published |\n|---|---|---|\n")
                for name, label, rows in entries:
                    handle.write(f"| {rows} | `{name}` | `{label}` |\n")
            handle.write(f"\n## The source list already spells these better — "
                         f"{len(siblings)} flow objects\n\n")
            handle.write("| rows | published | also shipped as |\n|---|---|---|\n")
            for rows, label, best in siblings:
                handle.write(f"| {rows} | `{label}` | `{best}` |\n")
        print(f"wrote {args.write}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
