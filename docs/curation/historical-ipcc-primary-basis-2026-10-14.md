# Primary basis of the historical BAFU IPCC additions

For the historical generic `Methane` addition, the literal `29.8` agrees with
the AR6 fossil-methane GWP100 entry. That agreement cannot establish the carbon
origin of a BAFU flow or show that the historical script ran. The nine additions
need separate records for their original assertion, published basis, application
policy and native quantity binding.

This 14 October 2026 review reads the retained source text and primary provider
references. It supplies corroboration and identifies gaps. It approves no
factor, restores no flow identifier, changes no method and establishes no
historical execution, reviewer signoff or consumer adoption.

## The original assertions

The private retained `historical-ipcc-additions.py` has SHA-256
`9ea30ff7d690bdccff94a7bc8c6bb462733a6ab9e237be5a023e971a6bb4a7c1`.
Lines 14-16 select `IPCC 2021 / climate change / GWP100 - BAFU`, project
`bafu_fresh` and database `bafu_biosphere`. Lines 21-29 contain the assertions
below, in that order. The retained snapshot revision is
`4bec1691c938db6ec61a8c7e667e10c5307827c7`; this identifies a snapshot,
not the introduction or execution of its code.

The source searches by exact name, prefers only the broad compartment, then
falls back to the first name match (lines 33-44). A hint-code mismatch produces
a note and still uses the found flow (lines 86-93). There is no native-unit
check or quantity conversion before appending the literal. These are source
facts, without a claim about which records an execution selected.

| Source line and assertion | Published corroboration | What remains unresolved |
|---|---|---|
| 21: CO2 to soil or biomass stock, `-1.0`, preferred soil | ecoinvent v3.10 Table 7, printed p.28, implements `-1` for this stock-uptake flow. Section 6.4.1, p.19, states its long-term retention assumption. [Implementation report](https://support.ecoinvent.org/hubfs/Knowledge%20Base/Database/Releases/LCIA%20implementation%203.10%20%281%29.pdf). | A stock-accounting policy, rather than a direct AR6 soil-emission metric. Recover actual flow direction, native kg CO2 versus kg C, inventory sign, retention boundary and reversals. A negative CF on an already negative inventory quantity can reverse the intended credit. |
| 22: generic Methane, `29.8`, preferred air | AR6 Table 7.15, p.1017, gives fossil CH4 GWP100 `29.8 ± 11` and non-fossil `27.0 ± 11`. [Chapter 7](https://www.ipcc.ch/report/ar6/wg1/downloads/report/IPCC_AR6_WGI_Chapter07.pdf). | Generic origin is unknown. Recover the selected flow and the biogenic-carbon policy. Do not silently declare it fossil; corrected implementations including biogenic CO2 can also assign non-fossil methane 29.8. |
| 23: fossil CO, `4.0624`, preferred air | ecoinvent v3.10 Table 10, p.32, explicitly gives `4.0624 = 2.491 + 1.5714`, with AR5 Table 8.A.4 plus oxidation as its basis. [Implementation report](https://support.ecoinvent.org/hubfs/Knowledge%20Base/Database/Releases/LCIA%20implementation%203.10%20%281%29.pdf). | This is an implemented AR5 SLCF extension. Recover its selected provider/version, regional choice, oxidation policy and native kg CO basis. Check whether oxidation CO2 is already counted elsewhere. |
| 24: biogenic CO, `2.491`, preferred air | The same Table 10 gives non-fossil CO `2.491`, without the fossil oxidation addition. | Equating this local name with the provider's non-fossil flow needs evidence. Including biogenic CO2 changes the corrected SLCF implementation to `4.0624`; see the variant table below. |
| 25: generic CO, `4.0624`, preferred air | Numerically identical to the published fossil-CO implementation above. | A numerical match cannot settle the generic flow's carbon origin. Recover the explicit unknown-origin treatment; no fossil default is approved here. |
| 26: HCFC-31, `79.4`, preferred air | Final AR6 Table 7.SM.7, printed p.16, identifies HCFC-31 as CH2ClF and prints `79.4` in **GWP-100**. [Final supplement](https://www.ipcc.ch/report/ar6/wg1/downloads/report/IPCC_AR6_WGI_Chapter07_SM.pdf). | Recover substance identity, exact source version and native mass/air binding. The source hint is not an enforced identity constraint. |
| 27: perfluoropentane, `9220`, preferred air | Final AR6 Table 7.SM.7, printed p.21, identifies **PFC-41-12, n-C5F12** and prints `9220` in **GWP-100**. [Final supplement](https://www.ipcc.ch/report/ar6/wg1/downloads/report/IPCC_AR6_WGI_Chapter07_SM.pdf). | Qualify the actual flow as normal perfluoropentane; a broad name does not settle isomer identity, unit or context. |
| 28: unspecified-origin VOC, `3.9762`, preferred air | No exact derivation was recovered. AR5 Table 8.A.5, p.740, gives a global GWP100 `4.5` **per kg C**, with a stated `0.94` reference-CO2 adjustment. [AR5 Chapter 8](https://www.ipcc.ch/pdf/assessment-report/ar5/wg1/WG1AR5_Chapter08_FINAL.pdf). | Recover the exact implementation and calculation. Establish VOC versus NMVOC membership, carbon fraction, methane inclusion, origin, region and native quantity. Applying a kg-C metric to kg mixture requires evidenced conversion. |
| 29: nitrogen monoxide, `-10.8`, preferred air | No exact derivation was recovered. AR5 Table 8.A.3, p.739, gives surface-source **NOx per kg N**, several regional estimates and a global GWP100 `-11`; its caption allows `0.94` reference-CO2 scaling. [AR5 Chapter 8](https://www.ipcc.ch/pdf/assessment-report/ar5/wg1/WG1AR5_Chapter08_FINAL.pdf). | Establish NO versus grouped NOx, kg NO versus kg N or NO2-equivalent, region, release context and complete SLCF boundary. The historical literal is not validated by the sign or approximate magnitude of a table entry. |

## Keep method variants explicit

ecoinvent's [IPCC guidance](https://support.ecoinvent.org/guidance-on-ipcc-methods)
distinguishes the main method from its complementary method including biogenic
CO2. SLCF categories retain IPCC 2013 factors because AR6 supplies no replacement
metrics for CO, nitric oxide and VOC. Its v3.11 implementation report, pp.28-30,
separates the categories by these policies. The historical `GWP100 - BAFU`
label alone does not tell us which combination was intended.

The provider's [v3.11 known-issues correction](https://support.ecoinvent.org/ecoinvent-version-3.11)
shows why that choice matters:

| Corrected IPCC 2021 GWP100 variant | Non-fossil CO | Non-fossil methane |
|---|---:|---:|
| Exclude biogenic CO2; exclude SLCFs | No factor shown | 27 |
| Include biogenic CO2; exclude SLCFs | No factor shown | 29.8 |
| Exclude biogenic CO2; include SLCFs | 2.491 | 27 |
| Include biogenic CO2; include SLCFs | 4.0624 | 29.8 |

“No factor shown” retains the provider's blank entry; it is not a measured zero.
These are corrected provider implementations, not evidence of the variant
installed in `bafu_fresh`. The current errata also distinguish these corrections
from the previously published implementation. Preserve that version difference
when receiving historical results.

AR6's supplementary methane entry `27.9` excludes carbon budgeting according
to footnote 1 on p.16; it is not a substitute for the origin-specific main-table
entries. Chapter 7, Section 7.6.1.3, p.1014, warns that methane oxidation CO2 may
already be in an inventory. The chapter also explains that reactive-species
effects vary with place and season. Both main and supplementary metrics include
carbon-cycle responses; the main-table caption excludes stratospheric
ozone-depletion contributions for halogenated species. [Chapter 7](https://www.ipcc.ch/report/ar6/wg1/downloads/report/IPCC_AR6_WGI_Chapter07.pdf),
[final supplement](https://www.ipcc.ch/report/ar6/wg1/downloads/report/IPCC_AR6_WGI_Chapter07_SM.pdf).

## Evidence that each case still needs

Keep the original literal alongside this review. For each case, receive the
exact provider artifact and row, the calculation or implementation policy,
the selected native flow/version, its property/unit and context, and a
same-generation execution record. Quantity conversion needs its direction,
inputs and application count. Generic and grouped flows need explicit origin
and membership decisions. Approval needs an actual reviewer and recorded
scope; code authorship or a matching table number cannot supply it.

For VOC and NO, the missing calculation is an unresolved evidence gap. The
primary tables provide useful boundaries for investigation, not replacement
CFs. For stock uptake, an application needs its retention and sign conventions.
For CO and methane, receive carbon accounting and SLCF selection together so
the retained extension cannot silently become the core IPCC implementation.

## Retained sources and page verification

The canonical literature identity **`forster_2021`** is reused for AR6 Chapter 7,
DOI [10.1017/9781009157896.009](https://doi.org/10.1017/9781009157896.009).
Its existing library PDF has 132 pages. The transcript and `source.md` helped
locate pages; neither is the numerical authority, and their pending review
metadata was not upgraded. No central-library record was changed.

The existing canonical **`sonderegger_2022`** record retains the ecoinvent
**v3.9** implementation report, dated 2022.10.13 (Thomas Sonderegger and
Nikolia Stoikou on its title page). Its Table 7, printed p.23, corroborates
stock CO2 `-1` and fossil/non-fossil methane `29.8`/`27`. Its Table 10, p.26,
already prints fossil CO `4.0624 = 2.491 + 1.5714` and non-fossil CO `2.491`.
That is earlier provider corroboration, not evidence that this report was used
by the historical routine. This v3.9 artifact is distinct from the captured
v3.10 and v3.11 reports; agreement on these rows does not make their versions
interchangeable.

Additional official provider references are private technical-source captures,
pending any canonical-library contribution. They are not new producer records
for the historical routine. The final AR6 supplement was chosen rather than
the indexed Final Government Distribution drafts. Direct web-tool requests to
IPCC returned 403; successful direct HTTPS retrieval supplied the retained final
PDF. No source text was taken from draft search snippets.

PDF indices below are **zero-based**; printed pages are taken from the actual
page images. Table headers, captions and relevant footnotes were visually
checked, after text extraction located the pages. Original references and
rendered page captures are retained privately in
`ipcc-primary-basis-20261014`; no source PDF or factor export is added to Git.

| Reference | SHA-256 of retained bytes | Visually inspected locator |
|---|---|---|
| Canonical AR6 Chapter 7 PDF | `470d2662fdd212421617a32c684e8106a4221a7235bdfff40a278eff02febfa9` | Index 91 / p.1014, Section 7.6.1.3; index 94 / p.1017, Table 7.15 and Box 7.3 |
| Canonical ecoinvent v3.9 implementation, dated 2022.10.13 | `64450f7e3f5549b5feda225e4d7de7a60a49217dab42e91f6cc6a88d3369c84b` | Index 22 / p.23, Table 7; index 25 / p.26, Section 7.4.6.2 and Table 10 |
| Final AR6 Chapter 7 supplement | `4290518ef9418a4157ddb9481e589131eeb110614c3aa7b62641d3241d39ce58` | Index 15 / p.16, Table 7.SM.7 header, HCFC-31 and methane footnote; index 20 / p.21, continuing header and PFC-41-12 |
| Final AR5 Chapter 8 | `9709d70802b4a78fe372f6a949d4d2af7bf31c38c1f666783d5b188702dc2836` | Index 80 / p.739, Table 8.A.3 including kg-N basis and notes; index 81 / p.740, Tables 8.A.4-5 including kg-C basis and notes |
| ecoinvent v3.10 implementation, dated 2023.11.28 | `d956b314051c6a9e2944dd35f8e9c9b76f2402b8d0b5aeb3b90c282911bbb59a` | Index 18 / p.19, stock-retention policy; index 27 / p.28, Table 7; index 31 / p.32, Table 10 and limitations |
| ecoinvent v3.11 implementation, dated 2024.11.19 | `6c7e0ff88921fbb81f29c22ac055c17956fecdc98936bbb9033effca19103542` | Text inspected pp.27-30 for named variants; numerical correction taken from the live errata below |
| ecoinvent v3.11 page, captured 14 October 2026 | `45d38b26e9d29f397802174e764642f2a8049a7600e3b321b8c6b96a7b9b3958` | Known Issues / LCIA Issues / non-fossil methane and CO; full variant-table column labels inspected |
| ecoinvent IPCC guidance, captured 14 October 2026 | `a6cebe2ab158f6119263e70d840498fc749a40e30358dcb0d3b9abc4e2b0bdef` | Available Impact Categories; biogenic-carbon guidance |

The implementation reports are first-party descriptions of ecoinvent's
choices. They corroborate those implementations; they do not establish BAFU's
method policy or the historical script's source ancestry. This review remains
source evidence until those distinct receiving records exist.
