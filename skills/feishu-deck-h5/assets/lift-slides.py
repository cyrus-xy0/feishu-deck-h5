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
                       (any of ~15, not just the 5 heavy) + RECOVER the source's
                       HEAD per-slide rules (the page-anim pattern:
                       `[data-slide-key=K]` / `[data-page=N]` rules in a head
                       <style>) + pull the @keyframes they reference. So an OLD
                       deck lifts CLEAN with no pre-fix / no migrate codemod.
                       Global `.slide .foo` rules are NOT inlined — they apply in
                       any target deck that links feishu-deck.css.
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
  · Writes a structured `lift_origin` provenance block on each lifted slide
    (src_deck / src_path / src_key / src_index / lifted_at:null) so heal/re-lift
    can return to the EXACT source slide deterministically — no class-signature
    reverse-guessing, no data-page≠visual-order mis-targeting (F-70). `lifted_at`
    is null on purpose: we never call datetime.now() (it would break workflow
    determinism); the caller stamps it if wanted.
  · Reports per-slide: key, label, decor/accent, bytes, asset copies, AND a
    full asset-reference scan (F-45) — every LOCAL ref (<iframe>/<img>/<source>/
    <video>/url()/background-image) bucketed as present / source-file-MISSING /
    framework-shared / BRAND-specific-clientlogo, so a human can swap or remove
    instead of the lift silently carrying or dropping. base64/http refs are not
    reported (self-contained / external). Informational only — never blocks.

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
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

# iter_css_rules is single-sourced in deck-json/_css_utils.py (LIFT-ARCHITECTURE
# step 1) so render-deck.py + lift-slides.py can't drift on CSS parsing.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "deck-json"))
from _css_utils import iter_css_rules  # noqa: E402


def atomic_write_text(path, text, encoding="utf-8"):
    """Crash-safe write (F-269): temp file in the same dir + os.replace, so a
    kill mid-write never leaves a half-written deck.json on disk. Mirrors
    deck-cli.atomic_write_text — kept as a local copy here to avoid an
    importlib dance against the hyphenated deck-cli.py module name."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding) as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise

SKILL_PREFIX = "../../../skills/feishu-deck-h5/"

# Layouts whose visual depends 100% on framework's `.slide[data-layout="X"]`
# rules. When we lift to `layout: "raw"`, those rules stop matching and the
# slide renders at browser defaults (e.g. 92px blockquote → 16px). Auto-inline
# the framework's rules scoped to the new slide-key to preserve the visual.
HEAVY_FRAMEWORK_LAYOUTS = {"quote", "cover", "section", "big-stat", "end"}

# Framework-drift modernization: an OLD deck may reference a CSS custom property
# the CURRENT framework no longer defines. var(--undefined) makes the WHOLE
# declaration fail in the browser — for a `font:` shorthand that means the size
# silently falls back to 16px (R-CSSVAR render-fail on lift). Map known-retired
# tokens to their current equivalent. `--fs-accent4` was the teal keyword-jump
# accent (ACCENT4 = teal per the copy rules) → now `--fs-teal`. (2026-06-02)
_RETIRED_VAR_MAP = {"--fs-accent4": "--fs-teal"}

# --shake recovers source-head per-slide CSS VERBATIM (step 5.55). Old decks
# often inline MB-scale background images as `data:…;base64,…` right there, and
# the same blob is frequently referenced 2×+. Carried verbatim, one such page
# balloons to 10-20 MB → every subsequent render-deck.py / validate.py pass
# re-parses the whole thing → the lift FEELS slow (the lift itself is instant;
# the tools choking on a bloated string is the cost). So at lift time we
# externalize any base64 blob over this threshold to an `input/` file (deduped
# by content hash, so N identical refs share ONE file) and rewrite the refs.
# Small inline blobs (icons, tiny textures) stay inline — self-contained is fine
# at small sizes; only the heavyweight ones are worth a file. Threshold is in
# base64 CHARACTERS (~4/3 of decoded bytes): 100_000 chars ≈ 75 KB decoded.
B64_EXTERNALIZE_MIN_CHARS = 100_000
# When Pillow is importable, also downscale the externalized raster to this max
# long-edge (decks are 1920×1080; a slide image rarely needs more) — pure weight
# win for delivery. Format is preserved (no lossy PNG→JPEG conversion, so diagram
# text stays crisp). If Pillow is absent we still externalize the RAW bytes — the
# parse-speed + dedupe win does NOT depend on Pillow.
B64_DOWNSCALE_MAX_EDGE = 1600
_B64_EXT_BY_MIME = {
    "image/png": "png", "image/jpeg": "jpg", "image/jpg": "jpg",
    "image/gif": "gif", "image/webp": "webp",
}
_B64_DATA_URI_RE = re.compile(
    r'data:(image/(?:png|jpe?g|gif|webp));base64,([A-Za-z0-9+/=]+)')

# --- F-84: self-contain per-deck content assets that live OUTSIDE output/ ----
# A SOURCE deck's slide can reference a per-run CONTENT asset via a leading
# `../input/<file>` — which, in the source run, resolves to the run-level
# `input/` (a SIBLING of `output/`). Lifted verbatim, the `../input/...` ref
# carries into the target and the file lands in the TARGET's run-level `input/`
# (also outside `output/`). That breaks the moment `output/` is moved/zipped/
# delivered or the run-level `input/` is cleaned (kangshifu `taste-shifts-3pains`
# product images 404'd this way). F-84 detects this family, copies the file into
# the target's `output/input/`, and rewrites the ref to the output-internal
# `input/<file>` form so the lifted slide is self-contained under `output/`.
#
# IMPORTANT scope: ONLY a single leading `../` followed by `input/` (the run-
# level content-asset sibling). Framework/shared linked refs
# (`../../../skills/feishu-deck-h5/assets/...`) are INTENTIONAL linked-mode refs
# handled by copy-assets.py at delivery — this pattern's `\.\./input/` anchor
# never matches them (they go `../../../skills/...`), so they are left untouched.
_REL_INPUT_RE = re.compile(r'^(?:\./)*\.\./input/(?P<file>[^?#]+)')


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
            p.read_text(encoding="utf-8") for p in sheets if p.exists())
    return _FRAMEWORK_CSS


# --- Target-framework layout coverage (F-83) ------------------------------
# When lifting INTO a legacy target whose bundled feishu-deck.css is an OLDER
# snapshot, that sheet may have NO `[data-layout="X"]` rules for the source
# page's layout. The lifted page renders as `data-layout="X"` (so the target's
# framework rules are what style it — lift-to-html keeps the orig layout on the
# wrapper, lift-to-deck.json relies on render-deck doing the same), so a MISSING
# layout block means the page renders unstyled (e.g. iframe-embed → iframe
# shrinks to a tiny box) UNLESS --shake inlines the framework rules into the
# slide itself. The pre-F-83 preview only inspected the SOURCE head for coupled
# CSS; it never asked whether the TARGET framework actually covers the layout,
# so `recommend_shake` stayed false and the user hit the breakage. These helpers
# resolve the target's framework CSS and check coverage for a given layout.

def _resolve_target_framework_css(target_index_html):
    """Read the FRAMEWORK CSS that a target index.html actually links.
    Resolves every `<link rel=stylesheet href=...>` relative to the target file
    (the common bundled case is `assets/feishu-deck.css`). For a single-file deck
    that has NO linked local stylesheet, falls back to concatenating the inlined
    `<style>` blocks (the framework is embedded there). Returns the combined CSS
    text (empty string if the target can't be read / has no resolvable CSS).

    IMPORTANT: when a linked framework sheet exists we deliberately do NOT fold
    in the page-level inlined `<style>` blocks. Those blocks are exactly the
    PER-SLIDE / shake-inlined CSS (e.g. `--shake`'s `AUTO-INLINED from framework
    [data-layout=X]` recovery) — counting them as "framework coverage" would
    mask the very gap we're detecting (a target that already absorbed one lift's
    shake-inlined block would look like it has the layout for the NEXT lift).
    The framework's own [data-layout=X] rules live in the linked sheet."""
    target = Path(target_index_html)
    try:
        html = target.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return ""
    base = target.resolve().parent
    parts = []
    # Linked stylesheets — resolve href relative to the target file.
    for m in re.finditer(r'<link\b[^>]*>', html, re.I):
        tag = m.group(0)
        if not re.search(r'rel\s*=\s*["\']?[^"\'>]*stylesheet', tag, re.I):
            continue
        hm = re.search(r'href\s*=\s*["\']([^"\']+)["\']', tag, re.I)
        if not hm:
            continue
        href = hm.group(1).strip()
        low = href.lower()
        if low.startswith(("http://", "https://", "//", "data:")):
            continue  # external sheet — not resolvable / not the lift's concern
        css_path = (base / href.split("?", 1)[0].split("#", 1)[0].lstrip("./"))
        try:
            if css_path.is_file():
                parts.append(css_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    # Single-file deck (no resolvable linked sheet): the framework is inlined in
    # <style> blocks — fall back to those. Skip when a linked sheet was found.
    if not parts:
        for m in re.finditer(r'<style\b[^>]*>(.*?)</style>', html, re.S | re.I):
            parts.append(m.group(1))
    return "\n".join(parts)


def target_lacks_layout_css(target_index_html, layout):
    """True if the target's framework CSS has NO rule selecting
    `[data-layout="LAYOUT"]`. `raw` (and a missing layout) is never flagged: a
    lifted raw slide is styled by the target's own `[data-layout="raw"]` rules,
    not a layout-specific block. Returns False when we can't read the target
    (don't false-warn on an unreadable target — the existing reasoning still
    applies)."""
    if not layout or layout == "raw":
        return False
    css = _resolve_target_framework_css(target_index_html)
    if not css:
        return False
    # Match `[data-layout="LAYOUT"]` allowing single OR double quotes (and the
    # render-deck inline form uses single quotes), tolerant of surrounding space.
    pat = re.compile(r'\[\s*data-layout\s*=\s*["\']' + re.escape(layout) + r'["\']\s*\]')
    return not pat.search(css)


# --- lift-fidelity helpers (F-250 asset-var deref · F-251 title seed) ------
_ASSET_VAR_DEF_RE = re.compile(
    r'--fs-asset-([a-z0-9-]+)\s*:\s*url\(\s*["\']?([^"\')]+)["\']?\s*\)', re.I)
_ASSET_VAR_USE_RE = re.compile(r'var\(\s*--fs-asset-([a-z0-9-]+)\s*\)', re.I)


def _asset_var_filemap():
    """`--fs-asset-NAME` → filename, parsed from feishu-deck.css :root."""
    m = {}
    for name, url in _ASSET_VAR_DEF_RE.findall(get_framework_css()):
        m[name.lower()] = url.rsplit('/', 1)[-1]
    return m


def _deref_asset_vars(css):
    """F-250: a `var(--fs-asset-X)` that ends up INLINED in the lifted slide's
    data.html resolves its url() relative to the HTML *document* (not the
    feishu-deck.css that defines the var) → 404 → black/blank background. Replace
    known asset vars with an explicit `url("assets/<file>")` — the path
    copy-assets lands framework brand assets at for linked-local delivery (the
    default + delivered form). Unknown vars are left untouched."""
    fm = _asset_var_filemap()
    def repl(mt):
        fn = fm.get(mt.group(1).lower())
        return f'url("assets/{fn}")' if fn else mt.group(0)
    return _ASSET_VAR_USE_RE.sub(repl, css)


def _source_title(html):
    """F-251: source deck <title> text, for seeding a new target deck.title."""
    m = re.search(r'<title[^>]*>(.*?)</title>', html, re.I | re.S)
    return re.sub(r'\s+', ' ', m.group(1)).strip() if m else ""


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


def _root_animation_names(css, slide_key):
    """Animation names applied to the `.slide` ROOT (not a descendant or pseudo-
    element) for this slide. The framework owns the root's `transform` (present-
    mode fit-scale); a recovered page-entrance animation that lands on the root
    is the one whose keyframes can clobber that scale (F-332)."""
    names = set()
    # Pre-guard: a slide whose markup has no `animation` substring (or no rule
    # braces at all) cannot declare a root animation → the loop below would walk
    # the whole input and return the SAME empty set, but the greedy `[^{}]+`
    # backtracks char-by-char on brace-free markup (O(n^2) → ~40s on a 90KB
    # content slide during `--shake` lift). Both checks are exact no-op proofs:
    # `_referenced_anim_names` only adds names from `animation:`/`animation-name:`
    # tokens (each contains "animation"), and the regex requires a literal `{`.
    if 'animation' not in css or '{' not in css:
        return set()
    key_sel = '.slide[data-slide-key="%s"]' % slide_key
    for m in re.finditer(r'([^{}]+)\{([^{}]*)\}', css):
        sel, body = m.group(1), m.group(2)
        if 'animation' not in body:
            continue
        for one in sel.split(','):
            one = one.strip()
            idx = one.find(key_sel)
            if idx == -1:
                continue
            rest = one[idx + len(key_sel):].strip()
            # root iff nothing (or only a pseudo-CLASS like :hover) follows the
            # slide-key compound. A descendant (` .x`, `>`, `+`, `~`) or a
            # pseudo-ELEMENT (`::before`) targets a different box → not the root.
            if rest == '' or (rest.startswith(':') and not rest.startswith('::')):
                names |= _referenced_anim_names(body)
                break
    return names


def _descale_root_animation_keyframes(css, slide_key, report=None):
    """F-332: strip `transform` from any @keyframes applied to the `.slide` ROOT
    via an entrance animation. The framework drives present-mode fit-scale through
    the root's `transform: scale(var(--fs-scale))`. A page-anim recovered onto the
    root (e.g. `fs-page-enter` with `to{transform:scale(1)}`, fill-mode `both`)
    freezes the root at the keyframe scale and overrides the fit-scale → the slide
    renders unscaled and overflows/clips at non-16:9 viewports. Opacity/filter and
    other entrance props are preserved; only `transform` (the fit-scale carrier)
    is removed, so the fade survives and the framework keeps the slide fitted."""
    if not slide_key:
        return css
    root_anims = _root_animation_names(css, slide_key)
    if not root_anims:
        return css
    kfs = _extract_keyframes(css)
    for name in root_anims:
        block = kfs.get(name)
        if not block or not re.search(r'(?:-webkit-)?transform\s*:', block):
            continue
        descaled = re.sub(r'\s*(?:-webkit-)?transform\s*:[^;}]*;?', '', block)
        css = css.replace(block, descaled)
        if report is not None:
            report.setdefault("root_anim_descaled", []).append(name)
    return css


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


def _page_to_key(full_html):
    """Map data-page → data-slide-key by reading each rendered frame's DOM (so
    [data-page=N] head rules can be re-pointed at the right lifted slide)."""
    out = {}
    for fm in re.finditer(r'<div\b[^>]*class="[^"]*\bslide-frame\b[^"]*"[^>]*>',
                          full_html):
        seg = full_html[fm.start():fm.end() + 1500]
        pm = re.search(r'data-page="?([\w-]+)"?', seg)
        km = re.search(r'data-slide-key="([^"]+)"', seg)
        if pm and km:
            out[pm.group(1)] = km.group(1)
    return out


# --- Asset-reference scan (F-45) ------------------------------------------
# A lifted slide's HTML can reference assets in several ways. base64 (`data:`)
# refs are self-contained (travel with the HTML) so we ignore them; http(s) refs
# are external (not ours to carry). Everything else is a LOCAL path that must be
# resolved against the SOURCE deck dir and (often) copied to the target — and if
# the source file is missing, the lifted page renders blank/broken. clientlogo
# refs are extra-special: they're BRAND-specific (the source customer's logo), so
# even when the file exists, a new customer almost certainly wants it swapped.
#
# This scanner is INFORMATIONAL only — it never blocks a lift, it just surfaces
# {present / missing / brand-specific} so a human can decide to swap or remove,
# instead of the old silent carry-or-drop behaviour.

# Local asset references in the inner HTML, by every syntax a slide can use:
#   <iframe src=...>, <img src=...>, <... src=...>, url(...), background-image
# We capture the raw URL token then filter to LOCAL paths below.
_ASSET_REF_PATTERNS = (
    re.compile(r'''<iframe\b[^>]*?\bsrc\s*=\s*['"]([^'"]+)['"]''', re.I),
    re.compile(r'''<img\b[^>]*?\bsrc\s*=\s*['"]([^'"]+)['"]''', re.I),
    re.compile(r'''<source\b[^>]*?\bsrc\s*=\s*['"]([^'"]+)['"]''', re.I),
    re.compile(r'''<video\b[^>]*?\b(?:src|poster)\s*=\s*['"]([^'"]+)['"]''', re.I),
    re.compile(r'''url\(\s*(?:&(?:quot|apos|#34|#39);|['"])?((?:[^'")&]|&(?!(?:quot|apos|#34|#39);))+?)(?:&(?:quot|apos|#34|#39);|['"])?\s*\)''', re.I),  # F-333: tolerate an entity-quote (&quot;/&#34;/&apos;/&#39;) OR literal quote wrapping the path, and a LITERAL '&' inside the filename (only a '&' that begins a quote-entity terminates) → capture the CLEAN inner ref, which both classifies and round-trips via inner.replace (it is a literal substring of the original url(...)). Verbatim mirror with import-html-slide.
)


def _is_local_asset_ref(url):
    """True for refs we must resolve against the source deck dir. False for
    self-contained (`data:`/base64) and external (`http(s):`//`mailto:` etc.)
    refs, and for in-page anchors / blank refs."""
    u = (url or "").strip()
    if not u:
        return False
    low = u.lower()
    if low.startswith(("data:", "http://", "https://", "//", "mailto:",
                       "tel:", "javascript:", "blob:", "#", "about:")):
        return False
    return True


def _strip_leading_dotslash(u):
    """Strip leading `./` segments only — NOT `../`. The old `lstrip("./")`
    stripped the *characters* `.`+`/` in any combination, so `../input/x.png`
    collapsed to `input/x.png` (mis-bucketed `input`) and `../../../skills/...`
    lost its `../`. F-84 needs `../input/...` to stay distinct from a plain
    `input/...`, so strip ONLY repeated `./` and stop at the first `../`."""
    while u.startswith("./"):
        u = u[2:]
    return u


def _classify_asset_ref(url):
    """Bucket a LOCAL asset ref for the report:
      'framework' — assets/shared/* or assets/lark-* (resolve in the SKILL, not
                    the per-deck dir; carried by path-rewrite, always present);
                    also the linked-mode `../../../skills/.../assets/...` form.
      'clientlogo'— assets/shared/clientlogo/* (BRAND-specific → flag for swap)
      'input'     — input/* per-run screenshots/source files (copied by transform)
      'rel-input' — ../input/* per-run CONTENT asset reached via a leading `../`
                    (resolves OUTSIDE output/ in the source run). F-84 copies it
                    INTO output/input/ and rewrites the ref to `input/...`.
      'prototype' — prototypes/<slug>/* iframe bodies (copied by transform)
      'other'     — any other local path (e.g. a sibling .html iframe body, a
                    relative ../foo.png) — these are the silent-break risk.
    """
    u = _strip_leading_dotslash(url.strip())
    low = u.lower()
    # F-84: a single leading `../` + input/ is the run-level content-asset family.
    # Check BEFORE the framework/clientlogo branches scan substrings — but the
    # framework `../../../skills/...` form has TWO+ `../` so it never matches this.
    if _REL_INPUT_RE.match(url.strip()):
        return "rel-input"
    if "shared/clientlogo/" in low or low.startswith("clientlogo/"):
        return "clientlogo"
    if low.startswith("assets/shared/") or re.match(r'assets/lark-', low):
        return "framework"
    if low.startswith("input/"):
        return "input"
    if low.startswith("prototypes/"):
        return "prototype"
    return "other"


def scan_asset_refs(inner, src_dir):
    """Scan a lifted slide's inner HTML for every LOCAL asset reference and
    resolve it against the SOURCE deck dir to learn if the file is present.
    Returns a list of dicts:
        {"url": <as-written>, "kind": <bucket>, "exists": <bool|None>}
    `exists` is None for kinds we don't resolve here (framework refs resolve in
    the skill tree after path-rewrite; we don't second-guess them). De-duplicated
    by url, document order preserved. base64/http refs are skipped entirely."""
    seen = set()
    refs = []
    for pat in _ASSET_REF_PATTERNS:
        for m in pat.finditer(inner):
            url = m.group(1).strip()
            if not _is_local_asset_ref(url) or url in seen:
                continue
            seen.add(url)
            kind = _classify_asset_ref(url)
            if kind == "framework":
                exists = None  # resolved in skill tree post path-rewrite
            elif kind == "prototype":
                # prototypes/<slug>/... → check the <slug> dir exists in source
                mm = re.match(r'(?:\./)?prototypes/([^/]+)/', url)
                exists = (src_dir / "prototypes" / mm.group(1)).is_dir() if mm else None
            elif kind == "rel-input":
                # F-84: `../input/foo.png` resolves to the RUN-LEVEL input/
                # (sibling of src_dir=output/), with output/input/ as a fallback.
                fname = _REL_INPUT_RE.match(url).group("file").split("?", 1)[0].split("#", 1)[0]
                exists = ((src_dir.parent / "input" / fname).is_file()
                          or (src_dir / "input" / fname).is_file())
            else:
                # input/clientlogo/other → resolve the path against source dir
                rel = _strip_leading_dotslash(
                    url.split("?", 1)[0].split("#", 1)[0])
                exists = (src_dir / rel).is_file()
            refs.append({"url": url, "kind": kind, "exists": exists})
    return refs


def extract_head_slide_rules(src_head_css, slide_key, page_map):
    """Pull source HEAD/deck-level rules that target THIS slide — via
    `[data-slide-key="K"]` or `[data-page="N"]` (N→K through page_map) — and
    rewrite any `[data-page="N"]` token to `[data-slide-key="K"]` so the rule
    still matches the lifted raw slide (which carries the slide-key, not
    data-page). This recovers the page-anim head pattern at lift time, so OLD
    decks lift clean WITHOUT first running the migrate codemod. @keyframes the
    rules reference are pulled by the closure step (5.6). Over-inclusive: a
    multi-target rule is kept whole when this slide is one of its targets."""
    # Inline single-file decks embed MB-scale images as `url(data:…;base64,…)`
    # right in the head CSS — a 248MB block is not unusual (wudeli). Brace-parsing
    # that verbatim is O(n²) in _match_brace (≈15s of a 21s lift). Stash the
    # `data:` URIs to short tokens BEFORE parsing, then restore them only in the
    # (few) rules we keep → byte-identical output, ~3× faster lift. The `data:`
    # guard keeps the normal-deck path (no data URIs) untouched. (wudeli, 2026-06-02)
    _uri_stash = {}

    def _stash_uri(m):
        tok = f"\x00DURI{len(_uri_stash)}\x00"
        _uri_stash[tok] = m.group(0)
        return tok

    light = (re.sub(r'data:[^)\s"\']+', _stash_uri, src_head_css)
             if 'data:' in src_head_css else src_head_css)
    keep = []
    for selector, body in iter_css_rules(light):
        keys = set(re.findall(r'\[data-slide-key="([^"]+)"\]', selector))
        for n in re.findall(r'\[data-page="?([\w-]+)"?\]', selector):
            mapped = page_map.get(n)
            if mapped:
                keys.add(mapped)
        if slide_key in keys:
            # `[data-page="N"]` matched the source FRAME (an ANCESTOR of `.slide`).
            # The lifted raw slide carries the key ON `.slide` itself, so a plain
            # token-swap yields `[data-slide-key="K"] .slide …` — which needs a
            # `.slide` NESTED in the keyed node (none exists) → rule matches 0
            # elements → the slide's bespoke layout collapses on lift (qingdao
            # `feishu-ecosystem` repro: diagram + compare-table vanish). Fuse the
            # redundant `(>) .slide` descendant onto the keyed `.slide` first,
            # then re-anchor any remaining bare `[data-page]` token onto `.slide`.
            #
            # Strip CSS comments from the SELECTOR first: authors annotate rule
            # groups inline (`[data-page="47"] /* 单 frame 卡片 */ .slide .card`),
            # and a comment between `[data-page]` and `.slide` breaks the fusion
            # → leaves a phantom ` .slide` descendant (radial icon positions
            # `.i1`..`.i6`, card `height:100%`, table cell sizing silently die →
            # "比例不对"). Comments are decorative in selector position; dropping
            # them is semantically safe. Rule-body comments are untouched.
            sel = re.sub(r'/\*[\s\S]*?\*/', ' ', selector)
            # A multi-target comma rule is kept whole because THIS slide is ONE
            # of its targets — but re-anchoring must touch ONLY the comma part(s)
            # that actually reference this slide. Re-anchoring across the whole
            # selector string would rewrite a sibling part like
            # `[data-page="9"] .slide .bar` onto THIS slide's key too, hijacking
            # page 9's selector. So split on commas and re-anchor per-part. (lift-4)
            new_parts = []
            for part in sel.split(','):
                part_keys = set(re.findall(r'\[data-slide-key="([^"]+)"\]', part))
                for n in re.findall(r'\[data-page="?([\w-]+)"?\]', part):
                    mapped = page_map.get(n)
                    if mapped:
                        part_keys.add(mapped)
                if slide_key not in part_keys:
                    # Targets a different page (or no keyed target) — leave it
                    # verbatim so it keeps matching its own slide, not this one.
                    new_parts.append(part)
                    continue
                np = re.sub(
                    r'\[data-page="?[\w-]+"?\]\s*(?:>\s*)?\.slide\b',
                    f'.slide[data-slide-key="{slide_key}"]', part)
                np = re.sub(
                    r'\[data-page="?[\w-]+"?\]',
                    f'.slide[data-slide-key="{slide_key}"]', np)
                new_parts.append(np)
            new_sel = ",".join(new_parts)
            rule = f"{new_sel} {{ {body} }}"
            if _uri_stash:
                rule = re.sub(r'\x00DURI\d+\x00',
                              lambda mm: _uri_stash[mm.group(0)], rule)
            keep.append(rule)
    return "\n".join(keep)


def find_frame_lines(src_lines):
    """Return list of (1-indexed) line numbers where `<div class="slide-frame"`
    appears, in document order. The Nth entry is the start of the Nth slide."""
    starts = []
    for i, line in enumerate(src_lines, 1):
        if '<div class="slide-frame"' in line:
            starts.append(i)
    return starts


# Match the `.slide` opening tag — allowing EXTRA classes (`class="slide foo"`,
# e.g. iframe-embed pages tagged `class="slide embedded-management-page"`). The
# old exact string `'<div class="slide"'` missed multi-class slide divs → frame
# keyed "?" / unliftable. The `(?:\s[^"]*)?` keeps `class="slide-frame"` OUT (a
# `-` follows `slide`, not whitespace or the closing quote). (wudeli inline, 2026-06-02)
_SLIDE_OPEN_RE = re.compile(r'<div\s+class="slide(?:\s[^"]*)?"')


def extract_one(src_lines, frame_start, frame_end):
    """Slice the inner of the slide inside frame_start..frame_end (1-indexed
    inclusive). Returns dict with: key, label, accent, decor, orig_layout,
    lifted, inner_html, image_refs."""
    # Find <div class="slide" within (allowing extra classes via _SLIDE_OPEN_RE)
    slide_open = None
    for i in range(frame_start, frame_end):
        if _SLIDE_OPEN_RE.search(src_lines[i]):
            slide_open = i + 1  # 1-indexed
            break
    if slide_open is None:
        raise ValueError(f"no <div class='slide'> found between lines {frame_start}..{frame_end}")
    # Find the slide close by DIV-DEPTH balance from the slide open — the line
    # whose </div> brings depth back to 0 IS the slide close. The old "2nd
    # </div>-line from the end" heuristic mis-counted whenever the .slide-frame
    # close `</div>` sat on its own line below the .slide close: lift() passes
    # frame_end = (next-frame start − 1) = the frame-close line, so the reverse
    # scan started one line too low, counted the slide-close + the slide's LAST
    # CHILD close as its "two" closes, and stopped early → the slide's final
    # container (e.g. `.stage`) lost its </div> → +1 imbalance → R-DOM frame
    # nesting on lift (qingdao `feishu-product-leadership` repro, 2026-06-01).
    # Depth-balance is position-agnostic (works whether frame_end points at the
    # frame-close line, a trailing blank, or a combined `</div></div>` line).
    # Inline <style>/comments are masked (newlines preserved) so stray `<div`
    # text in co-located CSS can't corrupt the count.
    _frame_text = "".join(src_lines[slide_open - 1:frame_end])
    _blank = lambda m: re.sub(r'[^\n]', ' ', m.group(0))
    _masked = re.sub(r'<style[^>]*>.*?</style>', _blank, _frame_text, flags=re.S)
    _masked = re.sub(r'<!--.*?-->', _blank, _masked, flags=re.S)
    depth = 0
    slide_close = frame_end
    for _off, _ltext in enumerate(_masked.splitlines(keepends=True)):
        depth += len(re.findall(r'<div\b', _ltext)) - len(re.findall(r'</div\s*>', _ltext))
        if depth <= 0:
            slide_close = slide_open + _off   # 1-indexed line holding the .slide close
            break

    # The .slide opening tag may wrap across MULTIPLE lines (attrs on their own
    # lines). Read the full tag — from `<div class="slide"` up to its closing
    # `>` — not just the first line, or attrs that wrapped (data-slide-key /
    # data-screen-label) are missed → key=None → --index shows "?", --key can't
    # find the slide, src_key=None, and (worst) the slide_key never reaches
    # extract_head_slide_rules so the slide's own per-slide CSS is NOT recovered
    # → layout collapses to block flow on lift. (merged-49pages `back-1000stores`
    # repro: 3-line .slide tag → grid dropped → vertical collapse, 2026-06-02.)
    _join = "".join(src_lines[slide_open - 1:frame_end])
    _sm = _SLIDE_OPEN_RE.search(_join)
    _sopen = _sm.start() if _sm else -1
    _sgt = _join.find('>', _sopen) if _sopen != -1 else -1
    opening = _join[_sopen:_sgt + 1] if (_sopen != -1 and _sgt != -1) else src_lines[slide_open - 1]

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
    # Start inner AFTER the (possibly multi-line) opening tag's `>` — otherwise
    # the wrapped attribute lines (data-screen-label / data-slide-key on their
    # own lines) leak into the body as VISIBLE TEXT at the top of the slide.
    # (merged-49pages `back-store-pipeline` tag-attribute leak, 2026-06-02.)
    _body = "".join(src_lines[slide_open - 1:slide_close - 1])
    _bm = _SLIDE_OPEN_RE.search(_body)
    _bgt = _body.find('>', _bm.start()) if _bm else -1
    inner = _body[_bgt + 1:] if _bgt != -1 else "".join(src_lines[slide_open:slide_close - 1])
    return info, inner


def externalize_large_base64(inner, dst_input_dir, slide_key, report):
    """Move oversized inline `data:image/*;base64,…` blobs out of `inner` into
    `input/` files and rewrite every reference to the file path. Identical blobs
    (by content hash) share ONE file → N duplicate refs collapse to one. Blobs
    under B64_EXTERNALIZE_MIN_CHARS stay inline. With Pillow available, rasters
    are also downscaled to B64_DOWNSCALE_MAX_EDGE (format preserved); without it,
    raw bytes are written (parse-speed + dedupe win is Pillow-independent).
    Returns the rewritten HTML."""
    # Collect unique oversized blobs (dedupe by exact base64 text).
    blobs = {}  # b64text -> (mime, count)
    for m in _B64_DATA_URI_RE.finditer(inner):
        mime, b64 = m.group(1), m.group(2)
        if len(b64) < B64_EXTERNALIZE_MIN_CHARS:
            continue
        rec = blobs.get(b64)
        blobs[b64] = (mime, (rec[1] + 1) if rec else 1)
    if not blobs:
        return inner

    key_slug = re.sub(r'[^a-zA-Z0-9_-]', '-', slide_key or "slide")
    for b64, (mime, count) in blobs.items():
        try:
            raw = base64.b64decode(b64)
        except Exception:
            continue  # malformed → leave it inline rather than corrupt the page
        ext = _B64_EXT_BY_MIME.get(mime, "png")
        digest = hashlib.md5(b64.encode("ascii", "ignore")).hexdigest()[:8]
        out_bytes, out_ext = raw, ext
        # Optional downscale — never a hard dependency.
        try:
            import io
            from PIL import Image
            im = Image.open(io.BytesIO(raw))
            w, h = im.size
            if max(w, h) > B64_DOWNSCALE_MAX_EDGE:
                scale = B64_DOWNSCALE_MAX_EDGE / max(w, h)
                im = im.resize((max(1, round(w * scale)), max(1, round(h * scale))),
                               Image.LANCZOS)
                buf = io.BytesIO()
                save_fmt = {"jpg": "JPEG"}.get(ext, ext.upper())
                save_kw = {"optimize": True}
                if save_fmt == "JPEG":
                    im = im.convert("RGB")
                    save_kw["quality"] = 88
                im.save(buf, save_fmt, **save_kw)
                out_bytes = buf.getvalue()
        except Exception:
            pass  # Pillow missing or decode failed → keep raw decoded bytes

        fname = f"lift-{key_slug}-{digest}.{out_ext}"
        dst_input_dir.mkdir(parents=True, exist_ok=True)
        (dst_input_dir / fname).write_bytes(out_bytes)
        # Rewrite the whole `data:…;base64,…` token (preserving surrounding
        # quotes/paren) to the local path — all `count` occurrences at once.
        inner = inner.replace(f"data:{mime};base64,{b64}", f"input/{fname}")
        report.setdefault("base64_externalized", []).append(
            {"file": fname, "refs": count,
             "kb": len(out_bytes) // 1024, "from_kb": len(raw) // 1024})
    return inner


def transform(inner, src_input_dir, src_proto_dir, dst_input_dir, dst_proto_dir,
              report, orig_layout=None, slide_key=None, shake=False,
              src_head_css="", page_map=None):
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

    # 2) Strip data-text-id attrs (inert source-bound ids; drop on lift)
    inner = re.sub(r'\s+data-text-id="[^"]*"', '', inner)

    # 3) Rescope CSS: drop [data-layout="..."] filter from slide-key-scoped rules
    inner = re.sub(
        r'(\[data-slide-key="[^"]+"\])\[data-layout="[^"]+"\]',
        r'\1',
        inner
    )

    # 4) Rewrite shared/framework asset paths (assets/shared/* + assets/lark-*,
    #    matching _classify_asset_ref) to skill-relative — in url(), <img src>,
    #    href=, poster= alike (NOT just url()), and for ANY framework file (no
    #    hardcoded filename list). The leading quote/paren guard leaves already-
    #    prefixed refs (preceded by `/`) untouched, so this is idempotent. The
    #    old url()-only + 6-file-list version left `<img src="assets/lark-*">` and
    #    any 7th framework file un-rewritten → 404 in the target (F-76 class).
    inner = re.sub(
        r'''(['"(]\s*)((?:assets/shared/|assets/lark-)[^'")\s]*)''',
        lambda m: f"{m.group(1)}{SKILL_PREFIX}{m.group(2)}",
        inner)

    # 5) Auto-copy input/<file> references + leave path local. Scan EVERY asset
    #    syntax (<img>/<source>/<video>/<iframe>/url()) via the SAME patterns the
    #    F-45 report uses — NOT just CSS url() — else `<img src="input/…">` assets
    #    silently fail to carry (broken images on lift) while the report still
    #    claims them "carried". (F-76)
    _input_seen = set()

    def _carry_input_refs(_html):
        # Copy every `input/<file>` ref in _html (any asset syntax) into the
        # target input/, de-duped via _input_seen. Factored out so it can run
        # AGAIN after the CSS-injection steps below introduce more refs (F-376).
        for _pat in _ASSET_REF_PATTERNS:
            for _m in _pat.finditer(_html):
                _url = _m.group(1).strip()
                if _classify_asset_ref(_url) != "input" or _url in _input_seen:
                    continue
                _input_seen.add(_url)
                fname = _url.split("?", 1)[0].split("#", 1)[0].lstrip("./")[len("input/"):]
                if not fname:
                    continue
                src = src_input_dir / fname
                dst = dst_input_dir / fname
                if src.is_file():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    if not dst.exists() or src.stat().st_mtime > dst.stat().st_mtime:
                        shutil.copy2(src, dst)
                    report.setdefault("input_copied", []).append(fname)
                else:
                    report.setdefault("input_missing", []).append(fname)
    _carry_input_refs(inner)

    # 5b) F-84: self-contain `../input/<file>` refs. A source slide may point a
    #     content asset (product photo etc.) at `../input/foo.png`, which in the
    #     source run resolves to the RUN-LEVEL `input/` (a sibling of `output/`,
    #     OUTSIDE it). Carried verbatim, that file lands outside the target's
    #     `output/` too → it 404s the moment `output/` is moved/zipped/delivered
    #     or the run-level `input/` is cleaned. Copy it INTO the target's
    #     `output/input/` and rewrite the ref to the output-internal `input/foo.png`
    #     so the lifted slide is self-contained under `output/`. Scan EVERY asset
    #     syntax (<img>/<source>/<video>/<iframe>/url()) via the F-45 patterns.
    #     Source resolution: `../input/foo.png` is relative to the source `output/`
    #     (= src_input_dir.parent), i.e. the run-level `input/`
    #     (src_input_dir.parent.parent / "input"); also fall back to the source's
    #     own `output/input/` (= src_input_dir) — both may hold the file.
    #     SCOPE: only a single leading `../` + `input/` matches; framework/shared
    #     linked refs (`../../../skills/...`) never match → left untouched (F-84).
    _src_output_dir = src_input_dir.parent
    _src_run_input = _src_output_dir.parent / "input"
    _rel_seen = {}
    for _pat in _ASSET_REF_PATTERNS:
        for _m in _pat.finditer(inner):
            _url = _m.group(1).strip()
            _rm = _REL_INPUT_RE.match(_url)
            if not _rm or _url in _rel_seen:
                continue
            _fname = _rm.group("file")
            # Resolve from run-level input/ first (the `../input` target), then
            # the source output/input/ fallback. Skip if neither has it.
            _src = None
            for _cand in (_src_run_input / _fname, src_input_dir / _fname):
                if _cand.is_file():
                    _src = _cand
                    break
            if _src is None:
                _rel_seen[_url] = None
                report.setdefault("rel_input_missing", []).append(_url)
                continue
            _dst = dst_input_dir / _fname
            _dst.parent.mkdir(parents=True, exist_ok=True)
            # Idempotent: copy only if absent or the source is newer.
            if not _dst.exists() or _src.stat().st_mtime > _dst.stat().st_mtime:
                shutil.copy2(_src, _dst)
            _rel_seen[_url] = f"input/{_fname}"
            report.setdefault("rel_input_copied", []).append(_fname)
    # Rewrite each carried `../input/...` ref to its output-internal form. Replace
    # the exact as-written URL token (longest first, so `../input/a` can't clobber
    # a longer match) so we only touch the resolved refs, never partial overlaps.
    for _old_url in sorted((u for u, v in _rel_seen.items() if v), key=len, reverse=True):
        inner = inner.replace(_old_url, _rel_seen[_old_url])

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

    # 5.55) Recover source HEAD per-slide rules for this slide (--shake). The
    # page-anim pattern writes `.slide[data-slide-key=K] .x{…}` / `[data-page=N]…`
    # into a head <style>; those aren't in the slide DOM, so without this they're
    # lost on lift. Recover + rewrite `[data-page=N]`→`[data-slide-key=K]` so OLD
    # decks lift clean WITHOUT the migrate codemod. (Keyframes pulled by 5.6.)
    if shake and src_head_css and slide_key:
        head_rules = extract_head_slide_rules(src_head_css, slide_key, page_map or {})
        # Recovered rules may be scoped `[data-slide-key=K][data-layout=X]` (the
        # inline/render-deck co-location pattern). The lifted slide renders as
        # `data-layout="raw"`, so a `[data-layout="X"]` filter would NEVER match →
        # DEAD rule (R-VIS-DEAD-RULE), layout silently lost. Drop it — same rescope
        # step 3 applies to the slide's own inner CSS (which runs before this
        # recovery, so these head rules missed it). (wudeli inline, 2026-06-02)
        head_rules = re.sub(
            r'(\[data-slide-key="[^"]+"\])\[data-layout="[^"]+"\]', r'\1', head_rules)
        if head_rules:
            inner = (
                '<style>\n/* AUTO-RECOVERED source-head per-slide CSS '
                '(lift-slides.py --shake · page-anim pattern) */\n'
                + head_rules + '\n</style>\n' + inner
            )
            report.setdefault("head_css_recovered", []).append(slide_key)

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

    # 5.62) F-376: re-carry input/ assets introduced by the CSS-recovery steps
    #    above. Step 5's carry ran on the RAW inner — but 5.5 (inline framework)
    #    and especially 5.55 (recover source-head per-slide rules) INJECT CSS that
    #    can reference NEW `url('input/…')` files step 5 never saw. The classic
    #    miss: a page-anim `[data-page=N] .photo{background:url(input/x.jpg)}` head
    #    rule recovers its CSS but its image file is left behind → broken background
    #    on lift (the user must hand-copy it). Re-scan the assembled inner now,
    #    BEFORE 5.7 (base64-externalize synthesizes input/ refs that resolve to dst,
    #    not src, and would log false "missing"). Idempotent via _input_seen. (F-76 class)
    _carry_input_refs(inner)

    # 5.63) F-377: prune DEAD rules from the 5.5 AUTO-INLINED framework block.
    #    `--shake` is over-inclusive by design — it inlines the slide's WHOLE
    #    `[data-layout=X]` ruleset, but a slide using a bespoke body (e.g. a
    #    photo-grid under content-2col) uses none of `.grid/.col-text/.col-visual`
    #    → those rescoped rules match zero elements → R-VIS-DEAD-RULE noise + dead
    #    weight in the inline <style>. Drop a rule ONLY when every DESCENDANT class
    #    it names is absent from this slide's markup (a sufficient proof of
    #    deadness); rules naming any present/wrapper class, or pure scope/element
    #    rules, are kept. Touches only the AUTO-INLINED block, never the slide's
    #    own recovered/author CSS.
    if shake and slide_key:
        inner = _prune_dead_inlined_layout_css(inner, slide_key)

    # 5.65) Protect the present-mode fit-scale (F-332). 5.55/5.6 can recover a
    # source page-entrance animation onto the `.slide` ROOT whose keyframes set
    # `transform` (the framework's fit-scale carrier). With fill-mode `both` the
    # root freezes at the keyframe scale, overriding `scale(var(--fs-scale))` →
    # the slide renders unscaled and overflows at non-16:9 viewports. Strip
    # `transform` from those root-applied keyframes (fade/other props survive).
    if shake:
        inner = _descale_root_animation_keyframes(inner, slide_key, report)

    # 5.7) Externalize oversized inline base64 images. --shake's head-CSS
    # recovery (5.55) and source markup can carry MB-scale `data:…;base64,…`
    # blobs (often duplicated), inflating the slide to 10-20 MB → every later
    # render/validate re-parses the bloat → the lift FEELS slow. Move big blobs
    # to deduped `input/` files (Pillow downscales when present). Small blobs
    # stay inline. Runs AFTER all CSS-injection steps so it catches both sources.
    inner = externalize_large_base64(inner, dst_input_dir, slide_key, report)

    # 6) Auto-copy prototypes/ iframe bodies — BOTH a subdir (prototypes/<slug>/…)
    #    AND a direct file (prototypes/<demo>.html). The old regex required a
    #    trailing slash → direct-file iframe bodies were silently dropped (blank
    #    iframe on lift), same class as the deck-cli paste bug. (2026-06-02)
    for seg in sorted(set(re.findall(
            r'''(?:src|href)=['"](?:\./)?prototypes/([^/'"]+)''', inner))):
        src = src_proto_dir / seg
        dst = dst_proto_dir / seg
        if src.is_dir():
            if not dst.exists():
                shutil.copytree(src, dst)
            report.setdefault("proto_copied", []).append(seg + "/")
        elif src.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            if not dst.exists() or src.stat().st_mtime > dst.stat().st_mtime:
                shutil.copy2(src, dst)
            report.setdefault("proto_copied", []).append(seg)
        else:
            report.setdefault("proto_missing", []).append(seg)

    # 6b) Copy OTHER deck-local refs the standard buckets miss — e.g. a foreign
    #     deck's iframe body at a non-standard path (assets/custom/<demo>/x.html).
    #     scan_asset_refs buckets these "other" (the silent-break risk) and nothing
    #     copied them → blank iframe / 404 on lift. Copy preserving the deck-
    #     relative path; an iframe/demo .html in a subfolder brings its whole
    #     folder (so the demo's own deps come too). (B#43 jay-xhs-review, 2026-06-02)
    src_root, dst_root = src_input_dir.parent, dst_input_dir.parent
    for _r in scan_asset_refs(inner, src_root):
        if _r["kind"] != "other" or not _r.get("exists"):
            continue
        rel = _strip_leading_dotslash(
            _r["url"].split("?", 1)[0].split("#", 1)[0])
        if not rel or rel.startswith("/") or rel.startswith("../") or "/../" in rel:
            continue
        if rel.lower().endswith((".html", ".htm")) and "/" in rel:
            sub = rel.rsplit("/", 1)[0]
            if not (dst_root / sub).exists() and (src_root / sub).is_dir():
                shutil.copytree(src_root / sub, dst_root / sub)
            report.setdefault("local_copied", []).append(sub + "/")
        elif (src_root / rel).is_file():
            d = dst_root / rel
            d.parent.mkdir(parents=True, exist_ok=True)
            if not d.exists() or (src_root / rel).stat().st_mtime > d.stat().st_mtime:
                shutil.copy2(src_root / rel, d)
            report.setdefault("local_copied", []).append(rel)

    # 6c) Modernize retired framework CSS vars (framework drift) — see
    #     _RETIRED_VAR_MAP. var(--undefined) silently kills the whole declaration
    #     (a `font:` shorthand → 16px fallback) → R-CSSVAR render-fail on lift.
    for _old, _new in _RETIRED_VAR_MAP.items():
        if f"var({_old})" in inner:
            inner = inner.replace(f"var({_old})", f"var({_new})")
            report.setdefault("retired_vars_mapped", []).append(f"{_old}→{_new}")

    # F-250: deref inlined `var(--fs-asset-X)` → `url("assets/<file>")` so the
    # background image actually loads in the lifted (data.html-inline) slide.
    inner = _deref_asset_vars(inner)

    # F-252: a lifted page using `<img>` for content photos/avatars FAILS UI1 on
    # render (every <img> in body is flagged). Surface it at LIFT time with the
    # fix, not as a render-time wall. Skip imgs already vouched by UI1 escapes.
    content_imgs = [m for m in re.findall(r'<img\b[^>]*>', inner)
                    if 'data-ui-screenshot' not in m and 'data-decor' not in m]
    if content_imgs:
        report["content_imgs"] = len(content_imgs)

    return inner


def lift(src_html_path, frame_indices, dst_deck_json, output_dir=None, shake=False,
         force=False, replace_index=None, keep_title=False):
    src_html_path = Path(src_html_path).resolve()
    dst_deck_json = Path(dst_deck_json).resolve()
    output_dir = Path(output_dir).resolve() if output_dir else dst_deck_json.parent

    # Fail fast on a bad DEST path BEFORE the expensive source read below. A
    # RELATIVE dst under the symlinked skill root (e.g. CWD
    # ~/.claude/skills/feishu-deck-h5 → real .../Github/feishu-deck-h5/skills/
    # feishu-deck-h5) resolves to a non-existent runs/ that does not match where
    # new-run.sh actually created the run — the write then dies with a cryptic
    # FileNotFoundError AFTER parsing the whole (possibly 100s-of-MB) source.
    # We never auto-create the parent: a missing parent means a wrong path, not
    # an intent to scatter a run somewhere new. Pass the ABSOLUTE run path that
    # new-run.sh printed.
    if not dst_deck_json.parent.is_dir():
        print(
            f"\n✗ DEST parent dir does not exist: {dst_deck_json.parent}\n"
            f"   You likely passed a RELATIVE path under the symlinked skill root.\n"
            f"   Re-run with the ABSOLUTE run path new-run.sh printed, e.g.\n"
            f"   .../runs/<ts>-<slug>/output/deck.json (and the same dir as OUTPUT_DIR).",
            file=sys.stderr)
        sys.exit(3)

    src_dir = src_html_path.parent
    src_input_dir = src_dir / "input"
    src_proto_dir = src_dir / "prototypes"
    dst_input_dir = output_dir / "input"
    dst_proto_dir = output_dir / "prototypes"

    src_lines = src_html_path.read_text(encoding="utf-8").splitlines(keepends=True)
    starts = find_frame_lines(src_lines)
    # Source author head/deck CSS (non-framework <style> blocks) + data-page→key
    # map — used by --shake to recover the page-anim head pattern on lift.
    full_src_html = "".join(src_lines)
    src_head_css = _source_author_css(full_src_html) if shake else ""
    page_map = _page_to_key(full_src_html) if shake else {}
    src_stem = src_html_path.parent.name.replace(" ", "")  # e.g. "merged-49pages 2" → "merged-49pages2"

    # Optimistic lock (F-53): record dst mtime at read time so we can refuse to
    # silently clobber a concurrent edit on write-back (mirrors deck-cli.py F-48).
    if dst_deck_json.exists():
        dst_mtime = dst_deck_json.stat().st_mtime
        deck = json.loads(dst_deck_json.read_text(encoding="utf-8"))
    else:
        dst_mtime = None  # new file — nothing to clobber
        # F-251: seed deck.title so the FIRST render of a freshly-lifted NEW deck
        # doesn't fail schema validation (deck.title is required). Prefer the
        # source deck's <title>; fall back to the source folder name. The human
        # renames it later — an un-renderable deck.json is the worse default.
        seed_title = _source_title(full_src_html) or src_stem or "未命名 deck"
        deck = {"version": "1.0", "deck": {"title": seed_title}, "slides": []}

    print(f"source : {src_html_path}")
    print(f"frames : {len(starts)} total in source; lifting {frame_indices}")
    print(f"target : {dst_deck_json}")
    print(f"output : {output_dir}")
    print()

    appended = 0
    existing_keys = {s.get("key") for s in deck["slides"] if s.get("key")}
    # F-378 --replace: must point at an existing slot (1-based, = the deck page #).
    if replace_index is not None and not (1 <= replace_index <= len(deck["slides"])):
        print(f"\n✗ --replace {replace_index} out of range — target deck has "
              f"{len(deck['slides'])} slide(s)", file=sys.stderr)
        sys.exit(6)
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
        # F-45: scan asset refs on the PRE-transform inner (raw source paths, so
        # `assets/shared/` is still classifiable as framework before the rewrite
        # turns it into a skill-relative `../../../` path). Informational only.
        asset_refs = scan_asset_refs(inner, src_dir)
        inner = transform(inner, src_input_dir, src_proto_dir,
                          dst_input_dir, dst_proto_dir, report,
                          orig_layout=info.get("orig_layout"),
                          slide_key=info.get("key"),
                          shake=shake, src_head_css=src_head_css,
                          page_map=page_map)
        # Verify no nested .slide
        if '<div class="slide"' in inner:
            print(f"  ⚠ frame {one_indexed} ({info['key']}): nested .slide remains in inner — "
                  f"check frame boundary")
        # Placement key/label: REPLACE an existing slot in place (F-378) vs the
        # default APPEND. Replace keeps the TARGET slot's identity (key +
        # screen_label) and, with --keep-title, its visible title — only the body
        # is swapped in from the source frame.
        if replace_index is not None:
            tgt = deck["slides"][replace_index - 1]
            key = tgt.get("key") or info["key"]
            label = tgt.get("screen_label", info["label"])
            # Rescope the lifted body's per-slide CSS from the SOURCE key to the
            # TARGET slot's key so it matches the unchanged wrapper (F-255 path).
            inner = _rekey_inner_css(inner, info["key"], key)
            if keep_title:
                tgt_title = _slide_visible_title(tgt.get("data", {}).get("html", ""))
                if not tgt_title:
                    print(f"    ⚠ --keep-title: target slot #{replace_index} has no "
                          f"visible title — source title kept")
                else:
                    inner, _swapped = _swap_slide_title(inner, tgt_title)
                    if _swapped:
                        print(f"    ↻ kept target title: {tgt_title!r}")
                    else:
                        print(f"    ⚠ --keep-title: no title element in lifted body — "
                              f"source title kept (target wanted {tgt_title!r})")
        else:
            # De-collide the lifted key against the destination deck AND other
            # frames lifted in this same run. The source key was previously used
            # verbatim → a collision produced a deck.json that render --strict
            # rejects (R-KEY) with no rollback. render-deck sets data-slide-key from
            # this entry key on the wrapper and `inner` carries no .slide of its own
            # (checked above), so renaming the entry key suffices. Provenance below
            # keeps the SOURCE key.
            key = info["key"]
            if key in existing_keys:
                base, j = key, 2
                while f"{base}-{j}" in existing_keys:
                    j += 1
                key = f"{base}-{j}"
                print(f"    key collision: '{info['key']}' already in target → renamed '{key}'")
            existing_keys.add(key)
            label = info["label"]
            # F-255: a de-collided key must follow into the slide's inlined per-slide
            # CSS (`data.html` carries a <style> block transform() scoped to the
            # ORIGINAL key); without this the entry's key is `-2` while its embedded
            # selectors still point at the bare key → unstyled slide, dead @keyframes.
            inner = _rekey_inner_css(inner, info["key"], key)
        entry = {
            "key": key,
            "layout": "raw",
            "screen_label": label,
            "lifted": f"{src_stem}#{info['key']}",
            # F-70: structured provenance so heal/re-lift can return to the exact
            # source slide DETERMINISTICALLY (no class-signature reverse-guessing
            # / hash-screenshot mis-targeting). The free-text `lifted` ref above
            # stays for the validator's downgrade contract; `lift_origin` is the
            # machine-readable counterpart. `lifted_at` is intentionally null —
            # we do NOT call datetime.now() (it would break workflow determinism);
            # the caller fills it in if/when a timestamp is wanted.
            "lift_origin": {
                "src_deck": src_stem,
                "src_path": str(src_html_path),
                "src_key": info["key"],
                "src_index": one_indexed,
                "lifted_at": None,
                # F-287 (injection-surface provenance): the lifted page's markup
                # comes from a FOREIGN deck — arbitrary inline <script> / on*
                # handlers can ride along and, via slide-library ingest, spread
                # cross-deck. Mark the origin untrusted so downstream
                # (validator's R-FOREIGN-SCRIPT, publish, ingest) knows this
                # content is from an external source and must be sanitized.
                "untrusted": True,
            },
            "data": {"html": inner},
        }
        if info["accent"]:
            entry["accent"] = info["accent"]
        if info["decor"]:
            # F-308-fix (2026-06-13): data-decor is a space-separated token LIST
            # (e.g. "mix-glow grain" = two decors). Wrapping the whole string in a
            # 1-elem array → decor:["mix-glow grain"], an invalid single enum value
            # that fails validate-deck.py --strict and rolls the whole lift back.
            # Split on whitespace so each token is its own array element.
            entry["decor"] = info["decor"].split()
        if replace_index is not None:
            deck["slides"][replace_index - 1] = entry
        else:
            deck["slides"].append(entry)
        appended += 1
        cp = report.get("input_copied", [])
        miss = report.get("input_missing", [])
        proto = report.get("proto_copied", [])
        print(f"✓ frame {one_indexed:3d} → key={key!r} ({len(inner)} bytes)")
        if cp: print(f"    input/ copied: {cp}")
        if proto: print(f"    prototypes/ copied: {proto}")
        if miss: print(f"    ✗ input/ MISSING in source: {miss}")
        rel_cp = report.get("rel_input_copied", [])
        rel_miss = report.get("rel_input_missing", [])
        if rel_cp: print(f"    ../input/ self-contained → output/input/ (F-84): {rel_cp}")
        if rel_miss: print(f"    ✗ ../input/ MISSING in source (left as-is): {rel_miss}")
        inlined = report.get("inlined_layout_css", [])
        if inlined: print(f"    auto-inlined framework CSS for: {inlined}")
        rec = report.get("head_css_recovered", [])
        if rec: print(f"    recovered source-head per-slide CSS for: {rec}")
        kf = report.get("keyframes_pulled", [])
        if kf: print(f"    pulled @keyframes from source head: {kf}")
        ext = report.get("base64_externalized", [])
        for e in ext:
            saved = (f", downscaled {e['from_kb']}→{e['kb']} KB"
                     if e['kb'] < e['from_kb'] else f", {e['kb']} KB")
            print(f"    externalized inline base64 → input/{e['file']} "
                  f"({e['refs']}× ref{saved})")
        hint = report.get("shake_hint", [])
        if hint:
            print(f"    ⓘ layout {hint} has framework CSS that won't survive "
                  f"lift-to-raw — re-run with --shake to inline it")
        nimg = report.get("content_imgs")
        if nimg:
            print(f"    ⚠ {nimg} content <img> → will FAIL UI1 on render. Convert to "
                  f"`<div style=\"background-image:url(...);background-size:cover\">` "
                  f"(photos/avatars, per brand rule), or add data-ui-screenshot if "
                  f"intentionally a screenshot.")
        # F-45: informational asset-reference report. Surface what this page
        # references so a human can decide to swap/remove — never silent.
        if asset_refs:
            # "carried" = actually copied by transform (input/ + prototypes/).
            # `other`-kind refs (sibling .html, relative ../paths) resolve in the
            # source but are NOT auto-copied — don't claim they're carried (F-76).
            # `other`-kind refs that step 6b copied (foreign-deck iframe bodies /
            # non-standard local paths) are now CARRIED, not stranded.
            _local_done = set(report.get("local_copied", []))

            def _carried_by_6b(url):
                rel = url.split("?", 1)[0].split("#", 1)[0].lstrip("./")
                return rel in _local_done or (
                    "/" in rel and (rel.rsplit("/", 1)[0] + "/") in _local_done)

            carried = [r for r in asset_refs
                       if r["exists"] is True and (
                           r["kind"] in ("input", "prototype")
                           or (r["kind"] == "other" and _carried_by_6b(r["url"])))]
            other_present = [r for r in asset_refs
                             if r["exists"] is True and r["kind"] == "other"
                             and not _carried_by_6b(r["url"])]
            # clientlogo refs get their own line (with present/missing state), so
            # exclude them from the generic missing bucket to avoid double-listing.
            missing = [r for r in asset_refs
                       if r["exists"] is False and r["kind"] != "clientlogo"]
            logos = [r for r in asset_refs if r["kind"] == "clientlogo"]
            fw = [r for r in asset_refs if r["kind"] == "framework"]
            print(f"    ── asset refs ({len(asset_refs)}) ──")
            if carried:
                print(f"    ✓ present (carried): "
                      f"{[r['url'] for r in carried]}")
            if other_present:
                print(f"    ⚠ present in source but NOT auto-copied (relink/verify): "
                      f"{[r['url'] for r in other_present]}")
            if fw:
                print(f"    ✓ framework/shared (resolve in skill): "
                      f"{[r['url'] for r in fw]}")
            if missing:
                print(f"    ✗ SOURCE FILE MISSING (page may render blank/broken): "
                      f"{[r['url'] for r in missing]}")
            if logos:
                state = ["(file present)" if r["exists"] else "(file MISSING)"
                         for r in logos]
                pairs = [f"{r['url']} {s}" for r, s in zip(logos, state)]
                print(f"    ⚠ BRAND-specific clientlogo — new customer likely "
                      f"needs to swap/remove: {pairs}")

    # Nothing lifted (every requested frame out of range / failed extraction):
    # do NOT rewrite deck.json and exit non-zero, so a caller can't mistake a
    # no-op for a successful lift.
    if appended == 0:
        print("\n✗ no slides lifted — destination deck.json left unchanged",
              file=sys.stderr)
        sys.exit(2)

    # Optimistic-lock check (F-53): if dst changed on disk since we read it,
    # another process wrote it — refuse so we don't silently clobber that edit.
    if (dst_mtime is not None and not force and dst_deck_json.exists()
            and abs(dst_deck_json.stat().st_mtime - dst_mtime) > 1e-6):
        print(f"\n✗ {dst_deck_json.name} changed on disk since read "
              f"(concurrent edit by another process); re-read & retry, or --force",
              file=sys.stderr)
        sys.exit(4)
    # Concurrent-CREATE guard (lift-5): the pre-existing-file lock above only
    # fires when the file existed at read time (dst_mtime is not None). When we
    # read NO deck.json (dst_mtime is None) we seeded a fresh `deck` from scratch;
    # if another process created the file in the interim, writing now would blow
    # away that brand-new deck. Refuse (the seeded deck has only the just-lifted
    # slides, so this is a clobber, not a merge) unless --force.
    if dst_mtime is None and not force and dst_deck_json.exists():
        print(f"\n✗ {dst_deck_json.name} was created on disk since read "
              f"(concurrent create by another process); re-read & retry, or --force",
              file=sys.stderr)
        sys.exit(4)

    # F-281b (老 F-124/F-75): write-after-validate + rollback. Mirrors
    # deck-cli.write_deck_with_validation — we write the dst deck.json then
    # re-run `validate-deck.py <dst> --strict`; if it fails we restore the
    # PRE-write bytes and exit non-zero. Without this, a lift that produced a
    # schema-invalid deck.json (e.g. a residual R-KEY dup, a malformed entry)
    # landed on disk silently and only blew up downstream at `render --strict`,
    # AFTER the bad state was already committed. `_prev` is the exact previous
    # content (None for a brand-new file) so the rollback is byte-faithful — no
    # backup turd to clean up. Kept as a local copy of the deck-cli contract
    # rather than an import to avoid the hyphenated-module importlib dance (same
    # rationale as atomic_write_text above).
    _prev = (dst_deck_json.read_text(encoding="utf-8")
             if dst_deck_json.exists() else None)
    atomic_write_text(
        dst_deck_json,
        json.dumps(deck, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    validate_deck = (Path(__file__).resolve().parent.parent
                     / "deck-json" / "validate-deck.py")
    vr = subprocess.run(
        [sys.executable, str(validate_deck), str(dst_deck_json), "--strict"],
        capture_output=True, text=True)
    if vr.returncode != 0:
        # Roll back to the exact pre-write state (delete the file if it was new).
        if _prev is not None:
            atomic_write_text(dst_deck_json, _prev, encoding="utf-8")
            restored = f"restored {dst_deck_json.name} to its pre-lift state"
        else:
            try:
                dst_deck_json.unlink()
            except OSError:
                pass
            restored = f"removed the freshly-created {dst_deck_json.name}"
        print(f"\n✗ post-lift validation FAILED ({validate_deck.name} --strict) — "
              f"rolling back ({restored}).", file=sys.stderr)
        if vr.stdout:
            print(vr.stdout, file=sys.stderr)
        if vr.stderr:
            print(vr.stderr, file=sys.stderr)
        sys.exit(5)

    if replace_index is not None:
        print(f"\n✓ {appended} slide(s) replaced into slot #{replace_index} of "
              f"{dst_deck_json.name} (total {len(deck['slides'])})")
    else:
        print(f"\n✓ {appended} slides appended to {dst_deck_json.name} "
              f"(total {len(deck['slides'])})")
    print(f"✓ post-lift validation passed ({validate_deck.name} --strict)")
    print(f"Now run: python3 deck-json/render-deck.py {dst_deck_json} {output_dir}/ --visual")


def build_manifest(src_html_path):
    """Stream a source index.html into a per-frame manifest
    [{frame_index, key, layout, label, bytes}] — without loading the body into a
    caller's context. Lets a lift pick a slide by semantic key from a small
    table for FOREIGN decks that have no slide-index.json sidecar (LIFT-
    ARCHITECTURE L4)."""
    src_html_path = Path(src_html_path).resolve()
    src_lines = src_html_path.read_text(encoding="utf-8").splitlines(keepends=True)
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


# ── F-80: lift straight into a legacy index.html target (no deck.json) ────────
# The deck.json path (lift()) is the native route, but OLD/hand-authored decks
# have NO deck.json — index.html IS the source. Before this, lifting a page into
# such a target was ~8 hand steps (extract frame / shake CSS / copy assets / wrap
# / renumber / div-balance splice / backup / validate). --to-html chains them
# into ONE command, reusing extract_one + transform (same as the deck.json path)
# and the div-balance splice that proved correct on the everbright/kangshifu lift
# (2026-06-02). Key contract (F-82): a raw slide's `inner` has NO `.slide`
# wrapper (render-deck adds it); so we re-wrap here exactly as render-deck does.

def _strip_label_number(label):
    """Drop a leading '16 ' / '04-A ' chapter number from a screen_label, leaving
    the descriptive name. Mirrors render-deck._canonical_screen_label's strip."""
    if not label:
        return ""
    return re.sub(r"^\s*\d[\w\-]*\s+", "", label).strip()


def _existing_html_keys(html_text):
    """Set of data-slide-key values already present in a rendered index.html."""
    return set(re.findall(r'data-slide-key="([^"]+)"', html_text))


def _rekey_inner_css(inner, old_key, new_key):
    """F-255: follow a de-collided key into the co-located <style> block.

    When a lifted page's key collides with the target and gets renamed
    (`KEY` → `KEY-2`), `transform()` has ALREADY inlined that page's per-slide
    CSS under the ORIGINAL key — the recovered head rules and the F-40-fused
    `[data-page=N]` rewrites are all scoped to `.slide[data-slide-key="KEY"]`.
    The wrapper div gets the NEW key (via `_wrap_frame` / the deck.json entry),
    but those embedded selectors stay on the old key and match NOTHING → the
    slide renders unstyled and its @keyframes never fire. That is the exact
    "lifted page came over garbled, animation gone" failure.

    Rewrite the anchor inside INNER to track the rename. The trailing `"` anchors
    the match so `KEY` is never confused with an already-suffixed `KEY-2`, and
    INNER carries no `.slide` wrapper of its own (asserted by both callers), so
    only style-block selectors are touched — never a real slide's key attribute.
    @keyframes names stay global/shared (identical across the colliding pages,
    same lineage), matching the tool's keyframes-resolve-globally contract."""
    if not old_key or old_key == new_key:
        return inner
    return inner.replace(f'data-slide-key="{old_key}"',
                         f'data-slide-key="{new_key}"')


# ── lift --replace --keep-title helpers (F-378) ────────────────────────────
# A slide's visible title lives in the MARKUP (.title-zh / .title-en / .title /
# h1-h2), never in <style>. _slide_visible_title reads it from the target slot;
# _swap_slide_title writes it into the grafted source body — so a body-swap that
# replaces an existing slot KEEPS that page's own title.
_TITLE_RXS = (
    re.compile(r'(<[^<>]*\bclass="[^"]*\btitle-zh\b[^"]*"[^<>]*>)(.*?)(</[a-zA-Z][\w]*>)', re.S),
    re.compile(r'(<[^<>]*\bclass="[^"]*\btitle-en\b[^"]*"[^<>]*>)(.*?)(</[a-zA-Z][\w]*>)', re.S),
    re.compile(r'(<[^<>]*\bclass="[^"]*\btitle\b[^"]*"[^<>]*>)(.*?)(</[a-zA-Z][\w]*>)', re.S),
    re.compile(r'(<h[12]\b[^<>]*>)(.*?)(</h[12]>)', re.S),
)


def _strip_tags(s):
    return re.sub(r'<[^>]+>', '', s).strip()


def _in_style(text, pos):
    """True if offset `pos` falls inside a <style>…</style> block."""
    return text.rfind('<style', 0, pos) > text.rfind('</style>', 0, pos)


def _slide_visible_title(html):
    """First visible title TEXT in a slide's data.html (markup only, not CSS)."""
    if not html:
        return ""
    for rx in _TITLE_RXS:
        for m in rx.finditer(html):
            if _in_style(html, m.start()):
                continue
            txt = _strip_tags(m.group(2))
            if txt:
                return txt
    return ""


def _swap_slide_title(inner, new_text):
    """Replace the FIRST visible title element's text with new_text (markup
    only). Returns (new_inner, swapped?)."""
    for rx in _TITLE_RXS:
        for m in rx.finditer(inner):
            if _in_style(inner, m.start()):
                continue
            return (inner[:m.start()] + m.group(1) + new_text + m.group(3)
                    + inner[m.end():], True)
    return inner, False


# ── lift --shake dead-rule prune helper (F-377) ────────────────────────────
# Renderer-injected ancestor classes exist at render time but never appear in a
# slide's data.html — a rule targeting them is NOT dead just because the markup
# lacks the class. Treat them as always-present so the page-bg / wrapper rules
# the AUTO-INLINED block carries are never pruned.
_RENDER_WRAPPER_CLASSES = frozenset(
    {"deck", "slide-frame", "slide", "is-current", "wordmark"})


def _prune_dead_inlined_layout_css(inner, slide_key):
    """Drop rules in the `--shake` AUTO-INLINED framework <style> block whose
    descendant selector targets only classes this slide's markup never uses.
    Conservative: a rule is dropped ONLY if it names >=1 descendant class and
    EVERY such class is absent from the markup (+ wrapper allowlist) — a
    sufficient proof of deadness. Pure scope/element rules and any rule naming a
    present class are kept. Only the AUTO-INLINED block is rewritten; the slide's
    own recovered/author CSS is never touched."""
    if "AUTO-INLINED from framework" not in inner:
        return inner
    markup = re.sub(r'<style\b.*?</style>', '', inner, flags=re.S | re.I)
    present = set(_RENDER_WRAPPER_CLASSES)
    for c in re.findall(r'class="([^"]*)"', markup):
        present.update(c.split())
    # Per-slide scope prefix → stripped so only DESCENDANT classes are weighed.
    scope_re = re.compile(
        r'\.slide(?:\.[\w-]+)*\[data-slide-key="' + re.escape(slide_key)
        + r'"\](?:\[[^\]]*\]|:[\w-]+(?:\([^()]*\))?)*')

    def _sel_dead(sel):
        rest = scope_re.sub(' ', sel)
        classes = re.findall(r'\.([\w-]+)', rest)
        return bool(classes) and all(c not in present for c in classes)

    def _prune(mb):
        css = mb.group(1)
        if "AUTO-INLINED from framework" not in css:
            return mb.group(0)
        out, i = [], 0
        for rm in re.finditer(r'([^{}]+)\{([^{}]*)\}', css):
            out.append(css[i:rm.start()])            # comments / whitespace
            sel_text = re.sub(r'/\*.*?\*/', ' ', rm.group(1), flags=re.S)
            sels = [s.strip() for s in sel_text.split(',') if s.strip()]
            # a grouped rule is dead only if EVERY comma-selector is dead
            if not (sels and all(_sel_dead(s) for s in sels)):
                out.append(rm.group(0))              # keep
            i = rm.end()
        out.append(css[i:])
        return "<style>" + "".join(out) + "</style>"

    return re.sub(r'<style>(.*?)</style>', _prune, inner, flags=re.S)


def _wrap_frame(inner, info, label, key):
    """Wrap a transformed slide INNER (no .slide wrapper) into a complete
    `<div class="slide-frame"><div class="slide" …>INNER</div></div>`, matching
    render-deck's raw wrapper: data-layout = the source's data-layout (so the
    framework's `.slide[data-layout=X]` rules in the target's linked
    feishu-deck.css still engage — same as render-deck's effective_layout =
    _orig_layout)."""
    eff_layout = info.get("orig_layout") or "raw"
    attrs = [f'data-layout="{eff_layout}"']
    if info.get("accent"):
        attrs.append(f'data-accent="{info["accent"]}"')
    if info.get("decor"):
        attrs.append(f'data-decor="{info["decor"]}"')
    attrs.append(f'data-screen-label="{label}"')
    attrs.append(f'data-slide-key="{key}"')
    body = inner if inner.startswith("\n") else "\n" + inner
    body = body if body.endswith("\n") else body + "\n"
    return ('    <div class="slide-frame">\n'
            f'      <div class="slide" {" ".join(attrs)}>{body}'
            '      </div>\n    </div>\n    ')


def _deck_close_offset(text):
    """Char offset of the `</div>` closing `<div class="deck">`, found by
    <div>/</div> balance from the deck open (robust: .deck closes before any body
    <script>, so balance hits 0 there first). None if not found."""
    dopen = text.find('<div class="deck"')
    if dopen == -1:
        return None
    tags = sorted([(m.start(), +1) for m in re.finditer(r'<div\b', text)] +
                  [(m.start(), -1) for m in re.finditer(r'</div>', text)])
    bal = 0
    for pos, delta in tags:
        if pos < dopen:
            continue
        bal += delta
        if bal == 0:
            return pos
    return None


def _splice_into_html(dst_html, frame_block, position="end"):
    """Insert one complete .slide-frame block into a legacy index.html's
    <div class="deck">. position='end' → before .deck close; int N → before the
    Nth existing frame. Writes a .bak first. Returns (n_frames_after, bak_path)."""
    dst = Path(dst_html).resolve()
    t = dst.read_text(encoding="utf-8")
    frame_opens = [m.start() for m in re.finditer(r'<div class="slide-frame"', t)]
    close = _deck_close_offset(t)
    if close is None:
        raise ValueError(f"{dst.name}: could not locate <div class=\"deck\"> close")
    if '<div class="slide-frame"' in t[close:]:
        raise ValueError(f"{dst.name}: .deck-close detection failed (frames after close)")
    if position in ("end", None):
        insert_at = close
    else:
        p = int(position)
        insert_at = frame_opens[p - 1] if 1 <= p <= len(frame_opens) else close
    block = frame_block if frame_block.endswith("\n") else frame_block + "\n"
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    bak = dst.with_name(dst.name + f".bak-pre-lift-{ts}")
    shutil.copy(dst, bak)
    new_t = t[:insert_at] + block + t[insert_at:]
    atomic_write_text(dst, new_t, encoding="utf-8")   # F-269: crash-safe
    return new_t.count('<div class="slide-frame"'), bak


def _validate_after_lift(dst_html, lifted_keys):
    """Run validate.py on the assembled index.html (no deck.json needed) and judge
    THIS lift only (F-68/F-63): R-DOM must be clean + no finding may reference the
    lifted key(s). Legacy targets carry pre-existing findings → the global exit
    code is NOT the signal; the two gates here are."""
    vp = Path(__file__).resolve().parent / "validate.py"
    try:
        r = subprocess.run([sys.executable, str(vp), str(dst_html), "--no-visual"],
                           capture_output=True, text=True)
    except Exception as e:  # noqa: BLE001
        print(f"⚠ validate skipped: {e}")
        return
    out = (r.stdout or "") + (r.stderr or "")
    dom_err = [ln.strip() for ln in out.splitlines() if "R-DOM" in ln and "✗" in ln]
    key_find = [ln.strip() for ln in out.splitlines()
                if any(k in ln for k in lifted_keys)]
    if dom_err:
        print("✗ R-DOM STRUCTURAL ERROR — the lift broke the DOM:")
        for ln in dom_err:
            print("   " + ln)
    else:
        print("✓ R-DOM clean (frame structure intact)")
    if key_find:
        print(f"⚠ {len(key_find)} finding(s) reference the lifted key(s) (the page's own — review):")
        for ln in key_find[:8]:
            print("   " + ln)
    else:
        print("✓ no validator finding references the lifted key(s)")
    print(f"  (validate.py exit {r.returncode}; legacy targets carry pre-existing findings — "
          f"expected. The two gates above are what matter for THIS lift.)")


def lift_to_html(src_html_path, frame_indices, dst_html, shake=False,
                 position="end", run_validate=True):
    """Lift slides from a source deck's index.html straight into a legacy target
    index.html (no deck.json). Per frame: extract_one → transform (asset-copy +
    optional tree-shake, reused from lift()) → _wrap_frame → de-collide key →
    div-balance splice before .deck close. Then validate (R-DOM + new-key gate)."""
    src_html_path = Path(src_html_path).resolve()
    dst_html = Path(dst_html).resolve()
    if not dst_html.exists():
        print(f"✗ target {dst_html} does not exist — --to-html needs an existing index.html",
              file=sys.stderr)
        sys.exit(2)

    src_dir = src_html_path.parent
    src_input_dir, src_proto_dir = src_dir / "input", src_dir / "prototypes"
    out_dir = dst_html.parent
    dst_input_dir, dst_proto_dir = out_dir / "input", out_dir / "prototypes"

    src_lines = src_html_path.read_text(encoding="utf-8").splitlines(keepends=True)
    starts = find_frame_lines(src_lines)
    full_src = "".join(src_lines)
    src_head_css = _source_author_css(full_src) if shake else ""
    page_map = _page_to_key(full_src) if shake else {}

    print(f"source : {src_html_path}")
    print(f"target : {dst_html}  (legacy index.html, no deck.json)")
    print(f"frames : {len(starts)} in source; lifting {frame_indices} → position {position}")
    print()

    appended, lifted_keys = 0, []
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
        if not info.get("key"):
            print(f"✗ frame {one_indexed}: source .slide has no data-slide-key "
                  f"(multi-line open tag?) — can't lift safely, skipped")
            continue
        report = {}
        asset_refs = scan_asset_refs(inner, src_dir)
        inner = transform(inner, src_input_dir, src_proto_dir,
                          dst_input_dir, dst_proto_dir, report,
                          orig_layout=info.get("orig_layout"),
                          slide_key=info.get("key"),
                          shake=shake, src_head_css=src_head_css, page_map=page_map)
        if '<div class="slide"' in inner:
            print(f"  ⚠ frame {one_indexed} ({info['key']}): nested .slide remains — check boundary")

        # Re-read target each iteration (keys + frame count change as we splice).
        cur = dst_html.read_text(encoding="utf-8")
        existing = _existing_html_keys(cur)
        key = info["key"]
        if key in existing:
            base, j = key, 2
            while f"{base}-{j}" in existing:
                j += 1
            key = f"{base}-{j}"
            print(f"    key collision: '{info['key']}' → '{key}'")
        # F-255: the de-collided key must follow into the inlined per-slide CSS,
        # else the embedded `.slide[data-slide-key="OLD"]` selectors match nothing
        # → page renders garbled + @keyframes dead. No-op when key was unchanged.
        inner = _rekey_inner_css(inner, info["key"], key)
        n_frames = cur.count('<div class="slide-frame"')
        name = _strip_label_number(info.get("label")) or info["key"]
        label = f"{n_frames + 1:02d} {name}"  # canonical: leading number = frame_index
        frame = _wrap_frame(inner, info, label, key)
        try:
            n_after, bak = _splice_into_html(dst_html, frame, position)
        except ValueError as e:
            print(f"✗ splice failed: {e}", file=sys.stderr)
            sys.exit(3)
        appended += 1
        lifted_keys.append(key)
        print(f"✓ frame {one_indexed:3d} → key={key!r}, label={label!r} "
              f"({len(inner)} bytes) · target now {n_after} frames · bak {bak.name}")
        for rk, rl in (("input_copied", "input/ copied"),
                       ("proto_copied", "prototypes/ copied"),
                       ("input_missing", "✗ input/ MISSING in source"),
                       ("rel_input_copied",
                        "../input/ self-contained → output/input/ (F-84)"),
                       ("rel_input_missing",
                        "✗ ../input/ MISSING in source (left as-is)")):
            if report.get(rk):
                print(f"    {rl}: {report[rk]}")
        if report.get("keyframes_pulled"):
            print(f"    pulled @keyframes from source head: {report['keyframes_pulled']}")
        if report.get("head_css_recovered"):
            print(f"    recovered source-head per-slide CSS for: {report['head_css_recovered']}")
        if report.get("shake_hint"):
            print(f"    ⓘ layout {report['shake_hint']} has framework CSS that may not survive "
                  f"lift-to-raw if the target lacks it — re-run with --shake to inline")
        # F-83: target-framework layout coverage. The lifted frame keeps its
        # orig_layout on the wrapper (see _wrap_frame), so the TARGET's bundled
        # feishu-deck.css is what styles it. If that sheet is an OLDER snapshot
        # with NO [data-layout=X] block for this page's layout, the page renders
        # unstyled (e.g. iframe-embed → iframe shrinks to a tiny box) UNLESS
        # --shake already inlined the framework rules. Warn LOUDLY rather than
        # auto-shake: --shake is a per-INVOCATION flag (it sets up src_head_css /
        # page_map at the top of this function); selectively shaking one page
        # mid-loop would diverge from that contract and the tool's advisory
        # style. The human re-runs with --shake (consistent, all-pages).
        if not shake and target_lacks_layout_css(dst_html, info.get("orig_layout")):
            print(f"    ⚠⚠ TARGET FRAMEWORK LACKS [data-layout=\"{info.get('orig_layout')}\"] CSS — "
                  f"the target deck's bundled feishu-deck.css is an older snapshot with no rules "
                  f"for this layout. This page WILL render unstyled/broken (e.g. iframe collapses). "
                  f"RE-RUN this lift WITH --shake to inline the framework layout CSS into the slide.")
        carried = [r["url"] for r in asset_refs
                   if r["exists"] and r["kind"] in ("input", "prototype")]
        missing = [r["url"] for r in asset_refs
                   if r["exists"] is False and r["kind"] != "clientlogo"]
        logos = [r["url"] for r in asset_refs if r["kind"] == "clientlogo"]
        if carried:
            print(f"    ✓ assets present (carried): {carried}")
        if missing:
            print(f"    ✗ SOURCE ASSET MISSING (page may render broken): {missing}")
        if logos:
            print(f"    ⚠ BRAND clientlogo — new customer likely needs to swap: {logos}")

    if appended == 0:
        print("\n✗ no slides lifted — target left unchanged", file=sys.stderr)
        sys.exit(2)

    print(f"\n✓ {appended} slide(s) lifted into {dst_html.name}")
    if run_validate:
        _validate_after_lift(dst_html, lifted_keys)
    return appended


# ── F-81: read-only preview — one command, all the lift judgments ─────────────
def cmd_preview(src_html_path, sel, against=None):
    """Read-only judgment for lifting frame `sel` (#N or slide-key) from src.
    Prints a compact JSON verdict (self-contained? CSS inline/head? @keyframes
    closure? asset refs present? key collision vs target?) so the caller decides
    in ONE call instead of hand-grepping 5 things. Writes nothing."""
    src_html_path = Path(src_html_path).resolve()
    rows = build_manifest(src_html_path)
    frame_index = None
    if str(sel).isdigit():
        frame_index = int(sel)
    else:
        for r in rows:
            if r["key"] == sel:
                frame_index = r["frame_index"]
                break
    if not frame_index or frame_index < 1 or frame_index > len(rows):
        print(json.dumps({"error": f"slide not found in source: {sel}"}, ensure_ascii=False))
        return 1
    src_lines = src_html_path.read_text(encoding="utf-8").splitlines(keepends=True)
    starts = find_frame_lines(src_lines)
    fs = starts[frame_index - 1]
    fe = starts[frame_index] - 1 if frame_index < len(starts) else len(src_lines)
    try:
        info, inner = extract_one(src_lines, fs, fe)
    except ValueError as e:
        print(json.dumps({"error": str(e), "frame_index": frame_index}, ensure_ascii=False))
        return 1
    full_src = "".join(src_lines)
    src_dir = src_html_path.parent
    page_map = _page_to_key(full_src)
    # Exclude THIS frame's own lines when scanning for "external head CSS":
    # _source_author_css() returns ALL non-framework <style> bodies (head AND
    # every frame's inline block), so counting this frame's OWN inline <style> as
    # "head CSS" would falsely flag a self-contained page as NOT self-contained.
    non_frame = "".join(src_lines[:fs - 1]) + "".join(src_lines[fe:])
    head_css = _source_author_css(non_frame)
    head_rules = (extract_head_slide_rules(head_css, info.get("key"), page_map)
                  if info.get("key") else "")
    inline_kf = list(_extract_keyframes(inner).keys())
    head_kf = list(_extract_keyframes(head_css).keys())
    ref_anim = sorted(_referenced_anim_names(inner))
    need_shake_kf = [a for a in ref_anim if a not in inline_kf and a in head_kf]
    css_in_inner = "<style" in inner
    css_location = ("inline" if css_in_inner and not head_rules else
                    "head" if head_rules and not css_in_inner else
                    "both" if head_rules and css_in_inner else
                    "none-or-framework-only")
    asset_refs = scan_asset_refs(inner, src_dir)
    self_contained = (css_in_inner and not head_rules and not need_shake_kf
                      and all(r["exists"] in (True, None) for r in asset_refs))
    result = {
        "frame_index": frame_index,
        "key": info.get("key"),
        "orig_layout": info.get("orig_layout"),
        "label": info.get("label"),
        "bytes": len(inner),
        "self_contained": self_contained,
        "css_location": css_location,
        "head_scoped_rules_for_this_key": bool(head_rules),
        "inline_keyframes": inline_kf,
        "referenced_anim_names": ref_anim,
        "keyframes_only_in_head_need_shake": need_shake_kf,
        "asset_refs": asset_refs,
        "recommend_shake": bool(head_rules or need_shake_kf),
    }
    if against:
        atext = Path(against).read_text(encoding="utf-8")
        # F-83: does the TARGET's bundled framework actually have CSS for this
        # page's [data-layout=X]? An OLDER target snapshot may lack it → the
        # lifted page (which keeps orig_layout on its wrapper) renders unstyled
        # unless --shake inlines the framework rules. This is INDEPENDENT of the
        # source-head coupling the rest of cmd_preview inspects, so OR it into
        # recommend_shake (raw is never flagged — it's framework-default styled).
        lacks_layout = target_lacks_layout_css(against, info.get("orig_layout"))
        result["against"] = {
            "target": str(against),
            "target_frames": atext.count('<div class="slide-frame"'),
            "key_collision": info.get("key") in _existing_html_keys(atext),
            "assets_present_in_target": [
                r["url"] for r in asset_refs if r["kind"] == "input"
                and (Path(against).parent / r["url"].lstrip("./")).is_file()
            ],
            "target_lacks_layout_css": lacks_layout,
        }
        if lacks_layout:
            result["against"]["note"] = (
                f"target framework has NO [data-layout=\"{info.get('orig_layout')}\"] "
                f"CSS — this layout's rules are missing in the target deck, so the "
                f"lifted page will render unstyled/broken unless you lift with --shake "
                f"(which inlines the framework layout CSS into the slide itself).")
            result["target_lacks_layout_css"] = True
            result["recommend_shake"] = True
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


# ── F-324: pre-lift WHOLE-SOURCE health scan ─────────────────────────────────
# `--preview` judges ONE slide; `--scan` sweeps the whole source in one read and
# flags every frame whose content is populated at RUNTIME — an iframe demo the
# source injects by JS (src=about:blank / iframe-embed), image-slot/photo-cell
# placeholders with no static image, or a frame the lifter can't even parse.
# deck.json is JS-free, so a raw lift lands all of that EMPTY/broken. Surfacing
# it BEFORE the lift collapses a page-by-page post-lift screenshot+forensics hunt
# into one upfront table (the exact cost this command exists to remove).
_SLOT_CLASSES = r'photo-cell|poster-img|img-slot|image-slot|photo-slot'
# Match the whole opening TAG of a placeholder element, so a div carrying BOTH
# role="img" AND a slot class counts once (not twice) — the printed slot count
# must be the element count.
_PLACEHOLDER_RE = re.compile(
    r'<\w+\b[^>]*?(?:role\s*=\s*["\']img["\']'
    r'|class\s*=\s*["\'][^"\']*\b(?:' + _SLOT_CLASSES + r')\b)[^>]*>',
    re.I)
_IMG_URL_RE = re.compile(r'url\(\s*["\']?(?!data:)[^)"\']*\.(?:jpe?g|png|webp|gif)', re.I)
_ABOUT_BLANK_IFRAME_RE = re.compile(r'<iframe\b[^>]*\bsrc\s*=\s*["\']about:blank', re.I)


def cmd_scan(src_html_path):
    """Read-only whole-source health report: which frames carry runtime/dynamic
    content that a deck.json lift cannot carry. The per-frame head-CSS scan (the
    expensive part) runs ONLY for frames that actually have image-slot
    placeholders, so the sweep stays cheap on big single-file sources."""
    src_html_path = Path(src_html_path).resolve()
    src_lines = src_html_path.read_text(encoding="utf-8").splitlines(keepends=True)
    full_src = "".join(src_lines)
    starts = find_frame_lines(src_lines)
    dirty, clean = [], 0
    for i in range(len(starts)):
        fs = starts[i]
        fe = starts[i + 1] - 1 if i + 1 < len(starts) else len(src_lines)
        try:
            info, inner = extract_one(src_lines, fs, fe)
        except ValueError:
            info, inner = {"key": None, "label": None, "orig_layout": None}, ""
        flags = []
        key = info.get("key")
        if not key:
            flags.append(("unparseable",
                          "lifter can't read this frame's key/layout — a lift by key will skip or "
                          "fail it (run --index to confirm). Re-author or lift its source page."))
        else:
            layout = info.get("orig_layout")
            if layout == "iframe-embed" or _ABOUT_BLANK_IFRAME_RE.search(inner):
                flags.append(("iframe-embed",
                              "iframe demo (src=about:blank / iframe-embed) is populated by the "
                              "source's JS — a lift-to-raw lands it BLANK. Lift it as an "
                              "iframe-embed schema slide (deck.json data.src=prototypes/<demo>.html) "
                              "and carry the prototype, e.g. `deck-cli paste --from <src deck.json> "
                              "--key " + key + "` rather than lift-slides --shake."))
            # Empty image slot = a photo placeholder whose image isn't static in
            # the frame body (no <img>, no url()). Such photos are slot/JS-injected
            # and land empty on lift. We deliberately do NOT exempt frames whose
            # head CSS has a matching photo-slot url(): observed cases (ai-lecture-
            # hall) keep such a rule yet still lift empty (--shake doesn't reliably
            # recover it), so a head exemption produces false-NEGATIVES — and for a
            # pre-lift advisory, over-warning is far cheaper than missing a page
            # that lands blank.
            n_ph = len(_PLACEHOLDER_RE.findall(inner))
            has_img = ("<img" in inner) or bool(_IMG_URL_RE.search(inner))
            if n_ph and not has_img:
                flags.append(("empty-image-slots",
                              f"{n_ph} image-slot placeholder(s) "
                              "(photo-cell/poster-img/role=img) with NO static <img>/url() in the "
                              "frame body — photos here are slot/JS-injected and MAY land EMPTY on "
                              "lift. Verify after rendering; attach real images if blank."))
        if flags:
            dirty.append((i + 1, info, flags))
        else:
            clean += 1

    inline_scripts = [m for m in re.findall(r'<script\b[^>]*>([\s\S]*?)</script>', full_src)
                      if m.strip()]
    total_js = sum(len(s) for s in inline_scripts)

    print(f"SCAN · {src_html_path.name} · {len(starts)} frame(s)")
    if not dirty:
        print("  ✓ all frames lift cleanly (static HTML/CSS/assets).")
    else:
        print(f"  ⚠ {len(dirty)} frame(s) carry DYNAMIC content a deck.json lift cannot carry "
              "(JS-free) — a raw lift lands them empty/broken:")
        for idx, info, flags in dirty:
            print(f"   #{idx:<3} {(info.get('key') or '?'):<30} {info.get('orig_layout') or '?'}")
            for tag, detail in flags:
                print(f"        [{tag}] {detail}")
        print(f"  ✓ {clean} frame(s) lift cleanly (static HTML/CSS/assets).")
    if inline_scripts:
        print(f"  ℹ source has {len(inline_scripts)} inline <script> block(s) (~{total_js/1024:.0f} "
              "KB) outside the framework — any page whose content/charts/images they build at "
              "runtime loses it on lift (deck.json has no JS slot).")
    return 0


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
    ap.add_argument("--scan", action="store_true",
                    help="F-324: read-only WHOLE-SOURCE health report — flag every frame whose "
                         "content is runtime/JS-injected (iframe demo, image-slot placeholders, "
                         "unparseable) and will land EMPTY on a deck.json lift. Run this BEFORE "
                         "lifting to plan special-casing up front. Writes nothing.")
    ap.add_argument("--key",
                    help="comma-separated slide-keys to lift (alternative to positional FRAMES)")
    ap.add_argument("--shake", action="store_true",
                    help="tree-shake: inline framework [data-layout=X] CSS for the slide's "
                         "ACTUAL layout (any of ~15) + RECOVER source-head per-slide rules "
                         "([data-slide-key]/[data-page] page-anim pattern) + pull referenced "
                         "@keyframes. Lets OLD/foreign decks lift CLEAN with no pre-fix codemod. "
                         "Over-inclusive by design.")
    ap.add_argument("--force", action="store_true",
                    help="bypass concurrent-modification (optimistic-lock) check — write "
                         "DEST_DECK_JSON even if it changed on disk since it was read (F-53)")
    ap.add_argument("--preview", action="store_true",
                    help="F-81: read-only. Print a JSON judgment for lifting the selected "
                         "slide (self-contained? CSS inline/head? @keyframes closure? asset "
                         "refs? key collision vs --against?) and exit. Writes nothing.")
    ap.add_argument("--pos", default="end",
                    help="F-80 (--to-html only): insert position — 'end' (default) or a "
                         "1-indexed frame number to insert BEFORE")
    ap.add_argument("--against", default=None,
                    help="--preview only: a target index.html to check key-collision/assets against")
    ap.add_argument("--no-validate", action="store_true",
                    help="--to-html only: skip the post-lift validate.py gate (not recommended)")
    ap.add_argument("--replace", type=int, default=None, metavar="N",
                    help="F-378 (deck.json only): instead of APPENDING, overwrite the body "
                         "of the target deck's existing slide #N (1-based = the deck page "
                         "number) with the single lifted source frame, KEEPING that slot's "
                         "key + screen_label. Requires exactly one frame/key.")
    ap.add_argument("--keep-title", action="store_true",
                    help="F-378 (with --replace): also keep the TARGET slot's visible title "
                         "— only the body content is swapped in from the source frame.")
    # `--key K DEST.json --shake` is the documented/native-lift form. Plain
    # argparse stops collecting the `rest` positional after an optional when
    # `nargs="*"` is involved, so DEST.json can be reported as "unrecognized".
    # Intermixed parsing keeps the legacy positional contract while allowing
    # options before or after DEST.json.
    parse_args = getattr(ap, "parse_intermixed_args", ap.parse_args)
    args = parse_args()

    if args.index:
        print_manifest(args.src_html)
        return 0

    if args.scan:
        return cmd_scan(args.src_html)

    if args.preview:
        rest = list(args.rest)
        if args.key:
            sel = args.key.split(",")[0].strip()
        elif rest:
            sel = rest[0]
        else:
            print("✗ --preview needs a slide: --key K  or  a frame number", file=sys.stderr)
            return 1
        return cmd_preview(args.src_html, sel, against=args.against)

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

    # F-378 --replace / --keep-title validation (deck.json native path only).
    if args.replace is not None or args.keep_title:
        if str(dst).endswith(".html"):
            print("✗ --replace/--keep-title are for the deck.json path, not --to-html",
                  file=sys.stderr)
            return 1
        if args.keep_title and args.replace is None:
            print("✗ --keep-title only applies together with --replace <N>", file=sys.stderr)
            return 1
        if args.replace is not None and len(frames) != 1:
            print(f"✗ --replace overwrites ONE slot — select exactly one frame/key "
                  f"(got {len(frames)})", file=sys.stderr)
            return 1

    # Route by destination type: *.html → splice into a legacy index.html (F-80,
    # no deck.json needed); *.json → the native deck.json path (lift()).
    if str(dst).endswith(".html"):
        lift_to_html(args.src_html, frames, dst, shake=args.shake,
                     position=args.pos, run_validate=not args.no_validate)
    else:
        lift(args.src_html, frames, dst, out, shake=args.shake, force=args.force,
             replace_index=args.replace, keep_title=args.keep_title)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
