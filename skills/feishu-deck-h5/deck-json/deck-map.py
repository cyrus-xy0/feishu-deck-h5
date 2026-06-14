#!/usr/bin/env python3
"""deck-map.py — print the real page map of a deck (HTML or deck.json).

The problem this solves: a rendered deck HTML is a single big file where
`data-slide-key="x"` also appears dozens of times inside `<style>` rules and
`<script>` templates, so a naive `grep` count of slide keys is wildly wrong.
The ONLY source of truth for "how many pages and what's on each" is the
`<div class="slide-frame">` blocks (HTML) or the `slides[]` array (deck.json).
This tool reads exactly those and prints:

    idx · key · layout · screen-label · title

so you never have to archaeology a montage by hand again.

    deck-map.py <index.html | deck.json>          # human table
    deck-map.py <file> --json                      # machine-readable JSON
    deck-map.py <file> --key tongdianjuli          # only matching rows

stdlib only. Python 3.11+.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


_COMMENT_OPEN = "<!--"
_SKIP_BLOCKS = (("<!--", "-->"), ("<script", "</script>"), ("<style", "</style>"))


def _skip_inert(html: str, j: int) -> int | None:
    """If `html[j:]` begins an HTML comment, <script>, or <style> block, return the
    index just past its end (so a stray </div> or <div inside a comment / JS string
    / CSS body is NOT counted toward div depth). Otherwise return None.
    Comments match anywhere; script/style only at a real tag boundary."""
    if html.startswith(_COMMENT_OPEN, j):
        end = html.find("-->", j + len(_COMMENT_OPEN))
        return (end + 3) if end >= 0 else len(html)
    lower = html[j:j + 7].lower()
    for opener, closer in _SKIP_BLOCKS[1:]:
        if lower.startswith(opener) and (len(html) <= j + len(opener)
                                         or html[j + len(opener)] in " \t\n\r>/"):
            close = html.lower().find(closer, j)
            return (close + len(closer)) if close >= 0 else len(html)
    return None


def _depth_match_divs(html: str, open_re: re.Pattern) -> list[tuple[int, int]]:
    """Return (start, end) spans of every `<div …>` block matched by open_re,
    depth-counted to the matching </div> (blocks may contain nested divs).
    Comment / <script> / <style> bodies are skipped wholesale so a stray
    </div> or <div inside them does not corrupt the depth count."""
    spans: list[tuple[int, int]] = []
    i = 0
    while True:
        m = open_re.search(html, i)
        if not m:
            break
        start = m.start()
        depth = 1
        j = m.end()
        while j < len(html) and depth > 0:
            skip_to = _skip_inert(html, j)
            if skip_to is not None:
                j = skip_to
                continue
            close = re.match(r'</div>', html[j:])
            tag = re.match(r'<div[\s>]', html[j:])
            if close:
                depth -= 1
                j += len(close.group(0))
            elif tag:
                depth += 1
                gt = html.find(">", j)
                j = gt + 1 if gt > 0 else j + 1
            else:
                j += 1
        if depth == 0:
            spans.append((start, j))
            i = j
        else:
            break
    return spans


def _attr(frag: str, name: str) -> str | None:
    m = re.search(rf'\b{re.escape(name)}\s*=\s*"([^"]*)"', frag)
    return m.group(1) if m else None


_TAG_RE = re.compile(r'<[^>]+>')
_WS_RE = re.compile(r'\s+')


def _text_of(frag: str, *selectors_classes: str) -> str | None:
    """Pull the visible text of the first element whose class contains one of
    `selectors_classes`, else the first <h1>/<h2>. Tags stripped, ws collapsed."""
    # class-based first (e.g. title-zh)
    for cls in selectors_classes:
        m = re.search(rf'<(\w+)[^>]*\bclass="[^"]*\b{re.escape(cls)}\b[^"]*"[^>]*>(.*?)</\1>',
                      frag, re.S)
        if m:
            txt = _WS_RE.sub(" ", _TAG_RE.sub("", m.group(2))).strip()
            if txt:
                return txt
    for tag in ("h1", "h2", "h3"):
        m = re.search(rf'<{tag}\b[^>]*>(.*?)</{tag}>', frag, re.S)
        if m:
            txt = _WS_RE.sub(" ", _TAG_RE.sub("", m.group(1))).strip()
            if txt:
                return txt
    return None


def map_html(html: str) -> list[dict]:
    """Map a rendered deck HTML by its `<div class="slide-frame">` blocks."""
    frame_re = re.compile(r'<div\s+class="slide-frame"[^>]*>', re.S)
    rows: list[dict] = []
    for n, (s, e) in enumerate(_depth_match_divs(html, frame_re), 1):
        frame = html[s:e]
        rows.append({
            "index": n,
            "key": _attr(frame, "data-slide-key"),
            "layout": _attr(frame, "data-layout"),
            "label": _attr(frame, "data-screen-label"),
            "title": _text_of(frame, "title-zh", "title"),
        })
    return rows


def map_deckjson(deck: dict) -> list[dict]:
    rows: list[dict] = []
    # Page number = frame_index = position AFTER skipping _disabled slides — the
    # canonical rule the renderer (active_slides) and locate-slide.py both enforce,
    # and what URL #N / slide-index.json use. Enumerating the raw array would make
    # every row after a _disabled slide off-by-one vs the real page number.
    fi = 0
    for s in deck.get("slides", []):
        if s.get("_disabled"):     # omitted from the DOM and slide-index.json
            continue
        fi += 1
        data = s.get("data") or {}
        title = data.get("title")
        if not title and isinstance(data.get("html"), str):
            t = _text_of(data["html"], "title-zh", "title")
            title = t
        rows.append({
            "index": fi,
            "key": s.get("key"),
            "layout": s.get("layout"),
            "label": s.get("screen_label"),
            "title": title,
            "lifted": bool(s.get("lifted")),
        })
    return rows


def _fmt_table(rows: list[dict], deck_name: str | None) -> str:
    if not rows:
        return "  (no slides found)"
    out = []
    if deck_name:
        out.append(f"deck: {deck_name}")
    out.append(f"pages: {len(rows)}")
    kw = max((len(str(r.get("key") or "")) for r in rows), default=3)
    lw = max((len(str(r.get("layout") or "")) for r in rows), default=6)
    bw = max((len(str(r.get("label") or "")) for r in rows), default=5)
    for r in rows:
        lift = " ⬑lifted" if r.get("lifted") else ""
        title = _WS_RE.sub(" ", str(r.get("title"))).strip() if r.get("title") else "—"
        out.append(
            f"  {r['index']:>2}  "
            f"{str(r.get('key') or '—'):<{kw}}  "
            f"{str(r.get('layout') or '—'):<{lw}}  "
            f"{str(r.get('label') or '—'):<{bw}}  "
            f"{title}{lift}"
        )
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="deck-map.py", description=__doc__.split("\n")[0])
    ap.add_argument("file", type=Path, help="index.html (rendered deck) or deck.json")
    ap.add_argument("--json", action="store_true", help="machine-readable JSON output")
    ap.add_argument("--key", help="only rows whose key matches")
    ap.add_argument("--index", type=int, help="only the row at this 1-based frame index")
    args = ap.parse_args(argv)

    if not args.file.is_file():
        print(f"deck-map: not a file: {args.file}", file=sys.stderr)
        return 2

    text = args.file.read_text(encoding="utf-8")
    deck_name = None
    if args.file.suffix == ".json":
        try:
            deck = json.loads(text)
        except json.JSONDecodeError as e:
            print(f"deck-map: invalid JSON: {e}", file=sys.stderr)
            return 2
        deck_name = deck.get("title") or deck.get("deck")
        if isinstance(deck_name, dict):          # deck.json `title` is often an object
            deck_name = deck_name.get("title")
        rows = map_deckjson(deck)
    else:
        m = re.search(r'<div\s+class="deck"[^>]*data-deck-title="([^"]*)"', text)
        deck_name = m.group(1) if m else None
        rows = map_html(text)

    if args.index is not None:
        rows = [r for r in rows if r["index"] == args.index]
    if args.key:
        rows = [r for r in rows if r.get("key") == args.key]

    if args.json:
        print(json.dumps({"deck": deck_name, "pages": len(rows), "slides": rows},
                         ensure_ascii=False, indent=2))
    else:
        print(_fmt_table(rows, deck_name))
    return 0


if __name__ == "__main__":
    sys.exit(main())
