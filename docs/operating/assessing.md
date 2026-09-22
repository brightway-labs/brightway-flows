# Assessing a build

The test suite tells you whether the code is broken. It cannot tell you whether
the output is getting better, or whether the change you just made did the thing
you said it would do. `brightway-flows assess` answers that.

```bash
uv run brightway-flows build --source ecoinvent-3.12 --source bafu-2026-v1
uv run brightway-flows assess
```

It reads `consensus-flows.sqlite3` and nothing else, and it never writes to it.

`build` merges nothing unless asked, so which lists you name is what the
placement table below can report on — and a baseline recorded from one set of
sources is not comparable to a build with another. `assess` says so rather than
reporting every measure of a list you did not merge as a collapse.

## What it prints

**What it published** — how many flows and substances came out, how many flows
carry a characterisation factor, how many are deprecated.

**Where each list lands** — one row per source list: how many rows it shipped,
how each of them was placed, and what share reached a flow that already existed
rather than one the merge had to invent.

```
  list                       rows   prepared  algorithm     manual    created   unplaced  charact'd     unit x  on existing
  ecoinvent-3.12            9,850        189      8,813          0        848          0      6,487          0        91.4%
  ecoinvent-3.8             4,421        199      4,220          0          2          0      2,502          0       100.0%
  bafu-2026-v1              2,679         26      2,562          0         91          0      1,467        162        96.6%
  stepwise-2006-1.09        6,055         13      5,921          0        119          2      3,725          0        98.0%
  agribalyse-3.2            5,485         22      5,383          0         80          0      3,204         26        98.5%
```

**Expectations** — the statements in `expectations/`, each graded against this
build. For anything that does not hold, it prints what the merge decided
instead, and every candidate the selector scored:

```
  UNMET (pending)   #65 0381-bafu-water-lands-somewhere
      The BAFU rows named `Water` land on a consensus flow that already exists
      not_outcome: expected 'unmatched', got {algorithm: 119, unmatched: 50}   [50 of 169 rows]
        'Water' ['emissions to air', 'unspecified'] -> unmatched (tied-elementary-candidates)
          candidate 3  kg  Environmental / Air / Aircraft cruise height  2905ed3b
          candidate 3  kg  Environmental / Air / Unknown                 fe0acd60
          candidate 3  kg  Environmental / Air / Long-term               fe0acd60
```

That last part is the point. A checker that says only "unmet" sends its reader
back to the database to find out why; the database already knows, and the merge
records every candidate it scored.

**Since the baseline** — every measure that has moved since somebody last ran
`assess --record`, labelled improved or regressed where the direction is
unambiguous and `moved` where it is not.

## Writing an expectation

A pull request that closes an issue adds a file to `expectations/` saying what
should now be true. See
[`expectations/README.md`](https://github.com/brightway-labs/brightway-flows/blob/main/expectations/README.md)
for the whole vocabulary; the short version is that an expectation names a
subject and states a claim about it.

```json
{
  "id": "0381-bafu-water-lands-somewhere",
  "issue": 381,
  "title": "The BAFU rows named `Water` land on a consensus flow that already exists",
  "subject": {"kind": "source_row", "list": "bafu", "name": "Water"},
  "expect": {"not_outcome": "unmatched"},
  "comment": "169 rows, all unmatched on a tie in the 2026-08-14 build.",
  "pending": true
}
```

A subject is a row of a vendor list (`source_row`), a consensus flow (`flow`), a
substance (`substance`), or one counted number (`measure`). `pending: true`
means the project agrees this is not true yet — it is still evaluated and still
printed, but it does not make `--strict` fail. Drop the flag in the pull request
that makes it true.

Every key is checked against a closed list, and so is every value: a misspelled
claim, a bound with an unrecognised key (`{"at_mst": 3}`), a count written as a
string, a boolean written as `"true"` — each is a load error naming the file and
the key, rather than a line that is silently ignored or an expectation that
passes without testing anything. `tests/test_expectations.py` loads every file,
which means a typo fails the test suite and never reaches a build.

## Four results, not two

| | |
|---|---|
| **met** | every claim holds |
| **unmet** | the subject is there and a claim does not hold |
| **unresolved** | the selector matched nothing — the subject has been renamed or removed upstream, or the expectation names it wrongly |
| **error** | this build has no table that could answer the claim |

`unresolved` is kept separate on purpose. Folded into `unmet`, an expectation
whose subject has quietly gone away still reads as work to do, and goes on
testing nothing.

## Recording progress

```bash
uv run brightway-flows assess --record   # then commit expectations/baseline.json
```

`baseline.json` holds every measure and every expectation's status as of the
build it was recorded from. It is committed so that a pull request improving the
matching carries the movement in its own diff:

```diff
-    "merge.bafu-2026-v1.unmatched": 275,
+    "merge.bafu-2026-v1.unmatched": 10,
```

Record only from a full build, and from the same `--source` list you will
compare against. A `--max-flows` run measures a prefix of the base list, and a
baseline taken from one would report every count as collapsed on the next full
run; `--record` refuses it. A `--max-rows` run is refused for the same reason
on the other side: it merges a prefix of each source list, so every `merge.*`
count is a count of the sample. Both bounds are printed at the top of the
report, so a number you are about to trust says what it was taken from. A build that merged a different set of source lists
is not comparable either — every `merge.*` measure of a list only one of them
merged would read as gone or new — and `assess` says so instead of printing a
regression that is only a different flag.

The baseline records, it does not gate. Whether a movement was allowed is what
an expectation says — a threshold on a population ("no more than 300 unmatched
rows") passes for the wrong reason as easily as the right one, while "this row
lands on this flow" cannot.

## Other outputs

```bash
uv run brightway-flows assess --json report.json    # everything, including all 485 measures
uv run brightway-flows assess --html report.html    # a standalone review page
uv run brightway-flows assess --strict              # exit 1 if anything not `pending` fails
uv run brightway-flows assess --verbose             # list the expectations that hold, too
```

The JSON carries every measure key this build supports, which is how to find out
what a `measure` expectation can name: the merge and pipeline counters are all
there, under `merge.*`, `flows.*`, `substances.*`, `queue.*`, `stats.*` and
`lookup.*`. The `stats.*` family is `run_stats` — the hundred-odd counters the
transformers already write — folded in rather than restated, so there is only
ever one number for each thing.

The `lookup.*` family is the odd one out: it is not counted from a table but
*measured*, by asking [the lookup](../using/matching-your-own-list.md) every
question this build has already answered and comparing. It costs about thirteen
seconds against a four-list build, which is why nothing else pays for it, and it
is what says whether a change to the matching has quietly stopped the two
agreeing. The key to watch is `lookup.evidence.other_flow`: rows the lookup
places on a flow the build did not choose. It should be nothing.

The HTML is self-contained and theme-aware, which makes it the thing to send
somebody who is not going to run the command.

## Auditing the curated correspondence

ecoinvent used to publish a table saying which EF 3.1 flow each of its flows
is, and the merge honoured it before it looked at a registry number. Where the
two disagreed the result could be quietly wrong in a way no other check saw —
metaldehyde's rows sent to an uncharacterised duplicate of the pesticide they
name, a herbicide's resource factor published on granite — which is why the
audit exists, and eventually why the tables were retired outright
([#141](https://github.com/brightway-labs/brightway-flows/issues/141)).

What lands as a `prepared` outcome now is this project's own rows from the
`*-match-overrides.json` files, applied onto an empty table. The audit keeps
its job with a better subject: it sorts every one of *our* rows by whether the
row's own registry number agrees with where we send it, so a curated join that
contradicts the vendor's stated identity has to be a decision somebody wrote
down rather than a leftover:

```bash
uv run python tools/audit_prepared_correspondence.py .data/consensus-flows.sqlite3
```

Most rows agree or state nothing checkable. One disagreement shape is expected
and whitelisted, because the modelling is stated on the row itself: an
ore-content resource flow (`TiO2, 54% in ilmenite…`) names its own grade and
converts onto the element it is mined for with a per-row factor. (A second
whitelist used to excuse the tables' element-versus-ion compartment routing;
it retired with the tables, so a curated row that confuses an element with its
ion prints as contradicted rather than being excused.) Everything else prints
as `CONTRADICTED`, one line per decision with the substance the registry
number actually names — unless the row **signs** the contradiction:
`"not_the_stated_substance": true` in its override file, beside the comment
that argues it, and the group bins as acknowledged instead. The `Carbon`
routing is the founding case — ecoinvent registers its soot measure under the
element's number, and sending it to `Elemental Carbon` anyway is a decision
#141 recorded and signed. A signature on a row that in fact agrees with its
number is stale and flags the same way, so the file cannot drift in either
direction without the audit saying so. `--all` prints the whitelisted and
acknowledged groups too, which is how the scheme and the signatures get
reviewed. `--strict` exits non-zero on any unsigned contradiction or stale
signature and passes on a build whose every disagreement is a signed
decision — on the first post-merge build it exits 0, and it is the routine
gate.

Run it when a new ecoinvent release arrives or the override files change,
before anything downstream reads the build. The defects it catches are fixed
in the `*-match-overrides.json` files; `plans/retire-prepared-correspondence.md`
is the longer story.

## What this is not

It is not [`tools/verify_run.py`](../reference/architecture.md). That runs the
same bounded job under two revisions and diffs every artifact, which is how a
refactor is shown to have changed nothing. `assess` reads one build and asks
whether it is right. A refactor wants the first; a change to the matching wants
the second.
