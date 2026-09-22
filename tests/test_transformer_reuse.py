"""A transformer must survive `transform()` being called more than once.

`setup()` runs once per build and `transform()` used to run once too, so a
transformer could acquire a resource in the first and release it in the second
and never notice. #213 made `transform()` run again per source list, without a
second `setup()` -- deliberately, because `setup()` reloads ChEBI and PubChem.

Two transformers were closing their `httpx.Client` at the end of `transform()`
and setting it to None. On the second call every lookup raised
`'NoneType' object has no attribute 'get'` into a broad `except` and was logged
as a warning, so the run completed and the enrichment was quietly half-dead --
after paying the rate-limit delay for each call that could not succeed:

    CommonChem prefetch:  26%|███████| 691/2622 [04:35<12:52, 2.50req/s]
    [warning] commonchemistry_search_failed error="'NoneType' object has no
              attribute 'get'" query=Decalin

These assert the contract rather than that one bug: a transformer is reusable
across calls, and holds no resource whose lifetime is one `transform()`.
"""

import unittest

from brightway_flows.transformers.commonchem_cas_review import (
    CommonchemCasReviewTransformer,
)
from brightway_flows.transformers.consensus_match.lookups import LookupClient

#: Every object that keeps an HTTP client between calls, with the routine that
#: loads its supplementary data.  `consensus_match` keeps its client on the
#: lookup collaborator rather than on the transformer itself.
CLIENT_HOLDERS = (
    (CommonchemCasReviewTransformer, CommonchemCasReviewTransformer.setup),
    (LookupClient, LookupClient.load),
)


class HttpClientOutlivesTransformTestCase(unittest.TestCase):
    def test_a_client_is_available_without_setup(self):
        """`setup()` loads supplementary data; it is not what makes the network
        usable, because it does not run again for the second call."""
        for cls, _setup in CLIENT_HOLDERS:
            with self.subTest(cls.__name__):
                self.assertIsNotNone(cls()._client())

    def test_a_client_is_available_again_after_being_closed(self):
        """`transform()` closes it on the way out. That has to be a release, not
        a teardown, or the next call has nothing to make requests with."""
        for cls, _setup in CLIENT_HOLDERS:
            with self.subTest(cls.__name__):
                transformer = cls()
                first = transformer._client()
                first.close()
                transformer._http_client = None  # what transform() does
                second = transformer._client()
                self.assertIsNotNone(second)
                self.assertIsNot(second, first)

    def test_the_same_client_is_reused_within_a_call(self):
        """Created on demand, not per request."""
        for cls, _setup in CLIENT_HOLDERS:
            with self.subTest(cls.__name__):
                transformer = cls()
                self.assertIs(transformer._client(), transformer._client())

    def test_setup_does_not_own_the_client(self):
        """It used to, which is what tied the client's lifetime to a single
        build rather than to the transformer."""
        import inspect

        for cls, setup in CLIENT_HOLDERS:
            with self.subTest(cls.__name__):
                self.assertNotIn(
                    "self._http_client = httpx.Client",
                    inspect.getsource(setup),
                )


if __name__ == "__main__":
    unittest.main()
