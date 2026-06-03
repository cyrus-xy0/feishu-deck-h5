#!/usr/bin/env python3
"""sync-index-to-deck.py — port post-render edits from index.html back into
deck.json so re-render is byte-identical (modulo formatting).

The drift problem this fixes
----------------------------
deck.json is the canonical source. index.html is derived (rendered from
deck.json by render-deck.py). But sometimes an author / agent edits
index.html DIRECTLY after rendering — adding animations, tweaking layouts,
dropping a `<script>`, fine-tuning CSS in dev-tools and pasting back.
Those edits live ONLY in index.html. Re-render destroys them. Forking
the deck folder by copying just deck.json silently loses them.

What this tool does
-------------------
For each `<div class="slide" data-slide-key="K">` in index.html, extract
the inner HTML (everything AFTER the leading `<div class="wordmark">...</div>`
that every raw slide carries), find the matching slide in deck.json by
`key`, and overwrite `data.html`. If the slide currently uses a non-raw
layout (template-rendered), switch to `layout: "raw"` + `_orig_layout: <prev>`
so the data.html survives.

Safety
------
- Writes `deck.json.bak-pre-sync-<timestamp>` before mutating.
- Idempotent: re-running on an already-synced deck is a no-op.
- `--dry-run` reports diff without mutating.
- `--slide-key K` syncs just that one slide.
- Template-layout slides REQUIRE `--force` (converting cover/quote/agenda/
  etc. to raw is lossy — drops the structured fields).

Usage
-----
    python3 sync-index-to-deck.py <output>/index.html <output>/deck.json
    python3 sync-index-to-deck.py ... --slide-key content-pipeline
    python3 sync-index-to-deck.py ... --dry-run
    python3 sync-index-to-deck.py ... --force        # convert template slides too

stdlib only. Python 3.10+.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path


def _normalize_asset_paths(s: str) -> str:
    """Strip `../` prefixes from src=/href=/url() references so post-copy-assets
    local-relative paths (`input/X`) compare equal to authoring-form paths
    (`../input/X`, `../../../skills/feishu-deck-h5/assets/X`). copy-assets.py
    rewrites these as part of finalize — not real drift."""
    s = re.sub(r'(src|href)="((?:\.\./)+)([^"]+)"', r'\1="\3"', s)
    s = re.sub(r"(src|href)='((?:\.\./)+)([^']+)'", r"\1='\3'", s)
    s = re.sub(r"url\(\s*['\"]?((?:\.\./)+)([^)'\"]+)['\"]?\s*\)", r"url('\2')", s)
    # also strip skill-relative prefix (../../../skills/feishu-deck-h5/) that
    # copy-assets.py rewrites to bare 'assets/' / 'shared/' etc.
    s = re.sub(r"skills/feishu-deck-h5/", "", s)
    return s


def extract_slide_inner(html: str, slide_key: str) -> str | None:
    """Find <div class="slide" ... data-slide-key="K" ...>INNER</div> and
    return INNER minus the leading wordmark div, by depth-counting <div>/</div>.

    Returns None if the slide isn't found in html.
    """
    pat = rf'<div class="slide(?:\s[^"]*)?"[^>]*data-slide-key="{re.escape(slide_key)}"[^>]*>'
    m = re.search(pat, html)
    if not m:
        return None

    i = m.end()
    depth = 1
    j = i
    while depth > 0 and j < len(html):
        nm = re.search(r"<div\b[^>]*>|</div>", html[j:])
        if not nm:
            return None
        if nm.group(0).startswith("</"):
            depth -= 1
        else:
            depth += 1
        j += nm.end()

    inner_full = html[i : j - len("</div>")]
    # strip the leading per-slide custom_css block (render-deck.py injects it as
    # the FIRST child of .slide, marked data-fs-custom-css). It is sourced from
    # the deck.json `custom_css` field, NOT data.html, so it must NOT be folded
    # back into data.html on sync — else re-render would double it.
    cc = re.match(r'\s*<style[^>]*\bdata-fs-custom-css\b[^>]*>.*?</style>\s*',
                  inner_full, re.S)
    if cc:
        inner_full = inner_full[cc.end():]
    # strip the leading wordmark div (added by raw.fragment.html / cover.fragment.html / etc)
    wm = re.match(r'\s*<div class="wordmark"[^>]*>.*?</div>\s*', inner_full, re.S)
    if wm:
        inner_full = inner_full[wm.end():]
    # rstrip trailing template indentation/newlines before the closing slide </div>.
    # deck.json data.html strings never carry trailing whitespace, so this is safe
    # and necessary for accurate parity comparison.
    return inner_full.rstrip()


# ---------------------------------------------------------------------------
# canvas layout — by-id round-trip back into data.elements[].
#
# Mirrors render-deck.py _enrich_canvas. The render + by-id reverse-map logic
# was prototyped & validated in /tmp/struct-proto (8/8: text/geometry/add/
# delete/reorder lossless by data-el-id; only lossy case = multi-run inline
# formatting flattened on edit). Productionized here.
#
# - text from <span>s → runs (no span structure left → single run);
# - geometry cqw/cqh → px on canvas_w × canvas_h;
# - a JSON element whose id is gone from the HTML = delete;
# - an HTML data-el-id with no matching JSON element = add;
# - DOM order of data-el-id = element order (reorder).
# ---------------------------------------------------------------------------

_STYLE_RE = re.compile(r'style="([^"]*)"')
_SPAN_RE = re.compile(r'<span\b[^>]*style="([^"]*)"[^>]*>(.*?)</span>', re.S)
_COLOR_RE = re.compile(r'color:\s*([^;]+)')


def _canvas_geom_from_style(style: str, W: int, H: int) -> dict:
    """cqw/cqh in an element's inline style → px geometry (1 decimal)."""
    g = {}
    for css_key, base, json_key in (("left", W, "x"), ("top", H, "y"),
                                    ("width", W, "w"), ("height", H, "h")):
        m = re.search(rf'{css_key}:\s*([\d.]+)cq[wh]', style)
        if m:
            g[json_key] = round(float(m.group(1)) / 100 * base, 1)
    return g


def _text_from_html(html_text: str) -> str:
    """Inner HTML → plain run text. <br> → \\n FIRST (the renderer's _esc_br
    emits run-internal newlines as <br>; reverse it so paragraph/soft breaks
    survive the round-trip), then strip remaining tags and unescape entities."""
    s = re.sub(r"<br\s*/?>", "\n", html_text, flags=re.I)
    return _html_unescape(re.sub(r"<[^>]+>", "", s))


def _runs_from_inner(inner: str) -> list:
    """span inner → runs (per-run bold/color). No spans but text present →
    single flattened run (documented lossy boundary on multi-run edit)."""
    runs = []
    for style, text in _SPAN_RE.findall(inner):
        cm = _COLOR_RE.search(style)
        run = {"text": _text_from_html(text)}
        if "700" in style:
            run["bold"] = True
        if cm:
            run["color"] = cm.group(1).strip()
        runs.append(run)
    if runs:
        return runs
    flat = _text_from_html(inner).strip()
    if flat:
        return [{"text": flat}]
    return []


def _collect_canvas_els(inner: str) -> "list[tuple[str, dict]]":
    """Parse the slide's rendered .canvas inner for every [data-el-id] element.
    Returns [(id, {tag, style, inner})] in DOM order. div / svg use depth-counted
    inner; img is void. (svg = a FREEFORM/custGeom/LINE shape element.)"""
    out = []
    for tm in re.finditer(r'<(div|img|svg)\b[^>]*\bdata-el-id="([^"]+)"[^>]*>',
                          inner):
        tag, eid = tm.group(1), tm.group(2)
        open_tag = inner[tm.start():tm.end()]
        sm = _STYLE_RE.search(open_tag)
        style = sm.group(1) if sm else ""
        el_inner = ""
        if tag in ("div", "svg"):
            depth = 1
            i = tm.end()
            for mm in re.finditer(rf"<(/?){tag}\b", inner[i:]):
                depth += -1 if mm.group(1) else 1
                if depth == 0:
                    el_inner = inner[i:i + mm.start()]
                    break
        out.append((eid, {"tag": tag, "style": style, "inner": el_inner}))
    return out


def sync_canvas_data(inner: str, data: dict) -> dict:
    """Reverse-map rendered canvas inner → a new data dict (elements[] updated
    by id). Returns a fresh dict; caller decides whether it differs."""
    import copy as _copy
    W = data.get("canvas_w") or 1920
    H = data.get("canvas_h") or 1080
    new = _copy.deepcopy(data)

    found = _collect_canvas_els(inner)
    by_id = {eid: h for eid, h in found}
    order = {eid: i for i, (eid, _) in enumerate(found)}

    elements = new.get("elements") or []
    # 1) delete: JSON had it, HTML dropped it
    elements = [e for e in elements if e.get("id") in by_id]
    jmap = {e["id"]: e for e in elements}

    for eid, h in found:
        if eid not in jmap:
            # 3) add: HTML has a new data-el-id. tag → type:
            #   img → image, svg → shape (freeform/line), div → text.
            if h["tag"] == "img":
                etype = "image"
            elif h["tag"] == "svg":
                etype = "shape"
            else:
                etype = "text"
            new_el = {"id": eid, "type": etype}
            new_el.update(_canvas_geom_from_style(h["style"], W, H))
            if etype == "text":
                new_el["runs"] = _runs_from_inner(h["inner"])
            jmap[eid] = new_el
            elements.append(new_el)
            continue
        el = jmap[eid]
        # 2) geometry write-back
        el.update(_canvas_geom_from_style(h["style"], W, H))
        if el.get("type") == "text":
            runs = _runs_from_inner(h["inner"])
            if runs:
                el["runs"] = runs

    # 4) reorder by DOM order
    elements.sort(key=lambda e: order.get(e.get("id"), 1 << 30))
    new["elements"] = elements
    return new


def _html_unescape(s: str) -> str:
    import html as _h
    return _h.unescape(s)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("index_html", type=Path, help="path to rendered index.html")
    ap.add_argument("deck_json", type=Path, help="path to deck.json (will be mutated)")
    ap.add_argument("--slide-key", help="sync only this slide (key match)")
    ap.add_argument("--dry-run", action="store_true",
                    help="report drift without writing")
    ap.add_argument("--force", action="store_true",
                    help="convert template-layout slides (cover/quote/etc) to raw")
    args = ap.parse_args()

    if not args.index_html.exists():
        print(f"sync-index-to-deck: {args.index_html} not found", file=sys.stderr)
        return 2
    if not args.deck_json.exists():
        print(f"sync-index-to-deck: {args.deck_json} not found", file=sys.stderr)
        return 2

    index_html = args.index_html.read_text(encoding="utf-8")
    deck = json.loads(args.deck_json.read_text(encoding="utf-8"))

    drift_count = 0
    skipped_template = []
    skipped_missing = []
    synced = []

    for slide in deck.get("slides", []):
        key = slide.get("key")
        if not key:
            continue
        if args.slide_key and key != args.slide_key:
            continue

        inner = extract_slide_inner(index_html, key)
        if inner is None:
            skipped_missing.append(key)
            continue

        cur_layout = slide.get("layout", "")
        cur_html = slide.get("data", {}).get("html", "") if cur_layout == "raw" else None

        # Decide what action is needed
        if cur_layout == "canvas":
            # Structured by-id round-trip: reverse the rendered positioned HTML
            # back into data.elements[]. No raw-string capture and no layout
            # switch — canvas stays canvas (deck.json is the source of truth).
            cur_data = slide.get("data") or {}
            new_data = sync_canvas_data(inner, cur_data)
            if json.dumps(new_data, ensure_ascii=False, sort_keys=True) == \
               json.dumps(cur_data, ensure_ascii=False, sort_keys=True):
                continue  # no real drift
            drift_count += 1
            if not args.dry_run:
                slide["data"] = new_data
            old_n = len(cur_data.get("elements") or [])
            new_n = len(new_data.get("elements") or [])
            synced.append(("canvas", key, old_n, new_n))
            continue

        if cur_layout == "raw":
            # Compare with normalization: asset-path rewrites from copy-assets.py
            # AND leading/trailing whitespace differences (some builder scripts
            # left trailing whitespace in deck.json data.html) don't count as
            # real drift.
            if _normalize_asset_paths((cur_html or "").strip()) == _normalize_asset_paths(inner.strip()):
                continue  # no real drift, no-op
            # raw slide with drift → just update data.html
            drift_count += 1
            if not args.dry_run:
                slide["data"]["html"] = inner
            synced.append(("raw", key, len(cur_html or ""), len(inner)))
        else:
            # template slide — would need conversion to raw
            if not args.force:
                skipped_template.append((key, cur_layout))
                continue
            drift_count += 1
            if not args.dry_run:
                slide["layout"] = "raw"
                slide["_orig_layout"] = cur_layout
                # purge structured data fields; keep only html
                slide["data"] = {"html": inner}
            synced.append((f"{cur_layout}→raw", key, 0, len(inner)))

    # Reorder deck.json slides to match index.html DOM order. The visual editor's
    # drag-reorder only rewrites index.html DOM order; without syncing it back,
    # re-render restores the OLD deck.json order and the reorder is lost. Only
    # when syncing the WHOLE deck (no --slide-key) and the key SETS match (a pure
    # permutation — not an add/remove, which is other drift handled elsewhere).
    if not args.slide_key:
        dom_order = re.findall(
            r'<div class="slide(?:\s[^"]*)?"[^>]*data-slide-key="([^"]+)"', index_html)
        deck_keys = [s.get("key") for s in deck.get("slides", []) if s.get("key")]
        if dom_order and set(dom_order) == set(deck_keys) and dom_order != deck_keys:
            drift_count += 1
            synced.append(("reorder", "DOM order != deck.json order", 0, 0))
            if not args.dry_run:
                order_idx = {k: i for i, k in enumerate(dom_order)}
                deck["slides"].sort(key=lambda s: order_idx.get(s.get("key"), 1 << 30))

    # Report
    print(f"sync-index-to-deck: scanned {len(deck.get('slides', []))} slides")
    if args.slide_key:
        print(f"  filter: slide-key={args.slide_key}")
    if synced:
        print(f"  {'WOULD UPDATE' if args.dry_run else 'UPDATED'}: {len(synced)} slide(s)")
        for kind, key, old_size, new_size in synced:
            if kind == "raw":
                delta = f"{old_size}→{new_size} chars"
            elif kind == "canvas":
                delta = f"{old_size}→{new_size} elements"
            else:
                delta = f"new {new_size} chars"
            print(f"    [{kind:14s}] {key}  ({delta})")
    if skipped_template:
        print(f"  SKIPPED (template layout — use --force to convert): {len(skipped_template)}")
        for key, layout in skipped_template:
            print(f"    {key} (layout={layout})")
    if skipped_missing:
        print(f"  SKIPPED (slide-key not in index.html): {len(skipped_missing)}")
        for key in skipped_missing:
            print(f"    {key}")
    if drift_count == 0:
        print("  ✓ deck.json is in sync with index.html — no drift detected.")
        return 0

    if args.dry_run:
        print(f"\n  (--dry-run; deck.json NOT modified. {drift_count} slide(s) would be updated.)")
        return 0

    # Backup before write
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    bak = args.deck_json.with_suffix(f".json.bak-pre-sync-{ts}")
    shutil.copy2(args.deck_json, bak)
    print(f"  ✓ backup: {bak.name}")

    args.deck_json.write_text(
        json.dumps(deck, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"  ✓ wrote {args.deck_json}")
    print(f"\nNext step: re-render to verify parity:")
    print(f"  python3 {Path(__file__).parent.name}/render-deck.py \\")
    print(f"    {args.deck_json}  {args.deck_json.parent}/")

    return 0


if __name__ == "__main__":
    sys.exit(main())
