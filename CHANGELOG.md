# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
- A full pytest suite, run in CI across Python 3.11-3.13.

### Changed

- Description parsing now recognizes plain-text chapter lists (previously
  only HTML-delimited lists matched) and extracts PSC `href`/`image`
  attributes.
- Extractors log through the standard `logging` module instead of printing.
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
- CI runs `ruff format --check` instead of black, runs the test suite, and
  triggers on pull requests.

## [0.1.0] - 2024

- Initial release: description, PSC, and PCI chapter extraction.
