"""UI1 升级 · 整页截图当正文 → err (2026-05-31, P9).

字号检查够不到栅格图像里的 8-10px 字 → 从源头禁止贴截图当正文。内容版式非品牌
<img> → err;replica / imported → 降 warn;品牌资产豁免。Static.
"""
import sys
import pathlib

ASSETS = pathlib.Path(__file__).resolve().parents[2] / "assets"
sys.path.insert(0, str(ASSETS))
from _validate_common import Issues          # noqa: E402
from _validate_audits import audit_ui_mocks_are_html  # noqa: E402


def _deck(slide_inner, meta=""):
    return (f'<html><head>{meta}</head><body><div class="deck">'
            f'<div class="slide-frame"><div class="slide">{slide_inner}</div></div>'
            '</div></body></html>')


def _run(html):
    i = Issues()
    audit_ui_mocks_are_html(html, i)
    return [c for c, _ in i.errors], [c for c, _ in i.warnings]


def test_content_screenshot_img_is_error():
    err, warn = _run(_deck('<img src="assets/meeting-screenshot.png">'))
    assert "UI1" in err, f"content screenshot <img> should be ERROR: err={err} warn={warn}"


def test_brand_asset_img_exempt():
    err, warn = _run(_deck('<img src="assets/lark-logo.png">'))
    assert "UI1" not in err and "UI1" not in warn, f"brand logo should be exempt: {err} {warn}"


def test_replica_page_downgrades_to_warn():
    err, warn = _run(_deck('<img src="page-3.png" class="page-replica">'))
    assert "UI1" not in err and "UI1" in warn, f"replica img should be WARN not err: {err} {warn}"


def test_imported_deck_downgrades_to_warn():
    err, warn = _run(_deck('<img src="shot.png">',
                           meta='<meta name="fs-deck-origin" content="imported">'))
    assert "UI1" not in err and "UI1" in warn, f"imported deck img should be WARN: {err} {warn}"


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
