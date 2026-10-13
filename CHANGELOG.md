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
  normalized lines after optional blockquote, `Chapters:`, bullet, or numbered-list
  prefixes, and at least two usable chapters are required. HTML block
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
- HTML title stripping follows visible text: `Part<b>One</b>` becomes `PartOne`
  rather than the pre-1.0 `Part One`. Block tags still establish boundaries.
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
- Strict description recognition accepts bullets (`-`, `*`, `+`, `•`) and
  numbered markers (`1.` and `1)`) followed by whitespace, plus case-insensitive
  leading `Chapters:` labels. Leading Unicode format characters (category `Cf`)
  no longer drop the first chapter; format characters inside titles are preserved.
  The CLI accepts UTF-8-BOM description and PCI files.
- Single trailing timestamp `:`/`.` delimiters no longer produce invalid-start
  issues, including before ASCII/en/em-dash separators. Fractional starts and
  explicit malformed-timestamp diagnostics are retained; lenient prose mentions
  without titles are ignored before timestamp validation.
- Description-only recovery preserves chapter boundaries after unquoted newlines
  while retaining continuation lines with conservative attribute assignments,
  including framework forms, Unicode names, and digit-leading names. Preceding
  boolean tokens remain attributes when followed by an assignment; boolean-only lines
  recover as chapters. URL/query/email tokens favor chapter recovery.
  URL/query fragments, slash-free domain queries, arithmetic, and punctuated
  prose no longer hide chapters; ambiguous `Show x=y` retains
  attribute interpretation. Framework evidence includes `[(name)]`, `*name`,
  `.name`, namespace/dynamic forms such as `v-bind:[key]`, and identifier-shaped
  modifier chains such as `on:click|once`.
  Framework-form recovery evidence requires quoted values, including multiline
  values; bare framework-like prose recovers as chapters. Plain attributes retain
  bare values, and ordinary complete tags retain bare framework attributes.
  Balanced formatted tags, relative anchors, void elements, and genuine
  self-closing tags take precedence over blockquote recovery. Opening terminators
  introduce chapter boundaries only after empty visible context or chapter text;
  strict prose stays continuous. Complete split closing tags close markup/link
  context before following chapters, with formatted boundaries after the closing
  tag. Unbalanced tags retain recovery using both visible HTML and physical
  source prefixes. Lazy token/balance lookahead reuses discovered boundaries;
  comments, attributes, and raw contents cannot supply matching closing tags.
  Physical and visible context reset together at block tags and decoded entity
  newlines, preserving strict prose continuity after earlier chapters. Compact
  array-backed boundaries and stacks replace retained per-tag objects, release
  consumed segments, and keep dense unbalanced markup within allocation bounds.
  Generic stripping and title processing skip recovery caches and token objects.
  Lexical records remain separate from contextual recovery decisions; normal
  parsing and prefix-only lookahead share recovery events. Literal nameless `<`
  fragments affect both contexts, and malformed formatted void tags retain their
  title text. Quote-adjacent names resume scanning after their literal prefix.
  Lookahead avoids HTMLParser buffers and skips decided prefix text.
  Nested `<` and quotes cannot become tag-name characters or artificial markup.
  Quotes directly after tag names remain literal rather than starting attributes.
  Attribute quotes protect only values beginning after `=`; quotes in attribute
  names or bare values no longer hide terminators from lookahead. Provisional
  formatted candidates cannot block enclosing balance, while genuine nested
  matches retain protection. Context-free lookahead consumes recovered raw closings.
  Non-CR/LF separators retain the earlier `splitlines(keepends=True)` title and
  source behavior: trailing separators before inline tags do not truncate titles,
  and another segment within the same data chunk establishes the boundary.
  Lookahead shares contextual raw-opening classification with normal processing,
  preventing unrelated earlier markup from hiding later tags or chapters. Raw
  closing absence requires a searched range; cached tokens are consumed once.
  Unfinished comments retain their complete remainder literally across both paths.
  Generic HTML stripping does not apply this recovery; recovered title fragments
  remain literal.
  Arbitrary tags and multiline attributes remain supported. Script/style handling
  uses ASCII names, distinguishes slash-valued attributes from self-closing tags,
  and recognizes closing-tag suffixes despite comparisons and quotes in contents.
  Unfinished matching raw closing tags can release description chapters,
  including blockquotes and HTML-wrapped prefixes, while
  generic stripping and truly unclosed raw blocks remain suppressed.
  Pending raw openings inside chapter context recover following unquoted chapter
  prefixes even with later closings; complete ordinary raw blocks remain hidden.
  Malformed matching raw closings consume their terminators without leaking `>`.
  Explicit invalid timestamps are rejected before preparing their HTML titles.
  Title-preparation failures no longer become invalid-start diagnostics.
  Local PCI JSON files detect UTF-8, UTF-16, and UTF-32 from bytes.
  The CLI encodes output once before opening a destination, writing validated
  UTF-8 bytes with LF endings and preserving existing output on encoding failure.
  Description writers flatten remaining title line boundaries recognized by `splitlines`,
  including Unicode separators and trailing boundaries,
  while parsing results retain literal titles. Rendered URL fields percent-encode
  all such boundaries, using UTF-8 for Unicode separators, preventing chapter-line
  injection without changing parsed data or existing percent escapes. Raw angle
  brackets, quotes, and all Unicode whitespace (including spaces and tabs) are
  percent-encoded; ampersands are HTML-escaped so URL
  entities and tags cannot introduce chapters while query separators survive
  reparsing. Matching URL text inside titles is escaped before flattening;
  already-rendered occurrences remain unchanged and deduplicate correctly.
  General title sanitization remains deferred: preserved newline entities and
  block markup can establish chapter boundaries on reparse, and lenient mode
  intentionally recognizes prose timestamps.
- HTTP feeds prioritize BOMs, then explicit charsets, then XML byte detection.
  Unknown charsets and decoding failures retry XML byte detection; structural XML
  failures and successful decodes do not. Common encodings avoid full-feed string
  copies, and unrecoverable failures follow the typed parse-error contract.
  Encoding validation after native XML failures uses bounded `codecs.iterdecode`
  chunks and final flushing; Latin-1 and
  failures after successful XML parsing avoid unnecessary decoding.
- All chapter error types round-trip through pickle without losing context or
  breaking process pools, including subclasses with custom constructors and slots
  that also inherit `OSError` or `TimeoutError`. State restoration after allocation
  supports cyclic arguments and slots in pickle and deep copy. Native fields
  retain explicit `None` assignments and deletions. Without custom `__getstate__`,
  Python slots are restored before invoking custom `__setstate__`; a custom getter
  controls dictionary and Python-slot state, including deliberate exclusions.
  Standard state works without custom setters, and `None` skips the setter.
  Native constructor `None` for errno/strerror is preserved when established at
  portable checkpoints, including before normal native-field or `args` changes.
  Explicit writes, deletions, and verified constructor presence retain distinct
  provenance; positively detected unobserved mutations conservatively invalidate
  earlier presence records of every origin. Normal tracked changes preserve
  established state and checkpoint after success. Primitive fingerprints and weak
  identity witnesses replace discarded-object addresses, with bounded primitive
  processing and unknown opaque comparisons. Built-in argument descriptor reads
  bypass subclass `args` getters during bookkeeping and default serialization.
  Constructor `None` filenames remain unset. Weak identity bookkeeping stays
  outside instance dictionaries and supports unhashable subclasses.
  Shared identities and opaque arguments do not imply native construction.
  Primitive checks require an unambiguous multi-argument fallback; single-argument
  message comparisons and user formatting hooks are not used.
  Direct built-in initialization/descriptor calls can make native `None` presence
  unobservable. Such bypasses require a custom reducer for exact preservation;
  default serialization retains known state and omits unknown `None` fields without
  a new warning or failure. This narrows the previous native-reset guarantee.
  Detectable argument-only bypasses can invalidate presence too; identical-value
  resets and unsupported opaque changes can remain unobservable.
  Copying honors registered reducers and custom reduce methods with protocol 4,
  including custom reconstruction factories and sixth-item state updaters.
  Cached feed failures raise fresh exceptions instead of retaining and growing
  traceback chains.
- Atomic archive replacement preserves existing file permissions; new archives
  and sidecars follow the process umask rather than always using mode `0600`.
  Permission changes use descriptors where supported and are skipped when modes
  already match; unsupported changes cannot replace an archive with different modes.
- PCI writers serialize integral starts and ends as JSON integers while retaining
  fractional values.

### Security

- Replaced both backtracking description regex paths and the HTML stripping regex
  with bounded scanning and HTML parsing. Hostile whitespace/bracket inputs and
  malformed markup no longer cause the reproduced parser slowdown.
- Added subprocess regressions with five-second timeouts, alongside tests for
  long inline layouts, parser recovery, rich round trips, verified caches,
  interrupted writes, feed indexing, and CLI integration.
- Description source mappings use compact spans rather than per-character
  integer/reference collections. A subprocess regression bounds traced Python
  allocations for a 5 MiB description with a long title below 64 MiB.

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
- Duplicate GUIDs retain the first episode even when it has no chapters. Legacy
  bulk extraction now follows this same policy instead of allowing later
  chapter-bearing duplicates to replace it.
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
