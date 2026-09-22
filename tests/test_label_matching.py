"""Which label evidence is allowed to resolve a source row to a flow object.

Labels are cheap and shared: a product code or a trade name can name several
unrelated substances, so a label hit is only as good as the label that produced
it.  `_narrow_label_candidates` is where that judgement lives, and it is reached
only once the CAS and EC lookups have already come back empty.

Found by widening matching to look up every name a row is known by (#213):
"Propylene Carbonate", CAS 108-32-7, matched **Talc** on a shared "K 3"
alternative label.  The guard that should have caught it tried to intersect the
candidates with the source CAS first and kept them all when that came back
empty -- which, given where it is called from, it always did.
"""

import unittest

from brightway_flows.merge.contexts import ContextExpectations
from brightway_flows.merge.matching import (
    ION_ELEMENT_REFUSED_BASIS,
    resolve_flow_object,
)
from brightway_flows.sources import resolve_source_list
from brightway_flows.merge.state import MergeAccumulator, MergeIndexes, SourceRow

TALC = "fo-talc"
CARBONATE = "fo-carbonate"
GRIT = "fo-grit"


def _row(name="Propylene Carbonate", *, cas="108-32-7", labels=None):
    return SourceRow(
        uuid="s-1", name=name, synonyms=[],
        labels=labels if labels is not None else [name],
        context=["water"], context_iri="", context_normalized=(),
        unit="kg", unit_iri="", cas=cas, ec="",
    )


def _indexes(*, label_index, pref_label_index, with_cas, cas_index=None,
             source="ecoinvent-3.12", labels=None):
    return MergeIndexes(
        flow_objects_by_id={}, flow_object_label_by_id=labels or {},
        cas_index=cas_index or {},
        ec_index={}, label_index=label_index, pref_label_index=pref_label_index,
        qualifier_index={}, flow_objects_with_cas=with_cas,
        context_expectations=ContextExpectations(
            _by_source_context={}, _source_label="test"
        ), consensus_context_strings={},
        prepared_context_decisions={}, mapping_file=None,
        source=resolve_source_list(source),
    )


def _resolve(row, indexes):
    return resolve_flow_object(
        row=row, indexes=indexes, accumulator=MergeAccumulator()
    )


class LabelEvidenceTestCase(unittest.TestCase):
    def test_an_alt_label_hit_on_a_cas_bearing_object_is_rejected(self):
        """The Talc case.  Talc carries a CAS and it is not 108-32-7, so the
        shared "K 3" is a coincidence of naming, not evidence of identity."""
        resolution = _resolve(
            _row(labels=["Propylene Carbonate", "K 3"]),
            _indexes(
                label_index={"k 3": {TALC}},
                pref_label_index={"talc": {TALC}},
                with_cas={TALC},
            ),
        )
        self.assertIsNone(resolution)

    def test_a_pref_label_hit_on_a_cas_bearing_object_is_kept(self):
        """The label is that substance's primary name, not one of the many
        things it is also called.  A salt form numbered differently from its
        parent acid lands here, which is why the CAS disagreement is tolerated."""
        resolution = _resolve(
            _row("Propylene carbonate"),
            _indexes(
                label_index={"propylene carbonate": {CARBONATE}},
                pref_label_index={"propylene carbonate": {CARBONATE}},
                with_cas={CARBONATE},
            ),
        )
        self.assertIsNotNone(resolution)
        self.assertEqual(resolution.flow_object_id, CARBONATE)

    def test_any_hit_on_a_cas_less_object_is_kept(self):
        """Neither side has a CAS, so there is nothing to disagree about.  This
        is what keeps unspecified groups and mineral aggregates matchable."""
        resolution = _resolve(
            _row("Grit", cas=""),
            _indexes(
                label_index={"grit": {GRIT}},
                pref_label_index={},
                with_cas=set(),
            ),
        )
        self.assertIsNotNone(resolution)
        self.assertEqual(resolution.flow_object_id, GRIT)

    def test_the_rule_does_not_depend_on_the_source_having_a_cas(self):
        """It used to: a row with a CAS took a branch that kept every candidate.
        Reaching here at all means the CAS lookup found nothing, so a source CAS
        is a number the index does not know either way."""
        indexes = _indexes(
            label_index={"k 3": {TALC}},
            pref_label_index={"talc": {TALC}},
            with_cas={TALC},
        )
        for cas in ("108-32-7", ""):
            with self.subTest(source_cas=cas or "(none)"):
                self.assertIsNone(
                    _resolve(_row(labels=["K 3"], cas=cas), indexes)
                )


RHODIUM = "fo-rhodium"
RHODIUM_ION = "fo-rhodium-3"


class AChargedNameNeverReachesTheBareElementTestCase(unittest.TestCase):
    """A row whose name states a charge is an ion, and the bare element is not
    where it goes (#198).

    ecoinvent 3.12's `Rhodium III` carries 16065-89-7 and ships `Rhodium` as a
    synonym.  EF 3.1 holds no rhodium ion, so the number found nothing and the
    synonym hit the element's preferred label -- evidence the label rule
    accepts, since the element is a numbered object and the hit is on its
    primary name.  Seven rows were published as the metal.
    """

    def _rhodium(self, *, ion=False):
        label_index = {"rhodium": {RHODIUM}}
        pref = {"rhodium": {RHODIUM}}
        labels = {RHODIUM: "Rhodium"}
        with_cas = {RHODIUM}
        if ion:
            label_index["rhodium(3+)"] = {RHODIUM_ION}
            pref["rhodium(3+)"] = {RHODIUM_ION}
            labels[RHODIUM_ION] = "Rhodium(3+)"
            with_cas.add(RHODIUM_ION)
        return _indexes(label_index=label_index, pref_label_index=pref,
                        with_cas=with_cas, labels=labels)

    def test_the_element_is_refused_and_the_refusal_is_recorded(self):
        accumulator = MergeAccumulator()
        resolution = resolve_flow_object(
            row=_row("Rhodium III", cas="16065-89-7",
                     labels=["Rhodium III", "Rhodium", "Rhodium ion"]),
            indexes=self._rhodium(), accumulator=accumulator,
        )
        self.assertIsNone(resolution)
        self.assertEqual([u.basis for u in accumulator.unmatched], [ION_ELEMENT_REFUSED_BASIS])

    def test_the_ion_is_reached_when_the_list_holds_it(self):
        """The other half: once a rhodium ion exists, the species spelling of
        the row's own name reaches it, and the element is not in the way."""
        resolution = _resolve(
            _row("Rhodium III", cas="16065-89-7",
                 labels=["Rhodium(3+)", "Rhodium III", "Rhodium"]),
            self._rhodium(ion=True),
        )
        self.assertIsNotNone(resolution)
        self.assertEqual(resolution.flow_object_id, RHODIUM_ION)

    def test_a_bare_name_still_reaches_the_element(self):
        """EF 3.1 ships bare elements in every compartment; a bare name is an
        identity, and nothing here may reread it as an ion."""
        resolution = _resolve(_row("Rhodium", cas=""), self._rhodium())
        self.assertIsNotNone(resolution)
        self.assertEqual(resolution.flow_object_id, RHODIUM)

    def test_the_generic_ion_marker_is_refused_too(self):
        """`Copper ion` states no charge, but it states an ion."""
        resolution = _resolve(
            _row("Rhodium ion", cas="", labels=["Rhodium ion", "Rhodium"]),
            self._rhodium(),
        )
        self.assertIsNone(resolution)

    def test_an_unrelated_element_is_not_refused(self):
        """The refusal is about the row's *own* element.  A label hit on some
        other element is a different mistake, and not this rule's."""
        indexes = _indexes(
            label_index={"palladium": {"fo-palladium"}},
            pref_label_index={"palladium": {"fo-palladium"}},
            with_cas={"fo-palladium"}, labels={"fo-palladium": "Palladium"},
        )
        resolution = _resolve(
            _row("Rhodium III", cas="16065-89-7", labels=["Rhodium III", "Palladium"]),
            indexes,
        )
        self.assertIsNotNone(resolution)
        self.assertEqual(resolution.flow_object_id, "fo-palladium")

    def test_a_row_no_name_reaches_is_not_marked_refused(self):
        accumulator = MergeAccumulator()
        resolution = resolve_flow_object(
            row=_row("Rhodium III", cas="16065-89-7", labels=["Rhodium III"]),
            indexes=self._rhodium(), accumulator=accumulator,
        )
        self.assertIsNone(resolution)
        self.assertNotEqual([u.basis for u in accumulator.unmatched], [ION_ELEMENT_REFUSED_BASIS])


class EveryLabelIsLookedUpTestCase(unittest.TestCase):
    """A row is known by all its names at once, so all of them are looked up."""

    def test_a_hit_on_a_label_other_than_the_first_still_resolves(self):
        """The `MCPA` case: enrichment renamed the row, and looking up only the
        name it settled on found nothing."""
        resolution = _resolve(
            _row("(4-Chloro-2-methylphenoxy)acetic acid", cas="",
                 labels=["(4-Chloro-2-methylphenoxy)acetic acid", "MCPA"]),
            _indexes(
                label_index={"mcpa": {GRIT}},
                pref_label_index={},
                with_cas=set(),
            ),
        )
        self.assertIsNotNone(resolution)
        self.assertEqual(resolution.basis, "label")

    def test_the_label_that_hit_is_what_gets_reported(self):
        """`basis_value` is how a match is traced back, so it must name the
        label that actually produced it rather than the row's first."""
        resolution = _resolve(
            _row("(4-Chloro-2-methylphenoxy)acetic acid", cas="",
                 labels=["(4-Chloro-2-methylphenoxy)acetic acid", "MCPA"]),
            _indexes(
                label_index={"mcpa": {GRIT}},
                pref_label_index={},
                with_cas=set(),
            ),
        )
        self.assertEqual(resolution.basis_value, "MCPA")


CHLOROETHANE = "fo-chloroethane"
DICHLOROETHYLENE = "fo-dichloroethylene"
BENTONITE = "fo-bentonite"
ANTHRACENE = "fo-benzo-a-anthracene"


class RewrittenNameTestCase(unittest.TestCase):
    """The question is asked of the names that found the candidate (#103).

    A SimaPro-shaped list writes `Ethane, chloro-` for chloroethane, and the
    rewriting (#285) is only reached once every identifier and every shipped
    name has failed.  The evidence its match rests on is the rewritten name, so
    that is the name the safety rule has to judge -- judging the shipped names
    instead finds nothing to accept, and no rewritten name could ever survive.
    """

    def test_a_rewritten_name_landing_on_a_preferred_name_is_accepted(self):
        """BAFU's `Ethane, chloro-` rewrites to `chloroethane`, which is not
        merely a synonym of the substance the list holds -- it is that
        substance's own published name, the strongest thing a name can be."""
        resolution = _resolve(
            _row("Ethane, chloro-", cas=""),
            _indexes(
                label_index={"chloroethane": {CHLOROETHANE}},
                pref_label_index={"chloroethane": {CHLOROETHANE}},
                with_cas={CHLOROETHANE},
                source="bafu-2026-v1",
            ),
        )
        self.assertIsNotNone(resolution)
        self.assertEqual(resolution.flow_object_id, CHLOROETHANE)
        self.assertEqual(resolution.basis, "simapro-name-pattern")

    def test_a_systematic_rewritten_name_landing_on_an_alt_label_is_accepted(self):
        """This test used to claim the opposite, and the claim was wrong (#103).

        It read: a derived spelling that is only something a CAS-bearing
        substance is *also called* stays out, exactly like a shipped one.  That
        is right about a shipped name and wrong about this one.  The refusal
        exists because nothing here can tell a trade name from a real one --
        `Granite` reaching Penoxsulam, `K 3` reaching Talc -- and a name built
        by de-inverting a CAS-index spelling settles that question by
        construction: it was assembled out of a parent compound and a
        substituent, so it cannot be either.

        Measured cost of the old claim: four BAFU names, seven rows.  `Ethene,
        1,1-dichloro-` rewrites to `1,1-dichloroethene`, which this list holds
        as a ChEBI synonym of `1,1-dichloroethylene` rather than as its
        published name, and the row minted a numberless second copy of it
        instead.
        """
        resolution = _resolve(
            _row("Ethene, 1,1-dichloro-", cas=""),
            _indexes(
                label_index={"1,1-dichloroethene": {DICHLOROETHYLENE}},
                pref_label_index={"1,1-dichloroethylene": {DICHLOROETHYLENE}},
                with_cas={DICHLOROETHYLENE},
                source="bafu-2026-v1",
            ),
        )
        self.assertIsNotNone(resolution)
        self.assertEqual(resolution.flow_object_id, DICHLOROETHYLENE)
        self.assertEqual(resolution.basis, "simapro-name-pattern")

    def test_a_phrase_rewriting_landing_on_an_alt_label_is_still_refused(self):
        """The other half of the same rule, and where it stops.

        `Clay, Bentonite` rewrites to `bentonite clay`, which the list does
        answer to as a synonym of `Bentonite`.  That rewriting swaps two
        ordinary English words, and an ordinary English phrase is exactly the
        shape a trade name takes, so the argument above does not reach it and
        the refusal stands.  BAFU's row is corrected by a curated registry
        number instead.
        """
        resolution = _resolve(
            _row("Clay, Bentonite", cas=""),
            _indexes(
                label_index={"bentonite clay": {BENTONITE}},
                pref_label_index={"bentonite": {BENTONITE}},
                with_cas={BENTONITE},
                source="bafu-2026-v1",
            ),
        )
        self.assertIsNone(resolution)

    def test_a_shipped_alt_label_hit_is_still_refused_for_a_simapro_list(self):
        """The Talc case does not soften because the list is SimaPro-shaped:
        the widening is for names the rewriting derived, not for the shipped
        labels the rule was written against."""
        resolution = _resolve(
            _row(labels=["Propylene Carbonate", "K 3"]),
            _indexes(
                label_index={"k 3": {TALC}},
                pref_label_index={"talc": {TALC}},
                with_cas={TALC},
                source="bafu-2026-v1",
            ),
        )
        self.assertIsNone(resolution)

    def test_a_retyped_fusion_locant_landing_on_an_alt_label_is_accepted(self):
        """The second rule that produces a systematic name, and it is the
        strongest case for admitting one: `Benzo(a)anthracene` and
        `benzo[a]anthracene` are the same name, and only the brackets differ."""
        resolution = _resolve(
            _row("Benzo(a)anthracene", cas=""),
            _indexes(
                label_index={"benzo[a]anthracene": {ANTHRACENE}},
                pref_label_index={"3,4-benzphenanthrene": {ANTHRACENE}},
                with_cas={ANTHRACENE},
                source="bafu-2026-v1",
            ),
        )
        self.assertIsNotNone(resolution)
        self.assertEqual(resolution.flow_object_id, ANTHRACENE)

    def test_a_list_simapro_did_not_shape_gets_none_of_this(self):
        """The relaxation lives inside the branch the flag gates, so a list
        without it is left exactly where it was: no rewriting, and no widened
        evidence either."""
        resolution = _resolve(
            _row("Ethene, 1,1-dichloro-", cas=""),
            _indexes(
                label_index={"1,1-dichloroethene": {DICHLOROETHYLENE}},
                pref_label_index={"1,1-dichloroethylene": {DICHLOROETHYLENE}},
                with_cas={DICHLOROETHYLENE},
                source="ecoinvent-3.12",
            ),
        )
        self.assertIsNone(resolution)


if __name__ == "__main__":
    unittest.main()
