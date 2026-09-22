"""The Flow working record and the typed Change contract.

The load-bearing property is that `Flow.from_dict` / `to_dict` reproduce the
serialisation `HarmonisedFlow` produced before the dataclass existed, so the
published artifacts are unchanged by the refactor.
"""

import unittest
from dataclasses import fields

from brightway_flows.domain.flow import (
    ALIAS_TO_FIELD,
    FIELD_ALIASES,
    Flow,
    UnknownFlowFieldError,
)
from brightway_flows.domain.context_registry import (
    context_dict_for_iri,
    context_for_iri,
)
from brightway_flows.domain.models import HarmonisedFlow
from brightway_flows.pipeline.loading import _normalize_input_flow_record
from brightway_flows.pipeline import Change

SUWA = "https://vocab.brightway.one/flow-contexts/envi-wate-suwa"


def _sample_payload() -> dict:
    return {
        "uuid": "u-1",
        "source": "EF 3.1",
        "name": "Carbon dioxide",
        "cas_numbers": ["124-38-9"],
        "ec_numbers": ["204-696-9"],
        "context": ["Emissions", "Emissions to air"],
        "unit": "kg",
        "prefLabel": [{"@value": "Carbon dioxide", "@language": "en"}],
    }


class SerialisationParityTestCase(unittest.TestCase):
    """Flow must serialise exactly as HarmonisedFlow did, bar one field."""

    #: `context` is the one key where the two records deliberately disagree.
    #: `HarmonisedFlow` reads an *input file*, which ships a compartment path;
    #: `Flow.context` is the consensus context, which nothing has decided yet
    #: at the moment an input row becomes a record.  The compartment is not
    #: lost -- it is `_provided.context`, which is where the transformer that
    #: decides the context reads it from (#97).
    DECIDED_LATER = ("context",)

    #: Pipeline bookkeeping `HarmonisedFlow` never had, added by #213 and
    #: declared last so they serialise after every field it does have.
    #: `_transformed` says whether the chain has already run over this flow;
    #: `_provided` keeps the values the source list shipped, which the chain
    #: replaces rather than only adds to.
    BOOKKEEPING = ("_transformed", "_provided")

    def test_round_trip_matches_harmonised_flow(self):
        payload = _sample_payload()
        expected = HarmonisedFlow.from_dict(payload).to_dict()
        actual = Flow.from_dict(expected).to_dict()
        for key in self.BOOKKEEPING:
            self.assertIn(key, actual)
            del actual[key]
        self.assertEqual(list(actual), list(expected), "key order changed")
        for key in self.DECIDED_LATER:
            del actual[key], expected[key]
        self.assertEqual(actual, expected)

    def test_an_input_compartment_is_not_read_as_a_consensus_context(self):
        """The compartment a source list ships is not an answer to which
        consensus context the flow is in, so it does not land in the field that
        holds that answer.  It is not lost either: the same boundary function
        that builds the record puts it in `_provided`, which is where the
        transformer that *does* decide the context reads it from (#97)."""
        normalised = _normalize_input_flow_record(_sample_payload())
        flow = Flow.from_dict(HarmonisedFlow.from_dict(normalised).to_dict())
        self.assertIsNone(flow.context)
        self.assertIsNone(flow.to_dict()["context"])
        self.assertEqual(flow.provided.context, ["Emissions", "Emissions to air"])

    def test_a_consensus_context_round_trips_as_the_record(self):
        payload = _sample_payload()
        payload["context"] = context_dict_for_iri(SUWA)
        payload["context_iri"] = SUWA
        flow = Flow.from_dict(payload)
        self.assertEqual(flow.context, context_for_iri(SUWA))
        self.assertEqual(flow.to_dict()["context"], context_dict_for_iri(SUWA))
        self.assertEqual(Flow.from_dict(flow.to_dict()).context, flow.context)

    def test_the_bookkeeping_fields_serialise_last(self):
        """So that removing them leaves the previous key order intact, which is
        what the round-trip test above relies on."""
        keys = list(Flow.from_dict(_sample_payload()).to_dict())
        self.assertEqual(keys[-len(self.BOOKKEEPING):], list(self.BOOKKEEPING))

    def test_an_unmarked_flow_round_trips_as_unmarked(self):
        """A payload written before #213 has no `_transformed`.  Defaulting it
        to False is right: it predates the flag, so nothing marked it, and the
        merge would rather re-show a flow than silently skip one."""
        flow = Flow.from_dict(_sample_payload())
        self.assertFalse(flow.transformed)
        self.assertFalse(Flow.from_dict(flow.to_dict()).transformed)

    def test_the_provided_values_round_trip_as_a_record(self):
        payload = _sample_payload()
        payload["_provided"] = {"name": "MCPA", "synonyms": ["Agroxone"]}
        flow = Flow.from_dict(payload)
        self.assertEqual(flow.provided.name, "MCPA")
        again = Flow.from_dict(flow.to_dict())
        self.assertEqual(again.provided.synonyms, ["Agroxone"])

    def test_field_order_mirrors_harmonised_flow(self):
        """to_dict() key order comes from declaration order, so it must match.

        Fields that HarmonisedFlow does not declare land in its
        ``additional_properties`` and serialise after the model fields, so Flow
        must declare them last, in the same relative order.
        """
        model_order = [
            f.alias or name
            for name, f in HarmonisedFlow.model_fields.items()
            if name != "additional_properties"
        ]
        flow_order = [
            FIELD_ALIASES.get(f.name, f.name)
            for f in fields(Flow)
            if f.name != "extra"
        ]
        self.assertEqual(
            flow_order[: len(model_order)], model_order,
            "Flow's leading fields must mirror HarmonisedFlow's declaration order",
        )
        trailing = flow_order[len(model_order):]
        self.assertEqual(
            set(trailing) & set(model_order), set(),
            "a trailing field must not duplicate a HarmonisedFlow field",
        )

    def test_optional_fields_absent_rather_than_null(self):
        """A non-deprecated flow must not gain owl:deprecated etc."""
        out = Flow(uuid="u-1").to_dict()
        for absent in (
            "name", "unit", "prefLabel",
            *(FIELD_ALIASES[k] for k in
              ("skos_definition", "owl_deprecated", "dcterms_is_replaced_by")),
            "is_replaced_by_uuid", "cas_match_labels", "cas_number_sources",
        ):
            with self.subTest(field=absent):
                self.assertNotIn(absent, out)

    def test_aliased_keys_round_trip(self):
        payload = {"uuid": "u-1"}
        for attr, alias in FIELD_ALIASES.items():
            payload[alias] = {"x": "y"} if attr == "pipeline_sources" else True
        flow = Flow.from_dict(payload)
        self.assertTrue(flow.owl_deprecated)
        self.assertEqual(flow.pipeline_sources, {"x": "y"})
        out = flow.to_dict()
        for alias in FIELD_ALIASES.values():
            with self.subTest(alias=alias):
                self.assertIn(alias, out)

    def test_alias_maps_are_inverses(self):
        self.assertEqual(
            ALIAS_TO_FIELD, {v: k for k, v in FIELD_ALIASES.items()}
        )


class ExtraFieldsTestCase(unittest.TestCase):
    def test_unknown_keys_are_preserved_not_dropped(self):
        payload = dict(_sample_payload(), elementary_flow_categorization=["a", "b"])
        flow = Flow.from_dict(payload)
        self.assertEqual(flow.extra["elementary_flow_categorization"], ["a", "b"])
        self.assertEqual(
            flow.to_dict()["elementary_flow_categorization"], ["a", "b"]
        )

    def test_records_have_no_get_shim(self):
        """Reading by attribute is the point: a bad field must raise, not be None.

        A `get()` returning None for an unknown field is how three dead branches
        survived in the transformers -- guards on `origin_qualifier`, which
        `Flow` did not have then and does now, so they never fired.  The example
        has had to move twice for that reason, `parent_flow_object_id` being the
        second; `molecular_formula` is a property of the substance and belongs
        to `FlowObject`, so it will not become one here.
        """
        flow = Flow.from_dict(_sample_payload())
        self.assertFalse(hasattr(flow, "get"))
        with self.assertRaises(AttributeError):
            flow.molecular_formula  # noqa: B018 -- the access is the assertion

    def test_extras_are_read_from_the_bag_explicitly(self):
        flow = Flow.from_dict(dict(_sample_payload(), weird_key=7))
        self.assertEqual(flow.extra["weird_key"], 7)
        self.assertEqual(flow.extra.get("missing", "fallback"), "fallback")


class FieldResolutionTestCase(unittest.TestCase):
    def test_attribute_and_alias_both_resolve(self):
        self.assertEqual(Flow.resolve_field("prefLabel"), "prefLabel")
        self.assertEqual(
            Flow.resolve_field(FIELD_ALIASES["skos_definition"]), "skos_definition"
        )

    def test_unknown_field_rejected(self):
        with self.assertRaises(UnknownFlowFieldError):
            Flow.resolve_field("prefLable")

    def test_extra_is_not_a_targetable_field(self):
        """Changes must not be able to write into the passthrough bag."""
        with self.assertRaises(UnknownFlowFieldError):
            Flow.resolve_field("extra")


class TypedChangeTestCase(unittest.TestCase):
    """A misspelled field must fail where it is written, not silently vanish."""

    def test_valid_field_accepted(self):
        change = Change("u-1", "prefLabel", [{"@value": "x"}])
        self.assertEqual(change.field, "prefLabel")

    def test_alias_normalised_to_attribute_name(self):
        change = Change("u-1", FIELD_ALIASES["skos_definition"], [])
        self.assertEqual(change.field, "skos_definition")

    def test_misspelled_field_rejected(self):
        with self.assertRaises(UnknownFlowFieldError):
            Change("u-1", "prefLable", [])

    def test_every_field_a_transformer_targets_exists(self):
        """Guards the fields found by scanning Change() call sites.

        `cas_number_sources` was missed by an earlier scan that only looked at
        positional arguments; it is only reachable via the keyword form.
        """
        targeted = {
            "altLabel", "cas_match_labels", "cas_number_sources", "cas_numbers",
            "context", "context_iri", "ec_numbers", "name", "prefLabel",
            "properties", "references", "skos_definition", "synonyms", "unit",
            "unit_iri",
        }
        self.assertEqual(targeted - Flow.field_names(), set())

    def test_setattr_applies_cleanly(self):
        """The engine applies changes with setattr; confirm the field is writable."""
        flow = Flow.from_dict(_sample_payload())
        change = Change(flow.uuid, "unit_iri", "https://example.org/kg")
        setattr(flow, change.field, change.new_value)
        self.assertEqual(flow.unit_iri, "https://example.org/kg")
        self.assertEqual(flow.to_dict()["unit_iri"], "https://example.org/kg")


if __name__ == "__main__":
    unittest.main()


class LabelMarkupTestCase(unittest.TestCase):
    """Presentation markup must not reach a stored or published label.

    ChEBI names carry it -- `<span class="text-smallcaps">D</span>-Glucitol` --
    and `prefLabel`/`altLabel` are read as text downstream. Only the webapp
    stripped it, at render time, so 962 alt-labels across 247 flows would have
    been published with raw HTML once consensus matching started working.
    """

    def test_tags_are_removed_from_a_string_label(self):
        from brightway_flows.domain.labels import coerce_label

        label = coerce_label(
            '<span class="text-smallcaps">D</span>-Glucitol', default_source="chebi"
        )
        self.assertEqual(label.value, "D-Glucitol")

    def test_tags_are_removed_from_a_language_tagged_label(self):
        from brightway_flows.domain.labels import coerce_label

        label = coerce_label(
            {"@value": "<i>N</i>-Nitrosamine", "@language": "en"}, default_source="x"
        )
        self.assertEqual(label.value, "N-Nitrosamine")

    def test_the_wrapped_text_is_kept_not_dropped(self):
        """The letter inside a smallcaps span is the meaningful part."""
        from brightway_flows.domain.labels import strip_markup

        self.assertEqual(strip_markup("<b>alpha</b>-Pinene"), "alpha-Pinene")

    def test_a_plain_label_is_untouched(self):
        from brightway_flows.domain.labels import strip_markup

        for text in ("Carbon dioxide", "1,4:3,6-dianhydro-", "PM2.5"):
            with self.subTest(text):
                self.assertEqual(strip_markup(text), text)

    def test_angle_brackets_that_are_not_tags_survive(self):
        """`<->` in a carbohydrate name is a glycosidic linkage.

        `beta-D-Fruf-(2<->1)-alpha-D-Glcp` is sucrose. Matching anything
        between angle brackets turned it into `(21)`, silently, in eleven
        published alt labels.
        """
        from brightway_flows.domain.labels import strip_markup

        for text in (
            "beta-D-Fruf-(2<->1)-alpha-D-Glcp",
            "alcohols, C12-14, ethoxylated, < 2.5 eo",
            "2 < 3 and 4 > 1",
        ):
            with self.subTest(text):
                self.assertEqual(strip_markup(text), text)

    def test_character_references_are_resolved(self):
        """Stripping tags alone leaves `N&#39;-` in a published name."""
        from brightway_flows.domain.labels import strip_markup

        self.assertEqual(
            strip_markup("N-D-Glucosyl-(2)-N&#39;-nitrosomethylharnstoff"),
            "N-D-Glucosyl-(2)-N'-nitrosomethylharnstoff",
        )
        self.assertEqual(strip_markup("&alpha;-Pinene"), "α-Pinene")

    def test_an_escaped_tag_stays_literal_text(self):
        """References resolve after tags are removed, not before.

        Otherwise `&lt;i&gt;` would become a tag and then vanish, deleting text
        the source deliberately escaped.
        """
        from brightway_flows.domain.labels import strip_markup

        self.assertEqual(
            strip_markup("a &lt;i&gt;literal&lt;/i&gt; escape"),
            "a <i>literal</i> escape",
        )

    def test_malformed_markup_is_still_removed(self):
        """CAS Common Chemistry emits this one, with crossed nesting."""
        from brightway_flows.domain.labels import strip_markup

        self.assertEqual(
            strip_markup(
                '<span class="text-smallcaps">D</smallcap>'
                "<smallcap>L</span>-α-Tocopherol"
            ),
            "DL-α-Tocopherol",
        )

    def test_comments_and_declarations_are_removed(self):
        from brightway_flows.domain.labels import strip_markup

        self.assertEqual(strip_markup("<!-- note -->Benzene"), "Benzene")
        self.assertEqual(strip_markup("<?xml version='1.0'?>Benzene"), "Benzene")

    def test_labels_differing_only_in_markup_share_a_canonical_value(self):
        from brightway_flows.domain.labels import canonical_label_value

        self.assertEqual(
            canonical_label_value('<span class="text-smallcaps">L</span>-Tryptophan'),
            canonical_label_value("L-Tryptophan"),
        )
