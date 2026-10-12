# Consumer integration follow-ups

These tasks belong in the consuming projects. Identify each exact checkout and
revision before implementation; this release changes only podcast-chapter-tools.

- **Source precedence:** reproduce the supplied Datastore candidate-list issue,
  then make structured PCI/PSC chapters outrank descriptions. Saving guessed
  chapters must not suppress later structured lookup; retain description fallback
  when structured chapters are absent or fetching fails. Add an ingestion-to-store
  regression with both a description match and a declared PCI URL.
- **Fetch lifecycle:** migrate to typed fetch errors, derive archive paths from a
  hash of the chapter URL, and choose bounded backoff/negative-cache lifetimes by
  HTTP status. Exercise transient failures, recoverable 404s, and cache collisions.
- **PSC ingestion:** build one feed index per retrieved XML document. Read the
  stored archive path instead of reconstructing it from a mutable feed title.
  Reproduce the reported save/read filename mismatch before classifying it as a
  confirmed bug, and add a save/read regression if confirmed.
- **Persistence:** map chapter fields explicitly into SQL columns. Test the rich
  model/legacy adapter integration without relying on tuple arity for insertion.
- **Inline extraction:** identify the intended ingestion entry point; repair empty
  chapter plumbing where used and remove obsolete unused helpers. Add real parser
  integration tests for PCI, PSC, descriptions, source selection, and persistence.
- **Refindery:** migrate section generation to visible rich chapters (`toc=True`),
  preserve fractional starts/end boundaries, and use strict description recognition.
  Verify that malformed/nonfinite input cannot propagate to a failed job or stall
  the event loop. Add an end-to-end regression for the previously inferred job
  failure; that consequence has not yet been demonstrated here.
- **Future packaging:** consider an `[http]` extra in a separately announced
  release. Transport imports are now lazy, but removing the required dependency
  changes existing URL/CLI installations and requires a migration decision.
