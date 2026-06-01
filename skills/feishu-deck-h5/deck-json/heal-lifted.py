#!/usr/bin/env python3
"""heal-lifted.py — turnkey repair for already-lifted-and-broken back-catalog decks.

The problem this fixes (audit F-67, with F-50 / F-51(a) / F-69 / F-72)
----------------------------------------------------------------------
When a slide was lifted into another deck by an OLD `lift-slides.py`, the
scoper prefixed EVERY rule of an inlined framework-CSS copy with
`.slide[data-slide-key="K"] ` — and stamped the prefix BEFORE the rule's
leading comment, producing:

    .slide[data-slide-key="K"] /* section comment */ .real-selector { … }

That selector is ILLEGAL (a comment cannot sit between two compound
selectors), so every browser silently discards the whole rule. On the
zhongan victim deck this is **1305 dead rules** across 16 lifted pages.

Crucial, measured fact (do not re-litigate — see the F-67 probe):
every one of those dead rules is a **framework-CSS copy** (its body is a
verbatim/stale copy of a rule in feishu-deck.css / extra-layouts.css /
feishu-deck-patterns.css, or it is a cross-slide leak that belongs to a
DIFFERENT slide's key). NONE is unique bespoke content for the page. The
target deck already `<link>`s the framework and `layout:raw` slides get the
framework cascade by default — so the correct, provably-safe heal is to
**drop the dead (illegal, browser-ignored) rules entirely**. We are deleting
CSS the browser already throws away; we keep every CLEAN, legal,
key-scoped bespoke rule byte-for-byte.

What it does, per `layout:raw` slide carrying a `lifted` marker
----------------------------------------------------------------
1. Walk each inline `<style>` block in `data.html` with a brace-matched
   parser (the `iter_css_rules` shape, extended to capture raw spans so the
   surviving CSS is rebuilt byte-faithfully).
2. DROP every top-level rule whose selector starts with this slide's
   `.slide[data-slide-key="K"]` prefix AND contains an embedded `/*…*/`
   comment — i.e. the illegal "prefix-then-comment-then-selector" dead rule.
   (Keyframes, @-rules, clean prefixed bespoke rules, and the small
   `data-scale-fix` / `data-batch-fix` / recovered blocks are all KEPT.)
3. F-51(a): repair any broken `] -frame.is-current` animation scope to
   `].slide-frame.is-current` (string-level, idempotent; the victim deck is
   already clean so this is a no-op here, but the step travels with the tool).

F-69 darkening discipline (the blood-lesson this tool is built around)
----------------------------------------------------------------------
This tool NEVER re-scopes / re-extracts / re-derives ANY CSS. It only
DELETES illegal dead rules and string-fixes the `-frame` typo. It never
pulls a generic `.slide` / background / overlay / dark rule back into a
single page (that is exactly what turned pg42 black). Nothing is added or
re-scoped, so there is no path to darkening, and the result is reductive
(F-72): re-running converges — the second run finds nothing to delete and
produces a byte-identical file.

Usage
-----
    python3 heal-lifted.py <deck.json> [--dry-run] [--force]

  --dry-run   report per-page dead-rule counts / bytes saved; write nothing.
  default     write deck.json back AFTER a `.bak-pre-heal-<ts>` backup, with
              an F-53 optimistic-lock (expected_mtime) check; `--force`
              bypasses the lock.

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


# ---------------------------------------------------------------------------
# Brace-matched CSS tokenizer that PRESERVES raw spans (comments + whitespace)
# so surviving CSS round-trips byte-for-byte. Same scanning shape as
# _css_utils.iter_css_rules — kept local & raw-span-aware on purpose.
# ---------------------------------------------------------------------------

def _tokenize(css: str):
    """Yield (kind, raw, selector) for every top-level construct.

    kind ∈ {'ws', 'comment', 'at', 'rule'}.
      - 'ws'      : a run of whitespace (raw preserved, selector='')
      - 'comment' : a /* … */ block (raw preserved, selector='')
      - 'at'      : an @-rule (keyframes / media / font-face / …) — raw
                    preserved verbatim, selector='' (never touched/dropped)
      - 'rule'    : a normal `selector { body }` — raw is the whole rule,
                    selector is the (comment-INCLUSIVE) selector text up to
                    the opening brace, exactly as iter_css_rules sees it.
    """
    i, n = 0, len(css)
    while i < n:
        c = css[i]
        # whitespace run
        if c in ' \t\r\n':
            j = i
            while j < n and css[j] in ' \t\r\n':
                j += 1
            yield ('ws', css[i:j], '')
            i = j
            continue
        # comment between rules
        if css[i:i + 2] == '/*':
            j = css.find('*/', i + 2)
            j = (j + 2) if j != -1 else n
            yield ('comment', css[i:j], '')
            i = j
            continue
        # @-rule
        if c == '@':
            brace = css.find('{', i)
            semi = css.find(';', i)
            if brace == -1 or (semi != -1 and semi < brace):
                end = (semi + 1) if semi != -1 else n
                yield ('at', css[i:end], '')
                i = end
                continue
            depth, k = 1, brace + 1
            while k < n and depth:
                if css[k] == '{':
                    depth += 1
                elif css[k] == '}':
                    depth -= 1
                k += 1
            yield ('at', css[i:k], '')
            i = k
            continue
        # regular rule: selector { body }
        brace = css.find('{', i)
        if brace == -1:
            # trailing junk (shouldn't happen in well-formed blocks) — emit raw
            yield ('ws', css[i:], '')
            break
        selector = css[i:brace]
        depth, k = 1, brace + 1
        while k < n and depth:
            if css[k] == '{':
                depth += 1
            elif css[k] == '}':
                depth -= 1
            k += 1
        yield ('rule', css[i:k], selector)
        i = k


# ---------------------------------------------------------------------------
# Dead-rule detection + block healing
# ---------------------------------------------------------------------------

def _is_dead_rule(selector: str, key: str) -> bool:
    """A dead, framework-copy rule = key-prefixed AND has an embedded comment
    between the prefix and the real selector (→ illegal, browser-discarded)."""
    s = selector.lstrip()
    prefix = f'.slide[data-slide-key="{key}"]'
    if not s.startswith(prefix):
        return False
    return '/*' in selector


# F-51(a): broken `] -frame.is-current` (a `.slide-frame` whose `slide` token
# the old scoper chewed off) → `].slide-frame.is-current`. Match `-frame.is-`
# only when the char before `-frame` is NOT part of `slide` (i.e. it is `]`,
# whitespace, or a combinator) so we never touch the already-correct
# `.slide-frame.is-current`.
_BROKEN_FRAME_RE = re.compile(r'(?<![\w-])-frame\.is-current')


def _fix_broken_frame(text: str) -> tuple[str, int]:
    """Repair broken `-frame.is-current` → `.slide-frame.is-current`.
    Idempotent: the corrected form already has `slide` before `-frame`, so the
    negative-lookbehind won't re-match it. Returns (new_text, n_fixed)."""
    n = len(_BROKEN_FRAME_RE.findall(text))
    if not n:
        return text, 0
    return _BROKEN_FRAME_RE.sub('.slide-frame.is-current', text), n


def heal_block(css: str, key: str) -> tuple[str, int, int]:
    """Return (healed_css, n_dead_dropped, n_frame_fixed) for one <style> body.

    Drops dead framework-copy rules; preserves everything else byte-faithfully;
    then applies the F-51(a) `-frame` string fix to the surviving text. When a
    dead rule is dropped, the whitespace run that immediately PRECEDED it is
    dropped too, so we don't accumulate blank lines (keeps the result reductive
    and idempotent)."""
    toks = list(_tokenize(css))
    out: list[str] = []
    n_dead = 0
    for idx, (kind, raw, selector) in enumerate(toks):
        if kind == 'rule' and _is_dead_rule(selector, key):
            n_dead += 1
            # also swallow the immediately-preceding whitespace token we emitted
            if out and toks[idx - 1][0] == 'ws':
                out.pop()
            continue
        out.append(raw)
    healed = ''.join(out)
    healed, n_frame = _fix_broken_frame(healed)
    return healed, n_dead, n_frame


def heal_html(html: str, key: str) -> tuple[str, int, int, int]:
    """Heal every <style> block inside a slide's data.html.
    Returns (new_html, n_dead, n_frame, bytes_saved)."""
    total_dead = total_frame = 0
    before_len = len(html)

    def _repl(m: re.Match) -> str:
        nonlocal total_dead, total_frame
        open_tag, body, close_tag = m.group(1), m.group(2), m.group(3)
        healed, nd, nf = heal_block(body, key)
        total_dead += nd
        total_frame += nf
        return open_tag + healed + close_tag

    new_html = _STYLE_RE.sub(_repl, html)
    return new_html, total_dead, total_frame, before_len - len(new_html)


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
                    help="report dead rules / bytes saved per page; write nothing")
    ap.add_argument("--force", action="store_true",
                    help="bypass the optimistic-lock (concurrent-edit) check on write")
    args = ap.parse_args(argv)

    if not args.deck_json.exists():
        print(f"heal-lifted: {args.deck_json} not found", file=sys.stderr)
        return 2

    expected_mtime = args.deck_json.stat().st_mtime
    raw_text = args.deck_json.read_text(encoding="utf-8")
    try:
        deck = json.loads(raw_text)
    except json.JSONDecodeError as e:
        print(f"heal-lifted: {args.deck_json} is not valid JSON: {e}", file=sys.stderr)
        return 2

    slides = deck.get("slides", [])
    targets = [s for s in slides
               if s.get("layout") == "raw" and s.get("lifted") and _slide_html(s)]

    print(f"heal-lifted: scanned {args.deck_json.name} — "
          f"{len(slides)} slide(s), {len(targets)} layout:raw+lifted candidate(s)")
    if not targets:
        print("  ✓ no layout:raw + lifted slides — nothing to heal.")
        return 0

    report = []          # (key, n_dead, n_frame, bytes_saved)
    total_dead = total_frame = total_saved = 0
    for slide in targets:
        key = slide.get("key") or ""
        html = _slide_html(slide)
        new_html, n_dead, n_frame, saved = heal_html(html, key)
        if n_dead or n_frame:
            report.append((key, n_dead, n_frame, saved))
            total_dead += n_dead
            total_frame += n_frame
            total_saved += saved
            if not args.dry_run:
                slide["data"]["html"] = new_html

    if not report:
        print("  ✓ all candidate slides already clean — no dead rules, no broken "
              "`-frame` scopes. (idempotent no-op.)")
        return 0

    verb = "WOULD HEAL" if args.dry_run else "HEALED"
    print(f"  {verb}: {len(report)} slide(s)")
    for key, nd, nf, saved in sorted(report, key=lambda r: -r[1]):
        bits = [f"{nd} dead framework-copy rule(s) dropped"]
        if nf:
            bits.append(f"{nf} `-frame.is-current` fix(es)")
        bits.append(f"~{saved/1024:.1f} KB")
        print(f"    → {key}: " + ", ".join(bits))
    print(f"  TOTAL: {total_dead} dead rule(s) dropped, "
          f"{total_frame} `-frame` fix(es), ~{total_saved/1024:.1f} KB saved")

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
    bak = args.deck_json.with_suffix(f".json.bak-pre-heal-{ts}")
    shutil.copy2(args.deck_json, bak)
    print(f"\n  ✓ backup: {bak.name}")
    args.deck_json.write_text(
        json.dumps(deck, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"  ✓ wrote {args.deck_json}")
    print(f"\nNext: re-render + validate to confirm the heal:")
    print(f"  python3 {Path(__file__).parent.name}/render-deck.py "
          f"{args.deck_json} {args.deck_json.parent}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
