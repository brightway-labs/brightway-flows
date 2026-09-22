"""One merged view of a CAS number, assembled from PubChem and Common Chemistry.

A profile answers the questions every later decision asks about a substance --
its structure key, its formula, its charge, its preferred name, and the URLs
that back those up -- so that the relationship classifier and the rules can
compare two CAS numbers without knowing which source each field came from.

Profiles are cached on disk between runs because building one costs a Common
Chemistry call.  The cache is validated on read: an entry naming a compound
whose own primary CAS is a different number was written before PubChem
disambiguation existed, and is discarded rather than trusted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from brightway_flows.filesystem import COMPOUND_PROFILE_CACHE_FILEPATH
from brightway_flows.transformers.consensus_match import lookups
from brightway_flows.transformers.consensus_match.indexes import (
    SourceIndexes,
    first_identifier_value,
    identifier_values,
)
from brightway_flows.transformers.consensus_match.lookups import LookupClient


@dataclass
class CompoundProfiles:
    """The per-CAS profile store, and the cache behind it."""

    indexes: SourceIndexes
    lookups: LookupClient
    cache: dict[str, dict[str, Any]] = field(default_factory=dict)

    def load(self) -> None:
        self.cache = lookups.load_json_cache(COMPOUND_PROFILE_CACHE_FILEPATH)

    def save(self) -> None:
        lookups.save_json_cache(COMPOUND_PROFILE_CACHE_FILEPATH, self.cache)

    def get(self, cas: str) -> dict[str, Any]:
        cached = self.cache.get(cas)
        if cached:
            # Validate cached entry: if it records a CID whose primary CAS differs
            # from this CAS, the cache was built with the old (unguarded) disambiguation
            # and is stale.  Discard it so we recompute with the correct compound.
            cached_cid = cached.get("cid")
            if isinstance(cached_cid, int) and self.indexes.compound_primary_cas_by_cid:
                primary = self.indexes.compound_primary_cas_by_cid.get(cached_cid)
                if primary and primary != cas:
                    del self.cache[cas]
                    cached = None
        if cached:
            return cached

        profile: dict[str, Any] = {
            "cas": cas,
            "cid": None,
            "preferred_name": None,
            "formula": None,
            "inchi_key": None,
            "charge": None,
            "chebi_ids": [],
            "chebi_urls": [],
            "pubchem_url": None,
            "commonchemistry_url": None,
        }

        compound = self.indexes.disambiguated_pubchem_compound(cas)
        if compound is None:
            compound = self.indexes.pubchem_primary_compound_by_cas.get(cas)
        cid: int | None = None
        if compound:
            cid_val = compound.get("cid")
            cid = cid_val if isinstance(cid_val, int) else None
            if cid is not None:
                profile["cid"] = cid
                profile["pubchem_url"] = f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}"
            charge_val = compound.get("charge")
            if isinstance(charge_val, int):
                profile["charge"] = charge_val
            _fill_from_pubchem_props(profile, compound.get("props", []))

        if cid is not None:
            id_map = self.indexes.pubchem_identifiers_by_cid.get(str(cid), {})
            iupac = first_identifier_value(id_map, "IUPAC Name")
            if iupac and not profile["preferred_name"]:
                profile["preferred_name"] = iupac
            chebi_ids = [
                v for v in identifier_values(id_map, "ChEBI ID")
                if isinstance(v, str) and v.strip()
            ]
            profile["chebi_ids"] = sorted(set(chebi_ids))
            profile["chebi_urls"] = [
                f"https://www.ebi.ac.uk/chebi/searchId.do?chebiId={v}"
                for v in profile["chebi_ids"]
            ]

        commonchem = self.lookups.commonchem_detail(cas)
        commonchem_url = commonchem.get("url")
        if isinstance(commonchem_url, str) and commonchem_url:
            profile["commonchemistry_url"] = commonchem_url
        if not profile["preferred_name"]:
            commonchem_name = commonchem.get("name")
            if isinstance(commonchem_name, str) and commonchem_name.strip():
                profile["preferred_name"] = commonchem_name.strip()
        if not profile["formula"]:
            formula = commonchem.get("molecularFormula")
            if isinstance(formula, str) and formula.strip():
                profile["formula"] = formula.strip()
        if not profile["inchi_key"]:
            inchi_key = commonchem.get("inchiKey")
            if isinstance(inchi_key, str) and inchi_key.strip():
                profile["inchi_key"] = inchi_key.strip()

        self.cache[cas] = profile
        return profile


def _fill_from_pubchem_props(profile: dict[str, Any], props: list[dict[str, Any]]) -> None:
    for prop in props:
        urn = prop.get("urn", {})
        label = urn.get("label")
        name = urn.get("name")
        value = prop.get("value", {})
        sval = value.get("sval")
        if label == "InChIKey" and isinstance(sval, str):
            profile["inchi_key"] = sval
        elif label == "Molecular Formula" and isinstance(sval, str):
            profile["formula"] = sval
        elif label == "IUPAC Name" and name == "Preferred" and isinstance(sval, str):
            profile["preferred_name"] = sval
