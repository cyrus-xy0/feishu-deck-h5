#!/usr/bin/env python3
"""fast-image.py — pure existing-<img> replacement, no render required.

Use when a user says "换成这张图" / "replace this picture" and the target
slide already has an <img>; no layout, crop, or CSS redesign is requested.

What it does:
  1. Copies the new image into <deck-dir>/input/.
  2. Replaces exactly one <img src="..."> in deck.json slide data.html.
  3. Replaces the same old src in the rendered index.html when it can do so
     unambiguously, keeping source and rendered output in sync without render.

Exit: 0 deck.json and index.html updated · 3 deck.json updated, index.html
needs render · 2 refused / bad input.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path


IMG_RE = re.compile(r"<img\b[^>]*\bsrc=(['\"])(.*?)\1[^>]*>", re.I | re.S)
SRC_RE = re.compile(r"\bsrc=(['\"])(.*?)\1", re.I | re.S)
ALT_RE = re.compile(r"\balt=(['\"])(.*?)\1", re.I | re.S)


def resolve(deck_arg: str) -> tuple[Path, Path]:
    p = Path(deck_arg).resolve()
    if p.is_dir():
        return p / "deck.json", p / "index.html"
    if p.name == "deck.json":
        return p, p.parent / "index.html"
    if p.suffix.lower() in (".html", ".htm"):
        return p.parent / "deck.json", p
    return p / "deck.json", p / "index.html"


def slide_index(slides: list[dict], query: str) -> int:
    q = query.strip()
    if q.startswith("#"):
        q = q[1:]
    if q.isdigit():
        idx = int(q) - 1
        if 0 <= idx < len(slides):
            return idx
        raise SystemExit(f"fast-image: page {query} out of range 1..{len(slides)}")
    for i, slide in enumerate(slides):
        if slide.get("key") == query:
            return i
    hits = [
        i for i, slide in enumerate(slides)
        if query in str(slide.get("key", ""))
        or query in str(slide.get("screen_label", ""))
        or query in str(slide.get("data", {}).get("title", ""))
    ]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise SystemExit(f"fast-image: slide not found: {query}")
    raise SystemExit(f"fast-image: slide query is ambiguous: {query} -> {len(hits)} hits")


def slug_name(src: Path, requested: str | None) -> str:
    suffix = src.suffix.lower() or ".png"
    if requested:
        stem = Path(requested).stem
        req_suffix = Path(requested).suffix.lower()
        if req_suffix:
            suffix = req_suffix
    else:
        stem = src.stem
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-._").lower()
    if not stem:
        stem = "image"
    return f"{stem}{suffix}"


def copy_asset(deck_dir: Path, image: Path, requested_name: str | None) -> str:
    if not image.exists():
        raise SystemExit(f"fast-image: image not found: {image}")
    input_dir = deck_dir / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    base = slug_name(image, requested_name)
    dest = input_dir / base
    if dest.exists() and not same_file(dest, image):
        stem, suffix = dest.stem, dest.suffix
        n = 2
        while dest.exists():
            dest = input_dir / f"{stem}-{n}{suffix}"
            n += 1
    shutil.copy2(image, dest)
    return f"input/{dest.name}"


def same_file(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except FileNotFoundError:
        return False


def select_img(html: str, old_src: str | None, img_index: int | None):
    matches = list(IMG_RE.finditer(html))
    if not matches:
        raise SystemExit("fast-image: target slide has no <img>")
    if old_src:
        hits = [m for m in matches if old_src in m.group(2) or old_src in Path(m.group(2)).name]
        if len(hits) != 1:
            raise SystemExit(f"fast-image: --old-src matched {len(hits)} image(s), need exactly 1")
        return hits[0]
    if img_index is not None:
        if img_index < 1 or img_index > len(matches):
            raise SystemExit(f"fast-image: --img-index out of range 1..{len(matches)}")
        return matches[img_index - 1]
    if len(matches) == 1:
        return matches[0]
    raise SystemExit(
        f"fast-image: target slide has {len(matches)} images; pass --img-index N or --old-src FRAGMENT"
    )


def replace_src_in_tag(tag: str, new_src: str, alt: str | None) -> str:
    tag2, n = SRC_RE.subn(lambda m: f"src={m.group(1)}{new_src}{m.group(1)}", tag, count=1)
    if n != 1:
        raise SystemExit("fast-image: selected <img> has no replaceable src")
    if alt is None:
        return tag2
    if ALT_RE.search(tag2):
        return ALT_RE.sub(lambda m: f"alt={m.group(1)}{alt}{m.group(1)}", tag2, count=1)
    return tag2[:-1] + f' alt="{alt}">'


def replace_index(index_html: Path, old_src: str, new_src: str) -> int:
    if not index_html.exists():
        print(f"· {index_html.name} absent — deck.json updated; render when ready")
        return 0
    raw = index_html.read_text(encoding="utf-8")
    old_variants = list(dict.fromkeys([
        old_src,
        old_src.replace("../input/", "input/"),
        f"../{old_src}" if not old_src.startswith("../") else old_src[3:],
    ]))
    for old in old_variants:
        if raw.count(old) == 1:
            nw = new_src
            if old.startswith("../input/") and new_src.startswith("input/"):
                nw = f"../{new_src}"
            index_html.write_text(raw.replace(old, nw), encoding="utf-8")
            print(f"✓ {index_html.name}: 1 image src replacement (no render needed)")
            return 0
    counts = ", ".join(f"{v}={raw.count(v)}" for v in old_variants)
    print(
        f"! {index_html.name}: old src not uniquely replaceable ({counts}). "
        "deck.json IS updated; sync html with render-deck.py --scope <page> --shoot",
        file=sys.stderr,
    )
    return 3


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("deck", help="deck dir, deck.json, or index.html")
    ap.add_argument("slide", help="1-based page (#36/36) or slide key")
    ap.add_argument("image", help="new local image file")
    ap.add_argument("--img-index", type=int, help="1-based image index inside the target slide")
    ap.add_argument("--old-src", help="old src fragment or basename to identify the image")
    ap.add_argument("--name", help="output filename or stem under input/")
    ap.add_argument("--alt", help="replacement alt text")
    args = ap.parse_args(argv)

    deck_json, index_html = resolve(args.deck)
    if not deck_json.exists():
        print(f"fast-image: {deck_json} not found", file=sys.stderr)
        return 2

    try:
        deck = json.loads(deck_json.read_text(encoding="utf-8"))
        slides = deck.get("slides", [])
        idx = slide_index(slides, args.slide)
        slide = slides[idx]
        data = slide.setdefault("data", {})
        html = data.get("html", "")
        if not isinstance(html, str) or not html:
            raise SystemExit("fast-image: target slide has no data.html")
        new_src = copy_asset(deck_json.parent, Path(args.image).resolve(), args.name)
        match = select_img(html, args.old_src, args.img_index)
        old_src = match.group(2)
        new_tag = replace_src_in_tag(match.group(0), new_src, args.alt)
        new_html = html[:match.start()] + new_tag + html[match.end():]
        data["html"] = new_html
        deck_json.write_text(json.dumps(deck, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"✓ {deck_json.name}: slide {idx + 1} ({slide.get('key')}) img src {old_src} -> {new_src}")
        return replace_index(index_html, old_src, new_src)
    except SystemExit as e:
        print(e, file=sys.stderr)
        return 2
    except Exception as e:
        print(f"fast-image: REFUSED — {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
