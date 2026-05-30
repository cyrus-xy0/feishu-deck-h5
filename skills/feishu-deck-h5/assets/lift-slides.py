#!/usr/bin/env python3
"""
lift-slides.py — extract slides from a source feishu-deck-h5 deck into a target
deck.json as `layout: "raw"` entries, with assets resolved automatically.

The 飞书 deck "Native slide lift" pattern (per SKILL.md) lets you splice a slide
from another deck verbatim into your current one. The manual pipeline has 3
high-risk steps:

  1. Cut the right DOM range (over- or under-cut → R-DOM nested / R-KEY dup)
  2. Rescope CSS selectors that filter on `[data-layout=…]` (because the wrapper
     becomes `data-layout="raw"`)
  3. Copy referenced ASSETS (images, prototypes, fonts) so the lift doesn't
     render with broken refs

Step 3 is the most-forgotten one — `_NOT_PORTED_input/` flag-and-forget patterns
silently break images. This tool fixes that: it auto-detects asset references in
the lifted inner HTML and copies them from source → destination.

USAGE:
    python3 lift-slides.py SRC_DECK.html FRAME_INDICES DEST_DECK_JSON [OUTPUT_DIR]

    SRC_DECK.html    — source deck's index.html (lifted-from)
    FRAME_INDICES    — comma-separated 1-indexed slide positions, e.g. "5,6,7"
    DEST_DECK_JSON   — destination deck.json (slides appended)
    OUTPUT_DIR       — optional; defaults to dirname(DEST_DECK_JSON).
                       Assets are copied to OUTPUT_DIR/input/ and
                       OUTPUT_DIR/prototypes/<slug>/.

EXAMPLE:
    python3 skills/feishu-deck-h5/assets/lift-slides.py \\
        ~/Downloads/source-deck/index.html \\
        34,35,36,37,38 \\
        runs/<ts>/output/deck.json

WHAT IT DOES:
  · For each requested frame, slices the inner of `<div class="slide">…</div>`
  · Drops the inline duplicate wordmarks (renderer auto-injects)
  · Strips `data-text-id` attrs (locator-bound, would collide with target deck)
  · Rescopes CSS selectors: `[data-slide-key="X"][data-layout="…"]` → drop the
    [data-layout="…"] filter (so the slide-key-scoped rules still match after
    the wrapper changes to data-layout="raw")
  · Rewrites asset URLs:
      assets/shared/…           → ../../../skills/feishu-deck-h5/assets/shared/…
      assets/lark-*.{png,jpg}   → ../../../skills/feishu-deck-h5/assets/…
      input/<file>              → input/<file>  (copied to OUTPUT_DIR/input/)
      prototypes/<slug>/…       → prototypes/<slug>/…  (whole dir copied)
  · Appends slide entries to deck.json with `lifted: "<src-stem>#<key>"` and
    `decor: [...]`, `accent`, etc. preserved.
  · Reports per-slide: key, label, decor/accent, bytes, asset copies.

WHY layout: "raw" + slide-key-scoped CSS + framework defaults
  · Framework's `.header { top:61 left:73 right:320 }` and `.stage { top:200
    bottom:200 left:96 right:96 ... }` apply to `data-layout="raw"` since
    2026-05-28, so most lifted slides need NO per-deck CSS patch.
  · Source's own slide-key-scoped CSS retains specificity over framework
    defaults, so custom top/bottom/etc. still wins.

LIMITATIONS
  · One source deck per invocation (multi-source = run multiple times).
  · Assumes the source uses the standard SKILL conventions (slide-frame /
    slide-key / data-layout attrs).
  · Doesn't run validator — pipe through render-deck.py --visual afterwards
    to verify (errors will be loud).

Per SKILL.md "Native slide lift" rules, lifted slides keep `lifted` metadata
which the validator uses to downgrade typography/color violations to warnings.
"""
import argparse
import json
import re
import shutil
import sys
from pathlib import Path

SKILL_PREFIX = "../../../skills/feishu-deck-h5/"

# Layouts whose visual depends 100% on framework's `.slide[data-layout="X"]`
# rules. When we lift to `layout: "raw"`, those rules stop matching and the
# slide renders at browser defaults (e.g. 92px blockquote → 16px). Auto-inline
# the framework's rules scoped to the new slide-key to preserve the visual.
HEAVY_FRAMEWORK_LAYOUTS = {"quote", "cover", "section", "big-stat", "end"}


def iter_css_rules(css):
    """Yield (selector, body) for top-level CSS rules. Skips @-rules (media,
    keyframes, etc.) and comments. Doesn't handle nested rules (CSS doesn't
    have them at top level in this codebase)."""
    i, n = 0, len(css)
    while i < n:
        # Skip whitespace
        while i < n and css[i] in ' \t\n\r':
            i += 1
        if i >= n: break
        # Skip block comment /* ... */
        if css[i:i+2] == '/*':
            j = css.find('*/', i + 2)
            if j == -1: break
            i = j + 2
            continue
        # Skip @-rule entirely (find matching close brace or ;)
        if css[i] == '@':
            brace = css.find('{', i)
            semi = css.find(';', i)
            if brace == -1 or (semi != -1 and semi < brace):
                i = (semi + 1) if semi != -1 else n
                continue
            # @-rule with body — scan balanced braces
            depth, k = 1, brace + 1
            while k < n and depth > 0:
                c = css[k]
                if c == '{': depth += 1
                elif c == '}': depth -= 1
                k += 1
            i = k
            continue
        # Regular rule: selector { body }
        brace = css.find('{', i)
        if brace == -1: break
        selector = css[i:brace].strip()
        depth, k = 1, brace + 1
        while k < n and depth > 0:
            c = css[k]
            if c == '{': depth += 1
            elif c == '}': depth -= 1
            k += 1
        body = css[brace + 1 : k - 1].strip()
        yield selector, body
        i = k


def extract_framework_layout_css(framework_css, layout, slide_key):
    """Extract all rules from framework_css that target `.slide[data-layout=LAYOUT]`
    (in any of the comma-separated selector parts), rewriting the layout attr
    to `[data-slide-key=KEY]`. Also handles `:has(> .slide[data-layout=LAYOUT])`
    on `.slide-frame` (the letterbox bg rule) the same way.
    Returns CSS text — empty string if nothing matched."""
    target = f'[data-layout="{layout}"]'
    replacement = f'[data-slide-key="{slide_key}"]'
    out = []
    for selector, body in iter_css_rules(framework_css):
        parts = [p.strip() for p in selector.split(',')]
        kept = [p.replace(target, replacement) for p in parts if target in p]
        if kept:
            out.append(",\n".join(kept) + " {\n  " + body + "\n}")
    return "\n".join(out)


# Cache framework CSS so we read it once per invocation
_FRAMEWORK_CSS = None
def get_framework_css():
    global _FRAMEWORK_CSS
    if _FRAMEWORK_CSS is None:
        css_path = Path(__file__).resolve().parent / 'feishu-deck.css'
        _FRAMEWORK_CSS = css_path.read_text() if css_path.exists() else ''
    return _FRAMEWORK_CSS


def find_frame_lines(src_lines):
    """Return list of (1-indexed) line numbers where `<div class="slide-frame"`
    appears, in document order. The Nth entry is the start of the Nth slide."""
    starts = []
    for i, line in enumerate(src_lines, 1):
        if '<div class="slide-frame"' in line:
            starts.append(i)
    return starts


def extract_one(src_lines, frame_start, frame_end):
    """Slice the inner of the slide inside frame_start..frame_end (1-indexed
    inclusive). Returns dict with: key, label, accent, decor, orig_layout,
    lifted, inner_html, image_refs."""
    # Find <div class="slide" within
    slide_open = None
    for i in range(frame_start, frame_end):
        if re.search(r'<div class="slide"', src_lines[i]):
            slide_open = i + 1  # 1-indexed
            break
    if slide_open is None:
        raise ValueError(f"no <div class='slide'> found between lines {frame_start}..{frame_end}")
    # Find the slide close by reverse-scanning from frame_end.
    # The slide-frame structure is:
    #   <div class="slide-frame">
    #     <div class="slide">…</div>      ← we want THIS close
    #   </div>                              ← slide-frame close
    # So the slide close is the SECOND-from-end <code>&lt;/div&gt;</code>, not the first.
    # (Earlier off-by-one bug stopped at slide-frame close and pulled an
    # extra </div> into the inner — 2026-05-29 P15 R-DOM imbalance.)
    closes_seen = 0
    slide_close = frame_end - 1
    while slide_close > slide_open:
        if src_lines[slide_close - 1].strip().startswith('</div>'):
            closes_seen += 1
            if closes_seen == 2:
                break
        slide_close -= 1

    opening = src_lines[slide_open - 1]

    def attr(name):
        m = re.search(rf'{name}="([^"]*)"', opening)
        return m.group(1) if m else None

    info = {
        "key": attr("data-slide-key"),
        "label": attr("data-screen-label"),
        "accent": attr("data-accent"),
        "decor": attr("data-decor"),
        "lifted_original": attr("data-lifted"),
        "orig_layout": attr("data-layout"),
    }
    inner = "".join(src_lines[slide_open : slide_close - 1])
    return info, inner


def transform(inner, src_input_dir, src_proto_dir, dst_input_dir, dst_proto_dir,
              report, orig_layout=None, slide_key=None):
    """Apply rescope + asset-rewrite + asset-copy transforms to inner HTML.
    `report` is a dict to accumulate per-slide asset-copy log.
    `orig_layout` + `slide_key`: if orig_layout is in HEAVY_FRAMEWORK_LAYOUTS,
    auto-inline the framework's [data-layout=X] CSS rescoped to slide-key
    (so lifted-as-raw doesn't lose the source's framework-driven styles)."""
    # 1) Drop renderer-duplicate wordmarks (renderer auto-injects one)
    inner = re.sub(r'\s*<div class="wordmark">飞书</div>\s*\n', '\n', inner, count=1)
    inner = re.sub(r'\s*<div class="wordmark"></div>\s*\n', '\n', inner, count=1)

    # 2) Strip data-text-id attrs (would collide with target deck's texts.md)
    inner = re.sub(r'\s+data-text-id="[^"]*"', '', inner)

    # 3) Rescope CSS: drop [data-layout="..."] filter from slide-key-scoped rules
    inner = re.sub(
        r'(\[data-slide-key="[^"]+"\])\[data-layout="[^"]+"\]',
        r'\1',
        inner
    )

    # 4) Rewrite shared/framework asset paths to skill-relative
    for q in ("'", '"'):
        inner = inner.replace(
            f"url({q}assets/shared/", f"url({q}{SKILL_PREFIX}assets/shared/")
        for f in ("lark-logo.png", "lark-logo-mono-white.png",
                  "lark-cover-bg.jpg", "lark-content-bg.jpg",
                  "lark-section-bg.jpg", "lark-slogan.png"):
            inner = inner.replace(
                f"url({q}assets/{f}{q}", f"url({q}{SKILL_PREFIX}assets/{f}{q}")

    # 5) Auto-copy input/<file> references + leave path local
    for m in re.finditer(r'''url\(['"]?input/([^'")\s]+)['"]?\)''', inner):
        fname = m.group(1)
        src = src_input_dir / fname
        dst = dst_input_dir / fname
        if src.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            if not dst.exists() or src.stat().st_mtime > dst.stat().st_mtime:
                shutil.copy2(src, dst)
            report.setdefault("input_copied", []).append(fname)
        else:
            report.setdefault("input_missing", []).append(fname)

    # 5.5) Auto-inline framework CSS for heavy-framework-styled source layouts.
    # When source's `data-layout="quote/cover/section/big-stat/end"`, the slide's
    # visual depends ENTIRELY on framework `[data-layout=X]` rules. Lifting to
    # `raw` makes those rules stop matching → slide renders at browser defaults
    # (e.g. quote blockquote falls from 92px to 16px). Auto-inline those rules
    # rescoped to the new slide-key. (Triggered 2026-05-29 P14 lift.)
    if orig_layout in HEAVY_FRAMEWORK_LAYOUTS and slide_key:
        framework_css = get_framework_css()
        injected = extract_framework_layout_css(framework_css, orig_layout, slide_key)
        if injected:
            inner = (
                f'<style>\n'
                f'/* AUTO-INLINED from framework `.slide[data-layout="{orig_layout}"]` rules\n'
                f'   (2026-05-29 lift-slides.py · prevents lifted-as-raw style loss) */\n'
                f'{injected}\n'
                f'</style>\n' + inner
            )
            report.setdefault("inlined_layout_css", []).append(orig_layout)

    # 6) Auto-copy prototypes/<slug>/ for iframe src="prototypes/..."
    for m in re.finditer(r'''src=['"]prototypes/([^/'"]+)/''', inner):
        slug = m.group(1)
        src = src_proto_dir / slug
        dst = dst_proto_dir / slug
        if src.is_dir():
            if not dst.exists():
                shutil.copytree(src, dst)
            report.setdefault("proto_copied", []).append(slug)
        else:
            report.setdefault("proto_missing", []).append(slug)

    return inner


def lift(src_html_path, frame_indices, dst_deck_json, output_dir=None):
    src_html_path = Path(src_html_path).resolve()
    dst_deck_json = Path(dst_deck_json).resolve()
    output_dir = Path(output_dir).resolve() if output_dir else dst_deck_json.parent

    src_dir = src_html_path.parent
    src_input_dir = src_dir / "input"
    src_proto_dir = src_dir / "prototypes"
    dst_input_dir = output_dir / "input"
    dst_proto_dir = output_dir / "prototypes"

    src_lines = src_html_path.read_text().splitlines(keepends=True)
    starts = find_frame_lines(src_lines)
    src_stem = src_html_path.parent.name.replace(" ", "")  # e.g. "merged-49pages 2" → "merged-49pages2"

    if dst_deck_json.exists():
        deck = json.loads(dst_deck_json.read_text())
    else:
        deck = {"version": "1.0", "deck": {}, "slides": []}

    print(f"source : {src_html_path}")
    print(f"frames : {len(starts)} total in source; lifting {frame_indices}")
    print(f"target : {dst_deck_json}")
    print(f"output : {output_dir}")
    print()

    appended = 0
    for one_indexed in frame_indices:
        if one_indexed < 1 or one_indexed > len(starts):
            print(f"✗ frame {one_indexed} out of range (source has {len(starts)})")
            continue
        fs = starts[one_indexed - 1]
        fe = starts[one_indexed] - 1 if one_indexed < len(starts) else len(src_lines)
        try:
            info, inner = extract_one(src_lines, fs, fe)
        except ValueError as e:
            print(f"✗ frame {one_indexed}: {e}")
            continue
        report = {}
        inner = transform(inner, src_input_dir, src_proto_dir,
                          dst_input_dir, dst_proto_dir, report,
                          orig_layout=info.get("orig_layout"),
                          slide_key=info.get("key"))
        # Verify no nested .slide
        if '<div class="slide"' in inner:
            print(f"  ⚠ frame {one_indexed} ({info['key']}): nested .slide remains in inner — "
                  f"check frame boundary")
        entry = {
            "key": info["key"],
            "layout": "raw",
            "screen_label": info["label"],
            "lifted": f"{src_stem}#{info['key']}",
            "data": {"html": inner},
        }
        if info["accent"]:
            entry["accent"] = info["accent"]
        if info["decor"]:
            entry["decor"] = [info["decor"]]
        deck["slides"].append(entry)
        appended += 1
        cp = report.get("input_copied", [])
        miss = report.get("input_missing", [])
        proto = report.get("proto_copied", [])
        print(f"✓ frame {one_indexed:3d} → key={info['key']!r} ({len(inner)} bytes)")
        if cp: print(f"    input/ copied: {cp}")
        if proto: print(f"    prototypes/ copied: {proto}")
        if miss: print(f"    ✗ input/ MISSING in source: {miss}")
        inlined = report.get("inlined_layout_css", [])
        if inlined: print(f"    auto-inlined framework CSS for: {inlined}")

    dst_deck_json.write_text(
        json.dumps(deck, ensure_ascii=False, indent=2) + "\n")
    print(f"\n✓ {appended} slides appended to {dst_deck_json.name} "
          f"(total {len(deck['slides'])})")
    print(f"Now run: python3 deck-json/render-deck.py {dst_deck_json} {output_dir}/ --visual")


def main():
    ap = argparse.ArgumentParser(
        description="Lift slides from a source feishu-deck-h5 deck into a target deck.json",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="See `lift-slides.py --help` and the script docstring for details.")
    ap.add_argument("src_html", help="source deck's index.html")
    ap.add_argument("frames", help="comma-separated 1-indexed frame positions, e.g. '5,6,7'")
    ap.add_argument("dst_deck_json", help="destination deck.json (slides appended)")
    ap.add_argument("output_dir", nargs="?", help="output dir (default: dst_deck_json's dir)")
    args = ap.parse_args()
    frames = [int(x) for x in args.frames.split(",") if x.strip()]
    lift(args.src_html, frames, args.dst_deck_json, args.output_dir)


if __name__ == "__main__":
    sys.exit(main() or 0)
