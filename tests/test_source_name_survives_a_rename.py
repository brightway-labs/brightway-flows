"""The name a rename replaces has to stay findable.

Both rename rules in `consensus_match` keep the source list's own name as an
alternative label, and both had that undone.  `add_commonchem_altlabels` runs
next over the same member and rewrites the whole `altLabel` field, and it built
its new list from the *record* -- which the rename has not been applied to yet,
because a transformer proposes and the engine applies.  Two proposals for one
field, the later one computed from stale input, and the engine takes the later
one.

The consequence is not subtle.  Of the 9,493 live flows a rename touched in the
2026-08-17 build, 5,188 no longer published the name their source list gave
them, across 443 distinct pairs: `HFC-116` for hexafluoroethane, `Halon-1001`
for bromomethane, `Systhane` for myclobutanil.  An inventory written against
EF 3.1 holds the vendor's string and nothing else, so a flow that has dropped it
cannot be found by the only name its user has (#104, #106).

The tests come in pairs.  One half asks that the source name survives; the other
asks that the Common Chemistry synonyms it used to be overwritten by are still
there, because the cheap way to make the first half pass is to stop adding them.
"""

from __future__ import annotations

import unittest
from collections import defaultdict
from unittest.mock import patch

from brightway_flows.domain.flow import Flow
from brightway_flows.domain.labels import coerce_alt_labels, coerce_pref_label
from brightway_flows.domain.preferred_label_decisions import (
    APPROVE,
    LabelDecision,
    decision_key,
    load_preferred_label_decisions,
)
from brightway_flows.pipeline import Change
from brightway_flows.transformers.consensus_match import ConsensusMatchTransformer

#: Hexafluoroethane, the substance #106 is written about: EF 3.1 calls it
#: `HFC-116`, Common Chemistry and ChEBI both call it `Hexafluoroethane`, and
#: Common Chemistry holds a dozen synonyms for the number.
_UUID = "08a91e70-3ddc-11dd-9340-0050c2490048"
_CAS = "76-16-4"
_CHEBI = "http://purl.obolibrary.org/obo/CHEBI_32905"
_SOURCE_NAME = "HFC-116"
_AGREED = "Hexafluoroethane"
_CC_SYNONYMS = [
    "Ethane, 1,1,1,2,2,2-hexafluoro-",
    "Ethyl hexafluoride",
    "Perfluoroethane",
]


def _transformer(
    *,
    chebi_label: str | None = _AGREED,
    cc_name: str = _AGREED,
    cc_synonyms: list[str] | None = None,
) -> ConsensusMatchTransformer:
    """A transformer whose ChEBI and Common Chemistry answers are stubs.

    `chebi_label=None` takes ChEBI out entirely, which is what sends the naming
    through the source vote instead of through bilateral agreement.
    """
    t = ConsensusMatchTransformer()
    if chebi_label is None:
        t.indexes.chebi_records = {}
        t.indexes.chebi_by_cas = defaultdict(list)
    else:
        t.indexes.chebi_records = {
            _CHEBI: {"label": chebi_label, "cas_numbers": [_CAS], "synonyms": []},
        }
        t.indexes.chebi_by_cas = defaultdict(list, {_CAS: [_CHEBI]})
    t.indexes.chebi_by_name = defaultdict(list)
    t.lookups.commonchem_cache = {
        "search_by_query": {},
        "detail_by_cas": {
            _CAS: {
                "name": cc_name,
                "synonyms": _CC_SYNONYMS if cc_synonyms is None else cc_synonyms,
            },
        },
    }
    t.lookups.service_available = {
        "commonchemistry": True, "wikidata": False, "duckduckgo": False,
    }
    t.gate.decisions = load_preferred_label_decisions()
    return t


def _flow(name: str = _SOURCE_NAME) -> dict:
    return {
        "uuid": _UUID,
        "prefLabel": [{"@value": name, "@language": "en"}],
        "altLabel": [],
        "source": "EF 3.1",
        "context": ["Emissions", "Emissions to air", "Emissions to air, unspecified"],
        "cas_numbers": [_CAS],
    }


def _run(t: ConsensusMatchTransformer, flow: dict) -> list[Change]:
    with patch.object(t.lookups, "reload_commonchem_cache"):
        with patch.object(t, "_save_caches"):
            with patch.object(t.lookups, "wikidata", return_value={}):
                with patch.object(t.lookups, "wikipedia", return_value={}):
                    with patch.object(
                        t.classifier, "classify_name_cas",
                        return_value=("exact_match", "test", []),
                    ):
                        return t.transform([Flow.from_dict(flow)])


def _applied(flow: dict, changes: list[Change]) -> dict:
    """The record the engine would leave behind: last writer wins per field.

    The same rule the engine applies, and the reason this defect existed: two
    changes to `altLabel` mean the second one decides, whatever the first said.
    """
    result = dict(flow)
    for change in changes:
        if change.uuid == flow["uuid"]:
            result[change.field] = change.new_value
    return result


def _alt_values(flow: dict, changes: list[Change]) -> list[str]:
    return [label.value for label in coerce_alt_labels(_applied(flow, changes).get("altLabel"))]


class BilateralAgreementKeepsTheSourceNameTestCase(unittest.TestCase):
    """Common Chemistry and ChEBI agree, and the vendor's name still survives."""

    def setUp(self) -> None:
        self.flow = _flow()
        self.changes = _run(_transformer(), self.flow)

    def test_the_flow_is_renamed(self):
        pref = coerce_pref_label(_applied(self.flow, self.changes).get("prefLabel"))
        self.assertIsNotNone(pref)
        self.assertEqual(pref.value, _AGREED)

    def test_the_source_name_is_still_an_alternative_label(self):
        self.assertIn(_SOURCE_NAME, _alt_values(self.flow, self.changes))

    def test_the_common_chemistry_synonyms_are_still_there(self):
        """The other half: not gained by dropping what used to overwrite it."""
        values = _alt_values(self.flow, self.changes)
        for synonym in _CC_SYNONYMS:
            self.assertIn(synonym, values)

    def test_the_new_name_is_not_also_an_alternative_label(self):
        self.assertNotIn(_AGREED, _alt_values(self.flow, self.changes))


class TheSourceVoteKeepsTheSourceNameTooTestCase(unittest.TestCase):
    """The other rename rule, which fires when ChEBI has no record.

    Both rules retain, both were overwritten by the same later proposal, and a
    fix applied to only one of them would leave the half of the list that ChEBI
    has never heard of exactly where it was -- which for #104 is 85 of 114
    substances.
    """

    def setUp(self) -> None:
        self.flow = _flow()
        t = _transformer(chebi_label=None)
        # Two sources naming the CAS is the vote's quorum; Common Chemistry is
        # one and the EC inventory is the second.
        t.indexes.ec_names_by_cas = defaultdict(set, {_CAS: {_AGREED}})
        t.indexes.ec_cas_by_name = defaultdict(set)
        # The vote is not trusted by default, so without a ruling this rename
        # is queued rather than applied and there would be nothing to retain.
        t.gate.decisions[decision_key(_SOURCE_NAME, _AGREED)] = LabelDecision(
            current=_SOURCE_NAME, replacement=_AGREED, decision=APPROVE,
        )
        self.changes = _run(t, self.flow)

    def test_the_flow_is_renamed_by_the_vote(self):
        pref = coerce_pref_label(_applied(self.flow, self.changes).get("prefLabel"))
        self.assertIsNotNone(pref)
        self.assertEqual(pref.value, _AGREED)

    def test_the_source_name_is_still_an_alternative_label(self):
        self.assertIn(_SOURCE_NAME, _alt_values(self.flow, self.changes))

    def test_the_common_chemistry_synonyms_are_still_there(self):
        values = _alt_values(self.flow, self.changes)
        for synonym in _CC_SYNONYMS:
            self.assertIn(synonym, values)


class NoCommonChemistrySynonymsTestCase(unittest.TestCase):
    """The case that always worked, which must go on working.

    Where the registry number has no Common Chemistry synonyms the second
    proposal was never made, so nothing overwrote the retention -- 4,305 of the
    9,493 renamed flows kept their source name for that reason alone.  A fix
    that moved the retention rather than protecting it would break these.
    """

    def setUp(self) -> None:
        self.flow = _flow()
        self.changes = _run(_transformer(cc_synonyms=[]), self.flow)

    def test_the_source_name_is_still_an_alternative_label(self):
        self.assertIn(_SOURCE_NAME, _alt_values(self.flow, self.changes))


class AlreadyNamedTestCase(unittest.TestCase):
    """A flow the source already named correctly gains no self-referential label."""

    def setUp(self) -> None:
        self.flow = _flow(name=_AGREED)
        self.changes = _run(_transformer(), self.flow)

    def test_no_rename_is_proposed(self):
        pref_changes = [c for c in self.changes if c.field == "prefLabel"]
        self.assertEqual(pref_changes, [])

    def test_the_name_is_not_added_as_its_own_alternative(self):
        self.assertNotIn(_AGREED, _alt_values(self.flow, self.changes))


if __name__ == "__main__":
    unittest.main()
