# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0] - Unreleased

This release adds rich chapter data and explicit failure contracts while retaining
the legacy four-field `Chapter` and `list[Chapter] | None` extractor APIs. Default
description recognition, entry recovery, silent-marker handling, and archive trust
change as described below.

### Added

- Immutable `ChapterData` with fractional starts, optional titles, URLs, images,
  end boundaries, and `toc` visibility metadata.
- `ChapterParseResult` with chapters, per-entry `ChapterIssue` diagnostics, and
  optional source/GUID context. Empty results represent successful absence.
- `parse_pci_chapters`, `parse_psc_chapters`, and `parse_description_chapters`.
  Structured parsers recover usable entries by default; `strict=True` rejects
  validation issues.
- `ChapterParseError`, `ChapterFetchError`, `ChapterHTTPError`, and
  `ChapterTransportError`. HTTP failures expose the requested URL, status code,
  and raw `Retry-After` header; decoding and request failures retain their causes.
- `fetch_pci_chapters` with rich results, typed failures, and verified archives.
- `parse_feed_chapters(xml)` for XML strings or bytes, returning a reusable GUID
  index with `psc_for_guid` and `pci_url_for_guid` lookups.
- `parse_timestamp` and `format_timestamp` for fractional timestamps, alongside
  the existing whole-second helpers.
- `normalize_chapter_data` to normalize chapters while retaining rich fields.
- Optional description checks for strictly increasing starts and a first chapter
  within one second of zero. Both checks are disabled by default.
- CLI `--description-mode {strict,lenient}` for description recognition.

### Changed

- Description parsing defaults to `mode="strict"`: timestamps must begin
  normalized lines, and at least two usable chapters are required. HTML block
  tags and `<br>` establish line boundaries. Inline layouts require
  `mode="lenient"` or CLI `--description-mode lenient`.
- PCI and PSC parsers preserve valid chapters when neighboring entries are
  malformed. Empty structured lists represent absence; nonempty lists without
  usable entries raise `ChapterParseError` in the new APIs.
- Missing PCI titles are valid. Invalid optional fields, including explicit null
  titles, are omitted or defaulted with diagnostics. PSC titles remain required.
- Numeric PCI strings are coerced with diagnostics and rejected under strict
  validation. Invalid end times, including ends before their start, are omitted.
- Legacy PCI extractors exclude `toc=False` markers by default;
  `include_non_toc=True` opts in. Legacy conversion truncates starts, maps absent
  titles to `""`, and drops end boundaries.
- All writers accept rich and legacy chapter models. PCI output preserves
  fractions, optional titles, end boundaries, and silent markers. PSC and
  description output preserves fractional starts, omits silent markers, and
  cannot retain PCI end boundaries.
- Archives retain their JSON structure and gain an adjacent `.meta.json` sidecar
  containing a schema version, exact requested URL, and SHA-256 digest. Missing
  metadata, corruption, mismatches, and unusable documents trigger one fetch.
  Writes use temporary files and atomic replacement; write failures do not
  discard successfully fetched chapters.
- File, URL, bulk, and GUID feed extraction shares the feed index implementation.
  Repeated index lookups reuse parsed results; malformed episodes are isolated.
- Package Loguru output is disabled by default. The CLI explicitly enables it
  and reports source, GUID, entry, and field context where available.
- The CLI uses rich parsing to retain PCI metadata and distinguishes absent
  chapters from parse and fetch failures.
- Replaced `requests` with the typed `httpx2` HTTP client while preserving
  redirect-following behavior. Pure parsing imports do not load the HTTP client;
  `httpx2` remains a required installation dependency.
- Requires Python 3.13 or newer, with CI coverage on Python 3.13 and 3.14.
- Switched packaging to the uv build backend.
- Switched type checking to Pyrefly and ty.
- Switched core package logging to Loguru.
- CI now installs with uv, checks Ruff formatting, runs the test suite, and
  verifies package builds with `uv build`.

### Fixed

- Parentheses and brackets in description titles no longer discard chapters.
  ASCII, en-dash, and em-dash separators immediately after timestamps are removed.
- Inline title markup, links, and literal punctuation survive description parsing;
  `strip_html=True` produces plain titles. Timestamps in attributes, comments,
  scripts, and styles do not become chapters.
- Infinite, nonfinite, negative, boolean, and malformed start times produce
  validation failures instead of leaking conversion exceptions.
- Reusing an archive path for another URL no longer returns the first URL's
  chapters. Truncated or unusable archives can recover through a fresh fetch.
- Feed lookup recognizes both supported PCI namespace URIs, preferring the
  canonical declaration. Duplicate GUIDs retain the first episode and are reported.
- File and HTTP feed adapters respect XML-declared encodings.

### Security

- Replaced both backtracking description regex paths and the HTML stripping regex
  with bounded scanning and HTML parsing. Hostile whitespace/bracket inputs and
  malformed markup no longer cause the reproduced parser slowdown.
- Added subprocess regressions with five-second timeouts, alongside tests for
  long inline layouts, parser recovery, rich round trips, verified caches,
  interrupted writes, feed indexing, and CLI integration.

### Migration

- Use `mode="lenient"` for existing inline description layouts. Use `strict=True`
  when entry-validation issues should reject a parsed list.
- Adopt the rich APIs when callers need fractions, PCI metadata, diagnostics, or
  distinct parse/HTTP/transport failures. Existing extractors still translate
  expected failures to `None`; `Chapter` retains tuple equality and unpacking.
- Refetch old raw archives once to create verified sidecars. For explicit offline
  use of archives without metadata, pass `trust_legacy_archive=True`. Existing
  URL mismatches remain rejected even with this option.
- Build one feed index per XML document for batches of GUID lookups. Repeated
  calls to single-GUID file/URL wrappers still read or fetch the feed each time.
- Applications that want package logs should call
  `logger.enable("podcast_chapter_tools")` and configure their own handlers.
- See [README.md](README.md) for API examples and format conversion losses.
  Consumer integration tasks are tracked separately in
  [FOLLOW_UPS.md](FOLLOW_UPS.md). Automatic retries and negative caching remain
  consumer policy; an optional HTTP dependency extra is deferred.

## [0.2.0] - 2026-07-03

### Added

- `Chapter` is now a `NamedTuple` with `start`, `title`, `url`, and `image`
  fields. It remains fully compatible with the previous plain-tuple shape.
- Writers for every supported format: `chapters_to_pci_dict`,
  `chapters_to_pci_json`, `chapters_to_psc_element`, `chapters_to_psc_xml`,
  and `chapters_to_description`.
- `podcast-chapters` CLI with `from-description`, `from-psc`, `from-pci`, and
  `from-id3` subcommands and `--to {pci,psc,description}` output selection.
- ID3v2 CHAP/CTOC chapter extraction (`extract_id3_chapters`) behind the
  `[id3]` optional extra (uses `mutagen`).
- `extract_psc_chapters_from_url` and `extract_all_psc_chapters_from_file`
  for fetching feeds directly and indexing whole feeds.
- `find_pci_chapters_url` to discover the Podcasting 2.0
  `<podcast:chapters>` URL declared in a feed.
- `normalize_chapters` (sort, dedupe, clamp to duration, strip HTML) and
  `strip_html` helpers; `extract_description_chapters` gained a
  `strip_html` keyword.
- Public `ts_to_secs` / `secs_to_ts` timestamp helpers with validation.
- A full pytest suite, run in CI across supported Python versions.

### Changed

- Description parsing now recognizes plain-text chapter lists (previously
  only HTML-delimited lists matched) and extracts PSC `href`/`image`
  attributes.
- Extractors log through Loguru instead of printing.
- HTTP requests now have a default 30-second timeout (configurable via the
  `timeout` parameter).
- `get_and_extract_pci_chapters`'s `headers` and `archive_path_json`
  arguments are now optional.
- The core package depends only on `requests`; AI-experiment dependencies
  moved to `ai/requirements.txt`.
- Timestamp parsing rejects malformed values (non-numeric segments,
  minutes/seconds >= 60) instead of silently misreading them.
- `ChapterType` gained a vendor-neutral `AI` member; `GEMINI`, `OPENAI`, and
  `SONNET` are deprecated.
- CI runs `ruff format --check`, runs the test suite, and triggers on pull
  requests.

## [0.1.0] - 2024

- Initial release: description, PSC, and PCI chapter extraction.
