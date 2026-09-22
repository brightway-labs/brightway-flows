# How do I find out why a factor says what it says?

*Part of [How a factor is decided](index.md). The last page of the section, and
the one to read when a number looks wrong.*

Every consensus factor answers the question in one word, its `derivation`, and
the word says where to look next.

| `derivation` | it means | look at |
|---|---|---|
| `sole` | only the method's own publisher stated it | the publisher's own row, on the same flow under their implementation |
| `agreed` | two deciding implementations stated one number within 2 %; the more precise printing is published and the other is in `also_stated` | both rows on the flow's page |
| `ruled` | a curator chose between numbers, or published in spite of the model | `data/lcia-factor-rulings.json`, and the queue row — now marked *ruled* — with the comment |
| `restated` | only a transcription stated it, and this list already published the same number for the same substance in another context of the category, within 2 % | the same substance's other contexts |
| `adopted` | a person signed for the substance taking another substance's number — an ion its element's, a pesticide a catch-all's, a land class its family's | `data/lcia-factor-adoptions.json`: the entry names the donor and the relationship |
| `carried` | nobody characterised the flow; the number was carried from a neighbouring context by the convention | `source_flow_uuid` is the flow it came from; the rule is `data/context-carry-rules.json`'s row for this flow's context |
| `moved` | published on the wrong flow and moved to the one it is about | `data/lcia-misattributed-factors.json` |
| `refined` | a rounded printing replaced by the precise value its own source states | `data/lcia-rounded-printings.json` |
| *(no factor)* | a queue is asking, a wall stands, or the blank has no rule | below |

## Where the numbers are

**On the flow's page** in the review application, every implementation's number
for every category, side by side, with the consensus row's derivation. This is
the first place to look: most surprises are one implementation disagreeing with
another, and the page shows it without a query.

**In the database:** `lcia_characterization_factors`, one row per (category,
flow, place), joined to `lcia_impact_categories` for the method, the category
and `implemented_by`. Only the consensus implementation's rows carry a
`derivation`; a transcription arrives at nothing, it says what its publisher
said.

**As a file:** `lcia-factors.json.gz`, every published factor of every
implementation, following the build's own redirects so that a factor about a
withdrawn flow is on its survivor ([outputs](../using/outputs.md)).

## Where the disagreements are

`/factors/differences`, or `lcia-differences.json`: every (flow, category,
place) where two implementations state different numbers, banded by how far
apart — within tolerance, 2×, 10×, 100×, more — and every one where one
implementation characterises a substance in a context and skips the context
beside it. The consensus row's derivation is on each difference, so a reader can
see that a 397× gap was ruled and a 10× gap is still open.

## Where the questions are

Three queues, each a work list of rows a person can answer, grouped by substance
and category because that is the unit a decision is made in:

| queue | asks | today |
|---|---|---:|
| `contested-factor` | two implementations differ; which? | 32 open, 6 ruled |
| `contradicted-factor` | the model underneath disagrees with both; publish anyway? | 8 open |
| `proposed-factor` | only a transcription speaks and nothing vouches for it; publish? | 16 open, 48 answered |

A ruled row stays on its page marked *ruled*, with the verdict and the comment;
the queue is a record as well as a work list.

## Where the blanks are

`/factors/coverage` counts, per context, the flows this list has that no
deciding implementation characterises while the same substance is characterised
next door — 4,859 for EF 3.1 on the build of 1 September 2026, 3,093 of them in
the unconfined aquifer. `tools/count_context_blanks.py` prints the same census
per pair of contexts with what each publisher did; `data/context-carry-rules.json`
says which of those pairs carry. The same page counts the blanks beside a
substance — an ion with no factor where its element has one in the same
compartment, 634 pairs over 25 ions for Stepwise 2006 on the build of 2
September 2026 before the ions were signed, 24 after — which no convention
fills: those are the adoptions file's.

## Where the decisions are

Every curated answer is a file under `data/`, registered in
`domain/rulings.py` with a sentence saying what it decides, and every entry
carries a mandatory comment. None of them is a value in a database. The files a
factor can point to:

- `lcia-factor-rulings.json` — a choice between stated numbers, pinned to them
- `lcia-factor-adoptions.json` — a substance taking another's number, adopted or declined
- `lcia-factor-adoptions-stepwise-2006.json` — the same for Stepwise 2006, where the recipient is stated by nobody and takes the donor's published number
- `lcia-misattributed-factors.json` — a number moved to the flow it is about
- `lcia-rounded-printings.json` — a precise printing preferred
- `context-carry-rules.json` — the convention for the blanks, and the walls
- `lcia-underlying-model-factors.json` — what USEtox says
- `lcia-substance-decisions.json` — which flow of ours a GreenDelta row is about

And `plans/lcia-consensus-decisions.md` is where the shape of all of it is
argued, with the measurements it rests on.
