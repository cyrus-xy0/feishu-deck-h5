#!/usr/bin/env python3
"""bench-render.py — PERF-0 (AUDIT-2026-06-17) · the RULER for pipeline speed.

Segment-times the deck PRODUCTION pipeline so every PERF-* optimization can be
judged on real before/after numbers instead of guesses. AUDIT-2026-06-17 found
wall-clock is dominated by repeated Chromium cold-start + full-deck reload over
the SAME rendered index.html (a default 50p advisory render pays ~3 Chromium
passes), NOT by the audit logic — this tool makes that measurable and tracks it.

It measures, each `--runs` times (median / min / max reported):
  · chromium_coldstart          empty headless launch+close (the unit tax)
  · render_advisory             render-deck.py default (no --visual, no autosnap)
  · validate_static             validate.py --no-visual   (byte/source rules, 0 browser)
  · validate_visual_json        validate.py --visual --json (engine + font probe)
  · validate_visual_nocache     same, DECK_NO_FONT_PROBE_CACHE=1 (shows PERF-A delta)
  · check_distribution          check-distribution.py --json (6c geometry)
  · deck_cli_set                deck-cli.py set (a write op)

Nothing here changes a deck or a verdict — it only renders into a throwaway temp
dir and times read-only validators. stdlib-only.

Usage:
  python3 assets/bench-render.py <deck.json> [--runs N] [--out bench.json]
                                 [--compare baseline.json] [--keep]

  --compare prints a delta table (this run vs a saved baseline JSON) so you can
  show, e.g., "validate_visual_json 4217ms -> 3760ms after PERF-A".
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent                 # assets/
SKILL_ROOT = HERE.parent                               # skills/feishu-deck-h5/
RENDER_DECK = SKILL_ROOT / "deck-json" / "render-deck.py"
DECK_CLI = SKILL_ROOT / "deck-json" / "deck-cli.py"
VALIDATE = HERE / "validate.py"
CHECK_DIST = HERE / "check-distribution.py"

# Static annotation of how many headless Chromium launches each segment pays
# today (from AUDIT-2026-06-17 §2). The tool times wall-clock; these are context.
CHROMIUM_NOTE = {
    "chromium_coldstart": "1 (empty)",
    "render_advisory": "3 (engine + font-probe + distribution, same html)",
    "validate_static": "0 (byte/source only)",
    "validate_visual_json": "2 (engine + font-probe) — 1 once PERF-A cache is warm",
    "validate_visual_nocache": "2 (engine + font-probe, cache bypassed)",
    "check_distribution": "1",
    "deck_cli_set": "0 (schema-validate spawn only)",
}


def _time_cmd(cmd, env=None):
    """Run a subprocess, return (wall_ms, returncode). Output captured/discarded."""
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    t0 = time.perf_counter()
    p = subprocess.run(cmd, capture_output=True, text=True, env=full_env)
    return (time.perf_counter() - t0) * 1000.0, p.returncode


def _coldstart_once():
    """Time an empty headless Chromium launch+close in a fresh interpreter so the
    cost is comparable to what every gate subprocess pays."""
    snippet = (
        "import time;from playwright.sync_api import sync_playwright;"
        "t=time.perf_counter();"
        "p=sync_playwright().start();b=p.chromium.launch(headless=True);"
        "b.close();p.stop();print((time.perf_counter()-t)*1000)"
    )
    p = subprocess.run([sys.executable, "-c", snippet],
                       capture_output=True, text=True)
    try:
        return float(p.stdout.strip().splitlines()[-1]), p.returncode
    except (ValueError, IndexError):
        return float("nan"), p.returncode


def _stats(samples):
    vals = [s for s in samples if s == s]  # drop NaN
    if not vals:
        return None
    return {
        "median_ms": round(statistics.median(vals), 1),
        "min_ms": round(min(vals), 1),
        "max_ms": round(max(vals), 1),
        "runs": len(vals),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("deck", type=Path, help="deck.json to benchmark")
    ap.add_argument("--runs", type=int, default=3, help="timed runs per segment (default 3)")
    ap.add_argument("--out", type=Path, help="write results JSON here")
    ap.add_argument("--compare", type=Path, help="baseline JSON to diff against")
    ap.add_argument("--keep", action="store_true", help="keep the temp render dir")
    args = ap.parse_args()

    deck = args.deck.resolve()
    if not deck.is_file():
        print(f"bench-render: deck not found: {deck}", file=sys.stderr)
        return 2
    try:
        n_slides = len(json.loads(deck.read_text(encoding="utf-8")).get("slides", []))
    except (OSError, ValueError):
        n_slides = -1

    work = Path(tempfile.mkdtemp(prefix="bench-render-"))
    # No-autosnap belt-and-suspenders (the temp dir is not under runs/ either).
    render_env = {"DECK_LOG_NO_AUTOSNAP": "1"}
    print(f"bench-render · {deck.name} · {n_slides} slides · {args.runs} runs/segment")
    print(f"  workdir: {work}")

    segments = {}

    # 1) Chromium cold-start unit tax.
    print("  · chromium_coldstart ...", flush=True)
    segments["chromium_coldstart"] = _stats(
        [_coldstart_once()[0] for _ in range(args.runs)])

    # 2) render_advisory — fresh output dir each run so it's a full (not
    #    incremental) render every time. The dir MUST be a canonical
    #    runs/<slug>/output/ layout, otherwise _is_runs_output() is false and
    #    render-deck.py skips the 6b/6c browser gates (you'd time a 0-Chromium
    #    fast path, ~0.5s, not the real ~6s production render). autosnap is
    #    disabled via DECK_LOG_NO_AUTOSNAP so this measures the advisory gate
    #    path (3 Chromium), not the +snapshot path (5).
    print("  · render_advisory ...", flush=True)
    samples, rc_ok = [], True
    first_out = None
    for i in range(args.runs):
        out = work / "runs" / f"bench-{i}" / "output"
        out.mkdir(parents=True, exist_ok=True)
        ms, rc = _time_cmd([sys.executable, str(RENDER_DECK), str(deck), str(out)],
                           env=render_env)
        samples.append(ms)
        rc_ok = rc_ok and rc in (0, 4)  # 4 = gate found defects (deck-specific, fine)
        if first_out is None:
            first_out = out
    seg = _stats(samples)
    if seg:
        seg["rc_ok"] = rc_ok
    segments["render_advisory"] = seg

    index_html = (first_out / "index.html") if first_out else None
    have_html = bool(index_html and index_html.is_file())
    if not have_html:
        print("  ! render produced no index.html — validator segments skipped",
              file=sys.stderr)

    def _bench_cmd(name, cmd, env=None, ok_rc=(0, 1, 4)):
        print(f"  · {name} ...", flush=True)
        samples, all_ok = [], True
        for _ in range(args.runs):
            ms, rc = _time_cmd(cmd, env=env)
            samples.append(ms)
            all_ok = all_ok and rc in ok_rc
        s = _stats(samples)
        if s:
            s["rc_ok"] = all_ok
        segments[name] = s

    if have_html:
        h = str(index_html)
        _bench_cmd("validate_static", [sys.executable, str(VALIDATE), h, "--no-visual"])
        _bench_cmd("validate_visual_json",
                   [sys.executable, str(VALIDATE), h, "--visual", "--json"])
        _bench_cmd("validate_visual_nocache",
                   [sys.executable, str(VALIDATE), h, "--visual", "--json"],
                   env={"DECK_NO_FONT_PROBE_CACHE": "1"})
        _bench_cmd("check_distribution",
                   [sys.executable, str(CHECK_DIST), h, "--json"])

    # 7) deck_cli_set — write op on a throwaway copy (never touch the real deck).
    deck_copy = work / "deck-copy.json"
    shutil.copy2(deck, deck_copy)
    _bench_cmd("deck_cli_set",
               [sys.executable, str(DECK_CLI), "--force", str(deck_copy),
                "set", "deck.title", "bench-title"],
               ok_rc=(0,))

    result = {
        "tool": "bench-render PERF-0",
        "deck": str(deck),
        "slides": n_slides,
        "runs": args.runs,
        "platform": sys.platform,
        "segments": segments,
        "chromium_launches_today": {k: CHROMIUM_NOTE.get(k, "?") for k in segments},
    }

    # Pretty table.
    print("\n  segment                     median    min     max   chromium")
    print("  " + "-" * 64)
    for name, s in segments.items():
        if not s:
            print(f"  {name:<26}  (skipped)")
            continue
        flag = "" if s.get("rc_ok", True) else "  ⚠rc"
        print(f"  {name:<26} {s['median_ms']:>7.0f} {s['min_ms']:>6.0f} "
              f"{s['max_ms']:>6.0f}   {CHROMIUM_NOTE.get(name,'')}{flag}")

    if args.out:
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        print(f"\n  → wrote {args.out}")

    if args.compare and args.compare.is_file():
        base = json.loads(args.compare.read_text(encoding="utf-8"))
        bseg = base.get("segments", {})
        print(f"\n  Δ vs {args.compare.name} (baseline → now):")
        for name, s in segments.items():
            if not s or name not in bseg or not bseg[name]:
                continue
            b = bseg[name]["median_ms"]
            now = s["median_ms"]
            d = now - b
            pct = (d / b * 100) if b else 0.0
            arrow = "▼" if d < 0 else ("▲" if d > 0 else "=")
            print(f"    {name:<26} {b:>7.0f} → {now:>7.0f}  {arrow}{abs(d):>6.0f}ms ({pct:+.0f}%)")

    if not args.keep:
        shutil.rmtree(work, ignore_errors=True)
    else:
        print(f"\n  (kept {work})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
