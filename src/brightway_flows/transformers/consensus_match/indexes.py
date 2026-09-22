"""The source tables matching votes over, loaded once per run.

ChEBI, the EC inventory and PubChem, each indexed both ways -- names for a CAS
and CAS for a name -- because a vote is taken in both directions.  The tables
are read-only once loaded; everything derived from them lives elsewhere.

The PubChem side carries one piece of judgement rather than being a plain
index: which compound a CAS actually denotes when several cross-reference it.
That is here rather than with the profiles because it is answered from the
tables alone, and because `compound_primary_cas_by_cid`, the map it turns on,
is built while the tables are read.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import orjson

from brightway_flows.filesystem import PUBCHEM_DATA_FILEPATH
from brightway_flows.integrations.chebi import load_chebi_index
from brightway_flows.integrations.ec_inventory import load_ec_inventory
from brightway_flows.pipeline import normalize
from brightway_flows.transformers.consensus_match.naming import normalize_chebi_id


def identifier_values(id_map: dict[str, Any], heading: str) -> list[str]:
    out: list[str] = []
    for item in id_map.get(heading, []):
        value = item.get("value")
        if isinstance(value, str):
            out.append(value)
    return out


def first_identifier_value(id_map: dict[str, Any], heading: str) -> str | None:
    vals = identifier_values(id_map, heading)
    return vals[0] if vals else None


@dataclass
class SourceIndexes:
    """ChEBI, EC-inventory and PubChem tables, indexed for matching."""

    chebi_records: dict[str, dict[str, Any]] = field(default_factory=dict)
    chebi_by_name: dict[str, list[str]] = field(default_factory=dict)
    chebi_by_cas: dict[str, list[str]] = field(default_factory=dict)

    ec_names_by_cas: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    ec_cas_by_name: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))

    pubchem_names_by_cas: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    pubchem_cas_by_name: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    pubchem_by_cas: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    pubchem_identifiers_by_cid: dict[str, dict[str, Any]] = field(default_factory=dict)
    pubchem_primary_compound_by_cas: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: CID → the compound's own primary CAS (first entry in its identifiers).
    #: Used to disambiguate when multiple compounds share a CAS: prefer the compound
    #: whose primary CAS matches the queried CAS.  PubChem sometimes links a CAS to
    #: compounds whose real identity is a different substance (e.g. CID 23969 / arsane
    #: appears under CAS 7440-38-2 / arsenic element, but its own primary CAS is
    #: 7784-42-1 / arsine).
    compound_primary_cas_by_cid: dict[int, str] = field(default_factory=dict)

    def load(self) -> None:
        """Fill the tables from disk, in place.

        In place rather than returning a new instance: the collaborators that
        read these tables are wired to one object when the transformer is
        constructed, and `setup()` runs after that.
        """
        chebi = load_chebi_index()
        self.chebi_records = chebi["records"]
        self.chebi_by_name = chebi["by_name"]
        self.chebi_by_cas = chebi["by_cas"]

        ec_data = load_ec_inventory()
        for rec in ec_data.get("records", []):
            name = rec.get("name")
            cas = rec.get("cas_number")
            if isinstance(name, str) and name.strip():
                nname = normalize(name)
                if cas:
                    self.ec_cas_by_name[nname].add(cas)
            if cas and isinstance(name, str) and name.strip():
                self.ec_names_by_cas[cas].add(name.strip())

        if PUBCHEM_DATA_FILEPATH.exists():
            self._load_pubchem()

    def _load_pubchem(self) -> None:
        pubchem = orjson.loads(PUBCHEM_DATA_FILEPATH.read_bytes())
        self.pubchem_by_cas = pubchem.get("by_cas", {})
        cid_to_names: dict[int, set[str]] = defaultdict(set)
        cid_to_cas: dict[int, set[str]] = defaultdict(set)
        self.pubchem_identifiers_by_cid = pubchem.get("identifiers", {})

        # Build compound → primary CAS mapping.  A compound's primary CAS is the
        # first CAS listed in its own identifiers record — i.e., the CAS that
        # PubChem considers the authoritative identifier for that structure.  This
        # is used in disambiguated_pubchem_compound to prefer the compound that
        # "owns" the queried CAS rather than a compound that merely cross-references
        # it.  For example CID 23969 (arsane, AsH3) cross-references CAS 7440-38-2
        # (arsenic element) but its primary CAS is 7784-42-1 — so it should not be
        # selected when looking up arsenic.
        for cid_str, id_map in self.pubchem_identifiers_by_cid.items():
            try:
                cid = int(cid_str)
            except (TypeError, ValueError):
                continue
            cas_items = id_map.get("CAS", [])
            if cas_items and isinstance(cas_items[0], dict):
                primary_cas = cas_items[0].get("value")
                if isinstance(primary_cas, str) and primary_cas.strip():
                    self.compound_primary_cas_by_cid[cid] = primary_cas.strip()

        for pname, compounds in pubchem.get("by_name", {}).items():
            if not isinstance(pname, str):
                continue
            for compound in compounds:
                cid = compound.get("cid")
                if isinstance(cid, int):
                    cid_to_names[cid].add(pname)

        for cas, compounds in pubchem.get("by_cas", {}).items():
            if not isinstance(cas, str):
                continue
            if compounds:
                self.pubchem_primary_compound_by_cas[cas] = compounds[0]
            for compound in compounds:
                cid = compound.get("cid")
                if isinstance(cid, int):
                    cid_to_cas[cid].add(cas)

        # Only propagate a compound's names to CAS numbers where that compound's
        # primary CAS matches.  Without this guard, a compound associated with
        # multiple CAS numbers (e.g. CID 5359596 / arsenic linked to both
        # 7440-38-2 and 7784-42-1) would inject its names into unrelated CAS
        # pools and cause wrong name candidates for those substances.
        for cid, names in cid_to_names.items():
            primary_cas = self.compound_primary_cas_by_cid.get(cid)
            for cas in cid_to_cas.get(cid, set()):
                if primary_cas and primary_cas != cas:
                    # This CAS is a secondary cross-reference; don't pollute its
                    # name pool.  Still populate the reverse map so identity
                    # resolution can find the canonical CAS for a given name.
                    for name in names:
                        self.pubchem_cas_by_name[normalize(name)].add(cas)
                    continue
                self.pubchem_names_by_cas[cas].update(names)
                for name in names:
                    self.pubchem_cas_by_name[normalize(name)].add(cas)

    # ------------------------------------------------------------------
    # PubChem compound identity

    def compound_chebi_ids(self, cid: int) -> set[str]:
        out: set[str] = set()
        id_map = self.pubchem_identifiers_by_cid.get(str(cid), {})
        if not isinstance(id_map, dict):
            return out
        for item in id_map.get("ChEBI ID", []):
            if not isinstance(item, dict):
                continue
            value = item.get("value")
            if isinstance(value, str):
                normalized = normalize_chebi_id(value)
                if normalized:
                    out.add(normalized)
        return out

    def disambiguated_pubchem_compound(self, cas: str) -> dict[str, Any] | None:
        compounds = [
            c for c in self.pubchem_by_cas.get(cas, [])
            if isinstance(c, dict) and isinstance(c.get("cid"), int)
        ]
        if not compounds:
            return None
        if len(compounds) == 1:
            return compounds[0]

        # Strategy 1: ChEBI cross-reference.  If ChEBI lists specific CAS → ChEBI ID
        # mappings, use them to pick the compound whose CID also has that ChEBI ID.
        chebi_ids_for_cas = {
            normalize_chebi_id(chebi_id)
            for chebi_id in self.chebi_by_cas.get(cas, [])
            if isinstance(chebi_id, str) and chebi_id.strip()
        }
        if chebi_ids_for_cas:
            matched = [
                c for c in compounds
                if self.compound_chebi_ids(c["cid"]).intersection(chebi_ids_for_cas)
            ]
            if len(matched) == 1:
                return matched[0]

        # Strategy 2: primary CAS matching.  Each PubChem compound has a canonical
        # primary CAS (the first CAS in its own identifiers).  Prefer the compound
        # whose primary CAS is the CAS being queried — it "owns" this CAS — over
        # compounds that merely cross-reference it.  This correctly handles cases like
        # CAS 7440-38-2 (arsenic): CID 23969 (arsane) cross-references it but its
        # primary CAS is 7784-42-1, while CID 5359596 (arsenic) has 7440-38-2 as
        # primary.
        primary_matched = [
            c for c in compounds
            if self.compound_primary_cas_by_cid.get(c["cid"]) == cas
        ]
        if len(primary_matched) == 1:
            return primary_matched[0]

        return None
