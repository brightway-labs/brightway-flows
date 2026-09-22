"""Flow objects: substance identity, and the flows that resolve to it.

The consensus app called these "flow objects", which is the record type's name
rather than the thing it describes. A reader looking at this page is looking at
a substance; the identifier stays `flow_object_id` because that is what the
database and every other layer call it.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any

from brightway_flows.domain.labels import coerce_alt_labels
from brightway_flows.domain.vocabulary import (
    CHEMINF_CAS_REGISTRY_NUMBER,
    CHEMINF_EC_NUMBER,
    CHEMROF_ISOMERIC_SMILES_STRING,
    CHEMROF_SMILES_STRING,
    PROV_WAS_GENERATED_BY_CURIE,
    RO_HAS_ROLE_IRI,
)
from brightway_flows.webapps.app.db import table_exists
from brightway_flows.webapps.app.labels import (
    local_name,
    predicate_label,
    predicate_term,
    resource_name,
    type_label,
)
from brightway_flows.webapps.app.queries.common import (
    PAGE_SIZE,
    Page,
    alphabetical as _alphabetical,
    load_json,
    order_by,
    resolve_page,
)
from brightway_flows.webapps.app.queries.flows import _classification_values
from brightway_flows.webapps.app.queries.roles import assertions_from_payload

#: Counted per row rather than stored, because a substance's flows and its
#: changes are both one-to-many and neither belongs on `flow_objects`.
_LINKED_FLOWS = (
    "(SELECT count(*) FROM elementary_flows ef "
    "WHERE ef.flow_object_id = fo.flow_object_id "
    "AND coalesce(ef.is_deprecated, 0) = 0)"
)
#: From `changelog`, which is keyed by `flow_object_id` -- so this is a filter,
#: not a join. `consensus_changes` had only the flow uuid, which is why the
#: consensus app had to join through `elementary_flows` to count the same thing
#: for one transformer.
#:
#: Counts edits. The log stores one row per edit rather than one per affected
#: flow, so a substance whose synonym list was stripped once counts one, where
#: it used to count once per elementary flow carrying it.
_CHANGE_COUNT = (
    "(SELECT count(*) FROM changelog c WHERE c.flow_object_id = fo.flow_object_id)"
)

#: Which source list minted this object, read out of the payload rather than
#: from a column, because there is no column: `created_from` is written by the
#: resolver that first reached the substance and the SQLite writer stores it
#: inside `flow_object_json` whole.
#:
#: Read at query time rather than added to the schema on purpose.  A new column
#: means every deployment needs a rebuild before the page works at all, and the
#: review app runs whatever build is in the shared data directory; extracting it
#: costs 0.37s over 8,060 rows on the build of 19 August 2026, which is a facet
#: list, not a page.
#:
#: `seed_source` is the list's key as the resolver wrote it -- `EF 3.1`,
#: `ecoinvent-3.12`, `bafu-2026-v1` -- and is deliberately not normalised here.
#: Two spellings of one list would be a defect in what minted the object, and
#: smoothing it over in the query is how it would stay invisible.
_ORIGIN_SOURCE = "json_extract(fo.flow_object_json, '$.created_from.seed_source')"

#: The role assertions on an object, as a table of `{"@id": ..., ...}` entries.
#:
#: `RO:0000087` is written at the top level of the payload under its full IRI,
#: which is a key with slashes and a colon in it, so the JSON path quotes it.
#: The IRI comes from the vocabulary registry rather than being spelled here:
#: the predicate this project publishes and the predicate ChEBI states are one
#: predicate, and a literal would be a second place for them to disagree.
_ROLE_ENTRIES = (
    f"json_each(json_extract(fo.flow_object_json, '$.\"{RO_HAS_ROLE_IRI}\"'))"
)


def _bears_any_role(count: int) -> str:
    """A `WHERE` clause true of an object carrying one of *count* named roles.

    An `EXISTS` over `json_each` rather than a `LIKE` on the payload: the IRIs
    are prefixes of each other nowhere, but `CHEBI_33286` is a substring of
    nothing and `CHEBI_2452` would be a substring of `CHEBI_24527`, and a
    filter that is right by luck about today's allow-list is a filter that
    breaks when a role is added to it.
    """
    placeholders = ", ".join("?" * count)
    return (
        f"EXISTS (SELECT 1 FROM {_ROLE_ENTRIES} AS role "
        f"WHERE json_extract(role.value, '$.@id') IN ({placeholders}))"
    )

_SORT_COLUMNS = {
    "name": "lower(fo.pref_label_value)",
    "id": "lower(fo.flow_object_id)",
    "type": "fo.flow_type",
    "flows": _LINKED_FLOWS,
    "origin": f"lower(coalesce({_ORIGIN_SOURCE}, ''))",
}
_DEFAULT_SORT = "lower(fo.pref_label_value)"


@dataclass
class SubstanceRow:
    flow_object_id: str
    name: str = ""
    flow_type: str = ""
    origin_qualifier: str = ""
    #: The source list that minted this object.  Beside `origin_qualifier` and
    #: not instead of it: one says which list first published the substance and
    #: the other says which of several forms of it this is, and a reader
    #: filtering on `fossil` is asking a different question from one filtering
    #: on `bafu-2026-v1`.
    origin_source: str = ""
    linked_flows: int = 0
    change_count: int | None = None
    cas_numbers: list[str] = field(default_factory=list)

    @property
    def type_label(self) -> str:
        return type_label(self.flow_type)


@dataclass
class LinkedFlow:
    """One elementary flow on a substance's detail page."""

    uuid: str
    source: str = ""
    unit: str = ""
    context_display: str = ""
    lcia_factor_count: int = 0
    is_deprecated: bool = False


#: The local name of `prov:wasGeneratedBy`, matched rather than compared: a
#: provenance block written before the CURIEs landed carries the expanded IRI,
#: and the app reads whichever database is in the data directory.
_WAS_GENERATED_BY = local_name(PROV_WAS_GENERATED_BY_CURIE)


def _generated_by(provenance: Any) -> str:
    """Which pass recorded a reference, under either spelling of the key."""
    if not isinstance(provenance, dict):
        return ""
    for key, value in provenance.items():
        if local_name(key) == _WAS_GENERATED_BY:
            return str(value or "")
    return ""


@dataclass
class PropertyRow:
    """One row of the properties table.

    *label* is the predicate in words and *term* is the same predicate as the
    vocabulary writes it.  Both, because they answer different questions: the
    label is what the row says, and the term is what a curator quotes in an
    issue or greps the published document for.

    *entry* is the stored payload, unformatted.  Rendering it is the
    `property_value` filter's job, and doing it here would put two spellings of
    the same value in the codebase.
    """

    label: str
    term: str
    entry: Any


@dataclass
class ReferenceRow:
    """One known URL for a substance, and where the pipeline got it.

    *resource* is the database the URL points at rather than its host, so a
    reader scanning the column sees "ChEBI", "PubChem", "Wikipedia" and not
    three spellings of `ncbi.nlm.nih.gov`.  *generated_by* is the pass that
    recorded it, verbatim: these links are evidence, and evidence with no
    named source is worth less than none.
    """

    url: str
    resource: str = ""
    generated_by: str = ""

    @property
    def is_link(self) -> bool:
        """Whether this is a URL a browser can follow.

        Not every reference is.  A ChEBI xref whose prefix has no expansion is
        stored as it was published -- `Beilstein:1234` -- and the page shows it
        as text rather than dropping it or linking somewhere it cannot reach.
        """
        return self.url.startswith(("http://", "https://"))


@dataclass
class SubstanceDetail:
    flow_object_id: str
    name: str = ""
    flow_type: str = ""
    cas_numbers: list[str] = field(default_factory=list)
    ec_numbers: list[str] = field(default_factory=list)
    pref_labels: list[dict[str, Any]] = field(default_factory=list)
    alt_labels: list[str] = field(default_factory=list)
    properties: dict[str, Any] = field(default_factory=dict)
    references: list[Any] = field(default_factory=list)
    classifications: dict[str, Any] = field(default_factory=dict)
    origin_qualifier: str = ""
    #: The source list that minted this object, and the resolver that did it.
    #: Shown on the page because "which list is this substance from?" was a
    #: question the record has always answered and no page ever asked.
    origin_source: str = ""
    origin_resolver: str = ""
    parent_flow_object_id: str = ""
    #: The non-material intervention family this object belongs to, where it
    #: has one.  Shown apart from `parent_flow_object_id`: that one names a
    #: base *substance*, and an object with this field set has none (#70).
    parent_intervention_id: str = ""
    flows: list[LinkedFlow] = field(default_factory=list)
    change_count: int | None = None
    #: How many of this substance's source rows carried a place written into
    #: the name -- `Water, AE`, `Phosphorus, CN` -- counted by running the
    #: geography splitter over the shipped names the mappings record.  The
    #: aggregate a curator asked for instead of a per-row display (#192,
    #: 2026-09-01): with up to two hundred places per base, the number is the
    #: readable fact and the rows are not.
    regionalised_source_rows: int = 0
    flow_object_json: dict[str, Any] = field(default_factory=dict)

    @property
    def type_label(self) -> str:
        return type_label(self.flow_type)

    @property
    def role_rows(self) -> list[Any]:
        """What this substance is used for, in label order.

        Read off the published payload rather than looked up in the allow-list,
        so a record written before a wording changed still shows the wording it
        was published with.  See `queries.roles`.
        """
        return assertions_from_payload(self.flow_object_json)

    @property
    def smiles_candidates(self) -> list[str]:
        """Every SMILES the substance carries, in stored order.

        A list, not one value: a substance whose structure is not settled
        carries several, and the first is not reliably the parseable one. The
        diagram tries each until RDKit accepts one -- which is also why a
        structure shown here is only evidence about *a* candidate. See
        `withhold_ambiguous_mass` for what the pipeline does about that.

        The isomeric SMILES come first. `smiles_string` is the molecular graph
        with stereochemistry removed, because ChemROF says that slot carries
        none; the stereochemistry is not lost, it moved to
        `isomeric_smiles_string`, and a reviewer looking at a structure wants
        the wedge bonds. Both are listed so the page still shows what is stored.
        """
        return [
            *_classification_values(self.properties, CHEMROF_ISOMERIC_SMILES_STRING),
            *_classification_values(self.properties, CHEMROF_SMILES_STRING),
        ]

    @property
    def has_structure(self) -> bool:
        return bool(self.smiles_candidates)

    @property
    def property_rows(self) -> list[PropertyRow]:
        """The properties table, ordered by what the rows say.

        Sorted on the label rather than on the key.  Sorting on the key ordered
        the table by namespace and then by accession, so the two CHEMINF
        registry numbers sat together at `http://semanticscience.org/...` and
        the ChemROF terms at `http://w3id.org/...` -- an order that means
        something to the vocabulary and nothing to a reader.
        """
        return sorted(
            (
                PropertyRow(
                    label=predicate_label(key),
                    term=predicate_term(key),
                    entry=entry,
                )
                for key, entry in (self.properties or {}).items()
            ),
            key=lambda row: (row.label.lower(), row.term),
        )

    @property
    def reference_rows(self) -> list[ReferenceRow]:
        """Every external record the pipeline linked this substance to."""
        return reference_rows(self.references)


def reference_rows(references: Any) -> list[ReferenceRow]:
    """*references* as a page shows them: one row per URL, named and ordered.

    Two shapes reach a flow object's `references` and both are read:
    `enrich_references` writes `{"@id": url, "provenance": {...}}`, and the
    isotope enrichment writes bare strings.  Deduplicated on the URL, because a
    substance with two ChEBI identifiers collects the same cross-reference
    twice, and ordered by resource so the ChEBI links, the PubChem links and
    the rest arrive in groups.

    A function rather than only a method on `SubstanceDetail`: the homepage
    card links the same substance to the same registries without loading the
    rest of a detail page, and two readings of this field would be two answers
    to "which database is this link to".
    """
    rows: dict[str, ReferenceRow] = {}
    for reference in references or []:
        if isinstance(reference, dict):
            url = str(reference.get("@id") or "").strip()
            generated_by = _generated_by(reference.get("provenance"))
        else:
            url = str(reference or "").strip()
            generated_by = ""
        if not url or url in rows:
            continue
        rows[url] = ReferenceRow(
            url=url,
            resource=resource_name(url),
            generated_by=generated_by,
        )
    return sorted(rows.values(), key=lambda row: (row.resource.lower(), row.url))


def substance_page(
    connection: sqlite3.Connection,
    *,
    query: str = "",
    name_only: bool = False,
    flow_type: str = "",
    origin_qualifier: str = "",
    origin_source: str = "",
    roles: tuple[str, ...] = (),
    sort: str = "",
    page: int = 1,
) -> Page[SubstanceRow]:
    """One page of flow objects, filtered by everything the page offers.

    *roles* is "bears at least one of these", not "bears all of them", which is
    what both callers need: the agricultural-chemicals page shows the whole
    `agrochemical_use` family when no single role is chosen, and one role when
    one is.  A role is many-valued -- sulfluramid is an insecticide *and* an
    acaricide -- so an all-of reading would answer a question nobody asked.

    *page* may be `common.RANDOM_PAGE`, which the flow-object list passes when
    the reader asked for nothing at all -- see :func:`common.resolve_page`.
    """
    has_changelog = table_exists(connection, "changelog")
    change_expression = _CHANGE_COUNT if has_changelog else "NULL"
    order = order_by(
        sort,
        {**_SORT_COLUMNS, "changes": change_expression if has_changelog else _DEFAULT_SORT},
        _DEFAULT_SORT,
    )

    def run(clauses: list[str], values: list[Any]) -> Page[SubstanceRow]:
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        total = int(
            connection.execute(
                f"SELECT count(*) FROM flow_objects fo {where}", values
            ).fetchone()[0]
        )
        number = resolve_page(page, total)
        rows = connection.execute(
            "SELECT fo.flow_object_id, fo.pref_label_value, fo.flow_type, "
            "fo.origin_qualifier, fo.classifications_json, "
            f"{_ORIGIN_SOURCE} AS origin_source, "
            f"{_LINKED_FLOWS} AS linked_flows, {change_expression} AS change_count "
            f"FROM flow_objects fo {where} ORDER BY {order} LIMIT ? OFFSET ?",
            [*values, PAGE_SIZE, (number - 1) * PAGE_SIZE],
        ).fetchall()
        return Page(
            rows=[
                SubstanceRow(
                    flow_object_id=row["flow_object_id"],
                    name=row["pref_label_value"] or "",
                    flow_type=row["flow_type"] or "",
                    origin_qualifier=row["origin_qualifier"] or "",
                    origin_source=row["origin_source"] or "",
                    linked_flows=int(row["linked_flows"] or 0),
                    change_count=(
                        None if row["change_count"] is None else int(row["change_count"])
                    ),
                    cas_numbers=_classification_values(
                        load_json(row["classifications_json"], {}),
                        CHEMINF_CAS_REGISTRY_NUMBER,
                    ),
                )
                for row in rows
            ],
            total=total,
            number=number,
        )

    clauses: list[str] = []
    params: list[Any] = []
    if flow_type:
        clauses.append("fo.flow_type = ?")
        params.append(flow_type)
    if origin_qualifier:
        clauses.append("fo.origin_qualifier = ?")
        params.append(origin_qualifier)
    if origin_source:
        clauses.append(f"{_ORIGIN_SOURCE} = ?")
        params.append(origin_source)
    if roles:
        clauses.append(_bears_any_role(len(roles)))
        params.extend(roles)

    if not query:
        return run(clauses, params)

    fts = (
        "fo.flow_object_id IN (SELECT flow_object_id FROM flow_objects_fts "
        "WHERE flow_objects_fts MATCH ?)"
    )
    term = f"pref_label:{query}" if name_only else query
    try:
        return run([*clauses, fts], [*params, term])
    except sqlite3.OperationalError:
        like = f"%{query.lower()}%"
        if name_only:
            return run([*clauses, "lower(fo.pref_label_value) LIKE ?"], [*params, like])
        return run(
            [*clauses, "(lower(fo.pref_label_value) LIKE ? OR lower(fo.flow_object_id) LIKE ?)"],
            [*params, like, like],
        )


def substance_detail(
    connection: sqlite3.Connection, flow_object_id: str
) -> SubstanceDetail | None:
    row = connection.execute(
        "SELECT * FROM flow_objects WHERE flow_object_id = ?", (flow_object_id,)
    ).fetchone()
    if row is None:
        return None

    payload = load_json(row["flow_object_json"], {})
    classifications = load_json(row["classifications_json"], {})
    flows = [
        LinkedFlow(
            uuid=item["uuid"],
            source=item["source"] or "",
            unit=item["unit"] or "",
            context_display=item["context_display"] or "",
            lcia_factor_count=int(item["lcia_factor_count"] or 0),
            is_deprecated=bool(item["is_deprecated"]),
        )
        for item in connection.execute(
            "SELECT uuid, source, unit, context_display, lcia_factor_count, "
            "is_deprecated FROM elementary_flows WHERE flow_object_id = ? "
            "ORDER BY is_deprecated, lower(context_display), lower(source)",
            (flow_object_id,),
        )
    ]

    change_count = None
    if table_exists(connection, "changelog"):
        change_count = int(
            connection.execute(
                "SELECT count(*) FROM changelog WHERE flow_object_id = ?",
                (flow_object_id,),
            ).fetchone()[0]
        )

    # The shipped names the mappings record, read back through the geography
    # splitter: since #192 a split row's `source_flow_name` is the vendor's
    # coded spelling, so counting the ones the splitter reads is counting the
    # rows that carried a place -- for BAFU's extraction-split rows and
    # AGRIBALYSE's load-split rows alike, with no schema change.
    from brightway_flows.simapro_names import split_geography_suffix

    regionalised = 0
    if table_exists(connection, "elementary_flow_sources"):
        for (name,) in connection.execute(
            "SELECT s.source_flow_name FROM elementary_flow_sources s "
            "JOIN elementary_flows e ON e.uuid = s.elementary_flow_uuid "
            "WHERE e.flow_object_id = ?",
            (flow_object_id,),
        ):
            if split_geography_suffix(str(name or "")):
                regionalised += 1

    return SubstanceDetail(
        flow_object_id=flow_object_id,
        name=row["pref_label_value"] or "",
        flow_type=row["flow_type"] or "",
        cas_numbers=_classification_values(classifications, CHEMINF_CAS_REGISTRY_NUMBER),
        ec_numbers=_classification_values(classifications, CHEMINF_EC_NUMBER),
        pref_labels=load_json(row["pref_label_json"], []),
        alt_labels=[label.value for label in coerce_alt_labels(load_json(row["alt_label_json"], []))],
        properties=load_json(row["properties_json"], {}),
        references=load_json(row["references_json"], []),
        classifications=classifications,
        origin_qualifier=row["origin_qualifier"] or "",
        origin_source=str((payload.get("created_from") or {}).get("seed_source") or ""),
        origin_resolver=str((payload.get("created_from") or {}).get("resolver") or ""),
        parent_flow_object_id=row["parent_flow_object_id"] or "",
        parent_intervention_id=row["parent_intervention_id"] or "",
        flows=flows,
        change_count=change_count,
        regionalised_source_rows=regionalised,
        flow_object_json=payload,
    )


def substance_type_options(connection: sqlite3.Connection) -> list[tuple[str, str]]:
    """The types in use, named by their vocabulary and in alphabetical order.

    Named, because 198 of these objects are typed by ENVO on the build of
    2026-08-20 and `ENVO_01000892` is an accession rather than a word.
    Alphabetical, because the count order this was written in is no order at all
    to somebody looking for one entry: the count is still on every option, so
    the common types are still obvious.
    """
    return _alphabetical(
        (row["flow_type"], type_label(row["flow_type"]), int(row["n"]))
        for row in connection.execute(
            "SELECT flow_type, count(*) AS n FROM flow_objects "
            "WHERE coalesce(flow_type, '') <> '' GROUP BY flow_type"
        )
    )


def substance_qualifier_options(
    connection: sqlite3.Connection,
) -> list[tuple[str, str]]:
    """The origin qualifiers in use, with a count of the substances carrying each.

    A second axis beside the type rather than a value of it. The qualified
    substances are mostly typed the same as the substances they were split from
    -- `Carbon Dioxide`, `Carbon Dioxide (biogenic)`, `Carbon Dioxide (fossil)`
    and `Carbon Dioxide (land Use Change)` are four `NeutralMolecule` objects --
    so the type filter cannot separate them and this one can.
    """
    return _alphabetical(
        (row["origin_qualifier"], row["origin_qualifier"], int(row["n"]))
        for row in connection.execute(
            "SELECT origin_qualifier, count(*) AS n FROM flow_objects "
            "WHERE coalesce(origin_qualifier, '') <> '' GROUP BY origin_qualifier"
        )
    )


def substance_origin_options(connection: sqlite3.Connection) -> list[tuple[str, str]]:
    """The source lists that minted an object, with a count of the objects each did.

    Counted over `flow_objects` and not over the flows resolving to them, unlike
    the facets on the elementary-flow page.  The question this filter answers is
    "which list first published this substance?", which is a question about the
    substance; counting flows would report EF 3.1 at 93,993 and tell a reader
    nothing about how many substances that is.

    An object whose `created_from` names no list is left out rather than
    bucketed under a made-up label.  Five are minted by the pipeline itself --
    four elements the element enrichment created and one non-material
    intervention family -- and calling them a source list would be a claim that
    a source list published them.
    """
    return _alphabetical(
        (row["origin_source"], row["origin_source"], int(row["n"]))
        for row in connection.execute(
            f"SELECT {_ORIGIN_SOURCE} AS origin_source, count(*) AS n "
            "FROM flow_objects fo WHERE origin_source IS NOT NULL "
            "AND origin_source <> '' GROUP BY origin_source"
        )
    )
