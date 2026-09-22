# A nuclide is named, or numbered, as something else

*Part of [What we have found](index.md), the class where the nuclide a flow names is not the nuclide its factors were computed for — or is not a nuclide at all.*

## Palladium-234m does not exist

EF 3.1 ships twelve flows named `Palladium-234m`, all in becquerels, in
radiological release compartments — ground-level air, aircraft cruise height, high
stack, ocean, surface water, agricultural ground.

Palladium is element 46 and its heaviest known isotope is around mass 128. **There
is no Pd-234, so there is no Pd-234m.** The flow is protactinium-234m — Pa-234m,
the short-lived isomer in the uranium-238 decay chain, and one of the nuclides an
inventory of nuclear power is most likely to report. The element symbol `Pa` was
expanded to the wrong element's name.

EF half-knows. The general comment on all twelve rows reads:

> CAS No and Synonyms removed; were erroneous. Correct CAS to be identified.
> Possibly has none assigned.

The identifiers were withdrawn *because they did not match the name*. The name
that made them not match was left in place, and the flow arrives carrying no
registry number at all — so nothing but the name says what it is, and the name is
the thing that is wrong.

## Where the identifiers are weakest

The name was left to do the identifying because nothing else could.

A radionuclide flow is measured in becquerels, and what it is depends on two
things a chemical flow does not have: which nuclide, and which nuclear state.
Neither is expressible as a registry number in practice, so nuclide rows are
where the lists' identifiers are weakest — and where a name is doing work no
number is checking.

## The same shape, four more times

| what the list says | what it is | flows |
|---|---|---|
| `Silver-110` in **every** list | Ag-110m, the 249.9-day isomer; Ag-110 is a 24.6-second ground state no inventory reports | EF 12, ecoinvent 9–10, BAFU 4 |
| `Uranium-238` carrying **7440-61-1** | that number is *uranium the element*; U-238's own is 24678-82-8 | EF 12, ecoinvent 9–10, BAFU 15 |
| `Praseodym-147` | a truncated element name; the flow also carries elemental praseodymium's number | EF 12 |
| `Thorium-232` carrying **7440-29-1** | the element's number again | EF 12, ecoinvent 9–10, BAFU 11 |

The silver case is worth following, because the name is wrong in every list at
once — a shared vendor convention, not one list's slip, so it cannot be settled by
preferring the other list. Half-life alone does not settle it either: 49 of the 81
matched nuclides in this list have a half-life under a year and most are
legitimate. What settles it is that **EF states which nuclide it means a second
time, in its own characterisation factor.** The four water rows carry
`Ionising radiation, human health` at 0.0236 kBq U235-eq per kBq. Of the
twenty-one nuclides carrying a water factor under that method, not one is
short-lived: the band runs from Iodine-129 down to Strontium-90, and this value
sits between Antimony-124 (60.2 days) and Manganese-54 (312 days). An exposure
efficiency of that size needs a nuclide that survives long enough to be ingested.
A 24.6-second beta emitter discharged to the ocean does not. **The factor was
computed for the isomer**
([#24](https://github.com/brightway-labs/brightway-flows/issues/24)).

**The decisions.** `Palladium-234m` is renamed, and the corrected label is what
lets the nuclide be recognised at all — typed as an isotope and a radionuclide,
where before it was untyped for having neither structure nor registry identifier.
`Silver-110` is renamed to `Silver-110m` **and keeps `Silver-110` as an
alternative label**, which is the opposite of the trichloroethane and paraquat
decisions and deliberately so: it is not another substance's name, it is the name
both vendor lists ship, and deleting it would remove the only string a consumer
holding one of those inventories could search for. `Uranium-238` gets its own
registry number on every list that carries it.

**What is still wrong.** `Thorium-232` and `Praseodym-147` keep the element's
registry number, because no cited nuclide-specific number exists for them and
inventing one would be worse than publishing the vendor's. A consumer joining on
CAS will re-merge those nuclides with their elements — which is exactly what the
identifiers say, and exactly what the nuclide identity in this list says they are
not
([#17](https://github.com/brightway-labs/brightway-flows/issues/17),
[#26](https://github.com/brightway-labs/brightway-flows/issues/26)).
