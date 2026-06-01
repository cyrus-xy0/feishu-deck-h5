#!/usr/bin/env python3
"""clean-lifted-css.py — F-50 (c2): repair CSS pollution that the OLD scoper
baked INSIDE @keyframes blocks of lifted pages. Zero-render-risk safety pass.

The problem this fixes (F-50, measured on the zhongan victim deck)
------------------------------------------------------------------
When a slide was lifted into another deck by an OLD `lift-slides.py`, the per-
slide scoper walked the inlined CSS and prefixed selectors with
`.slide[data-slide-key="K"]`. On ONE keyframe it scoped a frame selector that
was on its OWN line, turning

    @keyframes kf-fade-left{
      from { opacity:0; transform:translateX(-40px) }
      to   { opacity:1; transform:none }
    }

into

    @keyframes kf-fade-left{
      from { opacity:0; transform:translateX(-40px) }
      .slide[data-slide-key="back-coach"] to { opacity:1; transform:none }   ← CORRUPT
    }

A keyframe-selector may only be `from` / `to` / `<percentage>` — a compound
element selector like `.slide[...] to` is ILLEGAL, so every browser silently
drops that frame (the keyframe degrades to a `from`-only animation).

Why no existing tool catches this (the architectural reason)
------------------------------------------------------------
`heal-lifted.py` and `_css_utils.iter_css_rules` both treat `@keyframes` as an
opaque `@`-rule: they brace-match from `@` to its matching `}` and pass the
whole block through VERBATIM. The injected prefix sits INSIDE those braces, so
it is invisible to every top-level rule walker. It can only be repaired by
looking INSIDE the keyframe body — which is exactly what this tool does, and
nothing else does.

iter_css_rules probe (recorded, do not re-litigate — see F-50 report)
---------------------------------------------------------------------
Fed the corrupt block, `iter_css_rules()` yields **nothing** for it: the
`.slide[...] to {…}` is swallowed as part of the `@keyframes` `@`-rule, NOT
emitted as a (bogus) top-level rule. Confirmed empirically before this tool was
written.

Why this is zero-render-risk (measured)
---------------------------------------
On the victim deck `kf-fade-left` is **defined once per page and referenced
zero times** (no `animation:`/`animation-name:` mentions it). The keyframe is
dead/unused, so repairing the illegal frame back to `to` changes no rendering.
We pick REPAIR over DROP because it is the minimal, surgical edit (strip only
the scoper's injected prefix token) and leaves a legal keyframe behind for any
future hoist work, without removing anything the original author wrote.

Scope discipline — what this tool DELIBERATELY does NOT do
----------------------------------------------------------
F-50 also names "cross-page slide-key leaks" (rules scoped to a DIFFERENT
slide's key). Investigation (F-50 probe) found that on this deck those split
into two buckets, NEITHER safe to delete in this c2 pass:
  • the comment-mangled ones (`.slide[K] /*…*/ .slide[other]…`) are ALREADY
    dropped by `heal-lifted.py`'s dead-rule pass (illegal comment-in-selector);
    re-handling them here would double-handle the same bytes.
  • the remaining clean multi-key rules (e.g.
    `.slide[K=back-latte] .main, …, .slide[K=THIS-PAGE] .main { … }`) are VALID
    framework cascade rules whose comma-list ALSO contains THIS page's own key
    — deleting the whole rule would remove a selector that DOES apply here, i.e.
    a real render change. So per F-50's "若某类污染其实可能是有效规则，保守不删"
    discipline, this tool leaves all cross-page-leak rules untouched.
This tool's only mutation is the keyframe-internal prefix strip.

Usage
-----
    python3 clean-lifted-css.py <deck.json> [--dry-run] [--force]

  --dry-run   report per-page fix counts / bytes saved; write nothing.
  default     write deck.json back AFTER a `.bak-pre-clean-css-<ts>` backup,
              with an F-53 optimistic-lock (expected_mtime) check; `--force`
              bypasses the lock.

Idempotent: a second run finds nothing to fix and produces a byte-identical
file (the repaired frame has no injected prefix, so the matcher won't re-fire).

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

_STYLE_RE = re.compile(r'(<style[^>]*>)(.*?)(</style>)', re.S)

# An injected `.slide[data-slide-key="…"]` prefix glued directly in front of a
# keyframe frame selector (`to` / `from` / `<percentage>`). Only ever applied
# INSIDE a brace-matched @keyframes body (see _iter_keyframe_spans), so it can
# never touch a legitimate top-level `.slide[…] to` outside a keyframe. The
# lookahead anchors on a real frame keyword/percentage so we don't strip a
# prefix that legitimately precedes some `.to-foo` class either.
_INJECTED_FRAME_PREFIX = re.compile(
    r'\.slide\[data-slide-key="[^"]*"\]\s+(?=(?:to|from|\d+(?:\.\d+)?%)\b)'
)


_KEYFRAMES_HEAD = re.compile(r'@(?:-webkit-|-moz-|-o-)?keyframes\s+[\w-]+')


def _iter_keyframe_spans(css: str):
    """Yield (start, end) byte spans of every `@keyframes NAME { … }` block,
    brace-matched. COMMENT-AWARE: `@keyframes` tokens that appear inside a
    `/* … */` comment are ignored (the victim deck has a literal
    `/* AUTO-PULLED @keyframes from source head … */` lead comment whose
    `@keyframes from` text would otherwise produce a bogus, overlapping span and
    corrupt the cursor-based reassembly). Spans never overlap because the
    scanner advances past each matched block before looking for the next."""
    i, n = 0, len(css)
    while i < n:
        # skip /* … */ comments so an `@keyframes` mention inside one is ignored
        if css[i:i + 2] == '/*':
            j = css.find('*/', i + 2)
            i = (j + 2) if j != -1 else n
            continue
        if css[i] == '@':
            m = _KEYFRAMES_HEAD.match(css, i)
            if m:
                brace = css.find('{', m.end())
                if brace != -1:
                    depth, k = 1, brace + 1
                    while k < n and depth:
                        if css[k] == '{':
                            depth += 1
                        elif css[k] == '}':
                            depth -= 1
                        k += 1
                    yield (i, k)
                    i = k
                    continue
        i += 1


def clean_block(css: str) -> tuple[str, int]:
    """Strip injected slide-key prefixes from keyframe frame selectors in one
    <style> body. Operates ONLY inside brace-matched @keyframes spans, so no
    selector outside a keyframe can be affected. Returns (new_css, n_fixed)."""
    spans = list(_iter_keyframe_spans(css))
    if not spans:
        return css, 0
    out: list[str] = []
    cursor = 0
    n_fixed = 0
    for start, end in spans:
        out.append(css[cursor:start])           # untouched text before keyframe
        block = css[start:end]
        new_block, n = _INJECTED_FRAME_PREFIX.subn('', block)
        n_fixed += n
        out.append(new_block)
        cursor = end
    out.append(css[cursor:])                     # tail after last keyframe
    return ''.join(out), n_fixed


def clean_html(html: str) -> tuple[str, int, int]:
    """Clean every <style> block inside a slide's data.html.
    Returns (new_html, n_fixed, bytes_saved)."""
    total_fixed = 0
    before_len = len(html)

    def _repl(m: re.Match) -> str:
        nonlocal total_fixed
        open_tag, body, close_tag = m.group(1), m.group(2), m.group(3)
        cleaned, nf = clean_block(body)
        total_fixed += nf
        return open_tag + cleaned + close_tag

    new_html = _STYLE_RE.sub(_repl, html)
    return new_html, total_fixed, before_len - len(new_html)


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def _slide_html(slide: dict) -> str | None:
    data = slide.get("data")
    if isinstance(data, dict) and isinstance(data.get("html"), str):
        return data["html"]
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("deck_json", type=Path)
    ap.add_argument("--dry-run", action="store_true",
                    help="report keyframe fixes / bytes saved per page; write nothing")
    ap.add_argument("--force", action="store_true",
                    help="bypass the optimistic-lock (concurrent-edit) check on write")
    args = ap.parse_args(argv)

    if not args.deck_json.exists():
        print(f"clean-lifted-css: {args.deck_json} not found", file=sys.stderr)
        return 2

    expected_mtime = args.deck_json.stat().st_mtime
    raw_text = args.deck_json.read_text(encoding="utf-8")
    try:
        deck = json.loads(raw_text)
    except json.JSONDecodeError as e:
        print(f"clean-lifted-css: {args.deck_json} is not valid JSON: {e}", file=sys.stderr)
        return 2

    slides = deck.get("slides", [])
    targets = [s for s in slides
               if s.get("layout") == "raw" and s.get("lifted") and _slide_html(s)]

    print(f"clean-lifted-css: scanned {args.deck_json.name} — "
          f"{len(slides)} slide(s), {len(targets)} layout:raw+lifted candidate(s)")
    if not targets:
        print("  ✓ no layout:raw + lifted slides — nothing to clean.")
        return 0

    report = []          # (key, n_fixed, bytes_saved)
    total_fixed = total_saved = 0
    for slide in targets:
        key = slide.get("key") or ""
        html = _slide_html(slide)
        new_html, n_fixed, saved = clean_html(html)
        if n_fixed:
            report.append((key, n_fixed, saved))
            total_fixed += n_fixed
            total_saved += saved
            if not args.dry_run:
                slide["data"]["html"] = new_html

    if not report:
        print("  ✓ all candidate slides already clean — no corrupt keyframe "
              "prefixes. (idempotent no-op.)")
        return 0

    verb = "WOULD FIX" if args.dry_run else "FIXED"
    print(f"  {verb}: {len(report)} slide(s)")
    for key, nf, saved in sorted(report, key=lambda r: -r[1]):
        print(f"    → {key}: {nf} corrupt keyframe prefix(es) stripped, {saved} byte(s)")
    print(f"  TOTAL: {total_fixed} keyframe prefix(es) stripped, "
          f"{total_saved} byte(s) saved")

    if args.dry_run:
        print("\n  (--dry-run; deck.json NOT modified.)")
        return 0

    # F-53 optimistic lock: refuse to clobber a concurrent write.
    if not args.force:
        cur_mtime = args.deck_json.stat().st_mtime
        if abs(cur_mtime - expected_mtime) > 1e-6:
            print(f"\n  ✗ REFUSING write — {args.deck_json.name} changed on disk "
                  f"since it was read (concurrent edit by another process). "
                  f"Re-run, or pass --force to overwrite.", file=sys.stderr)
            return 3

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    bak = args.deck_json.with_suffix(f".json.bak-pre-clean-css-{ts}")
    shutil.copy2(args.deck_json, bak)
    print(f"\n  ✓ backup: {bak.name}")
    args.deck_json.write_text(
        json.dumps(deck, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"  ✓ wrote {args.deck_json}")
    print(f"\nNext: re-render + validate to confirm the fix is render-neutral:")
    print(f"  python3 {Path(__file__).parent.name}/render-deck.py "
          f"{args.deck_json} {args.deck_json.parent}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
