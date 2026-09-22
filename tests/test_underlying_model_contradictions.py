"""EF 3.1 says a kilogram of biphenyl causes 0.2 cases of disease, and the model
it is derived from says a millionth of that.

EF 3.1's toxicity categories are USEtox 2.1, by the JRC's own account. For the
two human-health ones the LC-Impact result workbook is the same computation --
cases of disease, published as the years of healthy life they cost -- so where
the two disagree, they disagree about the substance. For four substances they
are more than a hundredfold apart in **every** compartment, the narrowest 133×
and the widest 1,381,461×.

Freshwater ecotoxicity is not compared, whatever the gap. The workbook publishes
LC-Impact's ecosystem-quality result there, in potentially disappeared fraction
of species, and EF's CTUe is a potentially affected fraction: a ratio across two
models is not evidence that either is wrong.

Neither published implementation can see it. The JRC's says 0.19957 because EF
3.1 says 0.19957, and the ecoinvent Centre's says the same where it says
anything, because it transcribed the same file. Two transcriptions of one file
agreeing is not evidence about the file, and `Derivation.AGREED` would call it
agreement -- which is the one thing tested here that is not obvious: a
contradicted pair is withheld *even where both implementations agree*.

What the fix is not: a change to either transcription. EF 3.1 states 0.19957 and
this list goes on publishing that under the JRC's name, because that is what the
JRC published. Only the consensus implementation withholds, and only until a
curator rules -- which is why the third queue takes the same two verdicts as the
other two, and why a `publish` ruling can name the JRC and put the number back.

#107. `plans/lcia-factors.md` §4.5.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import orjson

from brightway_flows.domain.lcia.crosswalk import impact_categories
from brightway_flows.domain.lcia.records import StatedFactor, stated_category
from brightway_flows.domain.lcia.crosswalk import ef_method
from brightway_flows.lcia.consensus import Derivation, derive, queue_items
from brightway_flows.lcia.contradictions import (
    comparable_categories,
    CONTRADICTION_RATIO,
    MINIMUM_COMPARTMENTS,
    UNDERLYING_MODEL_FILEPATH,
    UnderlyingModelError,
    contradictions,
    load_underlying_model_factors,
)
from brightway_flows.lcia.matching import MatchedFactor
from brightway_flows.lcia.rulings import FactorRuling, Verdict
from brightway_flows.pipeline.review_records import ReviewQueue, Severity

#: EF 3.1's three implementations, read from its method file rather than from an
#: enum: an implementation belongs to a method, and which three these are is what
#: `data/lcia-impact-categories.json` says.
_METHOD = ef_method()
JRC_IMPL = _METHOD.reference
ECOINVENT_IMPL = _METHOD.implementation("ecoinvent-centre")
CONSENSUS_IMPL = _METHOD.consensus
IMPLEMENTATION_NAMES = {row.name for row in _METHOD.implementations}

SLUG = "human-toxicity-non-cancer"
PART = "human-toxicity-non-cancer-organics"
SUBSTANCE = "fo-biphenyl"
CAS = "92-52-4"
JRC = JRC_IMPL.name
ECOINVENT = ECOINVENT_IMPL.name

#: Biphenyl's six compartments, as EF 3.1 states them and as USEtox 2.1 does.
#: The real numbers, because a test of a hundredfold rule written with 1 and 200
#: would pass under a rule that compared the wrong pair of things.
COMPARTMENTS: tuple[tuple[str, str, float, float], ...] = (
    ("cf-air-urban", "https://vocab.brightway.one/flow-contexts/envi-air-grle-ur10pesq",
     0.19957, 1.44463e-07),
    ("cf-air-rural", "https://vocab.brightway.one/flow-contexts/envi-air-mest15me-ru10pesq",
     0.014939, 2.4822e-08),
    ("cf-water-fresh", "https://vocab.brightway.one/flow-contexts/envi-wate-suwa",
     0.0044065, 2.51061e-07),
    ("cf-water-sea", "https://vocab.brightway.one/flow-contexts/envi-wate-ocea",
     0.00015794, 1.7085e-08),
    ("cf-soil-agri", "https://vocab.brightway.one/flow-contexts/envi-grou-agri",
     0.00089871, 9.30296e-09),
    ("cf-soil-noag", "https://vocab.brightway.one/flow-contexts/envi-grou-noag",
     0.0008987, 1.46125e-09),
)

FLOWS = {
    uuid: {
        "flow_object_id": SUBSTANCE,
        "label": "Biphenyl",
        "context_iri": context_iri,
        "context_display": context_iri.rsplit("/", 1)[-1],
    }
    for uuid, context_iri, _published, _model in COMPARTMENTS
}
NAMES = {SLUG: "Human toxicity, non-cancer"}


def _matched(uuid: str, amount: float, *, ecoinvent: bool = False) -> MatchedFactor:
    return MatchedFactor(
        elementary_flow_uuid=uuid,
        factor=StatedFactor(
            category=stated_category(
                uuid=None if ecoinvent else "7cfdcfcf-b222-4b26-888a-a55f9fbf7ac8",
                name=(
                    "human toxicity: non-carcinogenic"
                    if ecoinvent
                    else "Human toxicity, non-cancer"
                ),
            ),
            flow_uuid="",
            amount=amount,
        ),
        source_flow_uuid="ei-1" if ecoinvent else None,
    )


def _stated(
    *, slug: str = SLUG, geography: str = "", ecoinvent: bool = False, scale: float = 1.0
) -> dict[tuple[str, str, str], MatchedFactor]:
    """The reference implementation's factors for biphenyl, keyed as `derive` keys."""
    return {
        (uuid, slug, geography): _matched(
            uuid, published * scale, ecoinvent=ecoinvent
        )
        for uuid, _context_iri, published, _model in COMPARTMENTS
    }


def _evidence(**overrides) -> dict:
    row = {
        "cas_number": CAS,
        "substance": "Biphenyl",
        "model_substance": "biphenyl",
        "category_slug": SLUG,
        "category": "Human toxicity, non-cancer",
        "unit": "CTUh",
        "stated": [
            {
                "compartment": context_iri.rsplit("-", 1)[-1],
                "context_iri": context_iri,
                "model_amount": model,
                "reference_amount": published,
            }
            for _uuid, context_iri, published, model in COMPARTMENTS
        ],
    }
    row.update(overrides)
    return row


def _file(rows: list[dict], **overrides) -> dict:
    payload = {
        "schema_version": 1,
        "method": _METHOD.slug,
        "description": "what the model underneath states",
        "model": {
            "name": "USEtox 2.1",
            "read_from": ["USEtox2.1_LC-Impact_v2_results_HUMANTOX_20190326.xlsx"],
            "sheet": "all impacts, long-term",
            "block": "Global average continent (default)",
            "measured_on": "2026-08-17",
        },
        "substances": rows,
    }
    payload.update(overrides)
    return payload


def _load(payload: dict):
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "underlying.json"
        path.write_bytes(orjson.dumps(payload))
        return load_underlying_model_factors(path)


def _contradicted(payload: dict | None = None, **kwargs):
    evidence = _load(payload if payload is not None else _file([_evidence()]))
    arguments = {
        "stated": _stated(),
        "flows": FLOWS,
        "substances": {CAS: [SUBSTANCE]},
    }
    arguments.update(kwargs)
    return contradictions(evidence, **arguments)


def _derive(*, jrc, ecoinvent=None, contradicted=None, rulings=None):
    return derive(
        stated={
            JRC_IMPL: jrc,
            ECOINVENT_IMPL: ecoinvent or {},
        },
        reference=JRC_IMPL,
        substances={uuid: SUBSTANCE for uuid in FLOWS},
        rulings={ruling.key: ruling for ruling in rulings or ()},
        contradicted=_contradicted() if contradicted is None else contradicted,
    )


class TheCuratedEvidenceTestCase(unittest.TestCase):
    """`data/lcia-underlying-model-factors.json` is measurement, and this is what
    measurement has to be: numbers a rule could select, about categories this list
    can name, over enough compartments to be about the substance."""

    @classmethod
    def setUpClass(cls):
        cls.rows = load_underlying_model_factors()

    def test_it_holds_the_thirty_eight_pairs_the_issue_found(self):
        self.assertEqual(len(self.rows), 38)
        self.assertEqual(
            sum(len(row.stated) for row in self.rows),
            228,
            "six compartments per pair, which is what the comparison covered",
        )

    def test_every_row_names_a_category_this_list_publishes(self):
        """Evidence filed under a category the crosswalk does not define is
        evidence nothing will ever compare against a factor."""
        slugs = {category.slug for category in impact_categories()}
        for row in self.rows:
            with self.subTest(substance=row.substance):
                self.assertIn(row.category_slug, slugs)

    def test_the_three_toxicity_categories_are_the_only_ones(self):
        """USEtox 2.1 is what EF 3.1's *toxicity* categories are derived from. A
        row about acidification would be a claim nobody made."""
        self.assertEqual(
            {row.category_slug for row in self.rows},
            {"ecotoxicity-freshwater", "human-toxicity-non-cancer"},
        )

    def test_the_ecotoxicity_rows_are_kept_and_asked_nothing_about(self):
        """34 of the 38 are freshwater ecotoxicity, and a build compares none of
        them.  They stay in the file because they were measured and are somebody
        else's published numbers -- deleting them would make the measurement
        unrepeatable and leave nothing saying why the category is absent."""
        compared = [
            row for row in self.rows if row.category_slug in comparable_categories(_METHOD.slug)
        ]
        self.assertEqual(len(self.rows) - len(compared), 34)
        self.assertEqual(
            sorted(row.substance for row in compared),
            [
                "2,4/2,6-toluenediisocyanate (mixture)",
                "Benfluralin",
                "Biphenyl",
                "O-phenylphenol",
            ],
        )

    def test_every_row_states_enough_compartments_to_be_about_the_substance(self):
        for row in self.rows:
            with self.subTest(substance=row.substance):
                self.assertGreaterEqual(len(row.stated), MINIMUM_COMPARTMENTS)

    def test_every_row_is_past_the_threshold_in_every_compartment(self):
        """The file states no row the rule would decline. It could -- nothing
        stops a measurement being close -- and a file where the two disagree
        about what belongs in it is a file nobody can read."""
        for row in self.rows:
            for amount in row.stated:
                ratio = max(
                    amount.reference_amount / amount.model_amount,
                    amount.model_amount / amount.reference_amount,
                )
                with self.subTest(substance=row.substance, at=amount.compartment):
                    self.assertGreater(ratio, CONTRADICTION_RATIO)

    def test_biphenyl_is_in_it_with_ef_s_own_number(self):
        """The worked example, and the check that `reference_amount` is EF's
        number verbatim rather than something rounded on the way in."""
        row = next(
            row
            for row in self.rows
            if row.cas_number == CAS and row.category_slug == SLUG
        )
        urban = next(
            amount
            for amount in row.stated
            if amount.compartment == "emission to urban air close to ground"
        )
        self.assertEqual(urban.reference_amount, 0.19957)
        self.assertLess(urban.model_amount, 1e-6)

    def test_the_model_is_named_and_says_where_it_was_read_from(self):
        """Every number in the file is a claim about somebody else's release, and
        a claim about a release nobody can find again is not reviewable."""
        for row in self.rows:
            with self.subTest(substance=row.substance):
                self.assertEqual(row.model.name, "USEtox 2.1")
                self.assertTrue(row.model.read_from)
                self.assertTrue(row.model.sheet)


class AMalformedFileRaisesTestCase(unittest.TestCase):
    """Rather than being skipped: evidence quietly dropped is a question this list
    stops asking without anybody deciding to stop asking it (rule 14)."""

    def test_a_file_from_another_schema_version(self):
        with self.assertRaises(UnderlyingModelError):
            _load(_file([_evidence()], schema_version=99))

    def test_a_file_naming_no_model(self):
        payload = _file([_evidence()])
        del payload["model"]
        with self.assertRaises(UnderlyingModelError):
            _load(payload)

    def test_a_model_with_no_file_behind_it(self):
        payload = _file([_evidence()])
        payload["model"]["read_from"] = []
        with self.assertRaises(UnderlyingModelError):
            _load(payload)

    def test_a_category_the_crosswalk_does_not_define(self):
        with self.assertRaises(UnderlyingModelError):
            _load(_file([_evidence(category_slug="human-toxicity-obscure")]))

    def test_a_row_stating_no_numbers(self):
        with self.assertRaises(UnderlyingModelError):
            _load(_file([_evidence(stated=[])]))

    def test_an_amount_with_no_compartment(self):
        row = _evidence()
        row["stated"][0] = dict(row["stated"][0], context_iri="")
        with self.assertRaises(UnderlyingModelError):
            _load(_file([row]))

    def test_a_model_amount_of_zero(self):
        """A ratio is not defined across zero, and a model that states nothing
        about a substance should not have a row saying it does."""
        row = _evidence()
        row["stated"][0] = dict(row["stated"][0], model_amount=0.0)
        with self.assertRaises(UnderlyingModelError):
            _load(_file([row]))

    def test_a_model_amount_that_is_not_a_number(self):
        row = _evidence()
        row["stated"][0] = dict(row["stated"][0], model_amount="1e-7")
        with self.assertRaises(UnderlyingModelError):
            _load(_file([row]))

    def test_the_same_substance_and_category_twice(self):
        with self.assertRaises(UnderlyingModelError):
            _load(_file([_evidence(), _evidence()]))

    def test_a_missing_file_is_not_an_error(self):
        """It is a build with no evidence, which asks nothing and publishes
        everything -- the state every build was in before #107."""
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(
                load_underlying_model_factors(Path(directory) / "absent.json"), ()
            )


class TheRuleIsCodeAndTheEvidenceIsDataTestCase(unittest.TestCase):
    """What makes a row a contradiction is measured here, against the numbers this
    build states -- so a re-transcription that fixes biphenyl publishes it again
    with nobody editing the file."""

    def test_a_pair_apart_in_every_compartment_is_contradicted(self):
        found = _contradicted()
        self.assertIn((SUBSTANCE, SLUG), found)
        contradiction = found[(SUBSTANCE, SLUG)]
        self.assertEqual(len(contradiction.compared), len(COMPARTMENTS))
        self.assertGreater(contradiction.narrowest, CONTRADICTION_RATIO)
        self.assertGreater(contradiction.widest, 1_000_000)

    def test_an_ecotoxicity_pair_is_not_compared_however_wide_the_gap(self):
        """The same numbers, filed under freshwater ecotoxicity, ask nothing.

        Biphenyl's own gap, moved to the category where the two publications are
        not stating one quantity: the workbook's ecotoxicity sheet is
        LC-Impact's ecosystem-quality result in potentially disappeared fraction
        of species and EF's CTUe is a potentially affected fraction.  A ratio
        across that measures the two models, and no gap makes it measure the
        substance -- which is why this is a rule about the category and not a
        larger threshold.
        """
        slug = "ecotoxicity-freshwater"
        self.assertNotIn(slug, comparable_categories(_METHOD.slug))
        found = _contradicted(
            _file([_evidence(category_slug=slug, category="Ecotoxicity, freshwater",
                             unit="CTUe")]),
            stated=_stated(slug=slug),
        )
        self.assertEqual(found, {})

    def test_the_categories_compared_are_the_two_human_health_ones(self):
        """Stated here rather than only in the constant, because widening it is
        the change this test exists to make somebody argue for."""
        self.assertEqual(
            set(comparable_categories(_METHOD.slug)),
            {"human-toxicity-cancer", "human-toxicity-non-cancer"},
        )

    def test_a_build_whose_numbers_have_moved_publishes_again(self):
        """The staleness contract `FactorRuling.covers` has, in the one shape it
        can take here: EF re-transcribed, the two now agree, and the file has not
        changed. Nothing is withheld and the run says so."""
        agreeing = {
            (uuid, SLUG, ""): _matched(uuid, model * 1.5)
            for uuid, _context_iri, _published, model in COMPARTMENTS
        }
        self.assertEqual(_contradicted(stated=agreeing), {})

    def test_one_compartment_inside_the_threshold_is_not_a_contradiction(self):
        """Every compartment has to disagree. A gap in one and not another is the
        two models routing an emission differently, which is ordinary."""
        stated = _stated()
        uuid = COMPARTMENTS[0][0]
        stated[(uuid, SLUG, "")] = _matched(uuid, COMPARTMENTS[0][3] * 10)
        self.assertEqual(_contradicted(stated=stated), {})

    def test_too_few_compartments_to_compare_is_not_a_contradiction(self):
        """A substance characterised in one place is never withdrawn on one
        number."""
        stated = _stated()
        for uuid, _context_iri, _published, _model in COMPARTMENTS[MINIMUM_COMPARTMENTS - 1:]:
            del stated[(uuid, SLUG, "")]
        self.assertEqual(_contradicted(stated=stated), {})

    def test_a_stated_zero_is_not_a_hundredfold_of_anything(self):
        """#47 made a stated zero a statement rather than an absence, and it is
        one here too: EF saying a substance does nothing is not EF stating a
        number two orders of magnitude from the model's."""
        stated = _stated()
        zeroed = 0
        for uuid, _context_iri, _published, _model in COMPARTMENTS:
            if zeroed < len(COMPARTMENTS) - MINIMUM_COMPARTMENTS + 1:
                stated[(uuid, SLUG, "")] = _matched(uuid, 0.0)
                zeroed += 1
        self.assertEqual(_contradicted(stated=stated), {})

    def test_a_located_factor_is_not_compared(self):
        """The model's numbers are for a global average continent, and EF's 180
        located toxicity factors are a different question."""
        self.assertEqual(_contradicted(stated=_stated(geography="ES-CA")), {})

    def test_a_registry_number_this_list_does_not_have_asks_nothing(self):
        self.assertEqual(_contradicted(substances={}), {})

    def test_a_registry_number_two_substances_carry_withholds_both(self):
        """Two flow objects on one CAS is #34's question and is not answered
        here: the evidence is about the number the registry number names, and
        this list cannot say which of the two is meant."""
        stated = dict(_stated())
        stated.update({
            (f"{uuid}-b", SLUG, ""): _matched(f"{uuid}-b", published)
            for uuid, _context_iri, published, _model in COMPARTMENTS
        })
        flows = dict(FLOWS)
        flows.update({
            f"{uuid}-b": {**FLOWS[uuid], "flow_object_id": "fo-other"}
            for uuid, _context_iri, _published, _model in COMPARTMENTS
        })
        found = _contradicted(
            stated=stated, flows=flows, substances={CAS: [SUBSTANCE, "fo-other"]}
        )
        self.assertEqual(sorted(found), [(SUBSTANCE, SLUG), ("fo-other", SLUG)])

    def test_the_organic_half_of_the_category_is_withheld_with_the_whole(self):
        """EF publishes one number twice -- under the aggregate category and under
        the half the substance falls in -- and withholding one of the two would
        withhold half a question and publish the other half."""
        stated = {**_stated(), **_stated(slug=PART)}
        found = _contradicted(stated=stated)
        self.assertEqual(sorted(found), sorted([(SUBSTANCE, SLUG), (SUBSTANCE, PART)]))

    def test_each_half_is_compared_on_its_own_numbers(self):
        """Widening to the group decides nothing: the part is contradicted only if
        the part's own factors are."""
        stated = {**_stated(), **_stated(slug=PART, scale=1e-7)}
        found = _contradicted(stated=stated)
        self.assertEqual(sorted(found), [(SUBSTANCE, SLUG)])


class AContradictedPairIsWithheldTestCase(unittest.TestCase):
    """Whatever the implementations say, including where they agree."""

    def test_a_sole_factor_is_not_published(self):
        published, questions, _applied = _derive(jrc=_stated())
        self.assertEqual(published, [])
        self.assertEqual(
            {queue for queue, _slug, _evidence in questions},
            {str(ReviewQueue.CONTRADICTED_FACTOR)},
        )
        self.assertEqual(len(questions), len(COMPARTMENTS))

    def test_two_implementations_agreeing_is_not_evidence_about_the_file(self):
        """The case that made this a queue rather than a tolerance: both
        transcribe EF, so both say 0.19957, and `agreed` would publish it as a
        number nobody disputes."""
        published, questions, _applied = _derive(
            jrc=_stated(), ecoinvent=_stated(ecoinvent=True)
        )
        self.assertEqual(published, [])
        self.assertEqual(
            {queue for queue, _slug, _evidence in questions},
            {str(ReviewQueue.CONTRADICTED_FACTOR)},
        )

    def test_a_contested_pair_asks_the_larger_question_first(self):
        """Where the two implementations disagree *and* the model contradicts
        both, settling which of the two readings is right publishes a number
        USEtox says is wrong by five orders of magnitude."""
        _published, questions, _applied = _derive(
            jrc=_stated(), ecoinvent=_stated(ecoinvent=True, scale=3.0)
        )
        self.assertEqual(
            {queue for queue, _slug, _evidence in questions},
            {str(ReviewQueue.CONTRADICTED_FACTOR)},
        )

    def test_an_uncontradicted_substance_is_published_as_before(self):
        """The withholding is 38 substances, not a change of policy about
        factors."""
        other = {("cf-other", SLUG, ""): _matched("cf-other", 1.0)}
        published, questions, _applied = _derive(jrc={**_stated(), **other})
        self.assertEqual(
            [(row.elementary_flow_uuid, row.derivation) for row in published],
            [("cf-other", str(Derivation.SOLE))],
        )
        self.assertTrue(questions)

    def test_the_transcriptions_are_untouched(self):
        """`derive` publishes the consensus implementation and nothing else; the
        JRC's factors reach the tables from `_transcribe`, which never sees a
        contradiction. Stated as a test because "only in our implementation" is
        the whole shape of the fix."""
        stated = _stated()
        _published, _questions, _applied = _derive(jrc=stated)
        self.assertEqual(
            [row.factor.amount for row in stated.values()],
            [published for _uuid, _iri, published, _model in COMPARTMENTS],
        )


class TheQuestionCarriesBothNumbersTestCase(unittest.TestCase):
    """A curator is being asked to weigh a third party's model against the
    method's own publisher, so the row says what each states and where the
    model's number was read from."""

    def _item(self, **kwargs):
        _published, questions, _applied = _derive(jrc=_stated(), **kwargs)
        items = queue_items(
            questions, method=_METHOD.slug, flows=FLOWS, category_names=NAMES
        )
        return items[ReviewQueue.CONTRADICTED_FACTOR][0]

    def test_one_question_per_substance_and_category(self):
        item = self._item()
        self.assertEqual(item.item_key, f"{_METHOD.slug}|{SUBSTANCE}|{SLUG}")
        self.assertEqual(item.payload["factor_count"], len(COMPARTMENTS))
        self.assertEqual(item.severity, Severity.BLOCKING)

    def test_it_names_the_model_and_the_files_it_was_read_from(self):
        payload = self._item().payload
        self.assertEqual(payload["contradicts"]["model"], "USEtox 2.1")
        self.assertTrue(payload["contradicts"]["read_from"])

    def test_it_states_both_numbers_per_compartment(self):
        compared = self._item().payload["contradicts"]["compared"]
        self.assertEqual(len(compared), len(COMPARTMENTS))
        urban = next(
            row
            for row in compared
            if row["context_iri"].endswith("envi-air-grle-ur10pesq")
        )
        self.assertEqual(urban["published_amount"], 0.19957)
        self.assertEqual(urban["model_amount"], 1.44463e-07)
        self.assertGreater(urban["ratio"], 1_000_000)

    def test_the_queue_sorts_on_the_gap_the_question_is_about(self):
        """Not on the gap between the two implementations, which is zero here
        because both transcribe one file."""
        payload = self._item(ecoinvent=_stated(ecoinvent=True)).payload
        self.assertEqual(
            payload["worst_ratio"], payload["contradicts"]["widest_ratio"]
        )

    def test_the_title_says_who_contradicts_it(self):
        self.assertIn("USEtox 2.1", self._item().title)


class ACuratorCanPutTheNumberBackTestCase(unittest.TestCase):
    """The queue is a question, not a verdict. A ruling that has read the JRC's
    report and found the adjustment deliberate publishes EF's number again."""

    def _ruling(self, **overrides) -> FactorRuling:
        fields = {
            "method": _METHOD.slug,
            "flow_object_id": SUBSTANCE,
            "category_slug": SLUG,
            "queue": str(ReviewQueue.CONTRADICTED_FACTOR),
            "verdict": Verdict.PUBLISH,
            "implemented_by": JRC,
            "comment": "the JRC report explains this one",
            "ruled_about": {
                JRC: tuple(published for _u, _i, published, _m in COMPARTMENTS)
            },
        }
        fields.update(overrides)
        return FactorRuling(**fields)

    def test_a_publish_ruling_republishes_the_method_s_number(self):
        published, _questions, applied = _derive(
            jrc=_stated(), rulings=[self._ruling()]
        )
        self.assertEqual(
            sorted(row.factor.amount for row in published),
            sorted(published_amount for _u, _i, published_amount, _m in COMPARTMENTS),
        )
        self.assertEqual(
            {row.derivation for row in published}, {str(Derivation.RULED)}
        )
        self.assertEqual(sum(applied.values()), len(COMPARTMENTS))

    def test_a_decline_publishes_nothing_and_says_so_on_the_record(self):
        published, questions, _applied = _derive(
            jrc=_stated(),
            rulings=[self._ruling(verdict=Verdict.DECLINE, implemented_by="")],
        )
        self.assertEqual(published, [])
        items = queue_items(
            questions, method=_METHOD.slug, flows=FLOWS, category_names=NAMES
        )
        item = items[ReviewQueue.CONTRADICTED_FACTOR][0]
        self.assertEqual(item.severity, Severity.INFO)
        self.assertEqual(item.payload["ruling"]["decision"], "decline")

    def test_a_ruling_written_for_the_contested_queue_does_not_settle_this(self):
        """The queue is part of a ruling's key, and this is why: "which of these
        two is right" is not an answer to "is either of them"."""
        published, questions, applied = _derive(
            jrc=_stated(),
            ecoinvent=_stated(ecoinvent=True, scale=3.0),
            rulings=[
                self._ruling(
                    queue=str(ReviewQueue.CONTESTED_FACTOR),
                    ruled_about={
                        JRC: tuple(p for _u, _i, p, _m in COMPARTMENTS),
                        ECOINVENT: tuple(p * 3.0 for _u, _i, p, _m in COMPARTMENTS),
                    },
                )
            ],
        )
        self.assertEqual(published, [])
        self.assertEqual(sum(applied.values()), 0)
        items = queue_items(
            questions, method=_METHOD.slug, flows=FLOWS, category_names=NAMES
        )
        self.assertEqual(
            items[ReviewQueue.CONTRADICTED_FACTOR][0].severity, Severity.BLOCKING
        )


class TheFileIsRegisteredTestCase(unittest.TestCase):
    def test_it_ships_with_the_package(self):
        self.assertTrue(UNDERLYING_MODEL_FILEPATH.exists())

    def test_the_register_names_the_module_that_applies_it(self):
        from brightway_flows.domain.rulings import CURATED_FILES

        entry = next(
            row
            for row in CURATED_FILES
            if row.filename == UNDERLYING_MODEL_FILEPATH.name
        )
        self.assertEqual(entry.applied_by, "brightway_flows.lcia.contradictions")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
