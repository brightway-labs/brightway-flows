<!--
Most of what a reviewer needs is produced by the CI run and attached to it as an
artifact, so do not copy it in here. What this template asks for is the part CI
cannot produce: what you meant to happen, and why.

CI runs when a maintainer approves it. If you are waiting, that is why.
-->

## What this changes

<!-- One paragraph. Name the substance, the list, the file or the count. -->

Closes #

## What it is meant to do to the output

Tick one. CI applies a different criterion to each, and fails the one it was told to expect.

- [ ] **Nothing.** This is a refactor, a test, or documentation. Every artifact should hash
      identically to the reference build.
- [ ] **Something, and here is what.** Rows move, and the paragraph below says which and why.

<!--
If you ticked the second box, write what moved here — the shape of it, not the
diff, which is in the artifact. "Nine ecoinvent air rows move from
1,1,2-trichloroethane to 1,1,1-trichloroethane; nothing else moves."

A change that moves rows nobody expected is not automatically wrong, but it has
to be accounted for here before it is merged.
-->

## The claim

Every change that says it fixes an issue states the claim as data, one file per issue, so
that `brightway-flows assess` can grade it against the build rather than a reviewer
taking the pull request description on trust.

- [ ] `expectations/<issue>-<slug>.json` is in this branch
- [ ] It failed on the reference build and holds on this one
- [ ] Its `pending` flag is dropped in this change — or it is still `pending`, and the
      paragraph above says what is left

<!--
If this change came from an issue where a contributor proposed a fix, the
expectation file is committed when this pull request is merged, and CI runs
again against the merged result. You do not need to pre-empt that here.
-->

## Checked by hand

<!--
What you verified that CI does not. Leave it empty if there is nothing — an empty
section is more useful than a filled-in one nobody meant.
-->

## For a change to the harmonisation chain or the merge

<!-- Delete this section if it does not apply. -->

- [ ] `answers_per_flow` is declared, and decided by reading what the transformer reads
- [ ] The registration points and the pages that move with the chain have moved with it
- [ ] A source row that changed where it lands was named before the fix, and measured
