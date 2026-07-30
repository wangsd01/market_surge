# Yahoo Metadata Rate-Limit Handling

## Problem

The price-history cache correctly reuses a previously fetched range when a
later `low_start` narrows the requested interval. After price screening,
however, the pipeline requests Yahoo metadata for candidates that were not
previously selected. `get_ticker_metadata` also treats cached rows with a null
52-week high as missing.

Metadata is fetched concurrently through `yf.Ticker(ticker).info`. Any one
request raising a rate-limit error aborts the complete screen before successful
responses are saved. Cached null values are requested again on every run, which
can produce a repeated request storm.

## Desired Behavior

- A Yahoo metadata failure must not abort price screening.
- Existing metadata must be reused, including rows with a null 52-week high.
- Only tickers absent from the metadata cache are fetched normally.
- Successful metadata responses must be saved even if other ticker requests
  fail.
- Failed tickers must be reported with a concise warning.
- Existing filtering behavior remains unchanged: tickers without a 52-week
  high continue to pass through the 52-week-high filter.
- `--refresh` remains the explicit way to retry all requested metadata.

## Design

`get_ticker_metadata` will distinguish cached tickers from absent tickers by
membership, not by whether `fifty_two_week_high` is null. Without `refresh`,
only absent tickers will be submitted to Yahoo.

Each future will retain its ticker identity. Exceptions will be caught while
collecting individual futures instead of escaping the collection loop.
Successful results will be accumulated and persisted after all futures finish.
Failures will be accumulated and emitted as one warning containing their count
and deterministically sorted ticker symbols. The function will return the union
of cached and successfully fetched metadata.

The existing pipeline and filters require no behavioral change. A ticker absent
from the returned metadata receives the existing default empty metadata during
attachment. Its null 52-week high continues to pass through the existing
52-week-high filter.

## Alternatives Considered

### Retry with backoff and fail

Retrying can help with transient failures, but Yahoo rate limits may last much
longer than a command invocation. It makes runs slow and still allows metadata
availability to block price screening.

### Replace Yahoo metadata

The 52-week high could be computed from cached prices and sector data could
come from SEC records. Industry classification would still require another
source, and this would be a broader data-model change than needed for the
failure at hand.

## Testing

Focused tests will verify:

1. A cached metadata row with a null 52-week high is returned without a Yahoo
   request.
2. When one uncached ticker raises and another succeeds, the successful result
   is saved and returned, the failure does not escape, and a warning identifies
   the failure count and deterministically sorted failed tickers.
3. `refresh=True` still requests cached tickers.

The full test suite will then verify that the changed failure handling does not
affect price caching, screening, or existing metadata extraction behavior.
