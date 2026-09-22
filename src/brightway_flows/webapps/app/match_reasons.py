"""Why the merge believes a source flow is this consensus flow, in a sentence.

The flow page listed which lists a flow came from and what it is called in each
of them, and said nothing about *why* those rows are held to be the same
substance in the same compartment.  That answer was already in the database --
every row of `elementary_flow_sources` carries the basis the substance was
resolved on, the reason the compartment was chosen, and the mapping file where
a curator wrote the decision down -- as four hyphenated category names a reader
had to know the merge to read.

This turns those categories into a sentence: *The CAS numbers are the same
(76703-62-3), and both name the same compartment.*  Two decisions behind that:

* **The evidence and the compartment are said separately**, because they are two
  separate steps and either can be the surprising one.  A row that matched on a
  name and then landed in the only compartment left is a weaker claim than one
  that matched on a registry number and an identical compartment IRI, and a
  curator scanning the table should be able to see which they are looking at.
* **An unrecognised category is printed rather than swallowed.**  The merge can
  gain a basis this file has not been taught; a row that then said nothing would
  read as "no reason recorded", which is a different and much worse claim than
  "recorded, and this page has no words for it yet".
"""

from __future__ import annotations

from typing import Any

#: How the *substance* was resolved -- `resolve_flow_object`'s basis.  The
#: `{value}` slot is the identifier the lookup used, where the row records one.
_EVIDENCE = {
    "cas": "The CAS numbers are the same ({value})",
    "cas+label": (
        "Several substances share the CAS number ({value}), and the row's name"
        " picks this one"
    ),
    "cas+designation": (
        "Several substances share the CAS number ({value}), and the industry"
        " designation the row's name ends in names this one"
    ),
    "cas+qualifier": (
        "Several substances share the CAS number ({value}), and the row's name"
        " picks this origin -- fossil, biogenic, and so on"
    ),
    "ec": "The EC numbers are the same ({value})",
    "label": "This substance answers to the name the row carries",
    "material": (
        "A curated ruling names the material this row is made of, and this flow"
        " is it"
    ),
    "simapro-name-pattern": (
        "Rewritten out of its SimaPro spelling, the row's name is this"
        " substance's"
    ),
    "historical-name": (
        "The row carries a name ecoinvent retired, and the vendor's own"
        " crosswalk says this substance is what it became"
    ),
}

#: How the *compartment* was chosen among the flows of that substance --
#: `_select_elementary_flow`'s reason.
_PLACEMENT = {
    "exact-context-iri-match": "both name the same compartment",
    "best-score": (
        "of this substance's flows, this one's compartment and unit fit the row"
        " best"
    ),
    "new-elementary-flow-created": (
        "no flow of this substance sat in that compartment, so this one was"
        " created for the row"
    ),
}

#: Why a row that matched nothing became a flow of its own -- the merge writes
#: the reason it could not be placed as the basis of the flow it then created.
_CREATION = {
    "no-flow-object-candidate": (
        "Nothing in the list carried this substance, so this flow was created"
        " from this row"
    ),
    "no-candidates-same-dimension-media": (
        "The substance was already in the list but had no flow in this"
        " compartment, so this flow was created from this row"
    ),
    "tied-elementary-candidates": (
        "Several of this substance's flows fitted the row equally well, so this"
        " flow was created from it rather than guessing between them"
    ),
    "context-contradiction": (
        "Every flow of this substance named a compartment this row rules out,"
        " so this flow was created from it"
    ),
}


def match_reason(metadata: Any, *, base_list: bool = False) -> str:
    """One source row's reason, as a sentence, or `""` where none is recorded.

    *metadata* is the `source_metadata` the merge wrote beside the reference --
    an external payload, and read as the dict it is.  *base_list* says the row
    comes from the list the consensus flow was minted from, which is not a match
    at all and is the majority of the rows on this page.
    """
    if base_list:
        return (
            "The consensus list is built from this one, so this row is the flow"
            " itself rather than something matched to it."
        )
    if not isinstance(metadata, dict):
        return ""
    basis = str(metadata.get("merge_basis") or "")
    method = str(metadata.get("merge_method") or "")
    if not basis and not method:
        return ""

    if method == "flow_object_creation":
        return _sentence(_CREATION.get(basis) or _unknown(basis, method))
    if method == "manual_addition_lookup" or basis == "manual_addition":
        return _sentence(
            "A curator's addition file groups this row onto this flow"
        )
    if basis == "prepared_mapping":
        return _sentence(_prepared(metadata))

    evidence = _EVIDENCE.get(basis)
    if evidence is None:
        return _sentence(_unknown(basis, method))
    value = str(
        metadata.get("cas_number") if basis.startswith("cas")
        else metadata.get("ec_number") if basis == "ec"
        else ""
    )
    placement = _PLACEMENT.get(str(metadata.get("selector_reason") or ""), "")
    clause = evidence.format(value=value) if value else _without_value(evidence)
    # A semicolon, not a comma: the evidence clause can already carry one comma
    # of its own, and three clauses joined by "and" read as one long guess
    # rather than as two separate decisions.
    return _sentence(f"{clause}; {placement}" if placement else clause)


def _prepared(metadata: dict[str, Any]) -> str:
    """A row placed by a curated correspondence table, and which one."""
    mapping_file = str(metadata.get("mapping_file") or "")
    named = f" ({mapping_file})" if mapping_file else ""
    details = metadata.get("merge_details")
    details = details if isinstance(details, dict) else {}
    redirected = (
        details.get("prepared_target_resolution")
        == "redirected-from-deprecated-target"
    )
    if str(metadata.get("selector_reason") or "") == "new-elementary-flow-created":
        return (
            f"A curator's mapping table{named} names this substance, which had"
            " no flow in this compartment, so this flow was created for the row"
        )
    if redirected:
        return (
            f"A curator's mapping table{named} names a flow that has since been"
            " deprecated, and this flow replaced it"
        )
    return f"A curator's mapping table{named} names this flow"


def _without_value(evidence: str) -> str:
    """The same sentence for a row whose identifier the merge did not record."""
    return evidence.replace(" ({value})", "").format(value="")


def _unknown(basis: str, method: str) -> str:
    """A category this file has no words for, printed rather than dropped."""
    recorded = " on ".join(part for part in (method, basis) if part)
    return f"Recorded as {recorded}"


def _sentence(text: str) -> str:
    return f"{text}." if text and not text.endswith(".") else text
