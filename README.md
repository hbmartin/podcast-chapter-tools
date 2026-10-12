# podcast-chapter-tools

[![Lint and Test](https://github.com/hbmartin/podcast-chapter-tools/actions/workflows/lint.yml/badge.svg)](https://github.com/hbmartin/podcast-chapter-tools/actions/workflows/lint.yml)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Checked with Pyrefly](https://img.shields.io/badge/pyrefly-checked-blue.svg)](https://pyrefly.org/)
[![Checked with ty](https://img.shields.io/badge/ty-checked-blue.svg)](https://docs.astral.sh/ty/)
[![twitter](https://img.shields.io/badge/@hmartin-00aced.svg?logo=twitter&logoColor=white)](https://twitter.com/hmartin)

<img src="https://raw.githubusercontent.com/hbmartin/podcast-chapter-tools/main/.idea/icon.svg" width="100" align="right">

Extract and transform podcast chapter information between
[PodcastIndex (PCI) chapters](https://github.com/Podcastindex-org/podcast-namespace/blob/main/docs/examples/chaptering/jsonChapters.md),
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

Every extractor returns `list[Chapter] | None`, where `Chapter` is a named
tuple of `(start, title, url, image)` with the start time in seconds:

```python
from podcast_chapter_tools import (
    extract_description_chapters,
    extract_psc_chapters_from_file,
    get_and_extract_pci_chapters,
    chapters_to_pci_json,
    normalize_chapters,
)
from pathlib import Path

# From show notes (plain text or HTML)
chapters = extract_description_chapters("0:00 Intro\n2:30 Interview\n")
# [Chapter(start=0, title='Intro', ...), Chapter(start=150, title='Interview', ...)]

# From a feed's Podlove Simple Chapters
chapters = extract_psc_chapters_from_file(Path("feed.xml"), guid="episode-guid")

# From a PodcastIndex chapters URL
chapters = get_and_extract_pci_chapters("https://example.com/chapters.json")

# Clean up and convert
chapters = normalize_chapters(chapters, strip_titles=True)
print(chapters_to_pci_json(chapters, indent=2))
```

Other useful entry points:

- `extract_all_psc_chapters_from_file(feed)` - chapters for every episode, keyed by GUID
- `extract_psc_chapters_from_url(feed_url, guid)` - fetch the feed for you
- `find_pci_chapters_url(feed, guid)` - discover the `<podcast:chapters>` URL declared in a feed
- `extract_id3_chapters(Path("episode.mp3"))` - ID3v2 CHAP frames (requires the `[id3]` extra)
- `chapters_to_psc_xml(chapters)` / `chapters_to_description(chapters)` - other writers
- `ts_to_secs("1:02:03")` / `secs_to_ts(3723)` - timestamp helpers

## Development

```bash
git clone git@github.com:hbmartin/podcast-chapter-tools.git
cd podcast-chapter-tools
uv sync

uv run pytest
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

[Garuff](https://github.com/gahjelle/garuff) is also being evaluated in a separate,
non-blocking CI job. It requires Python 3.14 or newer, so it lives in an opt-in
dependency group rather than the default development environment:

```bash
uv run --locked --only-group garuff --python 3.14 garuff check .
uv run --locked --only-group garuff --python 3.14 garuff rule --all
```

The checker is pinned to commit `7d126c00f13b4d94f39f1107934089241ab7a6a1`
in `pyproject.toml` and `uv.lock` because upstream has no packaged release yet.
CI keeps the full findings, explanations, and errors in the job logs and summary.
All default rules remain enabled across the library, tests, and experimental
scripts; no automatic fixes are applied. A nonzero checker exit fails its step
but is tolerated by the experimental job, including installation or checker errors.

The initial evaluation found 195 style violations: 146 missing function docstrings
(`GAC010`), 37 functions with multiple positional parameters (`GAC008`), and 12
docstrings using double backticks (`GAC004`). Of those findings, 140 are in tests,
34 in the library, and 21 in experimental scripts. These preferences need review
before enforcement: tests already omit docstrings by convention, double backticks
are valid reStructuredText, and adding keyword-only parameters to public functions
would break existing positional callers. Review findings and Python 3.13
compatibility before applying fixes, updating the pin, or making this job blocking.
Repeated Python 3.14 runs produced identical reports without crashes; rule
explanations and the missing-path error diagnostic also worked as expected.

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
