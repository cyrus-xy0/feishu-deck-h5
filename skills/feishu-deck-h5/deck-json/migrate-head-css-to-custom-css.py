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

Usage
-----
    python3 migrate-head-css-to-custom-css.py <out>/index.html <out>/deck.json [--dry-run] [--render]

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
    spans = []
    for fm in _FRAME_OPEN.finditer(html):
        depth, end = 1, len(html)
        for dm in _DIV_TOKEN.finditer(html, fm.end()):
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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("index_html", type=Path)
    ap.add_argument("deck_json", type=Path)
    ap.add_argument("--dry-run", action="store_true", help="report without writing")
    ap.add_argument("--render", action="store_true",
                    help="re-render after migrating (verify parity)")
    args = ap.parse_args(argv)

    for p in (args.index_html, args.deck_json):
        if not p.exists():
            print(f"migrate: {p} not found", file=sys.stderr)
            return 2

    html = args.index_html.read_text(encoding="utf-8")
    deck = json.loads(args.deck_json.read_text(encoding="utf-8"))
    by_key = {s.get("key"): s for s in deck.get("slides", [])}

    chunks, orphans, skipped_at = collect(html)

    print(f"migrate-head-css: scanned {args.index_html.name}")
    if not chunks:
        print("  ✓ no head/deck-level per-slide CSS found — nothing to migrate.")
        if orphans:
            print(f"  ({len(orphans)} non-attributable head rule(s) left in place)")
        return 0

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
        if not args.dry_run:
            ts = datetime.now().strftime("%Y-%m-%d")
            header = f"/* migrated from head <style> by L7 codemod ({ts}) */"
            existing = slide.get("custom_css", "") or ""
            sep = "\n" if existing.strip() else ""
            slide["custom_css"] = existing + sep + header + "\n" + css

    verb = "WOULD MIGRATE" if args.dry_run else "MIGRATED"
    print(f"  {verb}: {len(applied)} slide(s)")
    for key, nr, nbytes in applied:
        print(f"    → {key}  ({nr} rule/keyframe block(s), {nbytes} chars → custom_css)")
    if missing:
        print(f"  ⚠ {len(missing)} slide-key(s) referenced in head CSS not found in "
              f"deck.json (left in head): {missing}")
    if orphans:
        print(f"  ⚠ {len(orphans)} head rule(s) with no per-slide selector — left in "
              f"place (review manually):")
        for o in orphans[:8]:
            print(f"      {o}")
    if skipped_at:
        print(f"  ⚠ {len(skipped_at)} @media/@supports block(s) in head — NOT migrated "
              f"(per-slide rules inside @-wrappers need manual review):")
        for s in skipped_at[:6]:
            print(f"      {s}")

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
