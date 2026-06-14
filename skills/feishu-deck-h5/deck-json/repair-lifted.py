#!/usr/bin/env python3
"""repair-lifted.py — F-267: one-command repair pipeline for a LIFTED / IMPORTED
deck (back-catalog drift).

The problem this solves (F-267)
-------------------------------
A deck assembled by lifting/importing pages from OTHER decks accumulates a
predictable set of back-catalog defects, and the FIXES already exist as three
single-purpose tools plus two upstream codemods — but with ZERO routing. An
agent faced with a garbled imported deck had to know, in the right order, to run
`sync-index-to-deck --backfill` (if there is no deck.json yet),
`migrate-head-css-to-custom-css` (if per-slide CSS leaked into a head <style>),
then `heal-lifted` → `clean-lifted-css` → `reconcile-lifted`, then re-render and
validate. Nobody remembers that sequence. This orchestrator IS that sequence.

It is a THIN shell-out wrapper. Every real change is made by the existing tool
(each of which already has its own backup / optimistic-lock / `--dry-run`); this
script only decides WHICH steps apply (by file existence + a cheap precondition
scan) and runs them in the proven order:

  1. backfill            — sync-index-to-deck.py --backfill
                           ONLY when there is NO deck.json yet (HTML-only deck).
  2. migrate-head-css    — migrate-head-css-to-custom-css.py
                           ONLY when index.html has head/deck-level per-slide CSS
                           (`[data-slide-key=…]` / `[data-page=…]` in a <style>
                           that sits OUTSIDE any .slide). Otherwise skipped.
  3. heal-lifted         — heal-lifted.py        (drop illegal prefix-then-comment
                           dead rules — browser already ignores them)
  4. clean-lifted-css    — clean-lifted-css.py   (repair CSS baked INSIDE
                           @keyframes by the old scoper)
  5. reconcile-lifted    — reconcile-lifted.py   (snap off-ladder inline font
                           sizes onto the {16,24,28,48} type ladder)
  6. render + validate   — render-deck.py  then  validate-deck.py --strict
                           (regenerate index.html from the repaired deck.json and
                           prove the result is schema-clean).

dry-run-first (IMPORTANT — not "zero-risk direct")
--------------------------------------------------
The default is `--dry-run`: it PRINTS the plan and runs each applicable step in
its own dry-run mode (writing nothing), so you see exactly what each tool would
change. Add `--apply` to actually run the pipeline. This is deliberate: the
docs/archive record shows heal-lifted's "provably-safe" premise was once
falsified and rolled back, so we never assume a blind direct run is safe — you
preview, then apply.

Steps 3–5 each write a `deck.json.bak-pre-<cmd>-<ts>` before mutating (via
shutil.copy2) and honor `--dry-run`, but they do NOT themselves re-validate or
roll back — the timestamped .bak is the recovery point, and the final step 6
(render + validate --strict) is what proves the cumulative result is
schema-clean (and render-deck rolls back its own index.html on a gate fail).
Steps 1–2 also honor `--dry-run`; this orchestrator adds no writes of its own.

USAGE
-----
    python3 repair-lifted.py <DECK>              # dry-run: print the plan
    python3 repair-lifted.py <DECK> --apply      # run the pipeline for real

    <DECK> may be the deck DIRECTORY (the output/ dir), its index.html, or its
    deck.json — the siblings are resolved automatically.

    --apply              run the pipeline (default is dry-run / preview only)
    --output-dir DIR     where render writes index.html (default: deck dir)
    --no-render          skip the final render + validate step
    --visual             pass --visual to the final render (promotes the visual
                         audits to hard gates)
    --force              forward --force to the steps that take it (heal / clean /
                         reconcile optimistic-lock bypass)

stdlib only. Python 3.10+.
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

# The orchestrated tools (resolved beside this script / the assets dir).
SYNC = HERE / "sync-index-to-deck.py"
MIGRATE = HERE / "migrate-head-css-to-custom-css.py"
HEAL = HERE / "heal-lifted.py"
CLEAN = HERE / "clean-lifted-css.py"
RECONCILE = HERE / "reconcile-lifted.py"
CONFORM = HERE / "conform-to-deck.py"
RENDER = HERE / "render-deck.py"
VALIDATE = HERE / "validate-deck.py"


# --- precondition scan: head/deck-level per-slide CSS (migrate gate) ----------
# Mirror the detection migrate-head-css-to-custom-css.py uses: a per-slide
# selector (`[data-slide-key="K"]` or `[data-page="N"]`) inside a <style> block
# that sits OUTSIDE any .slide. We do a cheap, conservative version here purely
# to decide WHETHER to run migrate; migrate itself does the precise mapping and
# is idempotent, so a false-positive here just means migrate runs and reports
# "nothing to migrate" (a no-op), never a wrong edit.
_STYLE_RE = re.compile(r'<style(?P<attrs>[^>]*)>(?P<body>.*?)</style>', re.S | re.I)
_SLIDE_OPEN_RE = re.compile(r'<div\s+class="slide(?:\s[^"]*)?"', re.I)
_PERSLIDE_SEL_RE = re.compile(r'\[data-(?:slide-key|page)=', re.I)


def _slide_spans(html):
    """Char spans of each `.slide` element (open-tag start → its </div>, by
    div-depth balance) so we can tell head-level <style> from in-slide <style>."""
    spans = []
    for m in _SLIDE_OPEN_RE.finditer(html):
        start = m.start()
        gt = html.find(">", m.end())
        if gt == -1:
            continue
        depth, i = 1, gt + 1
        while i < len(html) and depth:
            nd = html.find("<div", i)
            cd = html.find("</div", i)
            if cd == -1:
                break
            if nd != -1 and nd < cd:
                depth += 1
                i = nd + 4
            else:
                depth -= 1
                i = cd + 5
        spans.append((start, i))
    return spans


def has_head_perslide_css(index_html_text):
    """True if a <style> block OUTSIDE every .slide carries a per-slide selector
    (`[data-slide-key=]` / `[data-page=]`) — the head-leak migrate fixes."""
    spans = _slide_spans(index_html_text)

    def inside(pos):
        return any(a <= pos < b for a, b in spans)

    for m in _STYLE_RE.finditer(index_html_text):
        if inside(m.start()):
            continue
        if _PERSLIDE_SEL_RE.search(m.group("body") or ""):
            return True
    return False


# --- deck path resolution -----------------------------------------------------
def resolve_paths(deck_arg):
    """From a deck DIRECTORY / index.html / deck.json, return (deck_dir,
    index_html, deck_json) as Paths (index_html / deck_json may not exist yet)."""
    p = Path(deck_arg).resolve()
    if p.is_dir():
        deck_dir = p
        index_html = deck_dir / "index.html"
        deck_json = deck_dir / "deck.json"
    elif p.name == "deck.json" or p.suffix == ".json":
        deck_json = p
        deck_dir = p.parent
        index_html = deck_dir / "index.html"
    elif p.suffix in (".html", ".htm"):
        index_html = p
        deck_dir = p.parent
        deck_json = deck_dir / "deck.json"
    else:
        # Bare path that isn't a dir and has no recognized suffix — treat as a
        # directory stem (don't guess a file type).
        deck_dir = p
        index_html = deck_dir / "index.html"
        deck_json = deck_dir / "deck.json"
    return deck_dir, index_html, deck_json


def _run(cmd, dry):
    """Run a sub-tool; on failure print its output and abort the pipeline.
    Returns nothing — raises SystemExit on failure so a half-repaired deck is
    never silently accepted. Recovery: each lifted-CSS step (heal/clean/
    reconcile) leaves a timestamped `.bak-pre-<cmd>-<ts>` of the deck.json from
    BEFORE its own edit; render-deck rolls back its own index.html on a gate
    fail."""
    label = " ".join(Path(c).name if Path(c).name.endswith(".py") else str(c)
                     for c in cmd[1:])
    print(f"  $ {Path(sys.executable).name} {label}")
    r = subprocess.run(cmd, capture_output=True, text=True)
    out = (r.stdout or "").rstrip()
    err = (r.stderr or "").rstrip()
    if out:
        print("\n".join("      " + ln for ln in out.splitlines()))
    if r.returncode != 0:
        if err:
            print("\n".join("      " + ln for ln in err.splitlines()),
                  file=sys.stderr)
        verb = "preview" if dry else "step"
        print(f"\n✗ repair-lifted: {verb} failed "
              f"({Path(cmd[1]).name}, exit {r.returncode}); pipeline aborted. "
              f"Recover the deck.json from the latest .bak-pre-*-<ts> beside it "
              f"if a step had already written.", file=sys.stderr)
        sys.exit(r.returncode or 1)
    elif err:
        print("\n".join("      " + ln for ln in err.splitlines()))


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Default is --dry-run (preview). Add --apply to run for real.")
    ap.add_argument("deck", help="deck directory, its index.html, or its deck.json")
    ap.add_argument("--apply", action="store_true",
                    help="actually run the pipeline (default: dry-run preview)")
    ap.add_argument("--dry-run", action="store_true",
                    help="explicitly preview without changing anything (the default)")
    ap.add_argument("--output-dir", type=Path, default=None,
                    help="render output dir (default: the deck dir)")
    ap.add_argument("--no-render", action="store_true",
                    help="skip the final render + validate step")
    ap.add_argument("--visual", action="store_true",
                    help="pass --visual to the final render (hard visual gates)")
    ap.add_argument("--force", action="store_true",
                    help="forward --force to heal/clean/reconcile (lock bypass)")
    args = ap.parse_args(argv)

    # --apply wins; otherwise dry-run (the safe default, and what --dry-run asks).
    dry = not args.apply
    deck_dir, index_html, deck_json = resolve_paths(args.deck)
    output_dir = (args.output_dir.resolve() if args.output_dir else deck_dir)

    print(f"repair-lifted ({'DRY-RUN — preview only' if dry else 'APPLY'})")
    print(f"  deck dir   : {deck_dir}")
    print(f"  index.html : {index_html}  {'(exists)' if index_html.exists() else '(MISSING)'}")
    print(f"  deck.json  : {deck_json}  {'(exists)' if deck_json.exists() else '(absent)'}")
    print()

    # Build the plan from file existence + the precondition scan, then execute
    # (or, in dry-run, run each step in its own dry-run mode).
    dr = ["--dry-run"] if dry else []
    force = ["--force"] if args.force else []
    plan = []

    # --- Step 1: backfill (only if there is NO deck.json yet) -----------------
    if not deck_json.exists():
        if not index_html.exists():
            print("✗ no deck.json AND no index.html — nothing to repair "
                  "(need at least a rendered index.html to backfill from).",
                  file=sys.stderr)
            return 2
        plan.append(("backfill (deck.json absent → reconstruct from index.html)",
                     [sys.executable, str(SYNC), str(index_html), str(deck_json),
                      "--backfill", *dr]))
    else:
        print("  · backfill        SKIP — deck.json already present")

    # --- Step 2: migrate head-leak CSS (only if index.html has it) ------------
    # Needs a rendered index.html to scan. After a (dry-run) backfill the
    # index.html is unchanged, so scanning it now is valid in both modes.
    if index_html.exists():
        try:
            if has_head_perslide_css(index_html.read_text(encoding="utf-8")):
                plan.append((
                    "migrate-head-css (head/deck-level per-slide CSS detected)",
                    [sys.executable, str(MIGRATE), str(index_html), str(deck_json),
                     *dr]))
            else:
                print("  · migrate-head    SKIP — no head/deck-level per-slide CSS")
        except OSError as e:
            print(f"  · migrate-head    SKIP — could not read index.html ({e})")
    else:
        print("  · migrate-head    SKIP — no index.html to scan")

    # --- Steps 3–5: the three lifted-CSS repairs (operate on deck.json) -------
    # These need a deck.json. When it's absent in dry-run, backfill above only
    # PREVIEWED it (wrote nothing), so it won't exist yet — note that and skip
    # so we never run them against a non-existent file. In --apply, backfill
    # created it, so they run.
    deck_will_exist = deck_json.exists() or (not dry and not deck_json.exists()
                                             and index_html.exists())
    if deck_will_exist:
        for name, tool in (("heal-lifted", HEAL),
                           ("clean-lifted-css", CLEAN),
                           ("reconcile-lifted", RECONCILE)):
            plan.append((name, [sys.executable, str(tool), str(deck_json),
                                *dr, *force]))
    else:
        print("  · heal/clean/reconcile  SKIP in dry-run — deck.json would be "
              "created by backfill first (re-run with --apply, or after backfill)")

    # --- Step 5.5: family-drift report (F-300, DETECTION ONLY) ----------------
    # Surface pages that diverge from the deck's sibling house style (own page-bg,
    # bespoke title, pre-title chrome, off-ladder fonts, muted body text). This is
    # READ-ONLY here on purpose: stripping a page background is a visible design
    # change, not a mechanical defect repair, so the actual conform stays an
    # explicit opt-in (`conform-to-deck.py <deck> --apply`). conform-to-deck
    # self-skips when there are < 3 raw content pages (no family to conform to).
    if deck_will_exist:
        plan.append(("conform drift report (read-only — fix via conform-to-deck "
                     "--apply)", [sys.executable, str(CONFORM), str(deck_json)]))

    # --- Step 6: render + validate -------------------------------------------
    if not args.no_render and deck_will_exist and not dry:
        # Render only on --apply: a dry-run must not write index.html. (The
        # repaired deck.json is what render consumes — only valid post-apply.)
        render_cmd = [sys.executable, str(RENDER), str(deck_json),
                      str(output_dir) + "/"]
        if args.visual:
            render_cmd.append("--visual")
        plan.append(("render", render_cmd))
        plan.append(("validate --strict",
                     [sys.executable, str(VALIDATE), str(deck_json), "--strict"]))
    elif not args.no_render:
        reason = ("dry-run does not render" if dry
                  else "deck.json not available yet")
        print(f"  · render+validate SKIP — {reason}")

    if not plan:
        print("\n✓ nothing to do — no applicable repair steps for this deck.")
        return 0

    print(f"\nplan ({len(plan)} step{'s' if len(plan) != 1 else ''}):")
    for i, (name, _) in enumerate(plan, 1):
        print(f"  {i}. {name}")
    print()

    for i, (name, cmd) in enumerate(plan, 1):
        print(f"[{i}/{len(plan)}] {name}")
        _run(cmd, dry)
        print()

    if dry:
        print("✓ dry-run complete — NOTHING was changed. Re-run with --apply to "
              "execute this plan.")
    else:
        print("✓ repair-lifted: pipeline complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
