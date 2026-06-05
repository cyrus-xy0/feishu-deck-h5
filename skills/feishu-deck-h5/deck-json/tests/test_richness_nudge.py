"""Unit tests for R-VIS-NO-IMAGERY — the design-quality nudge added 2026-05-29
from the quality benchmark (#1 gap: decks read visually flat / all text cards).

UNIFY-VALIDATE-ARCH step 4b: the rule now lives in the unified engine (rendered
DOM); fixtures render headlessly and we read the warn_soft findings. Covers
must-fire + must-not-fire + advisory-never-errors + sparse-skip. Chromium req.
Note: each slide carries a UNIQUE data-slide-key so the multi-slide fixtures
don't trip R-KEY duplicate (the old per-function call never saw sibling keys).
"""
import sys
import pathlib

ASSETS = pathlib.Path(__file__).resolve().parents[2] / "assets"
sys.path.insert(0, str(ASSETS))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import engine_helpers as E  # noqa: E402

_KSEQ = iter(range(100000))


def _slide(layout: str, body: str = "") -> str:
    return (
        f'<div class="slide-frame"><div class="slide" '
        f'data-layout="{layout}" data-screen-label="x" '
        f'data-slide-key="k{next(_KSEQ)}">'
        f"{body}</div></div>"
    )


def _soft_codes(slides):
    E.skip_if_no_engine()
    return E.soft_codes("R-VIS-NO-IMAGERY", list(slides))


def test_flat_deck_fires():
    # 3 content slides, all zero-imagery -> 3/3 flat -> nudge fires
    slides = [
        _slide("cover"), _slide("stats"), _slide("content-3up"),
        _slide("matrix-2x2"), _slide("end"),
    ]
    assert "R-VIS-NO-IMAGERY" in _soft_codes(slides)


def test_rich_deck_no_fire():
    # 2 of 3 content slides carry an icon -> 1/3 flat (33%) < 60% -> no nudge
    slides = [
        _slide("cover"), _slide("stats", "<svg></svg>"),
        _slide("content-3up", "<svg></svg>"), _slide("matrix-2x2"),
        _slide("end"),
    ]
    assert "R-VIS-NO-IMAGERY" not in _soft_codes(slides)


def test_image_or_background_counts_as_imagery():
    slides = [
        _slide("stats", '<img src="x.png">'),
        _slide("content-3up", '<div style="background-image:url(x)"></div>'),
        _slide("matrix-2x2", "<svg></svg>"),
    ]
    assert "R-VIS-NO-IMAGERY" not in _soft_codes(slides)  # 0/3 flat


def test_advisory_never_a_hard_error():
    E.skip_if_no_engine()
    slides = [_slide("stats"), _slide("content-3up"), _slide("matrix-2x2")]
    rno = [f for f in E.run(slides) if f.get("rule") == "R-VIS-NO-IMAGERY"]
    assert all(f.get("severity") == "warn_soft" for f in rno), \
        "R-VIS-NO-IMAGERY must only ever be a soft advisory, never err/warn"


def test_sparse_layouts_skipped():
    # cover/section/end/quote/agenda are sparse-by-design -> 0 content slides
    slides = [
        _slide("cover"), _slide("section"), _slide("quote"),
        _slide("end"), _slide("agenda"),
    ]
    assert "R-VIS-NO-IMAGERY" not in _soft_codes(slides)


def test_under_threshold_no_fire():
    # only 2 content slides (< 3 minimum) -> never fires regardless
    slides = [_slide("stats"), _slide("content-3up")]
    assert "R-VIS-NO-IMAGERY" not in _soft_codes(slides)


if __name__ == "__main__":
    # Allow running without pytest: python3 test_richness_nudge.py
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")
