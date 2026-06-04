#!/usr/bin/env python3
"""extract-text-pairs.py — generate the FIND side of apply-text-pairs input from a
deck.json, so translation/localization is structure-safe.

The pipeline can APPLY find/replace pairs (apply-text-pairs.py) but nothing
GENERATES the find side from a deck. Hand-authoring `find` strings is exactly what
causes apply-text-pairs' "unmatched" failures (<br>/emoji/whitespace normalization
between source and product). This tool extracts every visible CJK-bearing run
VERBATIM from each slide — `data.html` (+ translatable attributes + CSS content:)
for raw/schema slides, or the nested `data.elements[].runs[].text` for canvas
(PPTX/hybrid-import) slides — so the find strings match byte-for-byte what
apply-text-pairs will operate on. (Canvas decks are usually normalized first with
merge-canvas-lines.py so PDF-fragmented glyphs become whole logical lines.)

Output is the apply-text-pairs input format with `replace` left empty for a
translator (human/agent) to fill:

    [ {"key": "<slide-key>",
       "replacements": [ {"find": "<verbatim CJK run>", "replace": ""}, ... ]}, ... ]

Runs are deduped per slide and sorted LONGEST-FIRST so apply-text-pairs cannot do
partial-substring damage (the long run is swapped before any run it contains).

Usage:
    extract-text-pairs.py <deck.json>                 > pairs.skeleton.json
    extract-text-pairs.py <deck.json> --report        # per-slide CJK-run counts
    extract-text-pairs.py <deck.json> --slides k1,k2   # only these slide keys
    extract-text-pairs.py --check <filled-pairs.json>  # gate: every replace filled
                                                       #   and contains no CJK
Exit: 0 ok / 2 file error / 5 (--check) some replace empty or still-Chinese.
"""
from __future__ import annotations
import argparse, json, re, sys
from html.parser import HTMLParser
from pathlib import Path

CJK = re.compile(r'[㐀-䶿一-鿿　-〿＀-￯]')
TRANSLATABLE_ATTRS = ("alt", "title", "aria-label", "data-screen-label", "placeholder")
CONTENT_RE = re.compile(r'content:\s*([\'"])(.*?)\1')


class RunExtractor(HTMLParser):
    """Collect CJK-bearing visible runs: text nodes (not in script/style),
    translatable attribute values, and CSS content: strings inside <style>."""
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.runs: list[str] = []
        self._skip_depth = 0   # inside <script>
        self._in_style = False

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self._skip_depth += 1
        if tag == "style":
            self._in_style = True
        for name, val in attrs:
            if name in TRANSLATABLE_ATTRS and val and CJK.search(val):
                self._add(val.strip())

    def handle_startendtag(self, tag, attrs):
        for name, val in attrs:
            if name in TRANSLATABLE_ATTRS and val and CJK.search(val):
                self._add(val.strip())

    def handle_endtag(self, tag):
        if tag == "script" and self._skip_depth:
            self._skip_depth -= 1
        if tag == "style":
            self._in_style = False

    def handle_data(self, data):
        if self._skip_depth:
            return
        if self._in_style:
            for m in CONTENT_RE.finditer(data):
                if CJK.search(m.group(2)):
                    self._add(m.group(2).strip())
            return
        s = data.strip()
        if s and CJK.search(s):
            self._add(s)

    def _add(self, s):
        # collapse internal runs of whitespace to match how they sit in the html?
        # NO — keep verbatim (apply-text-pairs needs the exact substring). We only
        # strip leading/trailing ws (handled by callers via .strip()).
        if s and s not in self.runs:
            self.runs.append(s)


def runs_from_html(html: str) -> list[str]:
    p = RunExtractor()
    try:
        p.feed(html)
    except Exception:
        # malformed fragment — fall back to a coarse text-between-tags scan
        for m in re.finditer(r'>([^<]+)<', html):
            s = m.group(1).strip()
            if s and CJK.search(s) and s not in p.runs:
                p.runs.append(s)
    # longest-first so apply-text-pairs swaps containing runs before contained ones
    return sorted(set(p.runs), key=len, reverse=True)


def runs_from_value(v) -> list[str]:
    """For non-raw slides: pull CJK strings out of nested data values."""
    out = []
    def walk(x):
        if isinstance(x, str):
            if CJK.search(x):
                # a data field may itself be html-ish; reuse the html extractor
                got = runs_from_html(x) if "<" in x else ([x.strip()] if CJK.search(x) else [])
                out.extend(got)
        elif isinstance(x, list):
            for i in x: walk(i)
        elif isinstance(x, dict):
            for i in x.values(): walk(i)
    walk(v)
    # dedupe, longest-first
    seen, uniq = set(), []
    for s in sorted(out, key=len, reverse=True):
        if s and s not in seen:
            seen.add(s); uniq.append(s)
    return uniq


def extract(deck_path: Path, only=None):
    deck = json.loads(deck_path.read_text(encoding="utf-8"))
    result = []
    for s in deck.get("slides", []):
        key = s.get("key")
        if not key or (only and key not in only):
            continue
        data = s.get("data") or {}
        html = data.get("html")
        if html:
            runs = runs_from_html(html)
        else:
            runs = runs_from_value(data)
        if runs:
            result.append({"key": key,
                           "replacements": [{"find": r, "replace": ""} for r in runs]})
    return result


def cmd_check(pairs_path: Path) -> int:
    data = json.loads(pairs_path.read_text(encoding="utf-8"))
    empty, still_cjk = [], []
    for entry in data:
        for r in entry.get("replacements", []):
            rep = r.get("replace", "")
            if rep == "":
                empty.append((entry.get("key"), r.get("find", "")[:30]))
            elif CJK.search(rep):
                still_cjk.append((entry.get("key"), rep[:30]))
    if not empty and not still_cjk:
        n = sum(len(e.get("replacements", [])) for e in data)
        print(f"OK ✅ all {n} replacements filled and contain no CJK")
        return 0
    if empty:
        print(f"❌ {len(empty)} replacement(s) still EMPTY (would DELETE the find on apply):")
        for k, f in empty[:15]:
            print(f"   [{k}] find={f!r}")
    if still_cjk:
        print(f"❌ {len(still_cjk)} replacement(s) still contain Chinese:")
        for k, rep in still_cjk[:15]:
            print(f"   [{k}] replace={rep!r}")
    return 5


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("deck", type=Path, help="deck.json (or, with --check, a filled pairs.json)")
    ap.add_argument("--slides", help="comma-separated slide keys to limit to")
    ap.add_argument("--report", action="store_true", help="print per-slide CJK-run counts, no JSON")
    ap.add_argument("--check", action="store_true", help="treat arg as a FILLED pairs.json and gate it")
    args = ap.parse_args()

    if not args.deck.exists():
        print(f"extract-text-pairs: {args.deck} not found", file=sys.stderr)
        return 2
    if args.check:
        return cmd_check(args.deck)

    only = set(args.slides.split(",")) if args.slides else None
    pairs = extract(args.deck, only)
    if args.report:
        total = 0
        for e in pairs:
            n = len(e["replacements"]); total += n
            print(f"{e['key']:42s} {n} run(s)")
        print(f"\n{len(pairs)} slide(s) with translatable text, {total} run(s) total")
        return 0
    json.dump(pairs, sys.stdout, ensure_ascii=False, indent=1)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
