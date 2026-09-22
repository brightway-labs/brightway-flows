"""Write `environmental-materials.json` with its edge provenance derived.

The taxonomy is ours and some of its edges are not.  `lake water skos:broader
surface water` is a statement the LCA reading needs and ENVO declines to make;
`sea water skos:broader saline water` is one ENVO makes itself.  Publishing both
without saying which is which would make our additions indistinguishable from
the authority's, which is the one thing a scheme that maps out to a published
ontology must not do.

So the provenance is **computed** here rather than typed, by comparing each edge
against the parents in `material-anchor-snapshot.json`:

``asserted``
    The authority states this exact edge.
``shortened``
    The authority states it through an intermediate class the scheme does not
    carry -- brine reaches saline water via hypersaline water.  The skipped step
    is recorded on the row so the elision is visible.
``ours``
    The authority does not state it, transitively or otherwise.  Two edges, both
    from section 2 of `plans/water-taxonomy.md`.
``root``
    No parent within the scheme.

An intermediate concept is carried only when it groups **two or more** of our
concepts: `saline_water` earns its place by grouping sea water and brine, while
`underground water`, `hypersaline water` and `stream water` would each group one
and are recorded as skipped steps instead.

Usage::

    uv run python tools/build_environmental_materials.py
"""

from __future__ import annotations

import json
from hashlib import sha1
from pathlib import Path
from typing import Any

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from brightway_flows.domain.vocabulary import (  # noqa: E402
    Namespace,
    Term,
)
from brightway_flows.domain.vocabulary import _NAMESPACE_OF  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "src" / "brightway_flows" / "data"
SNAPSHOT_PATH = DATA_DIR / "material-anchor-snapshot.json"
OUTPUT_PATH = DATA_DIR / "environmental-materials.json"

#: Every ChemROF class name the vocabulary declares, so a mistyped
#: `chemrof` above fails at build time with a message rather than at
#: typing time with `ValueError: 'Foo' is not a valid Term`.
_CHEMROF_CLASSES = frozenset(
    term.value
    for term in Term
    if _NAMESPACE_OF.get(term) is Namespace.CHEMROF and term.value[:1].isupper()
)

WATER_CAS = "7732-18-5"
WATER_CHEBI = "CHEBI:15377"

#: id, parent, ENVO accession, AGROVOC id, label, basis, comment.
#: The parent is the *intended* edge; whether the authority agrees is computed.
NODES: tuple[dict[str, Any], ...] = (
    {
        "id": "water",
        "parent": None,
        "envo": "ENVO_00002006",
        "label": "Water",
        "basis": f"cas:{WATER_CAS}",
        "comment": (
            "The scheme's first root, and the node an unqualified water flow lands "
            "on. Keeps the bare CAS basis, so it keeps the flow object id it "
            "already has and the largest object in the list does not churn."
        ),
    },
    {
        "id": "fresh_water",
        "parent": "water",
        "envo": "ENVO_00002011",
        "label": "Fresh water",
        "basis": f"material:fresh_water|cas:{WATER_CAS}",
        "comment": (
            "EF 3.1's `freshwater`. Says what the stuff is rather than where it "
            "came from -- fresh water can be surface water or groundwater -- which "
            "is why it takes no water body in the context."
        ),
    },
    {
        "id": "rainwater",
        "parent": "fresh_water",
        "envo": "ENVO_01000600",
        "label": "Rainwater",
        "basis": f"material:rainwater|cas:{WATER_CAS}",
        "comment": (
            "EF 3.1's `Water (rain water)`. Under fresh water because ENVO puts it "
            "there; an earlier draft of the plan flattened it onto the root, which "
            "would have been our own edge where the authority already had one."
        ),
    },
    {
        "id": "surface_water",
        "parent": "water",
        "envo": "ENVO_00002042",
        "label": "Surface water",
        "basis": f"material:surface_water|cas:{WATER_CAS}",
        "comment": (
            "bafu's `Water, process, surface`, and the node that makes `Surface "
            "water` in the context enum mean *not narrowed to a lake or a river* "
            "rather than *including them*."
        ),
    },
    {
        "id": "lake_water",
        "parent": "surface_water",
        "envo": "ENVO_04000007",
        "label": "Lake water",
        "basis": f"material:lake_water|cas:{WATER_CAS}",
        "comment": (
            "One of the two edges that are ours. ENVO puts lake water under liquid "
            "water and astronomical body part, with surface water as a sibling; the "
            "LCA reading needs the containment and the external vocabulary declines "
            "to arbitrate, so the scheme asserts it and says so."
        ),
    },
    {
        "id": "river_water",
        "parent": "surface_water",
        "envo": "ENVO_01000599",
        "label": "River water",
        "basis": f"material:river_water|cas:{WATER_CAS}",
        "comment": (
            "The other edge that is ours. ENVO routes river water through stream "
            "water, which is a different claim from this one and equally not "
            "surface water."
        ),
    },
    {
        "id": "groundwater",
        "parent": "water",
        "envo": "ENVO_01001004",
        "label": "Groundwater",
        "basis": f"material:groundwater|cas:{WATER_CAS}",
        "comment": (
            "EF 3.1's `ground water`, ecoinvent's `Water, well, in ground`. ENVO "
            "reaches it through `underground water`, which would group only this "
            "node and is recorded as a skipped step rather than carried."
        ),
    },
    {
        "id": "fossil_groundwater",
        "parent": "groundwater",
        "envo": "ENVO_00003097",
        "envo_predicate": "skos:closeMatch",
        "label": "Fossil groundwater",
        "basis": f"material:fossil_groundwater|cas:{WATER_CAS}",
        "comment": (
            "ecoinvent's `natural resource / fossil well`, which EF 3.1 cannot "
            "hold: its water resources are classified `Renewable material "
            "resources from water`, and fossil groundwater is the one kind that "
            "is not renewable. `closeMatch`, not `exactMatch`, and the first in "
            "the scheme: ENVO's `bore hole water` names how the water is reached "
            "rather than that it is fossil, so the two overlap without being the "
            "same class, and saying `exactMatch` would assert an equivalence "
            "ENVO does not carry. The edge is ours for the same reason -- ENVO "
            "puts bore hole water under liquid water, not under groundwater."
        ),
    },
    {
        "id": "saline_water",
        "parent": "water",
        "envo": "ENVO_00002010",
        "label": "Saline water",
        "basis": None,
        "comment": (
            "The one concept with no flow object: nothing maps onto it, and it is "
            "here because it groups sea water and brine, which is the test for "
            "carrying an intermediate at all. A node earns an object when a source "
            "flow lands on it. Labelled all the same: sea water and brine publish "
            "it as their `skos:broader`, so it is read even though it is never "
            "landed on, and it was the one node in the scheme with nothing to "
            "display there (#273)."
        ),
    },
    {
        "id": "sea_water",
        "parent": "saline_water",
        "envo": "ENVO_00002149",
        "label": "Sea water",
        "basis": f"material:sea_water|cas:{WATER_CAS}",
        "comment": (
            "EF 3.1's `sea water` (kg), ecoinvent's `Water, salt, ocean` (m3). The "
            "one water pair in the corpus carrying a published conversion, 1025 "
            "kg/m3."
        ),
    },
    {
        "id": "brine",
        "parent": "saline_water",
        "envo": "ENVO_00003044",
        "label": "Brine",
        "basis": "material:brine",
        # Curated, not derived. "Carries no CAS" does not imply "is a mixture" --
        # plenty of things lack a registry number for other reasons -- so the
        # class is stated here rather than inferred at typing time.
        # `ImpreciseChemicalMixture` because the proportions are unstated;
        # `ChemicalMixture` and `PreciseChemicalMixture` are abstract in ChemROF
        # and instantiating one is a modelling error.
        "chemrof": "ImpreciseChemicalMixture",
        "comment": (
            "`Water, salt, sole` in both lists. The only node carrying no CAS: EF "
            "gives it 7732-18-5 and that is an error -- brine is a mixture, not the "
            "molecule. Reaches saline water through hypersaline water, which groups "
            "only this node."
        ),
    },
    {
        "id": "cooling_water",
        "parent": "water",
        "envo": "ENVO_03600002",
        "agrovoc": "c_b1215876",
        "label": "Cooling water",
        "basis": f"material:cooling_water|cas:{WATER_CAS}",
        "comment": (
            "The find that decided the design: EF's `Water to Cooling` is not a "
            "modelling quirk to tolerate in a name but a published class with a "
            "definition and a parent. Both authorities carry it, which is evidence "
            "rather than redundancy."
        ),
    },
    {
        "id": "turbine_water",
        "parent": "water",
        "mint": True,
        "label": "Turbine water",
        "basis": f"material:turbine_water|cas:{WATER_CAS}",
        "comment": (
            "The one node with no published class in either authority. Minted under "
            "vocab.brightway.one because blocking a published-score fix on an "
            "external release is not a trade worth making; an ENVO term request "
            "goes with it, and ours retires if ENVO adopts the term."
        ),
    },
    {
        "id": "contaminated_water",
        "parent": "water",
        "envo": "ENVO_00002186",
        "label": "Contaminated water",
        "basis": f"material:contaminated_water|cas:{WATER_CAS}",
        "comment": (
            "bafu's `Chemically polluted water`. Carried as its own concept "
            "rather than folded into waste water because ENVO makes waste water "
            "the narrower of the two, and bafu ships flows for both."
        ),
    },
    {
        "id": "waste_water",
        "parent": "contaminated_water",
        "envo": "ENVO_00002001",
        "label": "Waste water",
        "basis": f"material:waste_water|cas:{WATER_CAS}",
        "comment": (
            "bafu's `Waste water`. Under contaminated water because ENVO puts it "
            "there; an earlier draft flattened it onto the root, inventing an edge "
            "where the authority had one."
        ),
    },
    {
        "id": "water_vapour",
        "parent": None,
        "envo": "ENVO_01000266",
        "label": "Water vapour",
        "basis": f"material:water_vapour|cas:{WATER_CAS}",
        "absorbs": ["ENVO_01000268"],
        "comment": (
            "The scheme's second root, because ENVO branches vapour away from "
            "liquid water and one flow object cannot carry both sets of anchors. "
            "Absorbs `atmospheric water vapour`, a direct child: the `Air` media "
            "already says the vapour is in an atmosphere, so a node of our own "
            "would restate the context. Splitting this off stops no collapse the "
            "unit was not already stopping -- it buys a correct label."
        ),
    },
    {
        "id": "green_water",
        "parent": None,
        "agrovoc": "c_5867fbf1",
        "related": ["rainwater"],
        "label": "Green water",
        "basis": f"qual:green_water|cas:{WATER_CAS}",
        "comment": (
            "Outside the material tree on purpose. Green water is separate for "
            "accounting reasons, not physics: it is rainfall that infiltrated the "
            "soil, so `skos:broader rainwater` would be defensible and misleading. "
            "It stays a qualifier, keeps the basis that reproduces its published "
            "id, and anchors to AGROVOC because no OBO ontology carries the "
            "water-footprint sense."
        ),
    },
)

#: Anchors cited for context rather than mapped onto: recorded so a reader can
#: see the chain the scheme shortens.
INTERMEDIATES = {
    "ENVO_00002012": "hypersaline water",
    "ENVO_01000797": "gaseous environmental material",
}


def flow_object_id(basis: str) -> str:
    return "fo-" + sha1(basis.encode("utf-8")).hexdigest()[:16]


def main() -> int:
    snapshot = json.loads(SNAPSHOT_PATH.read_bytes())
    envo = snapshot["envo"]
    by_id = {node["id"]: node for node in NODES}

    # Which of our concepts each ENVO class stands for, so a parent chain can be
    # walked back into our own ids.
    ours_by_accession = {
        node["envo"]: node["id"] for node in NODES if node.get("envo")
    }

    def parents_of(accession: str) -> list[str]:
        row = envo.get(accession)
        if row is None:
            return []
        return [p["id"].replace(":", "_") for p in row["parents"]]

    def provenance(node: dict[str, Any]) -> dict[str, Any]:
        """Does the authority assert this edge, imply it, or neither?"""
        parent_id = node.get("parent")
        if parent_id is None:
            return {"broader_source": "root"}
        if not node.get("envo"):
            return {"broader_source": "ours", "broader_reason": "no published class"}

        parent_accession = by_id[parent_id].get("envo")
        direct = parents_of(node["envo"])
        if parent_accession and parent_accession in direct:
            return {"broader_source": "asserted"}

        # Walk up, one step at a time, through classes the snapshot carries.
        seen, frontier, path = set(), list(direct), {}
        for step in direct:
            path[step] = [step]
        while frontier:
            current = frontier.pop(0)
            if current in seen:
                continue
            seen.add(current)
            if current == parent_accession:
                skipped = [
                    envo.get(a, {}).get("label") or INTERMEDIATES.get(a, a)
                    for a in path[current][:-1]
                ]
                return {
                    "broader_source": "shortened",
                    "broader_via": skipped,
                }
            for nxt in parents_of(current):
                path.setdefault(nxt, path[current] + [nxt])
                frontier.append(nxt)

        return {
            "broader_source": "ours",
            "broader_reason": (
                f"{envo[node['envo']]['label']} is not under "
                f"{envo[parent_accession]['label']} in ENVO"
                if parent_accession
                else "no published class"
            ),
        }

    concepts = []
    for node in NODES:
        anchors = []
        if node.get("envo"):
            row = envo[node["envo"]]
            anchors.append(
                {
                    "authority": "envo",
                    "id": node["envo"],
                    "iri": row["iri"],
                    "label": row["label"],
                    # Per node, defaulting to equivalence.  `fossil_groundwater`
                    # is the one concept that overlaps its ENVO class without
                    # being it, and publishing that as `exactMatch` would assert
                    # an equivalence the authority does not carry.
                    "predicate": node.get("envo_predicate", "skos:exactMatch"),
                }
            )
        if node.get("agrovoc"):
            row = snapshot["agrovoc"][node["agrovoc"]]
            anchors.append(
                {
                    "authority": "agrovoc",
                    "id": node["agrovoc"],
                    "iri": row["iri"],
                    "label": row["label"],
                    "predicate": "skos:exactMatch",
                }
            )
        if node.get("mint"):
            anchors.append(
                {
                    "authority": "brightway",
                    "id": node["id"],
                    "iri": (
                        "https://vocab.brightway.one/environmental-materials/"
                        + node["id"].replace("_", "-")
                    ),
                    "label": node["label"],
                    "predicate": "minted",
                }
            )

        entry: dict[str, Any] = {
            "id": node["id"],
            "label": node["label"],
            "broader": node.get("parent"),
            **provenance(node),
            "anchors": anchors,
        }
        if node.get("absorbs"):
            entry["absorbs"] = [
                {"id": a, "label": envo[a]["label"], "reason": "the context already says it"}
                for a in node["absorbs"]
            ]
        if node.get("related"):
            entry["related"] = node["related"]
        stated_chemrof = node.get("chemrof")
        if stated_chemrof is not None and stated_chemrof not in _CHEMROF_CLASSES:
            raise SystemExit(
                f"{node['id']}: chemrof_type {stated_chemrof!r} is not a ChemROF "
                f"class this project declares. This field is hand-curated, so a "
                f"typo is the expected failure -- it should stop here rather "
                f"than raise mid-pipeline."
            )
        entry["chemrof_type"] = stated_chemrof
        entry["cas_number"] = None if node["basis"] == "material:brine" else WATER_CAS
        entry["chebi"] = None if node["basis"] == "material:brine" else WATER_CHEBI
        entry["flow_object_basis"] = node["basis"]
        entry["flow_object_id"] = (
            flow_object_id(node["basis"]) if node["basis"] else None
        )
        entry["comment"] = node["comment"]
        concepts.append(entry)

    payload = {
        "schema_version": 1,
        "description": (
            "The environmental material a flow is made of: our own SKOS scheme, "
            "whose concepts carry skos:broader to each other and skos:exactMatch "
            "out to ENVO and AGROVOC. ENVO types the material -- what the stuff is "
            "-- and AGROVOC types the accounting category -- how a method counts "
            "it. `broader_source` says whether each edge is the authority's, the "
            "authority's through a class this scheme does not carry, or ours: "
            "publishing our additions indistinguishably from theirs is the one "
            "thing a scheme that maps out to a published ontology must not do. "
            "Every anchor is checked against material-anchor-snapshot.json, and "
            "the provenance is computed by tools/build_environmental_materials.py "
            "rather than typed. A concept earns a flow object when a source flow "
            "lands on it; an intermediate is carried only when it groups two or "
            "more concepts. A concept may state a `chemrof_type` where the chemistry "
            "rules cannot reach it -- curated, because carrying no CAS does not "
            "imply being a mixture. See plans/water-taxonomy.md."
        ),
        "concepts": concepts,
    }
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2) + "\n")

    counts: dict[str, int] = {}
    for concept in concepts:
        counts[concept["broader_source"]] = counts.get(concept["broader_source"], 0) + 1
    objects = sum(1 for c in concepts if c["flow_object_id"])
    print(f"{len(concepts)} concepts, {objects} flow objects -> {OUTPUT_PATH.name}")
    for source, count in sorted(counts.items()):
        print(f"  {source}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
