"""A property statement is about the flow; the factor on a mapping is about a pair.

"One kilogram of this coal is 18.2 MJ of net calorific value" is what a list
says about its own flow.  18.2 is what a kilogram of it becomes on an EF flow
in megajoules, and 18,200 is what a tonne becomes.  Until #407 only the second
number existed, typed by hand on each override row, four times for four lists,
with no unit, no basis and no provenance.  These tests pin down what replaces
it: how a statement turns into a factor for a unit pair, how the right one of
several is chosen, what a malformed statements file is refused for, and that
the real files load for the releases they were checked against.

The vintage rule is the override module's (#162): a value is a measurement, a
measurement has a release it was read from, and a release nobody has checked is
refused rather than given the default.
"""

import tempfile
import unittest
from pathlib import Path

import orjson

from brightway_flows.domain.common import Provenance
from brightway_flows.domain.flow import Flow, ProvidedValues
from brightway_flows.domain.property_statements import (
    AmbiguousPropertyStatementsError,
    ConversionRule,
    PropertyStatement,
    StatementOrigin,
    choose_statement,
    decode_statements,
    encode_statements,
    factor_between,
)
from brightway_flows.domain.quantities import (
    CALORIFIC_VALUE,
    FISSION_ENERGY,
    GROSS_CALORIFIC_VALUE,
    MASS,
    NET_CALORIFIC_VALUE,
    VOLUME,
)
from brightway_flows.domain.units import unit_row_for
from brightway_flows.property_statements import (
    DECISIONS_SCHEMA_VERSION,
    PropertyStatements,
    attach_property_statements,
    load_property_statements,
    reference_quantities_from_ilcd,
    refuse_a_pair_stated_twice,
)
from brightway_flows.sources import (
    base_source_list,
    known_source_lists,
    resolve_source_list,
)

PROVENANCE = Provenance(
    was_generated_by="test",
    was_attributed_to="brightway-flows",
    had_primary_source=["the vendor's substance block"],
)

#: ILCD's net calorific value and mass flow properties, as EF 3.1 ships them.
ILCD_NET_CALORIFIC_VALUE = "93a60a56-a3c8-11da-a746-0800200c9a66"
ILCD_MASS = "93a60a56-a3c8-11da-a746-0800200b9a66"

#: EF 3.1's `Uranium` resource flow, whose megajoule EF labels a net calorific
#: value and the base list's statements file rules fission energy.
EF_URANIUM = "3e4d2966-6556-11dd-ad8b-0800200c9a66"

#: Statements per source list in the shipped files, by `list_name`.
EXPECTED_STATEMENT_COUNTS = {
    "ecoinvent": 6,
    "bafu": 11,
    "stepwise": 12,
    "agribalyse": 29,
}


def _stmt(
    quantity: str,
    value: float,
    unit: str,
    per_unit: str,
    stated_by: StatementOrigin = StatementOrigin.CURATED,
) -> PropertyStatement:
    return PropertyStatement(
        quantity=quantity,
        value=value,
        unit=unit,
        per_unit=per_unit,
        stated_by=stated_by,
        provenance=PROVENANCE,
        comment="a reason",
    )


def _kind(unit: str) -> str:
    row = unit_row_for(unit)
    return str(row.get("quantity_kind_iri") or "") if row else ""


class FactorBetweenTestCase(unittest.TestCase):
    """A statement answers a unit pair in the direction it is written, or inverted.

    Direction is carried by the units, never by the quantity: `0.001 m3 per kg`
    and `1025 kg per m3` both answer a kilogram-to-cubic-metre pair.  Each end
    scales through `units.json` within a kind, so a tonne reaches a statement
    per kilogram, and a standard cubic metre never reaches a plain one (#292).
    Where the number is stated in the asked direction it comes back bit for
    bit, which is what lets a curated file publish the stated number.
    """

    def setUp(self):
        self.net = _stmt(NET_CALORIFIC_VALUE, 18.2, "MJ", "kg")

    def test_stated_direction_is_exact(self):
        self.assertEqual(factor_between(self.net, "kg", "MJ"), 18.2)

    def test_source_unit_scales_onto_per_unit(self):
        self.assertAlmostEqual(factor_between(self.net, "t", "MJ"), 18200.0)

    def test_a_pair_the_statement_does_not_bridge_is_none(self):
        self.assertIsNone(factor_between(self.net, "m3", "MJ"))
        self.assertIsNone(factor_between(self.net, "kg", "kg"))

    def test_a_standard_cubic_metre_is_not_a_cubic_metre(self):
        per_sm3 = _stmt(NET_CALORIFIC_VALUE, 36.0, "MJ", "sm3")
        per_m3 = _stmt(NET_CALORIFIC_VALUE, 36.0, "MJ", "m3")
        self.assertIsNone(factor_between(per_sm3, "m3", "MJ"))
        self.assertIsNone(factor_between(per_m3, "sm3", "MJ"))
        self.assertEqual(factor_between(per_sm3, "sm3", "MJ"), 36.0)
        self.assertEqual(factor_between(per_m3, "m3", "MJ"), 36.0)

    def test_a_volume_per_kilogram_is_read_inverted_for_the_other_way(self):
        volume = _stmt(VOLUME, 0.001, "m3", "kg")
        self.assertEqual(factor_between(volume, "kg", "m3"), 0.001)
        self.assertEqual(factor_between(volume, "m3", "kg"), 1000.0)

    def test_a_density_serves_both_directions(self):
        density = _stmt(MASS, 1025, "kg", "m3")
        self.assertEqual(factor_between(density, "m3", "kg"), 1025.0)
        self.assertEqual(factor_between(density, "kg", "m3"), 1.0 / 1025)


class ChooseStatementTestCase(unittest.TestCase):
    """Which of a flow's statements converts onto a target of a given quantity.

    The exact quantity first; else a calorific value of unstated basis stands
    in for a net or gross one and the reverse; else what the list's conversion
    rule says.  Fission energy is not a heat of combustion, so it never stands
    in for one.  Two answers at one step are a question for a ruling, and the
    code raises rather than letting file order decide.
    """

    def setUp(self):
        self.net = _stmt(NET_CALORIFIC_VALUE, 18.2, "MJ", "kg")
        self.gross = _stmt(GROSS_CALORIFIC_VALUE, 19.1, "MJ", "kg")
        self.unstated = _stmt(CALORIFIC_VALUE, 18.01, "MJ", "kg")
        self.fission = _stmt(FISSION_ENERGY, 560_000, "MJ", "kg")
        self.gross_rule = ConversionRule(
            onto=NET_CALORIFIC_VALUE, convert_by=GROSS_CALORIFIC_VALUE, comment="Stepwise"
        )

    def test_exact_quantity_wins(self):
        chosen = choose_statement(
            [self.gross, self.net, self.unstated], target_quantity=NET_CALORIFIC_VALUE
        )
        self.assertIs(chosen, self.net)

    def test_basis_unstated_stands_in_for_a_stated_basis(self):
        for target in (NET_CALORIFIC_VALUE, GROSS_CALORIFIC_VALUE):
            with self.subTest(target=target):
                chosen = choose_statement([self.unstated], target_quantity=target)
                self.assertIs(chosen, self.unstated)

    def test_a_stated_basis_stands_in_for_an_unstated_target(self):
        self.assertIs(
            choose_statement([self.net], target_quantity=CALORIFIC_VALUE), self.net
        )
        self.assertIs(
            choose_statement([self.gross], target_quantity=CALORIFIC_VALUE), self.gross
        )

    def test_fission_energy_never_stands_in_for_a_heat_of_combustion(self):
        for target in (NET_CALORIFIC_VALUE, GROSS_CALORIFIC_VALUE, CALORIFIC_VALUE):
            with self.subTest(target=target):
                self.assertIsNone(
                    choose_statement(
                        [self.fission], target_quantity=target, rules=[self.gross_rule]
                    )
                )

    def test_fission_energy_is_accepted_for_a_fission_target(self):
        self.assertIs(
            choose_statement([self.fission], target_quantity=FISSION_ENERGY),
            self.fission,
        )

    def test_a_rule_picks_the_gross_value_when_nothing_closer_exists(self):
        chosen = choose_statement(
            [self.gross], target_quantity=NET_CALORIFIC_VALUE, rules=[self.gross_rule]
        )
        self.assertIs(chosen, self.gross)

    def test_without_the_rule_gross_does_not_convert_onto_net(self):
        self.assertIsNone(
            choose_statement([self.gross], target_quantity=NET_CALORIFIC_VALUE)
        )

    def test_the_rule_yields_to_a_closer_statement(self):
        """An exact or basis-unstated statement comes before any rule."""
        self.assertIs(
            choose_statement(
                [self.gross, self.net],
                target_quantity=NET_CALORIFIC_VALUE,
                rules=[self.gross_rule],
            ),
            self.net,
        )
        self.assertIs(
            choose_statement(
                [self.gross, self.unstated],
                target_quantity=NET_CALORIFIC_VALUE,
                rules=[self.gross_rule],
            ),
            self.unstated,
        )

    def test_a_rule_for_another_target_is_not_applied(self):
        rule = ConversionRule(onto=CALORIFIC_VALUE, convert_by=FISSION_ENERGY, comment="no")
        self.assertIsNone(
            choose_statement(
                [self.fission], target_quantity=NET_CALORIFIC_VALUE, rules=[rule]
            )
        )

    def test_two_statements_at_one_step_are_ambiguous(self):
        second_net = _stmt(NET_CALORIFIC_VALUE, 18.4, "MJ", "kg", StatementOrigin.VENDOR_METHOD)
        with self.assertRaises(AmbiguousPropertyStatementsError) as caught:
            choose_statement([self.net, second_net], target_quantity=NET_CALORIFIC_VALUE)
        self.assertIn("18.2", str(caught.exception))
        self.assertIn("18.4", str(caught.exception))

    def test_ambiguity_is_a_value_error(self):
        self.assertTrue(issubclass(AmbiguousPropertyStatementsError, ValueError))

    def test_nothing_applicable_is_none(self):
        self.assertIsNone(choose_statement([], target_quantity=NET_CALORIFIC_VALUE))
        self.assertIsNone(choose_statement([self.net], target_quantity=MASS))


class PropertyStatementRecordTestCase(unittest.TestCase):
    """The record refuses a value that converts nothing and round-trips its file form."""

    def test_zero_and_negative_values_are_refused(self):
        for value in (0, 0.0, -1, -18.2):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    _stmt(NET_CALORIFIC_VALUE, value, "MJ", "kg")

    def test_a_bool_is_not_a_number(self):
        with self.assertRaises(ValueError):
            _stmt(NET_CALORIFIC_VALUE, True, "MJ", "kg")

    def test_a_string_is_not_a_number(self):
        with self.assertRaises(ValueError):
            _stmt(NET_CALORIFIC_VALUE, "18.2", "MJ", "kg")

    def test_an_integer_value_is_stored_as_a_float(self):
        statement = _stmt(MASS, 1025, "kg", "m3")
        self.assertIsInstance(statement.value, float)
        self.assertEqual(statement.value, 1025.0)

    def test_to_dict_publishes_provenance_as_prov_and_origin_as_text(self):
        payload = _stmt(NET_CALORIFIC_VALUE, 18.2, "MJ", "kg").to_dict()
        self.assertEqual(payload["stated_by"], "curated")
        self.assertIsInstance(payload["provenance"], dict)
        self.assertEqual(
            payload["provenance"]["prov:hadPrimarySource"],
            ["the vendor's substance block"],
        )

    def test_round_trip_is_equal(self):
        statement = _stmt(NET_CALORIFIC_VALUE, 18.2, "MJ", "kg", StatementOrigin.VENDOR_FLOW)
        again = PropertyStatement.from_dict(statement.to_dict())
        self.assertEqual(again, statement)
        self.assertIs(again.stated_by, StatementOrigin.VENDOR_FLOW)
        self.assertIsInstance(again.provenance, Provenance)

    def test_quantity_iri_is_the_vocabulary_iri(self):
        statement = _stmt(NET_CALORIFIC_VALUE, 18.2, "MJ", "kg")
        self.assertEqual(
            statement.quantity_iri,
            "https://vocab.brightway.one/quantity/net-calorific-value",
        )

    def test_codec_pair_round_trips_a_list(self):
        statements = [_stmt(NET_CALORIFIC_VALUE, 18.2, "MJ", "kg")]
        encoded = encode_statements(statements)
        self.assertIsInstance(encoded[0], dict)
        self.assertEqual(decode_statements(encoded), statements)

    def test_codecs_pass_through_what_is_not_a_list(self):
        self.assertIsNone(encode_statements(None))
        self.assertIsNone(decode_statements(None))


class FlowFieldTestCase(unittest.TestCase):
    """`Flow.property_statements` is absent from the 94k records that carry none."""

    def test_a_flow_without_statements_serialises_without_the_key(self):
        self.assertNotIn("property_statements", Flow(uuid="u").to_dict())

    def test_a_flow_with_a_statement_round_trips_it(self):
        statement = _stmt(NET_CALORIFIC_VALUE, 18.2, "MJ", "kg", StatementOrigin.VENDOR_FLOW)
        flow = Flow(uuid="u", unit="kg", property_statements=[statement])
        payload = flow.to_dict()
        self.assertEqual(payload["property_statements"][0]["stated_by"], "vendor-flow")
        again = Flow.from_dict(payload)
        self.assertEqual(again.property_statements, [statement])
        self.assertIsInstance(again.property_statements[0], PropertyStatement)


def _entry(**overrides) -> dict:
    """One well-formed statement entry, with *overrides* applied on top."""
    entry = {
        "source_uuid": "coal-hard",
        "source_name": "Coal, hard",
        "quantity": NET_CALORIFIC_VALUE,
        "value": 18.2,
        "unit": "MJ",
        "per_unit": "kg",
        "stated_by": "vendor-flow",
        "checked_against": ["3.9.1", "3.12"],
        "primary_source": ["the vendor's substance block, row `Coal, hard`"],
        "comment": "the lower heating value the vendor states",
    }
    entry.update(overrides)
    return entry


def _without(entry: dict, key: str) -> dict:
    copy = dict(entry)
    copy.pop(key)
    return copy


class LoaderFixtureTestCase(unittest.TestCase):
    """Shared temp directory and file writer for the loader tests."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def write(self, name: str = "test-property-statements.json", **payload) -> Path:
        payload.setdefault("schema_version", DECISIONS_SCHEMA_VERSION)
        path = self.dir / name
        path.write_bytes(orjson.dumps(payload))
        return path

    def load(self, release: str = "", **payload) -> PropertyStatements:
        return load_property_statements(self.write(**payload), release=release)

    def assertRefused(self, naming: str, release: str = "", **payload) -> ValueError:
        with self.assertRaises(ValueError) as caught:
            self.load(release=release, **payload)
        self.assertIn(naming, str(caught.exception))
        return caught.exception


class LoaderTestCase(LoaderFixtureTestCase):
    """A good file loads into records, and a malformed one raises naming the row.

    A malformed ruling raises and is never skipped (rule 14), and the message
    says which row so that the person fixing the file does not have to read it
    from the top.
    """

    def test_a_good_file_loads(self):
        loaded = self.load(
            statements=[_entry()],
            conversion_rules=[
                {
                    "onto": NET_CALORIFIC_VALUE,
                    "convert_by": GROSS_CALORIFIC_VALUE,
                    "comment": "the method states gross values",
                }
            ],
            reference_quantities=[
                {"flow_uuid": EF_URANIUM, "quantity": FISSION_ENERGY, "comment": "not a fuel burnt"}
            ],
        )
        self.assertEqual(set(loaded.statements), {"coal-hard"})
        (statement,) = loaded.statements["coal-hard"]
        self.assertEqual(statement.quantity, NET_CALORIFIC_VALUE)
        self.assertEqual(statement.value, 18.2)
        self.assertEqual(statement.unit, "MJ")
        self.assertEqual(statement.per_unit, "kg")
        self.assertIs(statement.stated_by, StatementOrigin.VENDOR_FLOW)
        self.assertEqual(statement.comment, "the lower heating value the vendor states")
        self.assertEqual(
            statement.provenance.had_primary_source,
            ["the vendor's substance block, row `Coal, hard`"],
        )
        self.assertEqual(statement.provenance.was_derived_from, "test-property-statements.json")
        self.assertEqual(statement.provenance.was_generated_by, "property_statements")
        self.assertEqual(
            loaded.rules,
            (
                ConversionRule(
                    onto=NET_CALORIFIC_VALUE,
                    convert_by=GROSS_CALORIFIC_VALUE,
                    comment="the method states gross values",
                ),
            ),
        )
        self.assertEqual(loaded.reference_quantities, {EF_URANIUM: FISSION_ENERGY})
        self.assertEqual(loaded.filename, "test-property-statements.json")

    def test_generated_by_names_the_activity(self):
        path = self.write(statements=[_entry()])
        loaded = load_property_statements(path, generated_by="merge-stepwise")
        (statement,) = loaded.statements["coal-hard"]
        self.assertEqual(statement.provenance.was_generated_by, "merge-stepwise")

    def test_stated_by_defaults_to_curated(self):
        loaded = self.load(statements=[_without(_entry(), "stated_by")])
        (statement,) = loaded.statements["coal-hard"]
        self.assertIs(statement.stated_by, StatementOrigin.CURATED)

    def test_several_quantities_for_one_flow_are_kept_together(self):
        loaded = self.load(
            statements=[
                _entry(),
                _entry(quantity=GROSS_CALORIFIC_VALUE, value=19.1, stated_by="vendor-method"),
            ]
        )
        self.assertEqual(
            [s.quantity for s in loaded.statements["coal-hard"]],
            [NET_CALORIFIC_VALUE, GROSS_CALORIFIC_VALUE],
        )

    def test_a_file_with_no_statements_key_is_empty(self):
        loaded = self.load()
        self.assertEqual(loaded.statements, {})
        self.assertEqual(loaded.rules, ())
        self.assertEqual(loaded.reference_quantities, {})

    def test_unknown_quantity(self):
        error = self.assertRefused("Statement 0", statements=[_entry(quantity="heat")])
        self.assertIn("'heat'", str(error))

    def test_unit_not_of_the_quantitys_kind(self):
        error = self.assertRefused("Statement 0", statements=[_entry(unit="kg", per_unit="m3")])
        self.assertIn("Mass", str(error))
        self.assertIn("Energy", str(error))

    def test_unit_and_per_unit_of_one_kind(self):
        self.assertRefused(
            "Statement 0", statements=[_entry(quantity=MASS, unit="kg", per_unit="t")]
        )

    def test_unknown_unit(self):
        self.assertRefused("Statement 0", statements=[_entry(unit="furlongs")])
        self.assertRefused("Statement 0", statements=[_entry(per_unit="furlongs")])

    def test_unknown_origin(self):
        self.assertRefused("Statement 0", statements=[_entry(stated_by="hearsay")])

    def test_non_positive_value(self):
        self.assertRefused("Statement 0", statements=[_entry(value=0)])
        self.assertRefused("Statement 0", statements=[_entry(value=-18.2)])
        self.assertRefused("Statement 0", statements=[_entry(value="18.2")])

    def test_missing_comment(self):
        self.assertRefused("Statement 0", statements=[_without(_entry(), "comment")])
        self.assertRefused("Statement 0", statements=[_entry(comment="  ")])

    def test_missing_primary_source(self):
        self.assertRefused("Statement 0", statements=[_without(_entry(), "primary_source")])
        self.assertRefused("Statement 0", statements=[_entry(primary_source=[])])
        self.assertRefused("Statement 0", statements=[_entry(primary_source="a string")])

    def test_missing_checked_against(self):
        self.assertRefused("Statement 0", statements=[_without(_entry(), "checked_against")])
        self.assertRefused("Statement 0", statements=[_entry(checked_against=[])])

    def test_a_release_in_both_checked_against_and_by_release(self):
        error = self.assertRefused(
            "Statement 0",
            statements=[_entry(by_release={"3.12": {"value": 18.0}})],
        )
        self.assertIn("'3.12'", str(error))

    def test_by_release_value_not_an_object(self):
        self.assertRefused("Statement 0", statements=[_entry(by_release={"3.8": 17.9})])
        self.assertRefused("Statement 0", statements=[_entry(by_release={"3.8": {}})])
        self.assertRefused("Statement 0", statements=[_entry(by_release=[{"3.8": 17.9}])])

    def test_by_release_restating_an_unknown_key(self):
        error = self.assertRefused(
            "Statement 0",
            statements=[_entry(by_release={"3.8": {"value": 17.9, "comment": "no"}})],
        )
        self.assertIn("comment", str(error))

    def test_by_release_units_are_checked_too(self):
        self.assertRefused(
            "Statement 0", statements=[_entry(by_release={"3.8": {"unit": "kg"}})]
        )
        self.assertRefused(
            "Statement 0", statements=[_entry(by_release={"3.8": {"value": 0}})]
        )

    def test_the_second_row_naming_a_pair_already_stated_is_refused(self):
        error = self.assertRefused(
            "Statement 1", statements=[_entry(), _entry(value=18.4)]
        )
        self.assertIn("coal-hard", str(error))

    def test_wrong_schema_version(self):
        error = self.assertRefused(
            "test-property-statements.json", schema_version=2, statements=[_entry()]
        )
        self.assertIn(str(DECISIONS_SCHEMA_VERSION), str(error))

    def test_a_rule_onto_itself(self):
        self.assertRefused(
            "Conversion rule 0",
            conversion_rules=[
                {"onto": NET_CALORIFIC_VALUE, "convert_by": NET_CALORIFIC_VALUE, "comment": "x"}
            ],
        )

    def test_a_second_rule_onto_the_same_quantity(self):
        self.assertRefused(
            "Conversion rule 1",
            conversion_rules=[
                {"onto": NET_CALORIFIC_VALUE, "convert_by": GROSS_CALORIFIC_VALUE, "comment": "x"},
                {"onto": NET_CALORIFIC_VALUE, "convert_by": CALORIFIC_VALUE, "comment": "y"},
            ],
        )

    def test_a_rule_naming_an_unknown_quantity_or_lacking_a_comment(self):
        self.assertRefused(
            "Conversion rule 0",
            conversion_rules=[{"onto": NET_CALORIFIC_VALUE, "convert_by": "heat", "comment": "x"}],
        )
        self.assertRefused(
            "Conversion rule 0",
            conversion_rules=[{"onto": NET_CALORIFIC_VALUE, "convert_by": GROSS_CALORIFIC_VALUE}],
        )

    def test_a_reference_quantity_naming_an_unknown_slug(self):
        error = self.assertRefused(
            "Reference quantity 0",
            reference_quantities=[{"flow_uuid": EF_URANIUM, "quantity": "heat", "comment": "x"}],
        )
        self.assertIn("'heat'", str(error))

    def test_a_reference_quantity_ruled_twice(self):
        self.assertRefused(
            "Reference quantity 1",
            reference_quantities=[
                {"flow_uuid": EF_URANIUM, "quantity": FISSION_ENERGY, "comment": "x"},
                {"flow_uuid": EF_URANIUM, "quantity": NET_CALORIFIC_VALUE, "comment": "y"},
            ],
        )

    def test_a_statement_that_is_not_an_object(self):
        self.assertRefused("Statement 0", statements=["18.2 MJ/kg"])

    def test_no_path_is_an_empty_record(self):
        loaded = load_property_statements(None, release="3.12")
        self.assertEqual(loaded, PropertyStatements())
        self.assertEqual(loaded.filename, "")

    def test_a_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            load_property_statements(self.dir / "absent.json", label="nowhere")


class VintageTestCase(LoaderFixtureTestCase):
    """A value is a measurement and a measurement has a release.

    ecoinvent restated crude oil from 42.3 to 43.4 MJ/kg at 3.9, and its 3.8
    natural gas is a cubic-metre flow where the later releases have kilograms.
    `checked_against` names the releases that take the default; `by_release`
    states what another release says instead; a release in neither is refused,
    naming the flow and what was checked, so that a sixth release of a list
    cannot inherit a number nobody read for it.
    """

    def statements(self) -> list[dict]:
        return [
            _entry(by_release={"3.8": {"value": 17.9}}),
            _entry(
                source_uuid="gas-natural",
                source_name="Gas, natural, in ground",
                value=36.0,
                by_release={"3.8": {"value": 34.5, "per_unit": "m3"}},
            ),
        ]

    def test_an_earlier_release_takes_its_own_value(self):
        loaded = self.load(release="3.8", statements=self.statements())
        (coal,) = loaded.statements["coal-hard"]
        self.assertEqual(coal.value, 17.9)
        self.assertEqual(coal.per_unit, "kg")
        (gas,) = loaded.statements["gas-natural"]
        self.assertEqual(gas.value, 34.5)
        self.assertEqual(gas.per_unit, "m3")
        self.assertEqual(gas.unit, "MJ")

    def test_a_release_checked_against_takes_the_default(self):
        loaded = self.load(release="3.12", statements=self.statements())
        (coal,) = loaded.statements["coal-hard"]
        self.assertEqual(coal.value, 18.2)
        (gas,) = loaded.statements["gas-natural"]
        self.assertEqual((gas.value, gas.per_unit), (36.0, "kg"))

    def test_a_release_nobody_checked_is_refused_naming_the_flow(self):
        error = self.assertRefused("Coal, hard", release="3.13", statements=self.statements())
        message = str(error)
        self.assertIn("coal-hard", message)
        self.assertIn("3.13", message)
        for checked in ("3.9.1", "3.12", "3.8"):
            self.assertIn(checked, message)

    def test_an_empty_release_asks_nothing(self):
        loaded = self.load(release="", statements=self.statements())
        (coal,) = loaded.statements["coal-hard"]
        self.assertEqual(coal.value, 18.2)
        self.assertEqual(len(loaded.statements), 2)


class AttachTestCase(LoaderFixtureTestCase):
    """Statements land on the record of the flow they are about, and nowhere else.

    A statement is about one unit of the flow as the vendor measures it, so a
    heating value per kilogram on a flow in cubic metres is a typo and raises.
    The vendor's unit counts as well as the one the flow is carried in, because
    a manual fix may have rebased the flow since.
    """

    def loaded(self) -> PropertyStatements:
        return self.load(statements=[_entry()])

    def test_sets_the_field_on_the_matching_flow_only(self):
        coal = Flow(uuid="coal-hard", name="Coal, hard", unit="kg")
        water = Flow(uuid="water", name="Water", unit="m3")
        count = attach_property_statements([coal, water], self.loaded())
        self.assertEqual(count, 1)
        self.assertEqual(len(coal.property_statements), 1)
        self.assertEqual(coal.property_statements[0].quantity, NET_CALORIFIC_VALUE)
        self.assertIsNone(water.property_statements)

    def test_refuses_a_per_unit_of_another_kind_than_the_flows_unit(self):
        coal = Flow(
            uuid="coal-hard", name="Coal, hard", unit="m3", provided=ProvidedValues(unit="m3")
        )
        with self.assertRaises(ValueError) as caught:
            attach_property_statements([coal], self.loaded())
        message = str(caught.exception)
        self.assertIn("coal-hard", message)
        self.assertIn("'kg'", message)
        self.assertIn("'m3'", message)

    def test_the_vendors_unit_counts_when_a_fix_has_rebased_the_flow(self):
        coal = Flow(uuid="coal-hard", unit="MJ", provided=ProvidedValues(unit="kg"))
        self.assertEqual(attach_property_statements([coal], self.loaded()), 1)
        self.assertEqual(len(coal.property_statements), 1)

    def test_a_scaled_unit_of_the_same_kind_is_accepted(self):
        coal = Flow(uuid="coal-hard", unit="t", provided=ProvidedValues(unit="t"))
        self.assertEqual(attach_property_statements([coal], self.loaded()), 1)

    def test_nothing_to_attach_returns_zero(self):
        flows = [Flow(uuid="water", unit="m3")]
        self.assertEqual(attach_property_statements(flows, PropertyStatements()), 0)
        self.assertIsNone(flows[0].property_statements)


class RefusePairStatedTwiceTestCase(LoaderFixtureTestCase):
    """One number has one home.

    An override row keeps a `conversion_factor` only for a pair fact no
    property of the flow expresses -- an ore's share of its metal, mine gas at
    1.0 from plain to standard cubic metres.  Where the list's statements file
    already converts the same pair, the row's factor is a second copy that can
    disagree, and the load refuses it.
    """

    def loaded(self) -> PropertyStatements:
        return self.load(statements=[_entry()])

    def test_an_override_factor_for_a_pair_a_statement_converts_is_refused(self):
        row = {
            "route": "override",
            "conversion_factor": 18.2,
            "source": {"uuid": "coal-hard", "unit": "kg", "name": "Coal, hard"},
            "target": {"unit_name": "MJ"},
        }
        with self.assertRaises(ValueError) as caught:
            refuse_a_pair_stated_twice([row], self.loaded(), label="test-1.0")
        message = str(caught.exception)
        self.assertIn("test-1.0", message)
        self.assertIn("coal-hard", message)
        self.assertIn("test-property-statements.json", message)
        self.assertIn("18.2", message)

    def test_a_factor_for_a_pair_no_statement_bridges_passes(self):
        row = {
            "route": "override",
            "conversion_factor": 0.599,
            "source": {"uuid": "coal-hard", "unit": "kg"},
            "target": {"unit_name": "kg"},
        }
        refuse_a_pair_stated_twice([row], self.loaded(), label="test-1.0")

    def test_a_row_that_is_not_an_override_passes(self):
        row = {
            "route": "prepared",
            "conversion_factor": 18.2,
            "source": {"uuid": "coal-hard", "unit": "kg"},
            "target": {"unit_name": "MJ"},
        }
        refuse_a_pair_stated_twice([row], self.loaded(), label="test-1.0")

    def test_an_override_without_a_factor_passes(self):
        row = {
            "route": "override",
            "source": {"uuid": "coal-hard", "unit": "kg"},
            "target": {"unit_name": "MJ"},
        }
        refuse_a_pair_stated_twice([row], self.loaded(), label="test-1.0")

    def test_an_override_for_another_flow_passes(self):
        row = {
            "route": "override",
            "conversion_factor": 18.2,
            "source": {"uuid": "coal-brown", "unit": "kg"},
            "target": {"unit_name": "MJ"},
        }
        refuse_a_pair_stated_twice([row], self.loaded(), label="test-1.0")


class ReferenceQuantitiesFromIlcdTestCase(LoaderFixtureTestCase):
    """What each EF flow's unit measures, read off its ILCD flow property.

    An ILCD flow carries its reference property at a `meanValue` of 1.0 and
    any other property relative to it, so the one property at 1.0 is what the
    flow is measured in.  Two at 1.0 say nothing; a property the vocabulary
    does not name says nothing; a file nobody extracted is an empty answer,
    because a bounded build falls back to the unit's generic quantity.
    """

    def write_properties(self, values: list[dict]) -> Path:
        return self.write(
            name="flow-properties.json",
            source="EF 3.1",
            properties=[
                {"id": ILCD_NET_CALORIFIC_VALUE, "name": "Net calorific value"},
                {"id": ILCD_MASS, "name": "Mass"},
            ],
            flow_property_values=values,
            unmapped_units=[],
        )

    def test_one_property_at_one_maps_to_its_quantity(self):
        path = self.write_properties(
            [
                {
                    "flow_uuid": "hard-coal",
                    "source": "EF 3.1",
                    "properties": [
                        {"property_id": ILCD_NET_CALORIFIC_VALUE, "amount": 1.0, "meta": {}}
                    ],
                },
                {
                    "flow_uuid": "water",
                    "source": "EF 3.1",
                    "properties": [{"property_id": ILCD_MASS, "amount": 1.0, "meta": {}}],
                },
            ]
        )
        self.assertEqual(
            reference_quantities_from_ilcd(path),
            {"hard-coal": NET_CALORIFIC_VALUE, "water": MASS},
        )

    def test_a_flow_with_two_reference_properties_maps_to_nothing(self):
        path = self.write_properties(
            [
                {
                    "flow_uuid": "undecided",
                    "source": "EF 3.1",
                    "properties": [
                        {"property_id": ILCD_NET_CALORIFIC_VALUE, "amount": 1.0, "meta": {}},
                        {"property_id": ILCD_MASS, "amount": 1.0, "meta": {}},
                    ],
                }
            ]
        )
        self.assertEqual(reference_quantities_from_ilcd(path), {})

    def test_a_property_relative_to_the_reference_does_not_count(self):
        path = self.write_properties(
            [
                {
                    "flow_uuid": "hard-coal",
                    "source": "EF 3.1",
                    "properties": [
                        {"property_id": ILCD_NET_CALORIFIC_VALUE, "amount": 1.0, "meta": {}},
                        {"property_id": ILCD_MASS, "amount": 0.0549, "meta": {}},
                    ],
                }
            ]
        )
        self.assertEqual(reference_quantities_from_ilcd(path), {"hard-coal": NET_CALORIFIC_VALUE})

    def test_a_property_the_vocabulary_does_not_name_maps_to_nothing(self):
        path = self.write_properties(
            [
                {
                    "flow_uuid": "land",
                    "source": "EF 3.1",
                    "properties": [{"property_id": "no-such-property", "amount": 1.0, "meta": {}}],
                }
            ]
        )
        self.assertEqual(reference_quantities_from_ilcd(path), {})

    def test_a_missing_file_is_an_empty_answer(self):
        self.assertEqual(reference_quantities_from_ilcd(self.dir / "absent.json"), {})

    def test_a_file_without_values_raises(self):
        path = self.write(name="flow-properties.json", properties=[])
        with self.assertRaises(ValueError):
            reference_quantities_from_ilcd(path)


class ShippedFilesTestCase(unittest.TestCase):
    """The statements files the package ships load for the releases they name.

    These are the decisions the files exist for: that every registered list's
    file resolves for that list's own release, that EF's uranium is ruled
    fission energy, and that no statement names a release no manifest declares
    -- ecoinvent's one file serves five releases, and a sixth would be refused
    until somebody reads its workbook.
    """

    def setUp(self):
        self.sources = known_source_lists()
        self.files = {}
        for source in self.sources.values():
            if source.property_statements_path is not None:
                self.files.setdefault(source.property_statements_path, source.list_name)

    def test_every_source_list_loads_its_statements_for_its_own_release(self):
        for key, source in self.sources.items():
            with self.subTest(source=key):
                loaded = source.load_property_statements()
                self.assertIsInstance(loaded, PropertyStatements)

    def test_the_base_list_rules_ef_uranium_fission_energy(self):
        loaded = base_source_list().load_property_statements()
        self.assertEqual(loaded.reference_quantities.get(EF_URANIUM), FISSION_ENERGY)
        self.assertEqual(loaded.statements, {})

    def test_statement_counts(self):
        counts = {}
        for path, list_name in self.files.items():
            loaded = load_property_statements(path)
            counts[list_name] = sum(len(items) for items in loaded.statements.values())
        self.assertEqual(counts, EXPECTED_STATEMENT_COUNTS)
        self.assertEqual(sum(counts.values()), 58)

    def test_every_statement_states_one_kind_per_another(self):
        for path in self.files:
            loaded = load_property_statements(path)
            for uuid, statements in loaded.statements.items():
                for statement in statements:
                    with self.subTest(file=path.name, flow=uuid, quantity=statement.quantity):
                        unit_kind, per_kind = _kind(statement.unit), _kind(statement.per_unit)
                        self.assertTrue(unit_kind and per_kind)
                        self.assertNotEqual(unit_kind, per_kind)

    def test_every_checked_release_is_one_a_manifest_declares(self):
        for path, list_name in self.files.items():
            declared = {
                source.list_version
                for source in self.sources.values()
                if source.list_name == list_name
            }
            payload = orjson.loads(path.read_bytes())
            for index, entry in enumerate(payload.get("statements", [])):
                named = [*entry.get("checked_against", []), *(entry.get("by_release") or {})]
                for release in named:
                    with self.subTest(file=path.name, statement=index, release=release):
                        self.assertIn(release, declared)

    def test_ecoinvents_file_serves_five_releases(self):
        ecoinvent = [s for s in self.sources.values() if s.list_name == "ecoinvent"]
        self.assertEqual(len(ecoinvent), 5)
        self.assertEqual(len({s.property_statements_path for s in ecoinvent}), 1)

    def test_ecoinvent_3_8_natural_gas_is_stated_per_cubic_metre(self):
        """The one `by_release` the shipped files use, resolved both ways."""
        path = resolve_source_list("ecoinvent-3.8").property_statements_path
        payload = orjson.loads(path.read_bytes())
        (uuid,) = [
            e["source_uuid"]
            for e in payload["statements"]
            if e["source_name"] == "Gas, natural, in ground"
        ]
        (old,) = load_property_statements(path, release="3.8").statements[uuid]
        (new,) = load_property_statements(path, release="3.12").statements[uuid]
        self.assertEqual((old.value, old.per_unit), (34.5, "m3"))
        self.assertEqual((new.value, new.per_unit), (36.0, "sm3"))


if __name__ == "__main__":
    unittest.main()
