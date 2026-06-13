"""R-LAYOUT-DEPRECATED · F-305 «raw unless ceremonial» 版式收编 (2026-06-12).

正文 schema 版式 (content / stats / flow / chart / table / arch-stack /
image-text / logo-wall, 含全部 variant) 已冻结 → warn_soft 提醒新页走 raw。
仪式页 (cover/section/agenda/quote/end) + 机制页 (raw/canvas/iframe-embed/
replica) 永不报。imported / 无 deck.json 整体豁免。SOURCE-OF-TRUTH = deck.json 的
真 authored layout(非渲染后 data-layout —— raw 页会借 schema CSS)。同批退役了
反向规则 R-RAW-LOOKS-SCHEMA。
"""
import re
import sys
import pathlib

HERE = pathlib.Path(__file__).resolve()
ASSETS = HERE.parents[2] / "assets"
sys.path.insert(0, str(HERE.parent))
import engine_helpers as E  # noqa: E402
DOC = HERE.parents[2] / "references" / "validator-rules.md"

RULE = "R-LAYOUT-DEPRECATED"
FROZEN = ("content", "stats", "flow", "chart", "table",
          "arch-stack", "image-text", "logo-wall")
KEPT = ("cover", "section", "agenda", "quote", "end",
        "raw", "canvas", "iframe-embed", "replica")


# ── static contract (no engine — always runs) ───────────────────────────────

def test_rule_wired_and_twin_retired():
    assert E.rule_in_engine(RULE), "R-LAYOUT-DEPRECATED not emitted by the engine"
    assert RULE in DOC.read_text(encoding="utf-8"), \
        "R-LAYOUT-DEPRECATED undocumented in validator-rules.md (F-03 sync)"
    # the inverse rule must be RETIRED — no longer emitted by the engine
    # (only explanatory comments may still name it).
    assert not E.rule_in_engine("R-RAW-LOOKS-SCHEMA"), \
        "R-RAW-LOOKS-SCHEMA should be RETIRED (no `rule:` emit) per F-305"


def test_frozen_set_complete_and_disjoint():
    js = E.audits_js_text()
    m = re.search(r"DEPRECATED_BODY_LAYOUTS\s*=\s*new Set\(\[(.*?)\]\)", js, re.S)
    assert m, "DEPRECATED_BODY_LAYOUTS set not found in audits.js"
    body = m.group(1)
    for lyt in FROZEN:
        assert f"'{lyt}'" in body, f"{lyt} missing from DEPRECATED_BODY_LAYOUTS"
    for keep in KEPT:
        assert f"'{keep}'" not in body, f"{keep} must NOT be frozen (ceremonial/mechanism)"


# ── behaviour (needs Chromium; skips gracefully if unavailable) ──────────────

def _slide(key, data_layout, *, lifted=False):
    lift = ' data-lifted=""' if lifted else ''
    return (f'<div class="slide-frame"><div class="slide" data-layout="{data_layout}"'
            f'{lift} data-screen-label="x" data-slide-key="{key}">'
            f'<div class="header"><h2 class="title-zh">标题</h2></div>'
            f'<div class="stage">正文内容</div></div></div>')


def _dj(*pairs):
    return {"slides": [{"key": k, "layout": lyt} for (k, lyt) in pairs]}


def _soft(slides, dj=None):
    E.skip_if_no_engine()
    return E.soft_codes(RULE, slides, deck_json=dj)


def test_fires_on_frozen_content():
    soft = _soft([_slide("c1", "content-3up")], _dj(("c1", "content")))
    assert RULE in soft, f"frozen `content` layout not flagged: {soft}"


def test_fires_on_each_frozen_layout():
    # one slide per frozen base layout → exactly len(FROZEN) flags
    slides = [_slide(f"k{i}", lyt) for i, lyt in enumerate(FROZEN)]
    dj = _dj(*[(f"k{i}", lyt) for i, lyt in enumerate(FROZEN)])
    E.skip_if_no_engine()
    n = E.soft_codes(RULE, slides, deck_json=dj).count(RULE)
    assert n == len(FROZEN), f"expected {len(FROZEN)} frozen flags, got {n}"


def test_quiet_on_raw():
    soft = _soft([_slide("r1", "raw")], _dj(("r1", "raw")))
    assert RULE not in soft, f"raw page wrongly flagged: {soft}"


def test_quiet_on_ceremonial():
    slides = [_slide("sec1", "section"), _slide("e1", "end"), _slide("q1", "quote")]
    soft = _soft(slides, _dj(("sec1", "section"), ("e1", "end"), ("q1", "quote")))
    assert RULE not in soft, f"ceremonial page wrongly flagged: {soft}"


def test_imported_deck_exempt():
    # `content` layout BUT the (only) slide is lifted → deckAllImported() → exempt
    soft = _soft([_slide("c2", "content-3up", lifted=True)], _dj(("c2", "content")))
    assert RULE not in soft, f"imported (all-lifted) deck should be exempt: {soft}"


def test_quiet_without_deck_json():
    # no deck.json sidecar → cannot read the authored layout → skip silently
    soft = _soft([_slide("x1", "content-3up")], None)
    assert RULE not in soft, f"should skip silently when no deck.json injected: {soft}"


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
