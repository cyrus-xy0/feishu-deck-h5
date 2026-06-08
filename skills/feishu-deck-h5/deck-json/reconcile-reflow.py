#!/usr/bin/env python3
"""reconcile-reflow.py — F-54 「reconcile → reflow」闭环工具。

WHAT IT DOES (the one-paragraph version)
----------------------------------------
F-42's `reconcile-lifted.py` snaps a lifted slide's improvised font sizes onto
the 4-tier ladder {16,24,28,48}. Because ties go to the LARGER tier (it never
shrinks toward the floor), the snap can make a few px of text BIGGER — and when
that extra height lands inside a flex/overflow-pinned container, the content
spills past its box (R-VIS-CARD-OVERFLOW) even though the slide still fits the
1920×1080 canvas. R20 (type-ladder) goes green, but a NEW geometry defect was
silently introduced. That is the exact gap F-54 closes.

This tool runs the full loop:

    ① reconcile (font snap, channel 1)        ← reconcile-lifted.py, idempotent
              ↓ deck.json
    ② render-deck.py → index.html
              ↓
    ③ headless geometry probe                  ← validate.run_visual_audits
              ↓  (card-overflow / overlap / canvas-overflow findings)
    ④ reflow-boxes (channel 2)                 ← THIS FILE's contribution:
         for each NEWLY-overflowing box, measure grow vs canvas room
         (the grow-box-fit formula). GROW-OK → write ONE scoped
         `slide.custom_css` rule that unpins the box so it uses the canvas
         room it already has (flex:0 0 auto / overflow:visible / min-height:0,
         each `!important` so it wins the source-order tie against the
         slide's own equal-specificity rule). NO-ROOM → mark for human, never
         auto-delete content.
              ↓ deck.json (+ .bak)
    ⑤ re-render → re-probe
              ↓
    ⑥ per-slide multiset geometry GATE         ← zero-new-error or revert

Loop terminates on: (a) zero new geometry errors vs the pre-reconcile baseline,
(b) iteration cap (default 3), or (c) score did NOT strictly decrease this round
(anti-oscillation: revert this round's .bak and stop).

WHY custom_css AND WHY !important (both learned by experiment, F-54 design)
--------------------------------------------------------------------------
* deck.json is the source of truth (memory [[project-feishu-deck-lift]] L2). The
  fix is written to `slide.custom_css`; render-deck.py co-locates it as a
  slide-key-scoped `<style>` that round-trips back to deck.json. We never
  post-render-edit index.html (R-SELF-CONTAINED; the "page-anim vanishes on
  republish" trap).
* render-deck.py injects the custom_css `<style>` as the FIRST child of `.slide`.
  But a lifted slide's OWN `<style>` (its `.timeline{flex:1;overflow:hidden}`
  rule) is ALSO scoped to `.slide[data-slide-key=K] .timeline` — IDENTICAL
  specificity — and renders LATER, so it wins the cascade tie and our unpin is
  silently overridden. Verified on the zhongan deck: without `!important` the
  fix renders but `getComputedStyle` still reports `flex:1 1 0%`. Bumping the
  unpin declarations to `!important` makes them win regardless of source order.
  (`min-height` happened to win without it because nothing else set it, but we
  mark all three for consistency.)

WHAT IT WILL / WON'T DO (honesty contract)
------------------------------------------
* It ONLY treats hard geometry errors: R-VIS-CARD-OVERFLOW (err),
  R-OVERLAP (err), R-OVERFLOW (err, >60px clipped). These are the rules whose
  NEW appearance after reconcile = real damage.
* GROW-OK pinned-flex boxes (the dominant reconcile casualty) → auto-fixed.
* NO-ROOM boxes (grow > canvas room) → reported as a "needs human" list with
  page / box / px-deficit; NEVER auto-shrunk and NEVER auto-deleted (a
  destructive op; memory feedback「破坏性操作要二次确认」).
* Orphans (R-VIS-ORPHAN), tier-warn, body-floor-warn are SOFT side-effects:
  reported but NOT a gate. (They are warns, not content loss, and the right fix
  is text-wrap/nowrap which is a separate, lighter channel.)
* It is idempotent: a second run finds the boxes already unpinned (the
  custom_css rule already present) and writes nothing — byte-identical no-op.

USAGE
-----
    python3 reconcile-reflow.py <deck.json> [options]

      --max-rounds N      reflow iteration cap (default 3)
      --output-dir DIR    where to render (default: a temp dir; reused per round)
      --skip-reconcile    deck.json is ALREADY reconciled; only run the reflow
                          loop (channel 2). Baseline is then captured from the
                          deck AS GIVEN (so the gate has nothing to diff against
                          on the font side — see notes).
      --dry-run           run the whole loop, print the plan + would-be
                          custom_css, but write NOTHING to deck.json.
      --force             bypass the F-53 optimistic lock on write.
      --keep-renders      don't delete the temp render dir on exit.

EXIT CODES
    0  loop converged: final geometry errors ≤ pre-reconcile baseline (zero new).
    1  loop stopped with residual NEW geometry errors (NO-ROOM pages, or
       anti-oscillation revert). Report lists exactly what needs a human.
    2  usage / IO error.
    3  optimistic-lock refusal (deck.json changed on disk; re-run or --force).

DEPENDS ON (all in this skill, single source of truth — F-02)
    deck-json/reconcile-lifted.py   (channel 1; imported, not re-implemented)
    deck-json/render-deck.py        (deck.json → index.html)
    assets/validate.py              (run_visual_audits → geometry findings)
    grow-box-fit.py's room formula  (re-derived here against the OVERFLOW box,
                                     not the sub-floor text box — see Q2)

stdlib + playwright (via validate). Python 3.10+.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent          # …/deck-json
_SKILL = _HERE.parent                            # …/feishu-deck-h5
_ASSETS = _SKILL / "assets"

# Import the validator (single source for the geometry findings + the in-browser
# audit JS). It lives in assets/.
if str(_ASSETS) not in sys.path:
    sys.path.insert(0, str(_ASSETS))

# Import channel 1 (font snap) so we don't re-implement it.
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

# ---------------------------------------------------------------------------
# The three HARD geometry rules F-54 gates on. NEW appearance of any of these
# (per slide, multiset) after reconcile = damage we must heal or revert.
# ---------------------------------------------------------------------------
HARD_RULES = ("R-VIS-CARD-OVERFLOW", "R-OVERLAP", "R-OVERFLOW")
OVERFLOW_ERR_PX = 60          # R-OVERFLOW only counts as err above this (validate.py:249)


# ===========================================================================
# Geometry probe — one headless pass; returns raw card_overflow/overlap records
# AND the bucketed per-slide multiset used by the gate.
# ===========================================================================

def _probe(index_html: Path) -> dict:
    """Headless geometry probe. Returns:
        {
          'records': {'card_overflow':[...], 'overlap':[...], 'overflow':[...]},
          'errset':  Counter({(rule, slide_idx): n})   # HARD err-level only
        }
    Uses validate's exact audit JS + present-mode setup so the numbers match
    what check-only --visual reports."""
    # UNIFY-VALIDATE-ARCH step 4b: source geometry from the SINGLE unified engine
    # (audits.js via run-audits.py's run_unified_engine) instead of the retired
    # V._visual_audit_js() bucket report. The engine returns flat findings whose
    # payload carries the SAME fields (slide_idx/selector/overflow_px/direction/
    # recoverable for card-overflow; idx/deltaH/deltaW for overflow), so we just regroup
    # them back into the bucket shape this reflow stage consumes. The numbers
    # match check-only --visual because both call the same engine.
    import importlib.util
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("reconcile-reflow: playwright not installed — cannot probe geometry. "
              "`pip install playwright && python -m playwright install chromium`",
              file=sys.stderr)
        raise SystemExit(2)

    _ra_spec = importlib.util.spec_from_file_location(
        "run_audits_reflow", Path(__file__).resolve().parents[0].parent
        / "assets" / "run-audits.py")
    _RA = importlib.util.module_from_spec(_ra_spec)
    _ra_spec.loader.exec_module(_RA)
    try:
        result = _RA.run_unified_engine(index_html, None, dom_rules=True)
    except _RA.EngineUnavailable as e:
        print(f"reconcile-reflow: unified engine could not run ({e}). "
              "`pip install playwright && python -m playwright install chromium`",
              file=sys.stderr)
        raise SystemExit(2)

    findings = result.get("findings", [])
    records = {
        "card_overflow": [f for f in findings if f["rule"] == "R-VIS-CARD-OVERFLOW"],
        "overlap":       [f for f in findings if f["rule"] == "R-OVERLAP"],
        "overflow":      [f for f in findings if f["rule"] == "R-OVERFLOW"],
    }

    # Per-slide canvas room for every card_overflow box, in ONE extra browser
    # pass (kept separate from the engine eval), so the reflow stage can judge
    # GROW-OK without re-deriving geometry.
    url = index_html.resolve().as_uri()
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        page = b.new_context(viewport={"width": 1920, "height": 1080}).new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        # Bounded settle (B/2026-06-06): an embedded live demo can keep the 'load'
        # event pending ~30s. Prefer full load for fidelity but cap it, then await
        # fonts. Geometry probe needs layout settled — same as the screenshot path.
        try:
            page.wait_for_load_state("load", timeout=4_000)
        except Exception:
            pass
        try:
            page.evaluate("() => Promise.race([(document.fonts && document.fonts.ready) || Promise.resolve(), new Promise(r => setTimeout(r, 2000))])")
        except Exception:
            pass
        # Wait for framework init (feishu-deck.js sets data-js-ready on .deck).
        # domcontentloaded can return before layout JS runs → un-laid-out geometry.
        try:
            page.wait_for_function("() => document.querySelector('.deck[data-js-ready]')", timeout=5_000)
        except Exception:
            pass
        page.evaluate("""() => {
            const d = document.querySelector('.deck');
            if (d) d.setAttribute('data-mode', 'present');
        }""")
        page.wait_for_timeout(200)
        room = page.evaluate(_ROOM_JS, records["card_overflow"])
        b.close()
    # attach measured room back onto each card_overflow record by (slide,selector)
    room_by_key = {(r["slide_idx"], r["selector"]): r for r in room}
    for rec in records["card_overflow"]:
        k = (rec["slide_idx"], rec["selector"])
        if k in room_by_key:
            rec.update(room_by_key[k])

    errset: Counter = Counter()
    for rec in records["card_overflow"]:
        # mirror validate.py severity: card-overflow is err when overflow_px>16
        # (or non-recoverable clip at any px). We treat the non-recoverable clip
        # and any >16 spill as err — the harmful tier.
        px = rec.get("overflow_px", 0)
        # Mirror validate.py exactly: only a NON-RECOVERABLE CLIPPED overflow
        # (the 'else' branch — neither horizontal nor vertical-VISIBLE) is err at
        # ANY px; horizontal / vertical-visible / recoverable are err only when
        # overflow_px > 16. (The old `direction.startswith("vertical") and not
        # recoverable` wrongly err'd a small vertical-VISIBLE spill that
        # validate.py would only warn.)
        clipped_nonrec = (rec.get("direction", "") not in ("horizontal", "vertical-visible")
                          and rec.get("recoverable") is False)
        if px > 16 or clipped_nonrec:
            errset[("R-VIS-CARD-OVERFLOW", rec["slide_idx"])] += 1
    for rec in records["overlap"]:
        errset[("R-OVERLAP", rec["slide_idx"])] += 1
    for rec in records["overflow"]:
        # The unified engine's R-OVERFLOW finding carries deltaH/deltaW (already
        # the overflow delta vs 1080/1920 — NOT raw h/w), so consume those
        # directly. Reading rec['h']/['w'] (the retired bucket-report fields)
        # always defaulted to 0 → ov stayed negative → R-OVERFLOW was NEVER
        # added to errset, blinding the reflow regression gate to overflow it
        # introduces (H6).
        ov = max(rec.get("deltaH", 0), rec.get("deltaW", 0))
        if ov > OVERFLOW_ERR_PX:
            errset[("R-OVERFLOW", rec["idx"])] += 1
    return {"records": records, "errset": errset}


# In-browser: measure grow + canvas room for each card_overflow box. Mirrors the
# grow-box-fit余量公式 (grow-box-fit.py:130-141) but the TARGET is the overflow
# box itself, not a sub-floor text leaf. room = innerSlack(框内下方富余) +
# canvasBelow(框底到画布底). Also reports whether the box is "pinned" (flex grow
# or fixed height + overflow hidden/clip) so the reflow stage knows the fix kind.
_ROOM_JS = r"""
(targets) => {
  const deck = document.querySelector('.deck');
  if (deck) deck.setAttribute('data-mode', 'present');
  const slides = [...document.querySelectorAll('.slide')];
  const shortSel = el => {
    const tag = el.tagName.toLowerCase();
    const raw = el.className;
    const clsStr = (raw && raw.baseVal !== undefined ? raw.baseVal : (raw || '')).toString();
    const cls = clsStr.split(/\s+/).filter(Boolean);
    return cls.length ? `${tag}.${cls.join('.')}` : tag;
  };
  const hasOwnText = el => {
    for (const n of el.childNodes) if (n.nodeType === 3 && n.textContent.trim()) return true;
    return false;
  };
  const contentBottom = root => {
    let b = -Infinity, any = false;
    for (const el of root.querySelectorAll('*')) {
      if (!hasOwnText(el)) continue;
      const r = el.getBoundingClientRect();
      if (r.height < 1) continue;
      b = Math.max(b, r.bottom); any = true;
    }
    return any ? b : null;
  };
  const out = [];
  for (const t of targets) {
    const slide = slides[t.slide_idx - 1];
    if (!slide) continue;
    const scale = parseFloat(getComputedStyle(slide).getPropertyValue('--fs-scale')) || 1;
    const sr = slide.getBoundingClientRect();
    // find the element matching this card_overflow record by selector + size
    let el = null;
    for (const cand of slide.querySelectorAll('*')) {
      if (shortSel(cand) !== t.selector) continue;
      el = cand; break;
    }
    if (!el) continue;
    const cs = getComputedStyle(el);
    const br = el.getBoundingClientRect();
    const grow = Math.max(0, el.scrollHeight - el.clientHeight);
    const cb = contentBottom(el);
    const innerSlack = cb ? Math.max(0, (br.bottom - cb) / scale) : 0;
    const canvasBelow = Math.max(0, (sr.bottom - br.bottom) / scale);
    const room = Math.round(innerSlack + canvasBelow);
    // pinned? flex-grow>0 (won't grow with content) OR explicit fixed height,
    // combined with clipped overflow. flex shorthand parses to flexGrow.
    const fg = parseFloat(cs.flexGrow) || 0;
    const clipped = (cs.overflowY === 'hidden' || cs.overflowY === 'clip');
    const fixedH = cs.height && cs.height !== 'auto' && fg === 0
                   && (cs.flexBasis === '0%' || cs.flexBasis === 'auto');
    const pinned = (fg > 0 || fixedH);
    out.push({
      slide_idx: t.slide_idx, selector: t.selector,
      grow, room, innerSlack: Math.round(innerSlack),
      canvasBelow: Math.round(canvasBelow),
      flex: cs.flex, overflowY: cs.overflowY, flexGrow: fg,
      pinned, clipped,
    });
  }
  return out;
}
"""


# ===========================================================================
# render
# ===========================================================================

def _render(deck_json: Path, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(_HERE / "render-deck.py"),
           str(deck_json), str(out_dir) + "/", "--skip-validate-html"]
    # C3: this render runs once PER reflow iteration into a throwaway temp dir;
    # suppress render-deck's post-render auto-snapshot so mid-reflow intermediate
    # state is never written into the deck's making-of log.
    env = dict(os.environ, DECK_LOG_NO_AUTOSNAP="1")
    res = subprocess.run(cmd, capture_output=True, text=True, env=env)
    index = out_dir / "index.html"
    if res.returncode != 0 or not index.is_file():
        sys.stderr.write(res.stdout + "\n" + res.stderr + "\n")
        raise SystemExit(f"reconcile-reflow: render failed for {deck_json}")
    return index


# ===========================================================================
# reflow planning — turn a card_overflow record into a custom_css fix or a
# NO-ROOM mark. The judgment is grow-box-fit's room formula, applied to the
# OVERFLOW box (not a sub-floor text leaf).
# ===========================================================================

def _leaf_selector(short_sel: str) -> str:
    """`div.timeline` → `.timeline` (a class-only leaf selector that
    scope_selectors will scope to the slide-key). If the box has NO class
    (bare tag like `div`), fall back to the tag — risky (could hit siblings)
    so we flag it for the caller to treat as NO-ROOM-style manual."""
    m = re.match(r'[a-zA-Z][\w-]*((?:\.[\w-]+)+)$', short_sel)
    if m:
        return m.group(1)          # ".timeline" / ".card.kpi"
    # tag-only (no class) → can't safely scope to one box
    return ""


def plan_reflow(card_overflow_records: list[dict], new_errset: Counter,
                slides_by_idx: dict) -> tuple[list[dict], list[dict]]:
    """Returns (fixes, no_room). Each fix = {slide_idx, key, leaf_sel, css,
    grow, room}. Only acts on boxes that contribute a NEW hard err (i.e. their
    (rule,slide) is in `new_errset`)."""
    fixes, no_room = [], []
    new_card_slides = {sl for (rule, sl) in new_errset if rule == "R-VIS-CARD-OVERFLOW"}
    seen = set()
    for rec in card_overflow_records:
        sl = rec["slide_idx"]
        if sl not in new_card_slides:
            continue                              # baseline / not newly broken
        slide = slides_by_idx.get(sl)
        if slide is None:
            continue
        key = slide.get("key") or ""
        leaf = _leaf_selector(rec.get("selector", ""))
        dirn = rec.get("direction", "")
        grow = rec.get("grow", rec.get("overflow_px", 0))
        room = rec.get("room", 0)
        dedup = (sl, leaf)
        if dedup in seen:
            continue
        seen.add(dedup)

        # Horizontal overflow (flex-row children too wide) and bare-tag boxes
        # are not in-scope for the unpin fix — they need content edits → human.
        if dirn == "horizontal" or not leaf:
            no_room.append({**_norm(rec, key),
                            "reason": ("horizontal flex overflow — needs content "
                                       "edit / flex-wrap (not a grow fix)"
                                       if dirn == "horizontal"
                                       else "box has no class to scope a fix to")})
            continue

        # GROW-OK if the canvas + inner slack can absorb the spill.
        if grow <= room and room > 0:
            # Unpin the box so it uses the canvas room it already has. !important
            # so it wins the equal-specificity source-order tie against the
            # slide's own `.timeline{flex:1;overflow:hidden}` rule (verified).
            css = (f"{leaf}{{flex:0 0 auto !important;"
                   f"overflow:visible !important;min-height:0 !important}}")
            fixes.append({"slide_idx": sl, "key": key, "leaf_sel": leaf,
                          "css": css, "grow": grow, "room": room,
                          "preview": rec.get("selector", "")})
        else:
            no_room.append({**_norm(rec, key),
                            "reason": (f"grow {grow}px > canvas room {room}px — "
                                       "no space to grow; needs content压缩 (人工)")})
    return fixes, no_room


def _norm(rec: dict, key: str) -> dict:
    return {"slide_idx": rec["slide_idx"], "key": key,
            "selector": rec.get("selector", ""),
            "grow": rec.get("grow", rec.get("overflow_px", 0)),
            "room": rec.get("room", 0),
            "overflow_px": rec.get("overflow_px", 0)}


def apply_fixes(deck: dict, fixes: list[dict]) -> int:
    """Append each fix's css to the target slide's custom_css. Idempotent: if the
    exact rule is already present, skip. Returns number of slides changed."""
    slides_by_key = {s.get("key"): s for s in deck.get("slides", [])}
    changed = 0
    for fix in fixes:
        slide = slides_by_key.get(fix["key"])
        if slide is None:
            continue
        existing = slide.get("custom_css") or ""
        # idempotence: same leaf-sel unpin rule already there → no-op
        marker = f"/* f54-reflow:{fix['leaf_sel']} */"
        if marker in existing:
            continue
        block = (f"{marker}\n{fix['css']}")
        slide["custom_css"] = (existing.rstrip() + "\n" + block).lstrip("\n") \
            if existing.strip() else block
        changed += 1
    return changed


# ===========================================================================
# diff / gate
# ===========================================================================

def new_errors(baseline: Counter, current: Counter) -> Counter:
    """Per-(rule,slide) multiset difference current ⊖ baseline. Anything in
    current beyond what baseline already had = a NEW geometry error."""
    out: Counter = Counter()
    for key, n in current.items():
        extra = n - baseline.get(key, 0)
        if extra > 0:
            out[key] = extra
    return out


def score(errset: Counter) -> int:
    """Total hard geometry errors (for the monotonic-decrease guard)."""
    return sum(errset.values())


def _fmt_errset(es: Counter) -> str:
    if not es:
        return "(none)"
    by_rule: dict[str, list[int]] = {}
    for (rule, sl), n in es.items():
        by_rule.setdefault(rule, []).extend([sl] * n)
    return "; ".join(f"{r} {sorted(v)}" for r, v in sorted(by_rule.items()))


# ===========================================================================
# driver
# ===========================================================================

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("deck_json", type=Path)
    ap.add_argument("--max-rounds", type=int, default=3)
    ap.add_argument("--output-dir", type=Path, default=None)
    ap.add_argument("--skip-reconcile", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--keep-renders", action="store_true")
    args = ap.parse_args(argv)

    if not args.deck_json.exists():
        print(f"reconcile-reflow: {args.deck_json} not found", file=sys.stderr)
        return 2

    expected_mtime = args.deck_json.stat().st_mtime
    deck = json.loads(args.deck_json.read_text(encoding="utf-8"))
    slides = deck.get("slides", [])
    slides_by_idx = {i + 1: s for i, s in enumerate(slides)}

    work = Path(args.output_dir) if args.output_dir else \
        Path(tempfile.mkdtemp(prefix="f54-reflow-"))
    work.mkdir(parents=True, exist_ok=True)

    log: list[str] = []

    def say(s=""):
        print(s)
        log.append(s)

    say(f"reconcile-reflow · {args.deck_json.name} · {len(slides)} slides")
    say(f"  work dir: {work}")

    # --- BASELINE: render + probe the deck AS GIVEN (pre-reconcile) -----------
    say("\n[0] baseline (pre-reconcile) render + geometry probe …")
    base_index = _render(args.deck_json, work / "round0-baseline")
    baseline = _probe(base_index)["errset"]
    say(f"    baseline hard geometry errors: {_fmt_errset(baseline)}  "
        f"(score={score(baseline)})")

    # --- CHANNEL 1: reconcile (font snap) ------------------------------------
    # Work on an in-memory copy that we keep mutating; we write the deck.json
    # ONCE at the end (single optimistic-locked write).
    if not args.skip_reconcile:
        # reconcile-lifted.py has a hyphen → import via importlib helper.
        say("\n[1] channel 1 · reconcile fonts (snap to 4-tier ladder) …")
        RL = _import_reconcile()
        n_snap = _reconcile_in_place(deck, RL)
        say(f"    snapped {n_snap} font declaration(s) across lifted slides "
            f"(idempotent).")
    else:
        say("\n[1] --skip-reconcile: deck assumed already font-snapped.")

    # Render + probe the reconciled deck → this is what the reflow loop heals.
    say("\n[2] render reconciled deck + probe …")
    cur_index = _write_temp_and_render(deck, work / "round1-reconciled")
    cur = _probe(cur_index)
    cur_err = cur["errset"]
    say(f"    post-reconcile hard geometry errors: {_fmt_errset(cur_err)}  "
        f"(score={score(cur_err)})")
    delta = new_errors(baseline, cur_err)
    say(f"    NEW vs baseline (the damage reconcile introduced): "
        f"{_fmt_errset(delta)}")

    # --- CHANNEL 2: reflow loop ----------------------------------------------
    rounds_run = 0
    no_room_final: list[dict] = []
    round_history = [("baseline", baseline), ("post-reconcile", cur_err)]
    prev_score = score(cur_err)

    if not delta:
        say("\n[3] no NEW geometry errors after reconcile — nothing to reflow. "
            "Loop already converged.")
    else:
        for rnd in range(1, args.max_rounds + 1):
            rounds_run = rnd
            say(f"\n[3.{rnd}] reflow round {rnd} …")
            delta = new_errors(baseline, cur_err)
            if not delta:
                say(f"    ✓ zero new errors — converged at round {rnd-1}.")
                break
            fixes, no_room = plan_reflow(cur["records"]["card_overflow"],
                                         delta, slides_by_idx)
            no_room_final = no_room
            if not fixes:
                say("    no auto-fixable (GROW-OK) boxes this round — "
                    "remaining damage is NO-ROOM / out-of-scope (see report).")
                break
            for f in fixes:
                say(f"      [GROW-OK] slide {f['slide_idx']} "
                    f"({f['key']}) · {f['preview']} · grow {f['grow']}px ≤ "
                    f"room {f['room']}px → custom_css `{f['css']}`")

            # snapshot for possible revert (anti-oscillation)
            snapshot = json.dumps(deck, ensure_ascii=False)

            n_changed = apply_fixes(deck, fixes)
            if n_changed == 0:
                say("    all planned fixes already present (idempotent) — stop.")
                break

            cur_index = _write_temp_and_render(
                deck, work / f"round{rnd+1}-reflow")
            cur = _probe(cur_index)
            cur_err = cur["errset"]
            new_score = score(cur_err)
            round_history.append((f"reflow-r{rnd}", cur_err))
            say(f"    after round {rnd}: {_fmt_errset(cur_err)}  "
                f"(score={new_score}, prev={prev_score})")

            if new_score >= prev_score:
                # not strictly decreasing → revert this round and stop (the loop
                # is oscillating: a fix on A broke B). Q3 anti-oscillation guard.
                say(f"    ✗ score did NOT decrease ({new_score} ≥ {prev_score}) "
                    "— oscillation. Reverting this round's reflow and stopping.")
                deck = json.loads(snapshot)
                slides_by_idx = {i + 1: s for i, s in enumerate(deck["slides"])}
                cur_index = _write_temp_and_render(
                    deck, work / f"round{rnd+1}-reverted")
                cur = _probe(cur_index)
                cur_err = cur["errset"]
                break
            prev_score = new_score
        else:
            say(f"\n    reached max-rounds={args.max_rounds}; stopping.")

    # --- FINAL gate ----------------------------------------------------------
    final_err = cur_err
    final_delta = new_errors(baseline, final_err)
    say("\n" + "=" * 60)
    say("FINAL geometry gate (zero-new = pass)")
    say(f"  baseline (pre-reconcile): {_fmt_errset(baseline)}  "
        f"(score={score(baseline)})")
    say(f"  final (post-loop):        {_fmt_errset(final_err)}  "
        f"(score={score(final_err)})")
    say(f"  NEW geometry errors vs baseline: {_fmt_errset(final_delta)}")
    if no_room_final:
        say("\n  NO-ROOM / out-of-scope (NEEDS A HUMAN — never auto-edited):")
        for nr in no_room_final:
            say(f"    · slide {nr['slide_idx']} ({nr['key']}) · "
                f"`{nr['selector']}` · {nr.get('reason','')}")

    gate_pass = (score(final_delta) == 0)
    say("\n  GATE: " + ("✓ PASS — final geometry errors ≤ pre-reconcile "
                        "baseline (zero new)."
                        if gate_pass else
                        "✗ FAIL — residual NEW geometry errors remain "
                        "(see NO-ROOM list; needs human)."))

    # --- WRITE deck.json (once, optimistic-locked, with .bak) ----------------
    if args.dry_run:
        say("\n  (--dry-run; deck.json NOT modified. Planned custom_css shown "
            "above.)")
        _cleanup(work, args.keep_renders)
        return 0 if gate_pass else 1

    if not args.force:
        if abs(args.deck_json.stat().st_mtime - expected_mtime) > 1e-6:
            print("\n  ✗ REFUSING write — deck.json changed on disk since read "
                  "(concurrent edit). Re-run, or pass --force.", file=sys.stderr)
            _cleanup(work, args.keep_renders)
            return 3

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    bak = args.deck_json.with_suffix(f".json.bak-pre-reflow-{ts}")
    shutil.copy2(args.deck_json, bak)
    args.deck_json.write_text(
        json.dumps(deck, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    say(f"\n  ✓ backup: {bak.name}")
    say(f"  ✓ wrote {args.deck_json}")
    say(f"  rounds run: {rounds_run}")

    _cleanup(work, args.keep_renders)
    return 0 if gate_pass else 1


# ---------------------------------------------------------------------------
# helpers that need importlib (reconcile-lifted.py has a hyphen) + temp render
# ---------------------------------------------------------------------------

def _import_reconcile():
    """Import channel-1 (reconcile-lifted.py) by path — the hyphen forbids a
    plain `import`. Prefer the sibling next to THIS file; fall back to the
    canonical skill tree (~/.claude/skills/feishu-deck-h5/deck-json/) so the tool
    runs from a partial git worktree where reconcile-lifted.py may not be checked
    out (it currently lives only in the main working tree)."""
    import importlib.util
    candidates = [
        _HERE / "reconcile-lifted.py",
        Path.home() / ".claude/skills/feishu-deck-h5/deck-json/reconcile-lifted.py",
    ]
    src = next((c for c in candidates if c.is_file()), None)
    if src is None:
        raise SystemExit(
            "reconcile-reflow: cannot find reconcile-lifted.py (channel 1). "
            f"Looked in: {', '.join(str(c) for c in candidates)}. "
            "Run from the skill tree, or use --skip-reconcile if the deck is "
            "already font-snapped.")
    spec = importlib.util.spec_from_file_location("reconcile_lifted", src)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _reconcile_in_place(deck: dict, RL) -> int:
    """Run channel-1 font snap on the in-memory deck (mutates slide data.html)."""
    total = 0
    for slide in deck.get("slides", []):
        if not (slide.get("layout") == "raw" and slide.get("lifted")):
            continue
        data = slide.get("data")
        if not (isinstance(data, dict) and isinstance(data.get("html"), str)):
            continue
        new_html, n, _ = RL.reconcile_html(data["html"])
        if n:
            data["html"] = new_html
            total += n
    return total


def _write_temp_and_render(deck: dict, out_dir: Path) -> Path:
    """Serialize the in-memory deck to a temp json next to out_dir and render."""
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp_json = out_dir / "_deck.json"
    tmp_json.write_text(json.dumps(deck, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    return _render(tmp_json, out_dir)


def _cleanup(work: Path, keep: bool):
    if keep:
        print(f"  (renders kept in {work})")
        return
    try:
        shutil.rmtree(work)
    except Exception:
        pass


if __name__ == "__main__":
    sys.exit(main())
