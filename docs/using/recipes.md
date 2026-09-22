# Recipes

Worked answers to the questions people actually bring to this data. Each uses
only the published outputs — no project code required.

The SQLite recipes assume `consensus-flows.sqlite3` from the data directory (see
[Which output do I need?](outputs.md)); the JSON recipes assume
`harmonised-flows-simple.json.gz`.

## Load the published list

```python
import gzip, json, pathlib

path = pathlib.Path.home() / "Library/Application Support/brightway-flows/harmonised-flows-simple.json.gz"
payload = json.loads(gzip.decompress(path.read_bytes()))

assert payload["schema_version"] == 5
flows = payload["flows"]
```

Check `schema_version` rather than assuming. It is the signal that the file
layout is what your code expects — version 4 moved the mappings out of each
flow, and version 5 added `redirects`.

## Find a substance by name or synonym

Preferred names are normalised but not guaranteed to be what you would type, so
search synonyms too, case-insensitively.

```python
def find(flows, term):
    term = term.casefold()
    return [
        f for f in flows
        if term in f["prefLabel"].casefold()
        or any(term in alt.casefold() for alt in f["altLabel"])
    ]

for f in find(flows, "sulfur hexafluoride"):
    print(f["prefLabel"], "|", f["context_iri"], "|", f["unit"])
```

Against SQLite there is a full-text index that is much faster on the whole list:

```sql
SELECT uuid, name, context_display, unit
FROM elementary_flows_fts
WHERE elementary_flows_fts MATCH 'sulfur AND hexafluoride';
```

The indexed columns are `uuid`, `flow_object_id`, `name`, `source`, `unit`,
`context_display`, `cas_numbers`, and `alt_labels`. There is a parallel
`flow_objects_fts` over `pref_label`, `alt_labels`, `cas_numbers`, and
`ec_numbers` when you want identities rather than occurrences.

## Look up by CAS number — carefully

A CAS number is not a unique key. Expect several hits, and expect some of them
to be genuinely different substances that must stay apart.

```sql
SELECT fo.flow_object_id,
       fo.pref_label_value,
       fo.origin_qualifier
FROM flow_objects fo
WHERE fo.flow_object_id IN (
    SELECT flow_object_id FROM flow_objects_fts
    WHERE flow_objects_fts MATCH 'cas_numbers:"124-38-9"'
);
```

For CO₂ this returns the undifferentiated substance plus its fossil, biogenic,
and land-use-change variants — all sharing CAS 124-38-9. `origin_qualifier`
tells them apart and `parent_flow_object_id` points each variant at the base.

**If you collapse on CAS alone you will merge fossil and biogenic carbon.**

The review app filters on the same field: `/flows?qualifier=biogenic` and
`/flow-objects?qualifier=biogenic`. It is a separate filter from the type, because
all four CO₂ objects are `chemrof:NeutralMolecule` and the type cannot separate
them.

## List every context a substance appears in

```sql
SELECT ef.context_display, ef.unit, ef.source, ef.is_deprecated
FROM elementary_flows ef
JOIN flow_objects fo USING (flow_object_id)
WHERE fo.pref_label_value = 'Lead'
ORDER BY ef.context_display;
```

The `elementary_flows` table also carries the context split into columns —
`context_dimension`, `context_media`, `context_strata`,
`context_population_density`, `context_geography`, `context_water_body`,
`context_land_use`, `context_indoor` — so you can filter on one attribute:

```sql
SELECT pref_label_value, context_display
FROM elementary_flows
WHERE context_media = 'Water'
  AND context_water_body = 'Ocean'
  AND is_deprecated = 0;
```

## Translate a flow from one list to another

This is what `correspondences` is for. Each holds the associations for one
source list, and each association links a source-list flow to a consensus flow
with a SKOS mapping property.

They used to sit on the flow under `concept_associations`, and moved to the top
level in schema version 4 — a flow in the published export has no such key, and
code that reads one finds nothing.

```python
EF31 = "https://vocab.brightway.one/ef/3.1/flow/"
FLOW = "https://vocab.brightway.dev/elementary-flows/"

by_identifier = {f["identifier"]: f for f in flows}

by_source_uuid = {}
for correspondence in payload["correspondences"]:
    for assoc in correspondence["xkos:madeOf"]:
        src = assoc["xkos:sourceConcept"]["@id"]
        if src.startswith(EF31):
            target = assoc["xkos:targetConcept"]["@id"]
            by_source_uuid[src[len(EF31):]] = by_identifier.get(target[len(FLOW):])

hit = by_source_uuid.get("0000b186-aea3-4c0a-b0c2-c284de7cdf92")
print(hit["prefLabel"], hit["identifier"], hit["context_iri"])
```

That builds 93,863 entries for EF 3.1 on the 2026-08-12 build. Swap the prefix
for another list's — `https://vocab.brightway.one/ecoinvent/3.12/flow/` — to go
the other way; `correspondence["@id"]` names which list each one is for. Two
things to watch:

- **Read the mapping property, not a `mapType` field.** The kind of match is
  carried on the source concept as `skos:exactMatch` or `skos:broadMatch`.
  XKOS defines no property for the type of a mapping, so there is no
  `xkos:mapType`. `skos:broadMatch` means one consensus flow groups several
  source flows — the mapping is not reversible one-to-one.
- **Apply the conversion factor if there is one.** An association carries
  `qudt:conversionMultiplier` where an amount of the source flow does not mean
  an amount of the consensus flow — mass against energy, or an ore's mass
  against its metal's. Multiply the source amount by it. Factors `units.json`
  already carries on the unit, such as litres to cubic metres, are not here:
  read those off the unit. Absence means no factor was stated, *not* that the
  amounts are comparable, so check `qudt:hasUnit` on the source concept against
  the target flow's `unit` before assuming parity. See
  [`qudt:conversionMultiplier`](../reference/schemas.md#qudtconversionmultiplier).

## Get only the substances, not the occurrences

```sql
SELECT flow_object_id, pref_label_value, origin_qualifier, flow_type
FROM flow_objects
ORDER BY pref_label_value;
```

`flow_type` distinguishes ordinary consensus substances from specialised kinds
such as isotopes.

## Filter to elements, ions, or isotopes

Semantic typing is on the flow object. Elements carry an atomic number, ions
carry a non-zero elemental charge:

```python
CHARGE = "https://w3id.org/chemrof/elemental_charge"
NUMBER = "https://w3id.org/chemrof/atomic_number"

elements = [fo for fo in flow_objects if NUMBER in fo["properties"]]
ions = [
    fo for fo in flow_objects
    if (v := fo["properties"].get(CHARGE)) and v.get("@value") not in (0, None)
]
```

A nuclide carries `chemrof:symbol` and `chemrof:nucleon_number`, and that pair
is its identity — not its CAS number, which for several nuclides is the
*element's*, and not its label. Key on the pair if you are joining against a
nuclear data table:

```python
SYMBOL = "https://w3id.org/chemrof/symbol"
NUCLEONS = "https://w3id.org/chemrof/nucleon_number"

nuclides = {
    (fo["properties"][SYMBOL]["@value"][0], fo["properties"][NUCLEONS]["@value"][0]): fo
    for fo in flow_objects
    if SYMBOL in fo["properties"] and NUCLEONS in fo["properties"]
}
```

That pair does not distinguish a ground state from its isomer —
`Technetium-99` and `Technetium-99m` collide in it. The full state is in
`properties.isotope.isomeric_state`, empty for a ground state, and in
`properties.isotope.nuclide` as the source spells it (`99Tc`, `99Tcm`).

Property keys are full ChemROF IRIs in **both** files —
`properties["https://w3id.org/chemrof/atomic_number"]`. What differs is the
value: `flow_objects.properties_json` wraps it as `{"@value": …}` with
provenance alongside, and `harmonised-flows-simple.json.gz` unwraps it to a
plain string or number, which is usually what you want. The short name
`atomic_number` is what the published file's `@context` declares, and you see it
only by compacting the document with a JSON-LD processor — which also lifts it
out of `properties` onto the flow, because that key is mapped to `@nest`.

Alternatively, check `@type` for `chemrof:FullySpecifiedAtom` or
`chemrof:MonoatomicIon`.

## See why a flow's name changed

```sql
SELECT change_index, transformer, field, old_value_json, new_value_json, comment
FROM changelog
WHERE elementary_flow_uuid = '<flow uuid>'
ORDER BY change_index;
```

Changes are ordered by processing step; for the same field, later steps win.
`comment` is the reason the step recorded.

`changelog` is keyed by substance as well as by flow, so the same question
asked of a substance rather than one of its flows is the same query against
the other column:

```sql
SELECT transformer, field, old_value_json, new_value_json, comment
FROM changelog
WHERE flow_object_id = '<flow object id>'
ORDER BY change_index;
```

There was a `consensus_changes` table holding the `consensus_match` slice of
this log. It was removed in favour of `changelog`, which covers every
transformer and both access paths; add `WHERE transformer = 'consensus_match'`
to either query above for what it used to hold.

## Trace a flow back to its source rows

```sql
SELECT list_name, list_version, source_flow_uuid, source_flow_name
FROM elementary_flow_sources
WHERE elementary_flow_uuid = '<flow uuid>';
```

`source_metadata_json` additionally holds the input file, the dataset name, and
the original compartment strings as the source list wrote them. This is the
audit trail for a merge: if a consensus flow looks like it fused two things that
should be separate, this is where you see what was fused.

**SQLite is the only place to get this.** The published export strips
`source_refs`, so there is no file that carries it — apart from the merge
tables, for flows a merge created. The review application shows the same rows
as the **Source lists** section of a flow's detail page.

## Handle deprecated flows

A row superseded by another is marked rather than deleted:

```sql
SELECT uuid, replaced_by_uuid
FROM elementary_flows
WHERE is_deprecated = 1;
```

If you hold identifiers from an earlier version, follow `replaced_by_uuid`
rather than dropping unrecognised ones.

You do not need the database for this. Deprecated flows are excluded from
`flows` in `harmonised-flows-simple.json.gz`, but the same document's
`redirects` names each one's surviving flow — already resolved to the end of the
chain:

```python
import gzip, json

document = json.loads(gzip.decompress(open("harmonised-flows-simple.json.gz", "rb").read()))
published = {flow["identifier"] for flow in document["flows"]}
redirect = {
    row["identifier"]: (
        row["replaced_by_identifier"],
        row["https://vocab.brightway.one/terms/deprecationReason"]["@id"].rsplit("/", 1)[-1],
    )
    for row in document["redirects"]
}

def resolve(identifier):
    if identifier in published:
        return identifier, "live"
    if identifier in redirect:
        return redirect[identifier]          # (survivor, reason)
    return None, "never-harmonised"
```

The third return is the one that was missing before: a miss on both is a flow
this list has never carried, which is a different problem from one it merged
away.

!!! warning "`reason` is not a footnote"

    `identity-merge` is the same flow twice — the merge crossed no source
    context. `context-collapse` merged two source contexts whose
    characterisation factors legitimately disagree, and `unclassified` could not
    be checked. Detect those two and refuse rather than overwriting; and even on
    an identity merge, do not overwrite a factor you already hold.
    `identifier-scheme-change` is the exception: no flow moved, this list
    renamed one it had minted, and following it is always right. See
    [known limitations](../reference/limitations.md#what-a-redirects-reason-does-and-does-not-promise).

## Check the invariant before you rely on it

One row per substance-and-context is the guarantee the list is built on. It is
cheap to verify:

```sql
SELECT flow_object_id, context_display, COUNT(*) AS n
FROM elementary_flows
WHERE is_deprecated = 0
GROUP BY flow_object_id, context_display
HAVING n > 1;
```

An empty result is the expected outcome. `/checks/duplicate-contexts` presents
the same check.

## Sanity-check a database before trusting it

```sql
SELECT run_id, timestamp, flow_count, max_flows FROM pipeline_runs;
```

`max_flows` is the tell: a non-null value means a bounded run wrote this
database, so every count in it describes part of the list. The review
application says so on its overview before showing any number, for the same
reason.

The merge has a tell of its own, because it can be bounded separately:

```sql
SELECT list_name, list_version, row_count, available_row_count, max_rows
FROM merge_run_inputs ORDER BY sequence;
```

`1000` in `row_count` against `21088` in `available_row_count` is a run that
read a thousand of the list's rows, and `max_rows` says it was asked to. Every
number about that list — matched, created, unmatched — is a number about those
thousand rows.

What each stage counted is in `run_stats`, which is the cheapest way to spot a
regression between two runs:

```sql
SELECT stage, key, value FROM run_stats ORDER BY stage, key;
```

A fall in the ratio of typed objects to total, or a non-zero
`skipped_unknown_scheme`, is worth reading before trusting the run.

## Find out what a build spent its time on

```sql
SELECT stage, detail, duration_seconds FROM run_timings
ORDER BY duration_seconds DESC LIMIT 15;
```

One row per stage, with each transformer and each merged list named, so the
answer is "`consensus_match` over ecoinvent 3.12" rather than "the merge". The
build prints the same list as it finishes, as `build_timings`.

These are the only numbers in the database that differ between two runs of the
same code over the same inputs, which is why they are in a table of their own
rather than beside the counts in `run_stats`.
