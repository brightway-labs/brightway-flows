# What this build is supposed to do

Each file here states, in data, something that should be true of the published
output. `brightway-flows assess` reads them all, checks each against the
last build, and prints what holds, what does not, and — for anything that does
not — what the pipeline did instead and why.

The point is to make a claim checkable. "This fixes the water matching" is a
sentence in a pull request description that nobody re-reads; a file here that
says *the BAFU rows named `Water` land on the consensus water flow* is a
sentence somebody can run.

```bash
uv run brightway-flows build --source ecoinvent-3.12   # produces the artifacts
uv run brightway-flows assess                          # grades them against this directory
```

`build` merges nothing unless asked. An expectation about a list this build did
not merge reports `unresolved`, not `unmet` — which is right, and is why the two
statuses are separate.

## Adding one

A pull request that closes an issue adds or edits **one file per issue**, named
for it: `0381-bafu-water-names.json`. A file holds any number of expectations
about that issue.

```json
{
  "schema_version": 1,
  "description": "Why this file exists, in prose. Read by a person, not by code.",
  "expectations": [
    {
      "id": "0381-bafu-water-unqualified",
      "issue": 381,
      "title": "The BAFU rows named `Water` land on a consensus flow that already exists",
      "subject": {"kind": "source_row", "list": "bafu", "name": "Water"},
      "expect": {"outcome": "matched", "target_name": "Water"},
      "comment": "What the build does today, measured, and why the expected answer is the right one.",
      "pending": true
    }
  ]
}
```

`id` is what the baseline records a status against, so it has to be unique and
should not change once written — renaming one loses its history.

`title` is what the report prints. Write it as the sentence that should be true,
in words somebody who has not opened the repository can follow: *the BAFU rows
named `Water` land on a consensus flow that already exists*, not *bafu water
matcher returns non-null*.

`pending: true` means the project agrees this is not true yet. It is still
evaluated and still printed — it is the work queue — but it does not make
`assess --strict` fail. Drop the flag in the pull request that makes it true.

**Every key is checked against a closed list, and so is every value.** A
misspelled claim is a load error, not a silently ignored line, and
`tests/test_expectations.py` loads every file in this directory. So a typo fails
the test suite rather than producing an expectation that passes without testing
anything.

Values are checked for the same reason. A bound whose key is misspelled —
`{"at_mst": 3}` — used to load, match no comparison, and report **met**, which
is the worst outcome available: a typo that turns a check into a pass looks
exactly like a check that holds. So a bound's keys and types, a count's type and
a boolean's type are all rejected at load, with a message naming the file, the
entry and the key.

## What you can name

| `kind` | What it selects | Selectors |
|---|---|---|
| `source_row` | Rows of a vendor list, as the merge decided them | `list`, `version`, `uuid`, `name`, `name_contains`, `context`, `cas`, `unit` |
| `flow` | Consensus elementary flows (active ones, unless `include_deprecated`) | `uuid`, `name`, `context_iri`, `context_display`, `unit`, `include_deprecated` |
| `substance` | Flow objects — one substance identity, however many flows share it | `id`, `label`, `cas` |
| `factor` | One published characterisation factor: a flow, an impact category, and the implementation that stated it | `flow_uuid`, `flow_name`, `substance_cas`, `context_display`, `context_iri`, `category`, `implemented_by` |
| `measure` | One counted number about the build | `key`, `value_when_absent` |

Names match without regard to case, because vendors recapitalise the same
substance between releases and an expectation that broke on that would be noise.
Contexts, units, IRIs and identifiers match exactly.

`version` is optional. Leaving it out means "this list, whichever version was
merged", which is usually what an expectation about ecoinvent means; naming it
pins the expectation to one release, which is right when the issue is about that
release specifically.

### Name the subject the way it will still be findable

A selector is how a check finds its subject, and a subject that moves takes the
check with it. #106 left three expectations about borax and borate. Two of them
name the subject in words -- the flow called `Borate` in Resource → Ground, and
the substance called `Borate` -- and the third named it by registry number,
12447-40-4. #110 then renumbered borax to 1303-96-4, the number still in use,
and the third check went **unresolved**: nothing carries the old number any
more, so it had nothing to ask about, and it said so quietly rather than
failing. The two written in words went on working. That is #319.

So prefer the name to the number, and keep a number as the selector where the
number is what the claim is about -- as in #110's own pair, one of which exists
to say that no substance is published under the superseded number. And when a
correction moves an identifier, grep this directory for the old value: a check
that names it is not asking anything any more.

## What you can claim

**About a `source_row`** — where it landed:

| Claim | Meaning |
|---|---|
| `outcome` | `prepared`, `algorithm`, `manual-addition`, `created`, `unmatched`, or `matched` (the first three) / `placed` (the first four) |
| `not_outcome` | the same values, negated |
| `reason`, `basis` | why the merge decided as it did, and on what evidence |
| `target_name`, `target_uuid`, `target_unit`, `target_cas` | the flow it landed on |
| `target_context_iri`, `target_context_display` | the context of that flow |
| `target_characterised` | whether that flow carries a characterisation factor |
| `target_deprecated` | whether it landed on a flow the build deprecates |
| `target_substance_id` | the substance behind the flow |
| `unit_mismatch`, `context_inconsistency` | the two flags the merge raises on a row |

**About the set of rows a selector matched** — these are about the group, not
about each member:

| Claim | Meaning |
|---|---|
| `row_count` | how many rows the selector found |
| `same_target` / `distinct_targets` | they all reached one flow / no two reached the same one |
| `same_substance` / `distinct_substances` | the same two questions about the substance |
| `target_count`, `substance_count` | how many distinct ones they reached |

A flow and a substance are different questions, and the difference matters. Four
BAFU rows named `Silver-110` reach four flows, which is correct — they are in
four different contexts — and two substances, which is not. `same_target` would
call that fine; `same_substance` catches it.

**About a `flow`**: `exists`, `count`, `unit`, `context_iri`,
`context_display`, `characterised`, `deprecated`, `replaced_by`,
`substance_id`, `substance_cas`.

**About a `substance`**: `exists`, `count`, `label`, `cas`, `flow_count`,
`has_payload`, `flow_type`, `roles`.

`flow_type` is what the substance *is*: `NeutralMolecule`, `MonoatomicIon`,
`Material`, `Isotope`, or `unclassified` for one the typing rules could not
place. Write the short term rather than the full IRI — `MonoatomicIon`, not
`https://w3id.org/chemrof/MonoatomicIon` — and write it exactly, because it is a
vocabulary term and not a name anybody recapitalises. It is the claim to reach
for when the question is whether a substance the build created knows what kind
of thing it is: `unclassified` beside benzene is what #71 is about.

`roles` is what the substance is *used for* — `insecticide`, `herbicide`,
`fertilizer` — rather than what it is. It is met when the named role is among
the ones the substance publishes, so `{"roles": "insecticide"}` asks that it is
an insecticide, not that it is only an insecticide. Write the label, in ChEBI's
own spelling and lower case; the match is exact, because a role label is a
vocabulary term and not a name a vendor recapitalises.

**About a `factor`**: `exists`, `count`, and `amount` — the number itself.

Four implementations of EF 3.1 are published side by side: the JRC's, which is
the method's own publisher's; the ecoinvent Centre's; GreenDelta's, which is
published to be compared with and decides nothing; and this list's, which takes
one of the deciding two where they disagree. They are separate facts about one
flow, which is why `implemented_by` selects rather than being claimed — *the
JRC says 1.3532E-06 for vanadium in air* and *ecoinvent says 1.3532E-05* are
both true, and an expectation that could only name the flow would have to choose
which it meant. Stepwise 2006 is a second method, with one published
implementation of its own and this list's beside it.

`amount` is written as a **string, in the notation its source prints**, and the
digits are the tolerance:

```json
{"kind": "factor", "substance_cas": "7440-62-2", "category": "Ecotoxicity, freshwater",
 "context_display": "Environmental → Water → Surface water",
 "implemented_by": "European Commission — JRC"}
```
```json
{"amount": "4.78E+03"}
```

JRC 130796 Table 6 prints vanadium's freshwater ecotoxicity factor as
`4.78E+03`; the build holds `4775.290751488173`, and the two agree to every
digit the table states. A number would have to be either exactly equal — which
no transcription of a rounded table can be — or bounded by a tolerance somebody
picks per row, which is how a transcription error gets absorbed into a widened
bound. Rounding the build's value to as many significant figures as the claim
states asks exactly the question the document answers, and asks the same one of
every row. `"4.78E+03"` claims three figures; `"1.3532E-06"` claims five. A
float is refused at load rather than coerced.

It also survives the two implementations disagreeing in the last bit, which they
do: chromium(6+) is `12274.013470217462` under the JRC and `12274.01347021746`
under the ecoinvent Centre — one published number rendered twice.

**About a `measure`**: `equals`, `at_most`, `at_least`. A measure that
vanishes at zero -- most counts come off stats tables that write no row for
nothing -- may state `value_when_absent: 0` in its subject, so an
`at_most: 0` claim stays met rather than turning unresolved at the moment
the count it bounds is finally zero. Run
`brightway-flows assess --json out.json` to see every measure key this build
supports; the merge and pipeline counters are all there, under `merge.*`,
`flows.*`, `substances.*`, `queue.*` and `stats.*`.

Counts (`count`, `row_count`, `target_count`, `substance_count`) take a number
for exactly-that-many, or a bound: `{"at_most": 3}`, `{"at_least": 1}`, or both.

## Four results, not two

| | |
|---|---|
| **met** | every claim holds |
| **unmet** | the subject is there and a claim does not hold — the report shows what the merge decided instead, and every candidate it scored |
| **unresolved** | the selector matched nothing: the row has been renamed or removed upstream, or the expectation names it wrongly. The expectation needs rewriting, which is not the same job as fixing the pipeline |
| **error** | this build has no table that could answer the claim |

Keeping `unresolved` apart is the point of having four. Fold it into `unmet` and
an expectation whose subject has quietly gone away still reads as work to do.

## The baseline

`baseline.json` holds every measure and every expectation's status as of the
build somebody last ran `assess --record` against. It is committed so that a
pull request improving the matching carries

```diff
-    "merge.bafu-2026-v1.unmatched": 275,
+    "merge.bafu-2026-v1.unmatched": 22,
```

in its own diff. Rewrite it after a full build — never after a `--max-flows`
run, which measures a prefix of the base list and would record every count as
collapsed — and commit the result:

```bash
uv run brightway-flows assess --record
```

The baseline records; it does not gate. Whether a movement was allowed is what
an expectation says, because a threshold on a population ("no more than 300
unmatched rows") passes for the wrong reason as easily as the right one, while
"this row lands on this flow" cannot.
