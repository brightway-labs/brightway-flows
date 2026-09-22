"""What a substance is *used for*, asserted on the object from two sources.

A flow object says what a substance *is* -- its formula, its CAS, its ChemROF
class.  Nothing in it said what the substance is *for*, and the pipeline's only
way to express "this is a herbicide" was to stop publishing the substance and
publish `Herbicides, Unspecified` in its place (#206).  This module is the field
that removes the need to.

The relation is `RO:0000087 has role`, which is what ChEBI's own distribution
uses, so the assertions this project publishes and the assertions it reads are
the same relation.  Nothing is minted.

Two things make this an allow-list rather than a copy of ChEBI:

- **Volume.**  Of 1,881 published flow objects that bear any ChEBI role, the
  most common are `metabolite` (646), `inhibitor` (400), `drug` (396),
  `mouse metabolite` (107).  None of that groups anything an LCA asks about, and
  publishing it would bury the roles that do.
- **Safety.**  A role that looks authoritative and is incomplete is worse than
  no role.  `greenhouse gas` is the case that decided it: ChEBI gives it to
  carbon dioxide, methane and sulfur hexafluoride and to no HFC or PFC in this
  list, so a consumer grouping on it would get a greenhouse gas set missing the
  entire fluorinated basket.  It is deliberately not in the allow-list; see
  `plans/pesticide-taxonomy.md` for the measurement.

A role assertion is read the way ChEBI writes it, which means closing over
`is_a` in **two** directions.  Both are entailment, and missing either finds
fewer roles than ChEBI states:

- **Up the role hierarchy.**  ChEBI asserts `neonicotinoid insectide` on
  dinotefuran and not `insecticide`, because `neonicotinoid insectide is_a
  insecticide` and an ontology does not restate what it entails.  Reading only
  direct assertions would find no insecticides at all.
- **Down the chemical hierarchy.**  ChEBI asserts roles on chemical *classes*,
  and a `SubClassOf (has_role R)` axiom on a class holds for every subclass of
  it.  `2,3,7,8-TCDD` has no `has_role` edge of its own; its parent class
  `polychlorinated dibenzodioxine` bears `persistent organic pollutant`.  Read
  only the entity's own edges and every dioxin, most PCBs and the brominated
  flame retardants come out with no role whatever.

The second was missing from the first version of this module, found in review of
#269.  It cost 155 flow objects at least one entailed role, 73 of them every
role they should have had -- the same failure the `greenhouse gas` rejection
above is argued against, inside the roles that *are* published.  The check that
was supposed to catch it recomputed expectations with this same resolver, so it
could not: a resolver cannot be its own oracle.  `tests/test_chebi_roles.py`
now pins the entailed roles of named substances by hand instead.

## The curated half

ChEBI answers for about half of the substances that matter here and is silent
for the rest -- no `has role` edge for the sulfonylurea herbicides, for
spinetoram, for sodium fluorosilicate, or for kaolin.  That is a gap in ChEBI's
curation and not a claim that those substances have no use class, so
`assign_curated_roles` fills it from `curated-chebi-roles.json`, one row per
substance, each quoting a published source and linking the record it was read
from.

Two decisions about how the halves meet, both of which have a wrong answer that
looks fine:

- **Curated runs second and adds.**  A role is many-valued.  ChEBI calls
  laminarin an `agrochemical`; PPDB and its EU approval call it a fungicide;
  both are true and the object ends up holding both.  Curated first would have
  tripped `assign_chebi_roles`'s `curated_present` branch and published the
  curated half *instead of* ChEBI's.
- **Curated rows are materialised here** rather than left to be entailed, the
  same as the generated ones, because a published table that omits what it
  entails answers wrongly.  A row naming `herbicide` publishes `pesticide` too.

What is *not* asserted is recorded in the same file rather than left as an
absence: `objections` for a source list's filing this project declines to
reproduce, `undecided` for a substance the evidence does not settle.  Neither is
loaded, so nothing can mistake a refusal for a role.
"""

from __future__ import annotations

import collections
import gzip
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import orjson
import structlog

from brightway_flows.domain.common import Provenance
from brightway_flows.flow_layers.classifications import _classification_values
from brightway_flows.domain.flow_object import FlowObject, Role
from brightway_flows.domain.vocabulary import (
    CHEMINF_CAS_REGISTRY_NUMBER,
    PROV_WAS_GENERATED_BY_CURIE,
    RO_HAS_ROLE_IRI,
)
from brightway_flows.filesystem import CHEBI_JSON_GZ_FILEPATH, PACKAGE_DATA_DIR

logger = structlog.get_logger(__name__)

ROLES_DATA_PATH = PACKAGE_DATA_DIR / "chebi-roles.json"

#: The curator's half.  ChEBI has a `has role` edge for roughly half the
#: substances a source list routes to a group bucket, and the half it misses is
#: not exotic -- the sulfonylurea herbicides, spinetoram, sodium fluorosilicate.
#: This file closes that gap from a published source, in the same predicate and
#: the same allow-listed classes.
CURATED_ROLES_DATA_PATH = PACKAGE_DATA_DIR / "curated-chebi-roles.json"

#: The predicate to read in ChEBI's OBO graph.  It is the same IRI this project
#: publishes, and that is the point of the design rather than a coincidence: the
#: relation we assert and the relation we read are one relation.  So it comes
#: from the registry -- `tests/test_vocabulary.py` refuses a second declaration
#: of a registered IRI, and it caught this line holding a literal.
_CHEBI_HAS_ROLE_EDGE = RO_HAS_ROLE_IRI

#: Written into every generated assertion's provenance, and read back to tell a
#: generated assertion from a curated one.  One constant because the write and
#: the read must not be able to disagree.
GENERATED_BY = "chebi_roles"

#: The same, for the curated half.  `assign_chebi_roles` reads it as "not mine"
#: rather than by name, so the two only have to stay different.
CURATED_BY = "curated_roles"

#: The on-disk format of `curated-chebi-roles.json`, and of nothing else.  Not
#: the version of the list this project publishes, which is
#: `domain.schema.SCHEMA_VERSION` -- three modules meant three things by the
#: bare name until #98.
DECISIONS_SCHEMA_VERSION = 1

#: What a row may say about the registry numbers, and the reason the field is
#: mandatory: a curated role is only worth the identity check behind it.
#:
#: `exact` -- the source's record carries the number the source list ships.
#: `different_registry_entry` -- two numbers name one commercial substance, as
#: with copper oxychloride (1332-40-7 and 1332-65-6) and with soap, which is
#: real and is recorded rather than smoothed over.
#: `not_shipped` -- the source list ships no number, so the row is inert until
#: something supplies one.
CAS_AGREEMENTS = frozenset({"exact", "different_registry_entry", "not_shipped"})


@dataclass(frozen=True)
class CuratedRole:
    """One curator's answer to "what is this substance used for?".

    *source_states* is the source's own words for the substance's type, quoted
    rather than paraphrased, so a reader checks the claim instead of trusting
    the row.  *cas_agreement* says whether the record quoted carries the same
    registry number the source list ships; see :data:`CAS_AGREEMENTS`.
    """

    substance: str
    cas_number: str
    roles: tuple[str, ...]
    source_url: str
    source_states: str
    cas_agreement: str
    comment: str


class CuratedRoleError(ValueError):
    """A curated role row that cannot be read as one.

    Raised rather than skipped, for the reason every decisions file in this
    project raises: a row that is silently ignored is a curator's decision that
    looks applied and is not.
    """


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise CuratedRoleError(message)


@dataclass(frozen=True)
class AllowedRole:
    """One ChEBI role class this project publishes.

    *broader* is the role's allow-listed parents, which is what
    :func:`_materialise` walks: a table that names `herbicide` and
    not `pesticide` answers "is this a pesticide?" wrongly.  *family* groups the
    allow-list for the reader of `chebi-roles.json`; nothing branches on it.
    """

    iri: str
    curie: str
    label: str
    definition: str
    broader: tuple[str, ...]
    family: str


@lru_cache(maxsize=1)
def load_allowed_roles() -> dict[str, AllowedRole]:
    """The allow-list, keyed by ChEBI role IRI.

    Generated by `tools/generate_chebi_roles.py`; a test re-runs the generator
    and compares, so the file cannot drift from the ChEBI release beside it.
    """
    payload = orjson.loads(ROLES_DATA_PATH.read_bytes())
    return {
        str(row["iri"]): AllowedRole(
            iri=str(row["iri"]),
            curie=str(row["curie"]),
            label=str(row["label"]),
            definition=str(row["definition"]),
            broader=tuple(str(parent) for parent in row.get("broader") or ()),
            family=str(row.get("family") or ""),
        )
        for row in payload["roles"]
    }


def _load_chebi_graph() -> dict[str, Any]:
    """Parse `chebi.json.gz` once, with the same guard `integrations.chebi` uses.

    Guarded because this module is reached from `resolve_flow_layers`, which is
    the whole transform: without it a missing download surfaces as a bare
    `FileNotFoundError` from `gzip.open` several frames deep, rather than as the
    one line that says what to run.  `integrations/chebi.py` already learned
    this for the same file.

    `["graphs"][0]` is checked rather than indexed for the same reason -- a
    truncated download would otherwise raise `KeyError` and name nothing.
    """
    if not CHEBI_JSON_GZ_FILEPATH.exists():
        raise FileNotFoundError(
            f"ChEBI JSON not found at {CHEBI_JSON_GZ_FILEPATH}. "
            "Run 'brightway-flows chebi' first."
        )
    with gzip.open(CHEBI_JSON_GZ_FILEPATH, "rb") as handle:
        payload = orjson.loads(handle.read())
    graphs = payload.get("graphs")
    if not isinstance(graphs, list) or not graphs:
        raise ValueError(
            f"{CHEBI_JSON_GZ_FILEPATH} has no graphs; the download is "
            "truncated or is not an OBO graph document."
        )
    return graphs[0]


@lru_cache(maxsize=1)
def _chebi_indexes() -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Return (allowed_roles_by_entity, entities_by_cas).

    One pass over the graph builds both.  It was two, each decompressing and
    parsing the same 49 MB file for a measured ~2.8 GB peak RSS -- and
    `integrations.chebi.load_chebi_index` holds a third index of the same file
    alive during a run, so the waste was not hypothetical.

    ``allowed_roles_by_entity`` is resolved all the way to allow-listed roles
    here rather than at the call site, so both entailment directions are applied
    in one place and a caller cannot apply one and forget the other.

    Keyed by CAS rather than by name.  Normalising a name to alphanumerics
    deletes the stereodescriptor, so `(+)-Mecoprop` matches `Mecoprop` and a
    racemate acquires its eutomer's roles.  That produced two wrong rows in an
    earlier draft of this work; see `plans/pesticide-taxonomy.md`.
    """
    graph = _load_chebi_graph()
    allowed = load_allowed_roles()

    parents: dict[str, set[str]] = collections.defaultdict(set)
    direct_roles: dict[str, set[str]] = collections.defaultdict(set)
    for edge in graph.get("edges", ()):
        predicate = edge.get("pred")
        if predicate == "is_a":
            parents[edge["sub"]].add(edge["obj"])
        elif predicate == _CHEBI_HAS_ROLE_EDGE:
            direct_roles[edge["sub"]].add(edge["obj"])

    ancestor_cache: dict[str, frozenset[str]] = {}

    def ancestors(node: str) -> frozenset[str]:
        cached = ancestor_cache.get(node)
        if cached is not None:
            return cached
        seen: set[str] = set()
        stack = [node]
        while stack:
            current = stack.pop()
            for parent in parents.get(current, ()):
                if parent not in seen:
                    seen.add(parent)
                    stack.append(parent)
        frozen = frozenset(seen)
        ancestor_cache[node] = frozen
        return frozen

    # Which allow-listed roles a role IRI entails, itself included: the *upward*
    # closure, over the role hierarchy.
    role_closure: dict[str, frozenset[str]] = {}
    for role in {r for roles in direct_roles.values() for r in roles}:
        kept = ({role} | ancestors(role)) & allowed.keys()
        if kept:
            role_closure[role] = frozenset(kept)

    # Which allow-listed roles an entity bears: its own assertions and those of
    # every chemical class above it -- the *downward* closure, over the chemical
    # hierarchy.  Only entities that carry a CAS are resolved, because only
    # those can be reached from a flow object, and closing over all 224,571
    # nodes to answer 3,321 questions is work nobody asked for.
    entities_by_cas: dict[str, set[str]] = collections.defaultdict(set)
    for node in graph.get("nodes", ()):
        identifier = node.get("id")
        if not isinstance(identifier, str) or "/CHEBI_" not in identifier:
            continue
        for xref in node.get("meta", {}).get("xrefs", ()):
            value = xref.get("val")
            if isinstance(value, str) and value.lower().startswith("cas:"):
                entities_by_cas[value.split(":", 1)[1].strip()].add(identifier)

    allowed_by_entity: dict[str, set[str]] = {}
    for entity in {e for entities in entities_by_cas.values() for e in entities}:
        found: set[str] = set()
        for source in (entity, *ancestors(entity)):
            for role in direct_roles.get(source, ()):
                found |= role_closure.get(role, frozenset())
        if found:
            allowed_by_entity[entity] = found

    return allowed_by_entity, dict(entities_by_cas)


def _cas_numbers(flow_object: FlowObject) -> list[str]:
    """The object's CAS numbers, via the shared reader.

    `_classification_values` rather than a local copy: it carries the guard for
    a `classifications` that is not a dict, which a record deserialised with
    `classifications: null` is.
    """
    return [
        value.strip()
        for value in _classification_values(
            flow_object.classifications, CHEMINF_CAS_REGISTRY_NUMBER
        )
    ]


def roles_for_cas(cas_numbers: list[str]) -> set[str]:
    """The allow-listed role IRIs ChEBI entails for *cas_numbers*.

    Both entailment directions are already applied in `_chebi_indexes`; this is
    a lookup and a union, so there is no way to reach one closure without the
    other.
    """
    allowed_by_entity, entities_by_cas = _chebi_indexes()
    found: set[str] = set()
    for cas in cas_numbers:
        for entity in entities_by_cas.get(cas, ()):
            found |= allowed_by_entity.get(entity, set())
    return found


def assign_chebi_roles(flow_objects: list[FlowObject]) -> dict[str, int]:
    """Write `roles` onto every object ChEBI has an allow-listed role for.

    Returns counts for the run report.  Objects with no CAS, no ChEBI entity or
    no allow-listed role are left untouched -- ``roles`` stays ``None`` and the
    key stays absent from the published document, rather than serialising as an
    empty list that reads like "checked, and it has none".

    Curated assertions are **not** written here.  A substance ChEBI has no role
    for gets one from the curation file, with its own provenance, and this
    function must not overwrite it: it only ever writes objects whose roles are
    unset or were generated by this same function.
    """
    allowed = load_allowed_roles()
    stats: dict[str, int] = collections.Counter()

    for flow_object in flow_objects:
        cas_numbers = _cas_numbers(flow_object)
        if not cas_numbers:
            stats["no_cas"] += 1
            continue
        found = roles_for_cas(cas_numbers)
        if not found:
            stats["no_role"] += 1
            continue
        if flow_object.roles:
            existing = {
                row.get("@id") for row in flow_object.roles
                if (row.get("provenance") or {}).get(PROV_WAS_GENERATED_BY_CURIE)
                != GENERATED_BY
            }
            if existing:
                # A curated assertion is on the object.  Leave it alone and say
                # so; reconciling the two is the curation layer's job, and doing
                # it silently here is how a reasoned decision disappears.
                stats["curated_present"] += 1
                continue

        provenance = Provenance(
            was_generated_by=GENERATED_BY,
            was_attributed_to="brightway-flows",
            had_primary_source=["ChEBI"],
            was_derived_from=f"{CHEMINF_CAS_REGISTRY_NUMBER} -> ChEBI RO:0000087",
        )
        flow_object.roles = [
            Role(
                iri=iri,
                label=allowed[iri].label,
                definition=allowed[iri].definition,
                provenance=provenance,
            ).to_dict()
            for iri in sorted(found, key=lambda value: allowed[value].label)
        ]
        stats["assigned"] += 1

    logger.info(
        "chebi_roles_assigned",
        assigned=stats["assigned"],
        no_cas=stats["no_cas"],
        no_role=stats["no_role"],
        curated_present=stats["curated_present"],
    )
    return dict(stats)


@lru_cache(maxsize=1)
def load_curated_roles() -> dict[str, CuratedRole]:
    """The curated assertions, keyed by CAS registry number.

    `objections` and `undecided` are deliberately not read.  They record what
    this project declines to assert and why, and nothing should be able to reach
    them and mistake a refusal for a role.
    """
    return validate_curated_roles(orjson.loads(CURATED_ROLES_DATA_PATH.read_bytes()))


def validate_curated_roles(payload: dict[str, Any]) -> dict[str, CuratedRole]:
    """The checks `load_curated_roles` runs, over a payload rather than a path.

    Separate rather than a `path` argument, which would make the loader
    uncached: a cached loader that takes a path serves the first test's fixture
    to every caller after it.  A test hands a malformed row to this instead,
    which reading the shipped file cannot do.

    A malformed row raises and is never skipped.  A curator's decision that
    looks applied and is not is the failure every ruling file in this project is
    written against:

    - a role outside the allow-list is an error, not a dropped value, because
      the allow-list is the decision about what this project publishes and a
      curator reaching past it is making that decision by accident;
    - two rows for one registry number are an error, because which of them won
      would depend on file order;
    - `comment` and `source_url` are required, for the reason `comment` is
      mandatory on a match override -- an assertion nobody can check is an
      assertion nobody can revise.
    """
    _require(isinstance(payload, dict), "the curated roles file is not an object")
    version = payload.get("schema_version")
    _require(
        version == DECISIONS_SCHEMA_VERSION,
        f"{CURATED_ROLES_DATA_PATH.name} is schema version {version!r}; this "
        f"reads {DECISIONS_SCHEMA_VERSION}",
    )
    rows = payload.get("assertions")
    _require(isinstance(rows, list), "the curated roles file carries no assertions list")

    allowed = load_allowed_roles()
    index: dict[str, CuratedRole] = {}
    for position, row in enumerate(rows):
        _require(isinstance(row, dict), f"assertion {position} is not an object")
        name = str(row.get("substance") or "").strip()
        cas = str(row.get("cas_number") or "").strip()
        _require(name != "", f"assertion {position} names no substance")
        _require(cas != "", f"curated role for {name} has no CAS number")
        _require(
            cas not in index,
            f"two curated role rows for CAS {cas} "
            f"({index[cas].substance if cas in index else ''} and {name})",
        )
        roles = tuple(str(value).strip() for value in row.get("roles") or ())
        _require(roles != (), f"curated role row for {name} asserts no role")
        unknown = [iri for iri in roles if iri not in allowed]
        _require(
            not unknown,
            f"curated role for {name} names {unknown[0] if unknown else ''}, "
            f"which is not in the allow-list at {ROLES_DATA_PATH.name}",
        )
        assertion = CuratedRole(
            substance=name,
            cas_number=cas,
            roles=roles,
            source_url=str(row.get("source_url") or "").strip(),
            source_states=str(row.get("source_states") or "").strip(),
            cas_agreement=str(row.get("cas_agreement") or "").strip(),
            comment=str(row.get("comment") or "").strip(),
        )
        _require(
            assertion.comment != "" and assertion.source_url != "",
            f"curated role for {name} needs both a comment and a source_url",
        )
        _require(
            assertion.source_states != "",
            f"curated role for {name} does not quote what its source says. The "
            "quote is the checkable half: a paraphrase and a curator's opinion "
            "read identically",
        )
        _require(
            assertion.cas_agreement in CAS_AGREEMENTS,
            f"curated role for {name} says its registry numbers agree "
            f"{assertion.cas_agreement!r}; one of {sorted(CAS_AGREEMENTS)} is "
            "required, because a row is worth no more than that field says",
        )
        index[cas] = assertion
    return index


def _materialise(iris: set[str]) -> set[str]:
    """Close *iris* upwards over the allow-list's `broader` edges.

    A row naming `herbicide` publishes `pesticide` as well.  The generated half
    gets this from ChEBI's own role hierarchy in `_chebi_indexes`; the curated
    half has to be closed here, or the two would publish differently shaped sets
    under one predicate and a consumer doing a dictionary lookup would find a
    herbicide that is not a pesticide.
    """
    allowed = load_allowed_roles()
    found = set(iris)
    stack = list(iris)
    while stack:
        for parent in allowed[stack.pop()].broader:
            if parent not in found:
                found.add(parent)
                stack.append(parent)
    return found


def _curated_provenance(assertion: CuratedRole) -> Provenance:
    """Who said so, on the assertion itself rather than in the curation file.

    `prov:hadPrimarySource` carries the **record**, not the database: the whole
    claim of a curated role is that somebody can open the page and read the same
    thing, and a source that names only "PPDB" sends them to a search box.  It
    is also the reuse this source's terms permit -- citing and linking are free,
    copying the data is not -- so the link is the compliant form as well as the
    checkable one.
    """
    return Provenance(
        was_generated_by=CURATED_BY,
        was_attributed_to="brightway-flows",
        had_primary_source=[assertion.source_url],
        was_derived_from=(
            f"{CURATED_ROLES_DATA_PATH.name}: {assertion.substance} "
            f"({assertion.cas_number}) -- {assertion.source_states}"
        ),
    )


def assign_curated_roles(flow_objects: list[FlowObject]) -> dict[str, int]:
    """Add the curated assertions to every object whose CAS carries one.

    Runs *after* `assign_chebi_roles` and adds to what it wrote rather than
    replacing it: a role is many-valued, and a substance ChEBI calls an
    `agrochemical` and a curator calls a `fungicide` is both.  Each row keeps
    the provenance of whoever asserted it, so the two stay tellable apart in the
    published document.

    A curated row whose registry number reaches no flow object is not an error.
    Most of these substances have no object of their own yet -- that is the
    collapse this work exists to undo -- so the assertions are written before
    the objects they will land on, and `unmatched` counts how many are waiting.
    """
    curated = load_curated_roles()
    allowed = load_allowed_roles()
    stats: dict[str, int] = collections.Counter()
    matched: set[str] = set()

    for flow_object in flow_objects:
        # The record each role came from, so the provenance can name it.  A row
        # asserting two roles gives both the same record; two rows reaching one
        # object -- a substance carrying two registry numbers -- do not.
        source_by_iri: dict[str, CuratedRole] = {}
        for cas in _cas_numbers(flow_object):
            assertion = curated.get(cas)
            if assertion is None:
                continue
            matched.add(cas)
            for iri in _materialise(set(assertion.roles)):
                source_by_iri.setdefault(iri, assertion)
        if not source_by_iri:
            continue

        existing = list(flow_object.roles or [])
        present = {row.get("@id") for row in existing}
        stats["already_generated"] += len(set(source_by_iri) & present)
        added = sorted(
            set(source_by_iri) - present, key=lambda iri: allowed[iri].label
        )
        if not added:
            continue

        existing.extend(
            Role(
                iri=iri,
                label=allowed[iri].label,
                definition=allowed[iri].definition,
                provenance=_curated_provenance(source_by_iri[iri]),
            ).to_dict()
            for iri in added
        )
        # Sorted by label across both halves, so the published order says
        # nothing about which pass wrote which row.
        flow_object.roles = sorted(
            existing, key=lambda row: allowed[row["@id"]].label
        )
        stats["objects_assigned"] += 1
        stats["roles_added"] += len(added)

    stats["unmatched"] = len(curated) - len(matched)
    logger.info(
        "curated_roles_assigned",
        objects_assigned=stats["objects_assigned"],
        roles_added=stats["roles_added"],
        already_generated=stats["already_generated"],
        unmatched=stats["unmatched"],
    )
    return dict(stats)
