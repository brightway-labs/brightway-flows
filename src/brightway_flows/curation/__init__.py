"""What a curator is asked, and what the answer is worth.

The pipeline gates every preferred-label rename on
`domain.preferred_label_decisions`, and this package holds the two things that
prepare that decision rather than make it:

- :mod:`brightway_flows.curation.label_audit` -- is the replacement a name
  the cited CAS actually has, per Common Chemistry and ChEBI?  An identity
  question, answered from the sources.
- :mod:`brightway_flows.curation.qualifier_loss` -- does the replacement
  drop a qualifier the current name carries?  A specificity question, answered
  from the two strings, and only ever to *shortlist for a reader* (#224).

A third asks a question about names that no rename is involved in:

- :mod:`brightway_flows.curation.unreachable_names` -- has a name that
  reaches one substance already made a second one?  Answered from a finished
  merge run, because the failure is invisible in the list that caused it and
  shows only once another list ships the same string (#74).

Nothing here decides anything.  `tools/build_label_worklist.py`,
`tools/build_scope_narrowing_shortlist.py` and
`tools/build_unreachable_name_shortlist.py` are the callers; the pipeline is
not, and `tests/test_architecture_structure.py` pins that.
"""
