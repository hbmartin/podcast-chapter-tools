import copy
import json
import multiprocessing
import pickle
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from html import escape
from urllib.parse import quote

import pytest

from podcast_chapter_tools import (
    ChapterData,
    ChapterTransportError,
    errors,
    markup,
    parse_description_chapters,
)
from podcast_chapter_tools.cli import main
from podcast_chapter_tools.normalize import strip_html
from podcast_chapter_tools.writers import chapters_to_description


@pytest.mark.parametrize(
    "boundary", ["<br>", "</p><p>", "<div>", "&#10;", "&#13;", "&NewLine;"]
)
@pytest.mark.parametrize("tag", ["strong", 'a href="https://e.com/live"'])
def test_visible_boundaries_reset_physical_chapter_context(boundary, tag):
    name = tag.split()[0]
    text = (
        f"0:00 Intro{boundary}Join us live at <{tag}\n"
        f"  >12:30 PM ET</{name}\n  > every Tuesday.\n1:00 Next\n2:00 End"
    )
    result = parse_description_chapters(text, strict=True, require_monotonic=True)
    assert [c.start for c in result.chapters] == [0, 60, 120]
    assert 750 in [
        c.start for c in parse_description_chapters(text, mode="lenient").chapters
    ]


@pytest.mark.parametrize("tag", ["script", "style"])
@pytest.mark.parametrize("closing", [False, True])
@pytest.mark.parametrize("prefix", ["", "<p>", "<p>&gt; "])
def test_pending_raw_openings_recover_inside_chapters(tag, closing, prefix):
    suffix = f"</{tag}>" if closing else ""
    result = parse_description_chapters(
        f"{prefix}0:00 Intro <{tag}\n>1:00 Next{suffix}\n2:00 End"
    )
    assert [(c.start, c.title) for c in result.chapters] == [
        (0, f"Intro <{tag}"),
        (60, "Next"),
        (120, "End"),
    ]


@pytest.mark.parametrize("tag", ["script", "style"])
def test_normal_raw_blocks_and_generic_stripping_remain_suppressed(tag):
    text = f"0:00 Intro <{tag}>\n1:00 Hidden</{tag}>\n2:00 End"
    assert [c.start for c in parse_description_chapters(text).chapters] == [0, 120]
    assert strip_html(f"<{tag}\n>0:00 Hidden") == ""


@pytest.mark.parametrize("tag", ["script", "style"])
def test_malformed_raw_closing_consumes_its_terminator(tag):
    text = f"0:00 Intro <{tag}>x</{tag} <b>\n>1:00 Next\n2:00 End"
    assert [c.title for c in parse_description_chapters(text).chapters] == [
        "Intro",
        "Next",
        "End",
    ]


@pytest.mark.parametrize(
    "title", ["a<b<c> x", "if x<y<z> then", 'a<b"c> x', "a<b'c> x"]
)
@pytest.mark.parametrize("stripped", [False, True])
def test_invalid_tag_names_preserve_comparison_text(title, stripped):
    result = parse_description_chapters(f"0:00 {title}\n1:00 End", strip_html=stripped)
    assert [c.title for c in result.chapters] == [title, "End"]


def test_nested_less_than_cannot_create_a_block_boundary():
    result = parse_description_chapters(
        "0:00 Intro\n<em</p>1:00 Inline mention\n2:00 End"
    )
    assert [c.start for c in result.chapters] == [0, 120]


@pytest.mark.parametrize(
    "title",
    ["Why .NET = productivity", "*5 = great", "a|b = c", "Notes:[1] = x", ".5 = beta"],
)
def test_bare_framework_prose_recovers(title):
    result = parse_description_chapters(
        f"0:00 Intro <b\n1:00 {title} -> more\n2:00 End"
    )
    assert [c.title for c in result.chapters] == ["Intro <b", title + " -> more", "End"]


@pytest.mark.parametrize(
    "name",
    [
        "@click",
        "#ref",
        "[prop]",
        "(evt)",
        "[(ngModel)]",
        "*ngIf",
        ".value",
        "v-bind:[key]",
        "on:click|once",
    ],
)
@pytest.mark.parametrize("gap", ["", " ", "\n "])
def test_framework_recovery_evidence_requires_quoted_values(name, gap):
    text = (
        f'<custom\n0:00 #ref {name} ={gap}"y>z">hidden</custom>\n1:00 Intro\n2:00 End'
    )
    assert [c.start for c in parse_description_chapters(text).chapters] == [60, 120]
    bare = f"<custom\n0:00 #ref {name}=play>hidden</custom>\n1:00 Intro\n2:00 End"
    assert [c.start for c in parse_description_chapters(bare).chapters] == [0, 60, 120]
    assert strip_html(f"<custom {name}=play>visible</custom>") == "visible"


@pytest.mark.parametrize("name", ["plain", "1x", "xml:lang", "café"])
@pytest.mark.parametrize("value", ["play", "\nplay", '\n"play"'])
def test_plain_attribute_bare_values_need_same_line_or_closed_quotes(name, value):
    text = f"<custom\n0:00 #ref {name}={value}>hidden</custom>\n1:00 Intro\n2:00 End"
    expected = [0, 60, 120] if value == "\nplay" else [60, 120]
    assert [c.start for c in parse_description_chapters(text).chapters] == expected


@pytest.mark.parametrize(
    "fragment",
    ["&#10;", "&NewLine;", "&#13;", "<br>", "<p>", "&#x3c;br&#x3e;", '"', "'"],
)
@pytest.mark.parametrize("in_title", [False, True])
def test_url_markup_cannot_inject_chapters(fragment, in_title):
    url = f"https://x.com/{fragment}0:30 Injected"
    chapter = ChapterData(0, "Intro " + url if in_title else "Intro", url)
    rendered = chapters_to_description([chapter, ChapterData(60, "End")])
    safe = escape(
        "".join(quote(c, safe="") if c.isspace() or c in "<>\"'" else c for c in url),
        quote=False,
    )
    assert rendered == f"0:00 Intro {safe}\n1:00 End"
    for mode in ("strict", "lenient"):
        parsed = parse_description_chapters(rendered, mode=mode)
        assert [c.start for c in parsed.chapters] == [0, 60]
        assert parsed.chapters[0].url == "".join(
            quote(c, safe="") if c.isspace() or c in "<>\"'" else c for c in url
        )
    assert chapter.url == url
    assert chapter.title == ("Intro " + url if in_title else "Intro")


@pytest.mark.parametrize("title_kind", ["absent", "raw", "rendered"])
@pytest.mark.parametrize(
    "url",
    [
        "https://x.com/?a=1&b=2",
        "https://x.com/?a=1&",
        "https://x.com/%20?copy=1&copy=2",
    ],
)
def test_safe_url_deduplication_preserves_query_semantics(title_kind, url):
    safe = escape(url, quote=False)
    title = (
        "Intro"
        if title_kind == "absent"
        else "Intro " + (url if title_kind == "raw" else safe)
    )
    chapter = ChapterData(0, title, url)
    rendered = chapters_to_description([chapter, ChapterData(60, "End")])
    assert rendered == f"0:00 Intro {safe}\n1:00 End"
    assert parse_description_chapters(rendered).chapters[0].url == url
    assert chapter.title == title


def test_url_inside_title_is_escaped_before_title_boundary_flattening():
    url = "https://x.com/\r\n0:30"
    chapter = ChapterData(0, f"Intro <b>{url}</b>", url)
    assert (
        chapters_to_description([chapter])
        == "0:00 Intro <b>https://x.com/%0D%0A0:30</b>"
    )
    assert chapter.title == f"Intro <b>{url}</b>"


def test_empty_url_does_not_change_description_output():
    assert chapters_to_description([ChapterData(0, "Intro", "")]) == "0:00 Intro"


@pytest.mark.parametrize("in_title", [False, True])
def test_url_surrogates_leave_cli_destination_and_permissions_unchanged(
    tmp_path, in_title
):
    url = "https://x.com/\ud800"
    source, destination = tmp_path / "input.json", tmp_path / "output.txt"
    source.write_text(
        json.dumps(
            {
                "chapters": [
                    {
                        "startTime": 0,
                        "title": "Intro " + url if in_title else "Intro",
                        "url": url,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    destination.write_bytes(b"KEEP EXISTING OUTPUT")
    destination.chmod(0o640)
    assert (
        main(["from-pci", str(source), "--to", "description", "-o", str(destination)])
        == 1
    )
    assert destination.read_bytes() == b"KEEP EXISTING OUTPUT"
    assert destination.stat().st_mode & 0o777 == 0o640


class _LateError(ChapterTransportError, OSError):
    def __init__(self, *native):
        super().__init__("failure", url="https://e.com")
        OSError.__init__(self, *native)


_OPERATIONS = [*range(pickle.HIGHEST_PROTOCOL + 1), "copy", "deepcopy"]


def _roundtrip(error, operation):
    if isinstance(operation, int):
        return pickle.loads(pickle.dumps(error, protocol=operation))  # noqa: S301 - Test-owned state.
    return copy.copy(error) if operation == "copy" else copy.deepcopy(error)


@pytest.mark.parametrize("operation", _OPERATIONS)
@pytest.mark.parametrize(
    ("native", "field", "value"),
    [((None, "m"), "strerror", "z"), ((2, None), "errno", 3)],
)
def test_native_none_survives_changes_to_the_other_field(
    operation, native, field, value
):
    error = _LateError(*native)
    setattr(error, field, value)
    error.add_note("note")
    error.peer = error
    restored = _roundtrip(error, operation)
    assert str(restored) == str(error)
    assert restored.args == error.args
    assert restored.__notes__ == ["note"]
    assert restored.peer is (error if operation == "copy" else restored)
    assert not any(name.startswith("_chapter") for name in vars(error))


@pytest.mark.parametrize("operation", _OPERATIONS)
@pytest.mark.parametrize(
    ("native", "field"), [((None, "m"), "strerror"), ((2, None), "errno")]
)
@pytest.mark.parametrize("deleted", [False, True])
def test_native_none_survives_other_field_none_assignments_and_deletions(
    operation, native, field, deleted
):
    error = _LateError(*native)
    setattr(error, field, None)
    if deleted:
        delattr(error, field)
    assert str(_roundtrip(error, operation)) == str(error)


class _OpaqueValue:
    def __str__(self):  # noqa: PLE0307 - Formatting must fail in this regression.
        pytest.fail("Native capture called user formatting")

    def __repr__(self):
        pytest.fail("Native capture called user formatting")


@pytest.mark.parametrize("operation", _OPERATIONS)
def test_native_none_with_opaque_other_field_avoids_user_formatting(operation):
    error = _LateError(None, "m")
    error.strerror = _OpaqueValue()
    restored = _roundtrip(error, operation)
    assert restored.errno is None
    assert isinstance(restored.strerror, _OpaqueValue)
    assert errors._native_fields(restored)[OSError, "errno"]  # noqa: SLF001 - Assert native presence without formatting an opaque value.


class _GetterMutatesNativeError(_LateError):
    def __getstate__(self):
        OSError.__init__(self, None, "m")
        OSError.strerror.__set__(self, "changed")
        return self.__dict__


@pytest.mark.parametrize("operation", _OPERATIONS)
def test_native_capture_handles_descriptor_mutation_in_state_getter(operation):
    error = _GetterMutatesNativeError(2, "initial")
    restored = _roundtrip(error, operation)
    assert str(restored) == str(error) == "[Errno None] changed"


def test_native_capture_skips_probes_without_unresolved_none_fields(monkeypatch):
    def forbidden(*args):
        pytest.fail("Native capture formatted an error with no unresolved None")

    error = _LateError(2, "m")
    monkeypatch.setattr(errors, "_matches_native_format", forbidden)
    assert str(copy.copy(error)) == str(error)


def _raise_mutated_native():
    error = _LateError(None, "m")
    error.strerror = "changed"
    raise error


def test_mutated_native_worker_failure_preserves_type_and_pool():
    with ProcessPoolExecutor(
        max_workers=1, mp_context=multiprocessing.get_context("spawn")
    ) as pool:
        with pytest.raises(_LateError, match=r"\[Errno None\] changed"):
            pool.submit(_raise_mutated_native).result(timeout=20)
        assert pool.submit(abs, -3).result(timeout=20) == 3


def test_generic_markup_bypasses_recovery_cache_and_token_objects(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Generic markup constructed recovery-only state")

    monkeypatch.setattr(markup, "_TagCache", forbidden)
    monkeypatch.setattr(markup, "_TagToken", forbidden)
    assert strip_html("one <span>x</span><script>x</script>") == "one x"
    assert markup.inline_fragment("one <b>x</b>") == "one <b>x</b>"


def test_cached_matching_survives_consumed_chunk_release(monkeypatch):
    caches = []
    scanned = []
    initialize = markup._TagCache.__init__  # noqa: SLF001 - Verify retained storage.
    original_scan = markup._TagCache._scan  # noqa: SLF001 - Verify bounded lookahead.

    def construct(cache, text, **options):
        initialize(cache, text, **options)
        caches.append(cache)

    def scan(cache, start):
        scanned.append(start)
        return original_scan(cache, start)

    monkeypatch.setattr(markup._TagCache, "__init__", construct)  # noqa: SLF001 - Private scanner instrumentation.
    monkeypatch.setattr(markup._TagCache, "_scan", scan)  # noqa: SLF001 - Private scanner instrumentation.
    text = "0:00 Intro <unclosed\n>1:00 Next " + " ".join(
        f"<custom\n>{index + 2}:00 Title</custom>" for index in range(2500)
    )
    lines = markup.description_lines(text, recover_chapters=True)
    assert len(lines) == 2502
    assert len(scanned) == len(set(scanned)) == 5001
    assert len(caches[0].tokens.blocks) <= 1
    assert not caches[0].openings


def test_compact_offsets_support_sources_larger_than_32_bits():
    start = 2**32 + 17
    store = markup._TokenStore(start + 100)  # noqa: SLF001 - Exercise large-offset storage without allocating a large input.
    token = markup._TagToken(start=start, end=start + 3, name="b", complete=True)  # noqa: SLF001 - Private boundary record.
    store.append(token)
    assert store.width == "Q"
    assert store.consume(start) == token


@pytest.mark.parametrize(
    ("size", "lookahead", "limit"),
    [(1024 * 1024, False, 64), (5 * 1024 * 1024, True, 40)],
)
def test_dense_unbalanced_markup_memory_is_bounded(size, lookahead, limit):
    code = f"""
import json, tracemalloc
from podcast_chapter_tools import parse_description_chapters, markup
text = '0:00 Intro <b\\n>1:00 Next ' + '<b>' * ({size} // 3) + '\\n2:00 End'
tracemalloc.start()
if {lookahead!r}:
    cache = markup._TagCache(text, recover_chapters=True)
    assert not cache.balanced(cache.token(text.index('<')), visible=markup._ChapterPrefix(), source=markup._SourcePrefix())
else:
    result = parse_description_chapters(text)
    assert len(result.chapters) == 3
_, peak = tracemalloc.get_traced_memory()
assert peak < {limit} * 1024 * 1024, peak
print(json.dumps({{'peak': peak}}))
"""
    completed = subprocess.run(  # noqa: S603 - Fixed isolated memory regression.
        [sys.executable, "-c", code],
        check=True,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert json.loads(completed.stdout)["peak"] < limit * 1024 * 1024
