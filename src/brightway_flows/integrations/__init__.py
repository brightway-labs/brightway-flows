"""External source integrations and network/data adapters.

A source list's adapter is *not* re-exported here.  A manifest names it by
dotted path -- `brightway_flows.integrations.ecoinvent:fetch` -- so an alias
in this module would be a second name for the thing the manifest points at, and
the two `fetch`es would collide anyway.  `get_ecoinvent_release` was exported
until #15 and is gone with the command that called it.
"""

from brightway_flows._lazy import lazy_exports

#: Each name and the module it lives in, imported when the name is first used:
#: reading the ChEBI index should not import the EF 3.1 and PubChem fetchers.
_EXPORTS = {
    "download_ef31": "ef31",
    "extract_flow_data": "ef31",
    "extract_flow_property_values": "ef31",
    "find_ilcd_root": "ef31",
    "load_flow_properties": "ef31",
    "load_lcia_methods": "ef31",
    "zip_xml_paths": "ef31",
    "fetch_and_store_pubchem": "pubchem",
    "load_chebi_index": "chebi",
    "load_ec_inventory": "ec_inventory",
}

__getattr__, __dir__ = lazy_exports(__name__, _EXPORTS)

__all__ = sorted(_EXPORTS)
