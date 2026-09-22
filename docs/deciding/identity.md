# What do we do when the name and the CAS number don't agree?

*Part of [How a flow is decided](index.md), at the stage where a row's own name and its own registry number are asked whether they say the same thing.*

Identifiers are ranked, and the ranking is not negotiable: **a registry number
outranks a name.** A CAS number designates one substance by construction. A name
designates whatever the person writing it meant, and common names are routinely
generic where the substance is specific.

This is easy to state and was easy to get wrong, because the mistake does not
look like trusting a name — it looks like trusting Common Chemistry, which is
the most authoritative CAS source there is.

## How a source list uses the two together

EF 3.1 pairs a readable common name with the registry number that says which
substance is actually meant:

| EF 3.1 name | EF 3.1 CAS | What that number designates |
|---|---|---|
| `butanol` | `71-36-3` | 1-Butanol |
| `ascorbic acid` | `50-81-7` | L-ascorbic acid |
| `carbon` | `7782-42-5` | Graphite |
| `iron oxide` | `1345-25-1` | Ferrous oxide |
| `pyrethrin` | `8003-34-7` | Pyrethrins |

None of these is an error. The name is the label a practitioner reads; the CAS
is the identity. Carrying a generic name beside a specific number is exactly how
a flow list stays readable without becoming ambiguous.

## The failure

`commonchem_cas_review` looked up the flow's name in Common Chemistry and, on an
exact match, replaced the flow's CAS with the one Common Chemistry returned. For
the flows above, looking up the *generic* name returns Common Chemistry's
*generic* registry entry:

| Flow | Name lookup returned | Effect |
|---|---|---|
| `butanol` | `35296-72-1` — unspecified butanol | `71-36-3` discarded |
| `ascorbic acid` | `62624-30-0` | `50-81-7` discarded |
| `carbon` | `7440-44-0` — carbon | `7782-42-5` discarded |
| `pyrethrin` | `88108-26-3` — Pyrethrin | `8003-34-7` discarded |

Every one of those trades a specific number for a vaguer one, and discards the
only field that said which substance was meant. In the August 2026 build this
happened to 52 flow objects across 51 distinct registry numbers, and 51 of the
51 numbers discarded were valid registered CAS numbers that Common Chemistry
itself knows.

The claim being made was never checked against the claim being used. "Common
Chemistry says the name *butanol* maps to `35296-72-1`" is true. "A flow named
*butanol* carrying `71-36-3` is wrong about `71-36-3`" does not follow from it.

The cost showed up downstream. EF's pyrethrins flow lost `8003-34-7`, which is
the number ecoinvent's six `Pyrethrins` rows ship — so those rows could no
longer reach the substance they belong to by any identifier, and had candidates
only through an EC number shared with something unrelated.

## The rule

**An exact name match fills in a CAS the flow does not have. It never replaces
one the flow does have.** Where the two disagree, the flow's number stands and
the disagreement goes to the `commonchem-name-cas` queue with `applied: false`.

This is the same rule the mirror case already followed. When Common Chemistry
knows a flow's *CAS* and calls it something else, nothing is changed and a
report is filed — because "a name is not evidence of identity the way a CAS is".
That is the same disagreement approached from the other side, and it cannot have
two answers depending on which lookup happened to find it.

## What this gives up

The old behaviour caught two genuine errors, both in the same build:

| Flow | CAS it carried | What that number actually is |
|---|---|---|
| `1,1,1-trichloroethane` | `79-00-5` | 1,1,2-Trichloroethane — the wrong isomer |
| `1,3,5-triazine` | `121-82-4` | RDX — an unrelated explosive |

These are real findings and they are still reported; they are no longer applied
automatically. That is the right trade. A rule that corrects two flows and
damages forty-nine is not a correction rule, and neither error is safe to fix
without someone looking — the flow may be mislabelled rather than mis-numbered,
and only a curator can say which.

Implemented in `transformers/commonchem_cas_review.py`; see
[the review app](../operating/review-app.md) for the queue.

## When a label follows the number, and when it does not

Everything above ranks identifiers for deciding **identity**. The published
label is a different question, and it has the opposite default: the label
follows the source's readable name, not the number's registry designation.
`butanol` is published as `Butanol` while 71-36-3 says 1-butanol; `carbon`
stays `Carbon` beside a separate `Graphite`. Renaming either to what its
number designates would gain a precision no reader asked for and lose the name
every inventory actually uses — carrying a generic name beside a specific
number is how the base list stays readable, not a defect to repair.

One class of names is held to a different standard, because this project wrote
them: the generic-ion fallback. `flow_layers.ions` names an ion from its
label, and where the label states no numeral the name comes out `X, ion` — the
list's way of saying the charge is unstated
([#128](https://github.com/brightway-labs/brightway-flows/issues/128)).
When the charge later arrives on the object's own evidence, the fallback has
stopped being literally true, and may be corrected to `X(n+)` — but only where
the correction **disambiguates**:

- **the element has exactly one ionic form** — `Sodium(1+)` and `Lithium(1+)`:
  the generic and the charged name can only denote one substance, so the
  rename is a spelling improvement rather than an assertion; or
- **the generic name sits beside a published charged sibling** a reader could
  confuse it with — `Tin, ion` was published beside `Tin(2+)`, two different
  substances whose names did not say so
  ([#127](https://github.com/brightway-labs/brightway-flows/issues/127)),
  and became `Tin(4+)`.

Where neither holds, the generic name stands even though the object states its
charge. `Titanium, ion` is the worked example
([#143](https://github.com/brightway-labs/brightway-flows/issues/143)):
EF ships the name with 22541-75-9, the payload the number brought in says
`Ti+4`, and the identity is not in doubt — but the list publishes no other
titanium ion to confuse it with, the name is the one EF and ecoinvent both
write, and ecoinvent's twenty-six charge-withheld `Titanium ion` rows reach
the object by exactly this label. The rename would assert a specificity no
reader needs and unseat the label those rows land by, so the ruling in
`preferred-label-decisions.json` records a rejection, with the reasoning on
the row.

Whichever way a case falls, the gate is the same: a published label only ever
changes through a ruling in `preferred-label-decisions.json`, and a proposal
nobody has ruled on queues for a curator instead of applying
([#16](https://github.com/brightway-labs/brightway-flows/issues/16)).
