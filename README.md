# podcast-chapter-tools

[![Lint and Test](https://github.com/hbmartin/podcast-chapter-tools/actions/workflows/lint.yml/badge.svg)](https://github.com/hbmartin/podcast-chapter-tools/actions/workflows/lint.yml)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Checked with Pyrefly](https://img.shields.io/badge/pyrefly-checked-blue.svg)](https://pyrefly.org/)
[![Checked with ty](https://img.shields.io/badge/ty-checked-blue.svg)](https://docs.astral.sh/ty/)
[![twitter](https://img.shields.io/badge/@hmartin-00aced.svg?logo=twitter&logoColor=white)](https://twitter.com/hmartin)

<img src="https://raw.githubusercontent.com/hbmartin/podcast-chapter-tools/main/.idea/icon.svg" width="100" align="right">

Extract and transform podcast chapter information between
[PodcastIndex (PCI) chapters](https://github.com/Podcastindex-org/podcast-namespace/blob/main/docs/examples/chapters/jsonChapters.md),
[Podlove Simple Chapters (PSC)](https://podlove.org/simple-chapters/),
description embeds (timestamps in show notes), and ID3v2 CHAP frames.

## Installation

```bash
pip install podcast-chapter-tools

# with ID3 chapter support (mutagen)
pip install 'podcast-chapter-tools[id3]'
```

## Usage

### Command line

```bash
# Show-notes timestamps -> PodcastIndex chapters JSON
podcast-chapters from-description shownotes.txt --to pci

# PSC chapters from a feed (file or URL) -> description text
podcast-chapters from-psc feed.xml --guid "episode-guid" --to description

# PodcastIndex chapters JSON (file or URL) -> PSC XML
podcast-chapters from-pci https://example.com/chapters.json --to psc

# ID3 CHAP frames from an MP3 (requires the [id3] extra)
podcast-chapters from-id3 episode.mp3
```

All subcommands accept `--to {pci,psc,description}`, `--normalize` (sort,
dedupe, strip HTML from titles), and `--output FILE`.

### Library

Use the rich parsers when preserving fractions, silent markers, and validation
information matters. Parsing does not import the HTTP client or perform I/O.

```python
from podcast_chapter_tools import (
    parse_pci_chapters,
    chapters_to_pci_json,
    normalize_chapter_data,
)

result = parse_pci_chapters(
    {
        "chapters": [
            {"startTime": 0.5, "title": "Intro", "endTime": 61.5},
            {"startTime": 61.5, "toc": False, "img": "https://example.com/art.png"},
        ]
    }
)
# result.chapters is a tuple of immutable ChapterData objects.
# start, title, url, image, end, toc are available by name.
chapters = normalize_chapter_data(result.chapters)
print(chapters_to_pci_json(chapters, indent=2))
for issue in result.issues:
    print(
        result.source, result.guid, issue.index, issue.field, issue.code, issue.message
    )
```

`ChapterParseResult` represents a successful parse, including absence through an
empty `chapters` tuple. `diagnostics` (also called `issues`) contains validation
details. Invalid document structure and structured lists with no
usable entries raise `ChapterParseError`. Its `issues`, `source`, and `guid`
attributes provide context. By default, valid entries survive malformed neighbors;
`strict=True` rejects any validation issue. Entry indexes are zero-based.

PCI titles may be absent. Explicit null or incorrectly typed optional values are
omitted/defaulted with diagnostics. Start times must be finite and nonnegative;
booleans are rejected. Numeric strings are coerced with a diagnostic, and rejected
in strict validation. PSC requires both start and title. `parse_timestamp()` and
`format_timestamp()` retain fractional seconds; the existing `ts_to_secs()` and
`secs_to_ts()` helpers keep their whole-second behavior.

### Description chapters

```python
from podcast_chapter_tools import parse_description_chapters

result = parse_description_chapters("0:00 Intro\n2:30 Interview (part 1)\n")
listed = parse_description_chapters("Chapters: 0:00: Intro\n1. 2:30. Interview\n")
# Strict line recognition is the default, after HTML block/<br> normalization.
inline = parse_description_chapters(
    "<p>0:00 Intro 5:00 Main 10:00 End</p>",
    mode="lenient",
)
```

At least two usable chapters are required. Strict recognition (`mode="strict"`)
accepts timestamps at the beginning of normalized lines, including bracketed
timestamps and ASCII/en/em-dash separators. Optional prefixes include a blockquote
`>`, a case-insensitive `Chapters:` label, and bullets (`-`, `*`, `+`, `•`) or
numbered markers (`1.` and `1)`) followed by whitespace. Leading Unicode format
characters (category `Cf`, including BOM and zero-width marks) are ignored during
recognition, but characters inside titles are preserved. The description and PCI
CLI commands accept UTF-8 files with or without a BOM.

A single trailing `:` or `.` followed by whitespace, a closing bracket, a dash
separator, or end-of-line is a timestamp delimiter: `0:00: Intro`, `0:00. Intro`,
and `0:00:- Intro` all work.
Decimal fractions such as `0:00.25` are retained. Lenient recognition explicitly
allows inline timestamp layouts and can interpret incidental prose as chapters;
prose mentions without a following title, such as `at 1:00.` or `at 12:75`, are
ignored before timestamp validation.
Explicit chapter lines without titles still produce validation diagnostics.
Parentheses/brackets in titles are preserved. Inline title markup and links are
retained unless `strip_html=True`. Timestamps in HTML attributes, comments, scripts,
and styles are ignored. Both modes use bounded forward scanning.

Arbitrary HTML tag names and multiline attributes remain supported. Description
extraction recovers an unquoted newline followed by a chapter-line prefix unless
that continuation line contains an attribute assignment such as `alt="y"`.
Timestamp-like boolean attributes alone are ambiguous and recover as chapter
boundaries. Generic `strip_html()` does not apply chapter-boundary recovery.
Recovered fragments stay literal: retained titles can contain text such as
`Intro <span` and are not guaranteed to be balanced HTML. Same-line text that forms
valid HTML continues to be interpreted as markup. Script/style names use ASCII
case matching; comparisons in their contents do not hide matching closing tags,
including tolerated slash and attribute suffixes.

`require_monotonic=True` requires strictly increasing starts;
`require_zero_start=True` requires the first chapter within one second of zero.
These checks are off by default. `strict=True` controls validation failures,
independently of the recognition `mode`.

CLI inline conversion likewise requires `--description-mode lenient`:

```bash
podcast-chapters from-description shownotes.txt --description-mode lenient
```

### Parse a feed once

```python
from podcast_chapter_tools import parse_feed_chapters

index = parse_feed_chapters(feed_xml, source=feed_url)  # str or bytes
for guid in index.guids:
    chapters = index.psc_for_guid(guid)  # caches this episode's parse result
    pci_url = index.pci_url_for_guid(guid)
```

Feed parsing performs no I/O. Malformed XML/no RSS channel raises
`ChapterParseError`; malformed chapter lists fail only their own episode lookup.
Missing GUIDs or chapter declarations return an empty result. Repeated GUIDs keep
the first episode and are reported through `index.issues`, even when that episode
has no chapters and a later duplicate does. This policy also applies to legacy
bulk extraction, which previously allowed later chapter-bearing duplicates to win.
Both the canonical
PodcastIndex namespace and its specified GitHub documentation alias are recognized;
the canonical declaration takes precedence. Namespace prefixes do not matter.

For file-based bulk ingestion, `extract_all_psc_chapters_from_file(feed)` reads and
parses once and returns legacy chapters keyed by GUID. Repeated calls to the
single-GUID file/URL wrappers still read/fetch the feed each time; use the reusable
index or bulk function for a batch.

Feed files are parsed as bytes, respecting XML declarations and BOMs. HTTP feeds
use a BOM first, then an explicit `Content-Type` charset, then XML byte detection.
If charset lookup or strict decoding fails, the adapter retries XML byte detection
and logs successful recovery. Successfully decoded data and structural XML errors
do not trigger fallback: an incorrect Latin-1 header can still produce garbled
text. Common XML encodings are parsed directly from bytes; other Python codecs
remain supported. Unrecoverable failures produce `ChapterParseError`; legacy
helpers return `None`.

### Fetching and archives

```python
from pathlib import Path
from podcast_chapter_tools import (
    fetch_pci_chapters,
    ChapterHTTPError,
    ChapterTransportError,
    ChapterParseError,
)

try:
    result = fetch_pci_chapters(
        "https://example.com/chapters.json",
        archive_path_json=Path("chapters.json"),
        timeout=30.0,
    )
except ChapterHTTPError as error:
    print(error.url, error.status_code, error.retry_after)
except ChapterTransportError as error:
    print(error.url, error.__cause__)
except ChapterParseError as error:
    print(error.source, error.issues)
```

HTTP failures preserve status and the raw `Retry-After` header; transport and
JSON/XML decoding failures preserve their underlying exception as `__cause__`.
All four error types and subclasses with custom constructors support pickling,
including use in `ProcessPoolExecutor`, without duplicating message context.
Reconstruction preserves arguments, attributes, notes, and declared slots without
calling subclass constructors. Their `message` attribute holds the
unformatted error text. Repeated failed index lookups raise fresh exceptions while
reusing cached failure details.
The library makes one request per fetch, follows redirects, and performs no retry
or negative caching. Consumers choose backoff and cache lifetimes. `httpx2` remains
a required dependency in 1.0.0; an HTTP extra is deferred.

An archive retains raw chapter JSON and gains `chapters.json.meta.json` containing
`version`, the exact requested `url`, and `sha256` of the archived bytes. URL/digest
mismatches, missing/invalid metadata, corruption, or unusable documents trigger one
refetch. Writes use temporary files and atomic replacement; failed writes do not
discard a successfully fetched result. A mismatched/interrupted file pair cannot
serve unverified content. Only documents that parse successfully are cached.
Replacement preserves each existing file's permissions. New archives and sidecars
use mode `0666` subject to the process umask (usually `0644` under umask `022`).
Existing owner-only files are not automatically made readable by other users.

Old raw archives require an initial online refetch. For explicitly trusted offline
archives without a metadata sidecar, pass `trust_legacy_archive=True`. Existing
metadata with a URL mismatch is never trusted, even with this option. Prefer
URL-derived cache filenames; episode titles are neither unique nor stable.

### Legacy API and conversion

Existing extractors still return `list[Chapter] | None`; `Chapter` remains the
four-field named tuple `(start, title, url, image)` and works with positional
unpacking and tuple equality. Expected parse/fetch failures translate to `None`.
Structured empty lists retain their legacy `[]` convention; descriptions with
fewer than two chapters return `None`.

Legacy conversion truncates starts to whole seconds, represents absent titles as
`""`, and drops PCI end boundaries. `toc=False` markers are excluded by default;
`include_non_toc=True` includes them in PCI wrappers. Rich parsing always retains
those markers. `result.to_legacy()` provides the same explicit conversion.

Writers accept `ChapterData`, `Chapter`, and legacy four-field tuples. PCI writers
retain optional titles, fractions, end boundaries, and silent markers. Integral
`startTime` and `endTime` values are serialized as JSON integers. PSC and
description writers omit silent markers and cannot preserve PCI end boundaries;
missing titles become empty strings. Prefer PCI for preserving rich metadata.
`normalize_chapter_data()` retains metadata, while `normalize_chapters()` keeps its
legacy return contract. ID3 extraction remains available with the `[id3]` extra.

HTML stripping follows visible text rather than inserting spaces at every inline
tag: `Part<b>One</b>` becomes `PartOne`, and `pod<b>cast</b>` becomes `podcast`.
This changes the pre-1.0 `strip_html()` and title-normalization behavior; block
tags still establish spaces or line boundaries.

The library disables its Loguru output by default. Enable it in an application
with `logger.enable("podcast_chapter_tools")`; configure handlers in the application.
The CLI enables package logging and reports entry/source/GUID diagnostics, while
separating absent chapters from failures in its error messages.

## Development

```bash
git clone git@github.com:hbmartin/podcast-chapter-tools.git
cd podcast-chapter-tools
uv sync --locked --python 3.13

uv run --locked --python 3.13 pytest
uv run ruff check .
uv run ruff format --check .
uv run pyrefly check
uv run ty check
uv run --locked pyroma --min 10 .
```

Packaging metadata is checked with `pyroma621` (the command is `pyroma`).
The checker is pinned while it is being evaluated, and its separate CI job
runs on Python 3.13 and 3.14 with `continue-on-error: true`. A score below
10 or a checker error is visible in the job logs but does not block CI;
advisory findings are shown without affecting the score. Review the findings
and checker behavior before upgrading it or making the job blocking.

[Garuff](https://github.com/gahjelle/garuff) runs in a separate, enforced CI job.
It requires Python 3.14 or newer and lives in an opt-in dependency group.
Use isolated runs locally to preserve the project's interpreter and development
packages:

```bash
uv run --isolated --locked --only-group garuff --python 3.14 garuff check .
uv run --isolated --locked --only-group garuff --python 3.14 garuff rule --all
```

The checker is pinned to commit `7d126c00f13b4d94f39f1107934089241ab7a6a1`
in `pyproject.toml` and `uv.lock`. Findings and installation, configuration, or
execution failures fail the Garuff job. Open the Garuff job summary in a
[Lint and Test workflow run](https://github.com/hbmartin/podcast-chapter-tools/actions/workflows/lint.yml)
for the current findings, explanations, and errors; full output is also kept in
the job logs.

Configuration follows project conventions: test function docstrings are optional
(`GAC010`), valid reStructuredText double backticks are allowed (`GAC004`), and
functions may accept up to four positional parameters (`GAC008`). Narrow inline
exemptions preserve existing immutable tuple annotations (`GAC005`) and positional
dataclass construction (`GAC009`); those rules remain enabled for other code.
CI checks the library, tests, and experimental scripts without automatic fixes.

On Python 3.13, exclude the Python 3.14-only group when syncing all groups:

```bash
uv sync --locked --all-groups --no-group garuff --python 3.13
```

Without that exclusion, `--all-groups` requires Python 3.14 or newer.

The `ai/` directory contains experimental scripts for generating chapters
from transcripts with LLMs; its dependencies live in `ai/requirements.txt`
and are not part of the published package.

## See also

- https://github.com/hbmartin/podcast-transcript-convert
- https://github.com/Podcastindex-org/podcast-namespace/blob/main/transcripts/transcripts.md
- https://github.com/hbmartin/overcast-to-sqlite
- https://support.spotify.com/us/podcasters/article/enabling-podcast-chapters/

## Authors
- [Harold Martin](https://www.linkedin.com/in/harold-martin-98526971/) - harold.martin at gmail
- Icon courtesy of [Vecteezy.com](https://www.vecteezy.com)
