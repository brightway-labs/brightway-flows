"""External source integrations and network/data adapters.

A source list's adapter is *not* re-exported here.  A manifest names it by
dotted path -- `brightway_flows.integrations.ecoinvent:fetch` -- so an alias
in this module would be a second name for the thing the manifest points at, and
the two `fetch`es would collide anyway.  `get_ecoinvent_release` was exported
until #15 and is gone with the command that called it.
"""

from brightway_flows.integrations.chebi import load_chebi_index
from brightway_flows.integrations.ec_inventory import load_ec_inventory
from brightway_flows.integrations.ef31 import (
    download_ef31,
    extract_flow_data,
    extract_flow_property_values,
    find_ilcd_root,
    load_flow_properties,
    load_lcia_methods,
    zip_xml_paths,
)
from brightway_flows.integrations.pubchem import fetch_and_store_pubchem

__all__ = [
    "download_ef31",
    "extract_flow_data",
    "extract_flow_property_values",
    "find_ilcd_root",
    "load_flow_properties",
    "load_lcia_methods",
    "zip_xml_paths",
    "fetch_and_store_pubchem",
    "load_chebi_index",
    "load_ec_inventory",
]
