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
  etc. to raw is lossy — drops the structured fields). Without `--force` a
  template slide with browser edits now emits a loud WARNING (was a silent skip).
- DIRECTION GUARD: a full sync assumes index.html is the NEWER side (the post-
  render-edited one). If deck.json's mtime is NEWER than index.html's (you most
  likely edited deck.json and have not re-rendered), the tool refuses to write —
  it prints a hard warning and falls back to --dry-run. Pass `--index-is-newer`
  (alias `--force-direction`) to override and reverse-feed anyway. The normal
  render→sync flow (index.html always newer than deck.json) is UNAFFECTED.

What a default full sync now covers (no per-flag opt-in)
-------------------------------------------------------
- raw `data.html` inner-HTML drift  (always covered)
- canvas `data.elements[]` by-id round-trip  (always covered)
- slide ORDER (drag-reorder)  (already covered)
- `custom_css` block drift  (NEW — was silently dropped, reported "no drift")
- `hidden` flag + speaker `notes`  (NEW in the default path — previously only
  reachable via --hidden-only / --notes-only; both are lossless idempotent
  surgical reconciles, so there is no reason they needed a separate flag)

Usage
-----
    python3 sync-index-to-deck.py <output>/index.html <output>/deck.json
    python3 sync-index-to-deck.py ... --slide-key content-pipeline
    python3 sync-index-to-deck.py ... --dry-run
    python3 sync-index-to-deck.py ... --force        # convert template slides too
    python3 sync-index-to-deck.py ... --index-is-newer   # override direction guard

stdlib only (scope_selectors is loaded lazily from the sibling _css_utils.py).
Python 3.10+.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

_SCOPE_SELECTORS = None


def _scope_selectors(css: str, slide_key: str) -> str:
    """Scope author CSS to one slide-key, via the canonical _css_utils primitive
    (the SAME one render-deck.py uses to emit the <style data-fs-custom-css>
    block). Loaded lazily so the module stays import-light. scope_selectors is
    idempotent on already-scoped selectors, so feeding it the deck.json
    `custom_css` field (scoped OR unscoped) yields exactly the rendered block
    body — that equality is what custom_css drift detection relies on."""
    global _SCOPE_SELECTORS
    if _SCOPE_SELECTORS is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_css_utils", Path(__file__).resolve().parent / "_css_utils.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _SCOPE_SELECTORS = mod.scope_selectors
    return _SCOPE_SELECTORS(css, slide_key)


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


# ---------------------------------------------------------------------------
# R-BAKED-DOM guard + runtime-trace sanitizer (F-259).
#
# sync's reverse-feed assumes index.html is a render-deck.py output that an
# author then edited. But the in-browser edit-mode ⌘S (or a plain browser
# "save page") can serialize the LIVE post-JS DOM, which carries runtime traces
# feishu-deck.js writes at present-mode init: per-frame data-idx, the buildUI()
# .deck-ui overlay, .deck runtime flags, per-slide data-fs-* balance markers,
# the reveal --child-i custom prop, and inline geometry the balanceSlide /
# canvas-center passes compute (top/bottom/min-height/align-self/etc.). None of
# those are AUTHOR edits. Folding them back into deck.json makes the source drift
# every round-trip ("越改越坏"), and the runtime geometry would re-bake on the
# next render → compounding.
#
# Two boundaries, mirroring the edit-mode save sanitizer (deck-edit-mode.js):
#   1. DETECT the R-BAKED-DOM fingerprints (same logic as run-audits.py
#      audit_baked_runtime_dom_bytes) and REFUSE by default — the operator
#      should save through the sanitizing editor or pass --sanitize.
#   2. --sanitize: strip --child-i + runtime inline-style props from a COPY of
#      the HTML BEFORE drift comparison, so runtime mutations never count as
#      edits and never get written into deck.json.
# We do NOT touch the runtime (feishu-deck.js); we only sanitize at this border.
# ---------------------------------------------------------------------------

# Always-strip declarations: the UNAMBIGUOUS runtime CSS custom props --child-i
# (reveal stagger) and --fs-scale (scaleFrame) — an author never writes these.
# A declaration runs `prop: value` up to the next ; or the end of the attr. The
# property name is anchored to a declaration boundary (start of body or a `;`),
# kept in group(1) and re-emitted so neighbouring author declarations stay intact.
#
# DELIBERATELY NOT stripped: the balanceSlide geometry written WITHOUT !important
# (align-self / justify-content / min-height / padding-top / padding-bottom). It
# is TEXT-IDENTICAL to ordinary author inline styles, so stripping it would DELETE
# authored layout (a worse corruption than the one this fixes) — and unlike the
# canvas-center !important top/bottom it does NOT compound across round-trips
# (balanceSlide reverts non-improvements; a kept value is stable on re-render).
# See deck-edit-mode.js for the full rationale (the two sanitizers are paired).
_RUNTIME_DECL_RE = re.compile(
    r"(^|;)\s*(?:--child-i|--fs-scale)\s*:\s*[^;\"]*",
    re.I,
)
# top/bottom are stripped ONLY when they carry !important — the _ccApply
# canvas-center signature (the R-11 landmine that compounds). Plain author
# top/bottom (common on absolute boxes, e.g. `position:absolute;top:0`) carry no
# !important, so they survive. The boundary group(1) is preserved like above.
_RUNTIME_CC_DECL_RE = re.compile(
    r"(^|;)\s*(?:top|bottom)\s*:\s*[^;\"]*!important\s*[^;\"]*",
    re.I,
)


def _baked_dom_fingerprints(html: str) -> "list[str]":
    """Return the R-BAKED-DOM fingerprint hits in `html` (empty = clean).

    照抄 run-audits.py audit_baked_runtime_dom_bytes 的指纹检测(同一组 needle),
    so sync's reject reason matches exactly what the validator/gate reports.
    Signals (any present = a saved/"baked" live DOM, not a render output):
      · data-idx="…"                         (runtime .slide-frame index)
      · class="deck-ui"                       (buildUI() overlay)
      · .deck open tag with data-js-ready / data-nav-armed / data-edit-paste-guard
    """
    hits = []
    if re.search(r'<[^>]*\bdata-idx="', html):
        hits.append("data-idx=（运行时 .slide-frame 序号）")
    if re.search(r'class="[^"]*\bdeck-ui\b', html):
        hits.append('class="deck-ui"（运行时 buildUI 覆盖层）')
    deck_open = re.search(r'<div[^>]*\bclass="[^"]*\bdeck\b[^"]*"[^>]*>', html)
    if deck_open and re.search(r'data-(js-ready|nav-armed|edit-paste-guard)',
                               deck_open.group(0)):
        hits.append(".deck 带运行时标志(data-js-ready/nav-armed/edit-paste-guard)")
    return hits


def _sanitize_style_attr(style_body: str) -> str:
    """Drop runtime-injected declarations from one inline style body, preserving
    author declarations, their order, AND the author's trailing-';' state.
    Removes --child-i / --fs-scale always, and top/bottom only when !important
    (the canvas-center signature). Returns the cleaned body (may be empty).

    Each regex keeps the leading boundary (group 1: '' or ';') so author
    declarations on either side are untouched; the leftover double-';' is
    collapsed. We restore the original trailing ';' (render-deck.py's emitted
    inline styles end with ';', so dropping it would falsely register as drift)."""
    had_trailing_semi = style_body.rstrip().endswith(";")
    cleaned = _RUNTIME_DECL_RE.sub(r"\1", style_body)
    cleaned = _RUNTIME_CC_DECL_RE.sub(r"\1", cleaned)
    cleaned = re.sub(r";\s*;+", ";", cleaned)            # collapse `;;` runs
    cleaned = cleaned.strip().strip(";").strip()
    if cleaned and had_trailing_semi:
        cleaned += ";"
    return cleaned


def sanitize_runtime_traces(html: str) -> str:
    """Strip runtime traces from a (possibly baked) index.html so drift compare
    sees the pure AUTHOR state. Mirrors deck-edit-mode.js stripRuntimeArtifacts
    at the text level — but conservative: it only removes attributes/props the
    runtime is KNOWN to write, never author content.

    Removes: per-slide data-fs-* markers, per-frame data-idx, .deck runtime
    flags, and runtime inline-style declarations (--child-i + geometry) from any
    style="..." attribute. Leaves the .deck-ui overlay and structural DOM alone
    (the detect step already flags those; this is purely for the drift compare,
    and extract_slide_inner reads inside .slide where .deck-ui never lives)."""
    # 1) strip runtime marker attributes (with or without a value)
    out = re.sub(r'\s+data-fs-(?:balanced|colbalanced|canvascentered|autobalanced)(?:="[^"]*")?',
                 "", html)
    out = re.sub(r'\s+data-idx="[^"]*"', "", out)
    out = re.sub(r'\s+data-(?:js-ready|nav-armed|edit-paste-guard)(?:="[^"]*")?',
                 "", out)

    # 2) strip runtime inline-style declarations from every style="..."
    def _repl_style(m: re.Match) -> str:
        body = _sanitize_style_attr(m.group(1))
        return f'style="{body}"' if body else ""
    out = re.sub(r'style="([^"]*)"', _repl_style, out)
    return out


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


# ---------------------------------------------------------------------------
# backfill — create a deck.json FROM SCRATCH out of an index.html that has none.
#
# A LEGACY deck that is HTML-only (no deck.json) gets its `中间层` (deck.json
# intermediate) backfilled by reverse-engineering the REAL rendered DOM — the
# source code, which is more precise than any screenshot (DECKJSON-UNIFIED-
# INTERMEDIATE-SPEC §5). NO images.
#
#   - Self-rendered feishu decks (every slide carries data-slide-key): EXACT.
#     Each `.slide[data-slide-key="K"]` → one `raw` slide; inner = the same
#     thing extract_slide_inner() returns on sync (wordmark + custom_css block
#     stripped), so sync-index-to-deck on the same index.html is then a no-op.
#   - FOREIGN HTML (no data-slide-key): best-effort. Each top-level `.slide`,
#     else each direct <section>/page-container child, becomes one raw slide
#     with a generated key. If unrecognizable → a single raw slide of <body>
#     plus a warning. Never crashes.
#
# Backfilled slides are marked `lifted="backfill:<htmlstem>#<N>"` (imported
# provenance) so the validator downgrades content-authoring rules for this
# faithfully-carried content (data-lifted → _deck_all_imported / audit_copy_rules,
# commit 1fb1f6e).
# ---------------------------------------------------------------------------

_SLIDE_OPEN_RE = re.compile(
    r'<div class="slide(?:\s[^"]*)?"[^>]*\bdata-slide-key="([^"]+)"[^>]*>')


def _slide_keys_in_dom_order(html: str) -> list:
    """Every `.slide` data-slide-key in DOM order (self-rendered feishu deck)."""
    return _SLIDE_OPEN_RE.findall(html)


def _screen_label_for(html: str, slide_key: str) -> str | None:
    """The data-screen-label attr on the slide open tag, if any."""
    pat = (rf'<div class="slide(?:\s[^"]*)?"[^>]*'
           rf'data-screen-label="([^"]*)"[^>]*data-slide-key="{re.escape(slide_key)}"'
           rf'|<div class="slide(?:\s[^"]*)?"[^>]*data-slide-key="{re.escape(slide_key)}"'
           rf'[^>]*data-screen-label="([^"]*)"')
    m = re.search(pat, html)
    if not m:
        return None
    return m.group(1) if m.group(1) is not None else m.group(2)


def _extract_slide_custom_css(html: str, slide_key: str) -> str:
    """Return the SCOPED CSS body of this slide's leading
    `<style ... data-fs-custom-css>...</style>` block (render-deck injects it as
    the first child of `.slide`, sourced from the deck.json `custom_css` field).

    The body is ALREADY scoped to `.slide[data-slide-key="K"]`; scope_selectors
    is idempotent on already-scoped selectors, so storing it verbatim back into
    `custom_css` round-trips (re-render re-scopes → no change). Empty if none.
    """
    pat = rf'<div class="slide(?:\s[^"]*)?"[^>]*data-slide-key="{re.escape(slide_key)}"[^>]*>'
    m = re.search(pat, html)
    if not m:
        return ""
    cc = re.match(
        r'\s*<style[^>]*\bdata-fs-custom-css\b[^>]*>(.*?)</style>',
        html[m.end():], re.S)
    if not cc:
        return ""
    return cc.group(1).strip()


def _make_key(seed: str, used: set, fallback_idx: int) -> str:
    """Slugify `seed` into a schema-legal slide key (^[a-z][a-z0-9-]*$), unique
    within `used`. Falls back to slide-<N> when nothing usable remains."""
    s = re.sub(r"[^a-z0-9]+", "-", (seed or "").lower()).strip("-")
    s = re.sub(r"-{2,}", "-", s)
    if not s or not s[0].isalpha():
        s = f"slide-{fallback_idx}"
    base = s
    n = 2
    while s in used:
        s = f"{base}-{n}"
        n += 1
    used.add(s)
    return s


def _strip_leading_wordmark(inner: str) -> str:
    """Drop a leading `<div class="wordmark">…</div>` (raw/cover fragments carry
    it; foreign HTML usually won't). Mirrors extract_slide_inner."""
    wm = re.match(r'\s*<div class="wordmark"[^>]*>.*?</div>\s*', inner, re.S)
    return inner[wm.end():] if wm else inner


def _depth_extract_inner(html: str, open_match: re.Match, tag: str) -> str:
    """Given a regex match on an opening `<tag ...>`, return its inner HTML by
    depth-counting `<tag>`/`</tag>` (handles nesting)."""
    i = open_match.end()
    depth = 1
    j = i
    while depth > 0 and j < len(html):
        nm = re.search(rf"<{tag}\b[^>]*>|</{tag}>", html[j:])
        if not nm:
            return html[i:]
        depth += -1 if nm.group(0).startswith("</") else 1
        j += nm.end()
    return html[i: j - len(f"</{tag}>")]


def _foreign_top_level_slides(html: str) -> list:
    """Best-effort split of FOREIGN HTML (no data-slide-key) into raw slides.

    Strategy, in order:
      1. Top-level `<div class="slide ...">` (a foreign deck that uses the
         `.slide` class but no data-slide-key) → each one a slide.
      2. Else each `<section>` directly under <body> → each one a slide.
      3. Else a single raw slide of the whole <body> inner (last resort).

    Returns [(seed_label, inner_html)]. Order preserved. seed_label feeds key
    generation (id/data-name/heading text → slug, else positional).
    """
    body = _body_inner(html)

    def _seed(open_tag: str, inner: str) -> str:
        mid = re.search(r'\bid="([^"]+)"', open_tag)
        if mid:
            return mid.group(1)
        mname = re.search(r'\bdata-(?:name|slide|page)="([^"]+)"', open_tag)
        if mname:
            return mname.group(1)
        mh = re.search(r"<h[1-3][^>]*>(.*?)</h[1-3]>", inner, re.S | re.I)
        if mh:
            return _text_from_html(mh.group(1))[:40]
        return ""

    # 1) foreign `.slide` divs (no data-slide-key, else the native path runs)
    out = []
    for om in re.finditer(r'<div class="slide(?:\s[^"]*)?"[^>]*>', body):
        inner = _depth_extract_inner(body, om, "div")
        out.append((_seed(om.group(0), inner), inner.strip()))
    if out:
        return out

    # 2) <section> children
    for om in re.finditer(r"<section\b[^>]*>", body):
        inner = _depth_extract_inner(body, om, "section")
        out.append((_seed(om.group(0), inner), inner.strip()))
    if out:
        return out

    # 3) last resort: the whole body as one slide
    return [("", body.strip())]


def _body_inner(html: str) -> str:
    m = re.search(r"<body\b[^>]*>(.*)</body>", html, re.S | re.I)
    return m.group(1) if m else html


def backfill_deck(index_html: str, html_stem: str) -> "tuple[dict, list]":
    """Reverse-engineer a deck.json FROM SCRATCH out of an index.html.

    Returns (deck_dict, warnings). Each slide is layout:raw, marked
    lifted="backfill:<html_stem>#<N>". Self-rendered decks (data-slide-key) are
    exact; foreign HTML is best-effort.
    """
    warnings = []
    title = "Backfilled deck"
    tm = re.search(r"<title[^>]*>(.*?)</title>", index_html, re.S | re.I)
    if tm:
        t = _text_from_html(tm.group(1)).strip()
        if t:
            title = t

    slides = []
    native_keys = _slide_keys_in_dom_order(index_html)

    if native_keys:
        # EXACT path — self-rendered feishu deck. Reuse extract_slide_inner so
        # this is byte-identical to what a subsequent sync would compare against.
        used = set()
        for n, key in enumerate(native_keys, 1):
            inner = extract_slide_inner(index_html, key)
            if inner is None:
                warnings.append(f"slide-key {key!r} matched in scan but inner "
                                f"could not be extracted — skipped")
                continue
            # de-dupe collided keys (a malformed deck could repeat one); the
            # schema needs unique keys for a clean sync round-trip.
            ukey = key
            if ukey in used:
                ukey = _make_key(key, used, n)
                warnings.append(f"duplicate data-slide-key {key!r} → renamed "
                                f"{ukey!r} for uniqueness")
            else:
                used.add(ukey)
            slide = {
                "key": ukey,
                "layout": "raw",
                "lifted": f"backfill:{html_stem}#{n}",
                "data": {"html": inner},
            }
            label = _screen_label_for(index_html, key)
            if label:
                slide["screen_label"] = label
            cc = _extract_slide_custom_css(index_html, key)
            if cc:
                slide["custom_css"] = cc
            slides.append(slide)
    else:
        # FOREIGN path — best-effort.
        warnings.append("no data-slide-key found — FOREIGN HTML best-effort "
                        "split (each slide = layout:raw, geometry/structure "
                        "carried verbatim; review keys + per-slide split)")
        parts = _foreign_top_level_slides(index_html)
        if len(parts) == 1 and not parts[0][0]:
            warnings.append("structure unrecognizable — emitted ONE raw slide "
                            "of <body>; split it by hand if it should be many")
        used = set()
        for n, (seed, inner) in enumerate(parts, 1):
            inner = _strip_leading_wordmark(inner).rstrip()
            if not inner.strip():
                continue
            key = _make_key(seed, used, n)
            slides.append({
                "key": key,
                "layout": "raw",
                "lifted": f"backfill:{html_stem}#{n}",
                "data": {"html": inner},
            })

    if not slides:
        warnings.append("no slides could be reconstructed from index.html")

    deck = {
        "version": "1.0",
        "deck": {"title": title},
        "slides": slides,
    }
    return deck, warnings


def run_backfill(index_html_path: Path, deck_json_path: Path,
                 dry_run: bool = False, sanitize: bool = False) -> int:
    """CLI handler: backfill a deck.json from an index.html that has none."""
    index_html = index_html_path.read_text(encoding="utf-8")
    if sanitize:
        # A baked index.html backfilled verbatim would capture runtime geometry
        # (balance/canvas-center inline styles + --child-i) into the new raw
        # slides. Strip those first so the reconstructed deck.json is the author
        # state. (F-259 — mirrors the full-sync --sanitize path.)
        index_html = sanitize_runtime_traces(index_html)
    deck, warnings = backfill_deck(index_html, deck_json_path.stem
                                   if deck_json_path.stem != "deck"
                                   else index_html_path.stem)

    n = len(deck["slides"])
    print(f"sync-index-to-deck --backfill: reconstructed {n} slide(s) "
          f"from {index_html_path.name}")
    native = bool(_slide_keys_in_dom_order(index_html))
    print(f"  source: {'self-rendered (data-slide-key, EXACT)' if native else 'FOREIGN HTML (best-effort)'}")
    for s in deck["slides"]:
        cc = " +custom_css" if s.get("custom_css") else ""
        print(f"    [raw] {s['key']}  ({len(s['data']['html'])} chars{cc})  "
              f"lifted={s['lifted']}")
    for w in warnings:
        print(f"  ! {w}")

    if n == 0:
        print("  ✗ nothing reconstructed — refusing to write empty deck.json",
              file=sys.stderr)
        return 1

    if dry_run:
        print(f"\n  (--dry-run; {deck_json_path} NOT written.)")
        return 0

    if deck_json_path.exists():
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        bak = deck_json_path.with_suffix(f".json.bak-pre-backfill-{ts}")
        shutil.copy2(deck_json_path, bak)
        print(f"  ✓ backup: {bak.name}")

    deck_json_path.write_text(
        json.dumps(deck, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  ✓ wrote {deck_json_path}")
    print(f"\nNext step: re-render to verify parity:")
    print(f"  python3 {Path(__file__).parent.name}/render-deck.py \\")
    print(f"    {deck_json_path}  {deck_json_path.parent}/")
    return 0


def _slide_open_tag(html: str, key: str) -> str | None:
    """The full `<div class="slide..." ... data-slide-key="K" ...>` opening tag
    (so we can inspect data-* on it). data-hidden may sit before OR after
    data-slide-key — the `[^>]*` on both sides captures either."""
    pat = (rf'<div class="slide(?:\s[^"]*)?"[^>]*'
           rf'data-slide-key="{re.escape(key)}"[^>]*>')
    m = re.search(pat, html)
    return m.group(0) if m else None


# ---------------------------------------------------------------------------
# Lossless surgical reconciles (notes / hidden / order). Each mutates `deck` in
# place (unless dry_run) and returns (changed, report_lines). They are pure
# structural reconciles — no raw conversion, no inner-HTML diff — so they are
# SHARED by both the per-flag surgical path (run_surgical_sync) and the default
# full sync (F-273: hidden+notes used to be reachable ONLY via their own flags;
# nothing about them justified that, so the full path now runs them too).
# ---------------------------------------------------------------------------

def _reconcile_notes(deck: dict, html: str, dry_run: bool) -> "tuple[bool, list[str]]":
    """Speaker notes (口播稿) from the #fs-deck-notes island → slide.notes."""
    lines = []
    m = re.search(r'<script type="application/json" id="fs-deck-notes">(.*?)</script>',
                  html, re.S)
    html_notes = {}
    if m:
        try:
            html_notes = json.loads(m.group(1).replace('<\\/', '</'))
        except Exception:
            html_notes = {}
    n_changes = []
    for slide in deck.get("slides", []):
        key = slide.get("key")
        if not key:
            continue
        new = html_notes.get(key) or None
        cur = slide.get("notes") or None
        if new == cur:
            continue
        n_changes.append((key, cur, new))
        if not dry_run:
            if new:
                slide["notes"] = new
            else:
                slide.pop("notes", None)
    lines.append(f"[notes] island has {len(html_notes)} note(s)")
    for key, cur, new in n_changes:
        lines.append(f"  {key}: notes {'set' if new else 'cleared'}")
    if not n_changes:
        lines.append("  ✓ no notes drift.")
    return bool(n_changes), lines


def _reconcile_hidden(deck: dict, html: str, dry_run: bool) -> "tuple[bool, list[str]]":
    """Per-slide `hidden` (隐藏页) from data-hidden on the slide open tag."""
    lines = []
    h_changes, missing = [], []
    for slide in deck.get("slides", []):
        key = slide.get("key")
        if not key:
            continue
        tag = _slide_open_tag(html, key)
        if tag is None:
            missing.append(key)
            continue
        html_hidden = bool(re.search(r'\bdata-hidden\b', tag))
        if html_hidden == bool(slide.get("hidden")):
            continue
        h_changes.append((key, bool(slide.get("hidden")), html_hidden))
        if not dry_run:
            if html_hidden:
                slide["hidden"] = True
            else:
                slide.pop("hidden", None)   # clean-remove, no hidden:false residue
    lines.append(f"[hidden] scanned {len(deck.get('slides', []))} slides")
    for key, old, new in h_changes:
        lines.append(f"  {key}: hidden {old} → {new}")
    if missing:
        lines.append(f"  ⚠ {len(missing)} slide(s) not found in HTML (skipped): "
                     f"{', '.join(missing[:8])}")
    if not h_changes:
        lines.append("  ✓ no hidden-flag drift.")
    return bool(h_changes), lines


def _reconcile_order(deck: dict, html: str, dry_run: bool) -> "tuple[bool, list[str]]":
    """Slide ORDER (edit-mode drag-reorder) from DOM order. Only a pure
    permutation is applied — a differing key SET (add/remove) is left alone."""
    lines = []
    dom_order = re.findall(
        r'<div class="slide(?:\s[^"]*)?"[^>]*data-slide-key="([^"]+)"', html)
    deck_keys = [s.get("key") for s in deck.get("slides", []) if s.get("key")]
    lines.append(f"[order] HTML has {len(dom_order)} slides, deck.json has {len(deck_keys)}")
    changed = False
    if not dom_order:
        lines.append("  ⚠ no data-slide-key in HTML — can't sync order (skipped).")
    elif set(dom_order) != set(deck_keys):
        only_html = set(dom_order) - set(deck_keys)
        only_deck = set(deck_keys) - set(dom_order)
        lines.append(f"  ⚠ key sets differ (added/removed slides) — order NOT synced. "
                     f"only-in-HTML: {sorted(only_html)[:5]}  only-in-deck: {sorted(only_deck)[:5]}")
    elif dom_order == deck_keys:
        lines.append("  ✓ order already matches.")
    else:
        lines.append(f"  reorder: {deck_keys}  →  {dom_order}")
        if not dry_run:
            order_idx = {k: i for i, k in enumerate(dom_order)}
            deck["slides"].sort(key=lambda s: order_idx.get(s.get("key"), 1 << 30))
        changed = True
    return changed, lines


def run_surgical_sync(index_html_path: Path, deck_json_path: Path,
                      do_hidden: bool, do_order: bool, do_notes: bool, dry_run: bool) -> int:
    """Surgical: reconcile ONLY structural fields from the rendered index.html back
    into deck.json — `hidden` (隐藏页, per-slide data-hidden), slide ORDER (the
    edit-mode drag-reorder), and/or speaker `notes` (口播稿, edited in the presenter
    view, stored in the #fs-deck-notes island). Touches nothing else (no raw
    conversion, no inner-HTML diff). This is what the in-browser editor changes;
    run this to push those changes to the deck.json source. Any combination works."""
    html = index_html_path.read_text(encoding="utf-8")
    deck = json.loads(deck_json_path.read_text(encoding="utf-8"))
    changed = False

    if do_notes:
        ch, lines = _reconcile_notes(deck, html, dry_run)
        print("\n".join(lines))
        changed = changed or ch
    if do_hidden:
        ch, lines = _reconcile_hidden(deck, html, dry_run)
        print("\n".join(lines))
        changed = changed or ch
    if do_order:
        ch, lines = _reconcile_order(deck, html, dry_run)
        print("\n".join(lines))
        changed = changed or ch

    if dry_run:
        print(f"\n  (--dry-run; {deck_json_path} NOT written.)")
        return 0
    if not changed:
        print("  ✓ deck.json already in sync — nothing written.")
        return 0

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    bak = deck_json_path.with_suffix(f".json.bak-pre-sync-{ts}")
    shutil.copy2(deck_json_path, bak)
    print(f"  ✓ backup: {bak.name}")
    deck_json_path.write_text(
        json.dumps(deck, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  ✓ wrote {deck_json_path.name}")
    print(f"\nNext step: re-render to apply:")
    print(f"  python3 {Path(__file__).parent.name}/render-deck.py "
          f"{deck_json_path}  {deck_json_path.parent}/")
    return 0


# Direction guard tolerance: deck.json must be MORE than this many seconds newer
# than index.html to be considered "the wrong direction". A render writes both
# files back-to-back, so index.html is normally a hair newer; the slack absorbs
# clock jitter / FS mtime granularity so the normal render→sync flow never trips.
_DIRECTION_TOLERANCE_S = 2.0


def _wrong_direction(deck_json: Path, index_html: Path) -> "float | None":
    """Return how many seconds deck.json is NEWER than index.html if that gap
    exceeds the tolerance (→ a full sync would likely clobber un-rendered
    deck.json edits with stale HTML). Returns None when the direction is fine
    (index.html newer, equal, or within tolerance) or mtimes are unreadable —
    fail-open so the guard never blocks the normal flow on an FS quirk."""
    try:
        delta = deck_json.stat().st_mtime - index_html.stat().st_mtime
    except OSError:
        return None
    return delta if delta > _DIRECTION_TOLERANCE_S else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("index_html", type=Path, help="path to rendered index.html")
    ap.add_argument("deck_json", type=Path, help="path to deck.json (will be mutated)")
    ap.add_argument("--slide-key", help="sync only this slide (key match)")
    ap.add_argument("--dry-run", action="store_true",
                    help="report drift without writing")
    ap.add_argument("--check-drift", action="store_true",
                    help="read-only GUARD (F-315): exit 10 if index.html carries "
                         "authored edits / baked-DOM traces NOT present in deck.json "
                         "(un-synced browser edit-mode / hand-patch that the next "
                         "re-render would silently destroy), exit 0 if in sync, 2 on "
                         "error. Writes nothing, applies no direction guard. deck-cli "
                         "calls this before mutating deck.json; render-deck calls it "
                         "before overwriting a same-source index.html.")
    ap.add_argument("--force", action="store_true",
                    help="convert template-layout slides (cover/quote/etc) to raw")
    ap.add_argument("--backfill", action="store_true",
                    help="create deck.json FROM SCRATCH out of an index.html that "
                         "has none (legacy HTML-only deck). Reverse-engineers the "
                         "rendered DOM into raw slides marked lifted (imported "
                         "provenance). Auto-engaged when deck.json is absent.")
    ap.add_argument("--hidden-only", action="store_true",
                    help="surgical: reconcile ONLY the `hidden` flag (隐藏页) from "
                         "data-hidden in the HTML back into deck.json. Touches "
                         "nothing else (no raw conversion). Use after the in-browser "
                         "edit-mode eye toggle + ⌘S to push the change to the source.")
    ap.add_argument("--order-only", action="store_true",
                    help="surgical: reconcile ONLY slide ORDER (the edit-mode "
                         "drag-reorder) from the HTML DOM order back into deck.json. "
                         "Touches nothing else. Combine with --hidden-only to sync both.")
    ap.add_argument("--notes-only", action="store_true",
                    help="surgical: reconcile ONLY speaker notes (口播稿) from the "
                         "#fs-deck-notes island back into deck.json `notes`. Use after "
                         "editing notes in the presenter view + 💾/⌘S. Combinable.")
    ap.add_argument("--index-is-newer", "--force-direction", dest="index_is_newer",
                    action="store_true",
                    help="override the DIRECTION GUARD: reverse-feed index.html → "
                         "deck.json even when deck.json's mtime is newer (i.e. you "
                         "really did hand-edit index.html and have NOT touched "
                         "deck.json since). Without this, a newer deck.json downgrades "
                         "a full sync to a dry-run + hard warning, to avoid silently "
                         "clobbering un-rendered deck.json edits with stale HTML.")
    ap.add_argument("--sanitize", action="store_true",
                    help="treat index.html as a saved/'baked' live DOM (carries "
                         "runtime traces feishu-deck.js wrote at present-mode init) "
                         "and STRIP those traces before comparing for drift: the "
                         "reveal --child-i prop, per-slide data-fs-* balance markers, "
                         "per-frame data-idx, .deck runtime flags, and the inline "
                         "geometry the balance/canvas-center passes inject "
                         "(top/bottom/min-height/align-self/justify-content/padding). "
                         "Without this, a baked index.html is REFUSED (those runtime "
                         "mutations are NOT author edits — folding them into deck.json "
                         "makes the source drift every round-trip). Prefer saving via "
                         "the in-browser edit-mode (⌘S already sanitizes); use this "
                         "for a plain browser 'save page' or an externally-baked file.")
    args = ap.parse_args()

    if args.check_drift:
        # Read-only guard: never write, never apply the direction guard (the
        # CALLER decides what to do based on the verdict). dry_run keeps every
        # `if not args.dry_run` write-branch below inert.
        args.dry_run = True

    if not args.index_html.exists():
        print(f"sync-index-to-deck: {args.index_html} not found", file=sys.stderr)
        return 2

    # R-BAKED-DOM GUARD (F-259): refuse to reverse-feed a saved/"baked" live DOM
    # unless the operator opts into sanitizing it. The in-browser edit-mode ⌘S
    # already strips these traces (deck-edit-mode.js buildSavedHTML), so a normal
    # edit→save→sync flow never trips this. It catches a plain browser "save page"
    # or any externally-baked snapshot whose runtime mutations would otherwise be
    # folded into deck.json as fake author edits ("越改越坏"). Applies to ALL
    # modes (full / surgical / backfill) — runtime traces pollute any reverse map.
    _baked_hits = _baked_dom_fingerprints(
        args.index_html.read_text(encoding="utf-8", errors="replace"))
    if _baked_hits and not args.sanitize:
        if args.check_drift:
            # A baked live DOM = index.html was opened in the browser and saved
            # (runtime traces present) → touched OUTSIDE the renderer AND needs
            # --sanitize judgement before a reverse-feed → report as LOSSY (11):
            # un-synced state present, but NOT safe to auto-sync.
            return 11
        print("⚠ R-BAKED-DOM: index.html looks like a saved/'baked' live DOM, "
              "not a render-deck.py output.", file=sys.stderr)
        print("  Runtime traces present: " + "；".join(_baked_hits) + "。",
              file=sys.stderr)
        print("  These are written by feishu-deck.js at present-mode init, NOT by "
              "an author. Reverse-feeding them would corrupt deck.json (the source "
              "would drift every round-trip).", file=sys.stderr)
        print("  → Preferred: re-save in the in-browser edit-mode (⌘S already "
              "strips them), then sync the clean file.", file=sys.stderr)
        print("  → Or, to strip the traces here before comparing, re-run with "
              "--sanitize.", file=sys.stderr)
        print("  (Refusing to write.)", file=sys.stderr)
        return 2

    if args.hidden_only or args.order_only or args.notes_only:
        if not args.deck_json.exists():
            print(f"sync-index-to-deck: --hidden-only/--order-only/--notes-only need an "
                  f"existing {args.deck_json}", file=sys.stderr)
            return 2
        return run_surgical_sync(args.index_html, args.deck_json,
                                 do_hidden=args.hidden_only, do_order=args.order_only,
                                 do_notes=args.notes_only, dry_run=args.dry_run)

    # BACKFILL: explicit flag, OR auto-engaged when the deck.json target doesn't
    # exist yet (a legacy HTML-only deck being operated on for the first time).
    # DECKJSON-UNIFIED-INTERMEDIATE-SPEC §5: backfill the 中间层 by reverse-
    # engineering the real rendered DOM (NO screenshots).
    if args.backfill or not args.deck_json.exists():
        if args.slide_key:
            print("sync-index-to-deck: --slide-key is not supported with backfill",
                  file=sys.stderr)
            return 2
        return run_backfill(args.index_html, args.deck_json, dry_run=args.dry_run,
                            sanitize=args.sanitize)

    # DIRECTION GUARD (F-273): a full sync assumes index.html is the NEWER side
    # (the post-render-edited one). If deck.json is NEWER, the operator most
    # likely edited deck.json and forgot to re-render — running sync would feed
    # the STALE index.html back over those edits. Refuse to write: downgrade to a
    # dry-run + hard warning. Override with --index-is-newer. Within the surgical
    # paths above this guard is intentionally not applied (those are lossless
    # idempotent reconciles of fields the browser owns, not a content overwrite).
    direction_forced_dry = False
    newer_by = _wrong_direction(args.deck_json, args.index_html)
    if newer_by is not None and not args.index_is_newer and not args.dry_run:
        print("⚠ DIRECTION GUARD: deck.json is "
              f"{newer_by:.0f}s NEWER than index.html.", file=sys.stderr)
        print("  Drift direction is probably REVERSED: you likely edited "
              "deck.json and have not re-rendered yet.", file=sys.stderr)
        print("  Running sync now would overwrite those edits with the STALE "
              "index.html. Refusing to write.", file=sys.stderr)
        print("  → If you meant to apply deck.json edits, RE-RENDER instead:",
              file=sys.stderr)
        print(f"      python3 {Path(__file__).parent.name}/render-deck.py "
              f"{args.deck_json}  {args.deck_json.parent}/", file=sys.stderr)
        print("  → If you really did hand-edit index.html (deck.json untouched), "
              "re-run with --index-is-newer to force the reverse-feed.",
              file=sys.stderr)
        print("  (Falling back to --dry-run for this run.)\n", file=sys.stderr)
        args.dry_run = True
        direction_forced_dry = True

    index_html = args.index_html.read_text(encoding="utf-8")
    if args.sanitize:
        # Strip runtime traces (--child-i + balance/canvas-center inline geometry
        # + data-fs-*/data-idx/.deck flags) so the per-slide drift compare below
        # — extract_slide_inner → data.html, sync_canvas_data → elements[],
        # custom_css, and the order/hidden/notes reconciles — sees the pure AUTHOR
        # state and never folds a runtime mutation into deck.json. (F-259)
        index_html = sanitize_runtime_traces(index_html)
        print("  (--sanitize: stripped runtime traces before drift compare.)")
    deck = json.loads(args.deck_json.read_text(encoding="utf-8"))

    drift_count = 0
    lossy_drift = False   # F-315: set when a canvas slide drifts (reverse-map is
                          # non-idempotent — geometry/multi-run text). raw / custom_css
                          # / order / hidden / notes reverse losslessly. Used by
                          # --check-drift to tell the caller whether auto-sync is safe.
    skipped_template = []
    skipped_missing = []
    synced = []
    synced_css = []

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

        # --- custom_css block drift (F-273, layout-agnostic) ---
        # extract_slide_inner() STRIPS the leading <style data-fs-custom-css>
        # block before comparing data.html, and no other path compares it — so a
        # browser edit to that block was silently dropped while sync reported
        # "no drift". Compare the rendered block body against the deck.json
        # `custom_css` field (scoped via the SAME primitive render-deck.py uses;
        # scope_selectors is idempotent, so scoping the field reproduces the
        # rendered body when there is no drift) and write back on mismatch. The
        # stored value is the already-scoped body, which round-trips (re-render
        # re-scopes → no change), matching _extract_slide_custom_css's contract.
        html_css = _extract_slide_custom_css(index_html, key)
        cur_css = slide.get("custom_css") or ""
        if html_css.strip() != _scope_selectors(cur_css, key).strip():
            drift_count += 1
            if not args.dry_run:
                if html_css.strip():
                    slide["custom_css"] = html_css
                else:
                    slide.pop("custom_css", None)
            synced_css.append((key, len(cur_css), len(html_css)))

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
            lossy_drift = True   # F-315: canvas reverse-map is lossy → not auto-syncable
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

    surgical_lines: list[str] = []
    if not args.slide_key:
        # Reorder deck.json slides to match index.html DOM order. The visual
        # editor's drag-reorder only rewrites index.html DOM order; without
        # syncing it back, re-render restores the OLD deck.json order and the
        # reorder is lost. Only when syncing the WHOLE deck (no --slide-key) and
        # the key SETS match (a pure permutation — not an add/remove, which is
        # other drift handled elsewhere).
        dom_order = re.findall(
            r'<div class="slide(?:\s[^"]*)?"[^>]*data-slide-key="([^"]+)"', index_html)
        deck_keys = [s.get("key") for s in deck.get("slides", []) if s.get("key")]
        if dom_order and set(dom_order) == set(deck_keys) and dom_order != deck_keys:
            drift_count += 1
            synced.append(("reorder", "DOM order != deck.json order", 0, 0))
            if not args.dry_run:
                order_idx = {k: i for i, k in enumerate(dom_order)}
                deck["slides"].sort(key=lambda s: order_idx.get(s.get("key"), 1 << 30))

        # hidden / notes reconcile (F-273): these were previously reachable ONLY
        # via --hidden-only / --notes-only, so a default full sync silently left
        # browser-toggled 隐藏页 and edited 口播稿 un-synced (then reported "no
        # drift"). They are lossless idempotent field reconciles — fold them into
        # the default whole-deck path. (Skipped under --slide-key, like order:
        # those are whole-deck structural concerns, not a single-slide content sync.)
        h_changed, h_lines = _reconcile_hidden(deck, index_html, args.dry_run)
        n_changed, n_lines = _reconcile_notes(deck, index_html, args.dry_run)
        surgical_lines = h_lines + n_lines
        if h_changed:
            drift_count += 1
        if n_changed:
            drift_count += 1

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
    if synced_css:
        verb = "WOULD UPDATE" if args.dry_run else "UPDATED"
        print(f"  {verb} custom_css: {len(synced_css)} slide(s)")
        for key, old_size, new_size in synced_css:
            print(f"    [{'custom_css':14s}] {key}  ({old_size}→{new_size} chars)")
    if surgical_lines:
        for line in surgical_lines:
            print(line)
    if skipped_template:
        # F-273: a template slide with browser edits is data loss waiting to
        # happen — re-render drops the edits, --force drops the structured
        # fields. Was a silent SKIPPED line; now a loud WARNING.
        print(f"  ⚠ WARNING — {len(skipped_template)} TEMPLATE slide(s) have browser "
              f"edits that will be LOST on re-render:")
        for key, layout in skipped_template:
            print(f"    {key} (layout={layout}) — edits not synced. --force would "
                  f"convert it to raw (LOSSY: drops structured {layout} fields). A "
                  f"by-field reverse map for template slides is a separate task.")
    if skipped_missing:
        print(f"  SKIPPED (slide-key not in index.html): {len(skipped_missing)}")
        for key in skipped_missing:
            print(f"    {key}")
    if args.check_drift:
        # F-315 guard verdict for the caller (deck-cli / render auto-sync):
        #   0  = in sync (no slide-level drift)
        #   10 = drift present, ALL lossless (raw / custom_css / order / hidden /
        #        notes) → safe to auto reverse-sync
        #   11 = drift present, some LOSSY (a canvas slide) → needs human / --force
        if not drift_count:
            return 0
        return 11 if lossy_drift else 10

    if drift_count == 0:
        print("  ✓ deck.json is in sync with index.html — no drift detected.")
        return 0

    if args.dry_run:
        if direction_forced_dry:
            print(f"\n  (DIRECTION GUARD forced --dry-run; deck.json NOT modified. "
                  f"{drift_count} item(s) would be reverse-fed. Re-render, or pass "
                  f"--index-is-newer to override.)")
        else:
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
