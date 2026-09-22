"""PubChem's name for a CAS never becomes a flow's preferred label.

The `entropy` rule used to make it one: it replaced a preferred label with
PubChem's preferred name for the flow's CAS whenever that name scored as less
complex.  Two guards were built to hold it back -- one refusing a name from a
compound whose formal charge differed from the flow's (accepting `chloride` /
Cl⁻ for hydrogen chloride / HCl), and a whitelist keeping `Water` from becoming
`oxidane`.  Each was a patch on a rule whose real problem was that it took a
name from a single source with no agreement requirement, and #222 removed it.

What the guards protected is still worth pinning, because it is the outcome
rather than the mechanism: a PubChem name must not replace a label, by any path.

**"By any path" was a claim this file did not check** (#21).  It exercised the
`consensus_match` path and only that one, while `pubchem_readable_name` --
nineteenth in the chain, five stages after `consensus_match`, and so the last
word on the published label -- did exactly what the docstring forbids 17,942
times a run: `Nivalenol` published as `Epitope ID:2151205`, `Rhodamine 6G` as
its 90-character systematic name, `(-)-Borneol` as `Borneol, (-)-`.  Nobody was
asked about any of it; the stage consulted no ruling and queued nothing.

So the outcome is now pinned where it is decided, in the chain itself:
`TheChainHasNoPubChemNamingStage` fails if either module returns to
`DEFAULT_TRANSFORMERS`.

`_get_cas_profile` itself is not going anywhere -- the charge it reads is used
by the relationship classification -- so its unit tests stay as they were.
"""

import unittest
from unittest.mock import patch

from brightway_flows.domain.flow import Flow
from brightway_flows.transformers import DEFAULT_TRANSFORMERS
from brightway_flows.transformers.consensus_match import ConsensusMatchTransformer
from brightway_flows.transformers.consensus_match.lookups import LookupClient


def _make_transformer() -> ConsensusMatchTransformer:
    """Return a bare transformer with no external data loaded."""
    return ConsensusMatchTransformer()


def _pubchem_compound(cid: int, charge: int | None, iupac_name: str) -> dict:
    """Minimal PubChem compound dict as stored in `indexes.pubchem_by_cas`."""
    compound: dict = {"cid": cid, "props": []}
    if charge is not None:
        compound["charge"] = charge
    return compound


def _identifiers_for_cid(iupac_name: str) -> dict:
    """Minimal `indexes.pubchem_identifiers_by_cid` entry with a Preferred IUPAC Name."""
    return {"IUPAC Name": [{"value": iupac_name}]}


def _flow(uuid: str, name: str, cas: str) -> dict:
    """Minimal harmonised-flow dict for use with transform()."""
    return {
        "uuid": uuid,
        "prefLabel": [{"@value": name, "@language": "en"}],
        "cas_numbers": [cas],
        "ec_numbers": [],
        "source": "EF 3.1",
    }


class TestGetCasProfileChargeField(unittest.TestCase):
    """Unit tests: a compound profile carries the charge from the compound dict."""

    def test_negative_charge_stored(self):
        t = _make_transformer()
        t.indexes.pubchem_by_cas["7647-01-0"] = [_pubchem_compound(312, -1, "chloride")]
        profile = t.profiles.get("7647-01-0")
        self.assertEqual(profile["charge"], -1)

    def test_positive_charge_stored(self):
        t = _make_transformer()
        t.indexes.pubchem_by_cas["14798-03-9"] = [_pubchem_compound(825, 1, "ammonium")]
        profile = t.profiles.get("14798-03-9")
        self.assertEqual(profile["charge"], 1)

    def test_zero_charge_stored(self):
        t = _make_transformer()
        t.indexes.pubchem_by_cas["74-82-8"] = [_pubchem_compound(297, 0, "methane")]
        profile = t.profiles.get("74-82-8")
        self.assertEqual(profile["charge"], 0)

    def test_charge_is_none_when_absent(self):
        """Compounds without a charge field should leave charge as None."""
        t = _make_transformer()
        t.indexes.pubchem_by_cas["74-82-8"] = [_pubchem_compound(297, None, "methane")]
        profile = t.profiles.get("74-82-8")
        self.assertIsNone(profile["charge"])

    def test_charge_cached_across_calls(self):
        t = _make_transformer()
        t.indexes.pubchem_by_cas["7647-01-0"] = [_pubchem_compound(312, -1, "chloride")]
        first = t.profiles.get("7647-01-0")
        second = t.profiles.get("7647-01-0")
        self.assertEqual(first["charge"], second["charge"])
        self.assertIs(first, second)  # same dict object from cache


class TheChainHasNoPubChemNamingStage(unittest.TestCase):
    """No stage in the default chain names a flow from PubChem alone (#21).

    Asserted over the chain rather than over one class, because the two stages
    that did this were different classes doing the same thing:
    `PubChemReadableNameTransformer` took a record title and
    `PubChemTransformer` takes the preferred name for a CAS.  Both live under
    `transformers.pubchem*`, and neither belongs in a pipeline that publishes
    its labels -- the rules that survived require corroboration, bilateral
    CC/ChEBI agreement or a two-source quorum, and a single-source name is
    exactly what `entropy` was removed for.

    Written as a property of the module rather than a list of forbidden class
    names so that a third one, whatever it is called, fails here too.
    """

    def test_no_default_transformer_names_a_flow_from_pubchem(self):
        offenders = [
            transformer.__name__
            for transformer in DEFAULT_TRANSFORMERS
            if transformer.__module__.startswith(
                "brightway_flows.transformers.pubchem"
            )
        ]
        self.assertEqual(offenders, [])


class TestPubchemNameNeverReplacesLabel(unittest.TestCase):
    """The cases the removed rule got wrong, pinned as outcomes.

    Each ran through the real PubChem indexes rather than a patched lookup, and
    still does, so a reintroduction by any path fails these.
    """

    def setUp(self) -> None:
        self._save_patcher = patch.object(ConsensusMatchTransformer, "_save_caches")
        self._reload_patcher = patch.object(LookupClient, "reload_commonchem_cache")
        self._save_patcher.start()
        self._reload_patcher.start()

    def tearDown(self) -> None:
        self._save_patcher.stop()
        self._reload_patcher.stop()

    def _setup_transformer(
        self, cid: int, charge: int | None, iupac_name: str, cas: str
    ) -> ConsensusMatchTransformer:
        t = _make_transformer()
        t.indexes.pubchem_by_cas[cas] = [_pubchem_compound(cid, charge, iupac_name)]
        t.indexes.pubchem_identifiers_by_cid[str(cid)] = _identifiers_for_cid(iupac_name)
        t.indexes.compound_primary_cas_by_cid[cid] = cas
        return t

    def _pref_changes(self, t: ConsensusMatchTransformer, flows: list[dict]) -> list:
        changes = t.transform([Flow.from_dict(f) for f in flows])
        return [c for c in changes if c.field == "prefLabel"]

    def test_a_charged_compounds_name_is_not_adopted(self):
        """`Hydrogen Chloride` must not become `chloride`: the PubChem compound
        carrying that name is the Cl⁻ ion, a different substance."""
        cas = "7647-01-0"
        t = self._setup_transformer(cid=312, charge=-1, iupac_name="chloride", cas=cas)
        self.assertEqual(
            self._pref_changes(t, [_flow("uuid-hcl", "Hydrogen Chloride", cas)]), []
        )

    def test_a_cations_name_is_not_adopted(self):
        cas = "14798-03-9"
        t = self._setup_transformer(cid=825, charge=1, iupac_name="azanium", cas=cas)
        self.assertEqual(
            self._pref_changes(t, [_flow("uuid-nh4", "Ammonium Chloride Solution", cas)]), []
        )

    def test_a_neutral_compounds_name_is_not_adopted_either(self):
        """The charge guard was never the point.  A neutral compound whose name
        the old rule would have taken is left alone for the same reason: one
        source asserting a name is not enough to publish it as the label."""
        cas = "630-08-0"
        t = self._setup_transformer(cid=281, charge=0, iupac_name="carbon monoxide", cas=cas)
        self.assertEqual(
            self._pref_changes(
                t, [_flow("uuid-co", "CarbonMonoxide__LongComplexNameXYZ", cas)]
            ),
            [],
        )

    def test_water_does_not_become_oxidane(self):
        """All EF 3.1 water flows share CAS 7732-18-5, and PubChem's preferred
        name for it is the systematic `oxidane`.  The group's longest member
        name once set the score for every member, so plain `Water` was renamed
        along with `Water To Cooling`."""
        cas = "7732-18-5"
        t = self._setup_transformer(cid=962, charge=0, iupac_name="oxidane", cas=cas)
        flows = [
            _flow("uuid-water", "Water", cas),
            _flow("uuid-wtc", "Water To Cooling", cas),
        ]
        self.assertEqual(self._pref_changes(t, flows), [])
