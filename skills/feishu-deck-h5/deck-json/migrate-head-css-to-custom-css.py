#!/usr/bin/env python3
"""migrate-head-css-to-custom-css.py — LIFT-ARCHITECTURE L7 codemod.

Sweep a rendered deck's BACK-CATALOG drift: move per-slide CSS that lives in a
head/deck-level `<style>` block (the page-anim anti-pattern — vanishes on
republish, left behind on lift) INTO the matching slide's `custom_css` field in
deck.json, so it co-locates inside .slide and round-trips (LIFT-ARCHITECTURE L2).

This is the migration that lets R-SELF-CONTAINED's head-leak check be promoted
from advisory to error: once a deck is swept, re-rendering regenerates the slide
with the CSS co-located and the head leak gone.

How it maps a head rule → a slide
---------------------------------
- selector contains `[data-slide-key="K"]`  → slide K (direct).
- selector contains `[data-page="N"]`        → slide whose frame carries
  `data-page="N"` in the rendered index.html (read from the actual DOM, NOT
  guessed by order — so a deck whose data-page numbers were hand-edited out of
  order still maps correctly).
- `@keyframes` referenced by a moved rule's `animation:` are pulled along.
- Rules with no per-slide selector, and `@media`/`@supports` wrappers, are
  LEFT IN PLACE and reported — never silently dropped or mis-attributed.

The moved CSS is stored in `custom_css` VERBATIM. At render time the existing
scope_selectors() passes `[data-slide-key=]`-scoped selectors through unchanged,
rewrites `[data-page=N]` to the slide-key scope, and leaves `@keyframes` alone.

Safety
------
- Writes `deck.json.bak-pre-migrate-<ts>` before mutating (destructive-op
  discipline). `--dry-run` reports without writing.
- Idempotent: re-running on a swept + re-rendered deck finds no head leaks → no-op.
- Does NOT edit index.html. Re-render (render-deck.py, or pass --render) to
  regenerate the clean output from the updated deck.json.

F-272 · raw-page inline <style> sweep (page-CSS locus convergence)
-----------------------------------------------------------------
A raw slide's per-page CSS has two possible homes: `slide.custom_css` (the single
source of truth — round-trips with deck.json) OR a `<style>` embedded in its
`data.html` (does NOT round-trip the field, has no budget, can leak cross-page
selectors). By DEFAULT this tool now ALSO sweeps each raw slide's top-level
embedded `<style>` INTO that slide's `custom_css` and strips it from data.html,
so the page converges on the single home (render-time scope_selectors() then
scopes the moved CSS to the slide key). This is the fix R-CSS-INLINE-BUDGET /
R-CSS-CROSS-PAGE point at. `--no-raw-inline` keeps only the legacy head sweep;
`--raw-inline-only` runs ONLY this sweep and needs deck.json alone (no
index.html). A `<style data-source="framework">` is left in place.

Usage
-----
    # both sweeps (head-CSS from index.html + raw inline <style> from deck.json):
    python3 migrate-head-css-to-custom-css.py <out>/index.html <out>/deck.json [--dry-run] [--render]
    # ONLY the F-272 raw inline <style> sweep (deck.json alone):
    python3 migrate-head-css-to-custom-css.py --raw-inline-only <out>/deck.json [--dry-run]

stdlib only. Python 3.10+.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

_FRAME_OPEN = re.compile(r'<div\b[^>]*class="[^"]*\bslide-frame\b[^"]*"[^>]*>')
_DIV_TOKEN = re.compile(r'<div\b[^>]*>|</div>')
# Regions whose contents must NOT be scanned for <div>/</div> depth tokens —
# a `</div>` inside an HTML comment, a <script>, or a <style> body is not a real
# DOM close and would otherwise mis-balance the frame-span depth counter.
_MASKABLE_RE = re.compile(
    r'<!--.*?-->'
    r'|<script\b[^>]*>.*?</script\s*>'
    r'|<style\b[^>]*>.*?</style\s*>',
    re.S | re.I,
)


def _mask_noncode(html: str) -> str:
    """Return `html` with comment / <script> / <style> region INNARDS replaced by
    same-length spaces (offsets preserved) so a stray `</div>` inside them can't
    throw off div-depth counting. Length is preserved so positions stay valid."""
    return _MASKABLE_RE.sub(lambda m: " " * (m.end() - m.start()), html)
_STYLE_RE = re.compile(r'<style(?P<attrs>[^>]*)>(?P<body>.*?)</style>', re.S)
_SK_RE = re.compile(r'\[data-slide-key="([^"]+)"\]')
_DP_RE = re.compile(r'\[data-page="?([\w-]+)"?\]')
_ANIM_KEYWORDS = {
    'none', 'initial', 'inherit', 'unset', 'normal', 'reverse', 'alternate',
    'alternate-reverse', 'infinite', 'paused', 'running', 'forwards',
    'backwards', 'both', 'linear', 'ease', 'ease-in', 'ease-out',
    'ease-in-out', 'step-start', 'step-end',
}


def _frame_spans(html: str):
    # Count <div>/</div> depth over a version of the document where comment /
    # <script> / <style> innards are masked out, so a `</div>` written inside any
    # of those (common in raw slides) can't prematurely close — or fail to close —
    # a slide frame. Masking preserves offsets, so spans stay valid against `html`.
    scan = _mask_noncode(html)
    spans = []
    for fm in _FRAME_OPEN.finditer(scan):
        depth, end = 1, len(html)
        for dm in _DIV_TOKEN.finditer(scan, fm.end()):
            depth += 1 if dm.group(0)[1] != '/' else -1
            if depth == 0:
                end = dm.start()
                break
        spans.append((fm.start(), end))
    return spans


def _page_to_key(html: str) -> dict:
    """Map data-page → data-slide-key by reading each frame's rendered DOM."""
    out = {}
    for fm in _FRAME_OPEN.finditer(html):
        seg = html[fm.start():fm.end() + 1500]
        pm = re.search(r'data-page="?([\w-]+)"?', seg)
        km = re.search(r'data-slide-key="([^"]+)"', seg)
        if pm and km:
            out[pm.group(1)] = km.group(1)
    return out


def _head_blocks(html: str, spans):
    """Yield the body of each non-framework <style> that sits OUTSIDE any slide."""
    def inside(pos):
        return any(a <= pos < b for a, b in spans)
    for m in _STYLE_RE.finditer(html):
        if 'data-source="framework"' in (m.group('attrs') or ''):
            continue
        if inside(m.start()):
            continue
        yield m.group('body')


def _walk_top(css: str):
    """Yield ('rule', selector, full) | ('keyframes', name, full) | ('at', name, full)
    for top-level constructs, brace-matched."""
    i, n = 0, len(css)
    while i < n:
        while i < n and css[i] in ' \t\r\n':
            i += 1
        if i >= n:
            break
        if css[i:i + 2] == '/*':
            j = css.find('*/', i + 2)
            i = (j + 2) if j != -1 else n
            continue
        if css[i] == '@':
            m = re.match(r'@([\w-]+)', css[i:])
            name = m.group(1).lower() if m else ''
            brace = css.find('{', i)
            semi = css.find(';', i)
            if brace == -1 or (semi != -1 and semi < brace):
                end = (semi + 1) if semi != -1 else n
                yield ('at', name, css[i:end])
                i = end
                continue
            depth, k = 1, brace + 1
            while k < n and depth:
                if css[k] == '{':
                    depth += 1
                elif css[k] == '}':
                    depth -= 1
                k += 1
            full = css[i:k]
            if 'keyframes' in name:
                nm = re.match(r'@(?:-webkit-|-moz-)?keyframes\s+([\w-]+)', full)
                yield ('keyframes', nm.group(1) if nm else '', full)
            else:
                yield ('at', name, full)
            i = k
            continue
        brace = css.find('{', i)
        if brace == -1:
            break
        selector = css[i:brace].strip()
        depth, k = 1, brace + 1
        while k < n and depth:
            if css[k] == '{':
                depth += 1
            elif css[k] == '}':
                depth -= 1
            k += 1
        yield ('rule', selector, css[i:k].strip())
        i = k


def _anim_names(text: str) -> set:
    names = set()
    for m in re.finditer(r'animation(?:-name)?\s*:\s*([^;}\n]+)', text):
        for tok in re.split(r'[\s,]+', m.group(1).strip()):
            if re.fullmatch(r'[A-Za-z_][\w-]*', tok) and tok not in _ANIM_KEYWORDS:
                names.add(tok)
    return names


def _target_key(selector: str, page_map: dict):
    m = _SK_RE.search(selector)
    if m:
        return m.group(1)
    m = _DP_RE.search(selector)
    if m:
        return page_map.get(m.group(1))
    return None


def collect(html: str):
    """Return (chunks, orphans, skipped_at): chunks = {slide_key: css_to_move}."""
    spans = _frame_spans(html)
    page_map = _page_to_key(html)
    groups: dict[str, list] = {}
    group_anim: dict[str, set] = {}
    keyframes: dict[str, str] = {}
    orphans: list[str] = []
    skipped_at: list[str] = []

    # Pass 1: harvest @keyframes from EVERY head block, regardless of per-slide
    # selector. Authors routinely put @keyframes in their OWN selector-less
    # <style> block; gating keyframe collection on a per-slide selector (the
    # main loop below) dropped those → a moved rule's `animation: X` lost its
    # keyframe definition after migration → silent dead animation. (#13)
    for block in _head_blocks(html, spans):
        for kind, a, b in _walk_top(block):
            if kind == 'keyframes':
                keyframes[a] = b

    for block in _head_blocks(html, spans):
        # Only blocks that actually target a slide are leaks. A generic/shell
        # <style> (e.g. the R48 re-assertions, present-mode scaling) has no
        # per-slide selector — leave it alone (mirrors R-SELF-CONTAINED).
        if not (_SK_RE.search(block) or _DP_RE.search(block)):
            continue
        for kind, a, b in _walk_top(block):
            if kind == 'keyframes':
                keyframes[a] = b
            elif kind == 'at':
                skipped_at.append(re.sub(r'\s+', ' ', b[:70]))
            else:  # rule
                key = _target_key(a, page_map)
                if key:
                    groups.setdefault(key, []).append(b)
                    group_anim.setdefault(key, set()).update(_anim_names(b))
                else:
                    orphans.append(re.sub(r'\s+', ' ', a[:90]))

    chunks = {}
    for key, rules in groups.items():
        parts = list(rules)
        for name in sorted(group_anim.get(key, ())):
            if name in keyframes:
                parts.append(keyframes[name])
        chunks[key] = "\n".join(parts)
    return chunks, orphans, skipped_at


# ---------------------------------------------------------------------------
# F-272 · raw-page inline <style> → custom_css (page-CSS locus convergence)
# ---------------------------------------------------------------------------
# A raw slide keeps its per-page CSS in one of two homes: slide.custom_css (the
# single source of truth — round-trips with deck.json, co-located inside .slide
# at render) OR a `<style>` embedded in its data.html (does NOT round-trip the
# field, has no budget, can leak cross-page selectors). This sweep moves the
# embedded <style> bodies INTO custom_css and strips them from data.html, so the
# page converges on the single home. R-CSS-INLINE-BUDGET / R-CSS-CROSS-PAGE warn
# about decks that still carry the embedded channel; this is the fix they point
# at. Works on deck.json DIRECTLY (no index.html needed) — render-time
# scope_selectors() then scopes the moved CSS to the slide key.

def collect_raw_inline_styles(deck: dict, keys=None):
    """For every raw slide, pull every top-level `<style>` body out of its
    data.html. Returns (moves, total_styles):
      moves = list of (slide_ref, key, css_to_move, stripped_html, n_styles)
              — slide_ref is the actual slide dict (so the caller can mutate it).
    A `<style data-source="framework">` (shouldn't appear in raw data.html, but
    be safe) is LEFT IN PLACE. data.html with no <style> is skipped.
    `keys` (set|None): restrict to those slide-keys (None = every raw slide) —
    lets deck-cli `consolidate-css --key K` converge a single page."""
    moves = []
    total_styles = 0
    for slide in deck.get("slides", []):
        if slide.get("layout") != "raw":
            continue
        if keys is not None and slide.get("key") not in keys:
            continue
        data = slide.get("data") or {}
        html = data.get("html")
        if not isinstance(html, str) or "<style" not in html.lower():
            continue
        bodies = []
        n_styles = 0
        # Strip matched <style>…</style> blocks, collecting non-framework bodies.
        def _take(m):
            nonlocal n_styles
            attrs = m.group("attrs") or ""
            if 'data-source="framework"' in attrs or "data-source='framework'" in attrs:
                return m.group(0)          # leave framework blocks in place
            n_styles += 1
            body = m.group("body")
            if body and body.strip():
                bodies.append(body.strip())
            return ""                       # remove the <style> from data.html
        stripped = _STYLE_RE.sub(_take, html)
        if not n_styles:
            continue
        total_styles += n_styles
        # Collapse the blank lines a removed block can leave behind (cosmetic).
        stripped = re.sub(r"\n[ \t]*\n[ \t]*\n+", "\n\n", stripped)
        css_to_move = "\n".join(bodies)
        moves.append((slide, slide.get("key"), css_to_move, stripped, n_styles))
    return moves, total_styles


def migrate_raw_inline(deck: dict, *, dry_run: bool, keys=None):
    """Apply collect_raw_inline_styles to `deck` (in place unless dry_run).
    Returns a list of (key, n_styles, n_bytes) actually migrated.
    `keys` (set|None) restricts to those slide-keys (None = all raw slides)."""
    moves, _ = collect_raw_inline_styles(deck, keys=keys)
    applied = []
    for slide, key, css_to_move, stripped_html, n_styles in moves:
        # Idempotency here is structural, NOT marker-based: collect_raw_inline_styles
        # only returns a slide that STILL has a non-framework <style> in its
        # data.html, and a successful migration strips that <style> out — so a
        # swept slide simply won't reappear next run. A whole-slide skip keyed on a
        # prior migration MARKER would strand any <style> RE-ADDED to data.html
        # after an earlier sweep (the marker is present, yet a real <style> still
        # needs migrating). So always migrate what collect returned; the header
        # marker below is purely informational and may legitimately appear twice.
        applied.append((key, n_styles, len(css_to_move.encode("utf-8"))))
        if dry_run:
            continue
        ts = datetime.now().strftime("%Y-%m-%d")
        header = f"/* migrated from raw inline <style> by F-272 codemod ({ts}) */"
        existing = slide.get("custom_css", "") or ""
        sep = "\n" if existing.strip() else ""
        new_cc = existing + sep + header
        if css_to_move.strip():
            new_cc += "\n" + css_to_move
        slide["custom_css"] = new_cc
        slide.setdefault("data", {})["html"] = stripped_html
    return applied


def _migrate_head(html: str, deck: dict, *, dry_run: bool):
    """The original L7 head-CSS sweep, factored out. Returns (applied, missing,
    orphans, skipped_at) — applied = [(key, n_rules, n_chars)]."""
    by_key = {s.get("key"): s for s in deck.get("slides", [])}
    chunks, orphans, skipped_at = collect(html)
    applied, missing = [], []
    for key, css in chunks.items():
        slide = by_key.get(key)
        if slide is None:
            missing.append(key)
            continue
        # Idempotency: if this slide's custom_css already carries a migration
        # marker, the head blocks were migrated on a PRIOR run but index.html
        # wasn't re-rendered (so they still appear in head) — re-appending would
        # DUPLICATE the rules. Skip; re-render first to clear the head blocks.
        if "migrated from head <style> by L7 codemod" in (slide.get("custom_css") or ""):
            continue
        n_rules = sum(1 for _ in _walk_top(css))   # top-level rules + keyframes
        applied.append((key, n_rules, len(css)))
        if not dry_run:
            ts = datetime.now().strftime("%Y-%m-%d")
            header = f"/* migrated from head <style> by L7 codemod ({ts}) */"
            existing = slide.get("custom_css", "") or ""
            sep = "\n" if existing.strip() else ""
            slide["custom_css"] = existing + sep + header + "\n" + css
    return applied, missing, orphans, skipped_at


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("index_html", type=Path, nargs="?", default=None,
                    help="rendered index.html (for the head-CSS sweep). Optional "
                         "with --raw-inline-only (which works on deck.json alone).")
    ap.add_argument("deck_json", type=Path)
    ap.add_argument("--dry-run", action="store_true", help="report without writing")
    ap.add_argument("--render", action="store_true",
                    help="re-render after migrating (verify parity)")
    ap.add_argument("--no-raw-inline", action="store_true",
                    help="skip the F-272 raw-page inline <style> → custom_css "
                         "sweep (head-CSS sweep only, the legacy behaviour)")
    ap.add_argument("--raw-inline-only", action="store_true",
                    help="ONLY sweep raw-page inline <style> into custom_css "
                         "(F-272) — operates on deck.json directly, no index.html "
                         "needed (skips the head-CSS sweep)")
    args = ap.parse_args(argv)

    do_head = not args.raw_inline_only
    do_raw = not args.no_raw_inline

    if do_head and args.index_html is None:
        print("migrate: index_html is required for the head-CSS sweep "
              "(pass it, or use --raw-inline-only to sweep deck.json alone).",
              file=sys.stderr)
        return 2

    must_exist = [args.deck_json]
    if do_head:
        must_exist.append(args.index_html)
    for p in must_exist:
        if not p.exists():
            print(f"migrate: {p} not found", file=sys.stderr)
            return 2

    deck = json.loads(args.deck_json.read_text(encoding="utf-8"))

    head_applied, head_missing, orphans, skipped_at = [], [], [], []
    if do_head:
        html = args.index_html.read_text(encoding="utf-8")
        print(f"migrate-head-css: scanned {args.index_html.name}")
        head_applied, head_missing, orphans, skipped_at = _migrate_head(
            html, deck, dry_run=args.dry_run)
        if not head_applied and not orphans:
            print("  ✓ no head/deck-level per-slide CSS found.")
        else:
            verb = "WOULD MIGRATE" if args.dry_run else "MIGRATED"
            print(f"  [head <style>] {verb}: {len(head_applied)} slide(s)")
            for key, nr, nbytes in head_applied:
                print(f"    → {key}  ({nr} rule/keyframe block(s), {nbytes} chars → custom_css)")
            if head_missing:
                print(f"  ⚠ {len(head_missing)} slide-key(s) referenced in head CSS not "
                      f"found in deck.json (left in head): {head_missing}")
            if orphans:
                print(f"  ⚠ {len(orphans)} head rule(s) with no per-slide selector — "
                      f"left in place (review manually):")
                for o in orphans[:8]:
                    print(f"      {o}")
            if skipped_at:
                print(f"  ⚠ {len(skipped_at)} @media/@supports block(s) in head — NOT "
                      f"migrated (per-slide rules inside @-wrappers need manual review):")
                for s in skipped_at[:6]:
                    print(f"      {s}")

    raw_applied = []
    if do_raw:
        raw_applied = migrate_raw_inline(deck, dry_run=args.dry_run)
        if not raw_applied:
            print("migrate-raw-inline: ✓ no raw-page inline <style> to migrate.")
        else:
            verb = "WOULD MIGRATE" if args.dry_run else "MIGRATED"
            print(f"migrate-raw-inline (F-272): {verb}: {len(raw_applied)} raw slide(s)")
            for key, nstyle, nbytes in raw_applied:
                print(f"    → {key}  ({nstyle} inline <style> block(s), "
                      f"{nbytes} bytes → custom_css; <style> stripped from data.html)")

    if not head_applied and not raw_applied:
        print("\n  Nothing to migrate.")
        return 0

    if args.dry_run:
        print("\n  (--dry-run; deck.json NOT modified.)")
        return 0

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    bak = args.deck_json.with_suffix(f".json.bak-pre-migrate-{ts}")
    shutil.copy2(args.deck_json, bak)
    print(f"  ✓ backup: {bak.name}")
    args.deck_json.write_text(
        json.dumps(deck, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"  ✓ wrote {args.deck_json}")

    if args.render:
        render = Path(__file__).resolve().parent / "render-deck.py"
        print("\n  re-rendering to verify parity…")
        rc = subprocess.run([sys.executable, str(render), str(args.deck_json),
                             str(args.deck_json.parent)])
        if rc.returncode != 0:
            print("  ✗ re-render failed — inspect output", file=sys.stderr)
            return 1
    else:
        print(f"\nNext: re-render to bake the migration in, then validate:")
        print(f"  python3 {Path(__file__).parent.name}/render-deck.py "
              f"{args.deck_json} {args.deck_json.parent}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
