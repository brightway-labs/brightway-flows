"""Resolve every anchor the land-class scheme cites, and pin it.

The sibling of `tools/resolve_material_anchors.py`, and for the same reason: an
accession is eight digits, a typo in one of them is a different published class
that still resolves, and nothing in the repository can tell the two apart. So
the citations in `domain/land_use_anchors.py` are resolved against their
authorities and the answers written to `data/land-anchor-snapshot.json`, which a
test compares the module against. A mistyped accession then fails the suite
**offline**, and a label that drifts upstream shows up in a reviewable diff.

**Three authorities, and the third is read differently.**

ENVO and AGROVOC resolve exactly as they do for the material taxonomy -- OLS4
and the AGROVOC Skosmos REST API.

IUCN GET does not have a resolver to query. It has something better and worse:
a **published SKOS file**, CC-BY, under version control, at
`Ecosystem-Indicators-Workflows/IUCN-GET-vocabulary` -- 110 ecosystem functional
groups, 25 biomes and 11 realms, with `skos:prefLabel`, `skos:notation`,
`skos:broader` and a `dcterms:identifier` under the registered permanent
namespace `w3id.org/iucn-get`. Better because the whole vocabulary arrives at
once and cannot be half-fetched; worse because the w3id currently redirects to an
ARDC *demo* server on a path containing the word `example`, and the vocabulary's
own README still marks "register the vocabulary" as in progress.

That is exactly why the snapshot exists. We cite the w3id, read the published
Turtle, record its SHA-256 so the file we read is identifiable, and depend on
none of it at run time. When the registration lands, re-run this and the diff
will be the labels, not the design.

Usage::

    uv run python tools/resolve_land_anchors.py            # refresh
    uv run python tools/resolve_land_anchors.py --check    # diff, exit 1

Network is required to refresh. Nothing else in the build reaches out.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import urllib.request
from pathlib import Path
from typing import Any

from brightway_flows.domain.land_use_anchors import (
    Authority,
    check_cover_authority,
    check_every_value_is_decided,
    cited_identifiers,
)

# The material taxonomy's resolvers, imported rather than re-implemented.  ENVO
# and AGROVOC do not answer differently because a second scheme is asking, and
# two copies of an OLS4 client is two places for the same bug -- the plan asked
# for this file to *grow* a second scheme rather than be copied.  A sibling
# import works because `tools/` is on `sys.path` when a script in it is run.
from resolve_material_anchors import resolve_agrovoc, resolve_envo

REPO_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_PATH = (
    REPO_ROOT / "src" / "brightway_flows" / "data" / "land-anchor-snapshot.json"
)

#: The published SKOS export, pinned to the dated file rather than to a moving
#: branch name -- a vocabulary that changed under us without the URL changing is
#: the failure the snapshot is meant to make visible.
GET_TURTLE_URL = (
    "https://raw.githubusercontent.com/Ecosystem-Indicators-Workflows/"
    "IUCN-GET-vocabulary/main/output/IUCN-GET-profiles-exported-2026-04-01_skos.ttl"
)


def resolve_get(identifiers: set[str]) -> tuple[dict[str, Any], str]:
    """Every cited GET concept, read out of the published Turtle.

    Parsed with a regex rather than an RDF library on purpose: this project has
    no RDF parser in its dependencies, the file's shape is one flat block per
    concept, and a parser would be a dependency added to read five fields. The
    parse is checked by the resolver itself -- a concept the regex misses is a
    concept missing from the snapshot, which fails the run.
    """
    request = urllib.request.Request(
        GET_TURTLE_URL, headers={"Accept": "text/turtle"}
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        body = response.read()
    digest = hashlib.sha256(body).hexdigest()
    text = body.decode("utf-8")

    resolved: dict[str, Any] = {}
    for block in re.split(r"\n(?=base:)", text):
        match = re.match(r"base:(\S+) ", block)
        if match is None or match.group(1) not in identifiers:
            continue
        local = match.group(1)
        notation = re.search(r'skos:notation "([^"]+)"', block)
        label = re.search(r'skos:prefLabel "([^"]+)"@en', block)
        scope = re.search(r'skos:scopeNote """?(.*?)"""?@en', block, re.DOTALL)
        broader = re.findall(r"skos:broader base:(\S+?)[\s,;]", block)
        resolved[local] = {
            "iri": f"https://w3id.org/iucn-get/{local}",
            "notation": notation.group(1) if notation else "",
            "label": label.group(1) if label else "",
            "definition": " ".join(scope.group(1).split()) if scope else "",
            "parents": [{"id": parent, "label": ""} for parent in broader],
        }

    missing = identifiers - set(resolved)
    if missing:
        raise LookupError(f"not in the GET Turtle: {sorted(missing)}")
    return resolved, digest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="diff instead of writing")
    args = parser.parse_args()

    # The scheme has to be internally consistent before it is worth resolving.
    check_cover_authority()
    check_every_value_is_decided()

    cited = cited_identifiers()
    envo = {
        accession: resolve_envo(accession)
        for accession in sorted(cited[Authority.ENVO])
    }
    agrovoc = {
        concept: resolve_agrovoc(concept)
        for concept in sorted(cited[Authority.AGROVOC])
    }
    get, digest = resolve_get(cited[Authority.GET])

    payload = {
        "schema_version": 1,
        "description": (
            "What ENVO, IUCN GET and AGROVOC say about every class "
            "domain/land_use_anchors.py cites. Generated by "
            "tools/resolve_land_anchors.py; a test compares the module against "
            "this, so a mistyped accession fails offline. ENVO types the "
            "terrestrial cover, GET the aquatic cover, AGROVOC the regime."
        ),
        "sources": {
            "envo": "EBI OLS4, https://www.ebi.ac.uk/ols4/api",
            "agrovoc": "AGROVOC Skosmos, https://agrovoc.fao.org/browse/rest/v1",
            "get": GET_TURTLE_URL,
        },
        "get_turtle_sha256": digest,
        "envo": envo,
        "get": get,
        "agrovoc": agrovoc,
    }
    rendered = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"

    if args.check:
        current = SNAPSHOT_PATH.read_text() if SNAPSHOT_PATH.exists() else ""
        if current != rendered:
            print(f"{SNAPSHOT_PATH} is out of date; re-run without --check")
            return 1
        print(f"{SNAPSHOT_PATH} is up to date")
        return 0

    SNAPSHOT_PATH.write_text(rendered)
    print(f"{len(envo)} ENVO, {len(get)} GET, {len(agrovoc)} AGROVOC -> {SNAPSHOT_PATH}")
    print(f"  GET Turtle sha256 {digest[:16]}…")
    for accession, term in sorted(envo.items()):
        if term["obsolete"]:
            print(f"  OBSOLETE upstream: {accession} {term['label']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
