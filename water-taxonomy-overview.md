# Water in the Brightway flows list

*How the different kinds of water are now organised, which ones appear as elementary flows, and where EF 3.1 characterisation factors attach. Counts come from the list as built on 12 August 2026 (EF 3.1 flows, with ecoinvent 3.8–3.12 mapped onto them). One flow is still to come and is flagged where it matters.*

---

## 1. Why this was needed

Every LCI database ships a long list of water flows: *lake water*, *water, well, in ground*, *water to cooling*, *water, salt, sole*, *water vapour*, and so on. Chemically they are all the same thing — H₂O, CAS 7732-18-5. The difference between them lives only in the flow name.

The consensus list matches flows across databases by comparing what it knows about each one: the substance, the compartment, and the unit. It does not compare names, because names differ between databases and mean different things in each. So for water it had almost nothing to compare, and two problems followed.

**All water looked like one substance.** Lake water, river water, sea water and cooling water shared a single substance entry. That entry could only carry one name, and which name it got depended on which flows happened to be in the build — *Ground Water* in one, *Water From Cooling* in another. A correct mapping could look wrong simply because of the label it inherited.

**Water use results could come out badly wrong.** EF 3.1's *Water use* method works as a pair: a positive factor when water is withdrawn, a negative factor when it is returned. If the withdrawal and the return look identical to the list, one of them gets merged away and the negative half disappears. That happened, and in the case audited it inflated a water use result by roughly a factor of 434.

The fix is to record the distinction properly, so that cooling water and turbine water are simply different substances instead of the same substance with different names.

---

## 2. Four things a water flow now says

| What it says | Example | Was it there before? |
|---|---|---|
| **Which molecule** it is | H₂O, CAS 7732-18-5 | Yes |
| **Which direction** it crossed the boundary | withdrawal (resource) or return (emission) | Yes |
| **Which water body** it came from, or went to | lake, river, ocean, aquifer | Only for emissions |
| **What kind of water** it is | sea water, groundwater, cooling water, brine, waste water | **New** |

The last one is the new piece, and it is called the **material**. It answers a different question from the water body, and the two are not interchangeable:

| Flow | Kind of water | Water body |
|---|---|---|
| Water **taken from** a lake | lake water | Lake |
| Water **discharged to** a lake | water | Lake |

For withdrawals the two usually agree. For discharges they do not. And several databases give you only one of the two: ecoinvent's *Water, lake* sits in the generic compartment "natural resource / in water", with no water body recorded anywhere — the flow name is the only place the lake appears. Recording the kind of water is what keeps that information.

---

## 3. The kinds of water

There are seventeen, arranged as a small hierarchy. The names are not ours: each one is tied to a published environmental vocabulary, so that "sea water" in this list means the same thing as "sea water" elsewhere, and can be checked by anyone.

Two vocabularies are used, for two different purposes:

- **ENVO**, the Environment Ontology, for what the water physically *is*.
- **AGROVOC**, the FAO's vocabulary, for one entry that is an accounting concept rather than a physical kind: *green water*.

```
Water                          (liquid water)
├── Fresh water
│   └── Rainwater
├── Surface water
│   ├── Lake water
│   └── River water
├── Groundwater
│   └── Fossil groundwater
├── Saline water               (grouping only — no flows of its own)
│   ├── Sea water
│   └── Brine
├── Cooling water
├── Turbine water
└── Contaminated water
    └── Waste water

Water vapour                   (separate branch: a gas, not a liquid)
Green water                    (an accounting category, not a kind of water)
```

Three points worth knowing about how this tree was built:

**Where the hierarchy is ours, it says so.** Most parent–child links here are exactly what ENVO already states. Three are not: ENVO files neither lake water nor river water under surface water, and it files bore hole water — the nearest thing it has to fossil groundwater — under liquid water rather than under groundwater. LCA needs those containments, so the list asserts them and marks each as its own, so nobody mistakes them for something ENVO says. Every other link is checked automatically against a stored copy of what the vocabularies actually publish.

**And where a name is close but not equal, it says that too.** Sixteen of the seventeen concepts claim to *be* the class they cite. Fossil groundwater does not: ENVO's *bore hole water* describes how the water was reached rather than that it is fossil, so the two overlap without being the same thing, and the link is recorded as a close match rather than an equivalence. It is the only one in the scheme.

**Water vapour is its own branch.** ENVO treats it as a gas rather than a form of liquid water, and it has its own definition and its own name, so it gets its own entry. The unit does not tell the two apart: water vapour itself is filed in both kg and m³ (see §4).

**Green water is deliberately not filed under rainwater.** Physically it is rain that infiltrated the soil, so putting it there would be defensible. But green water exists as a separate flow for water-footprint accounting reasons, not physical ones, and treating it as a kind of rain would blur that. It sits outside the tree with a note saying why.

Two smaller decisions, recorded so they do not get re-litigated:

- **`Water, salt, sole` is brine.** EF 3.1 gives it water's CAS number; that is treated as an error and dropped, because brine is a mixture rather than pure water. It is the only water entry with no CAS number.
- **Turbine water has no published class anywhere**, in ENVO or elsewhere. It gets an identifier of our own, flagged as ours, and a request has been filed with ENVO.

---

## 4. What actually appears in the list

The list has two levels, and it helps to keep them apart:

- a **substance entry** — what the thing is: name, CAS number, formula, definitions, links to reference databases;
- an **elementary flow** — one occurrence of that substance in a particular compartment and unit. These are the rows an inventory or an impact method refers to.

**Sixteen of the seventeen kinds of water become substance entries.** *Saline water* is the exception: it exists only so that sea water and brine have a sensible parent, and no database flow lands on it directly.

Each of those entries now carries the environmental vocabulary class alongside the chemistry — sea water is stated to be both "a neutral molecule, CAS 7732-18-5" and "sea water, ENVO 00002149". Those are not competing claims: ENVO's own definition of liquid water is "an environmental material primarily composed of dihydrogen oxide", so the chemistry describes what the material is made of.

**Those entries carry 40 elementary flows, and every one of them is live.** Not a single water flow is retired any more — which is the plainest measure of whether this worked, since the whole exercise began with water flows being merged into each other.

| Kind of water | Live flows | Where they sit |
|---|---|---|
| Water | 6 | withdrawal (unspecified body); discharge to surface water, ocean, unspecified, long-term, and to a confined fossil aquifer |
| Fresh water | 1 | withdrawal, unspecified body |
| Lake water | 1 | withdrawal from a lake |
| River water | 1 | withdrawal from a river |
| Groundwater | 1 | withdrawal from an unconfined aquifer |
| Fossil groundwater | 0 | *withdrawal from a confined fossil aquifer — see below; it appears at the next build* |
| Sea water | 1 | withdrawal from the ocean (in kg) |
| Brine | 1 | withdrawal, unspecified body |
| Rainwater | 2 | withdrawal (kg); discharge to surface water |
| Cooling water | 3 | withdrawal (unspecified body, and from the ocean in kg); discharge to surface water |
| Turbine water | 2 | withdrawal; discharge to surface water |
| Water vapour | 19 | emissions to air (five heights, in kg and m³), to soil (3), to water (4, including long-term), plus water taken from air |
| Green water | 2 | withdrawal from air (EF 3.1); withdrawal from ground (ecoinvent) |
| Surface water, waste water, contaminated water | 0 | used by the Swiss BAFU list; no rows in this build |

**Water in the air is the untidiest corner of this.** Each of the five air compartments carries the same emission twice: EF's *water vapour* in kg and EF's *Water* in m³. Emissions to unspecified air carry a third, EF's *Water (evapotranspiration)*, also in m³. All eleven are published, none carry factors, and nothing has been combined — EF states no conversion between the halves, giving each flow a single flow property, Mass or Volume, at 1.0. The pair in unspecified air is where ecoinvent's *Water* to air lands, on the m³ side.

The last two water retirements went in this build. EF 3.1's "water, unspecified (long-term)" entries for water and for water vapour used to be merged away, because EF's long-term water compartment was mapped onto the ordinary "water, unspecified" one and the two pairs became indistinguishable. They now map to the long-term compartment and both are published in their own right.

The reason for that change was not those two flows — neither carries any factors — but ecoinvent: its *water / ground-, long-term* emission points at EF's long-term flow, and while that flow was merged away the mapping followed the redirect onto ordinary unspecified water, where the release picked up a short-term characterisation factor for a release ecoinvent defines as more than 100 years out. The principle is that **both halves of a temporal pair meet in the long-term compartment, or neither does**. The cost is around 7,150 long-term identifiers that carry no factors and are now published rather than merged; what is bought is that no flow silently inherits a factor from a different compartment.

Everything else that used to be merged away is now published in its own right.

### How flows from other databases appear here

EF 3.1 supplies the published rows. An ecoinvent flow that matches one of them does not create a row of its own: it is attached to the EF row and adopts its compartment. That is why *Water, lake*, *Water, well, in ground* and *Water, salt, ocean* do not appear as separate entries above — they are recorded on EF's lake water, groundwater and sea water rows.

It also means a distinction ecoinvent draws can end up finer than the row it lands on. **ecoinvent's fossil groundwater is the case to know about:**

| ecoinvent flow | Publishes as | Compartment it lands in |
|---|---|---|
| *Water, unspecified natural origin* — natural resource / **fossil well** | Groundwater | withdrawal from an **unconfined** aquifer |
| *Water* — water / **fossil well** | Water | discharge to unspecified water |
| *Water* — water / **ground-, long-term** | Water | discharge to unspecified water |

The compartment vocabulary does have a *Confined aquifer with fossil groundwater* value, and ecoinvent's fossil-well compartment maps to it. But ecoinvent's own correspondence table sends these three flows to EF flows that sit elsewhere, and the EF row wins. The mismatch is not silent — the merge records a context inconsistency on each of them — but at present nothing is published on the confined-aquifer compartment, and the fossil-water distinction survives only in the recorded mapping, not in the row you would characterise.

**Fixed on 12 August, and the fix is the material axis rather than an exception.** Both fossil-well flows now stop at ecoinvent's own compartments: the withdrawal in *Resource → Water → Confined aquifer with fossil groundwater*, the discharge in the environmental counterpart — where it is published in this build, as the first flow that compartment has ever held. What made that possible was recognising that **fossil groundwater is a different material, not merely groundwater in an unusual place.** EF classifies every water resource it carries as a *renewable* material resource, and fossil water is the one kind that is not renewable — so there was never a right flow for it in the target list, and no correspondence table could have named one.

So the seventeenth concept was added, ecoinvent's fossil-well withdrawal was assigned to it, and ecoinvent's correspondence rows for both flows were declined — a curated statement that the published table sends these somewhere wrong and has nowhere right to send them. The rest follows from machinery that already existed: the withdrawal names a material no substance entry covers yet, so the merge mints one and places the flow in the compartment the source states; the discharge stays plain water, finds three equally close candidates and no winner among them, and the merge adds a flow in the compartment the source states. No special case was written for water.

**The withdrawal stops inheriting EF *ground water*'s 209 *Water use* factors**, and that is intended rather than tolerated. Those factors belong to a renewable resource. Nothing ecoinvent publishes is lost either: in its own LCIA implementation the `fossil well` subcompartment carries no characterisation factor in any method. If your model needs fossil water charged, that is now a decision you make explicitly rather than one the list makes for you by filing it as an unconfined aquifer.

Both flows are declined together, not one at a time. Moving the withdrawal while leaving the discharge on unspecified water would leave a return charged where the withdrawal is not — the same shape as the defect in §1, arrived at from the other direction.

**The withdrawal is one build behind, and the reason is worth recording.** The first run after this change published the discharge and not the withdrawal, and the difference exposed a defect nothing to do with water: the merge reads a flow's material from a table keyed by the source list, but a flow it is about to create a new substance entry for has not yet been stamped with which list it came from. So the lookup asked the wrong list, found nothing, fell back to the CAS number shared by all water, and computed the ordinary water entry — which already exists, so the creation was refused and the flow published nothing at all. The discharge was unaffected because it needs no new entry. That lookup now names the list being merged, and the withdrawal appears at the next build. Any material curated for any non-base list was invisible in the same way; water is simply the only domain that has materials today.

---

## 5. Water bodies, now on withdrawals too

The compartment used to record a water body only for emissions. It now records one for withdrawals as well, meaning the body the water was taken **from**.

| Value | Withdrawals | Emissions |
|---|---|---|
| Unknown | ✅ | ✅ |
| Surface water — the general value, for when a lake or river is not specified | ✅ | ✅ |
| Lake | ✅ | ✅ |
| River | ✅ | ✅ |
| Ocean | ✅ | ✅ |
| Unconfined aquifer | ✅ | ✅ |
| Confined aquifer with fossil groundwater | ✅ | ✅ |
| Waste-water treatment plant | — | ✅ |
| Secondary water treatment | — | ✅ |
| Long-term | — | ✅ |

The last three cannot be withdrawn from. "Long-term" is not really a water body at all — it marks emissions beyond a 100-year horizon, and it sits in this field because the compartment model has nowhere else to put a time qualifier yet. It is a real, usable value: both EF's and ecoinvent's long-term water emissions belong in it, and as of 12 August both are mapped there.

*Confined aquifer with fossil groundwater* is the thinly occupied one: one water flow today, the fossil-well discharge, and a second at the next build when the withdrawal joins it. *Long-term* is at the other extreme — 7,187 flows of all kinds, since EF's long-term emissions stopped being merged onto their short-term twins.

**Why the body has to be read from the flow name.** EF 3.1 files all six of its water resources under one compartment: *Resources / Resources from water / Renewable material resources from water*. Lake water, river water, sea water and groundwater arrive indistinguishable, so the body is assigned flow by flow, with the reasoning written down for each. For example, EF's *ground water* says "aquifer" but not which kind, so it is placed in the unconfined aquifer — the general case — rather than in the fossil groundwater value, which EF does not claim.

The result: EF 3.1's eleven water withdrawals used to fall into two distinguishable groups. They now fall into six by compartment, and the rest are separated by the kind of water.

---

## 6. Where EF 3.1 characterisation factors attach

**Factors attach to elementary flows, not to substance entries.** A factor depends on where and how the water crossed the system boundary, so it belongs with the occurrence, not with the substance.

Eleven water flows carry EF 3.1's *Water use* factors (209 values each, for the indicator "user deprivation potential — deprivation-weighted water consumption"). All eleven are published as distinct, live flows:

| EF 3.1 flow | Kind of water | Compartment | Factors |
|---|---|---|---|
| water | Water | withdrawal, unspecified body | positive |
| freshwater | Fresh water | withdrawal, unspecified body | positive |
| lake water | Lake water | withdrawal from a lake | positive |
| river water | River water | withdrawal from a river | positive |
| ground water | Groundwater | withdrawal from an unconfined aquifer | positive |
| Water to Cooling | Cooling water | withdrawal, unspecified body | positive |
| Water to turbine | Turbine water | withdrawal, unspecified body | positive |
| Water | Water | discharge to surface water | negative |
| Water | Water | discharge to unspecified water | negative |
| Water from cooling | Cooling water | discharge to surface water | negative |
| Water from turbine | Turbine water | discharge to surface water | negative |

Seven withdrawals, four returns, with the full set of 209 values intact on each. **Four of these eleven used to be merged away** — which is exactly how a balanced method turned into a one-sided charge. They survive now because cooling water and turbine water are genuinely different substances in the list, rather than the same substance distinguished only by a name.

The other water flows — water vapour, sea water, brine, rainwater, green water — carry no EF 3.1 factors at all. They are published because they occur in inventories, not because a method scores them.

### Getting a factor onto your own inventory

- **If you already work in EF 3.1 flows**, nothing changes: the EF identifiers are the published identifiers.
- **If you work in another database**, each published flow lists the source flows that map onto it, with their original names, compartments, units and versions. Groundwater, for instance, gathers seven: EF's *ground water*, plus ecoinvent's *Water, well, in ground*, *Water, unspecified natural origin (in ground)* and *Water, unspecified natural origin (fossil well)*, across several versions. Applying an EF factor to an ecoinvent inventory means going through that list.
- **Where the units differ**, the mapping carries the conversion. There is exactly one in the water flows: ecoinvent's *Water, salt, ocean* in m³ maps to EF's *sea water* in kg at **1025 kg/m³**. It is verified by tests, which also check that no second water conversion can be added without someone reading the reasoning.
- **If a flow you use has been retired**, its replacement is published along with a reason. Only "identity merge" means the two were ever the same flow. "Context collapse" means two source compartments this list cannot tell apart, and their factors may legitimately differ — so check the reason before following a redirect.

---

## 7. What is deliberately left out

- **Blue, grey and green water** are accounting categories, not kinds of water. They stay as qualifiers on water rather than becoming materials. Blue and grey currently match no flow in any database we load.
- **Salinity** is treated as a property of the water, not of the compartment. That is why sea water and brine are kinds of water, and there is no "saline" compartment.
- **Evapotranspiration** is a process, not a material. EF's *Water (evapotranspiration)* is recorded as water vapour, which is what the process moves — in m³, alongside the other air flows (see §8).
- **Characterisation factors themselves.** This list carries the factors its source databases publish; it does not compute, regionalise or correct them.

---

## 8. What is not finished

| Open item | Where it stands |
|---|---|
| The **water body values are not yet tied to ENVO classes** the way the kinds of water are. Lake, river, ocean and aquifer are still plain English strings in the compartment. | Designed, not built |
| **Water in the air is doubled, and in one place tripled** — kg and m³ on each of the five air compartments, plus *Water (evapotranspiration)* in unspecified air. Two clean-ups are available: merging the two m³ flows in unspecified air needs no conversion at all and is already flagged as a collision; folding the kg and m³ halves together needs a stated density, for which 1000 kg/m³ is the usual liquid-equivalent convention for evapotranspiration volumes. | Open |
| **Turbine water uses an identifier of our own**, since no published vocabulary has the concept. That identifier has to be served publicly, and a term request with ENVO is the longer-term fix. | Pending |
| **Fossil groundwater's name is borrowed.** The concept is anchored to ENVO's *bore hole water* as a close match, because ENVO carries no class for fossil or connate water; the anchor names how the water is reached, not that it is non-renewable. A term request would replace it with an exact one. | Good enough, flagged |
| **What "fossil well" means** is also not settled. The name reads either as a well into fossil water or as a hydrocarbon well producing formation water; the confined-aquifer reading holds under both, but a clarification from ecoinvent could still change it. | Refinement only |
| **Surface water, waste water and contaminated water** only occur in the Swiss BAFU list, so they have no flows in an EF plus ecoinvent build. Merging BAFU gives them their first: on the 2026-08-15 build the three concepts hold five flows between them — three waste water, one surface water in `Resource → Water → Surface water`, one contaminated water — created from the BAFU rows the three were added for. | Closed by #86 for a build that merges BAFU |

---

## 9. In short

Water now records **what kind of water it is**, as well as its chemistry, its direction and its water body. Seventeen kinds, tied to published environmental vocabularies, with any hierarchy we added ourselves marked as ours. Sixteen of them become substance entries, and those entries carry 40 published water flows, none of them retired — 41 once the fossil groundwater withdrawal arrives. Withdrawals now record the water body they came from, read flow by flow because EF 3.1 files all of them under one compartment. And EF 3.1's *Water use* factors — seven positive withdrawals, four negative returns — now sit on eleven distinct published flows, which is what keeps a balanced method balanced.
