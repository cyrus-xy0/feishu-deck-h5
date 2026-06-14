"""layout:canvas — structured absolutely-positioned elements + by-id round-trip.

canvas is the PPTX → structured-JSON intermediate (DECKJSON-UNIFIED-INTERMEDIATE
-SPEC §3/§4): a slide is a list of positioned elements (text/image/shape), NOT
an HTML blob and NOT an image. It renders to positioned HTML (data-el-id +
cqw/cqh geometry) and round-trips losslessly back into data.elements[] by id.

These tests drive the REAL pipeline:
  - render-deck.py (runs schema + validate.py gate; a passing render = valid)
  - sync-index-to-deck.py's canvas reverse-map (imported as a module)

The proven logic comes from /tmp/struct-proto/proto.py (8/8: text/geometry/add/
delete/reorder lossless by data-el-id; only lossy case = multi-run inline
formatting flattened on edit). This locks that contract.
"""
import importlib.util
import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
RENDER = ROOT / "render-deck.py"
SYNC = ROOT / "sync-index-to-deck.py"


def _load_sync_module():
    spec = importlib.util.spec_from_file_location("sync_index_to_deck", SYNC)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


_sync = _load_sync_module()


def _canvas_slide():
    return {
        "key": "canvas-page",
        "layout": "canvas",
        "accent": "blue",
        "data": {
            "canvas_w": 1920,
            "canvas_h": 1080,
            "elements": [
                {"id": "t1", "type": "text", "x": 192, "y": 130, "w": 768, "h": 86,
                 "anchor": "top",
                 "runs": [{"text": "原始标题A", "bold": True, "color": "#1A1A1A"}]},
                {"id": "t2", "type": "text", "x": 192, "y": 324, "w": 1152, "h": 108,
                 "runs": [
                     {"text": "普通 ", "bold": False, "color": "#333333"},
                     {"text": "加粗词", "bold": True, "color": "#CC0000"},
                     {"text": " 收尾", "bold": False, "color": "#333333"},
                 ]},
                {"id": "img1", "type": "image", "x": 1152, "y": 130,
                 "w": 576, "h": 324, "src": "input/photo.jpg"},
            ],
        },
    }


def _render(tmp_path, slides):
    deck = {
        "version": "1.0",
        "deck": {"title": "canvas test", "author": "t", "date": "2026-06"},
        "slides": slides,
    }
    (tmp_path / "input").mkdir(exist_ok=True)
    (tmp_path / "input" / "photo.jpg").write_bytes(b"fake")
    djson = tmp_path / "deck.json"
    djson.write_text(json.dumps(deck, ensure_ascii=False), encoding="utf-8")
    r = subprocess.run([sys.executable, str(RENDER), str(djson), str(tmp_path) + "/"],
                       capture_output=True, text=True)
    assert r.returncode == 0, f"render/validate failed:\n{r.stdout}\n{r.stderr}"
    return (tmp_path / "index.html").read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# render
# --------------------------------------------------------------------------

def test_canvas_renders_positioned_elements(tmp_path):
    html = _render(tmp_path, [_canvas_slide()])
    # every element carries data-el-id, position:absolute, cqw/cqh geometry
    assert 'data-el-id="t1"' in html
    assert 'data-el-id="t2"' in html
    assert 'data-el-id="img1"' in html
    # geometry is cq, never px in the slot
    t1 = re.search(r'data-el-id="t1"[^>]*style="([^"]*)"', html).group(1)
    assert "position:absolute" in t1
    assert "left:10.0cqw" in t1 and "top:12.037cqh" in t1
    # image src kept verbatim (so copy-assets / lift can scan it)
    assert 'src="input/photo.jpg"' in html
    # multi-run text → one span per run with per-run weight/color
    t2_block = html[html.find('data-el-id="t2"'):]
    t2_block = t2_block[:t2_block.find("</div>")]
    assert "font-weight:700" in t2_block and "color:#CC0000" in t2_block


def test_canvas_shape_appearance_fields(tmp_path):
    """Shapes carry optional appearance fields (kind/fill/gradient/border/
    radius/svg/style) emitted by the PPTX parser — these must render."""
    slide = {
        "key": "shapes", "layout": "canvas", "accent": "blue",
        "data": {"canvas_w": 1920, "canvas_h": 1080, "elements": [
            {"id": "solid", "type": "shape", "x": 0, "y": 0, "w": 200, "h": 100,
             "kind": "roundRect", "fill": "#1A73E8", "radius": 12,
             "border": {"color": "#0B57D0", "width": 2}},
            {"id": "grad", "type": "shape", "x": 300, "y": 0, "w": 200, "h": 100,
             "gradient": "linear-gradient(90deg, #3C7FFF 0%, #33D6C0 100%)"},
            {"id": "rot", "type": "shape", "x": 600, "y": 0, "w": 200, "h": 100,
             "fill": "#888", "style": "transform:rotate(10deg)"},
            {"id": "free", "type": "shape", "x": 900, "y": 0, "w": 200, "h": 100,
             "svg": '<path d="M0,0 L100,0 L50,100 Z" fill="#E91E63"/>'},
        ]},
    }
    html = _render(tmp_path, [slide])
    # solid: fill + radius + border all present on one div
    solid = re.search(r'data-el-id="solid"[^>]*style="([^"]*)"', html).group(1)
    assert "background:#1A73E8" in solid
    assert "border-radius:12px" in solid
    assert "border:2px solid #0B57D0" in solid
    # gradient → background gradient (and no extra fill key conflict)
    grad = re.search(r'data-el-id="grad"[^>]*style="([^"]*)"', html).group(1)
    assert "background:linear-gradient(90deg, #3C7FFF 0%, #33D6C0 100%)" in grad
    # style escape-hatch appended
    rot = re.search(r'data-el-id="rot"[^>]*style="([^"]*)"', html).group(1)
    assert "transform:rotate(10deg)" in rot
    # svg shape → an <svg> with the path inline
    assert '<svg class="el shape" data-el-id="free"' in html
    assert '<path d="M0,0 L100,0 L50,100 Z" fill="#E91E63"/>' in html


def test_roundtrip_svg_shape_geometry(tmp_path):
    """An svg shape element survives sync (geometry write-back; appearance
    fields stay in JSON) and is not dropped as 'deleted'."""
    slide = {
        "key": "canvas-page", "layout": "canvas", "accent": "blue",
        "data": {"canvas_w": 1920, "canvas_h": 1080, "elements": [
            {"id": "free", "type": "shape", "x": 100, "y": 100, "w": 200, "h": 100,
             "svg": '<path d="M0,0 L100,100 Z" fill="#E91E63"/>'},
        ]},
    }
    html = _render(tmp_path, [slide])
    new = _sync.sync_canvas_data(_inner(html), slide["data"])
    free = next((e for e in new["elements"] if e["id"] == "free"), None)
    assert free is not None, "svg shape was dropped on sync"
    assert free["type"] == "shape"
    # appearance preserved (sync only rewrites geometry + text)
    assert "M0,0 L100,100 Z" in free["svg"]
    assert abs(free["x"] - 100) < 2 and abs(free["w"] - 200) < 2


def test_canvas_placeholder_renders_notice(tmp_path):
    slide = {"key": "ph", "layout": "canvas", "accent": "blue",
             "data": {"placeholder": True, "source_page": 7, "elements": []}}
    html = _render(tmp_path, [slide])
    assert "canvas-placeholder" in html
    assert "本页待重做 · 源第 7 页" in html


# --------------------------------------------------------------------------
# by-id round-trip (sync)
# --------------------------------------------------------------------------

def _inner(html):
    return _sync.extract_slide_inner(html, "canvas-page")


def test_roundtrip_text_edit(tmp_path):
    slide = _canvas_slide()
    html = _render(tmp_path, [slide])
    edited = html.replace("原始标题A", "编辑后B")
    new = _sync.sync_canvas_data(_inner(edited), slide["data"])
    t1 = next(e for e in new["elements"] if e["id"] == "t1")
    assert t1["runs"][0]["text"] == "编辑后B"


def test_roundtrip_geometry_edit(tmp_path):
    slide = _canvas_slide()
    html = _render(tmp_path, [slide])
    # nudge t1 left 10.0cqw → 13.021cqw (≈ 250px on 1920)
    edited = re.sub(r'(data-el-id="t1"[^>]*left:)10\.0cqw', r'\g<1>13.021cqw', html)
    new = _sync.sync_canvas_data(_inner(edited), slide["data"])
    t1 = next(e for e in new["elements"] if e["id"] == "t1")
    assert abs(t1["x"] - 250) < 2


def test_roundtrip_delete_element(tmp_path):
    slide = _canvas_slide()
    html = _render(tmp_path, [slide])
    edited = re.sub(r'\s*<img class="el" data-el-id="img1"[^>]*>', "", html)
    new = _sync.sync_canvas_data(_inner(edited), slide["data"])
    assert all(e["id"] != "img1" for e in new["elements"])


def test_roundtrip_add_element(tmp_path):
    slide = _canvas_slide()
    html = _render(tmp_path, [slide])
    new_div = ('<div class="el tb" data-el-id="tNEW" '
               'style="position:absolute;left:5.208cqw;top:50.0cqh;width:20.0cqw;height:5.0cqh">'
               '<span style="font-weight:400;color:#000">新增框</span></div>')
    m = re.search(r'(data-el-id="t2".*?</div>)', html, re.S)
    edited = html[:m.end()] + "\n" + new_div + html[m.end():]
    new = _sync.sync_canvas_data(_inner(edited), slide["data"])
    tnew = next((e for e in new["elements"] if e["id"] == "tNEW"), None)
    assert tnew is not None
    assert abs(tnew["x"] - 100) < 2
    assert tnew["runs"][0]["text"] == "新增框"


def test_roundtrip_reorder(tmp_path):
    slide = _canvas_slide()
    html = _render(tmp_path, [slide])
    inner = _inner(html)
    # move img1 to the front of the canvas inner
    m = re.search(r'<img class="el" data-el-id="img1"[^>]*>', inner)
    img = m.group(0)
    moved = img + "\n" + inner[:m.start()] + inner[m.end():]
    new = _sync.sync_canvas_data(moved, slide["data"])
    assert new["elements"][0]["id"] == "img1"


def test_roundtrip_multirun_preserved_on_geometry_only_edit(tmp_path):
    """Editing only geometry (not text) keeps the 3-run structure intact."""
    slide = _canvas_slide()
    html = _render(tmp_path, [slide])
    edited = re.sub(r'(data-el-id="t1"[^>]*left:)10\.0cqw', r'\g<1>11.0cqw', html)
    new = _sync.sync_canvas_data(_inner(edited), slide["data"])
    t2 = next(e for e in new["elements"] if e["id"] == "t2")
    assert len(t2["runs"]) == 3
    assert t2["runs"][1]["bold"] is True
    assert t2["runs"][1]["text"] == "加粗词"


def test_roundtrip_multirun_flatten_is_lossy(tmp_path):
    """Documented lossy boundary: wiping a multi-run box's span structure
    (contenteditable flatten) degrades it to a single run."""
    slide = _canvas_slide()
    html = _render(tmp_path, [slide])
    edited = re.sub(r'(<div class="el tb" data-el-id="t2"[^>]*>).*?(</div>)',
                    r'\1普通加粗词收尾(已抹平)\2', html, flags=re.S)
    new = _sync.sync_canvas_data(_inner(edited), slide["data"])
    t2 = next(e for e in new["elements"] if e["id"] == "t2")
    assert len(t2["runs"]) == 1
    assert "抹平" in t2["runs"][0]["text"]


def test_roundtrip_stable_second_sync(tmp_path):
    """render(sync(render)) is a fixed point: a second sync detects no drift."""
    slide = _canvas_slide()
    html1 = _render(tmp_path, [slide])
    data1 = _sync.sync_canvas_data(_inner(html1), slide["data"])
    # re-render from the synced data, sync again → must equal data1
    slide2 = dict(slide, data=data1)
    html2 = _render(tmp_path, [slide2])
    data2 = _sync.sync_canvas_data(_inner(html2), data1)
    assert json.dumps(data1, sort_keys=True, ensure_ascii=False) == \
           json.dumps(data2, sort_keys=True, ensure_ascii=False)


def _typo_slide():
    """A canvas slide whose runs carry the FULL typography set render-deck emits:
    size (font-size), font (font-family), grad (background-image), plus bold/color.
    Used to lock sync-1 (reverse-map must not strip per-run typography) and sync-2
    (integer geometry stays integer → no phantom drift)."""
    return {
        "key": "canvas-page", "layout": "canvas", "accent": "blue",
        "data": {"canvas_w": 1920, "canvas_h": 1080, "elements": [
            {"id": "t1", "type": "text", "x": 192, "y": 130, "w": 768, "h": 86,
             "anchor": "top",
             "runs": [{"text": "原始标题A", "bold": True, "color": "#1A1A1A",
                       "size": 48, "font": '"Arial"',
                       "grad": "linear-gradient(90deg, #3C7FFF 0%, #33D6C0 100%)"}]},
            {"id": "img1", "type": "image", "x": 1152, "y": 130,
             "w": 576, "h": 324, "src": "input/photo.jpg"},
        ]},
    }


def test_roundtrip_text_edit_preserves_typography(tmp_path):
    """sync-1: a text-only edit must NOT strip per-run size/font/grad (they are
    emitted to the DOM and must be recovered, not silently dropped)."""
    slide = _typo_slide()
    html = _render(tmp_path, [slide])
    edited = html.replace("原始标题A", "编辑后B")
    new = _sync.sync_canvas_data(_inner(edited), slide["data"])
    t1 = next(e for e in new["elements"] if e["id"] == "t1")
    r = t1["runs"][0]
    assert r["text"] == "编辑后B"
    assert r.get("size") == 48, "per-run font-size stripped on text edit"
    assert r.get("font") == '"Arial"', f"per-run font-family lost: {r.get('font')!r}"
    assert "linear-gradient" in (r.get("grad") or ""), "per-run grad stripped"
    assert r.get("bold") is True and r.get("color") == "#1A1A1A"


def test_roundtrip_stable_second_sync_with_typography(tmp_path):
    """sync-1 + sync-2: render(sync(render)) is a fixed point even when runs carry
    size/font/grad AND geometry is integer (would phantom-drift if floatified)."""
    slide = _typo_slide()
    html1 = _render(tmp_path, [slide])
    data1 = _sync.sync_canvas_data(_inner(html1), slide["data"])
    # geometry must stay integer (sync-2: 192 not 192.0)
    img = next(e for e in data1["elements"] if e["id"] == "img1")
    assert all(isinstance(img[k], int) for k in ("x", "y", "w", "h")), \
        f"geometry floatified: {[img[k] for k in ('x','y','w','h')]}"
    slide2 = dict(slide, data=data1)
    html2 = _render(tmp_path, [slide2])
    data2 = _sync.sync_canvas_data(_inner(html2), data1)
    assert json.dumps(data1, sort_keys=True, ensure_ascii=False) == \
           json.dumps(data2, sort_keys=True, ensure_ascii=False)


def test_roundtrip_add_image_keeps_src(tmp_path):
    """sync-4: a newly-added canvas <img> must keep its src (else broken box)."""
    slide = _canvas_slide()
    html = _render(tmp_path, [slide])
    inner = _inner(html)
    new_img = ('<img class="el" data-el-id="addedimg" loading="lazy" '
               'src="input/new.png" style="position:absolute;left:5.0cqw;'
               'top:50.0cqh;width:10.0cqw;height:10.0cqh">')
    m = re.search(r'<img class="el" data-el-id="img1"[^>]*>', inner)
    edited = inner[:m.end()] + "\n" + new_img + inner[m.end():]
    new = _sync.sync_canvas_data(edited, slide["data"])
    added = next((e for e in new["elements"] if e["id"] == "addedimg"), None)
    assert added is not None and added["type"] == "image"
    assert added.get("src") == "input/new.png", "added image dropped its src"


def test_roundtrip_add_shape_keeps_svg(tmp_path):
    """sync-4: a newly-added canvas <svg> shape must keep its path/inner svg."""
    slide = _canvas_slide()
    html = _render(tmp_path, [slide])
    inner = _inner(html)
    new_svg = ('<svg class="el shape" data-el-id="addedsvg" '
               'style="position:absolute;left:5.0cqw;top:50.0cqh;width:10.0cqw;'
               'height:10.0cqh;overflow:visible" viewBox="0 0 100 100" '
               'preserveAspectRatio="none">'
               '<path d="M0,0 L100,100 Z" fill="#E91E63"/></svg>')
    m = re.search(r'<img class="el" data-el-id="img1"[^>]*>', inner)
    edited = inner[:m.end()] + "\n" + new_svg + inner[m.end():]
    new = _sync.sync_canvas_data(edited, slide["data"])
    added = next((e for e in new["elements"] if e["id"] == "addedsvg"), None)
    assert added is not None and added["type"] == "shape"
    assert "M0,0 L100,100 Z" in (added.get("svg") or ""), "added shape dropped svg"
