"""The decision queues: where the pipeline declined to decide.

Fourteen queues. Thirteen come from `review_queue`, which is one table because
they differ only in which columns they render; the fourteenth is
`element_coverage`, which is a different question -- "what is missing" rather
than "what is wrong" -- and so keeps its own table and its own reader.

The ETL review app had eight routes over six JSON files, three of which the
pipeline had stopped writing. Adding a queue here is a `ReviewQueue` member and
a column list.

All but a few are one shape, and `elementary-flow-collision` is the first that
is not: its item is a group of flows rather than a row, so it names its own
template and its rows are read by `queries/collisions.py`. It had no page at all
until #61, because the shape it does not fit was the only one on offer. Its
counterpart `substance-in-two-places` -- one substance across several contexts,
where that is a group of *places* rather than of flows -- was rendered as a row
for as long as a place was taken to render as a string. It does not: what a
curator rules on is what sits in each place, and a row could only hold every
context beside every unit beside every source list, none of them paired with the
other two. So it names its own template as well, and `queries/places.py` reads
its places.

The index groups them by what they ask about, and the groups are also the two
runs that write them: a build asks what a substance *is*, `characterise` asks
what it is *worth*, and the second runs over a database the first has already
finished with. So the two halves of the index can be of different ages.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any

from brightway_flows.pipeline.review_records import (
    ElementStatus,
    ReviewQueue,
    Severity,
)
from brightway_flows.webapps.app.db import table_exists
from brightway_flows.webapps.app.queries.common import (
    PAGE_SIZE,
    Page,
    clamp_page,
    load_json,
)

#: The identifier of the elements queue. Not a `ReviewQueue` member because it
#: is not in `review_queue`: it is a join of the PubChem element cache against
#: the flow objects, computed by the pipeline into `element_coverage`.
ELEMENTS = "elements"

#: The one queue whose item is a group of flows rather than a row, and so the
#: one the shared template cannot render.
COLLISIONS = str(ReviewQueue.ELEMENTARY_FLOW_COLLISION)

#: Its counterpart: the queue whose item is a group of *places* rather than a
#: row. Read by `queries/places.py` and rendered by `queue_places.html`.
PLACES = str(ReviewQueue.SUBSTANCE_IN_TWO_PLACES)

#: The three whose item is a question about a substance across several flows, and
#: whose answer needs more than a table row can hold: where each flow came from,
#: what the pipeline did to it, and every number anybody states about it.  Read
#: by `queries/factors.py` and rendered by `queue_factors.html`.
FACTOR_QUEUES = (
    str(ReviewQueue.CONTESTED_FACTOR),
    str(ReviewQueue.PROPOSED_FACTOR),
    str(ReviewQueue.CONTRADICTED_FACTOR),
)


@dataclass(frozen=True)
class QueueGroup:
    """A kind of decision, and the run that produces it.

    The index used to be one grid of fourteen cards, which asked a curator to
    know from the titles that `Ambiguous CAS` and `Two implementations, two
    numbers` are not the same kind of work and do not come from the same run.
    They do not: the flow queues are written by `build`, and the factor queues by
    `characterise` against a build that has already finished. So the two can be
    of different ages against one database, and a curator draining one is not
    touching the other.
    """

    key: str
    title: str
    lede: str


#: What a build asks about: what a substance is, what it is called, and where in
#: the world it is emitted.
FLOW_DECISIONS = QueueGroup(
    key="flows",
    title="Flows and substances",
    lede="Written by a build, in the order a curator works them: the cheap "
         "mechanical ones first, because they improve every identity decision "
         "downstream.",
)

#: What `characterise` asks about: what a substance is worth. A separate run
#: over a finished build, so these can be older or newer than the queues above.
FACTOR_DECISIONS = QueueGroup(
    key="factors",
    title="Characterisation factors",
    lede="Written by `characterise`, which runs over a build that has already "
         "finished. Each asks about a number rather than about an identity, and "
         "each names the flows, the sources and every stated value behind it.",
)

#: In the order the index renders them.
GROUPS: tuple[QueueGroup, ...] = (FLOW_DECISIONS, FACTOR_DECISIONS)


@dataclass
class Column:
    """One column of a queue table.

    `path` is read out of the item's payload, which is queue-specific JSON --
    so the difference between six queues is this list and nothing else.
    """

    label: str
    path: str
    mono: bool = False
    #: Render a list value as one entry per line rather than as JSON.  For a
    #: column of numbers `["50-21-5"]` is only noisy; for one of names --
    #: `["50-21-5: rac-lactic acid, 2-hydroxypropanoic acid"]` -- the quoting
    #: is most of what the reader has to look past to read the name.
    lines: bool = False


@dataclass
class QueueDefinition:
    """What one queue is called, what it asks, and what it renders."""

    name: str
    title: str
    question: str
    columns: list[Column] = field(default_factory=list)
    #: Eleven queues render `queue.html`, which is a column list and nothing
    #: else.  A queue whose item is not a row -- `elementary-flow-collision`,
    #: whose item is a group of flows -- names its own template and carries no
    #: columns, because a group rendered as one is a column of UUIDs (#61).
    template: str = "queue.html"
    #: Which section of the index it appears under. Stated rather than derived
    #: from the template it renders: those coincide today and are two different
    #: facts, and a factor queue that grew a plain table would otherwise be
    #: filed silently under the flow decisions.
    group: str = FLOW_DECISIONS.key


@dataclass
class QueueItem:
    """One row, with its payload already read."""

    item_key: str
    title: str = ""
    severity: str = str(Severity.INFO)
    uuid: str = ""
    flow_object_id: str = ""
    cas: str = ""
    payload: dict[str, Any] = field(default_factory=dict)

    def value(self, path: str) -> Any:
        """A payload field by name, or None.

        Dotted paths are not supported deliberately: a column that needs one is
        a column whose queue wants a purpose-built page, not a generic table.
        """
        return self.payload.get(path)

    def value_lines(self, column: Column) -> list[str] | None:
        """The value as one line per entry, where the column asks for that.

        `None` where it does not, or where the value is not a list, and the
        template then renders the cell the way every other cell is rendered.
        """
        if not column.lines:
            return None
        value = self.value(column.path)
        return [str(entry) for entry in value] if isinstance(value, list) else None


@dataclass
class QueueSummary:
    """One queue on the index, and how much of it is blocking."""

    definition: QueueDefinition
    total: int = 0
    blocking: int = 0
    available: bool = True


#: Every queue, in the order a curator works them: cheap and mechanical first,
#: because those improve every identity decision downstream.
DEFINITIONS: tuple[QueueDefinition, ...] = (
    QueueDefinition(
        name=str(ReviewQueue.EC_MALFORMED),
        title="Malformed EC numbers",
        question="No valid EC number can be recovered from this string: either "
                 "it is not in the form NNN-NNN-N at all, or its check digit "
                 "arithmetic lands on a slot the register skipped rather than "
                 "issued. So nothing can be resolved from it and no correction "
                 "exists to propose. It is a data error at the source.",
        columns=[
            Column("Flow", "flow_name"),
            Column("EC number", "ec", mono=True),
        ],
    ),
    QueueDefinition(
        name=str(ReviewQueue.EC_CROSS_CHECK),
        title="CAS ↔ EC mismatches",
        question="The ECHA inventory pairs these identifiers differently from "
                 "the flow. Where PubChem confirmed the inventory, the EC was "
                 "added and wants checking; where it did not, nothing changed.",
        columns=[
            Column("Flow", "flow_name"),
            Column("Direction", "type"),
            Column("Flow CAS", "flow_cas", mono=True),
            Column("Flow EC", "flow_ec", mono=True),
            Column("Inventory EC", "inventory_ec", mono=True),
            Column("Inventory CAS", "inventory_cas", mono=True),
            Column("PubChem confirmed", "pubchem_confirmed"),
        ],
    ),
    QueueDefinition(
        name=str(ReviewQueue.COMMONCHEM_NAME_CAS),
        title="Common Chemistry CAS updates",
        question="Common Chemistry knows this flow's name and gives a different "
                 "CAS for it. Applied only where the flow had no CAS of its "
                 "own; where it had one, that number was kept and this is the "
                 "disagreement to rule on.",
        columns=[
            Column("Flow", "flow_name"),
            Column("Source", "source"),
            Column("Flow CAS", "current_cas_numbers", mono=True),
            Column("Common Chemistry CAS", "commonchem_cas_numbers", mono=True),
            Column("Applied", "applied"),
        ],
    ),
    QueueDefinition(
        name=str(ReviewQueue.COMMONCHEM_CAS_NAME_DIFFERENCES),
        title="Common Chemistry name differences",
        question="Common Chemistry knows this CAS and calls it something else. "
                 "Nothing was changed: a name is not evidence of identity the "
                 "way a CAS is, and the flow's own name may be what its source "
                 "list needs.",
        columns=[
            Column("Flow", "flow_name"),
            Column("Source", "source"),
            Column("CAS", "cas", mono=True),
            Column("Common Chemistry calls it", "commonchem_name"),
        ],
    ),
    QueueDefinition(
        name=str(ReviewQueue.CAS_AMBIGUOUS),
        title="Ambiguous CAS",
        question="The flow's name matches several ChEBI records and none of them "
                 "carries its CAS. The candidates are offered rather than "
                 "applied: choosing one is exactly the judgement the pipeline "
                 "cannot make — so each is shown with what its registry calls "
                 "it, which is the whole of what tells two numbers apart. "
                 "`Registry calls it` is what the flow's own number names, "
                 "where that is not what the flow names itself; where it is "
                 "empty the two agree, or no registry names the number. One "
                 "row per name and source list: the candidates come from the "
                 "name alone, so every flow published under it asks the same "
                 "question, and `Flows` says how many are waiting on the "
                 "answer.",
        columns=[
            Column("Flow", "flow_name"),
            Column("Source", "source"),
            Column("Flows", "flow_count"),
            Column("Current CAS", "current_cas_numbers", mono=True, lines=True),
            Column("Registry calls it", "current_cas_names", lines=True),
            Column("Possible", "possible_corrected_cas_names", lines=True),
        ],
    ),
    QueueDefinition(
        name=str(ReviewQueue.CONSENSUS_MATCH),
        title="Blocked consensus decisions",
        question="A CAS or a name the sources agree on, not applied — because "
                 "the substance's group holds several CAS whose relationship is "
                 "not exact, or because the name already belongs to a different "
                 "CAS-bearing substance in this dataset.",
        columns=[
            Column("Substance", "flow_name"),
            Column("Decision", "decision"),
            Column("Candidate CAS", "candidate_cas", mono=True),
            Column("Candidate name", "candidate_name"),
            Column("Why", "reason"),
        ],
    ),
    QueueDefinition(
        name=str(ReviewQueue.CURATED_CAS_EXCLUSION),
        title="CAS links PubChem does not curate",
        question="PubChem's cross-reference index linked this CAS to a compound "
                 "whose own curated record does not list the number — usually a "
                 "vendor catalogue entry with the wrong CAS on it. The compound "
                 "was dropped, so its structure and names are no longer merged "
                 "into the substance.",
        columns=[
            Column("CAS", "cas", mono=True),
            Column("Kept", "kept_cids", mono=True),
            Column("Dropped", "dropped_cids", mono=True),
            Column("Not asked", "unknown_cids", mono=True),
        ],
    ),
    QueueDefinition(
        name=str(ReviewQueue.COMMONCHEM_STRUCTURE_EXCLUSION),
        title="CAS publishes no structure",
        question="No structure was looked up through this CAS — either CAS "
                 "Common Chemistry gives it no molecular formula, which is what "
                 "it does for a UVCB or a commercial mixture, or a ruling in "
                 "`commonchemistry-structure-decisions.json` calls it an "
                 "unspecified isomer. PubChem answered it with a compound "
                 "anyway: one component of the mixture, or something unrelated. "
                 "Is the number really non-specific? Where the reason is "
                 "`contradicted` instead, Common Chemistry gave a different "
                 "structure from the one offered, and the compounds listed "
                 "under stereo-only differ from it in stereochemistry alone.",
        columns=[
            Column("CAS", "cas", mono=True),
            Column("Reason", "reason"),
            Column("Why", "why"),
            Column("CAS structure", "commonchemistry_inchikey", mono=True),
            Column("Dropped compounds", "dropped_cids", mono=True),
            Column("Dropped ChEBI", "dropped_chebi_ids", mono=True),
            Column("Stereo-only", "stereo_only_cids", mono=True),
        ],
    ),
    QueueDefinition(
        name=str(ReviewQueue.CONTESTED_CAS),
        title="One number, more than one name",
        question="More than one flow name in one source list carries this "
                 "registry number, and nothing decides whether they are one "
                 "substance: the list gives them no factor for the same method "
                 "and context to compare, or it gives them the same one, and "
                 "Common Chemistry does not publish every name as a synonym of "
                 "the number. They are merged, as before, because splitting on "
                 "suspicion is the larger risk. Are they one substance? Rule on "
                 "it in `contested-cas-decisions.json`. `Comparable` is how many "
                 "method-and-context pairs both names publish a factor for -- "
                 "zero means the list has not been asked, not that it agreed.",
        columns=[
            Column("CAS", "cas", mono=True),
            Column("Names", "names"),
            Column("Flows", "flow_count"),
            Column("Comparable", "comparable_factors"),
            Column("Divergence", "factor_divergence"),
        ],
    ),
    QueueDefinition(
        name=COLLISIONS,
        title="One place, more than one flow",
        question="Two live flows carry the same substance, the same context and "
                 "the same unit -- three of the fields deduplication signs on. "
                 "They were not collapsed, because it compares every other "
                 "field of the record as well and found one they disagree on. "
                 "That field, shown as what holds them apart, is the whole of "
                 "what keeps them two. Where it is the general comment -- a "
                 "free-text note -- they are one edit to a source list away "
                 "from being merged, and the flow holding fewer "
                 "characterisation factors would lose them. That is #31, "
                 "where a balanced pair of water withdrawal and return factors "
                 "became a one-sided charge. Everything else the flows "
                 "disagree on is listed under each of them: the names, most "
                 "often, which deduplication does not read at all and a "
                 "curator does. So: two flows, or one? Answering one means a "
                 "ruling in `elementary-flow-collision-decisions.json`, which "
                 "names the flow that survives and carries the other's factors "
                 "and source references onto it. Answering two means leaving "
                 "them alone, which is what the pipeline already does. A row "
                 "marked `review` is a different question and takes a "
                 "different answer: there the merge minted the flows, "
                 "answering a curated grouping by writing a flow onto a place "
                 "another flow already held, where the same grouping attaches "
                 "a source reference to the flow that is there when the "
                 "substance is in the prepared correspondence table (#60). "
                 "Those minted flows carry no characterisation factors, and a "
                 "ruling in the decisions file does nothing to them -- "
                 "deduplication and the rulings both run before the merge, so "
                 "nothing has ever inspected these. What answers them is which "
                 "of the two treatments the grouping should have had.",
        template="queue_collisions.html",
    ),
    QueueDefinition(
        name=str(ReviewQueue.CONTESTED_FACTOR),
        title="Two implementations, two numbers",
        question="Both implementations of EF 3.1 state a characterisation "
                 "factor for this substance and category, and the two numbers "
                 "differ by more than rounding. The consensus implementation "
                 "publishes neither until somebody rules: taking the method's "
                 "own publisher by default would publish a number nobody had "
                 "looked at, under a label saying a decision was made. What "
                 "answers one of these is which reading is right. Two are "
                 "answered — kresoxim-methyl, where EF files one substance twice "
                 "under two EC numbers and each implementation took a different "
                 "row's factor (#64), and vanadium, where the ratio is exactly "
                 "10.0000 in all ten rows with the mantissa preserved (#49) — "
                 "and a ruled question stays here as the record, marked "
                 "`ruled`, rather than disappearing.",
        template="queue_factors.html",
        group=FACTOR_DECISIONS.key,
    ),
    QueueDefinition(
        name=str(ReviewQueue.PROPOSED_FACTOR),
        title="Factors only ecoinvent states",
        question="The ecoinvent Centre characterises this substance where the "
                 "JRC does not — most often because EF 3.1's flow list has no "
                 "such compartment or no such form of the substance (#84). "
                 "Where the number is one this list already publishes — for the "
                 "same substance in another compartment within tolerance, or "
                 "bit for bit on another flow of the category, the way an ion "
                 "carries its element's factors — it is published as `restated` "
                 "and never reaches this queue. What is left is a number of "
                 "ecoinvent's own, about a flow the method's own publisher did "
                 "not characterise, so it is offered rather than taken. Where "
                 "one substance is proposed the same number in every context it "
                 "appears in, the row says so: that is what makes a ruling "
                 "about a compartment possible rather than one per flow.",
        template="queue_factors.html",
        group=FACTOR_DECISIONS.key,
    ),
    QueueDefinition(
        name=str(ReviewQueue.CONTRADICTED_FACTOR),
        title="The model underneath says something else",
        question="EF 3.1's toxicity categories are USEtox 2.1 — the JRC's own "
                 "report says so and lists the adjustments made on top of it. "
                 "For these four substances the two are more than a hundredfold "
                 "apart in every compartment, and for one of them a millionfold: "
                 "EF 3.1 characterises biphenyl, an ordinary industrial "
                 "chemical, at 0.19957 CTUh for a kilogram emitted to urban air "
                 "— two hundred cases of disease per tonne, and third of the "
                 "3,380 substances EF characterises there, above mercury — where "
                 "USEtox 2.1 gives 0.00000014. Neither published implementation "
                 "can see this, because both transcribe the same file and "
                 "therefore agree: the two numbers in the first table below are "
                 "one source counted twice, and the model's are in the table "
                 "under them. So the consensus implementation publishes nothing "
                 "here until somebody rules, and the two transcriptions are "
                 "untouched: EF 3.1 says 0.19957 and this list goes on saying "
                 "that under the JRC's name. What answers one of these is "
                 "whether the method's number should be published in spite of "
                 "the model — a `publish` ruling naming an implementation, if "
                 "the adjustment was deliberate and the report explains it, or a "
                 "`decline` if it was not. Two populations are deliberately not "
                 "here. The metals, because EF replaced USEtox's metal factors "
                 "with ones derived from EU data sources and that is a decision "
                 "rather than a defect. And freshwater ecotoxicity, whatever the "
                 "gap: the workbook publishes an ecosystem-quality result in "
                 "potentially disappeared fraction of species and EF's CTUe is a "
                 "potentially affected fraction, so the two were never the same "
                 "number and a ratio between them measures the models rather "
                 "than the substance (#107).",
        template="queue_factors.html",
        group=FACTOR_DECISIONS.key,
    ),
    QueueDefinition(
        name=str(ReviewQueue.SUBSTANCE_IN_TWO_PLACES),
        title="One substance, more than one place",
        question="The same substance is published in two contexts that are two "
                 "different places, rather than one place described at two "
                 "levels of detail — each of them states something the other "
                 "denies. Where a substance is *released* is a fact about the "
                 "process, so releases are not compared here: a metal emitted "
                 "to air and to a river is two ordinary flows. Where it is "
                 "*taken from* is a fact about the substance. Peat comes out of "
                 "the ground, wood off a living tree, geothermal heat out of "
                 "the rock beneath, and no process chooses — so two of those on "
                 "one substance are two answers to a question that has one, and "
                 "one of them was written by the merge on behalf of a source "
                 "list that files the substance elsewhere. Nothing goes wrong "
                 "at any single step, which is why this needed a check: the two "
                 "halves are separate identifiers that can never meet, so an "
                 "inventory using one and a method characterising the other "
                 "simply do not connect. Each place is one row, naming the "
                 "source lists that publish the substance there, the unit they "
                 "measure it in and how many characterisation factors sit on "
                 "it — so the row says whether the two places even measure the "
                 "same thing, and which of them the numbers are on. Answering "
                 "means deciding which place "
                 "is right and writing it down — a rule in "
                 "`context-manual-mapping.json` when the source list filed the "
                 "row in the wrong compartment, or a target in that list's "
                 "match overrides when it meant a different substance. Leaving "
                 "it is also an answer, and it is the one that keeps two flows.",
        template="queue_places.html",
    ),
    QueueDefinition(
        name=str(ReviewQueue.LAND_CLASS_OUT_OF_PLACE),
        title="A land class outside Land Use",
        question="A flow of a land-class substance is published outside the "
                 "Land Use dimension. A land class has exactly one right "
                 "dimension, stated by its own direction — an occupation "
                 "occupies and a transformation transforms, and neither is a "
                 "mineral or a water resource — so unlike the queue above, "
                 "nothing needs to disagree with anything for this to be "
                 "wrong: the vendor's compartment overruled the curated class "
                 "(#193). The merge now asks the class first when it places a "
                 "row, so an item here means a route into the published list "
                 "that skipped that rule; each names the class, the direction "
                 "it states, the context the flow was published in, and the "
                 "factor count that shows what the misplacement costs.",
        columns=[
            Column("Substance", "label"),
            Column("Class", "land_class_key", mono=True),
            Column("Direction", "direction"),
            Column("Published in", "context"),
            Column("Unit", "unit"),
            Column("Factors", "factor_count"),
        ],
    ),
    QueueDefinition(
        name=str(ReviewQueue.STEREO_DISAGREEMENT),
        title="Structures CAS does not agree with",
        question="The structure published for this CAS has the same skeleton as "
                 "the one CAS Common Chemistry publishes and differs from it "
                 "somewhere else. Where the kind is "
                 "`lost`, CAS gives the number a stereochemistry and the "
                 "published structure is flat — the direction is certain, but "
                 "CAS's key is usually non-standard and so cannot be copied in "
                 "as the correction. Where it is `conflict`, both sides are "
                 "specific and standard and they disagree, and neither can be "
                 "trusted without someone looking. Where it is `incomparable`, "
                 "CAS's structure for the number could not be re-expressed in "
                 "the notation everything else here uses, so the two keys were "
                 "never comparable and this is not known to be a disagreement "
                 "at all. The row says which of the three reasons it was: CAS "
                 "states a relative or racemic stereochemistry that no standard "
                 "InChIKey can express, its structure could not be read, or "
                 "reading it back altered it — which is what happens to a lone "
                 "isotope-labelled atom, whose label is dropped, and is not a "
                 "statement about shape at all. Where it is `protonation`, the "
                 "difference is not stereochemistry either: the last block of "
                 "the key says how many hydrogen ions the substance carries, "
                 "and this is CAS's substance with some added or taken away — "
                 "an acid and its ion, and which of the two the flow object is "
                 "for is the question. The remaining kinds record something the "
                 "pipeline did: `restored` published the stereochemistry CAS "
                 "states where no source held it, and `superseded` and "
                 "`protonation-withdrawn` took a second key out of the identity "
                 "field because another key on the object is the registry's own "
                 "answer. **Corrected** is the key the substance "
                 "should carry, or for a withdrawal the key that stayed; where "
                 "it is empty there is no expressible answer and the decision is "
                 "yours.",
        columns=[
            Column("CAS", "cas", mono=True),
            Column("Kind", "kind"),
            Column("Published", "published_inchikeys", mono=True),
            Column("CAS structure", "commonchemistry_inchikey", mono=True),
            Column("Corrected", "corrected_inchikey", mono=True),
            Column("From", "sources", mono=True),
        ],
    ),
    QueueDefinition(
        name=str(ReviewQueue.UNDECIDED_LABEL_REPLACEMENT),
        title="Renames awaiting a ruling",
        question="A rule proposed this preferred-label replacement and no ruling "
                 "covers it, so the current label stands. Rule on it in "
                 "`preferred-label-decisions.json`.",
        columns=[
            Column("Current", "current"),
            Column("Proposed", "replacement"),
            Column("Rule", "rule", mono=True),
            Column("Flows", "flow_count"),
            Column("CAS", "cas_numbers", mono=True),
        ],
    ),
    QueueDefinition(
        name=str(ReviewQueue.SUBSTANCE_LABEL_CONFLICT),
        title="A flow named for a different substance than its own",
        question="This flow's own name answers for a different substance than "
                 "the one the flow sits on, so giving the flow its substance's "
                 "name would delete the only visible symptom of what may be a "
                 "mis-grouping: either the two substance records are one "
                 "substance, or the flow is on the wrong one (#116). The flow "
                 "keeps its name until a ruling in "
                 "`preferred-label-decisions.json` answers the pair: `approve` "
                 "says the grouping is right — the flow takes its substance's "
                 "name, and the old name is published as a synonym of neither "
                 "substance, because a name that answers for two is a name for "
                 "none (#113). `reject` says the flow's own name stands. If the "
                 "grouping itself is wrong, the answer is not a ruling here but "
                 "a split, and the row waits until it has one.",
        columns=[
            Column("Flow says", "current"),
            Column("Substance says", "replacement"),
            Column("Flows", "flow_count"),
            Column("Also answers for", "other_claimants", lines=True),
        ],
    ),
    QueueDefinition(
        name=ELEMENTS,
        title="Elements not in the list",
        question="A chemical element with no flow object, or with one that "
                 "nothing in EF 3.1 references. The one queue that says "
                 "something is missing rather than that something is wrong.",
        columns=[
            Column("Atomic number", "atomic_number"),
            Column("Symbol", "symbol", mono=True),
            Column("Name", "name"),
            Column("Status", "status"),
        ],
    ),
    QueueDefinition(
        name=str(ReviewQueue.RETIRED_IDENTIFIER_UNRESOLVED),
        title="Retired identifiers that resolve to nothing",
        question="An identifier the renumbering retired points at a flow this "
                 "build no longer mints, so a consumer holding it is told "
                 "nothing. Usually that is a fix working: the flow was minted "
                 "because a row was filed in the wrong place, the row now goes "
                 "where its siblings go, and the flow correctly stopped being "
                 "minted -- taking a published identifier with it. Where the "
                 "substance is gone there is nothing to point at and the row is "
                 "information. Where it survives, the row lists the contexts it "
                 "survives in; the retired identifier names the one that is now "
                 "empty, so where should it point, and what does a redirect "
                 "across a context boundary promise a consumer?",
        columns=[
            Column("Substance", "name"),
            Column("Retired identifier", "identifier", mono=True),
            Column("It named", "context_iri", mono=True),
            Column("Substance still published", "substance_still_published"),
            Column("Surviving flows", "surviving_flows", lines=True),
            Column("One obvious target", "unambiguous_target", mono=True),
        ],
    ),
)

_BY_NAME = {definition.name: definition for definition in DEFINITIONS}


def definition(name: str) -> QueueDefinition | None:
    return _BY_NAME.get(name)


def index(connection: sqlite3.Connection) -> list[QueueSummary]:
    """Every queue with its counts, for the section landing page.

    Includes queues with nothing in them, unlike the overview: a curator on the
    queue index is choosing what to work on, and "this one is clear" is part of
    that answer.
    """
    has_review_queue = table_exists(connection, "review_queue")
    counts: dict[str, tuple[int, int]] = {}
    if has_review_queue:
        for row in connection.execute(
            "SELECT queue_name, count(*) AS total, "
            "sum(CASE WHEN severity = ? THEN 1 ELSE 0 END) AS blocking "
            "FROM review_queue GROUP BY queue_name",
            (str(Severity.BLOCKING),),
        ):
            counts[row["queue_name"]] = (int(row["total"]), int(row["blocking"] or 0))

    has_elements = table_exists(connection, "element_coverage")
    element_total = 0
    if has_elements:
        element_total = int(
            connection.execute(
                "SELECT count(*) FROM element_coverage WHERE status <> ?",
                (str(ElementStatus.LINKED),),
            ).fetchone()[0]
        )

    summaries: list[QueueSummary] = []
    for entry in DEFINITIONS:
        if entry.name == ELEMENTS:
            summaries.append(QueueSummary(
                definition=entry, total=element_total, blocking=0,
                available=has_elements,
            ))
            continue
        total, blocking = counts.get(entry.name, (0, 0))
        summaries.append(QueueSummary(
            definition=entry, total=total, blocking=blocking,
            available=has_review_queue,
        ))
    return summaries


def grouped(
    connection: sqlite3.Connection,
) -> list[tuple[QueueGroup, list[QueueSummary]]]:
    """The same summaries, under the kind of decision each one asks for.

    A group with no queues in it is left out rather than rendered empty: the
    groups are a way of reading the index, not a claim about what a build
    produces.
    """
    summaries = index(connection)
    sections = []
    for group in GROUPS:
        rows = [
            summary for summary in summaries
            if summary.definition.group == group.key
        ]
        if rows:
            sections.append((group, rows))
    return sections


def severity_badges(
    connection: sqlite3.Connection, name: str, *, query: str = ""
) -> tuple[list[tuple[str, str, int]], int]:
    """Each severity in this queue, its label and how many rows carry it.

    The same badge the table draws, offered as a filter above it.  A severity
    with nothing in it is left out: a chip reading `review 0` is a control that
    can only empty the table, and this page already has a dropdown that could do
    that.

    Counted under whatever search is in force, so the chips describe the rows on
    screen rather than the queue as a whole.  The elements queue is not in
    `review_queue` at all -- it is a coverage table, every row of the same kind
    -- so it offers no badges and the control is not drawn.
    """
    if name == ELEMENTS or not table_exists(connection, "review_queue"):
        return [], 0
    clauses, params = _item_clauses(name, query=query)
    where = " AND ".join(clauses)
    counted = {
        str(row["severity"]): int(row["n"])
        for row in connection.execute(
            f"SELECT severity, count(*) AS n FROM review_queue WHERE {where} "
            "GROUP BY severity",
            params,
        )
    }
    badges = [
        (str(severity), str(severity).capitalize(), counted[str(severity)])
        for severity in (Severity.BLOCKING, Severity.REVIEW, Severity.INFO)
        if counted.get(str(severity))
    ]
    return badges, sum(counted.values())


def _item_clauses(
    name: str, *, query: str = "", severity: str = ""
) -> tuple[list[str], list[Any]]:
    """The `WHERE` one queue's rows are selected by, shared by rows and counts.

    One place, so a chip cannot count a set the table does not show.
    """
    clauses = ["queue_name = ?"]
    params: list[Any] = [name]
    if severity:
        clauses.append("severity = ?")
        params.append(severity)
    if query:
        like = f"%{query.lower()}%"
        clauses.append(
            "(lower(title) LIKE ? OR lower(elementary_flow_uuid) LIKE ? "
            "OR lower(flow_object_id) LIKE ? OR lower(cas) LIKE ? "
            "OR lower(payload_json) LIKE ?)"
        )
        params.extend([like] * 5)
    return clauses, params


def items(
    connection: sqlite3.Connection,
    name: str,
    *,
    query: str = "",
    severity: str = "",
    page: int = 1,
) -> Page[QueueItem]:
    """One queue's rows, in the order the run produced them."""
    if name == ELEMENTS:
        return _element_items(connection, query=query, page=page)
    if not table_exists(connection, "review_queue"):
        return Page()

    clauses, params = _item_clauses(name, query=query, severity=severity)
    where = " AND ".join(clauses)

    total = int(
        connection.execute(
            f"SELECT count(*) FROM review_queue WHERE {where}", params
        ).fetchone()[0]
    )
    number = clamp_page(page, total)
    rows = connection.execute(
        f"SELECT * FROM review_queue WHERE {where} ORDER BY item_index "
        "LIMIT ? OFFSET ?",
        [*params, PAGE_SIZE, (number - 1) * PAGE_SIZE],
    ).fetchall()
    return Page(
        rows=[
            QueueItem(
                item_key=row["item_key"],
                title=row["title"] or "",
                severity=row["severity"],
                uuid=row["elementary_flow_uuid"] or "",
                flow_object_id=row["flow_object_id"] or "",
                cas=row["cas"] or "",
                payload=load_json(row["payload_json"], {}),
            )
            for row in rows
        ],
        total=total,
        number=number,
    )


def _element_items(
    connection: sqlite3.Connection, *, query: str = "", page: int = 1
) -> Page[QueueItem]:
    """The elements queue, shaped like the others so one template serves both."""
    if not table_exists(connection, "element_coverage"):
        return Page()
    clauses = ["status <> ?"]
    params: list[Any] = [str(ElementStatus.LINKED)]
    if query:
        like = f"%{query.lower()}%"
        clauses.append("(lower(symbol) LIKE ? OR lower(name) LIKE ?)")
        params.extend([like, like])
    where = " AND ".join(clauses)

    total = int(
        connection.execute(
            f"SELECT count(*) FROM element_coverage WHERE {where}", params
        ).fetchone()[0]
    )
    number = clamp_page(page, total)
    rows = connection.execute(
        f"SELECT * FROM element_coverage WHERE {where} ORDER BY atomic_number "
        "LIMIT ? OFFSET ?",
        [*params, PAGE_SIZE, (number - 1) * PAGE_SIZE],
    ).fetchall()
    return Page(
        rows=[
            QueueItem(
                item_key=str(row["atomic_number"]),
                title=row["name"] or "",
                # Never blocking: nothing is waiting on a ruling, something is
                # absent. Marking it blocking would put it above decisions that
                # are actually stuck.
                severity=str(Severity.INFO),
                flow_object_id=row["flow_object_id"] or "",
                payload={
                    "atomic_number": row["atomic_number"],
                    "symbol": row["symbol"] or "",
                    "name": row["name"] or "",
                    "status": row["status"],
                    "pubchem_page_url": row["pubchem_page_url"] or "",
                },
            )
            for row in rows
        ],
        total=total,
        number=number,
    )
