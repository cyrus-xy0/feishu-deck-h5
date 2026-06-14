"""R-VIS-RAW-TITLE-POS · custom-class raw title blind spot (F-271, 2026-06-10).

The 2026-06-04 raw-title twin (R-VIS-RAW-TITLE-POS) bailed the moment a raw slide
had ANY rendered `.header`, deferring to R-VIS-TITLE-POSITION. But TITLE-POSITION
only resolves a *framework* title (`.header > .title-zh` / `h1.title-zh` /
`h2.title-zh`); when a raw page wraps a **custom** title class (`.r-title`,
`.r-head`, …) inside its `.header`, TITLE-POSITION's `titleEl` is null → it
silently passes, AND RAW-TITLE-POS early-returned because the `.header` is present
→ BOTH rules miss. (Empirically, nut-assoc's 9 pages with header tops 44/48/61
all went unreported.)

The fix narrows RAW-TITLE-POS's defer condition: it only yields to TITLE-POSITION
when the `.header` actually contains a framework `.title-zh`; a `.header` with a
custom (or no) title falls through to the name-free de-facto title scan.

Severity stays **warn** (never error): F-256 promoted error-level R-VIS findings
to a hard render BLOCK, so flagging raw title drift as error would block the many
existing raw decks that already drift. warn closes the blind spot (it surfaces in
the advisory) without the aggressive block.

These cases pin: (1) custom title in a `.header` pushed off baseline FIRES warn;
(2) custom title in a `.header` AT baseline stays quiet (no false positive);
(3) a framework `.title-zh` in a raw `.header` off baseline is covered by BOTH
RAW-TITLE-POS (warn, advisory) AND R-VIS-TITLE-POSITION (error) — F-307 retired
the old "RAW-TITLE-POS defers to avoid double-report" contract because raw pages
don't reliably get the schema rule.
"""
import sys
import pathlib

HERE = pathlib.Path(__file__).resolve()
sys.path.insert(0, str(HERE.parent))
import engine_helpers as E  # noqa: E402


def _raw_with_header(header_top, title_cls):
    """A layout=raw slide whose `.header` (master-positioned, absolute) holds a
    title of class `title_cls`, with a stage-filling body below."""
    return (
        '<div class="slide" data-layout="raw" data-slide-key="t" '
        'style="position:relative;width:1920px;height:1080px">'
        f'<div class="header" style="position:absolute;top:{header_top}px;'
        'left:73px;right:320px;display:block">'
        f'<h2 class="{title_cls}" style="font-size:44px;margin:0;color:#fff">'
        '自定义类的标题在这里写一行</h2></div>'
        '<div class="raw-stage" style="position:absolute;top:340px;left:80px;'
        'right:80px;bottom:80px;border:1px solid #888;font-size:24px">'
        '正文卡片撑满本页</div>'
        '</div>')


def _run(rule, html):
    E.skip_if_no_engine()
    return E.findings_for(rule, html)


def test_rule_wired():
    assert E.rule_in_engine("R-VIS-RAW-TITLE-POS")


# ---- must-fire: custom-class title in a .header, pushed off baseline ----
def test_custom_title_in_header_low_fires_warn():
    """The blind spot: `.r-title` inside a `.header` at top:240 → RAW-TITLE-POS
    must fire (TITLE-POSITION can't see a custom title)."""
    hits = _run("R-VIS-RAW-TITLE-POS", _raw_with_header(240, "r-title"))
    assert len(hits) >= 1, f"custom-class raw title drift not flagged: {hits}"
    assert all(h["severity"] == "warn" for h in hits), \
        f"raw title drift MUST be warn, never error (F-256 block): {hits}"


def test_custom_title_other_class_also_fires():
    """Name-free: a different custom class (`.r-head`) is just as covered."""
    hits = _run("R-VIS-RAW-TITLE-POS", _raw_with_header(240, "r-head"))
    assert len(hits) >= 1, f"`.r-head` raw title drift not flagged: {hits}"


def test_title_position_silent_on_custom_title():
    """Control proving the blind spot is real: the schema rule cannot see a
    custom title, so it stays silent — RAW-TITLE-POS is what must cover it."""
    hits = _run("R-VIS-TITLE-POSITION", _raw_with_header(240, "r-title"))
    assert hits == [], \
        f"TITLE-POSITION unexpectedly resolved a custom title (test premise broke): {hits}"


# ---- must-not-fire: custom title AT baseline (no false positive) ----
def test_custom_title_in_header_at_baseline_quiet():
    hits = _run("R-VIS-RAW-TITLE-POS", _raw_with_header(61, "r-title"))
    assert hits == [], f"baseline custom raw title false-positived: {hits}"


# ---- framework .title-zh in a RAW header: BOTH rules now report (F-307) ----
def test_framework_title_in_header_raw_also_fires_raw_title_pos():
    """F-307 removed the old defer. On a RAW page a framework `.title-zh` drifted
    off baseline is now ALSO covered by R-VIS-RAW-TITLE-POS (warn, advisory) —
    raw pages don't reliably get the schema rule, so RAW-TITLE-POS no longer
    yields — while R-VIS-TITLE-POSITION keeps firing as the schema-path owner.
    (Pre-F-307 this test asserted RAW-TITLE-POS DEFERS / stays quiet; that
    contract was intentionally retired, so the assertion is flipped to match the
    shipped behavior. Ground-truth-confirmed: RAW=warn@240, TITLE-POSITION=error.)"""
    drifted = _raw_with_header(240, "title-zh")
    raw_hits = _run("R-VIS-RAW-TITLE-POS", drifted)
    assert len(raw_hits) >= 1, \
        f"RAW-TITLE-POS must cover a drifted framework .title-zh on a raw page (F-307): {raw_hits}"
    assert all(h["severity"] == "warn" for h in raw_hits), \
        f"raw title drift MUST be warn, never error (F-256 block): {raw_hits}"
    tp_hits = _run("R-VIS-TITLE-POSITION", drifted)
    assert len(tp_hits) >= 1, \
        f"TITLE-POSITION must still own the framework title (regression): {tp_hits}"


def test_framework_title_at_baseline_all_quiet():
    clean = _raw_with_header(61, "title-zh")
    assert _run("R-VIS-RAW-TITLE-POS", clean) == []
    assert _run("R-VIS-TITLE-POSITION", clean) == []


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
