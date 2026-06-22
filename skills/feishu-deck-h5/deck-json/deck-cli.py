#!/usr/bin/env python3
"""deck-cli.py — Phase 3 CLI editor for DeckJSON files.

Operate on a deck.json by command — let Claude / programmers / future
visual editor backends mutate decks without hand-editing JSON.

USAGE
  python3 deck-cli.py <deck.json> COMMAND [args...] [--yes] [--no-backup]

Read commands (no backup needed):
  list                        list slides as numbered table
  get PATH                    print value at dotted path (e.g. slides.3.data.title)
  lint                        validate against schema (wrap validate-deck.py)
  show KEY                    pretty-print one slide's JSON

Write commands (auto-backup + revalidate + rollback on schema fail):
  set PATH VALUE              dotted-path set (VALUE auto-typed: int/bool/str/json)
  set-accent KEY COLOR        slide.accent = COLOR
  set-decor KEY TOKENS        slide.decor = TOKENS (comma-sep, e.g. "blue-glow,grain")
  set-variant KEY VARIANT     for content/stats/flow only — also wipes data fields
                              that don't belong to the new variant
  reorder FROM TO             move slides[FROM] to position TO (1-indexed)
  move-key KEY POSITION       safer than reorder — survives prior renumbering
  insert POSITION L [V] KEY   insert a scaffold slide at POSITION
  delete KEY                  remove slide. MANDATORY confirm + backup.
  clone KEY NEW_KEY [POSITION]  duplicate KEY → NEW_KEY at POSITION (default after KEY)
  paste --from SRC --key K [--new-key NK] [POS]
                              copy a slide from another deck.json into this one (deck.json-
                              native lift) — deep-copies the slide object + its input/ &
                              prototypes/ assets, auto-suffixes key collisions

Render pipeline:
  render OUTPUT_DIR [--inline] [--skip-...]   wrap render-deck.py

Flags:
  --yes        skip interactive confirms (for Claude / CI / batch use)
  --no-backup  skip .bak-pre-<command>-<ts> backup (NOT recommended)

Exit codes:
  0 = success
  1 = invalid args / unknown command
  2 = deck.json read/parse error
  3 = post-op schema validation failed (auto-rolled-back)
  4 = user declined confirm
  5 = render subprocess failed
"""
from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE          = Path(__file__).resolve().parent
SCHEMA_FILE   = HERE / "deck-schema.json"
VALIDATE_DECK = HERE / "validate-deck.py"
RENDER_DECK   = HERE / "render-deck.py"

sys.path.insert(0, str(HERE))
from _safe_write import contained_dest          # noqa: E402  (path-traversal guard)


# ---------------------------------------------------------------------------
# Atomic file write (F-269) — shared so every writer in the pipeline (deck-cli,
# render-deck, lift-slides) gets crash-safe, all-or-nothing writes. A plain
# Path.write_text() truncates the target FIRST, then streams bytes; a kill /
# disk-full / exception mid-write leaves a HALF-WRITTEN file on disk that looks
# valid to the next reader. Writing to a sibling temp file and os.replace()-ing
# it into place is atomic on POSIX + Windows: a reader sees either the complete
# old file or the complete new one, never a torn one.
# ---------------------------------------------------------------------------

def atomic_write_text(path, text: str, encoding: str = "utf-8") -> None:
    """Write `text` to `path` atomically (temp file in the same dir + os.replace).

    os.replace requires the temp file and the destination to be on the SAME
    filesystem, hence the sibling temp file (NOT /tmp). The temp file is cleaned
    up on any failure so a crashed write never leaves a `.tmp` turd behind."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding) as fh:
            fh.write(text)
        os.replace(tmp, path)   # atomic rename over the destination
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Helpers — dotted-path get / set
# ---------------------------------------------------------------------------

def parse_value(s: str):
    """Auto-type a CLI string. Try JSON parse first (handles ints/bools/null/
    arrays/objects); fall back to raw string."""
    s_stripped = s.strip()
    # Pure JSON literals
    try:
        return json.loads(s_stripped)
    except (ValueError, json.JSONDecodeError):
        pass
    return s


def get_path(d, dotted: str):
    """Walk a dotted path. Numeric segments index arrays.
    Raises KeyError / IndexError on miss."""
    cur = d
    for seg in dotted.split("."):
        if isinstance(cur, list):
            idx = int(seg)
            cur = cur[idx]
        elif isinstance(cur, dict):
            cur = cur[seg]
        else:
            raise KeyError(f"can't descend into {type(cur).__name__} at '{seg}'")
    return cur


def set_path(d, dotted: str, value):
    """Set a dotted path. Creates intermediate dicts (NOT lists) as needed."""
    segs = dotted.split(".")
    cur = d
    for seg in segs[:-1]:
        if isinstance(cur, list):
            idx = int(seg)
            cur = cur[idx]
        elif isinstance(cur, dict):
            if seg not in cur or not isinstance(cur[seg], (dict, list)):
                cur[seg] = {}
            cur = cur[seg]
        else:
            raise KeyError(f"can't descend into {type(cur).__name__} at '{seg}'")
    last = segs[-1]
    if isinstance(cur, list):
        cur[int(last)] = value
    else:
        cur[last] = value


def find_slide_index(deck: dict, key: str) -> int:
    for i, s in enumerate(deck.get("slides", [])):
        if s.get("key") == key:
            return i
    raise KeyError(f"slide with key '{key}' not found")


def resolve_slide_ref(deck: dict, ref: str):
    """Resolve a slide reference to a 0-based index, accepting (in order): an
    exact semantic key, a 1-based page index ('36'), or a '#36' frame hash —
    the same ways a user cites a page. Returns None when nothing matches so
    callers can print a friendly error. `get-page` rides on this so reading a
    slide never needs a hand-rolled 'json.load + guess the field names' script."""
    slides = deck.get("slides", [])
    try:
        return find_slide_index(deck, ref)            # exact key wins
    except KeyError:
        pass
    bare = str(ref).lstrip("#").strip()
    if bare.isdigit():
        n = int(bare)
        return n - 1 if 1 <= n <= len(slides) else None
    try:
        return find_slide_index(deck, bare)           # '#key' style
    except KeyError:
        return None


# ---------------------------------------------------------------------------
# Backup + rollback
# ---------------------------------------------------------------------------

def backup_path(deck_path: Path, command: str) -> Path:
    ts = time.strftime("%Y%m%d-%H%M%S")
    base = deck_path.with_suffix(f".json.bak-pre-{command}-{ts}")
    if not base.exists():
        return base
    # Same-second collision (two writes of the same command within 1s) would
    # otherwise overwrite the first backup — append a counter.
    n = 1
    while (cand := deck_path.parent / f"{base.name}.{n}").exists():
        n += 1
    return cand


def prune_backups(deck_path: Path, keep: int = 15) -> int:
    """Keep only the most-recent `keep` `<deck>.bak-pre-*` backups (by mtime),
    delete the rest. One backup is written per mutation, so an actively-edited
    deck otherwise accumulates them into the hundreds (a real deck dir held ~100).
    Best-effort: never raises, returns the count deleted. (F-363)"""
    try:
        baks = sorted(deck_path.parent.glob(deck_path.name + ".bak-pre-*"),
                      key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return 0
    removed = 0
    for old in baks[keep:]:
        try:
            old.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def _edit_scope_keys(args, updated: dict):
    """F-320 · the set of slide KEYS this edit could legitimately affect, for the
    scope-aware pre-write lint. Return:
      · None      → opt OUT: whole-deck gate (unchanged default for commands that
                    haven't been scoped — every other command).
      · set()     → a DECK-LEVEL edit (deck meta / a top-level scalar): no per-slide
                    finding is this edit's fault, so only deck-level / schema errors
                    block; every pre-existing per-page error is demoted.
      · {keys…}   → scope the gate to those page(s).
    Conservative: only the single-slide-target / deck-scalar commands opt in; the
    rest (reorder / delete / move-key / clone / paste / hide …) keep the whole-deck
    gate, so this change can never WEAKEN a gate it doesn't understand."""
    cmd = getattr(args, "cmd", None)
    if cmd in ("set-page", "set-accent", "set-decor", "set-notes",
               "set-variant", "insert", "consolidate-css") and getattr(args, "key", None):
        return {args.key}
    if cmd == "set":
        path = getattr(args, "path", "") or ""
        if not path.startswith("slides"):
            return set()                        # deck-level scalar (deck.title, magic_move …)
        # `set` indexes arrays with DOTS (slides.5.accent); also tolerate brackets.
        m = re.match(r"slides[.\[](\d+)", path)
        if m:
            i = int(m.group(1))
            slides = updated.get("slides") or []
            if 0 <= i < len(slides) and slides[i].get("key"):
                return {slides[i]["key"]}
        return None                             # touches slides, unattributable → whole-deck gate
    return None


def _scope_demote(deck_path: Path, scope_keys, command: str) -> bool:
    """F-320 · the post-write whole-deck validation FAILED. Decide whether the
    failure is confined to PAGES THIS EDIT DID NOT TOUCH (→ True: KEEP the write,
    print an advisory) or hits an in-scope page / a deck-level / schema rule (→
    False: print the blocking error(s); the caller rolls back). Re-validates with
    `--json` for per-page attribution; on ANY parse failure returns False — the
    safe fallback is the original whole-deck rollback. `scope_keys` empty = a
    deck-level edit (only deck-level / schema errors block)."""
    try:
        jr = subprocess.run(
            [sys.executable, str(VALIDATE_DECK), str(deck_path), "--strict", "--json"],
            capture_output=True, text=True)
        errs = json.loads(jr.stdout).get("errors", [])
    except Exception:
        return False
    def _off(e):   # a per-page error on a page OUTSIDE this edit's scope
        return (e.get("slide") is not None and e.get("key") is not None
                and e.get("key") not in scope_keys)
    off_scope = [e for e in errs if _off(e)]
    in_scope = [e for e in errs if not _off(e)]
    if in_scope:
        print(f"deck-cli: ✗ post-{command} validation — {len(in_scope)} error(s) on "
              f"this edit's page(s) / deck-level:", file=sys.stderr)
        for e in in_scope[:8]:
            loc = f"slide '{e['key']}'" if e.get("key") else "deck-level"
            print(f"    ✗ {loc}: {(e.get('msg') or '')[:100]}", file=sys.stderr)
        return False
    print(f"deck-cli: ⓘ {len(off_scope)} PRE-EXISTING error(s) on page(s) this "
          f"'{command}' did NOT touch — demoted, write KEPT (scope: "
          f"{', '.join(sorted(scope_keys)) if scope_keys else 'deck-level only'}). "
          f"They predate this edit; run `lint` or render --final for the whole-deck "
          f"gate.", file=sys.stderr)
    for e in off_scope[:6]:
        print(f"    · slide '{e.get('key')}': {(e.get('msg') or '')[:90]}", file=sys.stderr)
    return True


def write_deck_with_validation(deck_path: Path, deck: dict, command: str,
                                no_backup: bool = False,
                                expected_mtime: float | None = None,
                                force: bool = False,
                                scope_keys=None) -> bool:
    """Write deck back to disk, re-validate. On schema fail: rollback, return False.

    Optimistic lock (F-48): if `expected_mtime` is given and the file's current
    mtime differs (another process wrote deck.json since we read it), refuse the
    write so we don't silently clobber that change. `--force` bypasses the check.
    """
    # 0. Optimistic-lock check — another session may have written since we read.
    if expected_mtime is not None and not force:
        if not deck_path.exists():
            # A concurrent process DELETED deck.json since we read it — writing
            # now would silently resurrect it over their delete. Refuse.
            print(f"deck-cli: REFUSING write — {deck_path.name} was DELETED on disk "
                  f"since it was read (concurrent edit). Re-read and retry, or --force.",
                  file=sys.stderr)
            return False
        cur_mtime = deck_path.stat().st_mtime
        if abs(cur_mtime - expected_mtime) > 1e-6:
            print(f"deck-cli: REFUSING write — {deck_path.name} changed on disk "
                  f"since it was read (concurrent edit by another process). "
                  f"Re-read the deck and retry, or pass --force to overwrite.",
                  file=sys.stderr)
            return False

    # 1. Backup current state. Even with --no-backup, keep the original TEXT in
    #    memory — the schema-fail rollback below must always have something to
    #    restore from (pre-W1 this path silently left the INVALID content on
    #    disk while printing "Rolling back").
    bak = None
    orig_text = None
    if deck_path.exists():
        try:
            orig_text = deck_path.read_text(encoding="utf-8")
        except OSError:
            pass
        if not no_backup:
            bak = backup_path(deck_path, command)
            shutil.copy2(deck_path, bak)
            # F-363: cap backup accumulation. The just-made `bak` is newest, so
            # it survives the prune and stays available for rollback below.
            prune_backups(deck_path)

    # 2. Write (atomic — F-269: a kill mid-write must not leave a torn deck.json)
    atomic_write_text(deck_path, json.dumps(deck, ensure_ascii=False, indent=2),
                      encoding="utf-8")

    # 3. Re-validate
    rc = subprocess.run(
        [sys.executable, str(VALIDATE_DECK), str(deck_path), "--strict"],
        capture_output=True, text=True,
    )
    if rc.returncode != 0:
        # F-320 · scope-aware pre-write lint. A SCOPED edit (scope_keys is not None)
        # must not roll back because of a PRE-EXISTING error on a page it did not
        # touch (another session's WIP, a validator-rule drift) — only an error on
        # an in-scope page OR a deck-level / schema rule should. `scope_keys is None`
        # → the unchanged whole-deck rollback (commands that didn't opt in).
        if scope_keys is not None and _scope_demote(deck_path, scope_keys, command):
            if bak:
                print(f"deck-cli: backup at {bak.name}")
            return True
        # Schema / in-scope fail — roll back.
        print(f"deck-cli: post-{command} validation FAILED. Rolling back.",
              file=sys.stderr)
        if scope_keys is None:
            print(rc.stdout, file=sys.stderr)   # scoped path already printed the focused errors
        if bak and bak.exists():
            shutil.copy2(bak, deck_path)
            print(f"deck-cli: restored from {bak.name}", file=sys.stderr)
        elif orig_text is not None:
            atomic_write_text(deck_path, orig_text, encoding="utf-8")
            print("deck-cli: restored pre-write content (in-memory copy — "
                  "--no-backup run)", file=sys.stderr)
        return False

    if bak:
        print(f"deck-cli: backup at {bak.name}")
    return True


def confirm(prompt: str, yes_flag: bool) -> bool:
    if yes_flag:
        return True
    if not sys.stdin.isatty():
        print(f"deck-cli: refusing non-interactive destructive op without --yes",
              file=sys.stderr)
        return False
    try:
        ans = input(f"{prompt} [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return ans in ("y", "yes")


# ---------------------------------------------------------------------------
# Read commands
# ---------------------------------------------------------------------------

def cmd_list(deck: dict, args) -> int:
    slides = deck.get("slides", [])
    print(f"{len(slides)} slides · deck='{deck.get('deck', {}).get('title', '<no title>')}'")
    print(f"{'#':>3}  {'KEY':<35}  {'LAYOUT':<12}  {'VARIANT':<11}  SCREEN-LABEL")
    print(f"{'-'*3}  {'-'*35}  {'-'*12}  {'-'*11}  {'-'*30}")
    for i, s in enumerate(slides, start=1):
        key = s.get("key", "<missing>")[:35]
        layout = s.get("layout", "?")[:12]
        variant = (s.get("variant") or "—")[:11]
        label = s.get("screen_label", "")[:30]
        print(f"{i:>3}  {key:<35}  {layout:<12}  {variant:<11}  {label}")
    return 0


def cmd_get(deck: dict, args) -> int:
    try:
        value = get_path(deck, args.path)
    except (KeyError, IndexError, ValueError) as e:
        print(f"deck-cli: path '{args.path}' not found ({e})", file=sys.stderr)
        return 1
    if isinstance(value, (dict, list)):
        print(json.dumps(value, ensure_ascii=False, indent=2))
    else:
        print(value)
    return 0


def cmd_show(deck: dict, args) -> int:
    try:
        idx = find_slide_index(deck, args.key)
    except KeyError as e:
        print(f"deck-cli: {e}", file=sys.stderr); return 1
    print(json.dumps(deck["slides"][idx], ensure_ascii=False, indent=2))
    return 0


def cmd_get_page(deck: dict, args) -> int:
    """Read-only dump of ONE slide's authored content, addressed by key OR a
    1-based page index (`36` / `#36`). This is the clean replacement for ad-hoc
    'json.load(deck); slides[i].html' extractors — the exact pattern that gets
    the slide object shape (data.html / custom_css / title) guessed wrong and
    burns a round-trip. Default prints a readable summary plus the raw html &
    css; --html / --css / --title print just that field, unescaped, ready to
    pipe to a file (`get-page X --html > frag.html`)."""
    idx = resolve_slide_ref(deck, args.ref)
    if idx is None:
        print(f"deck-cli: get-page — no slide matches '{args.ref}' "
              f"(use a key, or a 1-based page index like 36 / #36)",
              file=sys.stderr)
        return 1
    s = deck["slides"][idx]
    data = s.get("data") or {}
    html = data.get("html") or ""
    css = s.get("custom_css") or ""
    title = data.get("title") or ""
    if args.html:
        sys.stdout.write(html + ("" if html.endswith("\n") else "\n"))
        return 0
    if args.css:
        sys.stdout.write(css + ("" if css.endswith("\n") else "\n"))
        return 0
    if args.title:
        print(title)
        return 0
    print(f"page {idx + 1} · key={s.get('key')} · layout={s.get('layout')} · "
          f"screen_label={s.get('screen_label')!r}")
    if title:
        print(f"title: {title}")
    print(f"fields: {sorted(s.keys())}  |  data.html: {len(html)} chars  |  "
          f"custom_css: {len(css)} chars")
    if html:
        print("\n--- data.html ---")
        print(html)
    if css:
        print("\n--- custom_css ---")
        print(css)
    return 0


def _fontsize_map(style_text: str) -> list[tuple[str, str]]:
    """(selector, size) for every `font-size:Npx` / `font:… Npx…` decl in a CSS
    string. Coarse block split — good enough for a font inventory."""
    rows: list[tuple[str, str]] = []
    for m in re.finditer(r'([^{}]+)\{([^}]*)\}', style_text):
        body = m.group(2)
        fm = re.search(r'font(?:-size)?:\s*[^;]*?([0-9.]+)px', body)
        if fm:
            sel = m.group(1).strip().splitlines()[-1].strip()
            rows.append((sel[:48], fm.group(1) + "px"))
    return rows


def _visible_text(h: str) -> str:
    t = re.sub(r'<(script|style)\b[^>]*>.*?</\1>', ' ', h, flags=re.S | re.I)
    t = re.sub(r'<[^>]+>', ' ', t)
    t = re.sub(r'&[a-z]+;|&#\d+;', ' ', t)
    return re.sub(r'\s+', ' ', t).strip()


def cmd_inspect_text(deck: dict, args) -> int:
    """Read-only: dump a slide's effective TEXT + a font-size map, FOLLOWING any
    iframe `src` into its embedded prototype file (prototypes/<…>.html) and
    listing that file's font-sizes too.

    This is the "the demo text is too small" fix: the rendered text of an
    iframe-embedded demo otherwise lives two files deep (page → iframe src →
    prototype CSS) and has to be hand-traced before you can even find the sizes
    to change. (F-362)"""
    idx = resolve_slide_ref(deck, args.ref)
    if idx is None:
        print(f"deck-cli: inspect-text — no slide matches '{args.ref}' "
              f"(use a key, or a 1-based page index like 36 / #36)",
              file=sys.stderr)
        return 1
    s = deck["slides"][idx]
    html = (s.get("data") or {}).get("html") or ""
    css = s.get("custom_css") or ""
    deck_dir = args.deck.parent

    print(f"page {idx + 1} · key={s.get('key')} · layout={s.get('layout')}")
    page_styles = css + "\n" + "\n".join(
        re.findall(r'<style[^>]*>(.*?)</style>', html, re.S))
    pfm = _fontsize_map(page_styles)
    print(f"\n--- page font-sizes ({len(pfm)}) ---")
    for sel, sz in pfm:
        print(f"  {sz:>7}  {sel}")
    if not pfm:
        print("  (none in custom_css / inline <style>)")
    print("\n--- page text ---")
    print("  " + (_visible_text(html)[:600] or "(none)"))

    srcs = re.findall(r'<iframe[^>]+src=["\']([^"\']+)["\']', html, re.I)
    if not srcs:
        print("\n(no iframe — nothing further to follow)")
    for src in srcs:
        if src.startswith(("data:", "http://", "https://", "//")):
            print(f"\n--- iframe src={src[:48]}… (inline/remote — not followed) ---")
            continue
        proto = (deck_dir / src).resolve()
        print(f"\n--- iframe → {src} ---")
        if not proto.is_file():
            print(f"  (prototype file not found: {proto})")
            continue
        ph = proto.read_text(encoding="utf-8", errors="replace")
        ps = "\n".join(re.findall(r'<style[^>]*>(.*?)</style>', ph, re.S))
        ifm = _fontsize_map(ps)
        sizes = sorted({float(sz[:-2]) for _, sz in ifm})
        print(f"  font-sizes ({len(ifm)} decls): "
              + (", ".join(f"{x:g}px" for x in sizes) or "none"))
        for sel, sz in ifm:
            print(f"    {sz:>7}  {sel}")
        print(f"  text: {_visible_text(ph)[:400]}")
    return 0


def cmd_add_asset(deck: dict, args) -> int:
    """W8 (iteration-loop): compress + place an image next to the deck and print
    the relative URL to reference — the alternative to hand-base64'ing photos
    into fragments (deck.json bloat + the P50 250KB in-style cap)."""
    src = args.file
    if not src.is_file():
        print(f"deck-cli: add-asset — no such file: {src}", file=sys.stderr)
        return 1
    dest_dir = args.deck.parent / "input"
    dest_dir.mkdir(parents=True, exist_ok=True)
    name = args.name or src.name
    out = dest_dir / name
    orig_kb = src.stat().st_size // 1024
    try:
        from PIL import Image
        with Image.open(src) as im:
            has_alpha = im.mode in ("RGBA", "LA", "P") and (
                im.mode != "P" or "transparency" in im.info)
            if im.width > args.max_width:
                h = max(1, round(im.height * args.max_width / im.width))
                im = im.resize((args.max_width, h), Image.LANCZOS)
            if has_alpha:
                out = out.with_suffix(".png")
                im.save(out, optimize=True)
            else:
                out = out.with_suffix(".jpg")
                im.convert("RGB").save(out, quality=args.quality, optimize=True)
    except ImportError:
        shutil.copy2(src, out)          # no PIL — place verbatim, still linked
    except Exception as e:              # not an image / decode error — verbatim
        print(f"deck-cli: add-asset — not processable as image ({e}); "
              f"copying verbatim.", file=sys.stderr)
        shutil.copy2(src, out)
    new_kb = out.stat().st_size // 1024
    print(f"  {src.name} ({orig_kb}KB) → {out} ({new_kb}KB)")
    print(f"  reference it as:  input/{out.name}")
    if new_kb > 500:
        print(f"  ⚠ still {new_kb}KB — consider --max-width below "
              f"{args.max_width} or stronger --quality.")
    return 0


def cmd_lint(deck_path: Path, args) -> int:
    rc = subprocess.run(
        [sys.executable, str(VALIDATE_DECK), str(deck_path),
         *(["--strict"] if args.strict else [])],
        text=True,
    )
    return rc.returncode


# ---------------------------------------------------------------------------
# Set commands
# ---------------------------------------------------------------------------

def cmd_set(deck: dict, args) -> tuple[int, dict | None]:
    try:
        old = get_path(deck, args.path)
    except (KeyError, IndexError, ValueError):
        old = "<unset>"
    if getattr(args, "from_file", None):
        # W1 (iteration-loop): large payloads (data.html / custom_css) come from
        # a file, verbatim — argv can't carry 100KB fragments and ad-hoc heredoc
        # injectors lose the optimistic lock. NO parse_value: raw string.
        try:
            value = args.from_file.read_text(encoding="utf-8")
        except OSError as e:
            print(f"deck-cli: can't read --from-file: {e}", file=sys.stderr)
            return 1, None
    elif getattr(args, "str", False):
        # mutation-8: explicit raw-string channel — never JSON-coerce.
        value = args.value
    else:
        value = parse_value(args.value)
        # mutation-8: parse_value JSON-coerces a bare "42"/"true"/"null" to
        # int/bool/None. That silently CORRUPTS a field that currently holds a
        # string (e.g. `set …data.title 2024` would turn a string title into the
        # int 2024). Be conservative: when the existing value is a string and the
        # coercion would flip it to a non-string SCALAR, keep the raw string.
        # (Arrays/objects are clearly intentional JSON, so they pass through; use
        # --json to force a deliberate string→number/bool/null retype.)
        if (not getattr(args, "json", False)
                and isinstance(old, str)
                and value is not args.value
                and not isinstance(value, (str, list, dict))):
            print(f"deck-cli: '{args.path}' currently holds a string — keeping "
                  f"'{args.value}' as a string (use --json to set it to "
                  f"{value!r} deliberately, or --str to silence this).",
                  file=sys.stderr)
            value = args.value
    try:
        set_path(deck, args.path, value)
    except (KeyError, IndexError, ValueError) as e:
        print(f"deck-cli: can't set '{args.path}': {e}", file=sys.stderr)
        return 1, None
    print(f"  {args.path}:")
    _ostr, _nstr = repr(old), repr(value)
    print(f"    old: {_ostr if len(_ostr) <= 200 else _ostr[:200] + '…'}")
    print(f"    new: {_nstr if len(_nstr) <= 200 else _nstr[:200] + '…'}")
    # L2 self-doc: surface the scoped verify next-step at point-of-use so a
    # single-field edit isn't re-discovered or whole-deck-rendered.
    _m = re.match(r"slides\.(\d+)\.", str(getattr(args, "path", "")))
    if _m:
        _pg = int(_m.group(1)) + 1
        _deck = str(args.deck)
        _out = _deck.rsplit("/", 1)[0] if "/" in _deck else "."
        print(f"  → 验收(改一页别跑全 deck): python3 render-deck.py {_deck} {_out} "
              f"--scope {_pg} --shoot", file=sys.stderr)
    return 0, deck


_STYLE_BLOCK_RE = re.compile(r"<style(?P<attrs>[^>]*)>(?P<body>.*?)</style>", re.S | re.I)


def _embedded_style_count(html) -> int:
    """F-347: number of NON-framework <style> blocks in a slide's data.html.
    These are the silent-override trap — the renderer injects custom_css as the
    `.slide` FIRST CHILD, so any embedded <style> sits LATER in source order and
    WINS the cascade at equal specificity (cost ~2 render cycles this session on a
    3-block lifted page). `data-source="framework"` blocks don't count."""
    if not isinstance(html, str) or "<style" not in html.lower():
        return 0
    n = 0
    for m in _STYLE_BLOCK_RE.finditer(html):
        a = m.group("attrs") or ""
        if 'data-source="framework"' in a or "data-source='framework'" in a:
            continue
        n += 1
    return n


def cmd_set_page(deck: dict, args) -> tuple[int, dict | None]:
    """W1 (iteration-loop): one-shot page payload update — data.html / custom_css
    from files, plus title / lifted — with the W4 static pre-write lint so the
    known first-render gate failures (off-ladder font-size, dual-anchor,
    P50 base64-in-style …) are rejected BEFORE they reach deck.json."""
    try:
        idx = find_slide_index(deck, args.key)
    except KeyError as e:
        print(f"deck-cli: {e}", file=sys.stderr); return 1, None
    slide = deck["slides"][idx]

    html_txt = css_txt = None
    try:
        if args.html:
            html_txt = args.html.read_text(encoding="utf-8")
        if args.css:
            css_txt = args.css.read_text(encoding="utf-8")
    except OSError as e:
        print(f"deck-cli: can't read fragment file: {e}", file=sys.stderr)
        return 1, None
    if html_txt is None and css_txt is None and args.title is None \
            and not args.lifted:
        print("deck-cli: set-page — nothing to set "
              "(--html/--css/--title/--lifted)", file=sys.stderr)
        return 1, None

    # W4 pre-write lint on the NEW payloads (subset of the render gate;
    # geometry still belongs to the browser). --skip-lint to override.
    if (html_txt is not None or css_txt is not None) and not args.skip_lint:
        from _lint_fragment import lint_fragment, format_findings
        # F-355: a LIFTED slide's typescale/dual-anchor are verbatim-recovered
        # source styling → lint demotes them err→warn so this page no longer needs
        # a wholesale --skip-lint. AUTHORED pages still hard-fail pre-write (the
        # whole point: catch off-ladder/dual-anchor BEFORE a render round-trip).
        _lifted = bool(slide.get("lifted")) or bool(getattr(args, "lifted", False))
        fs = lint_fragment(html_txt or "", css_txt or "", lifted=_lifted)
        errs = [f for f in fs if f["sev"] == "err"]
        if fs:
            print(format_findings(fs))
        if errs:
            print(f"deck-cli: set-page REFUSED — {len(errs)} lint error(s) "
                  f"above would block the render gate anyway. Fix them, or "
                  f"--skip-lint if you really know better.", file=sys.stderr)
            return 5, None

    changed = []
    if html_txt is not None:
        slide.setdefault("data", {})["html"] = html_txt
        changed.append(f"data.html ({len(html_txt)} chars)")
    if css_txt is not None:
        slide["custom_css"] = css_txt
        changed.append(f"custom_css ({len(css_txt)} chars)")
    if args.title is not None:
        slide.setdefault("data", {})["title"] = args.title
        changed.append("data.title")
    if args.lifted:
        slide["lifted"] = True
        changed.append("lifted=true")
    print(f"  slides[{idx}] (key={args.key}) ← {', '.join(changed)}")

    # F-347: warn about the custom_css silent-override trap. If this page still
    # carries embedded <style> AND we just wrote custom_css, the embedded blocks
    # (injected after custom_css) can override it at equal specificity — exactly
    # the trap that ate ~2 render cycles this session. Point at the one-shot cure.
    n_emb = _embedded_style_count((slide.get("data") or {}).get("html", ""))
    if n_emb and css_txt is not None:
        print(f"  ⚠ this page has {n_emb} embedded <style> block(s); custom_css is "
              f"injected as .slide's first child, so those blocks can SILENTLY "
              f"OVERRIDE your rules at equal specificity. Cure: "
              f"`deck-cli.py <deck> consolidate-css --key {args.key}` (fold them "
              f"into custom_css → one home, predictable last-wins), or `!important`.",
              file=sys.stderr)
    # L2 self-doc: scoped verify next-step at point-of-use.
    _pg = idx + 1
    _deck = str(args.deck)
    _out = _deck.rsplit("/", 1)[0] if "/" in _deck else "."
    print(f"  → 验收(改一页别跑全 deck): python3 render-deck.py {_deck} {_out} "
          f"--scope {_pg} --shoot", file=sys.stderr)
    return 0, deck


def cmd_consolidate_css(deck: dict, args) -> tuple[int, dict | None]:
    """F-347: fold a raw page's embedded <style> block(s) into its custom_css —
    the single-source home that round-trips with deck.json AND wins the cascade
    predictably (last-wins within one <style>), killing the silent-override trap
    where custom_css (injected as .slide first-child) loses to later embedded
    blocks. Default: every raw page; --key: one page. Behaviour-preserving (it
    only MOVES CSS, source order kept), idempotent (a migration marker guards
    re-folding). Re-render afterwards to drop the blocks from index.html."""
    import importlib.util
    mig_path = Path(__file__).resolve().parent / "migrate-head-css-to-custom-css.py"
    try:
        spec = importlib.util.spec_from_file_location("_mig_css", mig_path)
        mig = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mig)
    except Exception as e:
        print(f"deck-cli: consolidate-css — can't load migrate codemod: {e}",
              file=sys.stderr)
        return 2, None

    keys = None
    if getattr(args, "key", None):
        try:
            idx = find_slide_index(deck, args.key)
        except KeyError as e:
            print(f"deck-cli: {e}", file=sys.stderr); return 1, None
        keys = {deck["slides"][idx].get("key")}

    applied = mig.migrate_raw_inline(deck, dry_run=args.dry_run, keys=keys)
    if not applied:
        where = f"page '{args.key}'" if keys else "any raw page"
        print(f"deck-cli: consolidate-css — nothing to do "
              f"({where} has no embedded <style>, or is already consolidated).")
        return 0, None
    verb = "would fold" if args.dry_run else "folded"
    for key, n_styles, n_bytes in applied:
        print(f"  {verb} {n_styles} embedded <style> block(s) "
              f"({n_bytes} B) → slides[{key}].custom_css")
    if args.dry_run:
        print("deck-cli: --dry-run, deck unchanged.")
        return 0, None
    print(f"deck-cli: consolidated {len(applied)} page(s). Re-render to drop the "
          f"embedded blocks from index.html.")
    return 0, deck


def cmd_set_accent(deck: dict, args) -> tuple[int, dict | None]:
    try:
        idx = find_slide_index(deck, args.key)
    except KeyError as e:
        print(f"deck-cli: {e}", file=sys.stderr); return 1, None
    old = deck["slides"][idx].get("accent", "<unset>")
    deck["slides"][idx]["accent"] = args.color
    print(f"  slides[{idx}] (key={args.key}) accent: {old!r} → {args.color!r}")
    return 0, deck


def cmd_set_decor(deck: dict, args) -> tuple[int, dict | None]:
    try:
        idx = find_slide_index(deck, args.key)
    except KeyError as e:
        print(f"deck-cli: {e}", file=sys.stderr); return 1, None
    tokens = [t.strip() for t in args.tokens.split(",") if t.strip()]
    old = deck["slides"][idx].get("decor", [])
    deck["slides"][idx]["decor"] = tokens
    print(f"  slides[{idx}] (key={args.key}) decor: {old} → {tokens}")
    return 0, deck


# Variant-data-shape map — used by set-variant to detect/wipe incompatible fields
VARIANT_DATA_FIELDS = {
    ("content", "3up"):         {"title", "cards", "lede", "body_blocks"},
    ("content", "2col"):        {"title", "text", "visual"},
    ("content", "story-case"):  {"title", "industry", "brand", "source", "hook", "arc", "scene"},
    ("content", "blocks"):      {"title", "lede", "body_blocks", "source_footer"},
    ("content", "matrix"):      {"title", "axes", "quadrants"},
    ("content", "before-after"):{"title", "before", "pivot", "after"},
    ("stats",   "row"):         {"title", "cols", "footnote"},
    ("stats",   "hero"):        {"title", "eyebrow", "stat", "heading", "body"},
    ("stats",   "waterfall"):   {"title", "bars", "footnote", "cols"},
    ("flow",    "timeline"):    {"title", "cols", "nodes"},
    ("flow",    "process"):     {"title", "cols", "steps"},
    ("flow",    "tree"):        {"title", "root", "branches"},
    ("flow",    "swim"):        {"title", "time_axis", "lanes"},
}


def _set_hidden(deck: dict, keys, value: bool) -> tuple[int, dict | None]:
    """Shared body for hide/unhide: set `hidden` on each slide by key. A hidden
    slide (隐藏页) is still rendered + reachable by direct #hash / scroll, but the
    runtime skips it in present-mode 翻页 and drops it from the page count.
    Re-render to apply. Idempotent; reports per-key old→new."""
    changed = False
    for key in keys:
        try:
            idx = find_slide_index(deck, key)
        except KeyError as e:
            print(f"deck-cli: {e}", file=sys.stderr); return 1, None
        old = bool(deck["slides"][idx].get("hidden", False))
        if value:
            deck["slides"][idx]["hidden"] = True
        else:
            deck["slides"][idx].pop("hidden", None)   # clear, don't leave hidden:false
        print(f"  slides[{idx}] (key={key}) hidden: {old} → {value}")
        changed = changed or (old != value)
    if not changed:
        print("  (no change — re-render not needed)")
    return 0, deck


def cmd_hide(deck: dict, args) -> tuple[int, dict | None]:
    return _set_hidden(deck, args.keys, True)


def cmd_unhide(deck: dict, args) -> tuple[int, dict | None]:
    return _set_hidden(deck, args.keys, False)


def cmd_set_notes(deck: dict, args) -> tuple[int, dict | None]:
    """Set (or clear, with empty text) a slide's speaker notes (口播稿) by key.
    Rendered into the hidden `#fs-deck-notes` island and shown in the presenter
    view (P). By key — survives reorder, unlike `set slides.N.notes`."""
    try:
        idx = find_slide_index(deck, args.key)
    except KeyError as e:
        print(f"deck-cli: {e}", file=sys.stderr); return 1, None
    old = deck["slides"][idx].get("notes", "<unset>")
    if args.text == "":
        deck["slides"][idx].pop("notes", None)
    else:
        deck["slides"][idx]["notes"] = args.text
    print(f"  slides[{idx}] (key={args.key}) notes: {old!r} → {args.text!r}")
    return 0, deck


def cmd_set_variant(deck: dict, args) -> tuple[int, dict | None]:
    try:
        idx = find_slide_index(deck, args.key)
    except KeyError as e:
        print(f"deck-cli: {e}", file=sys.stderr); return 1, None
    slide = deck["slides"][idx]
    layout = slide.get("layout")
    if layout not in ("content", "stats", "flow"):
        print(f"deck-cli: set-variant only valid on multi-variant layouts (content/stats/flow); slide is '{layout}'",
              file=sys.stderr)
        return 1, None
    new_variant = args.variant
    if (layout, new_variant) not in VARIANT_DATA_FIELDS:
        print(f"deck-cli: invalid variant '{new_variant}' for layout '{layout}'. "
              f"Valid: {sorted(v for l, v in VARIANT_DATA_FIELDS if l == layout)}",
              file=sys.stderr)
        return 1, None

    old_variant = slide.get("variant", "<unset>")
    keep_fields = VARIANT_DATA_FIELDS[(layout, new_variant)]
    data = slide.get("data", {}) or {}
    dropped = [f for f in data if f not in keep_fields]
    if dropped and not confirm(
        f"set-variant will DROP data fields {dropped} (not used by {layout}/{new_variant}). Proceed?",
        args.yes,
    ):
        return 4, None

    # Drop incompatible fields
    for f in dropped:
        del data[f]
    # Scaffold the new variant's required fields that are now MISSING (TODO
    # placeholders) so the switch yields a SCHEMA-VALID deck the user fills in —
    # instead of write_deck_with_validation rejecting + rolling back the whole
    # switch because the new variant's required fields aren't present. (#309)
    scaffolded = []
    sc = build_scaffold(layout, new_variant, args.key)
    if sc and isinstance(sc.get("data"), dict):
        for f, v in sc["data"].items():
            if f not in data:
                data[f] = copy.deepcopy(v)   # deepcopy: don't share the SCAFFOLDS literal
                scaffolded.append(f)
    slide["data"] = data
    slide["variant"] = new_variant
    print(f"  slides[{idx}] (key={args.key}) variant: {old_variant!r} → {new_variant!r}")
    if dropped:
        print(f"    dropped fields: {dropped}")
    if scaffolded:
        print(f"    scaffolded TODO fields for {layout}/{new_variant}: {scaffolded} (fill before render)")
    return 0, deck


# ---------------------------------------------------------------------------
# Structural commands
# ---------------------------------------------------------------------------

def cmd_reorder(deck: dict, args) -> tuple[int, dict | None]:
    slides = deck.get("slides", [])
    n = len(slides)
    if not (1 <= args.from_pos <= n) or not (1 <= args.to_pos <= n):
        print(f"deck-cli: positions out of range (1..{n})", file=sys.stderr)
        return 1, None
    if args.from_pos == args.to_pos:
        print("deck-cli: from == to, no-op"); return 0, None
    slide = slides.pop(args.from_pos - 1)
    slides.insert(args.to_pos - 1, slide)
    print(f"  moved slides[{args.from_pos}] (key={slide.get('key')}) → position {args.to_pos}")
    return 0, deck


def cmd_move_key(deck: dict, args) -> tuple[int, dict | None]:
    try:
        idx = find_slide_index(deck, args.key)
    except KeyError as e:
        print(f"deck-cli: {e}", file=sys.stderr); return 1, None
    n = len(deck.get("slides", []))
    if not (1 <= args.position <= n):
        print(f"deck-cli: position out of range (1..{n})", file=sys.stderr)
        return 1, None
    return cmd_reorder(deck, type("A", (), {"from_pos": idx + 1, "to_pos": args.position}))


def cmd_insert(deck: dict, args) -> tuple[int, dict | None]:
    slides = deck.get("slides", [])
    n = len(slides)
    if not (1 <= args.position <= n + 1):
        print(f"deck-cli: position out of range (1..{n+1})", file=sys.stderr)
        return 1, None
    # Key uniqueness
    if any(s.get("key") == args.key for s in slides):
        print(f"deck-cli: key '{args.key}' already exists", file=sys.stderr)
        return 1, None

    # Build scaffold per layout/variant
    scaffold = build_scaffold(args.layout, args.variant, args.key)
    if scaffold is None:
        print(f"deck-cli: unknown layout '{args.layout}'", file=sys.stderr)
        return 1, None

    slides.insert(args.position - 1, scaffold)
    print(f"  inserted at position {args.position}: key={args.key} layout={args.layout}"
          f"{'/' + args.variant if args.variant else ''}")
    print(f"    NOTE: scaffold data is placeholder. Fill required fields via set commands "
          f"before render or it will fail schema-fit check.")
    return 0, deck


def cmd_delete(deck: dict, args) -> tuple[int, dict | None]:
    try:
        idx = find_slide_index(deck, args.key)
    except KeyError as e:
        print(f"deck-cli: {e}", file=sys.stderr); return 1, None
    slide = deck["slides"][idx]
    print(f"deck-cli: about to delete:")
    print(f"    slides[{idx}]  key={args.key}")
    print(f"    layout: {slide.get('layout')}{'/' + slide['variant'] if slide.get('variant') else ''}")
    print(f"    screen_label: {slide.get('screen_label', '')}")
    if not confirm(f"DELETE this slide? (backup auto-created)", args.yes):
        print("deck-cli: deletion cancelled.")
        return 4, None
    deck["slides"].pop(idx)
    print(f"  deleted slides[{idx}] (key={args.key})")
    return 0, deck


def cmd_clone(deck: dict, args) -> tuple[int, dict | None]:
    try:
        idx = find_slide_index(deck, args.key)
    except KeyError as e:
        print(f"deck-cli: {e}", file=sys.stderr); return 1, None
    if any(s.get("key") == args.new_key for s in deck["slides"]):
        print(f"deck-cli: new key '{args.new_key}' already in use", file=sys.stderr)
        return 1, None
    cloned = copy.deepcopy(deck["slides"][idx])
    cloned["key"] = args.new_key
    n = len(deck["slides"])
    if args.position is not None:
        # Validate like insert/move-key (clone ADDS a slide → 1..n+1). The old
        # `args.position if args.position` also silently coerced an explicit
        # `position 0` to the default, and out-of-range values were absorbed by
        # list.insert's clamping → slide cloned to the wrong spot with no error.
        if not (1 <= args.position <= n + 1):
            print(f"deck-cli: position out of range (1..{n+1})", file=sys.stderr)
            return 1, None
        position = args.position
    else:
        position = idx + 2  # default: right after source
    deck["slides"].insert(position - 1, cloned)
    print(f"  cloned slides[{idx}] ({args.key}) → position {position} as '{args.new_key}'")
    return 0, deck


def _strip_text_ids(obj):
    """Recursively strip `data-text-id="..."` from every string in a slide.
    These ids are position-bound (`slide-NN.field`) to the SOURCE deck; they
    are inert in the target but carrying stale source-bound ids is messy, so
    we drop them on paste. Same call lift-slides.py makes. Returns the cleaned
    object + the count removed."""
    count = 0

    def walk(v):
        nonlocal count
        if isinstance(v, str):
            new = re.sub(r'\s+data-text-id="[^"]*"', '', v)
            count += len(re.findall(r'data-text-id="[^"]*"', v))
            return new
        if isinstance(v, dict):
            return {k: walk(x) for k, x in v.items()}
        if isinstance(v, list):
            return [walk(x) for x in v]
        return v

    return walk(obj), count


def _slide_asset_text(slide: dict) -> str:
    """Concatenate all string values in a slide (custom_css + every string in
    `data`, recursively) so asset references can be scanned without JSON-escape
    noise.

    The recursive `data` walk INCLUDES a `canvas` slide's
    `data.elements[].src` (each image element stores its path there, e.g.
    `input/img-001.jpg`) — so the `input/<file>` regex in _copy_slide_assets
    picks up canvas images for free, same as a raw slide's data.html refs. See
    _canvas_element_srcs for the explicit, name-free collector used as a belt-
    and-braces second pass for any non-`input/` element src form."""
    parts: list[str] = []
    cc = slide.get("custom_css")
    if isinstance(cc, str):
        parts.append(cc)

    def walk(v):
        if isinstance(v, str):
            parts.append(v)
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    walk(slide.get("data", {}))
    text = "\n".join(parts)
    # Collapse inline `data:` URIs (base64 blobs) before returning. They are
    # NEVER copyable local assets (paste skips them anyway), and a long unbroken
    # base64 run makes the media-ref scan in _copy_slide_assets (`_ref_re`)
    # backtrack catastrophically — a single 370KB inline image hung `paste` for
    # ~3.5 min at 100% CPU. The collapse is linear (anchored literal + greedy run
    # to the next delimiter, no failing follow-on to backtrack into).
    text = re.sub(r'''data:[^\s"'<>()]+''', "data:", text)
    return text


def _canvas_element_srcs(slide: dict) -> list[str]:
    """Explicit collector for a `canvas` slide's image element sources:
    `data.elements[].src` (and nested group children, if any future emitter
    adds them). Returns the raw `src` strings in document order, de-duplicated.

    A PPTX-imported `canvas` slide stores image paths ONLY here — not in
    data.html (there is none) — so paste/lift must scan elements[].src to carry
    the images. The generic `input/` text scan already catches the common
    `src:"input/<file>"` form; this collector makes the contract explicit and
    also surfaces bare/relative element srcs (`scene.png`, `./img.jpg`) that the
    deck-local media pass copies."""
    out: list[str] = []
    seen: set[str] = set()

    def walk(elements):
        if not isinstance(elements, list):
            return
        for el in elements:
            if not isinstance(el, dict):
                continue
            src = el.get("src")
            if isinstance(src, str) and src.strip() and src not in seen:
                seen.add(src)
                out.append(src.strip())
            # tolerate a future grouped form: elements with nested children
            for child_key in ("elements", "children"):
                if isinstance(el.get(child_key), list):
                    walk(el[child_key])

    data = slide.get("data")
    if isinstance(data, dict):
        walk(data.get("elements"))
    return out


def _copy_slide_assets(slide: dict, src_dir: Path, dst_dir: Path) -> dict:
    """Copy a pasted slide's referenced LOCAL assets from the source deck dir to
    the destination deck dir, preserving deck-relative paths (`input/<file>`,
    `prototypes/<slug>/`). Skill-relative (`../../../skills/...`) and shared-pool
    refs resolve identically in both decks, so they need no copy. Returns a
    report dict {input, prototypes, missing}.

    CANVAS slides store image paths in `data.elements[].src` (NOT in data.html —
    there is none). The `input/` text scan below already catches the common
    `src:"input/<file>"` form because _slide_asset_text walks `data` recursively;
    the explicit `_canvas_element_srcs` pass folds those srcs into the SAME text
    buffer so the contract is name-free and obvious, and any bare/relative
    element src (`scene.png`) falls through to the deck-local media pass."""
    # F-333: html.unescape FIRST so a data.html inline style url(&quot;input/x.png&quot;)
    # is decoded to a literal-quote url before the input/ + deck-local findall passes
    # below (else they over-capture an &quot;-tailed path and the asset isn't copied).
    # Safe: `text` is local, never written back. Covers &quot;/&#34;/&apos;/&#39;.
    text = html.unescape(_slide_asset_text(slide))
    # Belt-and-braces: explicitly append every canvas `data.elements[].src` to the
    # scanned text so a canvas slide's images are guaranteed to be seen by the
    # input/ + deck-local passes below (DECKJSON-UNIFIED-INTERMEDIATE-SPEC §7).
    canvas_srcs = _canvas_element_srcs(slide)
    if canvas_srcs:
        text = text + "\n" + "\n".join(canvas_srcs)
    copied = {"input": [], "prototypes": [], "shared": [], "local": [], "missing": []}
    for fname in sorted(set(re.findall(r"input/([^\s\"'<>()\\?#]+)", text))):
        s = src_dir / "input" / fname
        # mutation-2: a `../`-bearing fname from a crafted/foreign source deck must
        # not let the copy escape the destination input/ dir. contained_dest()
        # returns None for any ref that escapes — skip + flag it.
        d = contained_dest(dst_dir / "input", fname)
        if s.is_file() and d is not None:
            d.parent.mkdir(parents=True, exist_ok=True)
            if not d.exists() or s.stat().st_mtime > d.stat().st_mtime:
                shutil.copy2(s, d)
            copied["input"].append(fname)
        else:
            copied["missing"].append(f"input/{fname}")
    # prototypes/ refs come in two shapes: a SUBDIR (`prototypes/<slug>/...`, a
    # multi-file demo) OR a DIRECT FILE (`prototypes/<demo>.html`, the common
    # iframe-embed src). The old regex required a trailing slash → it copied only
    # subdirs and silently DROPPED direct files (iframe-embed src=prototypes/x.html
    # → blank iframe after paste). Capture the first path segment and copy whichever
    # it is. (cross-tenant-org-demo.html repro, 2026-06-02.)
    for seg in sorted(set(re.findall(r"prototypes/([^/\s\"'<>()\\?#]+)", text))):
        s = src_dir / "prototypes" / seg
        # mutation-2: containment guard — skip + flag any seg that escapes the
        # destination prototypes/ dir via ../.
        d = contained_dest(dst_dir / "prototypes", seg)
        if d is None:
            copied["missing"].append(f"prototypes/{seg}")
        elif s.is_dir():
            if not d.exists():
                shutil.copytree(s, d)
            copied["prototypes"].append(seg + "/")
        elif s.is_file():
            d.parent.mkdir(parents=True, exist_ok=True)
            if not d.exists() or s.stat().st_mtime > d.stat().st_mtime:
                shutil.copy2(s, d)
            copied["prototypes"].append(seg)
        else:
            copied["missing"].append(f"prototypes/{seg}")
    for ref in sorted(set(re.findall(r"assets/shared/([^\s\"'<>()\\?#]+)", text))):
        s = src_dir / "assets" / "shared" / ref
        # mutation-2: containment guard — skip + flag any ref that escapes the
        # destination assets/shared/ dir via ../.
        d = contained_dest(dst_dir / "assets" / "shared", ref)
        if s.is_file() and d is not None:
            d.parent.mkdir(parents=True, exist_ok=True)
            if not d.exists() or s.stat().st_mtime > d.stat().st_mtime:
                shutil.copy2(s, d)
            copied["shared"].append(ref)
        else:
            copied["missing"].append(f"assets/shared/{ref}")
    # Bare/relative deck-local media refs (scene.png, ./img.jpg, deck-local
    # assets/foo.png, replica page_image, image.src, …): NOT under input/ or
    # prototypes/, NOT framework (assets/shared·lark-)/http/data, NOT escaping
    # the deck dir via ../ or /. These were previously neither copied nor
    # reported → silent broken image after paste. Copy preserving the deck-
    # relative path, else flag missing.
    _MEDIA = r'(?:png|jpe?g|gif|webp|svg|avif|mp4|webm|mov|m4v)'
    already = set(copied["input"]) | {f"prototypes/{s}" for s in copied["prototypes"]}
    # Quantifier is bounded ({1,512}, generous for any real media path) as a
    # backstop: an unbounded `+` over a pathological long run (e.g. a base64 blob
    # the data:-collapse above somehow missed) backtracks O(n²); the bound caps
    # each attempt at 512 chars → O(n·k). No real asset path approaches 512.
    _ref_re = r'''([^\s"'<>()\\?#]{1,512}\.''' + _MEDIA + r''')(?=[\s"'<>()?#]|$)'''
    for m in re.finditer(_ref_re, text, re.I):
        ref = m.group(1)
        low = ref.lower()
        norm = low.lstrip("./")
        if (norm.startswith(("input/", "prototypes/", "assets/shared/", "assets/lark-"))
                or low.startswith(("http://", "https://", "data:", "//", "/"))
                or ref.startswith("../") or "/../" in ref):
            continue  # handled above / framework / external / escapes deck dir
        rel = ref.lstrip("./")
        if rel in already or rel in copied["local"]:
            continue
        s = src_dir / rel
        if s.is_file():
            d = dst_dir / rel
            d.parent.mkdir(parents=True, exist_ok=True)
            if not d.exists() or s.stat().st_mtime > d.stat().st_mtime:
                shutil.copy2(s, d)
            copied["local"].append(rel)
        else:
            copied["missing"].append(rel)
    return copied


def _extract_inline_images(slide: dict, dst_dir: Path, key: str) -> list[str]:
    """Extract LARGE inline `data:image/...;base64,…` URIs from a pasted slide
    into deck-local asset files (`assets/lift-<key>-<hash>.<ext>`) and rewrite the
    references to that relative path.

    Why: an inline base64 photo (e.g. a 370KB lifted hero image) bloats deck.json
    — every read / lint / render / snapshot re-parses it, and it is the P50
    base64-in-fragment anti-pattern add-asset exists to avoid. Cross-deck paste is
    exactly where a foreign slide's inline images arrive, so extract here: same net
    result as hand-running add-asset, but automatic and lossless (the bytes are
    written verbatim — no re-encode). SMALL data: URIs (tiny inline SVG icons /
    sprites below the threshold) are LEFT inline — not worth a file each.

    Runs AFTER _copy_slide_assets so the freshly-written `assets/lift-*` refs are
    not mis-scanned as "missing in source". Returns the written relative paths.
    """
    MIME_EXT = {"image/jpeg": "jpg", "image/jpg": "jpg", "image/png": "png",
                "image/gif": "gif", "image/webp": "webp", "image/avif": "avif",
                "image/svg+xml": "svg", "image/bmp": "bmp"}
    THRESHOLD = 8192  # base64 chars (~6KB binary); below this, keep inline
    # Non-greedy optional params (`;charset=…`) keep this LINEAR — it never
    # backtracks across the blob. Blob class is the base64 alphabet only.
    pat = re.compile(
        r'data:(image/[\w.+-]+)(?:;[\w.=+-]+)*?;base64,([A-Za-z0-9+/=]+)')
    mapping: dict[str, str] = {}   # full data: URI -> relative asset path
    written: list[str] = []

    def collect(v):
        if isinstance(v, str):
            for m in pat.finditer(v):
                full, mime, blob = m.group(0), m.group(1).lower(), m.group(2)
                if full in mapping or len(blob) < THRESHOLD:
                    continue
                try:
                    raw = base64.b64decode(blob)
                except Exception:
                    continue
                ext = MIME_EXT.get(mime, "bin")
                h = hashlib.md5(raw).hexdigest()[:8]
                rel = f"assets/lift-{key}-{h}.{ext}"
                out = dst_dir / rel
                out.parent.mkdir(parents=True, exist_ok=True)
                if not out.exists():
                    out.write_bytes(raw)
                mapping[full] = rel
                written.append(rel)
        elif isinstance(v, dict):
            for x in v.values():
                collect(x)
        elif isinstance(v, list):
            for x in v:
                collect(x)

    collect(slide.get("custom_css"))
    collect(slide.get("data"))
    if not mapping:
        return []

    def rewrite(v):
        if isinstance(v, str):
            for full, rel in mapping.items():
                v = v.replace(full, rel)
            return v
        if isinstance(v, dict):
            return {k: rewrite(x) for k, x in v.items()}
        if isinstance(v, list):
            return [rewrite(x) for x in v]
        return v

    if isinstance(slide.get("custom_css"), str):
        slide["custom_css"] = rewrite(slide["custom_css"])
    if "data" in slide:
        slide["data"] = rewrite(slide["data"])
    return written


# Framework-drift modernization: retired CSS custom properties an OLD deck may
# reference. var(--undefined) silently kills the whole declaration on render (a
# `font:` shorthand → 16px fallback) → R-CSSVAR. Map to the current equivalent.
# `--fs-accent4` was the teal keyword-jump accent (ACCENT4 = teal) → `--fs-teal`.
_RETIRED_VAR_MAP = {"--fs-accent4": "--fs-teal"}


def _map_retired_vars(slide: dict) -> tuple[dict, int]:
    """Remap retired framework CSS vars (var(--old) → var(--new)) across every
    string in the slide (data.html / custom_css / nested data). Returns
    (slide, count_of_occurrences_remapped)."""
    pairs = [(f"var({o})", f"var({n})") for o, n in _RETIRED_VAR_MAP.items()]
    total = 0

    def walk(v):
        nonlocal total
        if isinstance(v, str):
            for old, new in pairs:
                if old in v:
                    total += v.count(old)
                    v = v.replace(old, new)
            return v
        if isinstance(v, dict):
            return {k: walk(x) for k, x in v.items()}
        if isinstance(v, list):
            return [walk(x) for x in v]
        return v

    return walk(slide), total


def _rekey_slide_css(slide: dict, old_key: str, new_key: str) -> tuple[dict, int]:
    """F-255: follow a de-collided / renamed key into the slide's embedded keyed
    CSS. A raw slide's `data.html` (or a `custom_css` that already carries a
    `.slide[data-slide-key=...]` prefix — e.g. a slide that was itself lifted via
    lift-slides.py) anchors its selectors to the slide's ORIGINAL key. cmd_paste
    rewrites `slide["key"]`, but those embedded anchors stay on the old key → the
    slide renders unstyled and its @keyframes never fire. Rewrite the anchor
    across the slide's strings. No-op for the common prefix-free custom_css case;
    the trailing `"` anchors the match so `OLD` is never confused with `OLD-2`."""
    if not old_key or old_key == new_key:
        return slide, 0
    needle, repl = f'data-slide-key="{old_key}"', f'data-slide-key="{new_key}"'
    total = 0

    def walk(v):
        nonlocal total
        if isinstance(v, str):
            total += v.count(needle)
            return v.replace(needle, repl)
        if isinstance(v, dict):
            return {k: walk(x) for k, x in v.items()}
        if isinstance(v, list):
            return [walk(x) for x in v]
        return v

    return walk(slide), total


def cmd_paste(deck: dict, args) -> tuple[int, dict | None]:
    """Copy one slide from ANOTHER deck.json (args.from_deck) into this deck.

    This is the deck.json-native lift (LIFT-ARCHITECTURE step 3): for decks whose
    per-slide CSS lives in `custom_css` (self-contained-by-construction), pasting
    is a pure object copy — no index.html parsing, no CSS tree-shaking. Local
    assets (input/, prototypes/) are copied; key collisions auto-suffix."""
    src_path: Path = args.from_deck
    if not src_path.exists():
        print(f"deck-cli: source deck not found: {src_path}", file=sys.stderr)
        return 2, None
    try:
        src_deck = json.loads(src_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"deck-cli: source deck invalid JSON: {e}", file=sys.stderr)
        return 2, None

    src_slides = src_deck.get("slides", [])
    matches = [s for s in src_slides if s.get("key") == args.key]
    if not matches:
        avail = ", ".join(s.get("key", "?") for s in src_slides) or "(none)"
        print(f"deck-cli: slide-key '{args.key}' not found in source deck.\n"
              f"  available keys: {avail}", file=sys.stderr)
        return 1, None
    if len(matches) > 1:
        print(f"deck-cli: source has {len(matches)} slides keyed '{args.key}'; "
              f"taking the first.", file=sys.stderr)

    slide = copy.deepcopy(matches[0])

    # De-collide the key against the destination deck
    requested = args.new_key or slide.get("key", "pasted")
    existing = {s.get("key") for s in deck.get("slides", [])}
    new_key = requested
    if new_key in existing:
        i = 2
        while f"{requested}-{i}" in existing:
            i += 1
        new_key = f"{requested}-{i}"
        print(f"  key collision: '{requested}' already in target → renamed '{new_key}'")
    slide["key"] = new_key

    # F-255: if the key changed (collision OR explicit --new-key), follow it into
    # any embedded keyed CSS (raw data.html <style> / prefixed custom_css) so the
    # slide's selectors don't orphan onto the old key → unstyled, dead @keyframes.
    slide, n_css = _rekey_slide_css(slide, matches[0].get("key"), new_key)

    # Strip source-deck-bound data-text-id attrs (else T03 collision in target).
    slide, n_ids = _strip_text_ids(slide)

    # Modernize retired framework CSS vars (framework drift) so an old slide
    # doesn't render-fail on R-CSSVAR after paste into a current-framework deck.
    slide, n_vars = _map_retired_vars(slide)

    # Provenance — the validator downgrades typography/color violations to
    # warnings for slides carrying `lifted` (same contract as lift-slides.py).
    slide["lifted"] = f"{src_path.parent.name}#{matches[0].get('key')}"

    # Copy referenced local assets to target-relative paths
    src_dir = src_path.resolve().parent
    dst_dir = args.deck.resolve().parent
    report = _copy_slide_assets(slide, src_dir, dst_dir)
    # Lift large inline base64 images out of deck.json into asset files (keeps the
    # deck small + dodges the P50 base64-in-fragment trap). After the copy so the
    # new assets/lift-* refs aren't mis-scanned as missing-in-source.
    extracted = _extract_inline_images(slide, dst_dir, new_key)

    slides = deck.setdefault("slides", [])
    n = len(slides)
    # `is not None` so an explicit `position 0` is validated (and rejected) as
    # out-of-range rather than silently coerced to append (falsy-zero).
    pos = args.position if args.position is not None else n + 1
    if not (1 <= pos <= n + 1):
        print(f"deck-cli: position out of range (1..{n+1})", file=sys.stderr)
        return 1, None
    slides.insert(pos - 1, slide)

    variant = f"/{slide['variant']}" if slide.get("variant") else ""
    print(f"  pasted '{matches[0].get('key')}' from {src_path.name} → position {pos} "
          f"as '{new_key}' (layout={slide.get('layout')}{variant})")
    if n_css:
        print(f"    rekeyed {n_css} embedded data-slide-key selector(s) → '{new_key}'")
    if n_ids:
        print(f"    stripped {n_ids} source-bound data-text-id attr(s) "
              f"(re-render regenerates the sidecar)")
    if n_vars:
        print(f"    remapped {n_vars} retired CSS var ref(s) "
              f"({', '.join(f'{o}→{n}' for o, n in _RETIRED_VAR_MAP.items())})")
    if report["input"]:
        print(f"    input/ copied: {report['input']}")
    if report["prototypes"]:
        print(f"    prototypes/ copied: {report['prototypes']}")
    if report.get("local"):
        print(f"    deck-local assets copied: {report['local']}")
    if report["missing"]:
        print(f"    ⚠ assets MISSING in source (broken refs after paste): {report['missing']}")
    if extracted:
        print(f"    inline base64 → asset file(s): {extracted}")
    return 0, deck


# ---------------------------------------------------------------------------
# Scaffold templates
# ---------------------------------------------------------------------------

def build_scaffold(layout: str, variant: str | None, key: str) -> dict | None:
    common = {"key": key, "layout": layout, "screen_label": f"{key} (TODO)"}
    if variant:
        common["variant"] = variant

    SCAFFOLDS = {
        ("cover", None):           {"title": "〔标题 TODO〕", "author": "〔姓名 TODO〕", "date": "2026.MM.DD"},
        ("agenda", None):          {"items": [{"title_zh": "〔议程 1〕"}, {"title_zh": "〔议程 2〕"}]},
        ("section", None):         {"chapter_num": "01.", "title": "〔章节标题 TODO〕"},
        ("content", "3up"):        {"title": "〔标题 TODO〕", "cards": [
                                       {"title_zh": "〔卡片 1〕", "body": "〔正文 TODO〕"},
                                       {"title_zh": "〔卡片 2〕", "body": "〔正文 TODO〕"},
                                       {"title_zh": "〔卡片 3〕", "body": "〔正文 TODO〕"}]},
        ("content", "2col"):       {"title": "〔标题 TODO〕", "text": {"lede": "〔引言 TODO〕"},
                                    "visual": {"type": "placeholder", "label": "〔visual TODO〕"}},
        ("content", "story-case"): {"title": "〔案例标题 TODO〕", "industry": "〔行业 TODO〕",
                                    "hook": {"lead": "〔前 ", "accent": "强调词", "tail": " 后〕"},
                                    "arc": {"pain": "〔痛点 TODO TODO TODO〕",
                                            "conflict": "〔冲突 TODO TODO TODO〕",
                                            "solution": "〔解法 TODO TODO TODO〕",
                                            "value": {"lead": "〔前 ", "accent": "强调", "tail": " 后〕"}},
                                    "scene": {"image": "scene.png", "caption": "〔场景描述 TODO〕",
                                              "alt": "〔图片 alt TODO〕"}},
        ("content", "blocks"):     {"title": "〔标题 TODO〕", "body_blocks": [
                                       {"type": "pullquote", "text": "〔金句 TODO〕"}]},
        ("content", "matrix"):     {"title": "〔标题 TODO〕",
                                    "axes": {"y": {"name": "〔Y 轴名 TODO〕"},
                                             "x": {"name": "〔X 轴名 TODO〕"}},
                                    "quadrants": {
                                       "tl": {"ord": "A", "title": "〔象限 A〕", "items": ["〔条目 1〕"]},
                                       "tr": {"ord": "B", "title": "〔象限 B〕", "items": ["〔条目 1〕"]},
                                       "bl": {"ord": "D", "title": "〔象限 D〕", "items": ["〔条目 1〕"]},
                                       "br": {"ord": "C", "title": "〔象限 C〕", "items": ["〔条目 1〕"]}}},
        ("content", "before-after"):{"title": "〔标题 TODO〕",
                                    "before": {"tag": "〔现状 · 痛点〕", "items": [
                                       "〔痛点 1 TODO〕", "〔痛点 2 TODO〕", "〔痛点 3 TODO〕"]},
                                    "pivot": {"caption": "〔转折说明 TODO〕"},
                                    "after": {"tag": "〔用飞书之后〕", "items": [
                                       "〔改善 1 TODO〕", "〔改善 2 TODO〕", "〔改善 3 TODO〕"]}},
        ("stats", "row"):          {"title": "〔标题 TODO〕", "cols": [
                                       {"num": "0", "label": "〔标签 1 TODO〕"},
                                       {"num": "0", "label": "〔标签 2 TODO〕"},
                                       {"num": "0", "label": "〔标签 3 TODO〕"}]},
        ("stats", "hero"):         {"stat": {"number": "0"}, "heading": "〔Heading TODO〕",
                                    "body": "〔Body 描述 TODO TODO TODO〕"},
        ("stats", "waterfall"):    {"title": "〔标题 TODO〕", "bars": [
                                       {"kind": "base", "value": "100", "label": "〔起点〕"},
                                       {"kind": "pos",  "value": "+20", "label": "〔正向〕"},
                                       {"kind": "end",  "value": "120", "label": "〔终点〕"}]},
        ("quote", None):           {"quote": {"lead": "〔前 ", "accent": "强调短语", "tail": " 后〕"},
                                    "attribution": "〔归属 TODO〕"},
        ("image-text", None):      {"image": {"src": "scene.png", "alt": "〔alt TODO〕"},
                                    "title": "〔hero 标题 TODO〕"},
        ("table", None):           {"title": "〔标题 TODO〕",
                                    "headers": ["列1", "列2", "列3"],
                                    "rows": [["a", "b", "c"]]},
        ("flow", "timeline"):      {"title": "〔标题 TODO〕", "cols": 3, "nodes": [
                                       {"when": "W1", "what": "〔阶段 1〕"},
                                       {"when": "W2", "what": "〔阶段 2〕"},
                                       {"when": "W3", "what": "〔阶段 3〕"}]},
        ("flow", "process"):       {"title": "〔标题 TODO〕", "cols": 3, "steps": [
                                       {"title": "〔步骤 1〕", "body": "〔描述〕"},
                                       {"title": "〔步骤 2〕", "body": "〔描述〕"},
                                       {"title": "〔步骤 3〕", "body": "〔描述〕"}]},
        ("flow", "tree"):          {"title": "〔标题 TODO〕",
                                    "root": {"question": "〔根问题?〕"},
                                    "branches": [
                                       {"ord": "A", "title": "〔分支 A〕", "leaves": ["〔叶子〕"]},
                                       {"ord": "B", "title": "〔分支 B〕", "leaves": ["〔叶子〕"]}]},
        ("flow", "swim"):          {"title": "〔标题 TODO〕",
                                    "time_axis": ["〔Q1〕", "〔Q2〕", "〔Q3〕"],
                                    "lanes": [
                                       {"name": "〔泳道 1 TODO〕", "milestones": [
                                          {"quarter": 1, "title": "〔里程碑 TODO〕"},
                                          {"quarter": 3, "title": "〔里程碑 TODO〕"}]},
                                       {"name": "〔泳道 2 TODO〕", "milestones": [
                                          {"quarter": 2, "title": "〔里程碑 TODO〕"}]}]},
        ("end", None):             {},
        ("replica", None):         {"page_image": "page-01.jpg"},
        ("raw", None):             {"html": '<div class="slide" data-layout="raw" data-screen-label="〔TODO〕" data-slide-key="〔TODO〕"><div class="wordmark">飞书</div>〔自由内容 HTML〕</div>'},
    }

    scaffold_data = SCAFFOLDS.get((layout, variant))
    if scaffold_data is None:
        return None
    common["data"] = scaffold_data
    return common


# ---------------------------------------------------------------------------
# Render wrapper
# ---------------------------------------------------------------------------

def cmd_render(deck_path: Path, args) -> int:
    cmd = [sys.executable, str(RENDER_DECK), str(deck_path), str(args.output_dir)]
    if args.inline:           cmd.append("--inline")
    if args.skip_copy_assets: cmd.append("--skip-copy-assets")
    rc = subprocess.run(cmd)
    return 5 if rc.returncode != 0 else 0


# ---------------------------------------------------------------------------
# CLI dispatch
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="deck-cli.py", description=__doc__.split("\n")[0])
    ap.add_argument("deck", type=Path, help="path to deck.json")
    ap.add_argument("--yes", action="store_true", help="skip interactive confirms")
    ap.add_argument("--no-backup", action="store_true", help="skip .bak-pre-* backup")
    ap.add_argument("--force", action="store_true",
                    help="bypass concurrent-modification (optimistic-lock) check — "
                         "write even if deck.json changed on disk since it was read")

    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="list slides")
    sp = sub.add_parser("get", help="get value at dotted path"); sp.add_argument("path")
    sp = sub.add_parser("show", help="pretty-print one slide"); sp.add_argument("key")
    sp = sub.add_parser("get-page",
        help="dump ONE slide's authored content by key or 1-based index (#N) — "
             "read-side replacement for ad-hoc extractors")
    sp.add_argument("ref", help="slide key, or 1-based page index (36 / #36)")
    sp.add_argument("--html", action="store_true", help="print raw data.html only")
    sp.add_argument("--css", action="store_true", help="print raw custom_css only")
    sp.add_argument("--title", action="store_true", help="print data.title only")
    sp = sub.add_parser("inspect-text",
                        help="dump a page's effective text + font-size map, "
                             "following iframe src into embedded prototype files")
    sp.add_argument("ref", help="slide key, or 1-based page index (36 / #36)")
    sp = sub.add_parser("lint", help="validate against schema")
    sp.add_argument("--strict", action="store_true",
                    help="promote warnings to errors (default: lenient)")

    sp = sub.add_parser("set", help="set value at dotted path")
    sp.add_argument("path"); sp.add_argument("value", nargs="?", default=None)
    sp.add_argument("--from-file", dest="from_file", type=Path, default=None,
                    help="read the value VERBATIM from this file (raw string, "
                         "no JSON coercion) — the channel for large payloads "
                         "like data.html / custom_css")
    sp.add_argument("--str", dest="str", action="store_true",
                    help="treat VALUE as a raw string — never JSON-coerce "
                         "(e.g. keep '2024' a string, not the int 2024)")
    sp.add_argument("--json", dest="json", action="store_true",
                    help="force JSON coercion of VALUE even when the field "
                         "currently holds a string (deliberate string→number/"
                         "bool/null retype)")

    sp = sub.add_parser("set-page",
                        help="one-shot page payload: --html/--css from files "
                             "(+ --title/--lifted), pre-write linted (W4)")
    sp.add_argument("key")
    sp.add_argument("--html", type=Path, default=None,
                    help="file whose content becomes data.html")
    sp.add_argument("--css", type=Path, default=None,
                    help="file whose content becomes custom_css")
    sp.add_argument("--title", default=None, help="set data.title")
    sp.add_argument("--lifted", action="store_true",
                    help="mark slide lifted:true (verbatim from another deck — "
                         "font-tier findings downgrade to warnings)")
    sp.add_argument("--skip-lint", action="store_true",
                    help="bypass the W4 static pre-write lint (NOT recommended)")

    sp = sub.add_parser("consolidate-css",
                        help="fold a raw page's embedded <style> into custom_css "
                             "(single-source home; kills the custom_css silent-"
                             "override trap). Default: all raw pages.")
    sp.add_argument("--key", default=None,
                    help="one slide-key (default: every raw page)")
    sp.add_argument("--dry-run", dest="dry_run", action="store_true",
                    help="report what would move, write nothing")

    sp = sub.add_parser("set-accent", help="set slide accent color")
    sp.add_argument("key"); sp.add_argument("color")

    sp = sub.add_parser("set-decor", help="set slide decor tokens (comma-sep)")
    sp.add_argument("key"); sp.add_argument("tokens")

    sp = sub.add_parser("set-notes", help="set/clear a slide's speaker notes (口播稿, shown in presenter view P)")
    sp.add_argument("key"); sp.add_argument("text", help='note text (empty string "" clears it)')

    sp = sub.add_parser("set-variant", help="change variant of content/stats/flow slide")
    sp.add_argument("key"); sp.add_argument("variant")

    sp = sub.add_parser("hide", help="隐藏页: skip slide(s) in present-mode 翻页 (still rendered + reachable by #hash/scroll)")
    sp.add_argument("keys", nargs="+", help="one or more slide keys")

    sp = sub.add_parser("unhide", help="un-hide slide(s) by key (re-render to apply)")
    sp.add_argument("keys", nargs="+", help="one or more slide keys")

    sp = sub.add_parser("reorder", help="move slide by position (1-indexed)")
    sp.add_argument("from_pos", type=int); sp.add_argument("to_pos", type=int)

    sp = sub.add_parser("move-key", help="move slide by key to position")
    sp.add_argument("key"); sp.add_argument("position", type=int)

    sp = sub.add_parser("insert", help="insert scaffold slide at position")
    sp.add_argument("position", type=int)
    sp.add_argument("layout"); sp.add_argument("variant", nargs="?", default=None)
    sp.add_argument("key")

    sp = sub.add_parser("delete", help="delete slide by key (confirm + backup mandatory)")
    sp.add_argument("key")

    sp = sub.add_parser("clone", help="duplicate slide by key")
    sp.add_argument("key"); sp.add_argument("new_key")
    sp.add_argument("position", type=int, nargs="?", default=None)

    sp = sub.add_parser("paste", help="copy a slide from another deck.json into this one (+assets)")
    sp.add_argument("--from", dest="from_deck", type=Path, required=True, metavar="SRC",
                    help="source deck.json to copy from")
    sp.add_argument("--key", required=True, help="slide-key to copy from SRC")
    sp.add_argument("--new-key", dest="new_key", default=None,
                    help="rename pasted slide (default: keep key, auto-suffix on collision)")
    sp.add_argument("position", type=int, nargs="?", default=None,
                    help="1-indexed insert position (default: append at end)")

    sp = sub.add_parser("render", help="render to HTML (wrap render-deck.py)")
    sp.add_argument("output_dir", type=Path)
    sp.add_argument("--inline", action="store_true")
    sp.add_argument("--skip-copy-assets", action="store_true")

    sp = sub.add_parser("add-asset",
                        help="compress + place an image into <deck-dir>/input/ "
                             "and print the relative URL (vs hand-base64'ing "
                             "into fragments — deck bloat + P50)")
    sp.add_argument("file", type=Path)
    sp.add_argument("--max-width", dest="max_width", type=int, default=1600)
    sp.add_argument("--quality", type=int, default=85)
    sp.add_argument("--name", default=None,
                    help="output filename (default: source name; extension "
                         "follows the chosen format)")

    args = ap.parse_args(argv)

    # 无感自动 backfill (spec §10 decision 3): paste into a LEGACY HTML-only deck
    # (no deck.json, but a sibling index.html) → reverse-build the deck.json 中间层
    # from the rendered DOM FIRST (each .slide → raw, lossless, no screenshots),
    # so the paste then runs against a real deck.json. Only for `paste` — other
    # commands keep the explicit "deck not found" error.
    if args.cmd == "paste" and not args.deck.exists():
        _sib = args.deck.parent / "index.html"
        if _sib.exists():
            import subprocess
            _sync = Path(__file__).resolve().parent / "sync-index-to-deck.py"
            print(f"deck-cli: dest has no deck.json — auto-backfilling from {_sib} "
                  "before paste (legacy HTML deck)", file=sys.stderr)
            _r = subprocess.run([sys.executable, str(_sync), str(_sib), str(args.deck)],
                                capture_output=True, text=True)
            if _r.returncode != 0 or not args.deck.exists():
                print(f"deck-cli: auto-backfill failed:\n{_r.stderr or _r.stdout}",
                      file=sys.stderr)
                return 2

    # Load deck (capture mtime for the optimistic-lock check on write-back)
    try:
        deck_mtime = args.deck.stat().st_mtime
        deck = json.loads(args.deck.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"deck-cli: deck not found: {args.deck}", file=sys.stderr); return 2
    except json.JSONDecodeError as e:
        print(f"deck-cli: invalid JSON: {e}", file=sys.stderr); return 2

    READ_CMDS = {"list": cmd_list, "get": cmd_get, "show": cmd_show,
                 "get-page": cmd_get_page, "add-asset": cmd_add_asset,
                 "inspect-text": cmd_inspect_text}
    if args.cmd in READ_CMDS:
        return READ_CMDS[args.cmd](deck, args)
    if args.cmd == "lint":
        return cmd_lint(args.deck, args)
    if args.cmd == "render":
        return cmd_render(args.deck, args)

    # Write commands return (rc, deck_or_None)
    WRITE_CMDS = {
        "set":         cmd_set,
        "set-page":    cmd_set_page,
        "consolidate-css": cmd_consolidate_css,
        "set-accent":  cmd_set_accent,
        "set-decor":   cmd_set_decor,
        "set-notes":   cmd_set_notes,
        "set-variant": cmd_set_variant,
        "hide":        cmd_hide,
        "unhide":      cmd_unhide,
        "reorder":     cmd_reorder,
        "move-key":    cmd_move_key,
        "insert":      cmd_insert,
        "delete":      cmd_delete,
        "clone":       cmd_clone,
        "paste":       cmd_paste,
    }
    handler = WRITE_CMDS.get(args.cmd)
    if not handler:
        print(f"deck-cli: unknown command '{args.cmd}'", file=sys.stderr); return 1

    # F-315: CLOBBER GUARD (Option A — auto-sync-if-lossless, else refuse) — before
    # mutating deck.json, handle a sibling index.html that carries edits made after
    # its last render (browser edit-mode ⌘S / hand-patch) and never synced back.
    # Editing deck.json now and re-rendering would silently destroy them (deck.json
    # is the source; index.html is regenerated from it). Checked here, where
    # deck.json still matches the last render, so the verdict is unambiguous.
    #   ok       → no un-synced edit; proceed (fast path).
    #   autosync → edits are ALL lossless → fold them into deck.json FIRST (then the
    #              command's edit layers on top; both survive), and RELOAD deck.
    #   refuse   → lossy (canvas) / baked / chrome-only / error → stop and tell the
    #              user. --force skips the whole guard and DISCARDS the edits.
    if not getattr(args, "force", False):
        from _index_sig import resolve_clobber, auto_sync as _idx_auto_sync
        _idx = args.deck.parent / "index.html"
        _action, _reason = resolve_clobber(args.deck, _idx)
        if _action == "refuse":
            _sync = Path(__file__).resolve().parent / "sync-index-to-deck.py"
            print(f"deck-cli: REFUSING '{args.cmd}' — {_reason}", file=sys.stderr)
            print("  → Inspect / recover first:", file=sys.stderr)
            print(f"      python3 {_sync} --dry-run {_idx} {args.deck}", file=sys.stderr)
            print("  → Or pass --force to edit deck.json anyway and DISCARD the "
                  "un-synced index.html edits.", file=sys.stderr)
            return 6
        if _action == "autosync":
            print(f"deck-cli: index.html has un-synced (lossless) browser edits — "
                  f"folding them into deck.json before '{args.cmd}'…", file=sys.stderr)
            _ok, _out = _idx_auto_sync(args.deck, _idx)
            if not _ok:
                print(f"deck-cli: auto-sync FAILED — refusing to proceed:\n{_out}",
                      file=sys.stderr)
                return 6
            # auto-sync rewrote deck.json on disk → reload so the command's handler
            # (and the optimistic-lock mtime) operate on the freshly-synced source.
            deck = json.loads(args.deck.read_text(encoding="utf-8"))
            deck_mtime = args.deck.stat().st_mtime
            print("deck-cli: ✓ folded browser edits into deck.json; continuing.",
                  file=sys.stderr)

    rc, updated = handler(deck, args)
    if rc != 0 or updated is None:
        return rc

    ok = write_deck_with_validation(args.deck, updated, args.cmd, args.no_backup,
                                    expected_mtime=deck_mtime,
                                    force=getattr(args, "force", False),
                                    scope_keys=_edit_scope_keys(args, updated))
    return 0 if ok else 3


if __name__ == "__main__":
    sys.exit(main())
