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

Exit: 0 found · 4 not found · 2 bad input
"""
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
        entries.append({
            "key":         key,
            "frame_index": i + 1,
            "layout":      attr("data-layout"),
            "variant":     None,
            "label":       attr("data-screen-label") or (key or ""),
            "title":       "",
            "assets":      assets,
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
        if s.get("_disabled"):
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


def _fmt(e: dict, verbose: bool) -> str:
    if "_missing" in e:
        return f"#{e['_missing']}  ✗ no such frame_index"
    lv = f"/{e['variant']}" if e.get("variant") else ""
    line = (f"#{e['frame_index']}  key={e.get('key')}  "
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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Fast slide locator — page N = frame_index N = slides[N-1].")
    ap.add_argument("src", type=Path, help="deck dir, slide-index.json, or deck.json")
    ap.add_argument("query", help="frame_index / #N / URL#N / 46-48 / 46,2 / key / title substring")
    ap.add_argument("-v", "--verbose", action="store_true", help="show title + full asset list")
    ap.add_argument("--json", dest="as_json", action="store_true", help="emit matched entries as JSON")
    args = ap.parse_args(argv)

    entries, _title = _load_index(args.src)
    kind, val = _parse_query(args.query)
    res = _match(entries, kind, val)
    hits = [e for e in res if "_missing" not in e]

    if args.as_json:
        print(json.dumps(hits, ensure_ascii=False, indent=2))
        return 0 if hits else 4

    if not res:
        print(f"locate: no match for '{args.query}' among {len(entries)} slides", file=sys.stderr)
        return 4
    for e in res:
        print(_fmt(e, args.verbose))
    return 0 if hits else 4


if __name__ == "__main__":
    sys.exit(main())
