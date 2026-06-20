"""R-DECK-RADIUS-DRIFT — deck-wide corner-radius consistency (F-350, 2026-06-20).

taste-skill's "one corner-radius system". The "re-eyeballed the corner radius on
every box" fingerprint. Modeled on R-DECK-PALETTE-DRIFT (CSS-source scan): reads
AUTHOR CSS only (`iterStyleBlocks(false)` + inline `style=`, framework baseline
excluded), collects `border-radius` / `border-*-radius` px values, drops 0 (sharp)
and pills/circles (≥100px or any %), single-link clusters the remaining box radii
with a 2px tolerance, and warns when they fail to converge to ≤2 systems (≥3
distinct box-radius clusters = drift, e.g. 8/12/16). WARN · advisory · opt-out
`data-allow-radius`.

Static wiring lives in test_vis_deck_consistency.py; this file covers must-fire /
calibration behaviour through the headless engine.
"""
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve()
sys.path.insert(0, str(HERE.parent))
import engine_helpers as E  # noqa: E402

RULE = "R-DECK-RADIUS-DRIFT"


def _slide(css_and_body, attrs=""):
    return (f'<div class="slide" data-layout="content" data-slide-key="k" {attrs} '
            f'style="position:relative;width:1920px;height:1080px">{css_and_body}</div>')


def _run(html):
    E.skip_if_no_engine()
    return E.findings_for(RULE, html)


def test_wired():
    assert E.rule_in_engine(RULE)


def test_fires_on_near_duplicate_cluster():
    # 11 / 12 / 13 → one ≤3px cluster of 3 near-duplicates = "re-eyeballed the
    # radius" drift (parallel to R-DECK-PALETTE-DRIFT) → FIRE.
    css = ('<style>.a{border-radius:11px}.b{border-radius:12px}.c{border-radius:13px}</style>'
           '<div class="a">x</div><div class="b">y</div><div class="c">z</div>')
    hits = _run([_slide(css)])
    assert len(hits) >= 1, f"3 near-duplicate radii (11/12/13) not flagged as drift: {hits}"


def test_fires_on_dense_even_ladder():
    # 8 / 10 / 12 / 14 / 16 — a dense 2px ladder chains into one cluster of 5 → FIRE
    # (reads as a mush of slightly-different radii, not a deliberate tiered system).
    css = ('<style>.a{border-radius:8px}.b{border-radius:10px}.c{border-radius:12px}'
           '.d{border-radius:14px}.e{border-radius:16px}</style><div class="a">x</div>')
    hits = _run([_slide(css)])
    assert len(hits) >= 1, f"dense even radius ladder not flagged: {hits}"


def test_silent_on_deliberate_tiered_scale():
    # 8 / 16 / 24 — a clean 8px-step tier scale (chip/card/sheet). Each value is its
    # own singleton cluster (gaps 8 > 3px) → no ≥3 cluster → SILENT. A floor rule must
    # NOT punish an intentional tiered radius system (that is the model's design call).
    css = ('<style>.chip{border-radius:8px}.card{border-radius:16px}.sheet{border-radius:24px}</style>'
           '<div class="chip">a</div><div class="card">b</div><div class="sheet">c</div>')
    hits = _run([_slide(css)])
    assert hits == [], f"deliberate tiered radius scale (8/16/24) false-positived: {hits}"


def test_silent_on_rem_tiered_scale():
    # the same intentional ladder expressed in rem (0.5/0.75/1rem → 8/12/16) → SILENT.
    css = ('<style>.chip{border-radius:0.5rem}.card{border-radius:0.75rem}.sheet{border-radius:1rem}</style>'
           '<div class="chip">a</div>')
    hits = _run([_slide(css)])
    assert hits == [], f"rem-based tiered radius scale false-positived: {hits}"


def test_per_corner_longhand_is_seen():
    # per-corner longhand near-duplicates (border-top-left-radius 11/12/13) must be
    # extracted (regex allows multi-segment) and flagged as a near-dup cluster.
    css = ('<style>.a{border-top-left-radius:11px;border-top-right-radius:11px}'
           '.b{border-top-left-radius:12px;border-top-right-radius:12px}'
           '.c{border-top-left-radius:13px;border-top-right-radius:13px}</style>'
           '<div class="a">x</div><div class="b">y</div><div class="c">z</div>')
    hits = _run([_slide(css)])
    assert len(hits) >= 1, f"per-corner longhand near-dup radii not seen/flagged: {hits}"


def test_pills_and_circles_excluded():
    # 999px (pill) + 50% (circle) + one box radius → only 1 box radius → SILENT.
    css = ('<style>.a{border-radius:999px}.b{border-radius:50%}.c{border-radius:8px}</style>'
           '<div class="a">x</div>')
    hits = _run([_slide(css)])
    assert hits == [], f"pill/circle radii wrongly counted as box radii: {hits}"


def test_percent_token_does_not_drop_px_corners():
    # `border-radius:24px 24px 50% 50%` — the % tokens are skipped but the 24px corners
    # are still collected (regression guard for the old whole-declaration % skip).
    css = ('<style>.a{border-radius:23px}.b{border-radius:24px 24px 50% 50%}.c{border-radius:25px}</style>'
           '<div class="a">x</div><div class="b">y</div><div class="c">z</div>')
    hits = _run([_slide(css)])
    assert len(hits) >= 1, f"% shorthand masked the px corners (23/24/25 near-dup missed): {hits}"


def test_optout_silences():
    css = ('<style>.a{border-radius:11px}.b{border-radius:12px}.c{border-radius:13px}</style>'
           '<div class="a">x</div>')
    hits = _run([_slide(css, attrs="data-allow-radius")])
    assert hits == [], f"data-allow-radius should silence: {hits}"


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn(); print(f"  ok  {fn.__name__}")
        except Exception:
            failed += 1; print(f"FAIL  {fn.__name__}"); traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
