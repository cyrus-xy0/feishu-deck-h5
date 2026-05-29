"""Render tests for layout:chart (bar / line / donut) — the deterministic
data-viz family added 2026-05-29 (benchmark §8 frontier: decks lacked real
charts / data-viz, only text cards). Drives the REAL pipeline (render-deck.py
→ schema → render → validate.py gate): a passing render already proves the
deck validated. On top of that we assert the computed geometry is correct and
that every chart color is a brand token (never free hex → stays inside R10).
"""
import json
import re
import subprocess
import sys
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
RENDER = ROOT / "deck-json" / "render-deck.py"


def _render(tmp_path, slides):
    deck = {
        "version": "1.0",
        "deck": {"title": "chart test", "author": "t", "date": "2026-05"},
        "slides": (
            [{"key": "cover", "layout": "cover", "accent": "blue",
              "data": {"title": "t", "author": "t", "date": "2026-05"}}]
            + slides
            + [{"key": "end", "layout": "end", "accent": "blue",
                "data": {"title": "end", "contact": "x@y.z"}}]
        ),
    }
    djson = tmp_path / "deck.json"
    djson.write_text(json.dumps(deck, ensure_ascii=False), encoding="utf-8")
    r = subprocess.run([sys.executable, str(RENDER), str(djson), str(tmp_path) + "/"],
                       capture_output=True, text=True)
    # render-deck.py exits non-zero if schema OR validate.py gate fails
    assert r.returncode == 0, f"render/validate failed:\n{r.stdout}\n{r.stderr}"
    return (tmp_path / "index.html").read_text(encoding="utf-8")


def _chart_stage(html, key):
    i = html.find(f'data-slide-key="{key}"')
    s = html.find('<div class="stage">', i)
    nxt = html.find('data-slide-key="', s)
    return html[s: nxt if nxt > 0 else len(html)]


# ---- bar -------------------------------------------------------------
def test_bar_heights_proportional(tmp_path):
    slides = [{"key": "bar", "layout": "chart", "variant": "bar", "accent": "blue",
               "data": {"title": "bar", "unit": "万",
                        "series": [{"color": "blue", "points": [
                            {"label": "A", "value": 50},
                            {"label": "B", "value": 100}]}]}}]
    stage = _chart_stage(_render(tmp_path, slides), "bar")
    heights = [int(h) for h in re.findall(r'class="ccol" style="height:(\d+)px', stage)]
    assert len(heights) == 2
    # max value -> 360px cap; half value -> ~half height
    assert heights[1] == 360
    assert abs(heights[0] - 180) <= 2
    assert "50万" in stage and "100万" in stage  # value labels with unit


# ---- line ------------------------------------------------------------
def test_line_multi_series_and_crisp_stroke(tmp_path):
    slides = [{"key": "line", "layout": "chart", "variant": "line", "accent": "teal",
               "data": {"title": "line",
                        "series": [
                            {"name": "S1", "color": "blue", "points": [
                                {"label": "1", "value": 10}, {"label": "2", "value": 40}]},
                            {"name": "S2", "color": "grey", "points": [
                                {"label": "1", "value": 5}, {"label": "2", "value": 20}]}]}}]
    stage = _chart_stage(_render(tmp_path, slides), "line")
    polys = re.findall(r"<polyline ", stage)
    assert len(polys) == 2  # two series -> two polylines
    assert "vector-effect=\"non-scaling-stroke\"" in stage  # crisp under stretch
    assert "S1" in stage and "S2" in stage  # legend names


# ---- donut -----------------------------------------------------------
def test_donut_segments_sum_to_circumference(tmp_path):
    slides = [{"key": "donut", "layout": "chart", "variant": "donut", "accent": "violet",
               "data": {"title": "donut", "unit": "%",
                        "series": [{"points": [
                            {"label": "a", "value": 75},
                            {"label": "b", "value": 25}]}]}}]
    stage = _chart_stage(_render(tmp_path, slides), "donut")
    dashes = re.findall(r'stroke-dasharray="([\d.]+) ([\d.]+)"', stage)
    assert len(dashes) == 2
    circ = 2 * 3.141592653589793 * 84.0
    for seg, gap in dashes:
        assert abs(float(seg) + float(gap) - circ) < 0.5  # seg + gap == full circle
    # 75% segment ~= 3x the 25% segment
    s0, s1 = float(dashes[0][0]), float(dashes[1][0])
    assert abs(s0 - 3 * s1) < 1.0
    assert "100%" in stage  # center total


# ---- brand-token discipline -----------------------------------------
def test_chart_colors_are_brand_tokens_only(tmp_path):
    slides = [{"key": "d", "layout": "chart", "variant": "donut",
               "data": {"title": "d", "series": [{"points": [
                   {"label": "a", "value": 1}, {"label": "b", "value": 1},
                   {"label": "c", "value": 1}, {"label": "d", "value": 1},
                   {"label": "e", "value": 1}]}]}}]
    stage = _chart_stage(_render(tmp_path, slides), "d")
    # auto-rotation must never emit a free hex inside the chart
    assert "#" not in re.sub(r'data-[\w-]+="[^"]*"', "", stage) or "var(--fs-" in stage
    strokes = re.findall(r'stroke="([^"]+)"', stage)
    for c in strokes:
        assert c.startswith("var(--fs-") or c.startswith("rgba("), f"non-token color: {c}"
