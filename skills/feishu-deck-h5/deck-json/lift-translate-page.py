#!/usr/bin/env python3
"""
lift-translate-page.py — lift ONE deck.json-native page into an existing deck AND
prep its translation, as a two-phase flow that only SEQUENCES existing, validated
tools (deck-cli paste · extract-text-pairs · apply-text-pairs · render-deck).

WHY THIS EXISTS
---------------
The lift+translate-one-page micro-flow was documented as prose in editor/SKILL.md
("Fast path — one DeckJSON page into an existing deck, incl. lift+translate"), so
each cold session the model hand-sequenced 6-10 separate tool calls — paste →
locate-slide → extract → fill → --check → apply --dry-run → apply → render — and
re-discovered the chain every time (the exact re-archaeology the 2026-06 perf audit
flagged). This driver collapses the MECHANICAL glue into two commands. The model's
only job is the irreducible part: filling the {find,replace} English between the two
phases.

It DUPLICATES no copy/rekey/swap/render logic — every mutation goes through the
proven tools: paste (F-255 CSS rekey + data-text-id strip + retired-var remap +
asset copy + `lifted` stamp + optimistic lock + drift guard, reused from
lift-to-new-deck.py), apply-text-pairs (structure-safe swap, schema rollback,
exit-5 unmatched assertion, canvas "matched NO run" warning), and render-deck
(scoped gate + screenshot). It NEVER lets an LLM rewrite markup (translator Hard
Gate 1) and ends on the scoped render gate (Hard Gate 4).

HONEST SCOPE
------------
Whole-deck translation QA (residual-CJK / overflow, `translation-qa.py`) stays a
DELIVERY-checkpoint step — translation-qa.py has no per-page scope, so this per-page
driver does NOT fake one. Run it (plus `assets/validate.py --visual`) at delivery,
which Hard Gate 4 already prescribes. The win here is "fewer model turns + no
speculative re-renders for the mechanical chain", NOT minutes of saved render time.

USAGE
-----
  Phase 1 — paste the page + emit a translation skeleton scoped to JUST that page:
    lift-translate-page.py emit-pairs DEST_DECK SRC PAGE [POS] \
        [--new-key K] [--glossary G] [-o PAIRS] [--allow-drift]

    DEST_DECK  existing deck.json to paste INTO (must already exist).
    SRC        source — a deck.json / deck dir / index.html (deck.json-native).
    PAGE       which source page (locate-slide.py syntax: 46, #46, a key, a title);
               must resolve to EXACTLY one page.
    POS        1-based insert position in DEST (default: append at end).

  → then FILL every "replace" in the emitted PAIRS (apply the glossary; condense EN
    so it does not overflow the CJK-width box), and run phase 2.

  Phase 2 — gate + apply the filled pairs + render the one page scoped:
    lift-translate-page.py apply PAIRS

    PAIRS carries a sidecar PAIRS.meta.json (written by phase 1) recording the dest
    deck + landed key + 1-based position, so phase 2 needs no extra args.

EXIT: 0 ok · 1 usage/resolve error · 2 file error · 4 render BLOCKED ·
      5 unfilled/unmatched pairs (gate). Non-zero from a wrapped tool is propagated.
"""

import argparse
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DECK_CLI = HERE / "deck-cli.py"
EXTRACT = HERE / "extract-text-pairs.py"
APPLY = HERE / "apply-text-pairs.py"
RENDER = HERE / "render-deck.py"
VALIDATE = HERE.parent / "assets" / "validate.py"
TRANSLATION_QA = HERE / "translation-qa.py"
GLOSSARY_DEFAULT = HERE.parent / "subskills" / "translator" / "glossary.default.json"


def _err(msg):
    print(f"lift-translate-page: {msg}", file=sys.stderr)


def _load_ltnd():
    """Reuse lift-to-new-deck.py's blessed source-resolve / page-resolve / drift
    guard (hyphenated filename → import via importlib)."""
    spec = importlib.util.spec_from_file_location(
        "lift_to_new_deck", HERE / "lift-to-new-deck.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(cmd, capture=True):
    return subprocess.run([sys.executable, *map(str, cmd)],
                          capture_output=capture, text=True)


# ---------------------------------------------------------------- phase 1 -----
def emit_pairs(args):
    ltnd = _load_ltnd()

    dest_deck = args.dest_deck
    if not dest_deck.exists():
        _err(f"dest deck.json not found: {dest_deck}\n"
             f"  this driver pastes INTO an existing deck; create one first "
             f"(deck-cli.py new-deck / lift-to-new-deck.py).")
        return 2

    src_deck = ltnd.resolve_source_deck(args.src)
    if src_deck is None:
        return 2

    hits = ltnd.resolve_pages(src_deck, args.page)
    if hits is None:
        return 1
    if len(hits) != 1:
        _err(f"PAGE must resolve to exactly ONE page (matched {len(hits)}: "
             f"{', '.join(h['key'] for h in hits)}). Lift a single page per call.")
        return 1

    # Drift guard (reused): refuse a lift whose source CSS is stranded in the
    # rendered <head> — a naive paste would silently drop styling. (Same contract
    # as lift-to-new-deck.py; --allow-drift to bypass and recover CSS by hand.)
    drifted = ltnd.detect_drifted(args.src, src_deck, hits)
    if drifted and not args.allow_drift:
        _err(
            "源 deck.json 漂移:待拎页 custom_css 为空、样式留在 rendered index.html "
            f"的 <head>:{', '.join(drifted)}\n"
            "  裸 lift 会丢 CSS+accent/decor+背景图。先修源 deck 再重跑:\n"
            f"    python3 {(HERE / 'repair-lifted.py').name} {src_deck.parent} --apply\n"
            "  (确要手动恢复可加 --allow-drift。)")
        return 1

    # 1) paste — the ONE deterministic lift call (rekey + assets + lifted + lock).
    cmd = [DECK_CLI, "--yes", dest_deck, "paste",
           "--from", src_deck, "--key", hits[0]["key"]]
    if args.new_key:
        cmd += ["--new-key", args.new_key]
    if args.pos is not None:
        cmd += [str(args.pos)]
    r = _run(cmd)
    sys.stdout.write(r.stdout)
    if r.stderr:
        sys.stderr.write(r.stderr)
    if r.returncode != 0:
        _err(f"paste failed (rc={r.returncode}); nothing written downstream.")
        return r.returncode

    # Parse the landed key + 1-based position from paste's own report line:
    #   pasted '<src>' from <f> → position <pos> as '<landed>' (layout=…)
    m_key = re.search(r"as '([^']+)'", r.stdout)
    m_pos = re.search(r"→ position (\d+)", r.stdout)
    if not (m_key and m_pos):
        _err("could not parse landed key/position from paste output; aborting before "
             "extract (re-run paste manually and use extract-text-pairs --slides).")
        return 1
    landed_key, pos = m_key.group(1), int(m_pos.group(1))

    # 2) extract a translation skeleton scoped to ONLY the pasted page (--slides).
    r = _run([EXTRACT, dest_deck, "--slides", landed_key])
    if r.returncode != 0:
        sys.stderr.write(r.stderr)
        _err(f"extract-text-pairs failed (rc={r.returncode}).")
        return r.returncode

    pairs_path = args.out or (dest_deck.parent / "lift-translate.pairs.json")
    pairs_path.write_text(r.stdout, encoding="utf-8")
    meta_path = pairs_path.with_suffix(pairs_path.suffix + ".meta.json")
    meta_path.write_text(json.dumps(
        {"deck": str(dest_deck), "key": landed_key, "pos": pos},
        ensure_ascii=False, indent=2), encoding="utf-8")

    glossary = args.glossary or GLOSSARY_DEFAULT
    try:
        n_pairs = len(json.loads(r.stdout))
    except Exception:
        n_pairs = "?"
    print(f"\n✔ pasted → page {pos} (key '{landed_key}')")
    print(f"  skeleton → {pairs_path}  ({n_pairs} find/replace pair(s))")
    print(f"  NEXT: fill every \"replace\" (glossary: {glossary}; condense EN to fit "
          f"the CJK box), then:")
    print(f"    python3 {Path(__file__).name} apply {pairs_path}")
    return 0


# ---------------------------------------------------------------- phase 2 -----
def apply_pairs(args):
    pairs = args.pairs
    if not pairs.exists():
        _err(f"pairs file not found: {pairs}")
        return 2
    meta_path = pairs.with_suffix(pairs.suffix + ".meta.json")
    if not meta_path.exists():
        _err(f"sidecar {meta_path.name} not found — was this PAIRS emitted by "
             f"'emit-pairs'? (it records the dest deck + page to render.)")
        return 2
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    deck = Path(meta["deck"])
    pos = meta["pos"]
    out_dir = deck.parent

    # 1) gate: every replace filled, no residual CJK (extract --check, exit 5).
    r = _run([EXTRACT, "--check", pairs])
    sys.stdout.write(r.stdout)
    if r.returncode != 0:
        sys.stderr.write(r.stderr)
        _err("pairs not ready (empty replace or residual CJK). Fill them, re-run apply.")
        return r.returncode

    # 2) dry-run: every pair must hit exactly once (exit 5 = some find unmatched).
    r = _run([APPLY, deck, pairs, "--dry-run"])
    sys.stdout.write(r.stdout)
    if r.returncode != 0:
        sys.stderr.write(r.stderr)
        _err("dry-run found unmatched/over-matched pairs (rc=5) — DO NOT --force; "
             "fix the find side (or hand-resolve canvas 'matched NO run' phrases). "
             "Nothing was written.")
        return r.returncode

    # 3) real swap (optimistic lock + schema rollback inside apply-text-pairs).
    r = _run([APPLY, deck, pairs])
    sys.stdout.write(r.stdout)
    if r.returncode != 0:
        sys.stderr.write(r.stderr)
        _err(f"apply failed (rc={r.returncode}); apply-text-pairs rolled back on a "
             f"schema fail. deck.json unchanged.")
        return r.returncode

    # 4) scoped render + screenshot — the gate (Hard Gate 4, scoped form).
    r = _run([RENDER, deck, out_dir, "--scope", str(pos), "--shoot"], capture=False)
    rc = r.returncode
    verdict = "✔ PASS" if rc == 0 else ("✗ BLOCKED" if rc == 4 else "✗ FAIL")
    print(f"\n{verdict}  (render rc={rc}, scoped to page {pos})")

    log = out_dir / "last-render.log"
    if log.exists():
        head = log.read_text(encoding="utf-8").splitlines()[:4]
        print("  last-render.log:")
        for ln in head:
            print(f"    {ln}")
        print(f"  (full: {log} · screenshot: {out_dir}/*.shoot-p{pos}.png)")
    print("  DELIVERY checkpoint (Hard Gate 4 — run before handoff, NOT per page):")
    print(f"    python3 {VALIDATE} {out_dir}/index.html --visual")
    print(f"    python3 {TRANSLATION_QA} residual-cjk --strict-fullwidth "
          f"{out_dir}/index.html   # + overflow")
    return rc


def main(argv):
    ap = argparse.ArgumentParser(
        prog="lift-translate-page.py",
        description="Two-phase lift+translate of ONE deck.json page (sequences "
                    "existing tools only).")
    sub = ap.add_subparsers(dest="phase", required=True)

    e = sub.add_parser("emit-pairs", help="paste one page + emit a scoped translation skeleton")
    e.add_argument("dest_deck", type=Path, help="existing deck.json to paste INTO")
    e.add_argument("src", type=Path, help="source deck.json / deck dir / index.html")
    e.add_argument("page", help="source page (locate-slide.py syntax); exactly one")
    e.add_argument("pos", type=int, nargs="?", default=None,
                   help="1-based insert position in dest (default: append)")
    e.add_argument("--new-key", dest="new_key", default=None,
                   help="rename the pasted slide-key (paste rewrites it across the CSS)")
    e.add_argument("--glossary", type=Path, default=None,
                   help=f"glossary for the fill step (default: {GLOSSARY_DEFAULT.name})")
    e.add_argument("-o", "--out", type=Path, default=None,
                   help="skeleton path (default: <dest-dir>/lift-translate.pairs.json)")
    e.add_argument("--allow-drift", action="store_true",
                   help="bypass the source-CSS-in-<head> drift guard")
    e.set_defaults(fn=emit_pairs)

    a = sub.add_parser("apply", help="gate + apply filled pairs + scoped render")
    a.add_argument("pairs", type=Path, help="filled pairs.json from emit-pairs")
    a.set_defaults(fn=apply_pairs)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
