import importlib
import sys
from types import ModuleType, SimpleNamespace


def test_ai_chapters_imports_nested_ai_package(monkeypatch):
    nested_ai = ModuleType("ai.ai")
    nested_ai.complete = lambda **kw: {}
    nested_ai.prompt_transcript_to_chapters = lambda transcript: {"default": transcript}

    loguru = ModuleType("loguru")
    loguru.logger = SimpleNamespace(info=lambda *a, **kw: None)

    json2simple = ModuleType("podcast_transcript_tools.json2simple")
    json2simple.json_file_to_simple_file = lambda *a, **kw: None

    monkeypatch.setitem(sys.modules, "ai.ai", nested_ai)
    monkeypatch.setitem(sys.modules, "loguru", loguru)
    monkeypatch.setitem(
        sys.modules, "podcast_transcript_tools", ModuleType("podcast_transcript_tools")
    )
    monkeypatch.setitem(
        sys.modules, "podcast_transcript_tools.json2simple", json2simple
    )
    monkeypatch.setitem(sys.modules, "tiktoken", ModuleType("tiktoken"))
    sys.modules.pop("ai.chapters", None)

    chapters = importlib.import_module("ai.chapters")

    assert chapters.complete is nested_ai.complete
    assert (
        chapters.prompt_transcript_to_chapters
        is nested_ai.prompt_transcript_to_chapters
    )
