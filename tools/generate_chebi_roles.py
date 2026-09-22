"""Regenerate ``data/chebi-roles.json``, the allow-list of publishable roles.

ChEBI's role tree has 51 descendants under `pesticide` alone and several
thousand overall, most of them biomedical -- `mouse metabolite`,
`EC 3.1.1.7 (acetylcholinesterase) inhibitor`. None of that groups anything an
LCA asks about, so the roles this project publishes are allow-listed and the
allow-list is a data file.

What is *in* the list is a judgement, made once and recorded in
`plans/pesticide-taxonomy.md` with the measurements behind each inclusion and
each rejection. What is in each row -- label, definition, ChEBI parents -- is
not a judgement, and is read from the shipped `chebi.json.gz` by this tool so
that a typo cannot enter it and so that a ChEBI release can be absorbed by
re-running rather than by hand-editing fourteen definitions.

    uv run python tools/generate_chebi_roles.py [--check]

`--check` regenerates in memory and exits non-zero if the shipped file differs,
which is what `tests/test_chebi_roles.py` runs.
"""

from __future__ import annotations

import argparse
import collections
import gzip
import sys
from pathlib import Path

import orjson

from brightway_flows.domain.vocabulary import Namespace, RO_HAS_ROLE_IRI
from brightway_flows.filesystem import CHEBI_JSON_GZ_FILEPATH

OUTPUT_PATH = (
    Path(__file__).resolve().parent.parent
    / "src" / "brightway_flows" / "data" / "chebi-roles.json"
)

#: From the registry, not a literal.  `tests/test_vocabulary.py` refuses a
#: second declaration of a registered IRI but scans `src/` only, so a copy here
#: would drift silently -- which is the whole failure that test exists to stop.
OBO = Namespace.OBO.value

#: The allow-list itself: ChEBI accession -> family. Order within a family is
#: the order rows are written, so it is the order a reader sees.
#:
#: Two families, chosen against measured bearer counts over the published list.
#: `plans/pesticide-taxonomy.md` records the counts, and records the four roles
#: measured and rejected -- `greenhouse gas` (no HFC or PFC in the list carries
#: it), `antifungal agrochemical` (a strict subset of `fungicide`), `xenobiotic`
#: (duplicates `environmental contaminant`) and `poison` (incoherent) -- so that
#: adding one later is a decision rather than an oversight.
ALLOWED: dict[str, str] = {
    # A -- agrochemical use. The three low-count nodes are kept although eight
    # bearers each would not otherwise earn a row: this is the one branch where
    # partial coverage actively misleads, because a reader who finds `acaricide`
    # and no `rodenticide` concludes the list holds no rodenticides.
    "CHEBI_25944": "agrochemical_use",   # pesticide
    "CHEBI_33286": "agrochemical_use",   # agrochemical
    "CHEBI_24527": "agrochemical_use",   # herbicide
    "CHEBI_24127": "agrochemical_use",   # fungicide
    "CHEBI_24852": "agrochemical_use",   # insecticide
    "CHEBI_22153": "agrochemical_use",   # acaricide
    "CHEBI_26155": "agrochemical_use",   # plant growth regulator
    "CHEBI_25491": "agrochemical_use",   # nematicide
    "CHEBI_33287": "agrochemical_use",   # fertilizer
    "CHEBI_33288": "agrochemical_use",   # rodenticide
    "CHEBI_33904": "agrochemical_use",   # molluscicide
    "CHEBI_22583": "agrochemical_use",   # antifeedant
    # B -- environmental fate.
    "CHEBI_78298": "environmental_fate",  # environmental contaminant
    "CHEBI_77853": "environmental_fate",  # persistent organic pollutant
}


def _load_graph() -> dict:
    return orjson.loads(gzip.open(CHEBI_JSON_GZ_FILEPATH, "rb").read())["graphs"][0]


def build() -> dict:
    graph = _load_graph()
    nodes = {node["id"]: node for node in graph["nodes"]}
    parents: dict[str, set[str]] = collections.defaultdict(set)
    for edge in graph["edges"]:
        if edge["pred"] == "is_a":
            parents[edge["sub"]].add(edge["obj"])

    rows = []
    for accession, family in ALLOWED.items():
        iri = f"{OBO}{accession}"
        node = nodes.get(iri)
        if node is None:
            raise SystemExit(
                f"{accession} is not in {CHEBI_JSON_GZ_FILEPATH.name}. The "
                "allow-list names a class this ChEBI release does not have; "
                "check the accession before removing the row."
            )
        meta = node.get("meta", {})
        # Only parents that are themselves allow-listed. A consumer that wants
        # ChEBI's full tree resolves the IRIs; what is useful here is the tree
        # *within* what we publish, so a reader can roll `herbicide` up to
        # `pesticide` without a second lookup.
        broader = sorted(
            parent for parent in parents.get(iri, ())
            if parent.rsplit("/", 1)[-1] in ALLOWED
        )
        rows.append({
            "iri": iri,
            "curie": accession.replace("_", ":"),
            "label": node.get("lbl"),
            "definition": (meta.get("definition") or {}).get("val") or None,
            "broader": broader,
            "family": family,
        })

    return {
        "schema_version": 1,
        "description": (
            "Roles this project publishes on a flow object, as `RO:0000087 has "
            "role`. An allow-list over ChEBI's role tree, whose majority is "
            "biomedical and groups nothing an LCA asks about. Labels, "
            "definitions and `broader` are read from chebi.json.gz by "
            "tools/generate_chebi_roles.py; the membership is a judgement "
            "recorded in plans/pesticide-taxonomy.md."
        ),
        "predicate": RO_HAS_ROLE_IRI,
        "roles": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true",
        help="exit non-zero if the shipped file differs from a fresh build",
    )
    args = parser.parse_args()

    payload = orjson.dumps(
        build(), option=orjson.OPT_INDENT_2 | orjson.OPT_APPEND_NEWLINE
    )
    if args.check:
        if not OUTPUT_PATH.exists():
            print(f"{OUTPUT_PATH} does not exist", file=sys.stderr)
            return 1
        if OUTPUT_PATH.read_bytes() != payload:
            print(
                f"{OUTPUT_PATH.name} differs from a fresh build; re-run "
                "tools/generate_chebi_roles.py",
                file=sys.stderr,
            )
            return 1
        return 0

    OUTPUT_PATH.write_bytes(payload)
    print(f"wrote {OUTPUT_PATH} ({len(orjson.loads(payload)['roles'])} roles)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
