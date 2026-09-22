# What do we do when two implementations disagree?

*Part of [How a factor is decided](index.md). Two deciding implementations
state a number for the same flow, category and place — this page is what
happens when the numbers are not the same.*

Vanadium to air, ionising radiation aside, is as plain a metal as EF 3.1
characterises. The JRC states 1.3384 × 10⁻⁶ CTUh/kg for non-cancer human
toxicity from unspecified air; the ecoinvent Centre states 1.3384 × 10⁻⁵. The
mantissa is preserved to five significant figures and the decimal point has
moved — in five compartments and both halves of the category, always by exactly
ten
([#49](https://github.com/brightway-labs/brightway-flows/issues/49)).
Nobody disagrees about vanadium. Somebody slipped a unit.

Figures are from the build of 1 September 2026, run `20260901T0451332605450000`.

## Two percent is agreement; more is a question

Where every deciding implementation's number is within 2 % of the others', the
implementations are saying one thing and the most precise printing is published
as `agreed`, with the other recorded on the factor as `also_stated`. `0.000118`
and `0.00011755` are one number written twice, and this keeps the second — the
same judgement the merge makes about two rows that turn out to be one flow. Two
percent is the line the whole project draws between a rounding and a
disagreement, and it is not crossed over a zero or a sign change: a stated zero
against a number is not a rounding of anything, it is two teams disagreeing
about whether something has an effect.

Where they are further apart, the consensus implementation publishes
**nothing** and the row goes to the `contested-factor` queue. Taking the
method's own publisher by default would publish numbers nobody had looked at
under a label saying a decision was made; the queue publishes a question
instead. On this build that is 38 questions over 152 factors, 32 of them still
open.

Grouped by substance and category rather than by flow, because that is the unit
a person decides in: kresoxim-methyl's freshwater ecotoxicity is one question
asked about two compartments, not two questions. The queue row carries every
implementation's number, the ratio, whether the same disagreement holds in every
context — which is what makes a broad ruling possible — and where the flow came
from.

## What the disagreements turn out to be

Almost never toxicology. The ones ruled so far are all the same kind of finding:

- **kresoxim-methyl**, 397× — EF's own file carries the substance twice, under
  one name, one CAS number and two EC numbers, with different factors on the two
  rows. This build kept one row's number and the ecoinvent Centre kept the
  other's, in every compartment and never a third number. Ruled to the JRC's
  134.73, because that is the row ecoinvent's own flow corresponds to
  ([#64](https://github.com/brightway-labs/brightway-flows/issues/64)).
- **vanadium**, 10.0000× — the unit slip above. Ruled to the JRC's.
- **sulphuryl difluoride**, climate change — ecoinvent states a global warming
  potential of 4,630 kg CO₂‑eq where the JRC states none; ruled to publish, with
  IPCC AR6 cited on the ruling
  ([#151](https://github.com/brightway-labs/brightway-flows/issues/151)).

And two still open that are real, in the sense that the numbers describe
different things. **Fenpropimorph** in soil differs by 47× between the two
implementations, because EF lists the fungicide twice under two registry numbers
and the two teams characterised different copies; **fenoxycarb** differs by
740–800× in 22 compartments for the same reason
([#130](https://github.com/brightway-labs/brightway-flows/issues/130)).
Both are identity questions wearing a factor question's clothes, and the answer
to each begins in the merge rather than in this queue.

## What a ruling is

An entry in `data/lcia-factor-rulings.json`, keyed on the queue, the substance
and the category, with a **mandatory comment** — every ruling is a statement
about somebody else's science, and one with no reasoning is unreviewable.

**Two verdicts, and neither names a source list.** `publish` names the
implementation whose number this list takes; `decline` takes nobody's. The
first design had a verdict per publisher, which reads well with exactly two and
cannot express a third; `publish` with an `implemented_by` says the same thing
about any number of them. It also makes one verdict sayable that the old shape
could not: `decline` on a contested question is "neither of them, deliberately".

**A ruling is pinned to the numbers it was written about.** `ruled_about`
records what every implementation stated at the time, and if either revises —
or a third implementation appears — the ruling stops applying and the row asks
again. A ruling that the staleness check could never fail would be the same as
having no check. Fourteen rulings settle 52 factors on this build, and none has
gone stale.

A factor a ruling publishes carries `derivation: ruled`, distinguishable from
`agreed` (the pipeline found nothing to decide) and from `sole` (nobody else
spoke). The queue row stays on its page marked *ruled*, with the verdict and the
comment: an answered question is a record, not a deletion.

## Where it is written down

- `lcia_characterization_factors.derivation` — `agreed` with `also_stated`, or
  `ruled`.
- `/queue/contested-factor` — the open questions, worst ratio first, and the
  ruled ones after them.
- `data/lcia-factor-rulings.json` — the answers, with `ruled_about` and the
  comment.
- `/factors/differences` — every disagreement, ruled or not, banded by ratio.
