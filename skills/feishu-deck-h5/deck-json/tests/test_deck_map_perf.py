"""deck-map.py · linear-time parse regression (2026-06-14).

deck-map once pegged a CPU for minutes on a multi-MB CJK deck: `_depth_match_divs`
sliced `html[j:]` every char (O(n²)) and `_text_of`'s class regex backtracked on
the large inline `<style>` that lifted raw slides carry. This builds exactly that
shape — many frames, each with a big inline <style> before the title — and asserts
the map returns fast AND still reads every title correctly.
"""
import subprocess
import sys
import time
import pathlib
import tempfile

HERE = pathlib.Path(__file__).resolve()
DECK_MAP = HERE.parents[1] / "deck-map.py"


def _big_deck_html(n_frames=12, style_kb=120):
    # a chunky inline <style> (no title text) sitting BEFORE the title — the exact
    # thing that pushed the old class regex into pathological backtracking.
    blob = ("\n.slide .x { color:#fff; } /* 占位注释 占位注释 占位注释 */"
            * (style_kb * 1024 // 60))
    frames = []
    for i in range(1, n_frames + 1):
        frames.append(
            f'<div class="slide-frame" data-slide-key="k{i}" data-layout="raw" '
            f'data-screen-label="{i:02d} 标签">'
            f'<div class="slide" data-slide-key="k{i}">'
            f'<style>{blob}</style>'
            f'<div class="header"><h2 class="title-zh">第{i}页标题文字</h2></div>'
            f'<div class="stage"><p>正文内容 {i}</p></div>'
            f'</div></div>')
    return ('<!doctype html><html><body><div class="deck">'
            + "".join(frames) + "</div></body></html>")


def test_deck_map_is_fast_and_correct_on_big_deck():
    html = _big_deck_html()
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False,
                                     encoding="utf-8") as f:
        f.write(html)
        path = f.name
    t0 = time.time()
    # a 15s ceiling is ~70x headroom over the fixed runtime; pre-fix this hung
    # for minutes (had to be killed).
    r = subprocess.run([sys.executable, str(DECK_MAP), path, "--json"],
                       capture_output=True, text=True, timeout=15)
    dt = time.time() - t0
    assert r.returncode == 0, f"deck-map failed: {r.stderr[:300]}"
    assert dt < 5.0, f"deck-map too slow ({dt:.1f}s) — O(n^2) regression?"
    import json
    data = json.loads(r.stdout)
    rows = data["slides"]
    assert data["pages"] == 12 and len(rows) == 12, f"expected 12 frames, got {data['pages']}"
    # titles must still be extracted past the big inline <style>
    assert rows[0]["title"] == "第1页标题文字", rows[0]
    assert rows[-1]["title"] == "第12页标题文字", rows[-1]
    assert rows[5]["key"] == "k6" and rows[5]["layout"] == "raw"
