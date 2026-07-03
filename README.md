# podcast-chapter-tools

[![Lint and Test](https://github.com/hbmartin/podcast-chapter-tools/actions/workflows/lint.yml/badge.svg)](https://github.com/hbmartin/podcast-chapter-tools/actions/workflows/lint.yml)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Checked with mypy](https://img.shields.io/badge/mypy-checked-blue.svg)](https://mypy-lang.org/)
[![twitter](https://img.shields.io/badge/@hmartin-00aced.svg?logo=twitter&logoColor=black)](https://twitter.com/hmartin)

<img src=".idea/icon.svg" width="100" align="right">

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
python3 -m venv venv
source venv/bin/activate
pip install -e '.[lint,test]'

pytest
ruff check .
ruff format --check .
mypy podcast_chapter_tools
```

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
