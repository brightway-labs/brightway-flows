# The name is a part number, and the part number is not an identifier

*Part of [What we have found](index.md), the class where a flow's whole name is a trade designation — `HFC-134a`, `CFC-113` — which no registry issues and no database can resolve.*

## What the code does not tell you

**Fifty of EF 3.1's part-numbered flows shipped with no identifier at all** —
no registry number, no EC number, no formula, no structure, nothing but the
designation and a characterisation factor. `(E)-HFC-1225ye` is one: EF ships five
flows and ten factors under it, and nothing downstream could place the substance.
What resolves it is the code itself, used as evidence rather than as a name: the
digits decode to C₃HF₅, PubChem's record for CID 6329539 lists `(E)-HFC-1225ye`
among its synonyms and reports the same formula, and the two agreeing is what
justifies attaching 5595-10-8 to the flow.

**And the designations are not always right.** Two of EF's are internally
contradictory:

- `HCFC-140` — [described with the trichloroethane
  flows](names-and-numbers.md#hcfc-140-is-not-this-compound-either) — puts an
  F for fluorine in the name of a molecule that has none, and drops the isomer
  letter that separates it from the chemical it keeps being confused with.
- `HFC-1234yf` is a typo for `HFO-1234yf`. The leading digit of a four-digit
  refrigerant number is its count of double bonds, so 1234yf names an olefin,
  and the HFC family is saturated by definition: the compound cannot be an HFC.
  EF itself uses the right prefix elsewhere — its `polyhaloalkene` flow, which is
  this same substance, carries `hfo-1234yf` in its own synonym list. PubChem
  records the wrong spelling as a synonym, which makes it findable, not correct.

**The decision.** Where a registry names the number, the substance is published
under the chemistry — `HFC-134a` becomes `1,1,1,2-Tetrafluoroethane` — and the
designation is kept as an alternative label, so an inventory written against EF
3.1 still finds it. That is done for 70 of the 118. The remaining 48 keep the part
number, and the reasons are written down rather than left as an oversight: for 26
there is no chemical name to be had, and for the other 22 the available name is
worse than the code — it names a mixture as one isomer, or it is itself another
part number, or four isomeric ethers share one registry number and renaming them
would publish four substances under one name
([#104](https://github.com/brightway-labs/brightway-flows/issues/104),
[#19](https://github.com/brightway-labs/brightway-flows/issues/19); the full
accounting is in [Known limitations](../reference/limitations.md)).

## A designation is not an identifier

Reading a code as evidence works because the codes are systematic. Using one as
a name does not.

Refrigerants, blowing agents and fire suppressants are traded by designation:
`HFC-134a`, `CFC-113`, `Halon-1211`. The designations are systematic — the digits
encode the counts of carbon, hydrogen and fluorine, the trailing letters the
isomer — but they are issued by no registry, they are not unique across the
families that use them, and a database cannot resolve one. When a flow list uses a
designation *instead of* a chemical name, the substance has no name anything can
look up.

EF 3.1 names **118 substances** this way. Only EF does: measured over the
extracted inputs, 714 EF flows have a designation as their entire name, and in
ecoinvent and BAFU that number is **zero** — those lists append the designation to
a chemical name instead (`Ethane, 1,1,2-trichloro-1,2,2-trifluoro-, CFC-113`),
which loses nothing.

## When the designation is the only half that identifies

Appending the designation to a chemical name loses nothing *if the reader knows
to read the tail*. Sometimes the tail is all there is.

ecoinvent 2 named a family of fluorinated ethers as structural prose with the
designation on the end, and gave every member of a family **one registry
number**. Stepwise 2006, a SimaPro method file of that era, ships those rows
verbatim — and within a family the prose and the number are identical, so the
designation is the only thing that differs:

| Stepwise 2006 ships | CAS | its `Global warming, fossil` factor |
|---|---|---:|
| `Ether, 1,1,2,2-Tetrafluoroethyl 2,2,2-trifluoroethyl-, HFE-347mcc3` | 406-78-0 | 576 |
| `Ether, 1,1,2,2-Tetrafluoroethyl 2,2,2-trifluoroethyl-, HFE-347mcf2` | 406-78-0 | 963 |
| `Ether, 1,1,2,2-Tetrafluoroethyl 2,2,2-trifluoroethyl-, HFE-347pcf2` | 406-78-0 | 963 |

**The file contradicts itself in its own numbers.** Three rows it says are one
substance — one name, one number, one formula, `C4H3F7O` — are characterised
576 and 963 kg CO₂-eq per kilogram. EF 3.1 ships the same three substances
under the same shared number and gives them GWP100 of 576, 963 and 980. What
the designation encodes is the arrangement of the ether, which is exactly what
those numbers are sensitive to: the shared registry number is not a claim that
these are one chemical, it is a family's number written on each member, and
the trailing code is the member.

Twelve rows are in this shape, across four families: 406-78-0 on three,
382-34-3 on four, 1885-48-9 on three and 84011-06-3 on two. Both halves of the
identification fail together on all twelve — the number reaches every member of
the family, and the prose reaches none of them, because it is nobody's
published name. A row that states a name *and* a registry number, both
correctly copied, identifies nothing.

**The decision.** Where a registry number has found several substances and the
whole name has matched none of them, the last comma-segment of the name is read
against those candidates' published names — and only against those, so it can
settle a family the number already reached and can never reach outside it. The
row records `cas+designation`, so a match made on that reading is
distinguishable from one made on a name the vendor shipped. Asked of Stepwise
2006's 6,064 rows it moves exactly these twelve, each to its designation's own
substance: 5,061 matched becomes 5,073
([#19](https://github.com/brightway-labs/brightway-flows/issues/19)).
EF's four shared numbers are separately a
[contested-CAS](../deciding/registry-numbers.md#the-contested-cas-rule-one-number-claimed-by-two-names)
question, and all four carry a ruling that the number cannot stand for the
whole family.

**What it cost, by source list:**

| source list | flows whose whole name is a part number | of those, with no registry number |
|---|---:|---:|
| **EF 3.1** | **714**, under 93 designations | 32 |
| **ecoinvent 3.12** | 0 | — |
| **ecoinvent 3.8** | 0 (150 flows *append* a designation to a chemical name) | — |
| **BAFU 2026 v1** | 0 (58 append one) | — |
