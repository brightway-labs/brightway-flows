# Choosing sources

A build starts from EF 3.1 and merges source lists into it. Which lists is the
one choice you make — and the default is none of them, so a build that merges
anything is a build that asked to:

```bash
uv run brightway-flows build --source ecoinvent-3.12
uv run brightway-flows build --source ecoinvent-3.9.1 --source ecoinvent-3.12
```

`--source` is repeatable, and a list is merged against everything the lists
before it produced, so the order is part of the result.

**The order is not the order you type them in.** It is `merge_priority` in each
manifest, lowest first, and `build` sorts by it before merging. Lists at equal
priority keep the order they were given, so which ecoinvent release comes first
is still the caller's to say.

It works this way because **the first list to reach a substance mints its flow
object**, and every list merged after it matches against what that list created.
A list whose rows carry registry numbers has to reach a substance before one
whose rows carry only a name, or the better-identified list ends up matching
against objects the weaker one invented. That is the failure the brine comment
in every `ecoinvent-*-manual-fixes.json` describes for ecoinvent arriving before
EF 3.1, and until now nothing defended it but whoever typed the command.

The second vendor has arrived, so this is now doing something: BAFU 2026-v1
declares `merge_priority: 200` against ecoinvent's 100, and a build naming both
merges ecoinvent first whichever order the flags were typed in. Stepwise 2006
is third at 300, and AGRIBALYSE 3.2 fourth at 400. A run that reorders its lists says so with
`source_order_set_by_manifests`.

## One concept, not two

There used to be two ways in. `--input` named a file whose rows *became*
consensus flows, going through every processing step but never matched against
anything. `--source` named a list that was matched against the consensus flows
but never enriched, so a row that matched nothing was reported and dropped. On
top of `--input` sat a `transform-sources.json` config and an auto-discovery
pass over the data directory, which meant a list could enter a build in four
ways, two of which meant different things.

That split is gone. Each source list is enriched — CAS and EC checks, synonyms,
RDKit properties, name resolution — and *then* matched, in one pass, and a row
that matches nothing creates a consensus flow rather than being reported. The
two-pass workflow that existed to enrich unmatched rows on a second build went
with it.

EF 3.1 remains the fixed starting point. It is not a `--source`; it is what the
sources are merged into, and it is loaded from `ef-31-flows.json` in the data
directory.

That it is EF 3.1 is a **manifest entry with `role: "base"`**, not a string
literal repeated across the codebase (#14). Changing which list is the base is
a one-line change to `data/sources/`, with two deliberate exceptions: the
`not-linked-to-ef31` review queue slug and the `ef31_references` flow-object
property still name EF 3.1, because both are published — renaming either is a
data migration rather than a refactor.

The GLAD ILCD→SimaPro workbook is **not** a source list, despite once being
named like an input file. It is a correspondence table: each row maps an EF 3.1
flow to a SimaPro 10.2 flow with a match condition and a conversion factor. A
list whose flows originate in SimaPro reads it by declaring
`concept_associations.pairs_from: "glad"`, and only such a list does — see
[Concept associations](#concept-associations) below.

## What a source list is

**One JSON manifest in `src/brightway_flows/data/sources/`**, not a
parameter threaded through the merge and not an entry in a Python registry. A
file there is the whole of "this list exists": `brightway_flows.sources`
reads the directory, and nothing else names a list.

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

| Key | Required | What it is |
|---|---|---|
| `list_name`, `list_version` | **yes** | Together they form the `--source` key |
| `role` | **yes** | `source` for a list the merge consumes; `base` for the one every other list is merged into. Exactly one manifest is `base` |
| `merge_priority` | **yes**, for a `source` | Where this list belongs in the merge order, lowest first. The first list to reach a substance mints its flow object, so a better-identified list must merge earlier. ecoinvent is 100; gaps are deliberate. It does not have to separate versions of one list — see [Merge order](#merge-order). Meaningless for the `base`, which is always first |
| `adapter` | **yes** | Dotted `module:attribute` path to the callable that fetches this list — see [Adapters](#adapters) |
| `flow_iri_prefix` | **yes** | Minted IRI prefix for this list's flows |
| `simapro_origin` | no | `true` where this list's flow names were shaped by SimaPro, whatever the vendor's own name is. False by default; it is what entitles a name-matching strategy to run on the list — see [SimaPro lineage](#simapro-lineage) |
| `source_label` | no | Only where the list's flows carry a `source` string that is not the key — EF 3.1's do |
| `prepared_match_table` | no | A randonneur registry name, or a `.json` filename beside the manifests. **Deliberately null on every list today** (#141): the vendor tables are retired, and the match-override files are the whole correspondence. When a new ecoinvent release ships a table, leave this null — the decision is recorded in `plans/retire-prepared-correspondence.md` |
| `concept_associations` | no | How this list's mappings back to the consensus flows are built — see below |
| `inputs.flows` | **yes** | Filename in the **data directory**: the one derived input |
| `inputs.manual_fixes` | no | Hand-authored field corrections, applied before matching |
| `inputs.manual_additions` | no | Curated groupings that become new elementary flows |
| `inputs.additional_flows` | no | Whole source flows the vendor ships where the fetch does not look, appended before matching |
| `inputs.match_overrides` | no | Curated targets that win over `prepared_match_table` — see [Match overrides](#match-overrides) |

`inputs.flows` is resolved against the data directory because it is fetched.
Everything else is resolved against the package's `data/`, because those are
curated decisions that belong in the repository.

Any curated input may be `null`, meaning the list has none — which is what a
list looks like on the day it is added. Whatever a manifest *does* name has to
exist: `--source` resolution checks before `build` runs the transform, rather
than letting the run fail an hour later on every row's context.

A list's context rules are **not** declared here. They are rows in
`context-manual-mapping.json` keyed by the list's `source` string, and both the
transform and the merge read them through one loader. A manifest used to name a
per-list file, which was a generated projection of that master that `build`
never regenerated — so editing the master moved the transform and left the merge
on a stale copy. To map a new list, add rows to the master under its `source`;
`--source` resolution refuses a list with none, in the same place and for the
same reason it refuses one whose declared files are missing.

A grouping in `inputs.manual_additions` names a flow object that **already
exists**; nothing creates one from the file. An entry whose `flow_object_id`
resolves to nothing is a stale curated decision, and the merge stops on it
rather than writing an elementary flow that points at no substance — such a flow
has no formula, no mass, no synonyms and no `@type`, because all of those live
on the object. The one exception is a bounded run: under `--max-flows` the
consensus list is a slice of the base list, so a missing object is normally
outside the slice, and those rows are logged
(`manual_addition_target_outside_bounded_slice`) and left to the creation step
instead.

`flow_iri_prefix` is the one-way door. It is published as the
`xkos:sourceConcept` `@id` in `concept_associations`, so a list's prefix cannot
change once it has shipped. `tests/test_source_list.py` pins every registered
prefix for that reason.

## Merge order

The first list to reach a substance mints its flow object, and every list merged
after it matches against what that list created. So the order the `--source`
flags are typed in decides nothing: `build` sorts them, and two rules do it.

**Lowest `merge_priority` first.** A better-identified list has to arrive before
a weaker one. ecoinvent at 100 carries vendor uuids, CAS and EC numbers; BAFU at
200 carries a name, and a registry number on fewer than half of its rows;
Stepwise 2006 at 300 is an LCIA method rather than a flow list, so its rows are
whatever its nineteen impact categories characterise, it has no identifiers of
its own at all — a SimaPro method file ships none, so its UUIDs are derived from
its own names — and 164 of its 6,064 rows carry no registry number either.

**Within one list, newest version first** — 3.12, then 3.11, then 3.10.1, then
3.9.1, then 3.8, however they were typed. Versions are compared as numbers
rather than as text, so 3.10.1 is newer than 3.9.1 and not older.

This second rule is why `merge_priority` does not have to separate the five
ecoinvent releases, and it used to be missing. They all declare 100, ties kept
the order they arrived in, and so:

```bash
build -s ecoinvent-3.12 -s ecoinvent-3.8    # 3.12 first
build -s ecoinvent-3.8 -s ecoinvent-3.12    # 3.8 first
```

Two builds over the same data, differing only in the order somebody typed two
flags. Merging 3.8 first anchored the whole ecoinvent family to 2021 spellings
and left the newer releases matching against what the older one had built
(#100). Newest-first is the same argument that puts ecoinvent ahead of BAFU,
applied inside a list instead of between two.

When the sort changes what was asked for, the run says so —
`source_order_set_by_manifests`, naming both orders.

## Manual fixes

`inputs.manual_fixes` names hand-authored corrections to the vendor's own
fields, applied before anything reads a row. Each is a `match` (or a `uuid`), a
`field`, a `new_value` or `remove_value`, and a mandatory `comment` saying why.

`remove_value` works on either shape the source lists ship: it drops the one
entry from a list-valued `cas_numbers` and clears a singular `cas_number` to
`null`, which `pipeline/loading.py` already reads as "no number". Use it when
there is nothing to correct the value *to* — an identifier that names a mixture
appearing on its constituents, or a registry number on a row that is not one
compound at all. Only the list shape worked until
[#57](https://github.com/brightway-labs/brightway-flows/issues/57); a
removal on a scalar logged itself applied and changed nothing, so two curated
fixes were inert for months while their files went on asserting them.

**One file per version, and every version that ships the row needs the fix.**
Unlike match overrides, a fixes file belongs to one manifest — a fix states what
*that export* got wrong, and the exports differ. (The one exception is the
[lineage's own file](#simapro-lineage), which states what every SimaPro-shaped
export gets wrong the same way.) That makes the failure mode
easy to reach and impossible to see: for five months only ecoinvent 3.12 and EF
3.1 corrected Uranium-238's CAS and `Silver-110`'s label, while 3.8, 3.9.1,
3.10.1 and 3.11 shipped the same rows under the same UUIDs uncorrected, so a
build merging two ecoinvent versions was handed two lists that disagreed about
what a nuclide is — the exact situation those fixes exist to prevent
([#26](https://github.com/brightway-labs/brightway-flows/issues/26)).
Nothing failed: every file was internally consistent and the merge arbitrated
silently. `tests/test_cross_version_manual_fixes.py` is what reads the set of
files as one thing, and a new ecoinvent version is covered by it without anyone
remembering to add it.

**Match on the field that names the substance when the correction is about the
substance.** A CAS that names the wrong isomer is wrong in every context the
substance appears in, and ecoinvent repeats a substance once per context — nine
or ten rows for a nuclide, seven for a lindane isomer. A uuid-keyed rule would
state itself once per row and go stale the moment a context is added; `{"match":
{"name": "Uranium-238"}}` states it once, about the substance. Keep `uuid` for
what really is about one row.

### Rebasing a row onto another unit

A fix that rewrites `unit` may state the factor between the two units, and only
that kind of fix may:

```json
{
  "match": {"name": "Wood, unspecified, standing/kg"},
  "field": "unit",
  "original_value": "kg",
  "new_value": "m3",
  "conversion_factor": 0.00204,
  "comment": "0.49 oven-dry tonnes per cubic metre of fresh volume — a 50:50 mix of Picea abies (0.40) and Fagus sylvatica (0.58), IPCC 2006 Guidelines Vol 4 Ch 4 Table 4.14. …"
}
```

A unit rewrite is not like the other corrections. A CAS that names the wrong
isomer is simply wrong; a vendor measuring standing wood in kilograms is not
wrong, it is measuring the same resource another way. Rebasing it onto the unit
the rest of the list uses — so that one resource is one flow rather than two —
discards a fact unless the factor comes with it.

With the factor, the rewrite stops being a silent reinterpretation of somebody's
amounts. The flow is created in the new unit; the mapping back to the source
flow states the unit the **vendor** shipped and carries the factor beside it, as
`qudt:conversionMultiplier` on the `xkos:ConceptAssociation` and in
`source_metadata`. That is the same property, in the same place, a factor from a
correspondence table lands in — see
[`qudt:conversionMultiplier`](../reference/schemas.md#qudtconversionmultiplier)
and `brightway_flows.merge.conversions`. It exists here because a list with **no
correspondence table** had nowhere else to say it: BAFU publishes no mappings of
its own, so its factors have to be authored beside the correction that needs
them.

Three rules, each of which fails the build rather than being ignored:

- **`original_value` is required.** A factor is a statement about a *pair*, so
  the fix names both units rather than depending on what the row held when it
  ran. It is also what makes the record idempotent — a second pass finds the
  unit already rewritten and can still say what it was rewritten from.
- **Only on `unit`.** On any other field there is nothing for a factor to
  convert.
- **A positive real number.** One unit is a positive number of another.

The factor still has to pass the test every conversion in this project passes:
only one `units.json` could not already have made is published. Kilograms to
cubic metres crosses quantity kinds and qualifies; kilometres to metres does
not, and would be a second copy of something the reader already has.

## Match overrides

`inputs.match_overrides` names curated targets: rows this project asserts,
each `source_uuid`, `target_uuid` and a mandatory `comment`. While a list
declared a `prepared_match_table` these won over whatever it said; since the
ecoinvent tables were retired
([#141](https://github.com/brightway-labs/brightway-flows/issues/141)) the
ecoinvent file *is* the correspondence — `load_prepared_match_table` starts
from an empty table and every override row is appended onto it, so what
reaches the merge is exactly what this project wrote down, a few hundred
reviewable rows instead of thirteen thousand imported ones. The rows that
remain are the joins matching cannot derive: names with no registry number
(waste heat, the size fractions, the buckets), qualifiers ecoinvent marks by
uuid alone (the land-use-change gases), and the ore-to-metal conversions with
their stated factors.

Not a manual fix, and the difference is what the record *is*. A fix names a
field on a source flow and says the vendor got it wrong; a target uuid is not a
field on the source flow, so expressing the correction as a fix would make the
source list look as though the anomaly never happened.

**One file covers every version of a list.** ecoinvent's flow uuids are stable
across releases, so a decision about a flow is a decision about it in every
release that ships it, and all five ecoinvent manifests name
`ecoinvent-match-overrides.json`. A row naming a flow a version does not carry
is inert there rather than an error — ten rows name 3.8 flows that 3.9.1
dropped.

The reason it is one file and not five is
[#37](https://github.com/brightway-labs/brightway-flows/issues/37):
while the published tables were loaded, 3.8's was composed and checked in and
3.9.1 onwards read theirs from `randonneur_data` verbatim, so overriding what
the loader produced was the one hook that reached every version. The tables
are retired now and the argument survives them — the flows are still stable
across releases, so one stated row still decides for all five.

### When a release renumbers the flow

ecoinvent's codes are stable; what they stand for is not always. Release 3.8
ships thirteen codes as `Vanadium`, registry number 7440-62-2, and as
`Vanadium, ion`, 22541-77-1. Release 3.12 ships those same thirteen codes as one
`Vanadium V`, 22537-31-1. Vanadium(V) is not vanadium(III) and neither is the
metal — they behave differently in water, living things take them up
differently, and the Environmental Footprint method gives them different toxicity
numbers. So a correction about where pentavalent vanadium belongs is not a
correction about the other two, and letting it reach 3.8 would put thirteen
emissions on the wrong substance.

A **rename** is usually cosmetic and must not cost a decision: the coarse dust
flow is `Particulates, > 2.5 um, and < 10um` in 3.8 and
`Particulate Matter, > 2.5 um and < 10um` in 3.12, and the four corrections about
it are as true after the comma moved as before. A **renumbering** is the vendor saying the flow is a
different substance, and it is the case a correction has to answer for. A row
answers it one of two ways:

| Field | What the row is saying |
|---|---|
| `only_when_named` | This correction was written about a flow answering to *this* name, and is withheld from a row answering to another. Checked in the merge against the name the row is matched on -- the canonical identity's, where the element/ion rule governs. The thirteen vanadium rows. |
| `not_the_stated_substance` | This row's target is deliberately not the substance the row's stated registry number names, and the comment says why. The signature `tools/audit_prepared_correspondence.py` requires before `--strict` will pass a contradicting row; a signature on a row that agrees is stale and flags the same way. The five carbon rows. |
| `carries_when_registered_as` | This correction is about the substance behind the code, and it has been checked against these registrations. Nine `Chromium III` rows and one `Lutetium, in ground` row — the copper-oxychloride and flupyrsulfuron declines that used to be recorded here were spent when #141 retired the tables they declined rows out of. |

Which of the two is right is a question about chemistry, and the nine chromium
rows are why it cannot be guessed at. They have the vanadium shape exactly — 3.8
calls them `Chromium`, 7440-47-3, and 3.9.1 onwards call them `Chromium III`,
16065-83-1 — and the opposite answer, because 3.8 also shipped a separate
`Chromium VI` flow in those same nine places. Its unspeciated chromium was
therefore everything-but-hexavalent in practice, which is what 3.9.1's rename
says out loud, so the correction carries and the row records the two numbers it
carries across.

Asking the question is not a chemist's job, and
`tests/test_renumbered_flow_corrections.py` asks it of every correction against
every release fetched on the machine: a correction about a flow the releases
register two ways, saying neither of these two things, fails. That is how the
five copper oxychloride rows were found — 1332-40-7 in 3.9.1 and 3.10.1,
1332-65-6 in 3.11 and 3.12, the same name throughout, two registry entries for
one fungicide, and nobody had looked.

One code shows why the choice between the two fields cannot be made by reading
the name. `Flupyrsulfuron-methyl` is what ecoinvent calls a single code in all
five releases, and it registers it 144740-54-5 in 3.8 and 3.9.1 — the sodium salt
— and 144740-53-4 from 3.10.1 on, which is the parent herbicide, shipped
alongside a new `Flupyrsulfuron-methyl sodium` flow for the salt. Two substances,
one code, one spelling, so a name guard has nothing to tell the releases apart
with. The correction there records the two numbers instead, because it turns out
to be right about both for different reasons: the parent has no Environmental
Footprint flow to reach at all, and the salt's own registry number reaches the
flow the published table names anyway.

And when a release arrives that nobody has fetched here yet, a build merging it
**refuses** any correction it registers as a number the row was not checked
against, naming the row to re-read. Refused rather than skipped: a guard is a
decision, so skipping it carries the decision out, while a number nobody has
seen before is an unanswered question, and applying the row and skipping it are
both ways of publishing something unchecked.

## Adapters

The manifest says where a list's flows live. The **adapter** is what puts them
there: one callable that turns the vendor's distribution into the record shape
below and writes it to `inputs.flows`.

```python
# brightway_flows/integrations/bafu.py
def fetch(source: SourceList, *, force: bool = False) -> Path:
    ...
    source.flows_path.write_bytes(orjson.dumps(rows, option=orjson.OPT_INDENT_2))
    return source.flows_path
```

```bash
uv run brightway-flows fetch-source bafu-2026-v1
```

One command, any list, including the base one — `role: "base"` says which list
is merged *into*, not that it arrives by a different route. `extract` and
`download-ecoinvent-flows` survive as aliases for the base list and for
ecoinvent, because both are in existing runbooks; neither has an implementation
of its own.

It takes the `SourceList` rather than nothing, because five ecoinvent manifests
share one adapter and differ only in `list_version` — and because where a list's
flows go is the manifest's answer, not the adapter's to invent. It must return
`source.flows_path`, and that is checked: an adapter writing anywhere else has
produced a file the merge will never open.

Before this there was nowhere for an adapter to live and no protocol for one to
satisfy (#15). ecoinvent had a module, a dedicated command and a dedicated path
function; EF 3.1's extraction was ~55 lines inline in `cli.py`; `integrations/bafu.py`
held name-matching heuristics and was called from nothing. "Add a list" meant
four code changes, which is what made step 1 below a fiction. BAFU is a real
adapter now (#4), which is why the example above is a manifest you can read
rather than one invented for the documentation.

### Which ecoinvent release the adapter reads

ecoinvent does not publish one list of elementary flows. It publishes one per
system model — `cutoff`, `apos`, `consequential` and `EN15804` — and the adapter
reads **`cutoff`**, for every version.

That is safe because the difference has been measured rather than assumed. Of
the twenty releases behind the five registered versions, exactly one pair
disagrees: 3.8's APOS and consequential exports each carry three
`social / unspecified` exchanges cutoff does not, and those three arrive through
`inputs.additional_flows`. Everything else is identical — same uuids, and every
shared exchange equal field for field.

**Registering a new ecoinvent version means re-measuring it**, because nothing
in a build would notice a release that started to diverge:

```bash
uv run python tools/compare_ecoinvent_system_models.py --version 3.13
```

It reads all four releases, writes
`data/ecoinvent-<version>-additional-flows.json` with what it found, and exits
non-zero if it finds a difference that adding rows cannot settle — a flow only
cutoff has, or a shared record whose fields disagree. Both would mean deciding
which release the project should be reading, which is a manifest question rather
than a curated-data one (#100).

## SimaPro lineage

`simapro_origin` says that a list's flow **names** came, at some remove, out of
SimaPro. It is not a statement about the vendor: BAFU is a Swiss federal agency
with nothing to do with SimaPro the company, and its export is SimaPro-shaped
all the same. Stepwise 2006 is the other kind — a SimaPro `{methods}` CSV
export, so the lineage is not at a remove at all — and both declare the flag.

What travels with that lineage is a set of naming habits nothing else has:

| Habit | Example |
|---|---|
| the geography inside the name | `Water, RER` |
| the unit inside the name | `Gas, natural/m3` |
| chemicals in CAS-index order | `Benzene, chloro-` for chlorobenzene |
| the land-use class in the name, not the compartment | `Occupation, annual crop` |

Undoing those is what name matching for such a list consists of, and every one
of those rewrites is **wrong applied anywhere else**. De-inverting `Benzene,
chloro-` is correct for a SimaPro-lineage list and a licence to invent
structures for any other list that happens to have a comma in a name.

**The lineage has data habits too, and those are curated once.**
`simapro-lineage-manual-fixes.json` is a manual-fixes file that belongs to no
manifest: `SourceList.load_flows` applies it to every list whose
`simapro_origin` is true, after that list's own fixes and before the unit split,
and the lookup applies it to a query sent with the flag. What is in it is what
turned up in two lists before either was looked at for it — the element's
registry number written on `Uranium-238`'s activity rows, a resource's energy
content written into its name (`Uranium, 451 GJ per kg`, still in kilograms),
`Carbon dioxide, in air` unqualified. Correcting those list by list is how
BAFU's fourteen numbered `Uranium-238` rows were published as uranium the
element while Stepwise's identical rows sat in a review queue
([#147](https://github.com/brightway-labs/brightway-flows/issues/147)).
Every entry matches by name, because a lineage has no uuids, and pins whatever
else makes the match safe — the wrong number on the isotope rows, the registry
number on the carbon dioxide row — so a list that has already corrected a row
is not corrected twice.

So a strategy asks the flag rather than carrying its own list of keys:

```python
from brightway_flows.sources import simapro_origin_source_labels

if flow.source in simapro_origin_source_labels():
    ...
```

`simapro_origin_source_labels()` returns `source` strings rather than manifest
keys, because a strategy holds a flow and a flow carries `source`.

**Optional, and false by default**, unlike `merge_priority`. The failure modes
are not alike: a missing merge priority silently produces the wrong output,
while a missing flag here only declines an opportunity — the extra strategies
do not run, the rows stay unmatched, and the merge report says so. Safe by
default is the right bias for a flag that unlocks aggressive name rewriting.

Distinct from `concept_associations.pairs_from: "glad"`, which is also about
SimaPro. That one says where a list's *published mappings* come from; this one
says how its *names are spelled*. A list can be either without being both —
BAFU publishes no mappings at all and is still SimaPro-shaped.

## Reading SimaPro-shaped names

`simapro_origin` says a list carries SimaPro's naming habits. This is what is
done about them. `brightway_flows.simapro_names` holds the rules, and they
divide by **what the name is carrying** — which decides where in the pipeline
each is read.

| The name carries | What that is | Where it is read |
|---|---|---|
| another spelling of the substance | `Benzene, Chloro-`, `Arsenic V` | during matching, as a last resort |
| a field this list holds elsewhere | `Water, RER`, `Gas, natural/m3` | before matching, as a rewrite of the row |
| one segment that names the substance, and prose that does not | `Ether, …, HFE-347mcc3` | during matching, to settle a registry number that reached several |

**A spelling needs a second name to try.** `simapro_name_aliases(name)` is the
entry point for those, so a caller asks for "the other spellings of this name"
rather than for a rule by name and gains later ones without being edited. Two
are implemented: the CAS-index inversion and the charged and oxidised forms.

**A segment needs candidates to choose between**, and so it is read in the one
place there already are some: inside the CAS branch, where the number found
several substances and the whole name matched none of them. ecoinvent 2 wrote
a family of fluorinated ethers as structural prose with the industry
designation appended, and gave the whole family one registry number — three
Stepwise 2006 rows are called `Ether, 1,1,2,2-Tetrafluoroethyl
2,2,2-trifluoroethyl-` and numbered 406-78-0, and only the `HFE-347mcc3`,
`HFE-347mcf2`, `HFE-347pcf2` at the end says which is which. The last
comma-segment is looked up against the candidates' published labels and
nothing else, so it can settle a family the number reached and can never reach
outside it, and the row records `cas+designation` as its `basis`. It is the
third rung of [the narrowing
ladder](../deciding/registry-numbers.md#where-a-number-reaches-several-substances-how-an-arriving-row-is-narrowed),
behind every stated identifier and behind the whole name.

**A field needs to come out of the name entirely.** An alias would not be
enough: the row would still be *called* `Water, AE`, so it would create a flow
under that name, and every rule between loading and matching would still see a
name it does not recognise. So the row is rewritten, and what reaches the
pipeline is the row the vendor would have shipped had it modelled geography —
or the unit — the way this list does. Both are implemented, and they run at
different points: `split_geography_suffix` in the adapter, and the unit in
`SourceList.load_flows` *after* the list's manual fixes. The fixes are written
by reading the vendor's file, so they name a flow the way the vendor shipped
it, and a fix is how a row the unit rule declines gets corrected at all.

**A derived spelling is evidence of last resort**, and where it sits is more of
the safety than the rules are. `resolve_flow_object` tries a row's registry
number, then its EC number, then every name the vendor actually shipped — the
designation segment above is not an exception to that order, because it never
brings back a substance the number had not already found. Only when all of
those have come back empty, and only for a flagged list, does it rewrite the
names and look again. A row that matches on its CAS or on its own
label never has a derived spelling considered at all, so a rule that is wrong
about a name can only affect a row that was going to be reported unmatched
anyway.

Doing it the other way — writing the derived spelling on as an alternative
label before matching — reaches every such row, including the ones already
matching correctly. The CAS branch narrows on labels, so a wrong spelling there
can move a match that was right. Two of BAFU's names are exactly that row; see
below.

A row placed this way records `simapro-name-pattern` as its `basis` in
`merge_outcomes`, so a curator can tell a match on a name the vendor shipped
from a match on a name this project derived.

The rewrite kind gets none of that protection, and cannot: it runs before
anything has tried to match, on every row, and what it produces *is* the row.
Its safety has to come from the rule instead — which is why its whitelist is
the length it is, and why it is the part of this to read closely.

### CAS-index inversion

A printed chemical index sorts on the parent compound, so everything derived
from benzene files together, and writes the modification after it with a
trailing hyphen showing where it attaches. SimaPro inherited the convention.

| The list ships | It means |
|---|---|
| `Benzene, Chloro-` | chlorobenzene |
| `Benzene, 1,2-dichloro-` | 1,2-dichlorobenzene |
| `Ethene, Trichloro-` | trichloroethene |
| `Thiazole, 2-(thiocyanatemethylthio)benzo-` | 2-(thiocyanatemethylthio)benzothiazole |
| `Acetic acid, chloro-` | chloroacetic acid |

Read the halves in the other order and join them. The join is a
**concatenation, not a swap** — which is what makes it different from the comma
inversion already in the codebase for lists that ship *both* spellings. Nothing
here can be inferred from the list itself: BAFU ships `Benzene, Chloro-` and
never `chlorobenzene`, so the ordinary spelling has to be constructed.

Three details decide whether it is safe:

**The trailing hyphen is the signal, not the comma.** Keying on the comma alone
would sweep up `Water, RER` (a geography, [#65](https://github.com/brightway-labs/brightway-flows/issues/65)), `Gas, natural/m3` (a unit,
[#67](https://github.com/brightway-labs/brightway-flows/issues/67)), `Occupation, annual crop` (a land class, [#66](https://github.com/brightway-labs/brightway-flows/issues/66)) and `Nitrogen, organic
bound` (a nutrient load) — and turn each into a chemical that does not exist.

**The split is at the first comma.** The substituent half routinely contains its
own: `Benzene, 1,2-dichloro-` is one parent and one locant-bearing substituent,
not three fields. Splitting at the last comma would produce `2-dichloroBenzene,
1`.

**The join takes a hyphen where nomenclature needs one.** A substituent runs
straight into its parent — `chlorobenzene` — unless the parent leads with a
locant or the substituent is a bare positional descriptor: `2-Butene, 2-methyl-`
is `2-methyl-2-butene`, and `Xylene, o-` is `o-xylene`. Plain concatenation
would give `2-methyl2-butene`, which is not a name.

**A shape it is not sure of is declined, not guessed.** Two kinds. `Ethane,
1,1,1,2-tetrafluoro-, HFC-134a` carries a family name after the substituent.
`Dioxin, 2,3,7,8 Tetrachlorodibenzo-p-` ends in a hyphen that belongs to
`dibenzo-p-dioxin`, which is one word, rather than marking an attachment. Both
have right answers; reading either needs chemistry this rule does not have, so
it returns nothing. An unmatched row is visible in the merge report. A confident
wrong spelling is not.

### Valence and ion spellings

A Roman numeral after an element is its **oxidation state** — how many
electrons the atom has given up. It is not decoration: arsenic III and arsenic
V behave differently in water and are characterised differently, which is why
the list holds them as separate substances.

| The list ships | It means |
|---|---|
| `Arsenic V` | `Arsenic(5+)` |
| `Cadmium II` | `Cadmium(2+)` |
| `Iron, ion` | `iron ion` — dissolved and charged, charge unstated |
| `Perchlorate, ion` | `Perchlorate` |

The charged form is **read off the list's own data, not invented**. The list
publishes its named ions as `X(n+)` — one spelling, whichever of the roman,
parenthesised and numeric variants the source wrote
([#141](https://github.com/brightway-labs/brightway-flows/issues/141)).
`Chromium III` is the corroboration that reading a numeral this way is right:
the row ships 16065-83-1, the trivalent ion's own registry number, and lands on
`Chromium(3+)` by that number before the name is read at all.

A registry number outranks the name where the two disagree
([A name is not an identifier](../deciding/identity.md)),
and that is what made five of these rows land wrongly for a while. `Cadmium
II`, `Zinc II`, `Mercury II`, `Lead II` and `Nickel II` ship the **metals'**
numbers — 7440-43-9 for cadmium the element, and so on — beside names that
state the +2 ion, so each landed on the element, while ecoinvent's fourteen
rows of the very same name, carrying the ions' numbers, landed on `Cadmium(2+)`
and its siblings. The matcher was right to believe the number; the number was
wrong. Each of the five is now given the ion's number by a curated fix
([#146](https://github.com/brightway-labs/brightway-flows/issues/146)),
recorded as a replacement of what the vendor wrote rather than as a reading of
the name — the shape EF's own `vanadium (v)` correction uses.

Two details decide whether it is safe:

**A geography is not a valence.** `VI` is also the ISO code for the Virgin
Islands. What keeps them apart is that BAFU writes a geography after a comma —
`Water, VI` — and the valence rule requires whitespace and a single-word
element before the numeral. It fires on `Arsenic V` and on nothing in #65's
181 names.

**An unspecified ion never falls back to the uncharged element.** This is the
failure the issue names, and the guarantee is the shape of the alias rather
than a matter of getting six names right: it always ends in ` ion`, and every
object in the list answering to `<name> ion` is a species that is an ion by
definition — `Perchlorate`, `Sulfate`, `Chloride` and their kind. A neutral
element is spelled `Iron`, answers to `Iron`, and cannot be reached from here.

What decides an unspecified ion is **the list's own inventory, not the
environment the flow was emitted to**. Where one object answers to `<name>
ion`, that is what the row means — perchlorate has exactly one form, carries
charge −1 and the formula `ClO4-`, so the alias is one species spelled twice.
Where several answer to it, `multiple-flow-object-candidates` is recorded and
the row stays unmatched.

So `Iron, ion` reaches a substance that states no charge. Before
[#141](https://github.com/brightway-labs/brightway-flows/issues/141) it
found nothing: the list held only `Iron(2+)` and `Iron(3+)`, the row does not
say which it is, and picking one would assign a toxicity and a mobility by
regex. The retirement build then minted `Iron, Ion` from ecoinvent's own
charge-withheld `Iron ion` rows, and BAFU's row lands on it by label — the two
lists' charge-unstated iron is one substance, and still nobody has guessed a
charge, because the substance itself states none.

No redox guess is made, and none would be sound. `Iron, ion` arrives in
`emissions to water / unspecified`, which names no water body: Fe(II) dominates
anoxic groundwater and Fe(III) oxic surface water, and the compartment records
neither. `Arsenic, ion` arrives in `emissions to air`, where free ions do not
exist at all. The rows needing a guess are the ones carrying the least
information to guess from.

A row left unmatched still creates a substance rather than being dropped — see
[#71](https://github.com/brightway-labs/brightway-flows/issues/71) for
what that substance currently knows about itself, which is very little.

Of BAFU's six once-unmatched rows in this shape, **all six now reach a
published flow, and none of them by guessing**. Four were given their numbers
by curated fixes
([#127](https://github.com/brightway-labs/brightway-flows/issues/127)):
`Arsenic V` and `Vanadium V` are arsenate and pentavalent vanadium —
17428-41-0 and 22537-31-1, landing on `Arsenic(5+)` and `Vanadium(5+)` — and
`Calcium II` and `Perchlorate, ion` name forms with exactly one possible
charge, 14127-61-8 and 14797-73-0. The last two, `Arsenic, ion` and
`Iron, ion`, state no charge and land by label on the generic-ion substances
[#141](https://github.com/brightway-labs/brightway-flows/issues/141)
minted, `Arsenic, Ion` and `Iron, Ion`, whose whole meaning is that the charge
is unstated. The guarantee this section is about survives in a stronger form:
no BAFU row reaches a charged form on its name alone.

### Geography in the name

BAFU writes where the water was taken into the flow's name. This list does not
model geography there at all — it records where a flow happened in the flow's
**context**, and its names say what the substance is — so 181 names arrive
describing water the list already holds and match nothing
([#65](https://github.com/brightway-labs/brightway-flows/issues/65)).

| The list ships | It means |
|---|---|
| `Water, AE` | water, taken in the United Arab Emirates |
| `Water, unspecified natural origin, RER` | the same, for ecoinvent's Europe |
| `Nitrogen dioxide, RAF` | nitrogen dioxide, for Africa |
| `Water, OECD` | water, for the OECD countries |

Read as shipped they are 181 parallel waters. Read with the place taken out
they are **eleven flows**, each of which BAFU mostly already ships in its own
right.

**So the place comes out at extraction, not at matching.** `Water, AE` becomes
the flow `Water` with `location` `AE`, and the name as shipped is kept on
`original_name`. That ordering is the point:

- The row **creates the right flow when it fails to match.** A row still called
  `Water, AE` mints a flow object from that name, so the country ends up in the
  consensus list — 53 flows in the 2026-08-13 build are exactly that. A row
  called `Water` mints the flow object its unregionalised sibling mints, and
  `_add_created_flow` puts the second row on the first row's flow. Twenty-one
  countries become one flow with twenty-one source refs.
- **Every rule in between sees a name it recognises** — the context rules, the
  `Occupation, `/`Transformation, ` name prefixes, the manual fixes. None of
  them had to learn about geography.

**The two rows stay two flows.** `location` joins the identity seed, so `Water,
AE` and `Water, AR` keep separate identifiers and separate correspondences —
they are two rows BAFU ships, and fusing them would throw away the distinction
this is trying to preserve. It is appended only when there is one, so the 2,417
flows carrying no place keep the identifiers they were first published with and
only the 262 regionalised ones are renumbered.

Three details decide whether it is safe:

**Both halves are whitelisted, and the base label is the whole of the safety.**
A name is read as regionalised only when the part in front of the last comma is
one of eleven labels this project has agreed can carry a place — `Water`,
`Water, river`, `Water, well`, `Nitrogen dioxide` and the rest. A trailing
two-letter token is not rare in a flow name: BAFU ships `Silver, 0.007% in
sulfide, Ag 0.004%, Pb, Zn, Cd, In`, where `In` is indium, alongside `Water,
IN`, where `IN` is India. Capitalisation is the only thing separating those two
in the name, so the rule does not rest on it — it reads both halves
case-insensitively and declines the first on its base label instead. `Ammonia,
NL` is declined for the same reason, and that is the intent: nothing has agreed
this list holds an ammonia the suffix belongs to.

**The countries are a standard; the regions are not.** All 249 ISO 3166-1
alpha-2 codes are admitted, not just the 76 BAFU uses, so a release that adds a
country needs no change here. The non-country groupings are admitted one at a
time, because they are a vendor's list with nothing behind them — `RER` is
ecoinvent's Europe and is not defined as the continent, and `OECD` is an
economic grouping rather than a place. Five are in: `Europe`, `GLO`, `OECD`,
`RAF`, `RER`. `RoW` — "everywhere this dataset does not cover", which has no
fixed extent — is deliberately not among them.

**A withdrawn code is reported as its successor, and keyed as written.** `CS`
was Serbia and Montenegro, a state that dissolved in 2006 and whose code ISO has
since withdrawn. BAFU still ships `Water, CS` in 64 exchanges with real amounts,
so it is not a dead entry: its `location` is `RS`. The *identity* still seeds on
`CS`, because that is what the vendor wrote — canonicalising there would fuse
`Water, CS` with `Water, RS` the day a release puts both in one context.
`split_geography_suffix` and `canonical_geography_code` are that division.

**What the pipeline does with the two new fields: nothing, deliberately.** They
land in `Flow`'s passthrough bag, round-trip into `flow_json`, and no
transformer or matcher reads either. `location` is where a `dcterms:spatial` on
the correspondence would come from, and typing it is that change's job;
`original_name` is kept for the record and is **not** a synonym — as a label it
would put `Water, AE` back in front of the matcher, which is the shape this
stopped being.

Two of the eleven base labels are not flows BAFU also ships on its own, and two
more were absent only because it spells them with the unit in the name instead —
`Water, unspecified natural origin/m3`. That is the habit below, not this one,
and it is what reunites them. It is why 181 names left and only 177 name-shaped
rows disappeared: 1,187 distinct names became 1,010.

### The unit inside the name

SimaPro lists flows in one flat column keyed on names alone, so a substance
measured two ways has to say which way in its name. BAFU ships ten such names
across 18 rows
([#67](https://github.com/brightway-labs/brightway-flows/issues/67)):

| The list ships | Its `unit` field | It means |
|---|---|---|
| `Water/m3` | `m3` | water, in cubic metres |
| `Waste water/m3` | `m3` | waste water, in cubic metres |
| `Wood, unspecified, standing/kg` | `kg` | standing timber, by mass |
| `Water, process, unspecified natural origin/kg` | `kg` | process water, by mass |
| `Water, process, unspecified natural origin/m3` | `m3` | process water, by volume |

This list carries the unit as its own field, so the copy in the name says the
same thing twice — and, being a copy, it is also why the row matches nothing:
no flow object anywhere answers to a name with a unit stuck on the end.

**The comparison is against the row's own unit**, case-insensitive but
otherwise exact. That is the whole safety of the pattern: `Occupation, traffic
area, rail/road embankment` keeps its slash because `road embankment` is not
`m2a`, and `Gas, natural/m3` measured in `Nm3` is declined because a normal
cubic metre is gas at a stated temperature and pressure rather than a volume,
so the name and the field disagree about which was meant. Which of the two to
believe is a curator's question rather than a pattern's, and it is answered in
[`bafu-2026-v1-manual-fixes.json`](#manual-fixes), which runs first.

**A suffix comes off wherever it is a copy of the row's own unit**, and there
is no case where it stays. That is the whole rule, and it is worth saying what
it replaces, because the answer used to be more complicated. Where two rows
would strip to one name in two different units, the suffix was read as the only
thing telling them apart and both rows kept it — BAFU has one such pair:

```
Water, process, unspecified natural origin/kg   unit=kg
Water, process, unspecified natural origin/m3   unit=m3
```

That reading held the rows apart in name only. A flow's identity is its
substance and its context; the unit is not in it, and `(flow_object_id,
context_iri)` is unique across live flows. So two rows agreeing on a substance
and a compartment reach one flow whatever their names say — these two always
did, in both compartments they share — and the suffix bought nothing while
costing both rows their match, because no flow object answers to a name with a
unit stuck on the end.

Whether such a pair is one quantity is still a real question, and it is
answered by reading the vendor's archive rather than the vendor's names. For
standing wood the answer is yes: the volume rows are used in 134 datasets and
the two mass rows in one each, and no dataset carries both. For process water
in `resources / land` it is very nearly yes: 64 datasets use each spelling and
63 use both, but the mass there is a fixed 6.58 × 10⁻⁵ to 6.65 × 10⁻⁵ of what
the volume implies — a ratio that tight across 63 datasets is two numbers
generated from one, and reading them as one flow costs 66 parts per million. In
`resources / unspecified` it is genuinely open: 57 datasets carry both and the
ratio scatters from 1.6 × 10⁻⁵ to 3.89. Where the answer is known, a curator
states the conversion in [`bafu-2026-v1-manual-fixes.json`](#manual-fixes) —
0.00204 m³/kg for the timber, 1000 kg/m³ for the water — and the flow is
published in one unit with the factor on every mapping back to the vendor.
Where it is not, both rows are published, each keeping its own identifier, its
own unit and its own mapping.

**The vendor's spelling is added as a synonym**, and it is worth being exact
about what that does. The merge reads a row's synonyms when it matches the row,
so the spelling helps it find its flow. It is not published: `bootstrap_labels`
moves the name into `prefLabel` and purges both fields, so no consensus flow
carries `Water/m3` as an alternative label. A consumer holding a BAFU inventory
finds their row through the correspondence written for its uuid, which is what
BAFU's own identity is built on, rather than by searching for the name their
file uses.

### What happens to a derived spelling

The two alias rules above, not the split — that one *is* the row, and the
section on it says what it writes.

Nothing is written to the flow. The derived spelling is used to look up a flow
object and then discarded: what the vendor called the flow stays its name, and
the published record gains no label this project invented.

The lookup is the existing machinery's. It reuses the same label index and the
same `_narrow_label_candidates` guard as an ordinary label match, so a derived
spelling that hits an object carrying registry numbers the source row does not
have is still refused — a parallel matching path would have had to re-earn that
caution.

So a name that de-inverts to something the list does not hold simply does not
match, and the row goes on to create a flow as it would have anyway. Of the 34
names BAFU 2026 v1 spells this way, **32 name a substance the list already
holds**; `perfluorocyclopropane` and `2-(thiocyanatemethylthio)benzothiazole`
are genuinely absent and are meant to be created.

Measured over every BAFU row rather than over the unmatched ones, deliberately.
Twelve of the 34 had already matched by other means, and it was those that
exposed the two join rules above — a rule checked only against rows that failed
would have hung a wrong spelling on a flow that was already right.

## Concept associations

The `xkos:Correspondence` a list publishes, as three values rather than a Python
class per list:

```json
"concept_associations": {
  "scheme": "simapro-10.2",
  "pairs_from": "glad",
  "primary_source": "https://github.com/One-Click-LCA/GLAD-ElementaryFlowResources"
}
```

| Key | What it is |
|---|---|
| `scheme` | Slug of a scheme in `SOURCE_SCHEMES`. **Not necessarily this list's own** — a list whose flows originate in SimaPro publishes mappings to the *SimaPro* scheme, because that is whose flow identity its rows carry. An unregistered slug fails when the manifest is read |
| `pairs_from` | `source_refs`, when each consensus flow already records which of this list's flows it came from; `glad`, to read the GLAD EF 3.1→SimaPro correspondence table, for a list the consensus flows were never merged from |
| `primary_source` | `prov:hadPrimarySource` for the mappings. Optional for `glad`, which knows the table it reads |

**Declaring it is also what switches it on.** The builders for a run are the
base list's plus those of every list named by `--source`. GLAD is therefore
downloaded and parsed by a build that merges a SimaPro-derived list, and by no
other — it used to be pulled by every `extract`, for a builder no build
registered.

## What a source list's flows must look like

Either a bare list of flow records, or an object with a `flows` key (`flow_data`
is also accepted):

```json
[ {"uuid": "…", "name": "…", "source": "…", "context": "…", "unit": "kg"} ]
```

Per record:

| Field | Required | Notes |
|---|---|---|
| `uuid` | **yes** | Rows without one are dropped |
| `name` | yes | |
| `source` | yes | The list's display string, carried through to the published flow. It is *not* where the list name and version come from — those are the manifest's |
| `context` | yes | A list of strings, or a structured context object |
| `unit` | yes | Must resolve against the unit vocabulary |
| `cas_numbers`, `ec_numbers`, `synonyms`, `prefLabel`, `altLabel`, `properties` | no | Used if present |

Rows that are not objects are ignored. The same shape and the same normaliser
apply to the EF 3.1 base file, so a flow arrives in one shape however it is
reached.

## What happens as a row is loaded

Three things, in order.

**Normalisation.** A UUID is required; whitespace is stripped and capitalisation
rules applied. Rows that cannot be normalised into a valid record are dropped.
A source list's manual fixes are applied to the raw rows *before* this, because
they name the source's own field names — `cas_number`, not `cas_numbers`. For a
list `simapro_origin` is true of, two more things happen between the two, in
this order. The [lineage's own fixes](#simapro-lineage) are applied next, after
the list's and never before them, because a list that has already corrected a
row must not be corrected twice. Then a name whose tail is this row's own unit
loses it and keeps the vendor's spelling as a synonym, unless that tail is the
only thing telling two of the list's flows apart — which runs last of the three
because it reads the names the fixes leave. See [The unit inside the
name](#the-unit-inside-the-name).

**Source references are attached.** Every row gets a `source_refs` entry
recording where it came from:

```json
{
  "list_name": "EF",
  "list_version": "3.1",
  "source_flow_uuid": "0000b186-aea3-4c0a-b0c2-c284de7cdf92",
  "source_flow_name": "(3r,3ar,6s,6ar)-hexahydrofuro[3,2-b]furan-3,6-diyl dioctanoate",
  "source_metadata": {
    "input_file": "/…/ef-31-flows.json",
    "input_dataset": "EF 3.1",
    "original_context": ["Emissions", "Emissions to air", "Emissions to air, indoor"]
  }
}
```

The original name and the original compartment strings are kept verbatim. This
is not bookkeeping for its own sake — it is what lets you audit a merge later,
and it is what makes the output usable as a translation table.

`list_name` and `list_version` are copied from the list's manifest, not read out
of the `source` string beside them. `source` is a *display* string — `EF 3.1`
with a space, `ecoinvent-3.12` with a dash — and the pair used to be recovered
from it by splitting on the first dash when the tail contained a digit. A list
called `US LCI` or `Stepwise 2006` has no dash to split on, so it would have
shipped its whole display string as the list name and an empty version into both
`source_refs` and `elementary_flow_sources` (#13). Every caller has the list in
hand, so both places ask for it.

They survive in `consensus-flows.sqlite3` — in `elementary_flow_sources`, and
on the flow's detail page under **Source lists** — and in the merge tables. The
published export strips them; see
[Known limitations](../reference/limitations.md).

**Nothing is deduplicated.** Two source lists supplying the same substance in
the same context produce two rows at this stage. Deduplication happens after all
processing steps have run, during layering, when there is enough resolved
identity to do it correctly and the evidence for the decision can be recorded.
Deduplicating at load time would destroy that evidence.

## After loading

Every processing step runs in a fixed order over all flows, then the result is
split into flow objects and elementary flows and written out. See
[Harmonisation steps](../reference/harmonisation-steps.md) for what the steps
do, and [Which output do I need?](../using/outputs.md) for what comes out.

## Adding a new source list

1. Add a manifest to `src/brightway_flows/data/sources/`, choosing a
   `flow_iri_prefix` you are willing to publish. Leave `prepared_match_table`
   null — every list does, and not because nobody has mapped them: the vendor
   correspondence tables were retired deliberately (#141), and rows go through
   evidence matching plus whatever curated rows the list's own
   `match_overrides` file states. That stays the rule when a new ecoinvent
   release arrives with a published table of its own: don't declare it. The
   existing overrides cover the new release's uuids already, and the
   post-merge check is `tools/audit_prepared_correspondence.py` against the
   new build, not the vendor's opinion.
2. Write its [adapter](#adapters) — one `fetch(source, *, force=False) -> Path`
   in `brightway_flows/integrations/`, named by the manifest's `adapter` —
   and run `fetch-source <key>`.
3. Map the source's compartments onto consensus context IRIs, and register the
   mapping in `context-manual-mapping.json` so the context step can read it. A
   standalone mapping file will not be picked up. A row whose context maps to no
   consensus IRI stops the run rather than being guessed at, so this is a
   prerequisite and not a refinement.
4. Check that every unit resolves against the unit vocabulary. Unresolvable
   units fail the run.
5. Run bounded first, in an isolated data directory, and read the review queues
   and the merge report before running it for real.

Adding a list is a manifest and its data files. If it turns out to need a code
change, the code change is a defect in the merge rather than a step in this
list.
