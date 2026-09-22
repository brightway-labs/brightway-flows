"""Compare every ecoinvent system model's elementary flow list against cutoff.

ecoinvent does not publish one list of elementary flows.  It publishes one per
system model -- `cutoff`, `apos`, `consequential` and `EN15804` -- and the
adapter in :mod:`brightway_flows.integrations.ecoinvent` reads `cutoff`.  Any
flow another release ships and cutoff does not is a flow the project would never
see, so the difference has to be known rather than assumed (#100).

This tool is how it is known.  For each version it reads
`MasterData/ElementaryExchanges.xml` out of all four releases, compares them, and
writes one `ecoinvent-<version>-additional-flows.json` per version recording
what it found -- including, for the four versions where the answer is "nothing",
a file whose `flows` list is empty.  An empty file is the point: without one, a
version nobody has checked and a version checked and found clean look exactly
alike, which is the state #100 was filed about.

What it found when it was last run, on 2026-08-15 against 3.8, 3.9.1, 3.10.1,
3.11 and 3.12:

    3.8       apos and consequential each carry three exchanges cutoff does not
              -- `venting of argon, crude, liquid`, `venting of nitrogen,
              liquid` and `residual wood, dry`, all in `social / unspecified`.
              The same three in both.  EN15804 matches cutoff exactly.
    3.9.1     all four releases identical
    3.10.1    all four releases identical
    3.11      all four releases identical
    3.12      all four releases identical

"Identical" is meant strictly: the same uuids, and every shared exchange record
equal field for field, not merely equal in the handful of fields the adapter
keeps.

Two artefacts of the download cache are normalised away first, and neither is
something ecoinvent ships.  `ecoinvent_interface` rewrites `majorRelease` and
`minorRelease` on extracted master data and re-serialises the file
pretty-printed, so a release read from an extracted cache differs from one read
straight out of its archive in those two attributes and in whitespace-only text
nodes.  Comparing without normalising reports thousands of differing records,
every one of them a `property` block whose whitespace changed.

Downloads are expensive and this is not a build step.  A release already
extracted in the `ecoinvent_interface` cache is read in place.  Anything else is
downloaded as an archive, has the single XML extracted from it, and the archive
is deleted again -- an ecoSpold02 release is ~120 MB compressed and ~3 GB
extracted, and this needs one 17 MB file out of it.  Pass `--keep-downloads` to
leave the archives in the cache.

Usage::

    python tools/compare_ecoinvent_system_models.py
    python tools/compare_ecoinvent_system_models.py --version 3.12 --dry-run

Requires ecoinvent credentials in the `ecoinvent_interface` settings, and `7z`
on the path.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

import xmltodict

from brightway_flows.sources import PACKAGE_DATA_DIR

#: Every system model ecoinvent publishes a release for, cutoff first because it
#: is the one the adapter reads and so the one everything is compared against.
SYSTEM_MODELS = ("cutoff", "apos", "consequential", "EN15804")

#: The versions with a registered source list.  A new manifest belongs here.
VERSIONS = ("3.8", "3.9.1", "3.10.1", "3.11", "3.12")

#: Rewritten by `ecoinvent_interface` on extraction, not by ecoinvent.  Comparing
#: them would report every release read from a cache as differing from every
#: release read from an archive.
CACHE_REWRITTEN_ATTRIBUTES = ("@majorRelease", "@minorRelease")

RELEASE_FILE = "MasterData/ElementaryExchanges.xml"


def _master_data_path(version: str, system_model: str) -> Path | None:
    """An already-extracted release's master data, if one is in the cache."""
    from ecoinvent_interface.storage import CachedStorage

    cache = Path(CachedStorage().dir)
    candidate = (
        cache / f"ecoinvent {version}_{system_model}_ecoSpold02" / "MasterData"
        / "ElementaryExchanges.xml"
    )
    return candidate if candidate.exists() else None


def _download_master_data(
    version: str, system_model: str, destination: Path, *, keep: bool
) -> Path:
    """Fetch *version*'s *system_model* release and keep only the one XML.

    The archive is deleted unless *keep*, and its catalogue entry with it: a
    cache row pointing at a file that is gone makes the next `get_release` hand
    back a path that does not exist.
    """
    from ecoinvent_interface import EcoinventRelease, ReleaseType, Settings
    from ecoinvent_interface.storage import CachedStorage

    release = EcoinventRelease(Settings())
    archive = Path(
        release.get_release(
            version=version,
            system_model=system_model,
            release_type=ReleaseType.ecospold,
            extract=False,
            # Off deliberately: it is the rewriting this module normalises away,
            # and there is no reason to invite it into a file being compared.
            fix_version=False,
        )
    )
    subprocess.run(
        ["7z", "e", "-y", f"-o{destination.parent}", str(archive), RELEASE_FILE],
        check=True,
        capture_output=True,
    )
    (destination.parent / "ElementaryExchanges.xml").rename(destination)
    if not keep:
        archive.unlink()
        CachedStorage().catalogue.pop(archive.name, None)
    return destination


def load_exchanges(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """The exchanges of one master data file by uuid, and its header.

    Whitespace is stripped and the cache-rewritten release attributes dropped,
    so what comes back is what ecoinvent published.
    """
    with open(path) as fs:
        root = xmltodict.parse(fs.read(), strip_whitespace=True)[
            "validElementaryExchanges"
        ]
    exchanges = {obj["@id"]: obj for obj in root["elementaryExchange"]}
    header = {
        key: value
        for key, value in root.items()
        if key != "elementaryExchange" and key not in CACHE_REWRITTEN_ATTRIBUTES
    }
    return exchanges, header


def _describe(
    uuid: str, record: dict[str, Any], models: list[str], version: str
) -> dict[str, Any]:
    """One additional-flow record, in the shape the curated file takes."""
    compartment = record["compartment"]["compartment"]["#text"]
    subcompartment = record["compartment"]["subcompartment"]["#text"]
    identity = ["CAS number" if "@casNumber" not in record else None,
                "synonyms" if "synonym" not in record else None,
                "comment" if "comment" not in record else None]
    absent = [field for field in identity if field]
    if len(absent) > 1:
        absent = [", no ".join(absent[:-1]) + " and no " + absent[-1]]
    nothing_else = (
        f" ecoinvent ships no {''.join(absent)} for it: name, unit and "
        f"'{compartment} / {subcompartment}' is the whole record."
        if absent
        else ""
    )
    return {
        "uuid": uuid,
        "name": record["name"]["#text"],
        "context": [compartment, subcompartment],
        "unit": record["unitName"]["#text"],
        "comment": (
            f"Present in ecoinvent {version}'s {' and '.join(models)} "
            f"MasterData/ElementaryExchanges.xml, absent from the cutoff export "
            f"the adapter reads.{nothing_else}"
        ),
    }


def compare_version(version: str, master_data: dict[str, Path]) -> dict[str, Any]:
    """Compare every system model of *version* against its cutoff release."""
    loaded = {
        model: load_exchanges(path) for model, path in master_data.items()
    }
    cutoff, cutoff_header = loaded["cutoff"]

    counts = {model: len(exchanges) for model, (exchanges, _) in loaded.items()}
    #: uuid -> the models that ship it and cutoff does not.
    extra: dict[str, list[str]] = {}
    only_in_cutoff: dict[str, list[str]] = {}
    differing: dict[str, list[str]] = {}
    #: File-level attributes, kept apart from the exchanges.  A release that
    #: really does carry different flows also carries a different revision
    #: number, and counting that as a differing record would say two records
    #: disagree when none of them do.
    header_differences: dict[str, list[str]] = {}

    for model in SYSTEM_MODELS:
        if model == "cutoff":
            continue
        exchanges, header = loaded[model]
        for uuid in sorted(set(exchanges) - set(cutoff)):
            extra.setdefault(uuid, []).append(model)
        missing = sorted(set(cutoff) - set(exchanges))
        if missing:
            only_in_cutoff[model] = missing
        unequal = [
            uuid
            for uuid in sorted(set(exchanges) & set(cutoff))
            if exchanges[uuid] != cutoff[uuid]
        ]
        if unequal:
            differing[model] = unequal
        keys = sorted(
            key
            for key in set(header) | set(cutoff_header)
            if header.get(key) != cutoff_header.get(key)
        )
        if keys:
            header_differences[model] = keys

    flows = []
    for uuid, models in sorted(extra.items()):
        source_model = models[0]
        flows.append(_describe(uuid, loaded[source_model][0][uuid], models, version))

    return {
        "counts": counts,
        "flows": flows,
        "shipped_by": sorted({model for models in extra.values() for model in models}),
        "only_in_cutoff": only_in_cutoff,
        "differing": differing,
        "header_differences": header_differences,
    }


def _description(version: str, result: dict[str, Any]) -> str:
    counts = result["counts"]
    tally = ", ".join(f"{model} {counts[model]:,}" for model in SYSTEM_MODELS)
    if not result["flows"]:
        return (
            f"Nothing to add: ecoinvent {version} ships the same elementary "
            f"exchanges in all four of its system models. Compared release by "
            f"release from each one's MasterData/ElementaryExchanges.xml -- "
            f"{tally} exchanges -- with the same uuids throughout and every "
            f"shared record equal field for field, not merely in the fields the "
            f"adapter keeps. This file exists so that a version nobody has "
            f"checked and a version checked and found clean do not look alike: "
            f"the empty list is the finding. Regenerate with "
            f"tools/compare_ecoinvent_system_models.py. See #100."
        )
    shipped_by = result["shipped_by"]
    clean = [
        model
        for model in SYSTEM_MODELS
        if model != "cutoff" and model not in shipped_by
    ]
    clean_note = (
        f" {' and '.join(clean)} "
        f"{'matches' if len(clean) == 1 else 'match'} cutoff exactly."
        if clean
        else ""
    )
    return (
        f"Elementary exchanges ecoinvent {version} ships in a system model the "
        f"adapter does not read. Appended to the fetched flows before manual "
        f"fixes and before matching. Compared release by release from each "
        f"system model's MasterData/ElementaryExchanges.xml -- {tally} "
        f"exchanges. {' and '.join(shipped_by)} carry the "
        f"{len(result['flows'])} flows below and cutoff does not; no flow is "
        f"only in cutoff, and every shared record is equal field for field."
        f"{clean_note} Regenerate with "
        f"tools/compare_ecoinvent_system_models.py. See #25 and #100."
    )


def build_payload(version: str, result: dict[str, Any], *, on: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "source_version": version,
        "description": _description(version, result),
        "comparison": {
            "compared_on": on,
            "reference_system_model": "cutoff",
            "system_models": list(SYSTEM_MODELS),
            "release_type": f"ecoSpold02 {RELEASE_FILE}",
            "exchange_counts": result["counts"],
            "flows_only_in_another_system_model": len(result["flows"]),
            "flows_only_in_cutoff": sum(
                len(uuids) for uuids in result["only_in_cutoff"].values()
            ),
            "shared_records_differing": sum(
                len(uuids) for uuids in result["differing"].values()
            ),
            "file_attributes_differing": result["header_differences"],
        },
        "flows": result["flows"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--version", action="append", dest="versions", choices=VERSIONS,
        help="Compare only this version; repeatable. Default: all of them.",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=PACKAGE_DATA_DIR,
        help="Where the additional-flows files are written.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Report what was found and write nothing.",
    )
    parser.add_argument(
        "--keep-downloads", action="store_true",
        help="Leave downloaded release archives in the ecoinvent_interface cache.",
    )
    args = parser.parse_args(argv)
    versions = args.versions or list(VERSIONS)
    today = date.today().isoformat()

    exit_code = 0
    with tempfile.TemporaryDirectory() as scratch:
        for version in versions:
            master_data: dict[str, Path] = {}
            for model in SYSTEM_MODELS:
                cached = _master_data_path(version, model)
                if cached is not None:
                    print(f"{version} {model}: reading extracted cache")
                    master_data[model] = cached
                    continue
                print(f"{version} {model}: downloading release")
                master_data[model] = _download_master_data(
                    version, model,
                    Path(scratch) / f"{version}_{model}.xml",
                    keep=args.keep_downloads,
                )

            result = compare_version(version, master_data)
            counts = result["counts"]
            print(f"  ecoinvent {version}: " + ", ".join(
                f"{model} {counts[model]}" for model in SYSTEM_MODELS
            ))
            for flow in result["flows"]:
                print(f"    + {flow['uuid']} {flow['name']!r} "
                      f"{flow['context']} {flow['unit']}")
            for model, uuids in result["only_in_cutoff"].items():
                # Not something this file can express: a flow cutoff has and
                # another release does not is already in the list.  Reported so
                # it is not silently dropped.
                print(f"    ! {len(uuids)} flow(s) in cutoff but not {model}")
                exit_code = 1
            for model, uuids in result["differing"].items():
                print(f"    ! {len(uuids)} shared record(s) differ between "
                      f"cutoff and {model}")
                exit_code = 1

            payload = build_payload(version, result, on=today)
            destination = args.output_dir / f"ecoinvent-{version}-additional-flows.json"
            if args.dry_run:
                print(f"    would write {destination}")
                continue
            destination.write_text(json.dumps(payload, indent=2) + "\n")
            print(f"    wrote {destination}")

    if exit_code:
        print(
            "\nSomething the additional-flows mechanism cannot express was found. "
            "A flow only cutoff has, or a shared record whose fields disagree, is "
            "a difference between releases that adding rows will not settle -- it "
            "needs a decision about which release the project should be reading.",
            file=sys.stderr,
        )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
