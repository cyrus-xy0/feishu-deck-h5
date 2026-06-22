#!/usr/bin/env python3
"""
lift-to-new-deck.py — lift one (or more) slide(s) from a deck.json-native source
deck into a BRAND-NEW standalone deck, in one command.

WHY THIS EXISTS
---------------
The "开新 deck 复用某页" / LIFT+SWAP-into-a-new-deck flow had no first-class tool.
`deck-cli.py paste` already does the hard, correct per-slide copy — it follows a
key rename into the slide's embedded scoped CSS (F-255 `_rekey_slide_css`), strips
source-bound data-text-id, remaps retired CSS vars, stamps `lifted` provenance, and
copies referenced assets — but it can only paste INTO an existing deck.json. For a
new deck you first need an empty, schema-valid deck.json to paste into, and THAT
step had no command.

Hand-rolling that scaffold (build deck.json from scratch, set deck meta, rename the
slide key across hundreds of embedded CSS selectors by string-replace, then guess
render-deck.py's args) is slow and error-prone: a single bad `deck.mode` enum or a
forgotten CSS rekey breaks the render. This tool removes the hand-roll: it writes a
valid scaffold and then delegates every per-slide copy to the proven
`deck-cli.py paste`. No copy/rekey/asset logic is duplicated here.

USAGE
-----
    lift-to-new-deck.py SRC PAGES DEST [options]

    SRC    source deck — a deck.json, a deck directory (uses <dir>/deck.json), or
           an index.html (uses its sibling deck.json). For a LEGACY HTML-only deck
           with no deck.json, use assets/lift-slides.py instead (DOM-parse path).
    PAGES  which page(s) to lift, in locate-slide.py syntax: "46", "#46", a range
           "44-46", a list "44,2", a slide-key, or a title/label substring.
    DEST   destination directory for the NEW deck (created if missing). Refuses if
           it already holds a deck.json — adding to an existing deck is a job for
           `deck-cli.py paste`, not this tool.

    --title TITLE     deck title (default: derived from the first lifted slide).
    --new-key KEY     semantic slide-key for the lifted slide (ONLY when exactly
                      one page is lifted). paste rewrites it across the embedded CSS.
    --author NAME     deck author.
    --date  D         e.g. 2026.6.17.
    --slug  SLUG      customer_slug (default: DEST directory name).
    --mode  {rewrite,replica}   default rewrite (lift+swap re-authors content).
    --language {zh-only,zh-en}   default zh-only.
    --render          render to HTML after building (render-deck.py --final
                      --renumber, so screen_labels match true frame order).

EXAMPLE
-------
    # New single-page deck reusing ZhongAn page 46's layout:
    lift-to-new-deck.py /path/ZhongAn-AI/deck.json 46 runs/<ts>-foo/output \
        --title "医药代表的一天 · 一线推广知识图谱" --new-key medical-rep-day --render
    # then swap copy with deck-cli.py set-page / apply-text-pairs.py and re-render.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DECK_CLI = HERE / "deck-cli.py"
RENDER = HERE / "render-deck.py"
LOCATE = HERE / "locate-slide.py"


def _err(msg: str) -> None:
    print(f"lift-to-new-deck: {msg}", file=sys.stderr)


def resolve_source_deck(src: Path) -> Path | None:
    """Return the source deck.json path, or None (after printing why)."""
    if not src.exists():
        _err(f"source not found: {src}")
        return None
    if src.is_dir():
        cand = src / "deck.json"
        if not cand.exists():
            _err(f"no deck.json in source dir: {src}\n"
                 f"  (legacy HTML-only deck? use assets/lift-slides.py instead)")
            return None
        return cand
    if src.suffix == ".json":
        return src
    if src.suffix in (".html", ".htm"):
        cand = src.parent / "deck.json"
        if not cand.exists():
            _err(f"no sibling deck.json next to {src}\n"
                 f"  (foreign/legacy HTML deck? use assets/lift-slides.py instead)")
            return None
        return cand
    _err(f"unrecognized source (want deck.json / deck dir / index.html): {src}")
    return None


def resolve_pages(src_deck: Path, query: str) -> list[dict] | None:
    """Delegate page resolution to locate-slide.py (handles N/#N/range/list/key/title)."""
    r = subprocess.run([sys.executable, str(LOCATE), str(src_deck), query, "--json"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        _err(f"could not resolve pages '{query}' in {src_deck.name}:\n{r.stderr.strip()}")
        return None
    try:
        hits = json.loads(r.stdout or "[]")
    except json.JSONDecodeError:
        _err(f"locate-slide.py returned non-JSON for '{query}':\n{r.stdout[:200]}")
        return None
    if not hits:
        _err(f"no slides matched '{query}' in {src_deck.name}")
        return None
    return hits


def derive_title(hits: list[dict]) -> str:
    label = (hits[0].get("title") or hits[0].get("label") or "").strip()
    # strip a leading frame-number prefix like "46 " from a screen_label-derived label
    label = re.sub(r"^\d+\s+", "", label)
    return label or "〔标题 TODO〕"


# --- drift guard --------------------------------------------------------------
# Postmortem 2026-06-22 (everbright #7 → ai-into-org): lifting a page from an
# OLD deck whose per-slide CSS was never migrated out of the rendered index.html
# <head> (legacy `.slide[data-page="NN"]` scheme) silently produced a styleless,
# image-less page. resolve_source_deck() reads only the sibling deck.json, where
# that slide's custom_css is EMPTY — so paste/lift copy nothing and the head CSS
# + data-accent/data-decor (carried only on the rendered <div class="slide">) are
# lost with no error. The operator then reverse-engineers the recovery by hand
# (the ~15-call archaeology this guard exists to delete). We detect the drift up
# front and route to the blessed repair (repair-lifted → migrate-head-css).

_STYLE_BLOCK_RE = re.compile(r'<style\b([^>]*)>(.*?)</style>', re.S | re.I)


def _source_index_html(src: Path, src_deck: Path) -> Path | None:
    """The rendered index.html that may still hold drifted (head-scoped) per-slide
    CSS for the source deck — `src` itself when an index.html was passed, else the
    deck.json's sibling. None when there is no rendered HTML to inspect."""
    if src.suffix.lower() in (".html", ".htm"):
        return src if src.exists() else None
    cand = src_deck.parent / "index.html"
    return cand if cand.exists() else None


def _styling_lives_in_head(index_text: str, slide_key: str) -> bool:
    """True iff this slide's per-slide CSS lives in a HEAD <style> (legacy
    data-page / un-migrated scheme) rather than its deck.json custom_css — the
    'drifted deck.json' signature that makes a naive lift drop all styling.

    A correctly-homed slide keeps its deviation CSS in the co-located
    `<style data-fs-custom-css>` block INSIDE `.slide` (round-trips through
    deck.json custom_css); those are skipped. Any OTHER <style> carrying a
    selector keyed to this slide (`[data-slide-key="K"]` or the slide's legacy
    `[data-page="NN"]`) means the styling is stranded in the head."""
    keys = [f'[data-slide-key="{slide_key}"]']
    tag = re.search(
        r'<div\s+class="slide(?:\s[^"]*)?"[^>]*?\bdata-slide-key="'
        + re.escape(slide_key) + r'"[^>]*>', index_text)
    if tag:
        pm = re.search(r'\bdata-page="([^"]+)"', tag.group(0))
        if pm:
            keys.append(f'[data-page="{pm.group(1)}"]')
    for attrs, body in _STYLE_BLOCK_RE.findall(index_text):
        if 'data-fs-custom-css' in attrs:
            continue  # the CORRECT per-slide home (inside .slide) — not a leak
        if any(k in body for k in keys):
            return True
    return False


def detect_drifted(src: Path, src_deck: Path, hits: list[dict]) -> list[str]:
    """Return the keys of to-be-lifted slides whose styling is stranded in the
    source's rendered index.html <head> (empty deck.json custom_css). Empty when
    there is nothing to inspect or every page carries its own custom_css."""
    idx_html = _source_index_html(src, src_deck)
    if idx_html is None:
        return []
    try:
        slides = {s.get("key"): s for s in
                  json.loads(src_deck.read_text(encoding="utf-8")).get("slides", [])}
        idx_text = idx_html.read_text(encoding="utf-8")
    except Exception:
        return []
    return [h["key"] for h in hits
            if not (slides.get(h["key"], {}).get("custom_css") or "").strip()
            and _styling_lives_in_head(idx_text, h["key"])]


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        prog="lift-to-new-deck.py",
        description="Lift slide(s) from a deck.json-native source into a brand-new deck.")
    ap.add_argument("src", type=Path, help="source deck.json / deck dir / index.html")
    ap.add_argument("pages", help="page query (locate-slide.py syntax): 46, #46, 44-46, 44,2, key, title")
    ap.add_argument("dest", type=Path, help="destination directory for the NEW deck")
    ap.add_argument("--title", default=None)
    ap.add_argument("--new-key", dest="new_key", default=None,
                    help="semantic key for the lifted slide (only when lifting ONE page)")
    ap.add_argument("--author", default=None)
    ap.add_argument("--date", default=None)
    ap.add_argument("--slug", default=None, help="customer_slug (default: dest dir name)")
    ap.add_argument("--mode", choices=["rewrite", "replica"], default="rewrite")
    ap.add_argument("--language", choices=["zh-only", "zh-en"], default="zh-only")
    ap.add_argument("--render", action="store_true",
                    help="render to HTML after building (render-deck.py --final --renumber)")
    ap.add_argument("--allow-drift", action="store_true",
                    help="bypass the drift guard (source per-slide CSS stranded in "
                         "the rendered <head>); only when you will recover the CSS "
                         "yourself after the lift")
    args = ap.parse_args(argv)

    src_deck = resolve_source_deck(args.src)
    if src_deck is None:
        return 2

    hits = resolve_pages(src_deck, args.pages)
    if hits is None:
        return 1

    if args.new_key and len(hits) != 1:
        _err(f"--new-key is only valid when lifting exactly one page "
             f"(matched {len(hits)}: {', '.join(h['key'] for h in hits)})")
        return 1

    drifted = detect_drifted(args.src, src_deck, hits)
    if drifted and not args.allow_drift:
        _err(
            "源 deck.json 漂移:下列待拎页的 custom_css 为空,但样式留在 rendered "
            "index.html 的 <head>(legacy data-page 作用域)——\n"
            f"    {', '.join(drifted)}\n"
            "  裸 lift/paste 会静默丢掉它们的 CSS + accent/decor + 背景图(出无样式坏页)。\n"
            "  先修源 deck(把 head CSS 迁回各页 custom_css),再重跑本 lift:\n"
            f"    python3 {(HERE / 'repair-lifted.py').name} {src_deck.parent} --apply\n"
            "  repair-lifted 会路由 migrate-head-css-to-custom-css → 重渲;之后源页\n"
            "  custom_css 自带样式,lift/paste 即保真。\n"
            "  （确要手动恢复 CSS,可加 --allow-drift 跳过本检查。)")
        return 1

    dest_dir: Path = args.dest
    if dest_dir.exists() and not dest_dir.is_dir():
        _err(f"dest is not a directory: {dest_dir}")
        return 2
    dest_deck = dest_dir / "deck.json"
    if dest_deck.exists():
        _err(f"dest already has a deck.json: {dest_deck}\n"
             f"  this tool creates a NEW deck. To add a slide to an existing deck use:\n"
             f"  deck-cli.py paste --from {src_deck} --key <key> {dest_deck}")
        return 2

    # Carry the source's schema version forward; default to current.
    try:
        src_version = json.loads(src_deck.read_text(encoding="utf-8")).get("version", "1.0")
    except Exception:
        src_version = "1.0"

    title = args.title or derive_title(hits)
    slug = args.slug or dest_dir.name

    deck_meta = {"title": title, "customer_slug": slug,
                 "language": args.language, "mode": args.mode}
    if args.author:
        deck_meta["author"] = args.author
    if args.date:
        deck_meta["date"] = args.date

    # Scaffold: an empty deck.json. slides:[] is below schema minItems(1) and is
    # NEVER linted on its own — the first `paste` appends a slide and only THEN
    # deck-cli's write-back lints (now valid). deck-cli loads deck.json without a
    # load-time lint, so the empty scaffold is accepted as the paste target.
    dest_dir.mkdir(parents=True, exist_ok=True)
    scaffold = {"version": src_version, "deck": deck_meta, "slides": []}
    dest_deck.write_text(json.dumps(scaffold, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"lift-to-new-deck: new deck → {dest_deck}")
    print(f"  title: {title}")
    print(f"  lifting {len(hits)} page(s) from {src_deck.parent.name}/{src_deck.name}")

    for i, hit in enumerate(hits):
        # deck-cli signature: deck-cli.py [globals] <deck> <cmd> [cmd-args]
        # (the deck path is the FIRST positional, before the subcommand).
        cmd = [sys.executable, str(DECK_CLI), "--yes", str(dest_deck), "paste",
               "--from", str(src_deck), "--key", hit["key"]]
        if args.new_key:  # guaranteed len(hits)==1 here
            cmd += ["--new-key", args.new_key]
        r = subprocess.run(cmd, capture_output=True, text=True)
        sys.stdout.write(r.stdout)
        if r.returncode != 0:
            _err(f"paste of '{hit['key']}' failed (page {i + 1}/{len(hits)}):\n"
                 f"{r.stderr.strip()}")
            return r.returncode

    if args.render:
        print("lift-to-new-deck: rendering …")
        r = subprocess.run([sys.executable, str(RENDER), str(dest_deck), str(dest_dir),
                            "--final", "--renumber"])
        if r.returncode != 0:
            _err("render failed (deck.json is built; fix and re-render manually)")
            return r.returncode
        print(f"\n✔ done → {dest_dir / 'index.html'}")
    else:
        print(f"\n✔ deck.json built → {dest_deck}")
        print(f"  render:  python3 {RENDER.name} {dest_deck} {dest_dir} --final --renumber")

    print("  next — swap copy in place, then re-render:")
    print(f"    python3 deck-cli.py set-page <key> --from-file frag.html   # or apply-text-pairs.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
