"""Reading elementary flows out of BAFU's ecoSpold v1 process datasets (#4).

BAFU does not distribute a flow list. It distributes 11,947 process datasets,
and the elementary flows are exchanges inside them, repeated once per process
that uses them -- 293,747 exchanges naming 2,679 distinct flows. Everything
here is about that collapse being correct: which exchanges count, what makes
two of them the same flow, and what survives the merge of their fields.

The vendor archive is not checked in -- it is 38 MB and BAFU hands it over
rather than publishing it -- so these run against a fixture built to carry each
shape the real data has.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

import orjson

from brightway_flows.context_mapping import (
    MANUAL_MAPPING_FILEPATH,
    AmbiguousSourceContextError,
    context_iri_by_source_context,
    flow_context_iri,
    name_prefix_context_iri,
    normalize_context_key,
)
from brightway_flows.domain.flow import Flow
from brightway_flows.domain.units import build_units_index, resolve_unit_notation
from brightway_flows.integrations.bafu import (
    _flow_uuid,
    extract_elementary_flows,
)
from brightway_flows.pipeline.loading import _normalize_input_flow_record
from brightway_flows.simapro_names import split_geography_suffix
from brightway_flows.sources import known_source_lists

#: Where the manifest says this list's flows live: the data directory, because
#: they are fetched rather than authored.  So they are not in the repository and
#: the tests reading them skip without one, as the artifact tests do.
BAFU_2026 = known_source_lists()["bafu-2026-v1"]

#: One process, carrying every case the real archive puts in front of the
#: extractor: a resource (`inputGroup` 4), an emission (`outputGroup` 4), a
#: technosphere input and a reference product that must not be picked up, a CAS
#: number in BAFU's zero-padded spelling, and a formula.
PROCESS_ONE = b"""<?xml version='1.0' encoding='UTF-8'?>
<ecoSpold>
  <dataset generator="openLCA" number="1">
    <flowData>
      <exchange category="nuclear waste" name="Radioactive waste" number="9001"
                subCategory="unspecified" unit="m3" meanValue="1.0">
        <outputGroup>0</outputGroup>
      </exchange>
      <exchange category="electricity" name="Electricity, at grid" number="9002"
                subCategory="supply mix" unit="kWh" meanValue="377.0">
        <inputGroup>5</inputGroup>
      </exchange>
      <exchange CASNumber="000071-43-2" category="emissions to air" formula="C6H6"
                name="Benzene" number="9003" subCategory="high. pop."
                unit="kg" meanValue="0.5">
        <outputGroup>4</outputGroup>
      </exchange>
      <exchange category="resources" name="Water, AE" number="9004"
                subCategory="in water" unit="m3" meanValue="2.0">
        <inputGroup>4</inputGroup>
      </exchange>
    </flowData>
  </dataset>
</ecoSpold>
"""

#: A second process naming the same benzene flow -- with the CAS written
#: unpadded this time -- plus the same substance in a different subcompartment,
#: a metal carrying both the element's CAS and its ion's, a second regionalised
#: water in the same context as the first, the *unregionalised* water they are
#: both spellings of, and the silver ore whose name ends in indium.
PROCESS_TWO = b"""<?xml version='1.0' encoding='UTF-8'?>
<ecoSpold>
  <dataset generator="openLCA" number="2">
    <flowData>
      <exchange CASNumber="71-43-2" category="emissions to air" name="Benzene"
                number="9003" subCategory="high. pop." unit="kg" meanValue="0.25">
        <outputGroup>4</outputGroup>
      </exchange>
      <exchange CASNumber="71-43-2" category="emissions to air" name="Benzene"
                number="9003" subCategory="low. pop." unit="kg" meanValue="0.1">
        <outputGroup>4</outputGroup>
      </exchange>
      <exchange CASNumber="7440-47-3" category="emissions to water" name="Chromium"
                number="9005" subCategory="unspecified" unit="kg" meanValue="0.01">
        <outputGroup>4</outputGroup>
      </exchange>
      <exchange CASNumber="18540-29-9" category="emissions to water" name="Chromium"
                number="9005" subCategory="unspecified" unit="kg" meanValue="0.02">
        <outputGroup>4</outputGroup>
      </exchange>
      <exchange category="resources" name="Water, AR" number="9006"
                subCategory="in water" unit="m3" meanValue="3.0">
        <inputGroup>4</inputGroup>
      </exchange>
      <exchange category="resources" name="Water" number="9007"
                subCategory="in water" unit="m3" meanValue="4.0">
        <inputGroup>4</inputGroup>
      </exchange>
      <exchange category="resources" name="Silver, 0.007% in sulfide, Ag 0.004%, Pb, Zn, Cd, In"
                number="9008" subCategory="in ground" unit="kg" meanValue="5.0">
        <inputGroup>4</inputGroup>
      </exchange>
    </flowData>
  </dataset>
</ecoSpold>
"""


class ExtractionTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.directory = Path(self._tmp.name) / "ecoSpold files"
        self.directory.mkdir()
        (self.directory / "process_one.xml").write_bytes(PROCESS_ONE)
        (self.directory / "process_two.xml").write_bytes(PROCESS_TWO)
        self.archive = Path(self._tmp.name) / "bafu.zip"
        with ZipFile(self.archive, "w") as zf:
            zf.write(self.directory / "process_one.xml", "ecoSpold files/one.xml")
            zf.write(self.directory / "process_two.xml", "ecoSpold files/two.xml")

    def records(self, archive=None):
        return extract_elementary_flows(archive or self.archive, source="bafu-2026-v1")

    def by_name(self, records):
        return {(r["name"], r["context"][1]): r for r in records}

    def test_only_group_four_exchanges_are_elementary(self):
        """The reference product and the technosphere input are not flows.

        This is the whole of what makes an exchange elementary in ecoSpold v1 --
        there is no other marker, and a reading that took every exchange would
        turn 11,947 processes into the flow list.
        """
        names = {r["name"] for r in self.records()}
        self.assertEqual(
            names,
            {
                "Benzene",
                "Water, AE",
                "Water, AR",
                "Water",
                "Chromium",
                "Silver, 0.007% in sulfide, Ag 0.004%, Pb, Zn, Cd, In",
            },
        )
        self.assertNotIn("Electricity, at grid", names)
        self.assertNotIn("Radioactive waste", names)

    def test_resources_and_emissions_both_count(self):
        """`inputGroup` 4 is nature coming in, `outputGroup` 4 is nature going out."""
        contexts = {r["name"]: r["context"][0] for r in self.records()}
        self.assertEqual(contexts["Water, AE"], "resources")
        self.assertEqual(contexts["Benzene"], "emissions to air")

    def test_one_flow_per_name_context_and_unit(self):
        """293,747 exchanges are 2,679 flows: the same flow recurs per process."""
        records = self.records()
        self.assertEqual(len(records), 7)
        benzene = [r for r in records if r["name"] == "Benzene"]
        self.assertEqual(len(benzene), 2)
        self.assertEqual(
            sorted(r["context"][1] for r in benzene), ["high. pop.", "low. pop."]
        )

    def test_the_subcompartment_separates_two_flows(self):
        """Benzene in `high. pop.` and in `low. pop.` are not one flow.

        They share a name, a compartment, a unit and BAFU's own `number`. Only
        the subcompartment tells them apart, and the context mapping sends them
        to different context IRIs.
        """
        records = self.by_name(self.records())
        self.assertNotEqual(
            records[("Benzene", "high. pop.")]["uuid"],
            records[("Benzene", "low. pop.")]["uuid"],
        )

    def test_the_identifier_is_derived_from_what_names_the_flow(self):
        """No identifier ships with a BAFU flow, so one is minted (#4).

        Name-derived, which is what makes 2025 and 2026 comparable: the 2025
        extraction kept no `number`, so nothing else could line the two up.
        """
        record = self.by_name(self.records())[("Benzene", "high. pop.")]
        self.assertEqual(
            record["uuid"], _flow_uuid("Benzene", "emissions to air", "high. pop.", "kg")
        )

    def test_the_identifier_is_stable_across_runs_and_archives(self):
        """It is published in the flow IRI: a value that moves is a broken link."""
        self.assertEqual(
            [r["uuid"] for r in self.records()],
            [r["uuid"] for r in self.records(self.directory)],
        )

    def test_a_padded_and_an_unpadded_cas_are_one_number(self):
        """BAFU writes the same CAS both ways, in different processes.

        `000071-43-2` and `71-43-2` are benzene either way. Kept apart, every
        such flow would ship looking as though it had two candidate identities.
        """
        record = self.by_name(self.records())[("Benzene", "high. pop.")]
        self.assertEqual(record["cas_numbers"], ["71-43-2"])

    def test_two_genuinely_different_cas_numbers_are_both_kept(self):
        """Twelve real flows carry a metal's CAS and its ion's, and ship ambiguous.

        Chromium here holds chromium's number and chromium VI's, which is a
        different substance with a different toxicity. Choosing between them is
        a curation decision, and dropping one during extraction would take it
        where nothing can review it and leave a manual fix nothing to correct.
        """
        record = self.by_name(self.records())[("Chromium", "unspecified")]
        self.assertEqual(record["cas_numbers"], ["18540-29-9", "7440-47-3"])

    def test_a_flow_with_no_cas_carries_no_empty_field(self):
        record = self.by_name(self.records())[("Water, AE", "in water")]
        self.assertNotIn("cas_numbers", record)

    def test_the_zip_and_the_unpacked_directory_agree(self):
        """The archive is read without unpacking: 38 MB against 225 MB on disk."""
        self.assertEqual(self.records(), self.records(self.directory))

    def test_every_record_has_what_a_source_list_row_needs(self):
        """A row missing `uuid` is dropped by the loader without saying so."""
        for record in self.records():
            with self.subTest(name=record["name"]):
                for field in ("uuid", "name", "source", "context", "unit"):
                    self.assertTrue(record.get(field), field)
                self.assertEqual(record["source"], "bafu-2026-v1")
                self.assertEqual(len(record["context"]), 2)


class GeographyIsInTheNameTestCase(unittest.TestCase):
    """The largest matching gap in #4, and where it gets closed (#65).

    ecoSpold v1 has a `location` attribute, and BAFU's technosphere exchanges
    use it. Its elementary ones do not carry it at all -- 181 flow names end in
    a geography instead. So there is no field to read, and `Water, AE` really is
    the flow's name as the file has it.

    It is still read here rather than during matching, because the place is not
    another way to spell the substance: it is a field this list holds elsewhere,
    and taking it out is a **rewrite of the row**. Left in, the row carries the
    country into the flow it creates and into every rule between here and
    matching. Taken out, the row is the row BAFU would have shipped had it
    modelled geography the way this list does -- so it gets its sibling's
    context rules, its sibling's manual fixes and its sibling's flow object,
    and none of them had to learn about geography.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.directory = Path(self._tmp.name)
        (self.directory / "one.xml").write_bytes(PROCESS_ONE)
        (self.directory / "two.xml").write_bytes(PROCESS_TWO)

    def records(self, *, split_geography):
        return extract_elementary_flows(
            self.directory, source="bafu-2026-v1", split_geography=split_geography
        )

    def water(self, records, location):
        return next(
            r for r in records
            if r["name"] == "Water" and r.get("location") == location
        )

    def test_the_split_is_off_unless_the_list_asks_for_it(self):
        """The gate did not go away when the rule moved out of matching.
        Reading a trailing field as a place is right for a list SimaPro shaped
        and a guess for any other, so it stays something a list opts into."""
        records = self.records(split_geography=False)
        names = {r["name"] for r in records}
        self.assertIn("Water, AE", names)
        self.assertIn("Water, AR", names)
        self.assertTrue(all("location" not in r for r in records))
        self.assertTrue(all("original_name" not in r for r in records))

    def test_the_gate_is_the_lists_simapro_origin(self):
        """Not the vendor's identity, and not a constant in this module."""
        source = known_source_lists()["bafu-2026-v1"]
        self.assertTrue(source.simapro_origin)

    def test_the_place_moves_out_of_the_name_and_into_a_field(self):
        records = self.records(split_geography=True)
        water = self.water(records, "AE")
        self.assertEqual(water["name"], "Water")
        self.assertEqual(water["location"], "AE")
        self.assertEqual(water["original_name"], "Water, AE")
        self.assertEqual(water["context"], ["resources", "in water"])

    def test_two_places_become_two_rows_sharing_one_name(self):
        """Which is the whole point. `Water, AE` and `Water, AR` stay two flows
        -- they are two rows BAFU ships and each has its own correspondence --
        but they now name one substance in one context, so the merge mints one
        flow object for them and lands both on one consensus flow instead of
        creating a parallel water per country."""
        records = self.records(split_geography=True)
        waters = [r for r in records if r["name"] == "Water"]
        self.assertEqual(len(waters), 3)
        self.assertEqual(
            {r.get("location", "") for r in waters}, {"AE", "AR", ""}
        )
        self.assertEqual(
            {(r["name"], tuple(r["context"]), r["unit"]) for r in waters},
            {("Water", ("resources", "in water"), "m3")},
        )
        self.assertEqual(len({r["uuid"] for r in waters}), 3)

    def test_the_unregionalised_sibling_keeps_the_identifier_it_had(self):
        """Only the regionalised rows are renumbered. A flow that carries no
        place is the same flow it was before the split existed, and changing
        its identifier would move it for no reason."""
        before = {r["uuid"] for r in self.records(split_geography=False)}
        after = self.records(split_geography=True)
        unlocated = {r["uuid"] for r in after if "location" not in r}
        located = {r["uuid"] for r in after if "location" in r}
        self.assertEqual(unlocated - before, set())
        self.assertEqual(located & before, set())
        self.assertEqual(len(located), 2)

    def test_a_regionalised_row_does_not_take_its_siblings_identifier(self):
        """The place is in the seed. Without it `Water, AE` and the plain
        `Water` would be the same four fields in the same context, and the two
        would fuse -- taking BAFU's distinction with them."""
        records = self.records(split_geography=True)
        plain = next(
            r for r in records if r["name"] == "Water" and "location" not in r
        )
        self.assertNotEqual(self.water(records, "AE")["uuid"], plain["uuid"])
        self.assertNotEqual(
            self.water(records, "AE")["uuid"], self.water(records, "AR")["uuid"]
        )

    def test_indium_is_not_read_as_a_place(self):
        """`Silver, 0.007% in sulfide, Ag 0.004%, Pb, Zn, Cd, In` ends in
        indium, and `In` differs from India's `IN` only in case. The base label
        is what declines it, not the capitalisation."""
        records = self.records(split_geography=True)
        silver = next(r for r in records if r["name"].startswith("Silver"))
        self.assertEqual(
            silver["name"], "Silver, 0.007% in sulfide, Ag 0.004%, Pb, Zn, Cd, In"
        )
        self.assertNotIn("location", silver)

    def test_nothing_else_in_the_fixture_is_touched(self):
        untouched = {"Benzene", "Chromium"}
        for record in self.records(split_geography=True):
            if record["name"] in untouched:
                with self.subTest(name=record["name"]):
                    self.assertNotIn("location", record)
                    self.assertNotIn("original_name", record)

    def test_both_fields_reach_the_flow_record_and_are_carried_not_read(self):
        """`Flow` has no `location` or `original_name` attribute, and neither
        should be given one. They land in the passthrough bag, which is where a
        value the pipeline carries but does not act on belongs: it round-trips
        into `flow_json` and out again, and because records provide no `get()`
        nothing can read either by accident.

        The place is the half with a future -- it is where a `dcterms:spatial`
        on the correspondence would come from, and typing it is that change's
        job. The name as shipped has none: it is kept for the record.
        """
        record = self.water(self.records(split_geography=True), "AE")
        flow = Flow.from_dict(
            _normalize_input_flow_record(record, source_hint="bafu-2026-v1")
        )
        self.assertEqual(flow.name, "Water")
        self.assertEqual(flow.extra["location"], "AE")
        self.assertEqual(flow.extra["original_name"], "Water, AE")
        self.assertFalse(hasattr(flow, "location"))
        self.assertFalse(hasattr(flow, "original_name"))
        self.assertEqual(flow.to_dict()["location"], "AE")

    def test_the_place_is_not_a_label_the_matcher_can_reach(self):
        """`original_name` is not a synonym and must not become one. As a label
        it would put `Water, AE` back in front of the matcher, which is the
        shape this stopped being -- and `_source_labels` reads the shipped name
        and synonyms, neither of which it is."""
        record = self.water(self.records(split_geography=True), "AE")
        flow = Flow.from_dict(
            _normalize_input_flow_record(record, source_hint="bafu-2026-v1")
        )
        self.assertNotIn("Water, AE", flow.provided.labels())
        self.assertEqual(flow.provided.name, "Water")


class FetchedFlowsTestCase(unittest.TestCase):
    """Against the real 2,679 flows, not the fixture.

    These are what make an upstream change to BAFU fail rather than drift: a
    compartment the rules do not cover, or a unit the vocabulary does not know,
    would otherwise surface as every row of a merge failing into the report.

    They skip where the list has not been fetched, which is the cost of the
    flows living in the data directory: CI sees the fixture and a developer who
    has run `fetch-source bafu-2026-v1` sees both.
    """

    @classmethod
    def setUpClass(cls):
        if not BAFU_2026.flows_path.exists():
            raise unittest.SkipTest(
                f"{BAFU_2026.flows_path.name} not present; run "
                f"`{BAFU_2026.fetch_command}`"
            )
        cls.flows = orjson.loads(BAFU_2026.flows_path.read_bytes())

    def test_the_extraction_is_the_one_that_shipped(self):
        """2,679 flows under 1,010 names, where the names were 1,187 before the
        geography came out of them (#65).

        The arithmetic is exact and worth stating, because it is the whole of
        what the split did to this list: 181 regionalised names left, and four
        base labels arrived that BAFU ships in no other form -- `Water,
        embodied in product`, `Water, unspecified`, and the two `…natural
        origin` waters it otherwise spells with a unit on the end. 1,187 - 181
        + 4 = 1,010. No flow was lost and none was fused: the count of records
        did not move.
        """
        self.assertEqual(len(self.flows), 2679)
        self.assertEqual(len({f["name"] for f in self.flows}), 1010)
        self.assertEqual(len({f["uuid"] for f in self.flows}), len(self.flows))

    def test_the_place_is_a_field_and_no_longer_part_of_any_name(self):
        located = [f for f in self.flows if "location" in f]
        self.assertEqual(len(located), 262)
        self.assertEqual(len({f["original_name"] for f in located}), 181)
        self.assertEqual(len({f["name"] for f in located}), 11)
        self.assertEqual(len({f["location"] for f in located}), 81)
        self.assertTrue(
            all(split_geography_suffix(f["name"]) is None for f in self.flows),
            "a name still carries a place the splitter would read",
        )

    def test_every_compartment_has_a_context_rule(self):
        """26 rules, 26 compartments, and the merge stops on a row it cannot place."""
        rules = context_iri_by_source_context("bafu-2026-v1")
        self.assertEqual(len(rules), 26)
        used = {normalize_context_key(f["context"]) for f in self.flows}
        self.assertEqual(used - set(rules), set())

    def test_no_rule_is_dead(self):
        """A rule matching nothing is a rule nobody will notice going stale."""
        used = {normalize_context_key(f["context"]) for f in self.flows}
        self.assertEqual(set(context_iri_by_source_context("bafu-2026-v1")) - used, set())

    def test_every_context_iri_is_a_real_context(self):
        allowed = {
            row["context_iri"]
            for row in orjson.loads(MANUAL_MAPPING_FILEPATH.read_bytes())[
                "allowed_context_combinations"
            ]
        }
        for context_iri in context_iri_by_source_context("bafu-2026-v1").values():
            with self.subTest(context_iri=context_iri):
                self.assertIn(context_iri, allowed)

    def test_every_flow_resolves_a_context_the_way_the_transform_does(self):
        """Having a rule per compartment is not the same as placing every row.

        `resources / land` is a compartment whose context the *name* decides,
        because BAFU files occupation and transformation together. 123 of its
        127 names say which they are; four say neither, because they are not
        land-use flows at all -- a mineral, two water resources and standing
        timber, filed under land by the vendor.

        A full build is what found that, an hour in, after both ecoinvent
        merges had already run: `name_prefix_context_iri` raises rather than
        filing an undecidable name under the compartment's rule (#52). The
        earlier test here asserted every compartment has a rule and passed
        throughout, because that question is a different one. This asks the
        question the transform asks, of every row.
        """
        unplaced = []
        for flow in self.flows:
            context = flow["context"]
            iri = flow_context_iri("bafu-2026-v1", flow["uuid"], context)
            if not iri:
                try:
                    iri = name_prefix_context_iri("bafu-2026-v1", flow["name"], context)
                except AmbiguousSourceContextError:
                    unplaced.append(f"{flow['name']} in {context}")
                    continue
            if not iri:
                iri = context_iri_by_source_context("bafu-2026-v1").get(
                    normalize_context_key(context)
                )
            if not iri:
                unplaced.append(f"{flow['name']} in {context}")
        self.assertEqual(unplaced, [])

    def test_every_unit_resolves(self):
        """`m2a`, `m3y` and `personkm` are BAFU's separator-free spellings.

        All three name units the vocabulary already has -- `m2.a`, `m3.a`,
        `p.km` -- so what was missing was the alias, not the unit.
        """
        index = build_units_index()
        unresolved = sorted(
            {
                flow["unit"]
                for flow in self.flows
                if resolve_unit_notation(flow["unit"], index) is None
            }
        )
        self.assertEqual(unresolved, [])

    def test_every_manual_fix_names_a_row_this_list_ships(self):
        """A fix keyed on a name BAFU does not use corrects nothing.

        `apply_manual_fixes` warns -- `manual_fix_matched_nothing` -- but a
        warning in a build log is only seen by somebody who reads one, and a
        build takes thirteen minutes to produce.  This asks the same question
        in a second.

        The trap it exists for is capitalisation.  BAFU writes its names in
        sentence case, `Methyl mercaptan`, and the merge report shows them
        title cased, `Methyl Mercaptan`, because the harmoniser recapitalises
        downstream.  A curator reading `merge_outcomes` to find the row to
        correct therefore reads a spelling the vendor's file does not contain,
        and the match is case sensitive.  Nine of #103's nineteen fixes were
        written that way and silently corrected nothing.

        Names only.  A fix may also be keyed on a compartment or a unit, and
        whether *that* combination matches is a question about one row rather
        than about the vocabulary this list uses.
        """
        shipped = {flow["name"] for flow in self.flows}
        missing = sorted(
            {
                name
                for fix in orjson.loads(BAFU_2026.manual_fixes_path.read_bytes())["fixes"]
                if isinstance(name := (fix.get("match") or {}).get("name"), str)
                and name not in shipped
            }
        )
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
