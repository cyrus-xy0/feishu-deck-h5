#!/usr/bin/env python3
"""import-html-slide.py — interactively import local HTML slide fragments into a deck.

Two modes:

  Mode A (target = deck.json, recommended) — wraps each imported slide as
    `{layout: "raw", data: {html, _orig_layout}}` and appends/inserts into
    slides[]. Auto-re-renders via render-deck.py so the new index.html
    reflects the import.

  Mode B (target = .html file, deck.json absent) — directly splices
    `<div class="slide-frame">...</div>` blocks into the target deck's
    `<div class="deck">`. No json roundtrip. Useful for legacy decks.

Interactive flow:
  1. Pick target (current dir's deck.json / index.html / both shown).
  2. Pick source .html file(s) — multi-select.
  3. Each candidate slide passes validate.py. Clean → silent insert.
     Violations → list issues + ask: insert anyway / skip / abort.
  4. Pick position (numeric slide index, end, or after-key).
  5. Apply + (mode A) re-render.

Flags:
  --strict    Any compliance issue → abort, no prompt (default: prompt).
  --yes       Skip prompts (insert anyway, append at end).

stdlib only. Python 3.11+.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import shutil
from datetime import datetime
from pathlib import Path

HERE          = Path(__file__).resolve().parent
SKILL_ROOT    = HERE.parent
ASSETS_DIR    = SKILL_ROOT / "assets"
VALIDATE_HTML = ASSETS_DIR / "validate.py"
RENDER_DECK   = HERE / "render-deck.py"


# ──────────────────────────────────────────────────────── helpers

def _info(msg: str) -> None:  print(f"  {msg}", file=sys.stderr)
def _warn(msg: str) -> None:  print(f"  ⚠ {msg}", file=sys.stderr)
def _err(msg: str) -> None:   print(f"  ✗ {msg}", file=sys.stderr)
def _ok(msg: str) -> None:    print(f"  ✓ {msg}", file=sys.stderr)


def prompt(question: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default is not None else ""
    while True:
        try:
            ans = input(f"  {question}{suffix} > ").strip()
        except (EOFError, KeyboardInterrupt):
            print(file=sys.stderr); raise SystemExit("aborted by user")
        if not ans and default is not None:
            return default
        if ans:
            return ans


def prompt_choice(question: str, choices: list[str], default: str = "") -> str:
    while True:
        ans = prompt(f"{question} ({'/'.join(choices)})", default=default).lower()
        if ans in [c.lower() for c in choices]:
            return ans


# ──────────────────────────────────────────────────────── target detection

def detect_target(path: Path) -> tuple[Path, str]:
    """Returns (resolved_path, mode) where mode is 'A' (deck.json) or 'B' (html)."""
    p = path.resolve()
    if p.is_file():
        if p.suffix == ".json":
            return p, "A"
        if p.suffix == ".html":
            # If deck.json sits next to it, prefer A
            sibling = p.parent / "deck.json"
            if sibling.is_file():
                _info(f"Found {sibling.name} next to target HTML → using Mode A (deck.json).")
                return sibling, "A"
            return p, "B"
    raise SystemExit(f"target not found or unsupported: {p}")


def pick_target_interactive() -> tuple[Path, str]:
    cwd = Path.cwd()
    cands: list[Path] = []
    # Highest priority: deck.json in cwd
    if (cwd / "deck.json").is_file():
        cands.append(cwd / "deck.json")
    # Sibling deck.jsons in subdirs (1 level)
    cands.extend(cwd.glob("*/deck.json"))
    cands.extend(cwd.glob("*/output/deck.json"))
    # HTML files in cwd
    cands.extend(cwd.glob("*.html"))
    cands.extend(cwd.glob("*/index.html"))
    cands.extend(cwd.glob("*/output/index.html"))
    cands = sorted({c.resolve() for c in cands if c.is_file()})

    if not cands:
        raise SystemExit("no deck.json or .html found in current dir or 1-level subdirs. "
                         "Pass target explicitly: import-html-slide.py <path>")
    print("\n  Available targets:", file=sys.stderr)
    for i, c in enumerate(cands, 1):
        kind = "JSON" if c.suffix == ".json" else "HTML"
        try:
            rel = c.relative_to(cwd)
        except ValueError:
            rel = c
        print(f"    [{i}] {kind} · {rel}", file=sys.stderr)

    while True:
        ans = prompt("Pick target (number)")
        try:
            idx = int(ans) - 1
            if 0 <= idx < len(cands):
                return detect_target(cands[idx])
        except ValueError:
            pass
        _err("invalid number, try again")


# ──────────────────────────────────────────────────────── source picker

def pick_sources_interactive() -> list[Path]:
    cwd = Path.cwd()
    cands = sorted({p.resolve() for p in cwd.glob("*.html")
                    if p.name != "index.html" or p.parent == cwd})
    # also offer 1-level subdir HTML
    cands += sorted({p.resolve() for p in cwd.glob("*/*.html")})
    cands = list(dict.fromkeys(cands))   # dedupe preserve-order

    if not cands:
        raise SystemExit("no .html files found in cwd or 1-level subdirs to import.")

    print("\n  Source HTML candidates:", file=sys.stderr)
    for i, c in enumerate(cands, 1):
        try:
            rel = c.relative_to(cwd)
        except ValueError:
            rel = c
        # count slide-frame blocks
        try:
            text = c.read_text(encoding="utf-8")
            n = len(re.findall(r'<div\s+class="slide-frame"', text))
        except Exception:
            n = 0
        nstr = f"({n} slide{'s' if n != 1 else ''})" if n else "(no slide-frame found)"
        print(f"    [{i}] {rel}  {nstr}", file=sys.stderr)

    while True:
        ans = prompt("Pick source files (e.g. 1,3 or 'all' or '1-3')")
        picked = _parse_picks(ans, len(cands))
        if picked:
            return [cands[i] for i in picked]
        _err("invalid selection, try again")


def _parse_picks(s: str, n: int) -> list[int]:
    """Parse '1,3,5' or '1-3' or 'all' into 0-indexed positions."""
    s = s.strip().lower()
    if not s:
        return []
    if s == "all":
        return list(range(n))
    out: set[int] = set()
    for chunk in s.split(","):
        chunk = chunk.strip()
        if "-" in chunk:
            try:
                a, b = chunk.split("-", 1)
                for k in range(int(a) - 1, int(b)):
                    if 0 <= k < n:
                        out.add(k)
            except ValueError:
                return []
        else:
            try:
                k = int(chunk) - 1
                if 0 <= k < n:
                    out.add(k)
            except ValueError:
                return []
    return sorted(out)


# ──────────────────────────────────────────────────────── slide extraction

SLIDE_FRAME_RE = re.compile(
    r'<div\s+class="slide-frame"[^>]*>.*?</div>\s*</div>',
    re.S,
)
# Alternative: catch slides wrapped without slide-frame (just `<div class="slide">`)
LOOSE_SLIDE_RE = re.compile(
    r'<div\s+class="slide"[^>]*>.*?</div>\s*(?=<div\s+class="slide"|</div>|$)',
    re.S,
)


def extract_slide_frames(html_text: str) -> list[str]:
    """Pull all <div class="slide-frame">...</div>...</div> blocks.

    Brace-counts to find the matching close of the outer slide-frame div,
    since slide-frame contains a nested .slide div with arbitrary children.
    """
    out: list[str] = []
    i = 0
    open_re = re.compile(r'<div\s+class="slide-frame"[^>]*>', re.S)
    while True:
        m = open_re.search(html_text, i)
        if not m:
            break
        start = m.start()
        # Walk forward counting <div ...> vs </div>, starting at +1 depth
        depth = 1
        j = m.end()
        while j < len(html_text) and depth > 0:
            tag = re.match(r'<div[\s>]', html_text[j:])
            close = re.match(r'</div>', html_text[j:])
            if close:
                depth -= 1
                j += len(close.group(0))
            elif tag:
                depth += 1
                # advance to past the opening tag
                end_of_tag = html_text.find(">", j)
                j = end_of_tag + 1 if end_of_tag > 0 else j + 1
            else:
                j += 1
        if depth == 0:
            out.append(html_text[start:j])
            i = j
        else:
            break
    return out


def slide_key_in(frag: str) -> str | None:
    m = re.search(r'data-slide-key="([^"]+)"', frag)
    return m.group(1) if m else None


def data_layout_in(frag: str) -> str | None:
    m = re.search(r'data-layout="([^"]+)"', frag)
    return m.group(1) if m else None


# ──────────────────────────────────────────────────────── validate via validate.py

SHELL_TEMPLATE = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>fragment validation</title>
  <link rel="stylesheet" href="{css_path}">
</head>
<body>
  <div class="deck">
{slide_html}
  </div>
  <script src="{js_path}"></script>
</body>
</html>
"""


def validate_slide_fragment(frag: str, strict: bool = False) -> tuple[bool, list[str]]:
    """Build a temp full-deck HTML with just this slide, run validate.py.

    Returns (is_compliant, issue_lines). issue_lines are the human-readable
    rule violations from validate.py's output, stripped of noise.
    """
    css = ASSETS_DIR / "feishu-deck.css"
    js  = ASSETS_DIR / "feishu-deck.js"
    shell_html = SHELL_TEMPLATE.format(
        css_path=str(css), js_path=str(js), slide_html=frag,
    )
    with tempfile.NamedTemporaryFile(
        mode="w", suffix="-validate.html", delete=False, encoding="utf-8"
    ) as f:
        f.write(shell_html)
        tmp_path = Path(f.name)
    try:
        argv = [sys.executable, str(VALIDATE_HTML), str(tmp_path)]
        if strict:
            argv.append("--strict")
        proc = subprocess.run(argv, capture_output=True, text=True)
        issues = []
        # Rules that don't apply to a single-slide fragment validation:
        #   T03 — texts.md sidecar (deck-level, generated only for full decks)
        #   R-FEEDBACK — FEEDBACK.md sidecar (delivery-level)
        #   P50-P55 — perf budget (whole-deck level)
        FRAGMENT_IRRELEVANT = re.compile(r'\[(T03|R-FEEDBACK|P5\d)\]')
        for line in (proc.stdout + proc.stderr).splitlines():
            line = line.rstrip()
            if FRAGMENT_IRRELEVANT.search(line):
                continue
            if re.match(r'^\s*(?:✗|!|\[R-?\w+\])', line):
                issues.append(line.strip())
            elif "violation" in line.lower() or "fail" in line.lower():
                issues.append(line.strip())
        # If we filtered out ALL the noise, consider it compliant even if
        # validate.py's exit code was non-zero (the residual error was just T03/etc).
        is_compliant = proc.returncode == 0 or len(issues) == 0
        return is_compliant, issues
    finally:
        try: tmp_path.unlink()
        except OSError: pass


# ──────────────────────────────────────────────────────── interactive resolver

def resolve_compliance(name: str, idx: int, frag: str,
                       issues: list[str], strict: bool,
                       auto_yes: bool) -> str:
    """Returns 'insert' | 'skip' | 'abort'."""
    if not issues:
        return "insert"
    print(file=sys.stderr)
    _warn(f"{name}.slide[{idx}] (key='{slide_key_in(frag) or '?'}') "
          f"has {len(issues)} compliance issue(s):")
    for line in issues[:12]:
        _err(line)
    if len(issues) > 12:
        _info(f"... ({len(issues) - 12} more)")
    if strict:
        _err("--strict: aborting on first violation")
        return "abort"
    if auto_yes:
        _info("--yes: inserting anyway")
        return "insert"
    ans = prompt_choice(
        "Insert this slide anyway? (y=insert as-is, n=skip, a=abort run)",
        ["y", "n", "a"], default="n"
    )
    return {"y": "insert", "n": "skip", "a": "abort"}[ans]


# ──────────────────────────────────────────────────────── position picker

def pick_position_interactive(slides: list[dict | str]) -> int:
    """Returns 0-indexed insert position (0 = before first, len = end)."""
    print("\n  Current slides in target:", file=sys.stderr)
    for i, s in enumerate(slides, 1):
        if isinstance(s, dict):
            label = s.get("key", "<no key>")
            extra = f" [{s.get('layout', '?')}]"
        else:
            # mode B: s is a slide-frame fragment string
            label = slide_key_in(s) or "<no key>"
            extra = f" [{data_layout_in(s) or '?'}]"
        print(f"    [{i}] {label}{extra}", file=sys.stderr)
    print(f"    [end] append at position {len(slides) + 1}", file=sys.stderr)

    while True:
        ans = prompt("Insert imported slides at position", default="end")
        if ans == "end":
            return len(slides)
        try:
            n = int(ans)
            if 1 <= n <= len(slides) + 1:
                return n - 1
        except ValueError:
            pass
        _err("invalid number, try again")


# ──────────────────────────────────────────────────────── insertion · Mode A (JSON)

def _unique_key(base: str, taken: set[str]) -> str:
    if base not in taken:
        return base
    n = 2
    while f"{base}-imported-{n}" in taken:
        n += 1
    return f"{base}-imported-{n}"


def _strip_slide_wrappers(frag: str) -> tuple[str, dict]:
    """Pull out the data-* attrs from the `.slide` element and return
    (inner_html, attrs). inner_html is everything between the .slide's
    opening and closing tags, minus the wordmark (renderer adds its own).

    This avoids nested slide-frame when wrapping as `layout: raw` — the
    renderer's raw.fragment.html provides its own outer .slide-frame + .slide,
    so we keep ONLY the inner DOM tree of the original slide.
    """
    # Match the .slide opening tag and capture its attributes
    m_open = re.search(r'<div\s+class="slide"([^>]*)>', frag)
    if not m_open:
        return frag, {}
    open_end = m_open.end()
    # Walk to matching close (depth-counted, since .slide may contain nested divs)
    depth = 1
    j = open_end
    while j < len(frag) and depth > 0:
        nxt_open  = re.search(r'<div[\s>]', frag[j:])
        nxt_close = re.search(r'</div>', frag[j:])
        if not nxt_close:
            break
        if nxt_open and nxt_open.start() < nxt_close.start():
            depth += 1
            j += nxt_open.end()
        else:
            depth -= 1
            close_end = j + nxt_close.end()
            if depth == 0:
                inner = frag[open_end:j + nxt_close.start()]
                # Strip leading <div class="wordmark">飞书</div> — renderer re-emits it
                inner = re.sub(r'\s*<div\s+class="wordmark"[^>]*>[^<]*</div>\s*',
                               '\n', inner, count=1)
                # Parse attrs from open tag
                attrs = {}
                for a in re.finditer(r'data-([\w-]+)="([^"]*)"', m_open.group(1)):
                    attrs[a.group(1)] = a.group(2)
                return inner.strip("\n"), attrs
            j = close_end
    return frag, {}


def _renumber_text_ids(html: str, new_slide_no: int) -> str:
    """Imported HTML carries `data-text-id="slide-NN.field"` baked in from
    its source position. After insertion the slide's position changes, so
    we rewrite NN → new_slide_no (zero-padded). Both `data-text-id` and
    inline `id=` get rewritten."""
    padded = f"{new_slide_no:02d}"
    out = re.sub(
        r'data-text-id="slide-\d+\.',
        f'data-text-id="slide-{padded}.',
        html,
    )
    out = re.sub(r'\bid="slide-\d+\.', f'id="slide-{padded}.', out)
    return out


def insert_into_json(deck_path: Path, fragments: list[str], position: int) -> None:
    deck = json.loads(deck_path.read_text(encoding="utf-8"))
    existing_keys = {s.get("key") for s in deck["slides"]}
    new_slides = []
    for offset, frag in enumerate(fragments):
        inner, attrs = _strip_slide_wrappers(frag)
        # Renumber text-ids to match the final position after insertion
        # (1-indexed; position is 0-indexed insert point)
        new_pos = position + offset + 1
        inner = _renumber_text_ids(inner, new_pos)

        raw_key = attrs.get("slide-key") or slide_key_in(frag) or f"imported-{datetime.now():%H%M%S}"
        orig_layout = attrs.get("layout") or "raw"
        new_key = _unique_key(raw_key, existing_keys)
        existing_keys.add(new_key)

        # `_orig_layout` lives at slide level (schema 'slide.properties'),
        # NOT inside data — `_enrich_raw` reads `slide.get('_orig_layout')`.
        new_slide: dict = {
            "key": new_key,
            "layout": "raw",
            "_orig_layout": orig_layout,
            "data": {
                "html": inner,
            },
        }
        # Preserve original accent / decor on the new wrapping slide so
        # framework CSS rules still engage (`.slide[data-accent="teal"] ...`).
        if attrs.get("accent"):
            new_slide["accent"] = attrs["accent"]
        if attrs.get("decor"):
            new_slide["decor"] = attrs["decor"].split()
        if attrs.get("screen-label"):
            new_slide["screen_label"] = attrs["screen-label"]
        new_slides.append(new_slide)

    # Backup before write
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    bak = deck_path.with_suffix(f".json.bak-pre-import-{ts}")
    shutil.copy(deck_path, bak)
    _info(f"backup at {bak.name}")

    deck["slides"][position:position] = new_slides
    deck_path.write_text(
        json.dumps(deck, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _ok(f"inserted {len(new_slides)} slide(s) into {deck_path.name} at position {position + 1}")


def re_render(deck_path: Path) -> None:
    out_dir = deck_path.parent
    _info(f"re-rendering → {out_dir}")
    proc = subprocess.run(
        [sys.executable, str(RENDER_DECK), str(deck_path), str(out_dir)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        _err("re-render failed:")
        _err(proc.stdout + proc.stderr)
        return
    _ok("re-render OK")


# ──────────────────────────────────────────────────────── insertion · Mode B (HTML)

def insert_into_html(target_path: Path, fragments: list[str], position: int) -> None:
    text = target_path.read_text(encoding="utf-8")
    existing_frames = extract_slide_frames(text)
    if not existing_frames:
        raise SystemExit(f"target {target_path.name} has no <div class='slide-frame'>; "
                         f"can't determine insertion point")
    # Ensure new slide keys don't collide
    existing_keys = {slide_key_in(f) for f in existing_frames if slide_key_in(f)}
    renamed = []
    for frag in fragments:
        k = slide_key_in(frag)
        if k and k in existing_keys:
            new_k = _unique_key(k, existing_keys)
            frag = re.sub(
                rf'data-slide-key="{re.escape(k)}"',
                f'data-slide-key="{new_k}"',
                frag, count=1,
            )
            _info(f"slide-key collision: '{k}' → '{new_k}'")
            existing_keys.add(new_k)
        renamed.append(frag)

    # Decide where to splice. Find the n-th slide-frame's end offset.
    open_re = re.compile(r'<div\s+class="slide-frame"[^>]*>')
    matches = list(open_re.finditer(text))
    if position >= len(matches):
        # End mode — insert before </div> of the .deck wrapper
        deck_close = re.search(r'(\s*)</div>\s*(<script|</body>)', text)
        if deck_close:
            insert_at = deck_close.start(1)
        else:
            insert_at = len(text)
    else:
        # Insert BEFORE the slide-frame at `position`
        insert_at = matches[position].start()

    block = "\n" + "\n".join(renamed) + "\n"

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    bak = target_path.with_suffix(f".html.bak-pre-import-{ts}")
    shutil.copy(target_path, bak)
    _info(f"backup at {bak.name}")

    target_path.write_text(text[:insert_at] + block + text[insert_at:], encoding="utf-8")
    _ok(f"inserted {len(renamed)} slide(s) into {target_path.name} at position {position + 1}")


# ──────────────────────────────────────────────────────── main

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="import-html-slide.py",
                                  description=__doc__.split("\n")[0])
    ap.add_argument("target", type=Path, nargs="?", default=None,
                    help="deck.json (Mode A) or index.html (Mode B). Interactive picker if omitted.")
    ap.add_argument("source", type=Path, nargs="*", default=[],
                    help=".html files to import. Interactive picker if omitted.")
    ap.add_argument("--strict", action="store_true",
                    help="Any compliance issue → abort (default: prompt per slide).")
    ap.add_argument("--yes", action="store_true",
                    help="Skip prompts. Insert violations as-is. Append at end.")
    args = ap.parse_args(argv)

    # Resolve target
    if args.target is None:
        target, mode = pick_target_interactive()
    else:
        target, mode = detect_target(args.target)
    _info(f"target = {target}  (Mode {mode})")

    # Resolve sources
    if not args.source:
        sources = pick_sources_interactive()
    else:
        sources = [s.resolve() for s in args.source]
        for s in sources:
            if not s.is_file():
                raise SystemExit(f"source not found: {s}")
    _info(f"sources: {len(sources)} file(s)")

    # Extract + validate each slide-frame from each source
    accepted: list[str] = []
    for src in sources:
        text = src.read_text(encoding="utf-8")
        frags = extract_slide_frames(text)
        if not frags:
            _warn(f"{src.name}: no <div class='slide-frame'> found, skipping")
            continue
        _info(f"{src.name}: {len(frags)} slide-frame(s) found")
        for i, frag in enumerate(frags):
            ok, issues = validate_slide_fragment(frag, strict=args.strict)
            verdict = resolve_compliance(src.name, i, frag, issues,
                                          strict=args.strict, auto_yes=args.yes)
            if verdict == "insert":
                if ok:
                    _ok(f"{src.name}[{i}] '{slide_key_in(frag) or '?'}' clean, queued")
                else:
                    _info(f"{src.name}[{i}] inserted with {len(issues)} known issues")
                accepted.append(frag)
            elif verdict == "skip":
                _info(f"{src.name}[{i}] skipped")
            else:                                  # abort
                raise SystemExit("aborted on compliance issue (--strict)")

    if not accepted:
        _warn("no slides queued for import. nothing to do.")
        return 0

    # Pick position
    if mode == "A":
        deck = json.loads(target.read_text(encoding="utf-8"))
        slides_view = deck["slides"]
    else:
        text = target.read_text(encoding="utf-8")
        slides_view = extract_slide_frames(text)

    if args.yes:
        position = len(slides_view)
    else:
        position = pick_position_interactive(slides_view)

    # Apply
    if mode == "A":
        insert_into_json(target, accepted, position)
        re_render(target)
    else:
        insert_into_html(target, accepted, position)

    _ok("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
