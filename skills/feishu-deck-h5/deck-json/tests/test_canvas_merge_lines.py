"""merge-canvas-lines.py — cluster PDF-fragmented canvas runs into logical lines.

A hybrid (LibreOffice-PDF) import splits one visual line into many abutting
single-glyph text elements. merge-canvas-lines clusters them back: same style +
same y-band + x-adjacent (small gap) → merged into the leftmost host, far
elements (big x-gap) stay separate, siblings are deleted, host widens. Idempotent.
"""
import importlib.util
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
MERGE = ROOT / "merge-canvas-lines.py"


def _load_merge_module():
    spec = importlib.util.spec_from_file_location("merge_canvas_lines", MERGE)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


_merge = _load_merge_module()


def _frag(id_, x, text, w=40, y=100, h=40, size=40, color="#fff", font="F"):
    return {"id": id_, "type": "text", "x": x, "y": y, "w": w, "h": h,
            "runs": [{"text": text, "size": size, "color": color, "font": font}]}


def _deck(elements):
    return {"version": "1.0", "deck": {"title": "t"},
            "slides": [{"key": "p1", "layout": "canvas",
                        "data": {"canvas_w": 1920, "canvas_h": 1080,
                                 "elements": elements}}]}


def _els(deck):
    return deck["slides"][0]["data"]["elements"]


def _text(el):
    return "".join(r.get("text", "") for r in el.get("runs", []))


# ---- core clustering (module-level merge_slide) ----

def test_abutting_same_style_merge_into_host():
    deck = _deck([_frag("a", 100, "星"), _frag("b", 140, "巴"), _frag("c", 180, "克")])
    recs = _merge.merge_slide(deck["slides"][0], 0.6, 0.6)
    els = _els(deck)
    # three fragments collapse to one host element
    assert len(els) == 1
    host = els[0]
    assert host["id"] == "a"
    assert _text(host) == "星巴克"
    # host widened to span the whole segment (100 → 180+40 = 220)
    assert host["w"] == 120
    # merge record reported
    assert recs[0]["host_id"] == "a" and recs[0]["n_elements"] == 3
    assert recs[0]["member_ids"] == ["a", "b", "c"]


def test_big_x_gap_not_merged():
    # "门店" sits far to the right (big gap) — must stay its own element
    deck = _deck([_frag("a", 100, "星"), _frag("b", 140, "巴"),
                  _frag("d", 900, "门店", w=120)])
    _merge.merge_slide(deck["slides"][0], 0.6, 0.6)
    # ordering preserved: host 'a' (absorbing b) stays before far element 'd'
    ids = [e["id"] for e in _els(deck)]
    assert ids == ["a", "d"]
    by = {e["id"]: _text(e) for e in _els(deck)}
    assert by == {"a": "星巴", "d": "门店"}


def test_different_style_not_merged():
    # same row/abutting but different size → different logical run, no merge
    deck = _deck([_frag("a", 100, "标", size=40), _frag("b", 140, "题", size=88)])
    _merge.merge_slide(deck["slides"][0], 0.6, 0.6)
    assert {e["id"] for e in _els(deck)} == {"a", "b"}


def test_different_y_band_not_merged():
    # same style/x but two visual lines (y far apart) → separate
    deck = _deck([_frag("a", 100, "上", y=100), _frag("b", 100, "下", y=300)])
    _merge.merge_slide(deck["slides"][0], 0.6, 0.6)
    assert {e["id"] for e in _els(deck)} == {"a", "b"}


def test_images_and_singletons_untouched():
    deck = _deck([_frag("a", 100, "整句不碎", w=200),
                  {"id": "img", "type": "image", "x": 0, "y": 0,
                   "w": 1920, "h": 1080, "src": "bg/p1.jpg"}])
    recs = _merge.merge_slide(deck["slides"][0], 0.6, 0.6)
    assert recs == []                              # nothing to merge
    assert {e["id"] for e in _els(deck)} == {"a", "img"}


def test_host_run_style_preserved():
    deck = _deck([_frag("a", 100, "甲", color="#abc", font="Foo", size=36),
                  _frag("b", 140, "乙", color="#abc", font="Foo", size=36)])
    _merge.merge_slide(deck["slides"][0], 0.6, 0.6)
    run = _els(deck)[0]["runs"][0]
    assert run["text"] == "甲乙"
    assert (run["color"], run["font"], run["size"]) == ("#abc", "Foo", 36)


# ---- CLI: backup, write-back, review sidecar, idempotency ----

def test_cli_writes_backup_review_and_is_idempotent(tmp_path):
    deck = _deck([_frag("a", 100, "星"), _frag("b", 140, "巴"), _frag("c", 180, "克")])
    dj = tmp_path / "deck.json"
    dj.write_text(json.dumps(deck, ensure_ascii=False), encoding="utf-8")
    review = tmp_path / "review.json"

    r = subprocess.run([sys.executable, str(MERGE), str(dj), "--review", str(review)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    # backup created
    assert list(tmp_path.glob("deck.json.bak-pre-merge-*"))
    # review sidecar lists the merged line
    rv = json.loads(review.read_text(encoding="utf-8"))
    assert rv[0]["key"] == "p1" and rv[0]["merged"][0]["merged_text"] == "星巴克"
    # written deck has the merged element
    after = json.loads(dj.read_text(encoding="utf-8"))
    assert len(after["slides"][0]["data"]["elements"]) == 1

    # second run is a no-op (idempotent): nothing left to merge, no write
    r2 = subprocess.run([sys.executable, str(MERGE), str(dj), "--dry-run"],
                        capture_output=True, text=True)
    assert r2.returncode == 0
    assert "合并 0 条" in r2.stdout
