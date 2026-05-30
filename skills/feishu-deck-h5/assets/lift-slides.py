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
    python3 lift-slides.py SRC_DECK.html --index               # list slides, pick a key
    python3 lift-slides.py SRC_DECK.html --key KEY DEST_DECK_JSON [OUTPUT_DIR]

    SRC_DECK.html    — source deck's index.html (lifted-from)
    FRAME_INDICES    — comma-separated 1-indexed slide positions, e.g. "5,6,7"
    --index          — print a {frame|key|layout|label|bytes} manifest and exit
                       (zero-context discovery for FOREIGN decks with no
                       slide-index.json sidecar; native decks get that sidecar
                       from render-deck.py directly).
    --key KEY[,KEY]  — select slides by semantic data-slide-key instead of a
                       1-indexed frame number (resolved via the manifest).
    --shake          — tree-shake framework CSS for the slide's ACTUAL layout
                       (any of ~15, not just the 5 heavy) + pull source-head
                       @keyframes the slide references. For FOREIGN/legacy decks
                       whose per-slide CSS isn't in custom_css. Global
                       `.slide .foo` rules are NOT inlined — they apply in any
                       target deck that links feishu-deck.css.
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

# iter_css_rules is single-sourced in deck-json/_css_utils.py (LIFT-ARCHITECTURE
# step 1) so render-deck.py + lift-slides.py can't drift on CSS parsing.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "deck-json"))
from _css_utils import iter_css_rules  # noqa: E402

SKILL_PREFIX = "../../../skills/feishu-deck-h5/"

# Layouts whose visual depends 100% on framework's `.slide[data-layout="X"]`
# rules. When we lift to `layout: "raw"`, those rules stop matching and the
# slide renders at browser defaults (e.g. 92px blockquote → 16px). Auto-inline
# the framework's rules scoped to the new slide-key to preserve the visual.
HEAVY_FRAMEWORK_LAYOUTS = {"quote", "cover", "section", "big-stat", "end"}


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


# Cache framework CSS so we read it once per invocation. Concatenates all three
# framework sheets so [data-layout=X] extraction covers every layout: base
# layouts (feishu-deck.css), Phase-1.c extras — matrix/swim/waterfall/arch-stack/
# logo-wall/before-after (extra-layouts.css), and content/story-case
# (feishu-deck-patterns.css).
_FRAMEWORK_CSS = None
def get_framework_css():
    global _FRAMEWORK_CSS
    if _FRAMEWORK_CSS is None:
        here = Path(__file__).resolve().parent
        sheets = [
            here / 'feishu-deck.css',
            here.parent / 'deck-json' / 'templates' / 'extra-layouts.css',
            here / 'feishu-deck-patterns.css',
        ]
        _FRAMEWORK_CSS = "\n".join(
            p.read_text() for p in sheets if p.exists())
    return _FRAMEWORK_CSS


# --- Keyframe closure (L6) ------------------------------------------------
# Animation shorthand keywords that are NOT keyframe names (so we don't try to
# pull a @keyframes called "infinite").
_ANIM_KEYWORDS = {
    'none', 'initial', 'inherit', 'unset', 'normal', 'reverse', 'alternate',
    'alternate-reverse', 'infinite', 'paused', 'running', 'forwards',
    'backwards', 'both', 'linear', 'ease', 'ease-in', 'ease-out',
    'ease-in-out', 'step-start', 'step-end',
}


def _extract_keyframes(css):
    """Map keyframe-name → full `@keyframes name {...}` text (brace-matched)."""
    out = {}
    for m in re.finditer(r'@(?:-webkit-|-moz-)?keyframes\s+([\w-]+)\s*\{', css):
        name = m.group(1)
        i, depth = m.end(), 1
        while i < len(css) and depth:
            if css[i] == '{':
                depth += 1
            elif css[i] == '}':
                depth -= 1
            i += 1
        out[name] = css[m.start():i]
    return out


def _referenced_anim_names(text):
    """Animation names referenced by `animation:`/`animation-name:` declarations.
    Over-inclusive (a token that isn't really a keyframe just won't match a
    definition → no-op), which is the desired bias: never drop a real animation."""
    names = set()
    for m in re.finditer(r'animation-name\s*:\s*([^;}\n]+)', text):
        for n in m.group(1).split(','):
            n = n.strip()
            if n and n not in _ANIM_KEYWORDS:
                names.add(n)
    for m in re.finditer(r'animation\s*:\s*([^;}\n]+)', text):
        for tok in re.split(r'[\s,]+', m.group(1).strip()):
            if re.fullmatch(r'[A-Za-z_][\w-]*', tok) and tok not in _ANIM_KEYWORDS:
                names.add(tok)
    return names


def _source_author_css(full_html):
    """Concatenate all NON-framework `<style>` block bodies in the source HTML
    (head + deck-level page-anim blocks). These are exactly the styles that
    VANISH on lift if not carried — the keyframe closure pulls referenced
    @keyframes from here. Framework `<style data-source="framework">` is skipped
    (those keyframes resolve in the target's own linked feishu-deck.css)."""
    out = []
    for m in re.finditer(r'<style(?P<attrs>[^>]*)>(?P<body>.*?)</style>',
                         full_html, re.S):
        if 'data-source="framework"' in (m.group('attrs') or ''):
            continue
        out.append(m.group('body'))
    return "\n".join(out)


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
              report, orig_layout=None, slide_key=None, shake=False,
              src_head_css=""):
    """Apply rescope + asset-rewrite + asset-copy transforms to inner HTML.
    `report` is a dict to accumulate per-slide asset-copy log.
    `orig_layout` + `slide_key`: auto-inline the framework's `[data-layout=X]`
    CSS rescoped to slide-key (so lifted-as-raw doesn't lose the source's
    layout-specific styles). WITHOUT `shake`, only the 5 HEAVY_FRAMEWORK_LAYOUTS
    (back-compat default). WITH `shake` (L6), the slide's ACTUAL layout (any of
    ~15) — content/stats/flow/arch-stack/etc. layout rules also break on
    lift-to-raw. `shake` additionally pulls source-head `@keyframes` the slide
    references (the page-anim loss fix). Global `.slide .foo` rules are NOT
    inlined — they apply in any target deck that links feishu-deck.css."""
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

    # 5.5) Inline framework `[data-layout=X]` CSS rescoped to slide-key.
    # When source's layout-specific rules (`.slide[data-layout="X"] …`) style the
    # slide, lifting to `raw` makes them stop matching → slide renders at browser
    # defaults (e.g. quote blockquote 92px → 16px; content-3up grid collapses).
    # Default: only the 5 HEAVY_FRAMEWORK_LAYOUTS. With --shake: the slide's
    # ACTUAL layout (L6). `raw` is skipped — the lifted slide IS raw, so the
    # target's own `[data-layout="raw"]` rules already apply.
    if slide_key and orig_layout and orig_layout != "raw":
        injected = extract_framework_layout_css(
            get_framework_css(), orig_layout, slide_key)
        if injected and (shake or orig_layout in HEAVY_FRAMEWORK_LAYOUTS):
            inner = (
                f'<style>\n'
                f'/* AUTO-INLINED from framework `.slide[data-layout="{orig_layout}"]` rules\n'
                f'   (lift-slides.py · prevents lifted-as-raw style loss) */\n'
                f'{injected}\n'
                f'</style>\n' + inner
            )
            report.setdefault("inlined_layout_css", []).append(orig_layout)
        elif injected:
            # non-heavy layout, no --shake → this CSS would be lost on lift-to-raw
            report.setdefault("shake_hint", []).append(orig_layout)

    # 5.6) Keyframe closure (--shake): pull @keyframes the lifted slide references
    # from the source's AUTHOR head/deck <style> blocks (which vanish on lift —
    # the page-anim loss, cf. round-trip-integrity postmortem). Framework
    # keyframes are NOT pulled (they resolve in the target's linked sheet).
    if shake and src_head_css:
        referenced = _referenced_anim_names(inner)
        have = set(_extract_keyframes(inner))
        src_kf = _extract_keyframes(src_head_css)
        blocks = [src_kf[n] for n in sorted(referenced)
                  if n not in have and n in src_kf]
        if blocks:
            inner = (
                '<style>\n/* AUTO-PULLED @keyframes from source head '
                '(lift-slides.py --shake · prevents page-anim loss) */\n'
                + "\n".join(blocks) + '\n</style>\n' + inner
            )
            report.setdefault("keyframes_pulled", []).extend(
                n for n in sorted(referenced) if n not in have and n in src_kf)

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


def lift(src_html_path, frame_indices, dst_deck_json, output_dir=None, shake=False):
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
    # Source author head/deck CSS (non-framework <style> blocks) — keyframe
    # closure source for --shake (the page-anim styles that vanish on lift).
    src_head_css = _source_author_css("".join(src_lines)) if shake else ""
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
                          slide_key=info.get("key"),
                          shake=shake, src_head_css=src_head_css)
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
        kf = report.get("keyframes_pulled", [])
        if kf: print(f"    pulled @keyframes from source head: {kf}")
        hint = report.get("shake_hint", [])
        if hint:
            print(f"    ⓘ layout {hint} has framework CSS that won't survive "
                  f"lift-to-raw — re-run with --shake to inline it")

    dst_deck_json.write_text(
        json.dumps(deck, ensure_ascii=False, indent=2) + "\n")
    print(f"\n✓ {appended} slides appended to {dst_deck_json.name} "
          f"(total {len(deck['slides'])})")
    print(f"Now run: python3 deck-json/render-deck.py {dst_deck_json} {output_dir}/ --visual")


def build_manifest(src_html_path):
    """Stream a source index.html into a per-frame manifest
    [{frame_index, key, layout, label, bytes}] — without loading the body into a
    caller's context. Lets a lift pick a slide by semantic key from a small
    table for FOREIGN decks that have no slide-index.json sidecar (LIFT-
    ARCHITECTURE L4)."""
    src_html_path = Path(src_html_path).resolve()
    src_lines = src_html_path.read_text().splitlines(keepends=True)
    starts = find_frame_lines(src_lines)
    rows = []
    for i in range(len(starts)):
        fs = starts[i]
        fe = starts[i + 1] - 1 if i + 1 < len(starts) else len(src_lines)
        try:
            info, inner = extract_one(src_lines, fs, fe)
        except ValueError:
            info, inner = {"key": None, "label": None, "orig_layout": None}, ""
        rows.append({
            "frame_index": i + 1,
            "key": info.get("key"),
            "layout": info.get("orig_layout"),
            "label": info.get("label"),
            "bytes": len(inner),
        })
    return rows


def print_manifest(src_html_path):
    rows = build_manifest(src_html_path)
    print(f"{len(rows)} frames · {Path(src_html_path).name}")
    print(f"{'#':>3}  {'KEY':<34}  {'LAYOUT':<14}  {'BYTES':>7}  LABEL")
    print(f"{'-'*3}  {'-'*34}  {'-'*14}  {'-'*7}  {'-'*24}")
    for r in rows:
        print(f"{r['frame_index']:>3}  {(r['key'] or '?'):<34}  "
              f"{(r['layout'] or '?'):<14}  {r['bytes']:>7}  {(r['label'] or '')[:24]}")


def resolve_keys_to_frames(src_html_path, keys):
    """Map slide-keys → 1-indexed frame positions. Returns (frames, missing)."""
    rows = build_manifest(src_html_path)
    keymap = {r["key"]: r["frame_index"] for r in rows if r["key"]}
    frames, missing = [], []
    for k in keys:
        if k in keymap:
            frames.append(keymap[k])
        else:
            missing.append(k)
    return frames, missing


def main():
    ap = argparse.ArgumentParser(
        description="Lift slides from a source feishu-deck-h5 deck into a target deck.json",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="See `lift-slides.py --help` and the script docstring for details.")
    ap.add_argument("src_html", help="source deck's index.html")
    ap.add_argument("rest", nargs="*",
                    metavar="[FRAMES] DEST_DECK_JSON [OUTPUT_DIR]",
                    help="legacy: FRAMES DEST [OUT]; with --key: DEST [OUT]")
    ap.add_argument("--index", action="store_true",
                    help="print a slide manifest (key|layout|label|bytes) for SRC and exit "
                         "(for foreign decks without a slide-index.json sidecar)")
    ap.add_argument("--key",
                    help="comma-separated slide-keys to lift (alternative to positional FRAMES)")
    ap.add_argument("--shake", action="store_true",
                    help="tree-shake: inline framework [data-layout=X] CSS for the slide's "
                         "ACTUAL layout (any of ~15, not just the 5 heavy) + pull source-head "
                         "@keyframes the slide references. Use for FOREIGN/legacy decks whose "
                         "per-slide CSS isn't in custom_css. Over-inclusive by design.")
    args = ap.parse_args()

    if args.index:
        print_manifest(args.src_html)
        return 0

    rest = list(args.rest)
    if args.key:
        keys = [k for k in args.key.split(",") if k.strip()]
        frames, missing = resolve_keys_to_frames(args.src_html, keys)
        if missing:
            print(f"✗ slide-key(s) not found in source: {missing}\n", file=sys.stderr)
            print_manifest(args.src_html)
            return 1
        if not rest:
            print("✗ need DEST_DECK_JSON: lift-slides.py SRC.html --key K DEST.json [OUT]",
                  file=sys.stderr)
            return 1
        dst = rest[0]
        out = rest[1] if len(rest) > 1 else None
    else:
        if len(rest) < 2:
            print("✗ usage: lift-slides.py SRC.html FRAMES DEST.json [OUT]\n"
                  "         (or --index to list, or --key K DEST.json to select by key)",
                  file=sys.stderr)
            return 1
        frames = [int(x) for x in rest[0].split(",") if x.strip()]
        dst = rest[1]
        out = rest[2] if len(rest) > 2 else None

    lift(args.src_html, frames, dst, out, shake=args.shake)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
