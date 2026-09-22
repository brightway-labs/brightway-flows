"""The multi-source vote renames members, so the object's label must not gate it.

`rename_from_source_vote` is the fallback for a CAS that Common Chemistry and
ChEBI do not both name: the name a quorum of sources votes for.  It replaces the
preferred label of every *member* of a flow object, and it used to return as soon
as the flow *object's* label matched the candidate -- a comparison between the
candidate and a label the loop does not write.

Members need not share their object's label, so once the object converged the
members behind it were stranded.  That is the defect #221 fixed at the
`cc_chebi_agreement` site, where it had left 227 flows on a name their own flow
object disagreed with; #245 is the same guard at this one.  `normalize` folds
whitespace as well as case, which widens it: an object reading `Ethyl Benzene`
counted as already agreeing with `Ethylbenzene`, so the whole object was skipped.

The rule is not in `DEFAULT_APPROVED_RULES`, so what it proposes is queued for a
curator rather than written.  These pin the proposal -- that the rule now reaches
the member at all -- and, with a ruling in hand, the change it then makes.
"""

from __future__ import annotations

import unittest
from collections import defaultdict
from unittest.mock import patch

from brightway_flows.domain.flow import Flow
from brightway_flows.domain.labels import coerce_pref_label
from brightway_flows.domain.preferred_label_decisions import (
    APPROVE,
    LabelDecision,
    decision_key,
)
from brightway_flows.pipeline import Change
from brightway_flows.transformers.consensus_match import ConsensusMatchTransformer

_CAS = "100-41-4"
_CHEBI_ID = "http://purl.obolibrary.org/obo/CHEBI_16101"
_VOTED_NAME = "Ethylbenzene"

_OBJECT_MEMBER_UUID = "18a91e70-3ddc-11dd-9480-0050c2490048"
_STALE_MEMBER_UUID = "18a91e70-3ddc-11dd-9481-0050c2490048"


def _make_transformer() -> ConsensusMatchTransformer:
    """A transformer where only the vote rule can fire.

    ChEBI and the EC inventory both give `Ethylbenzene` for the CAS, which is the
    quorum of two the vote requires.  Common Chemistry holds nothing for it, so
    `cc_chebi_agreed_name` abstains and the vote is what runs -- the two rules are
    mutually exclusive.
    """
    t = ConsensusMatchTransformer()
    t.indexes.chebi_records = {
        _CHEBI_ID: {"label": _VOTED_NAME, "cas_numbers": [_CAS], "synonyms": []},
    }
    t.indexes.chebi_by_cas = defaultdict(list, {_CAS: [_CHEBI_ID]})
    t.indexes.chebi_by_name = defaultdict(list)
    t.indexes.ec_names_by_cas = defaultdict(set, {_CAS: {_VOTED_NAME}})
    t.lookups.commonchem_cache = {"search_by_query": {}, "detail_by_cas": {}}
    t.lookups.service_available = {
        "commonchemistry": False, "wikidata": False, "duckduckgo": False,
    }
    t.gate.decisions = {}
    return t


def _flow(uuid: str, name: str) -> dict:
    return {
        "uuid": uuid,
        "prefLabel": [{"@value": name, "@language": "en"}],
        "altLabel": [],
        "source": "EF 3.1",
        "context": ["Emissions", "Emissions to air", "Emissions to air, unspecified"],
        "cas_numbers": [_CAS],
    }


class MemberRenamedWhenObjectAlreadyAgreesTestCase(unittest.TestCase):
    """What the rule proposes, when the object's label is not what needs fixing."""

    def _run(
        self, names: dict[str, str], *, approve: bool = False
    ) -> tuple[list[Change], ConsensusMatchTransformer]:
        t = _make_transformer()
        if approve:
            t.gate.decisions = {
                decision_key(current, _VOTED_NAME): LabelDecision(
                    current=current, replacement=_VOTED_NAME, decision=APPROVE,
                )
                for current in names.values()
            }
        flows = [Flow.from_dict(_flow(uuid, name)) for uuid, name in names.items()]
        with patch.object(t.lookups, "reload_commonchem_cache"):
            with patch.object(t, "_save_caches"):
                with patch.object(t.lookups, "wikidata", return_value={}):
                    with patch.object(t.lookups, "wikipedia", return_value={}):
                        return t.transform(flows), t

    def _proposed_for(
        self, transformer: ConsensusMatchTransformer, uuid: str
    ) -> list[str]:
        return [
            row.replacement for row in transformer.gate.undecided if row.uuid == uuid
        ]

    def _pref_change(self, changes: list[Change], uuid: str) -> Change | None:
        for change in changes:
            if change.uuid == uuid and change.field == "prefLabel":
                return change
        return None

    def test_a_member_behind_an_agreeing_object_is_still_proposed(self):
        # The longest member name becomes the object's label, so the object here
        # reads `Ethylbenzene` -- already the voted name -- while `EtBz` behind
        # it does not.  This is the case the object-level guard skipped.
        _, t = self._run({
            _OBJECT_MEMBER_UUID: _VOTED_NAME,
            _STALE_MEMBER_UUID: "EtBz",
        })
        self.assertEqual(self._proposed_for(t, _STALE_MEMBER_UUID), [_VOTED_NAME])

    def test_a_name_differing_only_by_spacing_is_still_proposed(self):
        """`normalize` folds whitespace, so this used to read as no change."""
        _, t = self._run({_STALE_MEMBER_UUID: "Ethyl Benzene"})
        self.assertEqual(self._proposed_for(t, _STALE_MEMBER_UUID), [_VOTED_NAME])

    def test_the_member_that_already_agrees_is_left_alone(self):
        """Nothing proposed for it, so nothing for a curator to rule on."""
        _, t = self._run({
            _OBJECT_MEMBER_UUID: _VOTED_NAME,
            _STALE_MEMBER_UUID: "EtBz",
        })
        self.assertEqual(self._proposed_for(t, _OBJECT_MEMBER_UUID), [])

    def test_an_object_no_member_of_which_would_change_asks_nobody(self):
        """Neither a proposal nor a review row: the rule has nothing to say.

        Classification runs after the members are selected, so an object whose
        members all carry the voted name already never reaches it -- and never
        files the review row a non-exact verdict would produce.
        """
        changes, t = self._run({_OBJECT_MEMBER_UUID: _VOTED_NAME})
        self.assertEqual(t.gate.undecided, [])
        self.assertEqual(self._pref_change(changes, _OBJECT_MEMBER_UUID), None)
        self.assertEqual(
            [item for item in t.review if item.candidate_name == _VOTED_NAME], []
        )

    def test_a_ruled_member_behind_an_agreeing_object_is_renamed(self):
        """With the pair approved, the proposal becomes the label it names."""
        changes, _ = self._run(
            {_OBJECT_MEMBER_UUID: _VOTED_NAME, _STALE_MEMBER_UUID: "EtBz"},
            approve=True,
        )
        change = self._pref_change(changes, _STALE_MEMBER_UUID)
        self.assertIsNotNone(change, "member behind an agreeing object was not renamed")
        self.assertEqual(coerce_pref_label(change.new_value).value, _VOTED_NAME)
        self.assertIsNone(self._pref_change(changes, _OBJECT_MEMBER_UUID))


if __name__ == "__main__":
    unittest.main()
