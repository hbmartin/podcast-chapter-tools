from pathlib import Path

import pytest

FEED_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
     xmlns:psc="http://podlove.org/simple-chapters"
     xmlns:podcast="https://podcastindex.org/namespace/1.0">
  <channel>
    <title>Test Podcast</title>
    <item>
      <title>Episode One</title>
      <guid>guid-1</guid>
      <psc:chapters version="1.2">
        <psc:chapter start="00:00:00" title="Intro"/>
        <psc:chapter start="00:05:10" title="Main topic" href="https://example.com/topic"/>
        <psc:chapter start="01:00:00" title="Outro" image="https://example.com/outro.png"/>
      </psc:chapters>
    </item>
    <item>
      <title>Episode Two</title>
      <guid>guid-2</guid>
      <podcast:chapters url="https://example.com/chapters-2.json" type="application/json+chapters"/>
    </item>
    <item>
      <title>Episode Three</title>
      <guid>guid-3</guid>
    </item>
  </channel>
</rss>
"""


@pytest.fixture
def feed_file(tmp_path: Path) -> Path:
    path = tmp_path / "feed.xml"
    path.write_text(FEED_XML)
    return path


PCI_JSON = {
    "version": "1.2.0",
    "chapters": [
        {"startTime": 0, "title": "Intro"},
        {
            "startTime": 310,
            "title": "Main topic",
            "url": "https://example.com/topic",
            "img": "https://example.com/topic.png",
        },
    ],
}


@pytest.fixture
def pci_json() -> dict:
    return {
        "version": PCI_JSON["version"],
        "chapters": [dict(c) for c in PCI_JSON["chapters"]],
    }


class FakeResponse:
    def __init__(self, *, is_success=True, status_code=200, json_data=None, text=""):
        self.is_success = is_success
        self.status_code = status_code
        self._json_data = json_data
        self.text = text

    def json(self):
        return self._json_data
