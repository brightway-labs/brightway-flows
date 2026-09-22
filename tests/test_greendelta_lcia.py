"""EF 3.1 as GreenDelta implements it, and what is checked at ingest.

The third implementation of a method this list holds, and the second that is not
the method's own publisher's.  Every number below is measured against
`bafu-greendelta-lcia.zip` -- BAFU's openLCA distribution of `openLCA LCIA
methods 2.8.0`, digest `c7c98b84…7e6f` -- and the point of asserting them in the
adapter rather than recording them once is that each is a fact about a package:

* its 25 categories are addressed by the JRC's own ILCD method-file UUIDs, so a
  factor of theirs is filed under one of our categories by identity and not by a
  name nobody could derive (`Ecotoxicity freshwater (organics)`);
* 26,179 factors over 1,781 flows, no ``(category, flow, location)`` stated
  twice, so nothing silently wins;
* every factor is stated per its flow's own reference unit, so no conversion is
  needed that the merge did not already record;
* 20,332 of the rows carry a location, and every location the package ships has
  a code -- which is the spelling `StatedFactor.geography` holds and what makes
  a regionalised row of theirs comparable with the JRC's.

The archive is not in the repository, so the cases that need one build a small
stand-in.  The ones at the end read what a real fetch wrote, and skip where
nothing has.
"""

from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

import orjson

from brightway_flows.domain.lcia.crosswalk import ef_method
from brightway_flows.integrations.greendelta_lcia import (
    FACTORS_SCHEMA_VERSION,
    GREENDELTA_LCIA_SHA256,
    GREENDELTA_LCIA_URL,
    GreenDeltaLciaError,
    _check_categories,
    _factors,
    fetch,
    with_the_pairs_sign,
    flow_descriptions,
    load_factors,
    read_package,
)
from brightway_flows.sources import (
    LciaMethodSpec,
    LciaSpec,
    SourceList,
    known_source_lists,
)

#: EF 3.1's implementations, read from its method file rather than from an enum:
#: an implementation belongs to a method, and which four these are is what
#: `data/lcia-impact-categories.json` says.
_METHOD = ef_method()
JRC_IMPL = _METHOD.reference
ECOINVENT_IMPL = _METHOD.implementation("ecoinvent-centre")
GREENDELTA_IMPL = _METHOD.implementation("greendelta")
CONSENSUS_IMPL = _METHOD.consensus
IMPLEMENTATION_NAMES = {row.name for row in _METHOD.implementations}

#: What their package calls the method, read from the row that reads it: the
#: word "adapted" is theirs, and the method file is where this list records that
#: it is reading a method under that name rather than under EF 3.1's own.
GREENDELTA_METHOD_NAME = GREENDELTA_IMPL.factors.stated_method

#: A category identifier the crosswalk knows, and the name GreenDelta gives it.
FIRST = sorted(ef_method().by_stated_identifier("jrc"))[0]

KG = {"@type": "Unit", "@id": "u-kg", "name": "kg"}
MASS = {"@type": "FlowProperty", "@id": "fp-mass", "name": "Mass"}


def _flow(uuid: str, name: str, category: str, unit: str = "kg") -> dict:
    return {
        "@type": "Flow",
        "@id": uuid,
        "name": name,
        "category": category,
        "flowType": "ELEMENTARY_FLOW",
        "refUnit": unit,
        "cas": "",
    }


def _factor(flow: dict, value: float, location: str | None = None) -> dict:
    row = {
        "value": value,
        "flow": flow,
        "unit": KG,
        "flowProperty": MASS,
    }
    if location is not None:
        row["location"] = {"@type": "Location", "@id": location, "name": location}
    return row


def _package(
    tmp: Path,
    *,
    categories: list[dict],
    flows: list[dict],
    locations: list[dict] | None = None,
    methods: list[dict] | None = None,
) -> Path:
    """An openLCA JSON-LD archive holding exactly what a case needs."""
    path = tmp / "package.zip"
    method = {
        "@type": "ImpactMethod",
        "@id": "m-1",
        "name": GREENDELTA_METHOD_NAME,
        "category": "openLCA LCIA Methods 2.8.0 adapted",
        "version": "00.00.037",
    }
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("openlca.json", json.dumps({"schemaVersion": 5}))
        for entry in methods if methods is not None else [method]:
            archive.writestr(
                f"lcia_methods/{entry['@id']}.json", json.dumps(entry)
            )
        for entry in categories:
            archive.writestr(
                f"lcia_categories/{entry['@id']}.json", json.dumps(entry)
            )
        for entry in flows:
            archive.writestr(f"flows/{entry['@id']}.json", json.dumps(entry))
        for entry in locations or []:
            archive.writestr(
                f"locations/{entry['@id']}.json", json.dumps(entry)
            )
    return path


class ReadingThePackageTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.flow = _flow(
            "f-1", "Ammonia", "Elementary flows/Emission to air/unspecified"
        )
        self.category = {
            "@type": "ImpactCategory",
            "@id": FIRST,
            "name": ef_method().by_stated_identifier("jrc")[FIRST].stated["greendelta"].name,
            "refUnit": "mol H+ eq",
            "description": "what the category is",
            "impactFactors": [_factor(self.flow, 1.5)],
        }

    def tearDown(self):
        self.tmp.cleanup()

    def _read(self, **kwargs):
        path = _package(
            self.root,
            categories=kwargs.pop("categories", [self.category]),
            flows=kwargs.pop("flows", [self.flow]),
            **kwargs,
        )
        return path, read_package(path)

    def test_a_package_is_its_method_its_categories_and_its_flows(self):
        _path, package = self._read()
        self.assertEqual(package.method_name, GREENDELTA_METHOD_NAME)
        self.assertEqual(len(package.categories), 1)
        self.assertEqual(sorted(package.flows), ["f-1"])

    def test_two_methods_is_not_this_package(self):
        """Picking the first would publish half an implementation under the
        other's name."""
        second = {"@type": "ImpactMethod", "@id": "m-2", "name": "something else"}
        first = {"@type": "ImpactMethod", "@id": "m-1", "name": GREENDELTA_METHOD_NAME}
        with self.assertRaises(GreenDeltaLciaError):
            self._read(methods=[first, second])

    def test_a_factor_is_the_number_the_flow_and_the_category(self):
        path, package = self._read()
        factors, described = _factors(package, path=path)
        self.assertEqual(len(factors), 1)
        factor = factors[0]
        self.assertEqual(factor.amount, 1.5)
        self.assertEqual(factor.flow_uuid, "f-1")
        self.assertIsNone(factor.geography)
        # The identity that files it under one of ours, and the name that is
        # theirs alone.
        self.assertEqual(factor.category.uuid, FIRST)
        self.assertEqual(
            factor.category.name, ef_method().by_stated_identifier("jrc")[FIRST].stated["greendelta"].name
        )
        self.assertEqual(factor.category.methodology, GREENDELTA_METHOD_NAME)
        self.assertEqual(described["f-1"]["name"], "Ammonia")
        self.assertEqual(described["f-1"]["unit"], "kg")

    def test_a_place_is_the_location_s_code_and_not_its_name(self):
        """`CH`, not `Switzerland`: the code is the spelling every other
        implementation's geography is in."""
        self.category["impactFactors"] = [_factor(self.flow, 1.5, location="l-ch")]
        path, package = self._read(
            locations=[
                {"@type": "Location", "@id": "l-ch", "name": "Switzerland",
                 "code": "CH"}
            ]
        )
        factors, _described = _factors(package, path=path)
        self.assertEqual(factors[0].geography, "CH")

    def test_a_location_with_no_code_stops_the_read(self):
        """A regionalised factor with no place is not comparable with
        anybody's."""
        self.category["impactFactors"] = [_factor(self.flow, 1.5, location="l-ch")]
        path, package = self._read(
            locations=[{"@type": "Location", "@id": "l-ch", "name": "Switzerland"}]
        )
        with self.assertRaises(GreenDeltaLciaError):
            _factors(package, path=path)

    def test_a_factor_in_another_unit_than_its_flow_stops_the_read(self):
        row = _factor(self.flow, 1.5)
        row["unit"] = {"@type": "Unit", "@id": "u-g", "name": "g"}
        self.category["impactFactors"] = [row]
        path, package = self._read()
        with self.assertRaises(GreenDeltaLciaError):
            _factors(package, path=path)

    def test_one_flow_stated_twice_in_a_category_stops_the_read(self):
        """Two numbers for one (category, flow, place) means one of them wins
        without anybody choosing."""
        self.category["impactFactors"] = [
            _factor(self.flow, 1.5),
            _factor(self.flow, 3.0),
        ]
        path, package = self._read()
        with self.assertRaises(GreenDeltaLciaError):
            _factors(package, path=path)

    def test_the_same_flow_in_two_places_is_two_factors(self):
        self.category["impactFactors"] = [
            _factor(self.flow, 1.5, location="l-ch"),
            _factor(self.flow, 2.5, location="l-at"),
        ]
        path, package = self._read(
            locations=[
                {"@type": "Location", "@id": "l-ch", "name": "Switzerland",
                 "code": "CH"},
                {"@type": "Location", "@id": "l-at", "name": "Austria",
                 "code": "AT"},
            ]
        )
        factors, _described = _factors(package, path=path)
        self.assertEqual(
            {factor.geography: factor.amount for factor in factors},
            {"CH": 1.5, "AT": 2.5},
        )

    def test_a_category_the_crosswalk_does_not_know_stops_the_read(self):
        """Their package carries the JRC's own UUIDs; one that does not needs a
        join written before its factors mean anything."""
        self.category["@id"] = "not-a-category-of-ours"
        path, package = self._read()
        with self.assertRaises(GreenDeltaLciaError):
            _check_categories(package, path=path)


class WhatTheFetchWritesTestCase(unittest.TestCase):
    """The file, and that it reads back as the records it was written from."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        flow = _flow(
            "f-1", "Ammonia", "Elementary flows/Emission to air/unspecified"
        )
        category = {
            "@type": "ImpactCategory",
            "@id": FIRST,
            "name": ef_method().by_stated_identifier("jrc")[FIRST].stated["greendelta"].name,
            "refUnit": "mol H+ eq",
            "impactFactors": [_factor(flow, 1.5, location="l-ch")],
        }
        self.archive = _package(
            self.root,
            categories=[category],
            flows=[flow],
            locations=[
                {"@type": "Location", "@id": "l-ch", "name": "Switzerland",
                 "code": "CH"}
            ],
        )
        self.factors_path = self.root / "factors.json"
        self.source = SourceList(
            list_name="bafu",
            list_version="2026-v1",
            flows_path=self.root / "flows.json",
            lcia=LciaSpec(
                adapter="brightway_flows.integrations.greendelta_lcia:fetch",
                factors_path=self.factors_path,
                methods=(LciaMethodSpec(name=GREENDELTA_METHOD_NAME),),
                implemented_by="GreenDelta",
            ),
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _fetch(self):
        import brightway_flows.integrations.greendelta_lcia as module

        original = module.greendelta_lcia_zip_path
        module.greendelta_lcia_zip_path = lambda: self.archive
        try:
            return fetch(self.source)
        finally:
            module.greendelta_lcia_zip_path = original

    def test_it_writes_the_records_and_says_what_it_read(self):
        path = self._fetch()
        payload = orjson.loads(path.read_bytes())
        self.assertEqual(payload["schema_version"], FACTORS_SCHEMA_VERSION)
        self.assertEqual(payload["source"], "bafu-2026-v1")
        self.assertEqual(payload["archive"], self.archive.name)
        self.assertEqual(len(payload["archive_sha256"]), 64)
        self.assertEqual(payload["package_version"], "00.00.037")
        method = payload["methods"][0]
        self.assertEqual(method["method"], GREENDELTA_METHOD_NAME)
        self.assertEqual(method["factor_count"], 1)
        self.assertEqual(method["flow_count"], 1)

    def test_the_file_reads_back_as_what_was_written(self):
        path = self._fetch()
        factors = load_factors(path)[GREENDELTA_METHOD_NAME]
        self.assertEqual(len(factors), 1)
        self.assertEqual(factors[0].amount, 1.5)
        self.assertEqual(factors[0].geography, "CH")
        self.assertEqual(factors[0].category.uuid, FIRST)
        self.assertEqual(flow_descriptions(path)["f-1"]["name"], "Ammonia")

    def test_a_file_from_another_schema_is_not_read(self):
        self.factors_path.write_bytes(
            orjson.dumps({"schema_version": 99, "methods": []})
        )
        with self.assertRaises(GreenDeltaLciaError):
            load_factors(self.factors_path)

    def test_a_package_shipping_another_method_stops_the_fetch(self):
        """The manifest declares which method is ingested; a package that ships
        a different one is not the artifact it was declared for."""
        source = SourceList(
            list_name="bafu",
            list_version="2026-v1",
            flows_path=self.root / "flows.json",
            lcia=LciaSpec(
                adapter="brightway_flows.integrations.greendelta_lcia:fetch",
                factors_path=self.factors_path,
                methods=(LciaMethodSpec(name="EF 3.1"),),
                implemented_by="GreenDelta",
            ),
        )
        self.source = source
        with self.assertRaises(GreenDeltaLciaError):
            self._fetch()


class TheManifestDeclaresItTestCase(unittest.TestCase):
    def test_bafu_declares_greendelta_s_implementation(self):
        source = known_source_lists()["bafu-2026-v1"]
        self.assertIsNotNone(source.lcia)
        self.assertEqual(source.lcia.implemented_by, GREENDELTA_IMPL.name)
        self.assertEqual(
            [method.name for method in source.lcia.methods],
            [GREENDELTA_METHOD_NAME],
        )
        self.assertEqual(
            source.lcia.factors_path.name, "bafu-greendelta-lcia-factors.json"
        )

    def test_it_is_resolved_through_ecoinvent_newest_first(self):
        """Their package names flows by the ecoinvent UUID it was built against,
        and a UUID ecoinvent has reused means the later release's substance."""
        source = known_source_lists()["bafu-2026-v1"]
        self.assertEqual(
            source.lcia.resolve_through,
            ("ecoinvent-3.12", "ecoinvent-3.8", "EF-3.1"),
        )

    def test_every_list_it_resolves_through_is_registered(self):
        from brightway_flows.lcia.sources import registered_lists

        registry = registered_lists()
        for key in known_source_lists()["bafu-2026-v1"].lcia.resolve_through:
            with self.subTest(key):
                self.assertIn(key, registry)

    def test_the_adapter_it_names_is_importable(self):
        from brightway_flows.sources import load_adapter

        source = known_source_lists()["bafu-2026-v1"]
        self.assertTrue(
            callable(load_adapter(source, dotted_path=source.lcia.adapter))
        )

    def test_the_archive_is_named_and_pinned(self):
        """BAFU hands the distribution over rather than publishing it, so this
        project hosts the copy it read and states which bytes those are."""
        self.assertTrue(GREENDELTA_LCIA_URL.startswith("https://"))
        self.assertEqual(len(GREENDELTA_LCIA_SHA256), 64)


class WhatAFetchWroteTestCase(unittest.TestCase):
    """The measured numbers, against a file a real fetch produced.

    Skipped where nothing has fetched: `fetch-lcia bafu-2026-v1` downloads a
    9.6 MB archive and no test may do that.
    """

    def setUp(self):
        source = known_source_lists()["bafu-2026-v1"]
        self.path = source.lcia.factors_path
        if not self.path.exists():
            self.skipTest(f"{self.path} has not been fetched here")
        self.payload = orjson.loads(self.path.read_bytes())
        self.method = self.payload["methods"][0]

    def test_the_package_it_was_read_from(self):
        self.assertEqual(
            self.payload["archive_sha256"], GREENDELTA_LCIA_SHA256
        )
        self.assertEqual(self.method["method"], GREENDELTA_METHOD_NAME)

    def test_twenty_six_thousand_factors_over_one_thousand_flows(self):
        self.assertEqual(self.method["factor_count"], 26179)
        self.assertEqual(self.method["flow_count"], 1781)
        self.assertEqual(len(self.method["categories"]), 25)

    def test_the_regionalised_rows(self):
        """Land use and water use are stated per country, and that is most of
        the file: 20,332 of 26,179."""
        placed = [row for row in self.method["factors"] if row["geography"]]
        self.assertEqual(len(placed), 20332)
        self.assertEqual(len({row["geography"] for row in placed}), 223)

    def test_every_category_is_addressed_by_the_jrc_s_uuid(self):
        known = ef_method().by_stated_identifier("jrc")
        for row in self.method["categories"]:
            with self.subTest(row["category"]):
                self.assertIn(row["category_uuid"], known)
                self.assertEqual(
                    known[row["category_uuid"]].stated["greendelta"].name, row["category"]
                )


#: EF 3.1's `Water use`, by the JRC method-file UUID GreenDelta's package keeps.
#: The one category EF states as a pair, so the one where the flow's direction
#: decides the sign.
WATER_USE = "b2ad66ce-c78d-11e6-9d9d-cec0c932ce01"


class ThePairsSignTestCase(unittest.TestCase):
    """#172: the half of EF's water-use pair GreenDelta ships without its sign.

    Taking a cubic metre of water out of a French river costs +6.98 and putting
    one back is -6.98, so a process that withdraws and returns the same water
    scores about nothing.  Their package states both halves positive, and the
    magnitudes are the JRC's to the digit -- so what is missing is the sign,
    which is not on the factor at all: it is the direction of the flow, and
    openLCA states that in the flow's own category path.
    """

    def test_a_withdrawal_keeps_its_sign(self):
        self.assertEqual(
            with_the_pairs_sign(
                6.98,
                category_slug="water-use",
                flow_category="Elementary flows/Resource/in water",
            ),
            6.98,
        )

    def test_a_return_to_water_is_negated(self):
        self.assertEqual(
            with_the_pairs_sign(
                6.98,
                category_slug="water-use",
                flow_category="Elementary flows/Emission to water/river",
            ),
            -6.98,
        )

    def test_a_return_already_signed_is_left_alone(self):
        """It states the convention; it does not negate a number for having
        disagreed.  A package that fixed this upstream must read the same."""
        self.assertEqual(
            with_the_pairs_sign(
                -6.98,
                category_slug="water-use",
                flow_category="Elementary flows/Emission to water/river",
            ),
            -6.98,
        )

    def test_water_evaporated_to_air_keeps_its_sign(self):
        """The reason the rule names emissions *to water* rather than emissions.
        Water vapour is a loss from the catchment and counts positively -- the
        ecoinvent Centre states +42.95 for it in every air compartment."""
        self.assertEqual(
            with_the_pairs_sign(
                42.95,
                category_slug="water-use",
                flow_category="Elementary flows/Emission to air/unspecified",
            ),
            42.95,
        )

    def test_no_other_category_is_touched(self):
        """`Land use` is the one that looks like a pair and is not: `from
        forest` and `to forest` are two flows, both resources, so the minus sign
        is on the flow and GreenDelta's 5,733 negative land-use factors are
        right as they stand."""
        for slug in ("land-use", "climate-change", "acidification"):
            with self.subTest(slug=slug):
                self.assertEqual(
                    with_the_pairs_sign(
                        1.0,
                        category_slug=slug,
                        flow_category="Elementary flows/Emission to water/river",
                    ),
                    1.0,
                )

    def test_a_stated_zero_stays_zero(self):
        """A zero is a statement that the flow does not contribute, and -0.0 is
        the same number written in a way that reads as a sign."""
        self.assertEqual(
            with_the_pairs_sign(
                0.0,
                category_slug="water-use",
                flow_category="Elementary flows/Emission to water/river",
            ),
            0.0,
        )


class ReadingWaterUseTestCase(unittest.TestCase):
    """The rule where the reader applies it, over a package holding the pair."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.withdrawal = _flow(
            "f-in", "Water, FR", "Elementary flows/Resource/in water", unit="m3"
        )
        self.returned = _flow(
            "f-out", "Water, FR", "Elementary flows/Emission to water/river", unit="m3"
        )
        self.name = (
            ef_method().by_stated_identifier("jrc")[WATER_USE].stated["greendelta"].name
        )

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def _cubic_metres(flow, value):
        """`_factor` states kilograms; a water row is per cubic metre, and the
        reader refuses a factor stated in anything but its flow's own unit."""
        row = _factor(flow, value)
        row["unit"] = {"@type": "Unit", "@id": "u-m3", "name": "m3"}
        return row

    def _factors_of(self, rows):
        category = {
            "@type": "ImpactCategory",
            "@id": WATER_USE,
            "name": self.name,
            "refUnit": "m3 world eq",
            "description": "water use",
            "impactFactors": rows,
        }
        path = _package(
            self.root,
            categories=[category],
            flows=[self.withdrawal, self.returned],
        )
        package = read_package(path)
        _check_categories(package, path=path)
        factors, _described = _factors(package, path=path)
        return {factor.flow_uuid: factor.amount for factor in factors}

    def test_the_pair_comes_back_as_a_pair(self):
        amounts = self._factors_of([
            self._cubic_metres(self.withdrawal, 6.98),
            self._cubic_metres(self.returned, 6.98),
        ])
        self.assertEqual(amounts["f-in"], 6.98)
        self.assertEqual(amounts["f-out"], -6.98)
        # The whole point of the pair, stated as the arithmetic a reader does:
        # withdraw a cubic metre, give it back, score nothing.
        self.assertEqual(amounts["f-in"] + amounts["f-out"], 0.0)

    def test_the_magnitude_is_never_touched(self):
        amounts = self._factors_of([self._cubic_metres(self.returned, 0.04295)])
        self.assertEqual(abs(amounts["f-out"]), 0.04295)
