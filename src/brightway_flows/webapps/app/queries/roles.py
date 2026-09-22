"""What a substance is *used for*, as the pages read it.

A flow object says what a substance **is** -- its formula, its registry
numbers, its ChemROF class.  Since #206 it also says what the substance is
**for**, as `RO:0000087 has role` pointing into an allow-listed corner of
ChEBI's role tree.  That is the axis the agricultural-chemicals page is about,
and this module is how a page reads it.

The allow-list is not restated here.  `flow_layers/roles.py` owns
`chebi-roles.json` and every label, definition and `broader` edge in it, and a
page that spelled the fourteen classes out again would be a second copy to keep
right -- which is the defect `data/chebi-roles.json` exists to prevent.  What
this module adds is the two things a *reader* needs and the pipeline does not:
the counts, and the tree the `broader` edges already describe.

**A count here is a count of flow objects, not of flows.**  An object bearing
`herbicide` is one herbicide however many contexts it is emitted into, and the
question the page asks -- "how many of the substances in this list are
herbicides?" -- is a question about substances.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any

from brightway_flows.domain.vocabulary import (
    RDFS_LABEL_CURIE,
    RO_HAS_ROLE_IRI,
    SKOS_DEFINITION_IRI,
)
from brightway_flows.flow_layers.roles import (
    CURATED_BY,
    GENERATED_BY,
    AllowedRole,
    load_allowed_roles,
)
from brightway_flows.webapps.app.labels import local_name
from brightway_flows.webapps.app.queries.common import alphabetical

#: The family of `chebi-roles.json` the agricultural-chemicals page is about.
#:
#: The allow-list carries two.  `agrochemical_use` is what a substance is
#: applied to a field *for*; `environmental_fate` -- `environmental
#: contaminant`, `persistent organic pollutant` -- is what happens to it
#: afterwards, and is asserted of substances that were never agricultural at
#: all.  Putting both on one page would answer "which of these are
#: agricultural chemicals?" with a list that includes the dioxins.
AGROCHEMICAL_FAMILY = "agrochemical_use"

#: The other one, named rather than left as "not the first": the page says what
#: it leaves out, and a reader who wants those roles is sent to them.
ENVIRONMENTAL_FATE_FAMILY = "environmental_fate"

#: `prov:wasGeneratedBy` on a role assertion, and what each value means to a
#: reader.  The two halves are a real distinction rather than an implementation
#: detail: ChEBI answers for about half the substances that matter here, and
#: the curated half exists because the other half is a gap in ChEBI's curation
#: and not a claim that those substances have no use class.
EVIDENCE_LABELS: dict[str, str] = {
    GENERATED_BY: "ChEBI",
    CURATED_BY: "Curated",
}

_DEFINITION = local_name(SKOS_DEFINITION_IRI)


@dataclass
class RoleNode:
    """One allow-listed role, its count, and the roles below it."""

    iri: str
    curie: str
    label: str
    definition: str
    family: str
    #: Flow objects bearing this role.  Includes everything below it, because
    #: the pipeline materialises what it entails: a row naming `herbicide`
    #: publishes `pesticide` too, so an object under `herbicide` is already
    #: counted under `pesticide` in the data and not by summing here.
    object_count: int = 0
    children: list["RoleNode"] = field(default_factory=list)

    @property
    def chebi_url(self) -> str:
        return f"https://www.ebi.ac.uk/chebi/searchId.do?chebiId={self.curie}"


@dataclass
class RoleAssertion:
    """One role on one substance, as the detail page shows it.

    *evidence* is the half of `flow_layers/roles.py` that asserted it, in
    words.  A role assertion is only worth the source behind it, and "ChEBI
    says so" and "a curator read the PPDB entry and wrote it down" are not the
    same claim.
    """

    iri: str
    label: str
    definition: str = ""
    evidence: str = ""

    @property
    def curie(self) -> str:
        return "CHEBI:" + self.iri.rsplit("CHEBI_", 1)[-1]


def assertions_from_payload(payload: Any) -> list[RoleAssertion]:
    """The roles a `flow_object_json` payload carries, in label order.

    Reads the label and definition off the assertion rather than looking them
    up: they were written into the published record, and a page that showed the
    allow-list's wording instead would hide a record written before a wording
    changed.  The *evidence* is looked up, because it is a name of a pass and
    not a thing a reader should have to know.
    """
    entries = (payload or {}).get(RO_HAS_ROLE_IRI) if isinstance(payload, dict) else None
    rows: list[RoleAssertion] = []
    for entry in entries or ():
        if not isinstance(entry, dict):
            continue
        generated_by = ""
        provenance = entry.get("provenance")
        if isinstance(provenance, dict):
            for key, value in provenance.items():
                if local_name(key) == "wasGeneratedBy":
                    generated_by = str(value or "")
        definition = ""
        for key, value in entry.items():
            if local_name(key) == _DEFINITION:
                definition = str(value or "")
        rows.append(
            RoleAssertion(
                iri=str(entry.get("@id") or ""),
                label=str(entry.get(RDFS_LABEL_CURIE) or entry.get("@id") or ""),
                definition=definition,
                evidence=EVIDENCE_LABELS.get(generated_by, generated_by),
            )
        )
    return sorted(rows, key=lambda row: row.label.lower())


def family_roles(family: str) -> dict[str, AllowedRole]:
    """The allow-listed roles in *family*, keyed by IRI."""
    return {
        iri: role
        for iri, role in load_allowed_roles().items()
        if role.family == family
    }


def role_object_counts(connection: sqlite3.Connection) -> dict[str, int]:
    """``role IRI -> flow objects bearing it``, for every role in the build.

    One scan of `flow_objects` rather than one query per role.  A role the
    allow-list carries and nothing bears is absent from the result rather than
    zero -- callers ask with `.get(iri, 0)`, so the page shows `0` where the
    build has none, which is the honest reading of "no substance in this list
    is a rodenticide".
    """
    return {
        str(row["iri"]): int(row["n"])
        for row in connection.execute(
            "SELECT json_extract(role.value, '$.@id') AS iri, count(*) AS n "
            "FROM flow_objects fo, "
            f"json_each(json_extract(fo.flow_object_json, '$.\"{RO_HAS_ROLE_IRI}\"')) "
            "AS role GROUP BY iri"
        )
        if row["iri"]
    }


def role_tree(connection: sqlite3.Connection, family: str) -> list[RoleNode]:
    """*family*'s roles as the forest its `broader` edges describe.

    A forest and not a tree: `pesticide`, `agrochemical` and `plant growth
    regulator` are all roots of the agrochemical family, because ChEBI does not
    place a growth regulator under either of the other two and this project
    does not add edges ChEBI declines to assert.

    Ordered by count within a level, then by label, so the roles that group
    something in this list come first and the empty ones fall to the bottom
    where they read as coverage rather than as noise.
    """
    roles = family_roles(family)
    counts = role_object_counts(connection)
    nodes = {
        iri: RoleNode(
            iri=role.iri,
            curie=role.curie,
            label=role.label,
            definition=role.definition,
            family=role.family,
            object_count=counts.get(iri, 0),
        )
        for iri, role in roles.items()
    }
    roots: list[RoleNode] = []
    for iri, role in roles.items():
        # Only a parent inside this family makes an edge on this page. A role
        # whose parent the allow-list carries in the *other* family would
        # otherwise vanish from both trees.
        parents = [parent for parent in role.broader if parent in nodes]
        if parents:
            for parent in parents:
                nodes[parent].children.append(nodes[iri])
        else:
            roots.append(nodes[iri])

    def order(items: list[RoleNode]) -> list[RoleNode]:
        for item in items:
            item.children = order(item.children)
        return sorted(items, key=lambda node: (-node.object_count, node.label.lower()))

    return order(roots)


def evidence_counts(connection: sqlite3.Connection, family: str) -> dict[str, int]:
    """``evidence label -> assertions``, over *family*'s roles only.

    Counts assertions rather than substances: one substance carrying three
    curated roles is three curated statements, and the number a reader is
    checking is how much of the published axis rests on which source.
    """
    iris = list(family_roles(family))
    if not iris:
        return {}
    placeholders = ", ".join("?" * len(iris))
    rows = connection.execute(
        "SELECT json_extract(role.value, '$.provenance.prov:wasGeneratedBy') AS by, "
        "count(*) AS n FROM flow_objects fo, "
        f"json_each(json_extract(fo.flow_object_json, '$.\"{RO_HAS_ROLE_IRI}\"')) AS role "
        f"WHERE json_extract(role.value, '$.@id') IN ({placeholders}) GROUP BY by",
        iris,
    ).fetchall()
    counts: dict[str, int] = {}
    for row in rows:
        label = EVIDENCE_LABELS.get(str(row["by"] or ""), str(row["by"] or "unrecorded"))
        counts[label] = counts.get(label, 0) + int(row["n"])
    return counts


def substances_with_any_role(connection: sqlite3.Connection, family: str) -> int:
    """Flow objects bearing at least one role in *family*."""
    iris = list(family_roles(family))
    if not iris:
        return 0
    placeholders = ", ".join("?" * len(iris))
    return int(
        connection.execute(
            "SELECT count(*) FROM flow_objects fo WHERE EXISTS ("
            "SELECT 1 FROM "
            f"json_each(json_extract(fo.flow_object_json, '$.\"{RO_HAS_ROLE_IRI}\"')) "
            f"AS role WHERE json_extract(role.value, '$.@id') IN ({placeholders}))",
            iris,
        ).fetchone()[0]
    )


def role_options(connection: sqlite3.Connection, family: str) -> list[tuple[str, str]]:
    """The `<select>` options for *family*, as `(IRI, "label (count)")`.

    Every role in the family is offered, including the ones nothing in the
    build bears.  A dropdown that silently drops `rodenticide` cannot be used
    to find out that this list has nine of them and no more.

    In label order rather than by how many substances bear each, like every
    other filter list here: twelve classes ordered by count is twelve classes
    a reader has to read all of to find `fungicide`.
    """
    counts = role_object_counts(connection)
    return alphabetical(
        (role.iri, role.label, counts.get(iri, 0))
        for iri, role in family_roles(family).items()
    )
