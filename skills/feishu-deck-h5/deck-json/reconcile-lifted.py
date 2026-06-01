#!/usr/bin/env python3
"""reconcile-lifted.py — snap lifted-slide inline-CSS font sizes onto the 4-tier
type ladder {16, 24, 28, 48} (audit F-42, with F-71 for the `font:` shorthand).

The problem this fixes (audit F-42 / F-71)
------------------------------------------
A slide lifted verbatim from another deck carries that deck's improvised
content-page typography — 18 / 19 / 22 / 32 / 38 / 44 px body text that is NOT
on the canonical 4-tier ladder. R20 (`audit_type_ladder`) flags every one of
those as off-tier; on the zhongan victim deck that is 141 R20 warnings across
17 lifted pages. The human is then supposed to "snap to the ladder" by hand.
This tool does that snap deterministically and idempotently.

F-71 is folded in: the EARLIER `snap_fonts` prototype only matched
`font-size:Npx` and completely missed the `font:` shorthand, which on this deck
is where the BULK of off-ladder values live (e.g. case-luolai
`.kpi-strip-feihe .v{font:800 52px/1 …}` whose 52px slipped through and forced a
hand-written `/* allow:typescale */`). This tool snaps BOTH forms, using the
exact same px-extraction regexes the checker uses (R06/R20 in
_validate_audits.py) so the snapped value lines up with what the validator sees.

Snap policy (per CSS rule = selector + body)
--------------------------------------------
For each font value v found via `font-size:\\s*(\\d+)px` AND the first px of a
`\\bfont:\\s*[^;{}]*?(\\d+)px` shorthand (other shorthand tokens — weight /
line-height / family — are preserved byte-for-byte):

  • v in {16,24,28,48}                     → no-op (already on the ladder)
  • v >= 80                                → LEAVE (hero numerals / chapter nums /
                                             blockquotes — never shrink a hero)
  • selector hits a mockup/chrome class
    AND v < FLOOR_BODY_PX (24)             → LEAVE (rung-8 mockup-internal small
                                             text: .ui-* / .phone / .fs-phone /
                                             .ph-* / .mock-* / .attrib / .pill /
                                             .tag / … — snapping it up would
                                             break the simulated UI)
  • v < FLOOR_CHROME_PX (16)               → LEAVE (a body-class <16 is a genuine
                                             R06 floor violation that needs a
                                             grow-box, not a font snap — that is
                                             F-54's job, NOT F-42's; see "known
                                             limitation" below)
  • otherwise                              → SNAP to the nearest tier; ties go to
                                             the LARGER tier (20→24, 38→48) so we
                                             never shrink toward the floor

Mockup / chrome exemption boundary
----------------------------------
Imported (not re-typed) from the checker: `_validate_common._CHROME_CLASS_RE`
(covers `.ui-*`, `.attrib`, `.pill`, `.tag`, `.eyebrow`, `.source`, …) PLUS a
small mockup-container regex for the phone-frame primitives the checker doesn't
name (`.phone`, `.fs-phone`, `.ph-*`, `.mock-*`) called out in the F-42 ticket
+ the victim-deck survey. We deliberately do NOT use a bare `<16` numeric
threshold for the exemption (the old prototype did) — body copy at 18-22 is
also <24 but MUST snap; the exemption is selector-class driven.

Scope: layout:raw + lifted slides ONLY
---------------------------------------
Same predicate as heal-lifted.py: a slide is reconciled iff
`layout == "raw" AND lifted`. This is the F-42 contract ("only snap lift
pages") and it deliberately leaves the hand-written content pages alone — in
particular the two hand-written pages that own the 6 R20 ERRORs on this deck
(system-integration-thesis / sfdc-daily-ai-summary) are NOT lifted and are NOT
touched; those are a separate, human decision.

Idempotence (F-72 discipline)
------------------------------
Re-running converges: a value already on a tier is a no-op, so the second run
finds nothing to change and produces a byte-identical file. We REWRITE the
declaration in place (we do not append a new `<style>` block), so the inline
CSS never grows on re-run — the opposite of the hand-patch bloat F-72 measured.

Optimistic lock (F-53)
----------------------
mtime captured at read; re-checked before write; `--force` bypasses; a
`.bak-pre-reconcile-<ts>` backup is written before the file is replaced.

Usage
-----
    python3 reconcile-lifted.py <deck.json> [--dry-run] [--force]

stdlib only (+ the checker's _validate_common, imported for the exemption
boundary + ladder constants — single source of truth, F-02). Python 3.10+.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

# --- single source of truth: import the ladder + exemption boundary from the
#     checker rather than re-typing them (F-02). The validator assets live at
#     ../../assets relative to this deck-json/ tool. -----------------------------
_ASSETS = Path(__file__).resolve().parent.parent / "assets"
if str(_ASSETS) not in sys.path:
    sys.path.insert(0, str(_ASSETS))
try:
    from _validate_common import (
        _CHROME_CLASS_RE,
        TYPE_LADDER_PX,
        FLOOR_BODY_PX,
        FLOOR_CHROME_PX,
    )
except Exception:  # pragma: no cover — defensive fallback if assets unreachable
    _CHROME_CLASS_RE = re.compile(
        r'\.(?:eyebrow|footnote|pageno|deck-pageno|attrib|source(?:-footer)?|'
        r'pill|chip|tag(?:-chip)?|badge|label-small|chrome|kicker|overline|'
        r'meta|trend|axis(?:-cap)?|hint|tip|legend|nav-hint|mode-toggle|'
        r'phase-pill|status|status-dot|fmt|fix|disclaim|fineprint|'
        r'sc-cap|cfoot|stnum|chapter-num|stat-unit|kpi-unit|unit|'
        r'iframe-hint|count|n)\b|\.ui-[a-z][\w-]*')
    TYPE_LADDER_PX = {16, 24, 28, 48}
    FLOOR_BODY_PX, FLOOR_CHROME_PX = 24, 16

TIERS = sorted(TYPE_LADDER_PX)        # [16, 24, 28, 48]
HERO_FLOOR_PX = 80                    # >= this is a hero value; never snap

# Mockup-container primitives the checker's _CHROME_CLASS_RE does NOT name but
# the F-42 ticket + victim-deck survey call out: the phone frame and the dash-
# board mock wrappers. Their internal text is rung-8 mockup-internal.
_MOCKUP_CONTAINER_RE = re.compile(r'\.(?:phone|fs-phone|ph-[a-z][\w-]*|mock-[a-z][\w-]*)\b')

_STYLE_RE = re.compile(r'(<style[^>]*>)(.*?)(</style>)', re.S)


def _is_mockup_or_chrome(selector: str) -> bool:
    """Selector targets mockup-internal / chrome text → its <24px values are
    legitimately small (don't snap them up and break the simulated UI)."""
    return bool(_CHROME_CLASS_RE.search(selector) or _MOCKUP_CONTAINER_RE.search(selector))


def snap_tier(v: int) -> int:
    """Nearest tier; ties resolve to the LARGER tier (never shrink toward floor)."""
    return min(TIERS, key=lambda t: (abs(t - v), -t))


# ---------------------------------------------------------------------------
# Brace-matched CSS tokenizer that PRESERVES raw spans (same shape as
# heal-lifted.py / _css_utils.iter_css_rules) so surviving CSS round-trips
# byte-for-byte; we only rewrite the px inside font declarations.
# ---------------------------------------------------------------------------

def _tokenize(css: str):
    """Yield (kind, raw, selector) for every top-level construct.

    kind ∈ {'ws', 'comment', 'at', 'rule'}. For 'rule', selector is the
    comment-inclusive text up to the opening brace and raw is the whole
    `selector { body }`. @-rules are emitted whole; we recurse into @media so
    nested per-page rules get reconciled too.
    """
    i, n = 0, len(css)
    while i < n:
        c = css[i]
        if c in ' \t\r\n':
            j = i
            while j < n and css[j] in ' \t\r\n':
                j += 1
            yield ('ws', css[i:j], '')
            i = j
            continue
        if css[i:i + 2] == '/*':
            j = css.find('*/', i + 2)
            j = (j + 2) if j != -1 else n
            yield ('comment', css[i:j], '')
            i = j
            continue
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
            yield ('at', css[i:k], css[i:brace])
            i = k
            continue
        brace = css.find('{', i)
        if brace == -1:
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


# Declaration-level px rewriters. Both use the checker's exact px-extraction
# regexes so the snapped value matches what R06 / R20 see.
_FONT_SIZE_RE = re.compile(r'(font-size:\s*)(\d+)(px)')
# `font:` shorthand — capture up to (and incl.) the FIRST \d+px; the checker
# (R06:208, R20:318) reads exactly that first px. The trailing token (line-
# height / family / etc.) is preserved by the (?=...) lookahead structure.
_FONT_SHORTHAND_RE = re.compile(r'(\bfont:\s*[^;{}]*?)(\d+)(px)')


def _snap_declarations(body: str, selector: str, allow_typescale: bool,
                       changes: list[tuple[int, int, str]]):
    """Rewrite font px inside one rule body. Returns (new_body, n_changed).

    `changes` is appended (orig, snapped, kind) for the report. `allow_typescale`
    short-circuits the whole rule (mirrors the checker honoring the marker)."""
    if allow_typescale:
        return body, 0
    is_exempt = _is_mockup_or_chrome(selector)
    n = 0

    def _decide(orig: int) -> int | None:
        """Return the snapped value, or None to leave `orig` untouched."""
        if orig in TYPE_LADDER_PX:
            return None
        if orig >= HERO_FLOOR_PX:
            return None
        if is_exempt and orig < FLOOR_BODY_PX:
            return None                       # mockup/chrome small text — keep
        if orig < FLOOR_CHROME_PX:
            return None                       # body <16 → grow-box (F-54), not snap
        t = snap_tier(orig)
        return t if t != orig else None

    def _repl_size(m: re.Match) -> str:
        nonlocal n
        orig = int(m.group(2))
        t = _decide(orig)
        if t is None:
            return m.group(0)
        n += 1
        changes.append((orig, t, 'font-size'))
        return f'{m.group(1)}{t}{m.group(3)}'

    def _repl_shorthand(m: re.Match) -> str:
        nonlocal n
        orig = int(m.group(2))
        t = _decide(orig)
        if t is None:
            return m.group(0)
        n += 1
        changes.append((orig, t, 'font'))
        return f'{m.group(1)}{t}{m.group(3)}'

    body = _FONT_SIZE_RE.sub(_repl_size, body)
    body = _FONT_SHORTHAND_RE.sub(_repl_shorthand, body)
    return body, n


def _reconcile_css(css: str, changes: list[tuple[int, int, str]]) -> tuple[str, int]:
    """Reconcile one <style> body. Recurses into @media. Returns (new_css, n)."""
    out: list[str] = []
    total = 0
    for kind, raw, selector in _tokenize(css):
        if kind == 'rule':
            brace = raw.find('{')
            sel, rest = raw[:brace + 1], raw[brace + 1:-1]
            allow_ts = 'allow:typescale' in rest
            new_body, n = _snap_declarations(rest, selector, allow_ts, changes)
            total += n
            out.append(sel + new_body + '}')
        elif kind == 'at' and selector.lstrip().lower().startswith('@media'):
            # recurse into the @media body so nested per-page rules get snapped
            brace = raw.find('{')
            inner = raw[brace + 1:]
            # peel the matching final '}' (tokenizer guarantees balance)
            inner_body = inner[:inner.rfind('}')]
            new_inner, n = _reconcile_css(inner_body, changes)
            total += n
            out.append(raw[:brace + 1] + new_inner + '}')
        else:
            out.append(raw)
    return ''.join(out), total


def reconcile_html(html: str) -> tuple[str, int, list[tuple[int, int, str]]]:
    """Reconcile every <style> block in a slide's data.html.
    Returns (new_html, n_changed, changes[])."""
    changes: list[tuple[int, int, str]] = []
    total = 0

    def _repl(m: re.Match) -> str:
        nonlocal total
        open_tag, body, close_tag = m.group(1), m.group(2), m.group(3)
        new_body, n = _reconcile_css(body, changes)
        total += n
        return open_tag + new_body + close_tag

    new_html = _STYLE_RE.sub(_repl, html)
    return new_html, total, changes


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
                    help="report per-page snap plan; write nothing")
    ap.add_argument("--force", action="store_true",
                    help="bypass the optimistic-lock (concurrent-edit) check on write")
    args = ap.parse_args(argv)

    if not args.deck_json.exists():
        print(f"reconcile-lifted: {args.deck_json} not found", file=sys.stderr)
        return 2

    expected_mtime = args.deck_json.stat().st_mtime
    raw_text = args.deck_json.read_text(encoding="utf-8")
    try:
        deck = json.loads(raw_text)
    except json.JSONDecodeError as e:
        print(f"reconcile-lifted: {args.deck_json} is not valid JSON: {e}", file=sys.stderr)
        return 2

    slides = deck.get("slides", [])
    targets = [s for s in slides
               if s.get("layout") == "raw" and s.get("lifted") and _slide_html(s)]

    print(f"reconcile-lifted: scanned {args.deck_json.name} — "
          f"{len(slides)} slide(s), {len(targets)} layout:raw+lifted candidate(s)")
    if not targets:
        print("  ✓ no layout:raw + lifted slides — nothing to reconcile.")
        return 0

    report = []                                   # (key, n, changes[])
    total = 0
    for slide in targets:
        key = slide.get("key") or ""
        html = _slide_html(slide)
        new_html, n, changes = reconcile_html(html)
        if n:
            report.append((key, n, changes))
            total += n
            if not args.dry_run:
                slide["data"]["html"] = new_html

    if not report:
        print("  ✓ all candidate slides already on the 4-tier ladder — "
              "no off-tier font values to snap. (idempotent no-op.)")
        return 0

    verb = "WOULD SNAP" if args.dry_run else "SNAPPED"
    print(f"  {verb}: {len(report)} slide(s), {total} font declaration(s)")
    for key, n, changes in sorted(report, key=lambda r: -r[1]):
        from collections import Counter
        moves = Counter((o, t) for o, t, _ in changes)
        detail = ", ".join(f"{o}→{t}×{c}" for (o, t), c in
                           sorted(moves.items(), key=lambda x: (-x[1], x[0][0])))
        print(f"    → {key}: {n} ({detail})")
    print(f"  TOTAL: {total} font declaration(s) snapped to {{16,24,28,48}}")

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
    bak = args.deck_json.with_suffix(f".json.bak-pre-reconcile-{ts}")
    shutil.copy2(args.deck_json, bak)
    print(f"\n  ✓ backup: {bak.name}")
    args.deck_json.write_text(
        json.dumps(deck, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"  ✓ wrote {args.deck_json}")
    print("\nNext: re-render + visual-validate to confirm the snap did NOT push "
          "any page into overflow (font got LARGER):")
    print(f"  python3 {Path(__file__).parent.name}/render-deck.py "
          f"{args.deck_json} {args.deck_json.parent}/")
    print("  python3 assets/check-only.py <rendered index.html> --visual --by-rule")
    return 0


if __name__ == "__main__":
    sys.exit(main())
