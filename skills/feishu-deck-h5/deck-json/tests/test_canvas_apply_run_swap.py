"""apply-text-pairs.py — canvas-run text swap (no data.html).

Canvas (PPTX/hybrid-import) slides store text in data.elements[].runs[].text, not
data.html. apply-text-pairs swaps a run whose stripped text equals a find, leaving
geometry / id / per-run style untouched — while raw/html slides keep working in the
same deck. extract-text-pairs emits stripped run texts, so the two ends align.
"""
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
APPLY = ROOT / "apply-text-pairs.py"
MERGE = ROOT / "merge-canvas-lines.py"
EXTRACT = ROOT / "extract-text-pairs.py"


def _run(tmp_path, deck, pairs, *extra):
    dj = tmp_path / "deck.json"
    pj = tmp_path / "pairs.json"
    dj.write_text(json.dumps(deck, ensure_ascii=False), encoding="utf-8")
    pj.write_text(json.dumps(pairs, ensure_ascii=False), encoding="utf-8")
    r = subprocess.run([sys.executable, str(APPLY), str(dj), str(pj), *extra],
                       capture_output=True, text=True)
    out = json.loads(dj.read_text(encoding="utf-8"))
    return r, out


def _canvas_deck(elements):
    return {"version": "1.0", "deck": {"title": "t"},
            "slides": [{"key": "p1", "layout": "canvas",
                        "data": {"canvas_w": 1920, "canvas_h": 1080,
                                 "elements": elements}}]}


def _text_el(id_, text, **style):
    run = {"text": text}
    run.update(style or {"size": 40, "color": "#fff", "font": "F"})
    return {"id": id_, "type": "text", "x": 100, "y": 100, "w": 200, "h": 40, "runs": [run]}


def test_canvas_run_text_swapped_style_preserved(tmp_path):
    deck = _canvas_deck([_text_el("t1", "原始", bold=True, color="#CC0000", size=48)])
    pairs = [{"key": "p1", "replacements": [{"find": "原始", "replace": "Translated"}]}]
    r, out = _run(tmp_path, deck, pairs)
    assert r.returncode == 0, r.stderr
    run = out["slides"][0]["data"]["elements"][0]["runs"][0]
    assert run["text"] == "Translated"
    # all non-text fields preserved
    assert run["bold"] is True and run["color"] == "#CC0000" and run["size"] == 48
    # id + geometry untouched
    el = out["slides"][0]["data"]["elements"][0]
    assert el["id"] == "t1" and el["w"] == 200


def test_strip_match(tmp_path):
    # extract emits stripped finds; a run carrying surrounding whitespace still matches
    deck = _canvas_deck([_text_el("t1", "  门店  ")])
    pairs = [{"key": "p1", "replacements": [{"find": "门店", "replace": "Store"}]}]
    r, out = _run(tmp_path, deck, pairs)
    assert "1/1 命中" in r.stdout
    assert out["slides"][0]["data"]["elements"][0]["runs"][0]["text"] == "Store"


def test_find_matches_multiple_runs(tmp_path):
    # a repeated standalone run (e.g. brand) is swapped everywhere, like html-global
    deck = _canvas_deck([_text_el("t1", "飞书"), _text_el("t2", "飞书")])
    pairs = [{"key": "p1", "replacements": [{"find": "飞书", "replace": "Lark"}]}]
    r, out = _run(tmp_path, deck, pairs)
    texts = [e["runs"][0]["text"] for e in out["slides"][0]["data"]["elements"]]
    assert texts == ["Lark", "Lark"]


def test_unmatched_find_reported_exit5(tmp_path):
    deck = _canvas_deck([_text_el("t1", "门店")])
    pairs = [{"key": "p1", "replacements": [{"find": "缺失", "replace": "X"}]}]
    r, out = _run(tmp_path, deck, pairs)
    assert r.returncode == 5
    assert "0/1 命中" in r.stdout
    # nothing written on 0-hit
    assert out["slides"][0]["data"]["elements"][0]["runs"][0]["text"] == "门店"


def test_mixed_deck_html_and_canvas(tmp_path):
    # a deck with both a raw (data.html) slide and a canvas slide — both swap
    deck = {"version": "1.0", "deck": {"title": "t"}, "slides": [
        {"key": "raw1", "layout": "raw",
         "data": {"html": '<div class="slide"><p>星巴克的门店</p></div>'}},
        {"key": "p1", "layout": "canvas",
         "data": {"canvas_w": 1920, "canvas_h": 1080,
                  "elements": [_text_el("t1", "门店")]}},
    ]}
    pairs = [
        {"key": "raw1", "replacements": [{"find": "星巴克", "replace": "Starbucks"}]},
        {"key": "p1", "replacements": [{"find": "门店", "replace": "Store"}]},
    ]
    r, out = _run(tmp_path, deck, pairs)
    assert r.returncode == 0, r.stderr
    assert "Starbucks" in out["slides"][0]["data"]["html"]
    assert out["slides"][1]["data"]["elements"][0]["runs"][0]["text"] == "Store"


def test_no_text_container_still_skips(tmp_path):
    # a slide with neither data.html nor canvas elements → reported skip, exit 5
    deck = {"version": "1.0", "deck": {"title": "t"}, "slides": [
        {"key": "p1", "layout": "schema", "data": {"title": "x"}}]}
    pairs = [{"key": "p1", "replacements": [{"find": "门店", "replace": "Store"}]}]
    r, _ = _run(tmp_path, deck, pairs)
    assert r.returncode == 5
    assert "跳过" in r.stdout


def test_multi_run_element_matches_per_run_not_across(tmp_path):
    # whole-run match: a find equal to ONE run swaps it; a find spanning two runs
    # ('飞书' over runs '飞'+'书') does NOT match (documents the per-run contract —
    # merge-canvas-lines is what consolidates fragments first).
    el = {"id": "t1", "type": "text", "x": 0, "y": 0, "w": 80, "h": 40,
          "runs": [{"text": "飞", "size": 40}, {"text": "书", "size": 40}]}
    deck = _canvas_deck([el])
    pairs = [{"key": "p1", "replacements": [
        {"find": "飞", "replace": "F"},          # matches run[0]
        {"find": "飞书", "replace": "Lark"},      # spans runs → no match
    ]}]
    r, out = _run(tmp_path, deck, pairs)
    runs = out["slides"][0]["data"]["elements"][0]["runs"]
    assert [x["text"] for x in runs] == ["F", "书"]
    assert "1/2 命中" in r.stdout                 # '飞' hit, '飞书' missed


def test_non_string_run_text_does_not_crash(tmp_path):
    # a malformed/hand-edited canvas run with non-string text must not crash apply
    el = {"id": "t1", "type": "text", "x": 0, "y": 0, "w": 80, "h": 40,
          "runs": [{"text": None}, {"text": "门店"}]}
    deck = _canvas_deck([el])
    pairs = [{"key": "p1", "replacements": [{"find": "门店", "replace": "Store"}]}]
    r, out = _run(tmp_path, deck, pairs)
    assert r.returncode == 0, r.stderr
    assert out["slides"][0]["data"]["elements"][0]["runs"][1]["text"] == "Store"


def test_merge_extract_apply_chain(tmp_path):
    # end-to-end (stdlib only): fragmented p1 + intact p2 →
    # merge-canvas-lines → extract-text-pairs → fill → apply-text-pairs.
    def frag(id_, x, text):
        return {"id": id_, "type": "text", "x": x, "y": 100, "w": 40, "h": 40,
                "runs": [{"text": text, "size": 40, "color": "#fff", "font": "F"}]}
    deck = {"version": "1.0", "deck": {"title": "t"}, "slides": [
        {"key": "p1", "layout": "canvas", "data": {"canvas_w": 1920, "canvas_h": 1080,
         "elements": [frag("a", 100, "星"), frag("b", 140, "巴"), frag("c", 180, "克")]}},
        {"key": "p2", "layout": "canvas", "data": {"canvas_w": 1920, "canvas_h": 1080,
         "elements": [{"id": "d", "type": "text", "x": 100, "y": 100, "w": 120, "h": 40,
                       "runs": [{"text": "门店", "size": 40, "color": "#fff", "font": "F"}]}]}},
    ]}
    dj = tmp_path / "deck.json"
    dj.write_text(json.dumps(deck, ensure_ascii=False), encoding="utf-8")

    # 1) merge fragments into logical lines
    assert subprocess.run([sys.executable, str(MERGE), str(dj)],
                          capture_output=True, text=True).returncode == 0
    # 2) extract finds (now whole lines)
    ex = subprocess.run([sys.executable, str(EXTRACT), str(dj)],
                        capture_output=True, text=True)
    skel = json.loads(ex.stdout)
    finds = {f["find"] for s in skel for f in s["replacements"]}
    assert finds == {"星巴克", "门店"}            # p1 fragments merged, p2 intact
    # 3) fill + apply
    table = {"星巴克": "Starbucks", "门店": "Store"}
    for s in skel:
        for f in s["replacements"]:
            f["replace"] = table[f["find"]]
    pj = tmp_path / "pairs.json"
    pj.write_text(json.dumps(skel, ensure_ascii=False), encoding="utf-8")
    ap = subprocess.run([sys.executable, str(APPLY), str(dj), str(pj)],
                        capture_output=True, text=True)
    assert ap.returncode == 0, ap.stderr
    out = json.loads(dj.read_text(encoding="utf-8"))
    p1, p2 = out["slides"]
    assert p1["data"]["elements"][0]["runs"][0]["text"] == "Starbucks"
    assert len(p1["data"]["elements"]) == 1       # b,c removed by merge
    assert p2["data"]["elements"][0]["runs"][0]["text"] == "Store"
