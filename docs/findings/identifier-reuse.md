# The identifier stayed and the substance changed

*Part of [What we have found](index.md), the class where a flow keeps its identifier and its name from one release to the next, and means a different substance.*

## Pentavalent vanadium: thirteen identifiers, two substances, one release apart

ecoinvent 3.12 ships thirteen `Vanadium V` flows, all registered
**22537-31-1** — [ChEBI:33003, vanadium(5+)](https://www.ebi.ac.uk/chebi/searchId.do?chebiId=CHEBI:33003).
Those same thirteen identifiers, in ecoinvent 3.7 and 3.8, are:

| the same thirteen uuids | in ecoinvent 3.7 and 3.8 | in ecoinvent 3.12 |
|---|---|---|
| eight air and soil flows | `Vanadium`, [7440-62-2](https://commonchemistry.cas.org/detail?cas_rn=7440-62-2), the **element** | `Vanadium V`, 22537-31-1 |
| five water flows | `Vanadium, ion`, [22541-77-1](https://commonchemistry.cas.org/detail?cas_rn=22541-77-1), the **trivalent** ion | `Vanadium V`, 22537-31-1 |

Three different substances share those identifiers across releases, and nothing in
a uuid says so.

**What it does to a mapping.** GLAD's file maps every one of the thirteen
correctly for the release it was written against — rows 5193 to 5201 send the
eight elemental flows to EF's `vanadium`, rows 5204 to 5208 send the five ion
flows to EF's `Vanadium, ion`, thirteen registry-number matches with nothing wrong
in any of them. Read against ecoinvent 3.12, the same thirteen rows send
pentavalent vanadium to the element in air and soil and to the trivalent ion in
water: **one substance published as two, decided by the compartment it was
released to, and neither of them what the source row states.**

**EF 3.1 has the right target and no table uses it.** `vanadium (v)` exists in EF
in all thirteen compartments; it was unreachable while EF gave those flows the
divalent ion's registry number, which is
[a finding of its own](names-and-numbers.md#when-the-name-is-the-half-that-is-right).

**The decision.** Thirteen rewrites onto `vanadium (v)`, each keeping the target
*compartment* the table chose and moving only the substance — and each conditional
on the flow still being named `Vanadium V`, because applying them to 3.8 by
identifier alone would move eight elemental and five trivalent rows onto a
substance neither of them is. Measured on the build of 18 August 2026, it did
exactly that until the guard was added
([#109](https://github.com/brightway-labs/brightway-flows/issues/109)).

## What an identifier promises

A flow identifier is a promise: this row is the same row it was last release.
Both of the lists here have broken it — kept a uuid, kept the name, and changed the
substance underneath — and when that happens every correspondence table built
against the old release keeps working, silently, on the wrong chemical.

This is the class that makes stale mappings dangerous rather than merely
out-of-date, and all three instances on this page were found by reading a mapping
that was *correct when it was written*.

## The same shape, twice more

**EF 3.0 → EF 3.1, five trichloroethane flows.** The five air flows named
`1,1,1-trichloroethane` carry **71-55-6** in EF 3.0 and **79-00-5** in EF 3.1,
under unchanged identifiers and an unchanged name — the isomer swap
[the trichloroethane case](names-and-numbers.md#an-ozone-depleting-solvent-published-as-a-carcinogen)
is about, seen as a renumbering. GLAD's rows 1756 to 1760 matched them on the
registry number, correctly, and were made wrong by a later edit to the target
list.

**ecoinvent 3.8 → 3.12, one flupyrsulfuron flow.** uuid
`0c77f5af-0a0b-4205-acb6-0b031c22029f` is named `Flupyrsulfuron-methyl` in every
release. In 3.7 and 3.8 it carries **144740-54-5**, the sodium salt; in 3.12 it
carries **144740-53-4**, the parent acid — and a *new* flow,
`Flupyrsulfuron-methyl sodium`, takes over the salt's number. The substance behind
the identifier was replaced by its own chemical relative. GLAD's row 2051 maps it
to EF's flow for the salt, which was a true registry-number match in 3.7 and is
wrong for 3.12.

**Why this class matters more than its size.** Every one of these mappings was
right when it was made, by the strongest evidence a mapper has — the registry
number. Nothing in the table went stale in a way a reader could see, because the
table still refers to identifiers that still exist. **A correspondence table
cannot be trusted to a release it was not written against**, and this is why every
curated correction in this project that keys on an ecoinvent identifier states the
release it was checked against, and why several are conditional on the flow still
being named what it was named when the decision was made.
