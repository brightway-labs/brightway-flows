# Which sources do we believe, and how far?

*Part of [How a flow is decided](index.md). Every other page in this section leans on this one: which source may settle a question on its own, and which may only corroborate.*

| Source | Used for | Trusted for identity? |
|---|---|---|
| **EF 3.1** | The base flow list: names, CAS/EC, contexts, units, LCIA methods | Yes — it is the starting point |
| **ChEBI** | Synonyms, structures, cross-references | Yes, with a formula check |
| **CAS Common Chemistry** | Authoritative CAS ↔ name, structures | Yes — highest quality for CAS, but see [A name is not an identifier](identity.md) |
| **ECHA EC inventory** | Official CAS ↔ EC correspondence | Yes, for that correspondence |
| **PubChem** | Structures, names, cross-references | **Only when confirmed elsewhere** |
| **OPSIN** | Parsing IUPAC names into structures | Yes, when the name parses unambiguously |
| **RDKit** | Deriving formula, mass, InChIKey from structure | Yes — it is computation, not assertion |
| **GLAD mappings** | EF 3.1 ↔ SimaPro flow correspondence | Yes, as a stated mapping |
| **ecoinvent** | An additional source list to merge | Yes, as a source list |
| **BAFU 2026 v1** | An additional source list to merge | Yes, as a source list — but it ships no flow identifier of its own, so a row is matched on its registry number where it has one and on its name where it does not |
| **Stepwise 2006** | An additional source list to merge, and the second LCIA method | Yes, as a source list, and it merges last: a SimaPro method file ships no identifiers either, so every one is derived from the name, the compartment and the unit |

PubChem is the important exception. Its synonym and cross-reference data is
crowd-sourced and contains errors, so it is never accepted as the sole basis for
an identity claim. EF 3.1's own synonym lists appear to be drawn from PubChem,
which is why they are not used either.
