#!/usr/bin/env python3
"""fast-text.py — F-303: sub-second pure-copy edit, no render, no validation.

The mode this implements (user mandate, 2026-06-11)
----------------------------------------------------
"如果我让你改文字,按说就直接改,甚至连校验都不用跑 —— 极速改文字模式."
For a PURE copy swap (a word, a phrase, a sentence — zero DOM/layout change),
the full edit→render→validate→screenshot ceremony is waste: render alone is
~12s scoped, and a text swap can't break what validation checks for... except
overflow, which gets a heuristic length warning below instead of a render.

What it does
------------
ONE deterministic dual-write that keeps deck.json (source of truth) and the
rendered index.html in sync without a render:

  1. deck.json   : replace the JSON-escaped form of OLD with NEW (count==1
                   asserted), then re-parse the file to prove the JSON is
                   still valid (refuses + restores on any miss).
  2. index.html  : replace OLD with NEW (count==1; falls back to the
                   HTML-escaped form for &/quote-bearing strings).

Round-trip integrity holds because BOTH representations changed by the same
literal string — there is nothing for sync-index-to-deck to drift on.

Guardrails (hard, no flag overrides)
------------------------------------
- OLD/NEW containing '<' or '>' is REFUSED — that's a DOM edit, not a copy
  edit; go through the normal deck.json edit + render path.
- count != 1 in deck.json is REFUSED (ambiguous anchor → lengthen the string).
- count != 1 in index.html → deck.json is still updated, but the tool exits 3
  telling you index.html needs a `--quick` render to sync (happens when the
  renderer entity-escaped the text, e.g. ' → &rsquo;).
- A NEW much longer than OLD (>1.5x and >12 chars) prints an overflow warning
  (text got bigger, the box didn't) — it still applies; eyeball or do a
  `--scope` render if the page was already tight.

USAGE
-----
    python3 fast-text.py <deck-dir|deck.json> "OLD TEXT" "NEW TEXT"

Exit: 0 both files updated · 3 deck.json updated, index.html needs re-render ·
      2 refused / bad input.

stdlib only. Python 3.10+.
"""
from __future__ import annotations

import argparse
import html as _html
import json
import sys
from pathlib import Path


def resolve(deck_arg: str):
    p = Path(deck_arg).resolve()
    if p.is_dir():
        return p / "deck.json", p / "index.html"
    if p.name == "deck.json":
        return p, p.parent / "index.html"
    if p.suffix in (".html", ".htm"):
        return p.parent / "deck.json", p
    return p / "deck.json", p / "index.html"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("deck", help="deck dir, deck.json, or index.html")
    ap.add_argument("old", help="exact current text (no < or >)")
    ap.add_argument("new", help="replacement text (no < or >)")
    args = ap.parse_args(argv)

    old, new = args.old, args.new
    if old == new:
        print("fast-text: OLD and NEW are identical — nothing to do", file=sys.stderr)
        return 2
    if any(c in s for s in (old, new) for c in "<>"):
        print("fast-text: REFUSED — OLD/NEW contains '<' or '>'. That's a DOM "
              "edit, not a copy swap; use the normal deck.json edit + render "
              "path.", file=sys.stderr)
        return 2

    deck_json, index_html = resolve(args.deck)
    if not deck_json.exists():
        print(f"fast-text: {deck_json} not found", file=sys.stderr)
        return 2

    # --- 1. deck.json (source of truth) — JSON-escaped replace + re-parse ----
    raw = deck_json.read_text(encoding="utf-8")
    old_j = json.dumps(old, ensure_ascii=False)[1:-1]
    new_j = json.dumps(new, ensure_ascii=False)[1:-1]
    n = raw.count(old_j)
    if n != 1:
        print(f"fast-text: REFUSED — OLD matches {n}× in {deck_json.name} "
              f"(need exactly 1). {'Lengthen the anchor string.' if n else 'Check the exact wording (entities? whitespace?). Try: locate-slide.py <deck> all --grep <fragment>'}",
              file=sys.stderr)
        return 2
    new_raw = raw.replace(old_j, new_j)
    try:
        json.loads(new_raw)
    except json.JSONDecodeError as e:
        print(f"fast-text: REFUSED — replacement would corrupt deck.json "
              f"({e}). Nothing written.", file=sys.stderr)
        return 2
    deck_json.write_text(new_raw, encoding="utf-8")
    print(f"✓ {deck_json.name}: 1 replacement")

    # length-delta overflow heuristic (warn only — the deal is NO validation)
    if len(new) > len(old) * 1.5 and len(new) - len(old) > 12:
        print(f"⚠ NEW is {len(new) - len(old)} chars longer than OLD — text "
              "grew, the box didn't. Eyeball the page; if it was already "
              "tight, do a --scope render.", file=sys.stderr)

    # --- 2. index.html — same literal swap (or its HTML-escaped form) --------
    if not index_html.exists():
        print(f"· {index_html.name} absent — deck.json updated; render when ready")
        return 0
    h = index_html.read_text(encoding="utf-8")
    done = False
    for o, nw in ((old, new), (_html.escape(old), _html.escape(new))):
        if h.count(o) == 1:
            index_html.write_text(h.replace(o, nw), encoding="utf-8")
            print(f"✓ {index_html.name}: 1 replacement (no render needed)")
            done = True
            break
    if not done:
        cnt = h.count(old)
        print(f"! {index_html.name}: OLD matches {cnt}× (need 1 — the renderer "
              "may have entity-escaped it). deck.json IS updated; sync the "
              "html with:\n    python3 deck-json/render-deck.py "
              f"{deck_json} {deck_json.parent}/ --quick", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
