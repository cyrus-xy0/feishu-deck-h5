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

By default the importer also:
  • copies every LOCAL asset a slide references (img / iframe / video / url(),
    one level of iframe-body recursion) into `assets/imported/<src>/…` and
    rewrites the refs, so a slide pulled out of another deck doesn't 404; and
  • marks each imported slide `lifted:true` (it IS verbatim from another deck),
    so the validator warns — not fails — on that deck's off-ladder font sizes.

Flags:
  --strict           Any compliance issue → abort, no prompt (default: prompt).
  --yes              Skip prompts (insert anyway, append at end).
  --key KEY          Import only the slide-frame(s) with this data-slide-key —
                     pull ONE page out of a multi-slide montage.
  --index N          Import only the 1-based N-th slide-frame of each source.
  --no-lifted        Don't mark imported slides lifted (face the full font gate).
  --no-copy-assets   Don't copy/rewrite local assets (leave refs as-authored).

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

sys.path.insert(0, str(HERE))
from _safe_write import (                                  # noqa: E402
    validate_and_write_deck, restore_deck, contained_dest, atomic_write_text,
)


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


# ──────────────────────────────────────────────────────── asset copy + rewrite
# Mirror of lift-slides.py's _ASSET_REF_PATTERNS / _is_local_asset_ref (kept local
# to avoid importing across a hyphenated filename). SAME scanner the F-76 lift
# asset-copy fix standardized on, so url() / <img> / <iframe> / <video> / <source>
# refs all get carried — not just url(). An imported slide otherwise lands with
# refs relative to the SOURCE file (e.g. `tongdianjuli/input/x.jpeg`) that resolve
# to nothing under the target deck → silent 404s. We copy them in + rewrite.
_ASSET_REF_PATTERNS = (
    re.compile(r'''<iframe\b[^>]*?\bsrc\s*=\s*['"]([^'"]+)['"]''', re.I),
    re.compile(r'''<img\b[^>]*?\bsrc\s*=\s*['"]([^'"]+)['"]''', re.I),
    re.compile(r'''<source\b[^>]*?\bsrc\s*=\s*['"]([^'"]+)['"]''', re.I),
    re.compile(r'''<video\b[^>]*?\b(?:src|poster)\s*=\s*['"]([^'"]+)['"]''', re.I),
    re.compile(r'''url\(\s*['"]?([^'")]+?)['"]?\s*\)''', re.I),
)


def _is_local_asset_ref(url: str) -> bool:
    """True for refs to resolve against the source dir; False for self-contained
    (data:) / external (http) / in-page (#) refs."""
    u = (url or "").strip()
    if not u:
        return False
    low = u.lower()
    return not low.startswith(("data:", "http://", "https://", "//", "mailto:",
                               "tel:", "javascript:", "blob:", "#", "about:"))


def _strip_dotslash(u: str) -> str:
    while u.startswith("./"):
        u = u[2:]
    return u


def _slug(s: str) -> str:
    s = re.sub(r'\.[A-Za-z0-9]+$', '', s)                 # drop extension
    s = re.sub(r'[^\w-]+', '-', s).strip('-').lower()     # \w keeps CJK; spaces/dots → -
    return s or "src"


def _scan_local_refs(text: str) -> list[str]:
    """Distinct local asset refs in `text` (?query/#hash stripped), doc order."""
    seen: set[str] = set()
    out: list[str] = []
    for pat in _ASSET_REF_PATTERNS:
        for m in pat.finditer(text):
            base = m.group(1).strip().split("?", 1)[0].split("#", 1)[0]
            if _is_local_asset_ref(base) and base not in seen:
                seen.add(base)
                out.append(base)
    return out


def _rewrite_refs(text: str, mapping: dict[str, str]) -> str:
    """Replace each mapped ref (the regex capture) with its new path, in place,
    so ?query / #hash suffixes survive."""
    def make_repl(_pat):
        def repl(m):
            whole = m.group(0)
            u = m.group(1).strip()
            base = u.split("?", 1)[0].split("#", 1)[0]
            if base in mapping:
                return whole.replace(u, mapping[base] + u[len(base):])
            return whole
        return repl
    for pat in _ASSET_REF_PATTERNS:
        text = pat.sub(make_repl(pat), text)
    return text


def copy_and_rewrite_assets(frag: str, src_dir: Path, deck_dir: Path,
                            src_stem: str) -> tuple[str, list[str], list[str]]:
    """Copy every LOCAL asset a slide references into the target deck under
    `assets/imported/<src-slug>/…` (sub-paths preserved) and rewrite the refs to
    match. One-level recursion: an iframe/.html body ALSO gets its own local refs
    copied alongside it (the phone-mockup case), left relative so they still
    resolve. Returns (new_frag, copied_rel_paths, missing_refs)."""
    ns = f"assets/imported/{_slug(src_stem)}"
    copied: list[str] = []
    missing: list[str] = []
    mapping: dict[str, str] = {}
    deck_root = deck_dir.resolve()
    for ref in _scan_local_refs(frag):
        src_path = (src_dir / _strip_dotslash(ref)).resolve()
        if not src_path.is_file():
            missing.append(ref)
            continue
        dest_rel = f"{ns}/{_strip_dotslash(ref)}"
        # Containment guard (mutation-3): a `../`-bearing ref must never let the
        # copy escape the deck dir. The inner-iframe recursion already guards;
        # mirror it on the primary loop too.
        dest_path = contained_dest(deck_dir, dest_rel)
        if dest_path is None:
            missing.append(ref)
            continue
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_path, dest_path)
        mapping[ref] = dest_rel
        copied.append(dest_rel)
        # one-level recursion for an iframe/.html body's own assets
        if src_path.suffix.lower() in (".html", ".htm"):
            try:
                inner = src_path.read_text(encoding="utf-8")
            except OSError:
                inner = ""
            for r2 in _scan_local_refs(inner):
                s2 = (src_path.parent / _strip_dotslash(r2)).resolve()
                if not s2.is_file():
                    continue
                d2 = dest_path.parent / _strip_dotslash(r2)
                try:
                    d2.resolve().relative_to(deck_root)        # never write outside deck
                except ValueError:
                    continue
                d2.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(s2, d2)
                copied.append(str(d2.relative_to(deck_dir)))
    return _rewrite_refs(frag, mapping), copied, missing


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
        #   P50-P55 — perf budget (whole-deck level)
        FRAGMENT_IRRELEVANT = re.compile(r'\[(P5\d)\]')
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


def _slugify_key(raw: str) -> str:
    """Normalize a (possibly foreign) slide-key to the schema slug pattern
    ^[a-z][a-z0-9-]*$: lowercase, non-[a-z0-9] → '-', collapse/trim dashes,
    ensure a leading letter. 'Feiling_Product' → 'feiling-product'; a
    digit-leading key → 'imported-<key>'; empty → 'imported'. Without this a
    foreign data-slide-key was copied verbatim → the schema gate rejected the
    whole deck.json → no index.html produced after the destructive insert."""
    s = re.sub(r'[^a-z0-9]+', '-', (raw or '').lower()).strip('-')
    if not s:
        return 'imported'
    if not s[0].isalpha():
        s = 'imported-' + s
    return s


def _strip_slide_wrappers(frag: str) -> tuple[str, dict]:
    """Pull out the data-* attrs from the `.slide` element and return
    (inner_html, attrs). inner_html is everything between the .slide's
    opening and closing tags, minus the wordmark (renderer adds its own).

    This avoids nested slide-frame when wrapping as `layout: raw` — the
    renderer's raw.fragment.html provides its own outer .slide-frame + .slide,
    so we keep ONLY the inner DOM tree of the original slide.
    """
    # Match the .slide opening tag and capture its attributes
    m_open = re.search(r'<div\s+class="slide(?:\s[^"]*)?"([^>]*)>', frag)
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


def insert_into_json(deck_path: Path, fragments: list[str], position: int,
                     lifted: bool = True, allow_unsynced: bool = False,
                     force: bool = False) -> tuple[Path | None, str | None]:
    """Splice imported slides into deck.json with the validated-write contract.

    Returns (bak, orig_text) so the caller can `restore_deck` the SSOT if a LATER
    step (the re-render) fails. On schema validation failure the write itself is
    rolled back here (validate_and_write_deck) and we raise SystemExit.
    """
    # F-315 (Option A): this mutates deck.json then re-renders, which regenerates
    # index.html. If the sibling index.html carries un-synced browser/hand edits,
    # that re-render would silently destroy them. Resolve BEFORE reading deck.json
    # (so an auto-sync's folded edits are picked up by the read below):
    #   ok → proceed · autosync (all-lossless) → fold into deck.json first ·
    #   refuse (canvas/baked/chrome/error) → stop. --force skips & discards.
    if not allow_unsynced:
        import sys as _sys
        _sys.path.insert(0, str(HERE))
        from _index_sig import resolve_clobber as _idx_resolve, auto_sync as _idx_auto_sync
        _idx = deck_path.parent / "index.html"
        _action, _reason = _idx_resolve(deck_path, _idx)
        if _action == "refuse":
            _sync = HERE / "sync-index-to-deck.py"
            raise SystemExit(
                f"import-html-slide: REFUSING — {_reason}\n"
                f"  → Inspect: python3 {_sync} --dry-run {_idx} {deck_path}\n"
                f"  → Or re-run with --force to import anyway and DISCARD them.")
        if _action == "autosync":
            _info("index.html has un-synced (lossless) browser edits — folding them "
                  "into deck.json before import…")
            # NB: do NOT bind `_ok` here — that name is the module-level success
            # logger used at the end of this function; assigning it locally would
            # shadow it for the whole scope (UnboundLocalError on the later call).
            _synced, _out = _idx_auto_sync(deck_path, _idx)
            if not _synced:
                raise SystemExit(f"import-html-slide: auto-sync FAILED:\n{_out}")
            # folded; the json.loads below now sees the synced deck.json
    # Optimistic lock (mutation-6): capture mtime at the read below; if deck.json
    # changes on disk between this read and our write, another session edited it —
    # refuse rather than silently clobber. --force bypasses.
    expected_mtime = deck_path.stat().st_mtime
    deck = json.loads(deck_path.read_text(encoding="utf-8"))
    if not isinstance(deck.get("slides"), list):
        raise SystemExit(f"{deck_path.name}: malformed deck.json — missing/invalid "
                         f"'slides' array")
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
        new_key = _unique_key(_slugify_key(raw_key), existing_keys)
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
        # An imported HTML slide is verbatim from ANOTHER deck → mark lifted so the
        # validator downgrades that deck's font-tier choices (off-ladder sizes,
        # custom header position …) to warnings instead of failing the gate on
        # content the user explicitly chose to bring in as-is. `--no-lifted` opts
        # out when the user wants the slide treated as native + fully re-gated.
        if lifted:
            new_slide["lifted"] = True
        new_slides.append(new_slide)

    # Optimistic-lock check (mutation-6): refuse if deck.json changed on disk
    # since we read it above (another concurrent edit). --force bypasses.
    if not force:
        if not deck_path.exists():
            raise SystemExit(
                f"import-html-slide: REFUSING — {deck_path.name} was DELETED on disk "
                f"since it was read (concurrent edit). Re-run, or pass --force.")
        cur_mtime = deck_path.stat().st_mtime
        if abs(cur_mtime - expected_mtime) > 1e-6:
            raise SystemExit(
                f"import-html-slide: REFUSING — {deck_path.name} changed on disk since "
                f"it was read (concurrent edit by another process). Re-run, or pass "
                f"--force to overwrite.")

    # Backup the pre-write state ourselves so the CALLER can restore the SSOT if a
    # LATER step (the re-render) fails. validate_and_write_deck then does the
    # atomic write + schema re-validate + rollback-on-schema-fail (mutation-1/5),
    # so we tell it no_backup=True to avoid a redundant second .bak.
    orig_text = deck_path.read_text(encoding="utf-8") if deck_path.exists() else None
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    bak = deck_path.with_suffix(f".json.bak-pre-import-{ts}")
    shutil.copy(deck_path, bak)
    _info(f"backup at {bak.name}")

    deck["slides"][position:position] = new_slides
    if not validate_and_write_deck(deck_path, deck, "import", no_backup=True):
        # validate_and_write_deck already restored the prior content (in-memory
        # copy, since no_backup) and printed the schema errors — our .bak survives
        # for manual recovery, but the SSOT is back to its pre-import state.
        raise SystemExit(
            f"import-html-slide: the spliced deck.json failed schema validation "
            f"and was rolled back. No change written. Backup at {bak.name}.")
    _ok(f"inserted {len(new_slides)} slide(s) into {deck_path.name} at position {position + 1}")
    return bak, orig_text


def re_render(deck_path: Path) -> int:
    out_dir = deck_path.parent
    _info(f"re-rendering → {out_dir}")
    proc = subprocess.run(
        [sys.executable, str(RENDER_DECK), str(deck_path), str(out_dir)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        _err("re-render failed:")
        _err(proc.stdout + proc.stderr)
        return proc.returncode
    _ok("re-render OK")
    return 0


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

    # mutation-5 / F-269: atomic write so a kill mid-write can't torn the file.
    atomic_write_text(target_path, text[:insert_at] + block + text[insert_at:])
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
    ap.add_argument("--key", default=None,
                    help="Only import the slide-frame(s) with this data-slide-key "
                         "(use to pull ONE page out of a multi-slide montage).")
    ap.add_argument("--index", type=int, default=None,
                    help="Only import the slide-frame at this 1-based position "
                         "within each source file.")
    ap.add_argument("--no-lifted", action="store_true",
                    help="Do NOT mark imported slides lifted (treat as native — "
                         "they then face the full font-tier gate, not warnings).")
    ap.add_argument("--no-copy-assets", action="store_true",
                    help="Do NOT copy + rewrite the slide's local assets into the "
                         "target deck (leave refs as-authored).")
    ap.add_argument("--force", action="store_true",
                    help="F-315: import even if the target's index.html carries "
                         "un-synced browser/hand edits (the clobber guard would "
                         "otherwise refuse, since the post-import re-render would "
                         "destroy them). Also bypasses the optimistic-lock check "
                         "on deck.json. Use only after syncing or discarding them.")
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

    # Extract + validate each slide-frame from each source. Track the source dir
    # per accepted frag so assets resolve against the right directory.
    accepted: list[tuple[str, Path]] = []          # (frag, source_path)
    for src in sources:
        text = src.read_text(encoding="utf-8")
        frags = extract_slide_frames(text)
        if not frags:
            _warn(f"{src.name}: no <div class='slide-frame'> found, skipping")
            continue
        # --index / --key narrow a montage down to the one page wanted. Indices are
        # paired so the per-frame log still reflects the original 1-based position.
        indexed = list(enumerate(frags))
        if args.index is not None:
            indexed = [t for t in indexed if t[0] == args.index - 1]
        if args.key is not None:
            indexed = [t for t in indexed if slide_key_in(t[1]) == args.key]
        if not indexed:
            _warn(f"{src.name}: no slide-frame matched "
                  f"{'--index ' + str(args.index) if args.index else ''}"
                  f"{' --key ' + args.key if args.key else ''}; skipping")
            continue
        _info(f"{src.name}: {len(frags)} slide-frame(s) found, "
              f"{len(indexed)} selected")
        for i, frag in indexed:
            ok, issues = validate_slide_fragment(frag, strict=args.strict)
            verdict = resolve_compliance(src.name, i, frag, issues,
                                          strict=args.strict, auto_yes=args.yes)
            if verdict == "insert":
                if ok:
                    _ok(f"{src.name}[{i+1}] '{slide_key_in(frag) or '?'}' clean, queued")
                else:
                    _info(f"{src.name}[{i+1}] inserted with {len(issues)} known issues")
                accepted.append((frag, src))
            elif verdict == "skip":
                _info(f"{src.name}[{i+1}] skipped")
            else:                                  # abort
                raise SystemExit("aborted on compliance issue (--strict)")

    if not accepted:
        _warn("no slides queued for import. nothing to do.")
        return 0

    # Copy + rewrite each accepted slide's local assets into the target deck so
    # img/iframe/url() refs (authored relative to the SOURCE file) keep resolving.
    deck_dir = target.parent
    if not args.no_copy_assets:
        rewritten: list[tuple[str, Path]] = []
        for frag, src in accepted:
            new_frag, copied, missing = copy_and_rewrite_assets(
                frag, src.parent, deck_dir, src.stem)
            if copied:
                _ok(f"{src.name}: copied {len(copied)} asset(s) → "
                    f"assets/imported/{_slug(src.stem)}/")
            for mref in missing:
                _warn(f"{src.name}: asset ref not found on disk, left as-is: {mref}")
            rewritten.append((new_frag, src))
        accepted = rewritten

    accepted_frags = [f for f, _ in accepted]

    # Pick position
    if mode == "A":
        deck = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(deck.get("slides"), list):
            _err(f"{target.name}: malformed deck.json — missing/invalid 'slides' array")
            return 2
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
        bak, orig_text = insert_into_json(
            target, accepted_frags, position,
            lifted=not args.no_lifted, allow_unsynced=args.force, force=args.force)
        rc = re_render(target)
        if rc != 0:
            # mutation-1: the spliced deck.json passed schema validation but the
            # re-render failed downstream — restore the SSOT to its pre-import
            # state instead of leaving the user with a deck that only opens fine
            # because validate-deck passed but render-deck choked.
            restore_deck(target, bak, orig_text, "import")
            _err("import re-render FAILED — deck.json was RESTORED to its "
                 "pre-import state (no change applied). Fix the error shown "
                 "above and retry.")
            return rc
    else:
        insert_into_html(target, accepted_frags, position)

    _ok("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
