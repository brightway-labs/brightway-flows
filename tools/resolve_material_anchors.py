"""Resolve every external anchor the material taxonomy cites, and pin it.

`environmental-materials.json` says a node is `ENVO:00002149 sea water` or
`agrovoc:c_5867fbf1 green water`.  Nothing in the repository can check that: an
accession is eight digits and a typo in one of them is a different published
class, with a different definition, that still resolves.  So the assertions are
resolved against their authorities and the answers written to
`data/material-anchor-snapshot.json`, which a test compares the data files
against.  A mistyped accession then fails the suite **offline**, and a label or
definition that drifts upstream is visible in a reviewable diff rather than
discovered by a reader.

**Two authorities, because one does not cover it.**  ENVO types the material --
what the stuff is -- and is reachable through the EBI's OLS4.  AGROVOC types the
accounting category -- how a method counts it -- and is a SKOS thesaurus that
**OLS does not index**, so it needs its own resolver against the AGROVOC Skosmos
REST API.  Two resolvers is the price of anchoring the accounting categories at
all, and the alternative is writing our own definition of green water next to a
published one that already says the same thing.

What is pinned is what a reader would want to check: the label, the definition,
and the parents.  Parents matter more than they look -- the taxonomy asserts
`lake water skos:broader surface water`, which ENVO does *not*, and the only way
to keep that honest is to record what ENVO actually says so the divergence is
visible rather than merely absent.

Usage::

    uv run python tools/resolve_material_anchors.py            # refresh
    uv run python tools/resolve_material_anchors.py --check    # diff, exit 1

Network is required to refresh.  Nothing else in the build reaches out: the
snapshot is package data and the test reads it.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_PATH = (
    REPO_ROOT / "src" / "brightway_flows" / "data" / "material-anchor-snapshot.json"
)

OLS4_TERM = "https://www.ebi.ac.uk/ols4/api/ontologies/{ontology}/terms"
OLS4_PARENTS = (
    "https://www.ebi.ac.uk/ols4/api/ontologies/{ontology}/terms/{encoded}/parents"
)
AGROVOC_DATA = "https://agrovoc.fao.org/browse/rest/v1/agrovoc/data"

#: Every ENVO class the water taxonomy cites, by accession.  Listed here rather
#: than read from the data file so the resolver can run before that file exists,
#: and so adding an anchor is a deliberate edit in one place.
ENVO_ACCESSIONS = (
    "ENVO_00002006",  # liquid water -- the scheme's first root
    "ENVO_00002011",  # fresh water
    "ENVO_00002042",  # surface water
    "ENVO_04000007",  # lake water
    "ENVO_01000599",  # river water
    "ENVO_01001004",  # groundwater
    "ENVO_00003097",  # bore hole water -- the nearest class to fossil groundwater
    "ENVO_00002010",  # saline water -- concept only, no flow lands on it
    "ENVO_00002149",  # sea water
    "ENVO_00003044",  # brine
    "ENVO_01000600",  # rainwater
    "ENVO_03600002",  # cooling water
    "ENVO_00002001",  # waste water
    "ENVO_00002186",  # contaminated water
    "ENVO_01000266",  # water vapour -- the second root
    "ENVO_01000268",  # atmospheric water vapour -- folded into the above
    "ENVO_00002012",  # hypersaline water -- ENVO's parent of brine, recorded not minted
    "ENVO_01000797",  # gaseous environmental material -- ENVO's parent of vapour
    # Resolved so the provenance walk can reach the root through them.  Without
    # these two, an edge ENVO *does* imply comes out as one of ours, which is the
    # error the provenance field exists to prevent -- in the direction that
    # overstates what we invented.
    "ENVO_00005792",  # underground water -- ENVO's parent of groundwater
    "ENVO_03605006",  # stream water -- ENVO's parent of river water
)

#: AGROVOC concepts, by local id.  AGROVOC is not indexed by OLS.
AGROVOC_CONCEPTS = (
    "c_5867fbf1",  # green water -- the water-footprint sense
    "c_b1215876",  # cooling water -- second anchor beside ENVO's
    "c_6d63ccf3",  # grey water -- DO NOT MAP; see the taxonomy's note
    "c_66d531bb",  # water footprint -- the family grey water belongs to
    "c_8309",      # water -- green water's broader concept
)


def _get(url: str) -> Any:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read())


def _text(value: Any) -> str:
    """First English string from OLS's several shapes for one."""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list) and value:
        return _text(value[0])
    if isinstance(value, dict):
        return str(value.get("value") or "").strip()
    return ""


def resolve_envo(accession: str) -> dict[str, Any]:
    """Label, definition and asserted parents for one ENVO class, from OLS4."""
    iri = f"http://purl.obolibrary.org/obo/{accession}"
    payload = _get(
        OLS4_TERM.format(ontology="envo") + "?iri=" + urllib.parse.quote(iri, safe="")
    )
    terms = payload.get("_embedded", {}).get("terms") or []
    if not terms:
        raise LookupError(f"{accession}: OLS4 returned no term for {iri}")
    term = terms[0]

    encoded = urllib.parse.quote(urllib.parse.quote(iri, safe=""), safe="")
    try:
        parent_payload = _get(
            OLS4_PARENTS.format(ontology="envo", encoded=encoded)
        )
        parents = [
            {"id": p.get("obo_id"), "label": p.get("label")}
            for p in parent_payload.get("_embedded", {}).get("terms") or []
        ]
    except urllib.error.HTTPError as exc:
        # A root class has no parents endpoint; that is an answer, not a failure.
        if exc.code != 404:
            raise
        parents = []

    return {
        "iri": iri,
        "curie": accession.replace("_", ":"),
        "label": _text(term.get("label")),
        "definition": _text(term.get("description")),
        "obsolete": bool(term.get("is_obsolete")),
        "parents": sorted(parents, key=lambda p: str(p.get("id"))),
    }


#: Skosmos returns a JSON-LD graph whose concept node uses **unprefixed** keys
#: for the SKOS core properties -- `prefLabel`, `broader`, `related` -- and
#: *references* for the ones that carry text.  A definition is a `skos:definition`
#: pointing at an `xDef_*` node elsewhere in the same graph, whose text is under
#: `rdf:value`.  Reading `skos:definition` as a literal, as one would for any
#: other SKOS source, yields an empty string and no error.
_RDF_VALUE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#value"
_VOCBENCH_SOURCE = "http://art.uniroma2.it/ontologies/vocbench#hasSource"


def _rows(node: Any, *keys: str) -> list[dict[str, Any]]:
    """The values under the first of *keys* the node carries, always a list."""
    for key in keys:
        value = node.get(key)
        if value is None:
            continue
        return [value] if isinstance(value, dict) else list(value)
    return []


def _english(rows: list[dict[str, Any]]) -> str:
    for row in rows:
        if isinstance(row, dict) and row.get("lang") == "en":
            return str(row.get("value") or "").strip()
    return ""


def resolve_agrovoc(local_id: str) -> dict[str, Any]:
    """Label, definition, scope note and broader concepts, from Skosmos.

    The definition is dereferenced through the graph rather than read off the
    concept: AGROVOC models it as a `skos:definition` reference to a node whose
    text is under `rdf:value`, and carries the source it came from beside it.
    Several languages share one concept, so the English one is selected and the
    source recorded -- green water's is FAO term 36619, and quoting it without
    saying so would make our own wording indistinguishable from theirs.
    """
    iri = f"http://aims.fao.org/aos/agrovoc/{local_id}"
    payload = _get(
        AGROVOC_DATA
        + "?uri="
        + urllib.parse.quote(iri, safe="")
        + "&format=application/json"
    )
    graph = payload.get("graph", [])
    by_uri = {n.get("uri"): n for n in graph if isinstance(n, dict)}
    node = by_uri.get(iri)
    if node is None:
        raise LookupError(f"{local_id}: AGROVOC returned no concept for {iri}")

    def dereference(key: str) -> list[dict[str, str]]:
        out = []
        for ref in _rows(node, key, key.split(":", 1)[-1]):
            target = by_uri.get(ref.get("uri")) if isinstance(ref, dict) else None
            if target is None:
                # Some notes are plain literals rather than references.
                text = _english([ref]) if isinstance(ref, dict) else ""
                if text:
                    out.append({"text": text, "source": ""})
                continue
            text = _english(_rows(target, _RDF_VALUE, "skosxl:literalForm"))
            if not text:
                continue
            source = target.get(_VOCBENCH_SOURCE)
            if isinstance(source, dict):
                # Kept whole: some are FAO term ids, some are citations, some
                # are URLs to a PDF. Truncating to the last path segment turned
                # one of them into "a-av045e.pdf)." and lost the rest.
                source = str(source.get("uri") or source.get("value") or "")
            out.append({"text": text, "source": str(source or "")})
        return out

    def refs(key: str) -> list[str]:
        return sorted(
            str(row.get("uri"))
            for row in _rows(node, key, key.split(":", 1)[-1])
            if isinstance(row, dict) and row.get("uri")
        )

    definitions = dereference("skos:definition")
    return {
        "iri": iri,
        "curie": f"agrovoc:{local_id}",
        "label": _english(_rows(node, "prefLabel", "skos:prefLabel")),
        "definition": definitions[0]["text"] if definitions else "",
        "definition_source": definitions[0]["source"] if definitions else "",
        "scope_note": (dereference("skos:scopeNote") or [{"text": ""}])[0]["text"],
        "broader": refs("skos:broader"),
        "related": refs("skos:related"),
    }


def build() -> dict[str, Any]:
    envo: dict[str, Any] = {}
    for accession in ENVO_ACCESSIONS:
        print(f"  ENVO {accession}", file=sys.stderr)
        envo[accession] = resolve_envo(accession)

    agrovoc: dict[str, Any] = {}
    for local_id in AGROVOC_CONCEPTS:
        print(f"  AGROVOC {local_id}", file=sys.stderr)
        agrovoc[local_id] = resolve_agrovoc(local_id)

    return {
        "schema_version": 1,
        "description": (
            "What ENVO and AGROVOC say about every class the material taxonomy "
            "cites, resolved from the authorities by "
            "tools/resolve_material_anchors.py. A test compares the data files "
            "against this, so a mistyped accession -- which is a different "
            "published class that still resolves -- fails the suite offline. "
            "`parents` and `broader` are recorded because the taxonomy asserts "
            "edges the authorities do not, and the only way to keep that honest "
            "is to record what they actually say."
        ),
        "sources": {
            "envo": "EBI OLS4, https://www.ebi.ac.uk/ols4/api",
            "agrovoc": "AGROVOC Skosmos REST, https://agrovoc.fao.org/browse/rest/v1/agrovoc",
        },
        "envo": envo,
        "agrovoc": agrovoc,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="resolve and diff against the snapshot without writing it",
    )
    args = parser.parse_args()

    fresh = build()
    serialised = json.dumps(fresh, indent=2, sort_keys=False) + "\n"

    if args.check:
        if not SNAPSHOT_PATH.exists():
            print(f"{SNAPSHOT_PATH} does not exist", file=sys.stderr)
            return 1
        if SNAPSHOT_PATH.read_text() == serialised:
            print("snapshot is current")
            return 0
        print("snapshot differs from the authorities; re-run without --check")
        return 1

    SNAPSHOT_PATH.write_text(serialised)
    print(
        f"wrote {len(fresh['envo'])} ENVO and {len(fresh['agrovoc'])} AGROVOC "
        f"anchors to {SNAPSHOT_PATH}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
