"""F-279 (first half) · `deck-log diff` — adjacent-round per-slide visual diff.

Covers the new `diff` subcommand that pairs two snapshot rounds by slide key and
reports per-slide change ratio, flagging changes outside the edit scope as
possible collateral damage. This is the "did heal/reconcile/batch-rewrite break
anything?" check that the editor-roundtrip dimension was missing.

What's exercised:
  • identical PNGs  → 0% diff (no slide listed as changed)
  • a clearly-altered PNG → non-zero diff (listed as changed)
  • a change to a key OUTSIDE --scope-keys → flagged "unexpected" (possible
    collateral); a change INSIDE scope is NOT flagged
  • a missing PNG / a slide present in only one round → friendly report, no crash
  • fewer than 2 snapshot versions → friendly error (rc 2), no crash
  • --from / --to version selection
  • Pillow-absent fallback: _image_diff falls back to a byte compare (identical
    bytes → 0, differing bytes → 1) and still does NOT crash

Pillow / numpy are NOT required by the diff algorithm; the perceptual-hash +
pixel-diff path uses Pillow when present, else a pure-stdlib byte compare. Tests
that need real image decoding skip cleanly when Pillow is unavailable; the
journal-resolution / missing-PNG / version-count / byte-fallback tests run
regardless.
"""
import importlib.util
import json
import pathlib

import pytest

LOG_TOOL = pathlib.Path(__file__).resolve().parent
DECK_LOG = LOG_TOOL / "deck-log.py"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


DL = _load("_deck_log_under_test", DECK_LOG)


def _have_pillow() -> bool:
    try:
        import PIL  # noqa: F401
        return True
    except Exception:
        return False


HAVE_PIL = _have_pillow()


# --------------------------------------------------------------------------- fixtures
def _solid_png(path: pathlib.Path, color, size=(64, 36)):
    """Write a small solid-color PNG fixture (Pillow-only helper)."""
    from PIL import Image
    img = Image.new("RGB", size, color)
    img.save(str(path))


def _half_split_png(path: pathlib.Path, left, right, size=(64, 36)):
    """A PNG whose left/right halves differ — clearly distinct from a solid one."""
    from PIL import Image
    img = Image.new("RGB", size, left)
    px = img.load()
    for x in range(size[0] // 2, size[0]):
        for y in range(size[1]):
            px[x, y] = right
    img.save(str(path))


def _make_run(tmp_path, slides_v1, slides_v2):
    """Build a minimal run dir with log/journal.jsonl holding two version events.

    slides_vN = list of (key, idx, png_relpath_or_None). PNG files themselves are
    created by the caller under <log>/screenshots/.
    """
    log = tmp_path / "myrun" / "log"
    (log / "screenshots" / "v001").mkdir(parents=True, exist_ok=True)
    (log / "screenshots" / "v002").mkdir(parents=True, exist_ok=True)

    def _ev(v, slides):
        return {
            "t": "version", "v": v, "label": "",
            "slides": [{"idx": idx, "key": key, "layout": "story", "h": "x",
                        "png": png} for (key, idx, png) in slides],
            "n_slides": len(slides),
        }

    journal = log / "journal.jsonl"
    with journal.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({"t": "session", "title": "t",
                             "start_ts": "2026-06-10T00:00:00+08:00"}) + "\n")
        fh.write(json.dumps(_ev("v001", slides_v1), ensure_ascii=False) + "\n")
        fh.write(json.dumps(_ev("v002", slides_v2), ensure_ascii=False) + "\n")
    return log.parent  # the run dir (deck_dir)


class _Args:
    def __init__(self, deck_dir, **kw):
        self.deck_dir = str(deck_dir)
        self.from_v = kw.get("from_v")
        self.to_v = kw.get("to_v")
        self.scope_keys = kw.get("scope_keys")
        self.threshold = kw.get("threshold")
        self.json = kw.get("json", True)   # default to JSON so tests parse output


# --------------------------------------------------------------------------- tests
@pytest.mark.skipif(not HAVE_PIL, reason="Pillow unavailable")
def test_identical_pages_zero_diff(tmp_path, capsys):
    run = _make_run(
        tmp_path,
        [("cover", 1, "screenshots/v001/s01.png"), ("body", 2, "screenshots/v001/s02.png")],
        [("cover", 1, "screenshots/v002/s01.png"), ("body", 2, "screenshots/v002/s02.png")],
    )
    log = run / "log"
    # both rounds: cover blue, body green — byte-identical re-renders
    _solid_png(log / "screenshots/v001/s01.png", (10, 20, 200))
    _solid_png(log / "screenshots/v002/s01.png", (10, 20, 200))
    _solid_png(log / "screenshots/v001/s02.png", (10, 200, 20))
    _solid_png(log / "screenshots/v002/s02.png", (10, 200, 20))

    rc = DL.cmd_diff(_Args(run))
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["from"] == "v001" and out["to"] == "v002"
    assert out["changed"] == []           # nothing crossed the 1% threshold
    assert out["unchanged"] == 2
    assert out["missing"] == []


@pytest.mark.skipif(not HAVE_PIL, reason="Pillow unavailable")
def test_altered_page_nonzero_diff(tmp_path, capsys):
    run = _make_run(
        tmp_path,
        [("cover", 1, "screenshots/v001/s01.png"), ("body", 2, "screenshots/v001/s02.png")],
        [("cover", 1, "screenshots/v002/s01.png"), ("body", 2, "screenshots/v002/s02.png")],
    )
    log = run / "log"
    _solid_png(log / "screenshots/v001/s01.png", (10, 20, 200))
    _solid_png(log / "screenshots/v002/s01.png", (10, 20, 200))   # cover unchanged
    _solid_png(log / "screenshots/v001/s02.png", (10, 200, 20))   # body was solid green
    _half_split_png(log / "screenshots/v002/s02.png", (10, 200, 20), (240, 0, 0))  # now half red

    rc = DL.cmd_diff(_Args(run))
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    changed_keys = {c["key"] for c in out["changed"]}
    assert "body" in changed_keys          # the altered page is reported
    assert "cover" not in changed_keys     # the identical page is not
    body = next(c for c in out["changed"] if c["key"] == "body")
    assert body["ratio"] > 0.0 and body["pct"] > 0.0


@pytest.mark.skipif(not HAVE_PIL, reason="Pillow unavailable")
def test_scope_out_change_flagged_unexpected(tmp_path, capsys):
    # Both 'cover' and 'body' change, but caller said only 'body' should change.
    run = _make_run(
        tmp_path,
        [("cover", 1, "screenshots/v001/s01.png"), ("body", 2, "screenshots/v001/s02.png")],
        [("cover", 1, "screenshots/v002/s01.png"), ("body", 2, "screenshots/v002/s02.png")],
    )
    log = run / "log"
    _solid_png(log / "screenshots/v001/s01.png", (10, 20, 200))
    _half_split_png(log / "screenshots/v002/s01.png", (10, 20, 200), (255, 255, 0))  # cover changed (out of scope)
    _solid_png(log / "screenshots/v001/s02.png", (10, 200, 20))
    _half_split_png(log / "screenshots/v002/s02.png", (10, 200, 20), (240, 0, 0))    # body changed (in scope)

    rc = DL.cmd_diff(_Args(run, scope_keys="body"))
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["scope_keys"] == ["body"]
    assert out["unexpected_keys"] == ["cover"]      # cover is the collateral hit
    by_key = {c["key"]: c for c in out["changed"]}
    assert by_key["cover"]["unexpected"] is True
    assert by_key["body"]["unexpected"] is False


@pytest.mark.skipif(not HAVE_PIL, reason="Pillow unavailable")
def test_human_readable_warns_on_scope_out(tmp_path, capsys):
    run = _make_run(
        tmp_path,
        [("cover", 1, "screenshots/v001/s01.png")],
        [("cover", 1, "screenshots/v002/s01.png")],
    )
    log = run / "log"
    _solid_png(log / "screenshots/v001/s01.png", (10, 20, 200))
    _half_split_png(log / "screenshots/v002/s01.png", (10, 20, 200), (255, 255, 0))
    rc = DL.cmd_diff(_Args(run, scope_keys="body", json=False))   # 'cover' not in scope
    assert rc == 0
    text = capsys.readouterr().out
    assert "scope" in text and ("误伤" in text or "意外" in text)


@pytest.mark.skipif(not HAVE_PIL, reason="Pillow unavailable")
def test_from_to_selection(tmp_path, capsys):
    run = _make_run(
        tmp_path,
        [("cover", 1, "screenshots/v001/s01.png")],
        [("cover", 1, "screenshots/v002/s01.png")],
    )
    log = run / "log"
    _solid_png(log / "screenshots/v001/s01.png", (0, 0, 0))
    _solid_png(log / "screenshots/v002/s01.png", (0, 0, 0))
    # explicit --from 1 --to 2 (int form) resolves to v001 -> v002
    rc = DL.cmd_diff(_Args(run, from_v="1", to_v="2"))
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["from"] == "v001" and out["to"] == "v002"


def test_missing_png_friendly_no_crash(tmp_path, capsys):
    # body's v002 png path points at a file that does not exist → reported, not crashed.
    run = _make_run(
        tmp_path,
        [("body", 1, "screenshots/v001/s01.png")],
        [("body", 1, "screenshots/v002/MISSING.png")],
    )
    log = run / "log"
    # create only the old one (use raw bytes so this test does not need Pillow)
    (log / "screenshots/v001/s01.png").write_bytes(b"\x89PNG\r\n\x1a\nfake-old")
    rc = DL.cmd_diff(_Args(run))
    assert rc == 0                          # graceful, not a crash
    out = json.loads(capsys.readouterr().out)
    assert out["changed"] == []
    assert any(m["key"] == "body" for m in out["missing"])
    assert "缺图" in out["missing"][0]["why"]


def test_new_page_only_in_one_round(tmp_path, capsys):
    run = _make_run(
        tmp_path,
        [("cover", 1, "screenshots/v001/s01.png")],
        [("cover", 1, "screenshots/v002/s01.png"),
         ("appendix", 2, "screenshots/v002/s02.png")],   # appendix is brand new
    )
    log = run / "log"
    (log / "screenshots/v001/s01.png").write_bytes(b"\x89PNG\r\n\x1a\nA")
    (log / "screenshots/v002/s01.png").write_bytes(b"\x89PNG\r\n\x1a\nA")
    (log / "screenshots/v002/s02.png").write_bytes(b"\x89PNG\r\n\x1a\nB")
    rc = DL.cmd_diff(_Args(run))
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert any(m["key"] == "appendix" for m in out["missing"])


def test_fewer_than_two_versions_friendly_error(tmp_path, capsys):
    log = tmp_path / "solo" / "log"
    log.mkdir(parents=True)
    with (log / "journal.jsonl").open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({"t": "session", "title": "t"}) + "\n")
        fh.write(json.dumps({"t": "version", "v": "v001", "slides": []}) + "\n")
    rc = DL.cmd_diff(_Args(log.parent))
    assert rc == 2                          # friendly non-zero, not a traceback
    err = capsys.readouterr().err
    assert "snapshot" in err or "2 个" in err


def test_no_events_friendly_error(tmp_path, capsys):
    log = tmp_path / "empty" / "log"
    log.mkdir(parents=True)
    rc = DL.cmd_diff(_Args(log.parent))
    assert rc == 2
    assert "没有任何事件" in capsys.readouterr().err


def test_unknown_version_friendly_error(tmp_path, capsys):
    run = _make_run(
        tmp_path,
        [("cover", 1, "screenshots/v001/s01.png")],
        [("cover", 1, "screenshots/v002/s01.png")],
    )
    log = run / "log"
    (log / "screenshots/v001/s01.png").write_bytes(b"\x89PNG\r\n\x1a\nA")
    (log / "screenshots/v002/s01.png").write_bytes(b"\x89PNG\r\n\x1a\nA")
    rc = DL.cmd_diff(_Args(run, from_v="9"))   # v009 does not exist
    assert rc == 2
    assert "找不到版本" in capsys.readouterr().err


# ---- byte-fallback path (exercised regardless of Pillow availability) -------
def test_image_diff_byte_fallback_identical(tmp_path, monkeypatch):
    # Force the no-Pillow path and confirm identical bytes → 0.0, method 'byte'.
    monkeypatch.setattr(DL, "_have_pillow", lambda: False)
    a = tmp_path / "a.png"; b = tmp_path / "b.png"
    a.write_bytes(b"identical-bytes")
    b.write_bytes(b"identical-bytes")
    ratio, method = DL._image_diff(a, b)
    assert ratio == 0.0 and method == "byte"


def test_image_diff_byte_fallback_differ(tmp_path, monkeypatch):
    monkeypatch.setattr(DL, "_have_pillow", lambda: False)
    a = tmp_path / "a.png"; b = tmp_path / "b.png"
    a.write_bytes(b"one")
    b.write_bytes(b"two-different")
    ratio, method = DL._image_diff(a, b)
    assert ratio == 1.0 and method == "byte"


def test_diff_runs_under_byte_fallback(tmp_path, monkeypatch, capsys):
    # End-to-end diff with Pillow disabled: differing bytes flagged as changed,
    # identical bytes not — and it does not crash.
    monkeypatch.setattr(DL, "_have_pillow", lambda: False)
    run = _make_run(
        tmp_path,
        [("cover", 1, "screenshots/v001/s01.png"), ("body", 2, "screenshots/v001/s02.png")],
        [("cover", 1, "screenshots/v002/s01.png"), ("body", 2, "screenshots/v002/s02.png")],
    )
    log = run / "log"
    (log / "screenshots/v001/s01.png").write_bytes(b"SAME")
    (log / "screenshots/v002/s01.png").write_bytes(b"SAME")            # cover identical
    (log / "screenshots/v001/s02.png").write_bytes(b"OLD-body-bytes")
    (log / "screenshots/v002/s02.png").write_bytes(b"NEW-body-bytes")  # body differs
    rc = DL.cmd_diff(_Args(run))
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["method"] == "byte"
    changed_keys = {c["key"] for c in out["changed"]}
    assert changed_keys == {"body"}
