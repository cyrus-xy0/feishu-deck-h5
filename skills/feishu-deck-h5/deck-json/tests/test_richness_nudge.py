"""Unit tests for audit_visual_richness (R-VIS-NO-IMAGERY) — the design-quality
nudge added 2026-05-29 from the quality benchmark (#1 gap: decks read visually
flat / all text cards). Fast: imports validate.py directly, no render, no
Playwright. Covers must-fire + must-not-fire + advisory-never-errors + sparse-skip.
"""
import sys
import pathlib

ASSETS = pathlib.Path(__file__).resolve().parents[2] / "assets"
sys.path.insert(0, str(ASSETS))
import validate as V  # noqa: E402


def _slide(layout: str, body: str = "") -> str:
    return (
        f'<div class="slide-frame"><div class="slide" '
        f'data-layout="{layout}" data-screen-label="x" data-slide-key="k">'
        f"{body}</div></div>"
    )


def _soft_codes(slides):
    iss = V.Issues()
    V.audit_visual_richness(slides, iss)
    return [c for c, _ in iss.soft_warnings]


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
    iss = V.Issues()
    V.audit_visual_richness(
        [_slide("stats"), _slide("content-3up"), _slide("matrix-2x2")], iss
    )
    assert iss.errors == []  # only ever warn_soft, never err


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
