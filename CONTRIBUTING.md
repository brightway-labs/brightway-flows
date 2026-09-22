# Contributing

Most of what is wrong with this list will be found by somebody who knows one substance,
one compartment or one source list better than we do, and who has no intention of ever
reading the code. This page is arranged around that: the first two routes need nothing
installed.

## You do not need to run a build

Building the list downloads several gigabytes, needs a licensed archive for some source
lists, and on a cold cache takes hours — the pipeline queries PubChem, ChEBI, Common
Chemistry and Wikidata under deliberate rate limits so as not to hammer them. None of that
should stand between you and reporting that a herbicide is published as its own salt.

So the division of labour is: **you supply what only a person can — which half is wrong,
and why. The build supplies the measurement.** The forms do not ask you how many rows are
affected, what the list currently publishes, or what the other source lists say. Those are
looked up.

## Three routes

### 1. Report something that looks wrong

[Open an issue](https://github.com/brightway-labs/brightway-flows/issues/new/choose)
and pick the form that matches what you were looking at:

| If | Use |
|---|---|
| a row from your list is published as the wrong substance, or as none | **A row reaches the wrong substance** |
| the name and the registry number name two different chemicals | **A flow is not that chemical** |
| the substance is right and the name is not | **A substance is published under the wrong name** |
| the substance is right and the compartment or the unit is not | **A flow is in the wrong compartment, or the wrong unit** |
| one substance is published twice, or one record holds two | **Two records are one substance, or one record is two** |
| a characterisation factor cannot be about this substance | **A characterisation factor looks wrong** |
| a page says something untrue or unfollowable | **A documentation page is wrong or unclear** |

Before you write, it is worth a minute on [What we have
found](docs/findings/index.md). It records the classes of error already
found in the source data, each with a worked example — if your case is one of them, saying
so is the fastest way to get it understood. [Known
limitations](docs/reference/limitations.md) records what is still wrong on purpose, and
[How a flow is decided](docs/deciding/index.md) is the reasoning behind the
decisions. A good many surprises in this list are documented choices, and some of them are
choices we would change if somebody argued against them well.

**Two things make a report actionable.** Name the row exactly as your list ships it,
including the release — an identifier can keep its name and change its substance between
two releases, so a claim about a UUID means nothing without one. And say what your evidence
is. Where a name and a number disagree there is no way to tell from the flow alone which
half is wrong, so the evidence *is* the argument.

**Titles.** Say plainly what is wrong, concretely enough to mean something to somebody who
has not opened the issue: `Fix nine substances published in two resource contexts`, not
`A substance is taken from one place, and the rule now says which`. Name the substance, the
list, the file or the count.

### 2. Answer a question the list is waiting on

The pipeline does everything a rule can do and then stops, because what is left is a
judgement. Those judgements sit in the queues at `/queue/` on the website — one registry
number claimed by two names, a rename awaiting a ruling, a row that matched too much.

[The form for these](https://github.com/brightway-labs/brightway-flows/issues/new?template=answer-an-open-question.yml)
asks for the row, your verdict and your reasoning, and nothing else. You do not need to
know which of the decision files owns the question or what shape it wants. If you do know,
there is an optional box for it, and CI will check it.

The reasoning is not a formality. Every decision recorded in this project is a paragraph
of evidence, because a one-word answer nobody can check is not worth storing.

### 3. Open a pull request

See below.

## How CI answers a claim

CI does not run on its own. **A maintainer approves each run**, so there is a wait, and a
flood of drive-by issues cannot spend the build farm.

When it does run, it has a reference build of the merge base already in hand, built before
your changes. Against that it can do two things:

- **Answer** — look your claim up in the reference build. What the row reaches today, what
  the other lists do with the same substance, which factors are on it, and whether an
  existing expectation already covers it. No build required.
- **Try** — if you proposed a fix, apply it, build the list, and diff that build against
  the reference. Every row that moved, not only the ones you were thinking about. A
  compartment rule or a rename reaches far past its target, which is the whole reason this
  step exists. Identical hashes mean your proposal changed nothing — usually a row keyed on
  a name or an identifier that matches nothing, which is otherwise only discovered in
  review.

**The result is a workflow run with an artifact attached, not a comment.** The artifact
holds the merge-outcome diff, the grades for the claims, and the build hashes. Issue
threads stay readable, and a run that produced nine hundred moved rows does not bury the
conversation.

**Nothing is committed until a pull request is merged.** If your issue proposed a fix and
it is accepted, the `expectations/` file recording the claim is committed at merge, and CI
runs again against the merged result.

## Pull requests

Branch off `main`, one unit of work per branch.

```bash
uv venv
uv run python tools/seed_data_dir.py
export BRIGHTWAY_FLOWS_DATA_DIR=$PWD/.data
```

That third line goes in every shell that fetches, builds or runs the tests. Each working
copy gets its own data directory; never point one at a shared one, and never copy an
extracted list or a built database in from another.

Then:

```bash
uv run pytest
uv run ruff check --select F821,F401,F811
```

The second has repeatedly caught defects no test exercises, which is why it is called out
separately.

### State the claim as data

**A change that says it fixes an issue states the claim in `expectations/`** — one file per
issue, named for it, checked by `brightway-flows assess` against the build. Not as a
sentence in the pull request description, which nobody re-reads, but as a file somebody can
run.

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
      "comment": "What the build does today, measured, and why the expected answer is right.",
      "pending": true
    }
  ]
}
```

Write the claim while it is still false, and mark it `pending`. Drop the flag in the change
that makes it true. [`expectations/README.md`](expectations/README.md) has the whole
schema.

### Say what the change is meant to do

The pull request template asks whether the change is meant to alter the output. That is
load-bearing rather than bureaucratic: for a refactor, an identical hash is the success
criterion, and for anything else it is the failure. CI can produce the diff either way but
cannot know which you intended.

### If you are changing the harmonisation chain or the merge

Two jobs here have a procedure rather than a rule, and both are written down for whoever is
doing them — adding, removing or reordering a step in the harmonisation chain, and changing
where the merge puts a source row. Both live in `.claude/skills/`. Read the relevant one
before writing the fix; each has registration points and pages that have to move with the
change, and the second asks you to name the row and measure the build *before* touching
anything.

## Writing

Documentation here is written for an environmental engineer, not a programmer: an example
before the rule, substances and compartments rather than classes and functions, and code
only where the reader will type it. Three pages are exempt and say so at the top —
`docs/reference/architecture.md`, `docs/reference/conventions.md` and
`docs/reference/data-model.md`.

Quote the number and name the build it came from, rather than writing "some" or "many". A
count copied out of the curated data gets a case in `tests/test_documentation.py`; nothing
else stops it drifting.

## Reporting something that should not be public

If you find credentials, licensed source-list content, or personal data in this repository
or on the site, please do not open an issue. Write to the address on the site's About page.

## The conventions behind all of this

[`docs/reference/conventions.md`](docs/reference/conventions.md) is the reasoning, and
[`AGENTS.md`](AGENTS.md) is the same rules stated one sentence each. Neither is required
reading to report a problem; both are, to change the pipeline.
