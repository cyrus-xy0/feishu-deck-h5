#!/usr/bin/env python3
"""locate-slide.py — fast slide locator for feishu-deck-h5 decks.

Resolve ANY reference form to the exact slide, in one command:
  · frame_index / URL hash : 46 · #46 · path/to/index.html#46 · 46-48 · 46,2,10
  · slide key              : feishu-ecosystem
  · title / label substring: 飞书生态

CANONICAL RULE (do not relearn this): page N = frame_index N = slides[N-1].
The on-screen pager and the URL hash (#N) BOTH use frame_index (feishu-deck.js
writes `#${idx+1}` and the pager shows `pad(cur+1)`). The screen_label's leading
number (e.g. "50 飞书生态") is a possibly-stale author/library label — it is NOT
the page number. Never locate by it. (Use `render-deck.py --renumber` to make the
label number match frame_index.)

Reads slide-index.json (preferred — render emits it every build) or falls back to
deck.json (synthesizes the index, honoring _disabled skips for frame_index).

Usage:
  locate-slide.py <deck-dir | slide-index.json | deck.json> <query> [-v] [--json]
  locate-slide.py <deck-dir | deck.json> <query|all> --grep PATTERN [--context N]

--grep (F-301): excerpt INSIDE the matched slides' data.html + custom_css —
a raw slide's html can be 100s of KB, so never print the whole thing to find
one element; grep it. PATTERN is a regex (an invalid regex degrades to literal
substring). Each hit prints source (html|custom_css), char offset, and ±N chars
of whitespace-collapsed context (default 120). Query `all` greps every slide.
Requires a deck.json (slide-index.json carries no body content).

Exit: 0 found · 4 not found · 2 bad input
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


def _derive_label(s: dict) -> str:
    """Mirror render-deck.py:_derive_screen_label for the deck.json fallback."""
    t = s.get("data", {}).get("title", "")
    if not t:
        return (s.get("key") or "untitled")[:20]
    cleaned = re.sub(r"\s+", " ", re.sub(r"[·:：—\-]+", " ", t))
    return cleaned.replace("\n", " ").replace("<br>", " ").strip()[:20]


def _load_index_from_html(src: Path):
    """Build the index by parsing slide-frames from a rendered index.html — for
    OLD / foreign decks that have NO deck.json or slide-index.json. frame_index =
    DOM order (1-based), which is EXACTLY what `#N` resolves to (feishu-deck.js
    `frames[N-1]`). data-screen-label's leading number is ignored as a page number,
    same trap as everywhere else."""
    html = src.read_text(encoding="utf-8")
    frames = [f for f in re.split(r'(?=<div class="slide-frame")', html)
              if 'class="slide-frame"' in f]
    entries = []
    for i, f in enumerate(frames):
        m = re.search(r'<div class="slide(?: [^"]*)?"[^>]*>', f)
        tag = m.group(0) if m else ""

        def attr(name, _tag=tag):
            mm = re.search(name + r'="([^"]*)"', _tag)
            return mm.group(1) if mm else None

        refs = (re.findall(r"url\(['\"]?([^)'\"]+)", f)
                + re.findall(r'(?:src|href)="([^"]+)"', f))
        assets = sorted({a for a in refs
                         if not a.startswith(("http", "data:", "#", "..", "/"))})
        key = attr("data-slide-key")
        # data-hidden may sit before OR after data-slide-key in the .slide tag;
        # a bare boolean attribute (no `="..."`) so test for its presence.
        hidden = bool(re.search(r'\bdata-hidden\b', tag))
        entries.append({
            "key":         key,
            "frame_index": i + 1,
            "layout":      attr("data-layout"),
            "variant":     None,
            "label":       attr("data-screen-label") or (key or ""),
            "title":       "",
            "assets":      assets,
            "hidden":      hidden,
        })
    return entries, ""


def _load_index(src: Path):
    """Return (entries, deck_title). Preference order for a dir:
    slide-index.json → deck.json → index.html (old/foreign deck fallback).
    A directly-passed *.html is parsed too. frame_index is always post-_disabled
    DOM order, matching what the renderer emits and what #N resolves to."""
    if src.is_dir():
        si, dj, ih = src / "slide-index.json", src / "deck.json", src / "index.html"
        if si.exists():
            src = si
        elif dj.exists():
            src = dj
        elif ih.exists():
            src = ih
        else:
            print(f"locate: no slide-index.json / deck.json / index.html under {src}",
                  file=sys.stderr)
            sys.exit(2)
    if not src.exists():
        print(f"locate: not found: {src}", file=sys.stderr)
        sys.exit(2)
    if src.suffix.lower() in (".html", ".htm"):
        return _load_index_from_html(src)
    data = json.loads(src.read_text(encoding="utf-8"))
    slides = data.get("slides") or []
    # slide-index.json entries already carry frame_index → use as-is.
    if slides and "frame_index" in slides[0]:
        return slides, data.get("deck", "")
    # deck.json → synthesize.
    entries, fi = [], 0
    for s in slides:
        if s.get("_disabled"):   # hidden slides ARE rendered (skipped only in nav)
            continue
        fi += 1
        entries.append({
            "key":         s.get("key"),
            "frame_index": fi,
            "layout":      s.get("layout"),
            "variant":     s.get("variant"),
            "label":       s.get("screen_label") or _derive_label(s),
            "title":       s.get("data", {}).get("title", ""),
            "assets":      [],
            "hidden":      bool(s.get("hidden")),
        })
    return entries, (data.get("deck") or {}).get("title", "")


def _parse_query(q: str):
    """('index', [int,...]) for numeric/range/list (and URL#N / #N forms),
    else ('text', str)."""
    if "#" in q:                      # URL or #N → keep the fragment
        q = q.rsplit("#", 1)[1]
    q = q.strip()
    if re.fullmatch(r"\d+(-\d+)?(\s*,\s*\d+(-\d+)?)*", q):
        idxs = []
        for part in q.split(","):
            part = part.strip()
            if "-" in part:
                a, b = part.split("-", 1)
                idxs.extend(range(int(a), int(b) + 1))
            else:
                idxs.append(int(part))
        return "index", idxs
    return "text", q


def _match(entries, kind, val):
    if kind == "index":
        by_fi = {e["frame_index"]: e for e in entries}
        return [by_fi.get(i, {"_missing": i}) for i in val]
    exact = [e for e in entries if e.get("key") == val]
    if exact:
        return exact
    low = val.lower()
    return [e for e in entries
            if low in (e.get("key") or "").lower()
            or low in (e.get("label") or "").lower()
            or low in (e.get("title") or "").lower()]


def _annotate_visible_ordinals(entries):
    """Attach `visible_ordinal` to every entry: the on-screen pager number =
    count of NON-hidden slides at-or-before this one (what feishu-deck.js'
    visibleOrdinal shows). Hidden slides get visible_ordinal=None (they have no
    own pager position — the pager skips them) and are rendered as '—'. Returns
    True if ANY entry is hidden. frame_index/#N is unchanged: it still counts ALL
    slides (incl. hidden), so hidden slides stay #N-reachable."""
    any_hidden = False
    seen_visible = 0
    for e in entries:
        if e.get("hidden"):
            any_hidden = True
            e["visible_ordinal"] = None
        else:
            seen_visible += 1
            e["visible_ordinal"] = seen_visible
    return any_hidden


def _fmt(e: dict, verbose: bool) -> str:
    if "_missing" in e:
        return f"#{e['_missing']}  ✗ no such frame_index"
    lv = f"/{e['variant']}" if e.get("variant") else ""
    # screen = the on-screen pager position (visible-only count). A hidden slide
    # has no pager slot of its own → shows '—'; frame_index/#N still counts it.
    vo = e.get("visible_ordinal")
    screen = f"screen={vo}" if vo is not None else "screen=—"
    hidden_tag = " [hidden]" if e.get("hidden") else ""
    line = (f"#{e['frame_index']}  {screen}  key={e.get('key')}{hidden_tag}  "
            f"layout={e.get('layout')}{lv}  \"{e.get('label', '')}\"  "
            f"link=index.html#{e['frame_index']}")
    assets = e.get("assets") or []
    if verbose:
        if e.get("title"):
            line += f"\n    title: {e['title']}"
        line += f"\n    assets({len(assets)}): " + (", ".join(assets) if assets else "—")
    elif assets:
        line += f"  assets={len(assets)}"
    return line


# ---------------------------------------------------------------------------
# --grep: excerpt inside slide bodies (F-301) — raw data.html can be 100s of KB;
# locating an element must not require printing the whole slide.
# ---------------------------------------------------------------------------

def _find_deck_json(src: Path) -> Path | None:
    """--grep needs body content, which only deck.json has."""
    if src.is_dir():
        p = src / "deck.json"
        return p if p.exists() else None
    if src.name == "deck.json":
        return src
    p = src.parent / "deck.json"      # sibling of slide-index.json / index.html
    return p if p.exists() else None


def _grep_slides(deck_json: Path, keys: set | None, pattern: str, ctx: int) -> int:
    """Print matches of `pattern` inside data.html + custom_css of the selected
    slides (keys=None → all). Returns number of hits."""
    try:
        rx = re.compile(pattern)
    except re.error:
        rx = re.compile(re.escape(pattern))      # invalid regex → literal
    deck = json.loads(deck_json.read_text(encoding="utf-8"))
    hits = 0
    for i, s in enumerate(deck.get("slides") or [], 1):
        key = s.get("key")
        if keys is not None and key not in keys:
            continue
        sources = [("html", (s.get("data") or {}).get("html") or ""),
                   ("custom_css", s.get("custom_css") or "")]
        slide_hdr_printed = False
        for src_name, text in sources:
            for m in rx.finditer(text):
                if not slide_hdr_printed:
                    print(f"slides[{i - 1}] · key={key} · "
                          f"\"{s.get('screen_label', '')}\"")
                    slide_hdr_printed = True
                a, b = max(0, m.start() - ctx), min(len(text), m.end() + ctx)
                seg = re.sub(r"\s+", " ", text[a:b]).strip()
                print(f"  [{src_name} @{m.start()}] …{seg}…")
                hits += 1
                if hits >= 200:
                    print(f"  (cap: 200 hits — narrow the pattern)")
                    return hits
    return hits


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Fast slide locator — page N = frame_index N = slides[N-1].")
    ap.add_argument("src", type=Path, help="deck dir, slide-index.json, or deck.json")
    ap.add_argument("query", help="frame_index / #N / URL#N / 46-48 / 46,2 / key / title substring / all (with --grep)")
    ap.add_argument("-v", "--verbose", action="store_true", help="show title + full asset list")
    ap.add_argument("--json", dest="as_json", action="store_true", help="emit matched entries as JSON")
    ap.add_argument("--grep", metavar="PATTERN", default=None,
                    help="excerpt matches inside the selected slides' data.html + "
                         "custom_css (regex; invalid regex = literal)")
    ap.add_argument("--context", type=int, default=120,
                    help="±chars of context around each --grep hit (default 120)")
    args = ap.parse_args(argv)

    if args.grep is not None:
        dj = _find_deck_json(args.src)
        if dj is None:
            print("locate: --grep needs a deck.json (slide-index.json has no "
                  "body content)", file=sys.stderr)
            return 2
        if args.query.strip().lower() in ("all", "*"):
            keys = None
        else:
            entries, _ = _load_index(dj)
            kind, val = _parse_query(args.query)
            sel = [e for e in _match(entries, kind, val) if "_missing" not in e]
            if not sel:
                print(f"locate: no slide matches '{args.query}'", file=sys.stderr)
                return 4
            keys = {e.get("key") for e in sel}
        n = _grep_slides(dj, keys, args.grep, args.context)
        if not n:
            print(f"locate: 0 hits for --grep '{args.grep}'", file=sys.stderr)
        return 0 if n else 4

    entries, _title = _load_index(args.src)
    any_hidden = _annotate_visible_ordinals(entries)
    kind, val = _parse_query(args.query)
    res = _match(entries, kind, val)
    hits = [e for e in res if "_missing" not in e]

    if args.as_json:
        # visible_ordinal + hidden ride along on each entry; the note is human
        # context only, so emit it to stderr (keeps stdout pure JSON).
        if any_hidden:
            print("note: screen pager counts visible-only; #N/frame_index counts "
                  "all slides incl. hidden", file=sys.stderr)
        print(json.dumps(hits, ensure_ascii=False, indent=2))
        return 0 if hits else 4

    if not res:
        print(f"locate: no match for '{args.query}' among {len(entries)} slides", file=sys.stderr)
        return 4
    for e in res:
        print(_fmt(e, args.verbose))
    if any_hidden:
        print("note: screen pager counts visible-only; #N/frame_index counts all "
              "slides incl. hidden")
    return 0 if hits else 4


if __name__ == "__main__":
    sys.exit(main())
