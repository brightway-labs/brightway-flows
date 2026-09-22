# Source list manifests

One file per flow list this build knows about.  A file here is the whole of
"this list exists": `brightway_flows.sources` reads the directory, and
nothing else names a list.

```json
{
  "list_name": "bafu",
  "list_version": "2026-v1",
  "role": "source",
  "merge_priority": 200,
  "simapro_origin": true,
  "adapter": "brightway_flows.integrations.bafu:fetch",
  "flow_iri_prefix": "https://vocab.brightway.one/bafu/2026-v1/flow/",
  "prepared_match_table": null,
  "concept_associations": null,
  "inputs": {
    "flows": "bafu-2026-v1.json",
    "manual_fixes": null,
    "manual_additions": null,
    "additional_flows": null,
    "match_overrides": null
  }
}
```

| Key | Meaning |
|---|---|
| `list_name`, `list_version` | The list's identity. Together they are its `key`, which is what `--source` names and what `source_refs` publishes. |
| `role` | `source` for a list the merge consumes, `base` for the one every other list is merged into. Exactly one manifest is `base`. |
| `merge_priority` | Where this list belongs in the merge order, lowest first. The first list to reach a substance mints its flow object, so a better-identified list must merge earlier. ecoinvent is 100; gaps are deliberate. Meaningless for the `base`, which is always first |
| `adapter` | Dotted `module:attribute` path to the callable that fetches this list. See below. |
| `flow_iri_prefix` | Minted IRI prefix for this list's flows. **A one-way door**: it is published as the `xkos:sourceConcept` `@id` and read downstream, so it cannot change once the list has shipped. `tests/test_source_list.py` pins every registered prefix. |
| `simapro_origin` | `true` where this list's flow names were shaped by SimaPro, whatever the vendor's own name is. Optional, false by default. It is what entitles a name-matching strategy to run on the list — see below. |
| `source_label` | Only where the list's flows carry a `source` string that is not the key. EF 3.1's do (`"EF 3.1"`, with a space); nothing else's should. |
| `prepared_match_table` | A `randonneur_data` registry name, or a `.json` filename in `../`. **Null on every manifest, deliberately** (#141): the vendor correspondence tables are retired, and the `match_overrides` files are the whole prepared correspondence. Leave it null on a new list and on new ecoinvent releases alike — `plans/retire-prepared-correspondence.md` records the decision. |
| `concept_associations` | How this list's mappings back to the consensus flows are built, or `null` for a list that publishes none. See below. |

There is no `fetch_command` key. It was a string per manifest until #15 —
which meant a new list had to invent a command *and* write the code behind it,
and renaming a command left five manifests naming one that no longer existed.
One command fetches any list, so the string follows from the key:
`fetch-source <key>`.

## `adapter`

The callable that turns the vendor's distribution into
[the record shape](../../../../docs/operating/sources.md), written to
`inputs.flows`:

```python
def fetch(source: SourceList, *, force: bool = False) -> Path:
    ...
    return source.flows_path
```

It takes the `SourceList` rather than nothing. Five ecoinvent manifests share
one adapter and differ only in `list_version`, so a no-argument `fetch()` would
need five near-identical functions — and the adapter needs `flows_path`
regardless, because where a list's flows go is the manifest's answer and not the
adapter's to invent.

It must return `source.flows_path`. `fetch_source_flows` checks, because an
adapter that writes somewhere else has produced a file the merge will never
open, and the run that would otherwise notice is the one an hour later reporting
the flows missing.

`brightway-flows fetch-source <key>` runs it, for any list including the
base one. `extract` and `download-ecoinvent-flows` survive as aliases, because
both are in the README quick start and in existing runbooks; neither has an
implementation of its own.

## `concept_associations`

The published `xkos:Correspondence` for a list, as three values rather than a
Python class per list (#244):

```json
"concept_associations": {
  "scheme": "simapro-10.2",
  "pairs_from": "glad",
  "primary_source": "https://github.com/One-Click-LCA/GLAD-ElementaryFlowResources"
}
```

| Key | Meaning |
|---|---|
| `scheme` | Slug of a scheme in `domain.vocabulary.SOURCE_SCHEMES`. **Not necessarily this list's own**: a list whose flows originate in SimaPro publishes mappings to the *SimaPro* scheme. An unregistered slug fails when the manifest is read. |
| `pairs_from` | `source_refs` — each consensus flow records which of this list's flows it came from, so the pairing is already on the record. `glad` — read the GLAD EF 3.1-to-SimaPro correspondence table, for a list the consensus flows were never merged from and so carry no `source_refs` for. |
| `primary_source` | `prov:hadPrimarySource` for the mappings. Optional for `glad`, which knows the table it reads. |

**Declaring this is also what switches it on.** The builders for a run are the
base list's plus those of every list named by `--source`, so a correspondence
table is downloaded and parsed on a build that has something to use it for, and
on no other. GLAD used to be pulled by every `extract` to feed a builder that no
run registered.

## `inputs.additional_flows`

Whole source flows the vendor ships somewhere the fetch does not look, appended
to the fetched rows before manual fixes and before matching.

Not the same thing as `inputs.manual_fixes`, and the difference is what the
record *is*.  A fix names a field on a row the fetch already produced and says
the vendor got it wrong.  A row here is one the vendor got right and the fetch
never saw, because the distribution puts it in a file the adapter does not open
— expressed as a correction it would have nothing to attach to.

ecoinvent is the case (#25).  ecoinvent publishes one
`ElementaryExchanges.xml` per system model — `cutoff`, `apos`, `consequential`
and `EN15804` — and the adapter reads `cutoff`.  3.8's APOS and consequential
releases each carry the same three exchanges cutoff does not.

**Every registered ecoinvent declares this input, including the four with
nothing to add.**  Their files hold an empty `flows` list and a `comparison`
block saying what was read and what it held.  That is deliberate: a version
whose four releases were compared and agreed and a version nobody has looked at
are otherwise the same absence, and that ambiguity is what let `consequential`
and `EN15804` go unchecked on every version for as long as they did (#100).

The comparison is reproducible rather than remembered.
`tools/compare_ecoinvent_system_models.py` reads all four releases of each
version — from the `ecoinvent_interface` cache where one is already extracted,
otherwise downloading the archive for the single 17 MB file it needs and
deleting it again — compares them exchange by exchange, and rewrites these
files.  Run it when a new ecoinvent version is registered; `tests/
test_additional_flows.py` pins the counts it found.

A record needs `uuid`, `name`, `unit`, `context` and a `comment` saying what
ships it and where — an assertion that a vendor has a flow the fetch cannot see
is not checkable against the next release without one.  `source` is stamped from
the list rather than declared, because context rules are keyed by it, and
`unit_iri` is derived the same way the adapter derives it, so a hand-copied IRI
cannot go stale against `units.json`.

**A record whose uuid the fetch already carries is dropped, not appended.**  That
is what makes the file safe to leave in place should the adapter later learn to
read the other file: the fetch wins, and the run gets one flow rather than two
rows under one uuid, which the merge keys on.

## `inputs.match_overrides`

The list's curated correspondence rows -- since #141 the whole of its prepared
correspondence, because every manifest's `prepared_match_table` is null and the
overrides are applied onto an empty table.  A row is `source_uuid`,
`target_uuid` and a mandatory `comment`; `load_prepared_match_table` appends a
prepared row for each one.  (The rewrite-what-the-table-holds half of the
mechanism survives in code for the day a table exists again, but nothing
exercises it today.)  A row belongs in the file of the list whose uuids it
names -- two TiO2 rows filed under ecoinvent while naming BAFU uuids were
inert until review on #336 moved them.

Not the same thing as `inputs.manual_fixes`, and the difference is again what
the record *is*.  A fix names a field on a source flow and says the vendor got
it wrong.  A target uuid is not a field on the source flow, so the same
correction expressed as a fix would edit the source data and make the list look
as though the anomaly never happened.

**One file covers every version of a list.**  ecoinvent's flow uuids are stable
across releases, so a decision about a flow is a decision about it in every
release that ships it, and all five ecoinvent manifests name
`../ecoinvent-match-overrides.json` -- a couple of hundred rows now that the
file is the correspondence.  A row naming a flow a version does not carry is
inert there rather than an error: ten rows name 3.8 flows that 3.9.1 dropped.

The one-file shape dates from #37, when the point was that a curated target
stated only in the composed 3.8 table would have been invisible to the four
versions reading vendor tables.  The vendor tables are gone; the shape stays
because restating one decision five times was never going to improve it.

`inputs.flows` is resolved against the **data directory**: it is the one derived
input, produced by a fetch.  Every other input is resolved against **this
package's `data/`**, because those are curated decisions that belong in the
repository.

Every curated input may be `null`, meaning the list has none — which is the
normal state of a list on the day it is added.  Whatever a manifest *does* name
has to exist: `resolve_source_list` checks before `build` runs the transform,
rather than letting the run fail an hour later.

**Context rules are not an input here.**  They are rows in
`../context-manual-mapping.json` keyed by the list's `source` string, read by
the transform and the merge through one loader.  A manifest used to name a
per-list file, which was a *generated projection* of that same master that
`build` never regenerated.  To map a new list's compartments, add rows to the
master under its `source`; `resolve_source_list` refuses a list that has none,
because the merge would place none of its rows.
