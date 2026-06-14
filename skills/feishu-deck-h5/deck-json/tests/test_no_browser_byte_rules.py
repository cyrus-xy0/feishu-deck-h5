"""No-browser BYTE-PATH rules — M9 + C9 (UNIFY-VALIDATE-ARCH H1 restore).

The default render gate (`validate.py --no-visual`, the write-hook,
render-deck.py's default door) runs WITHOUT Chromium. The H1 restore put the
"truly source-byte-only" rules back onto that no-browser path so the gate keeps
real static enforcement:

    R-KEY      duplicate / missing / invalid / positional slide-key
    R-ESC-HTML literal escaped markup (&lt;span …&gt;) in slide text
    R02 / R07  per-frame data-layout / data-screen-label / .wordmark
               (R07 EXEMPT for canvas slides + imported decks — parity w/ audits.js)
    R05        emoji / '!' / '…' / '???' in slide copy (IMPORTED → warn_soft)
    R-DOM      <body> <div> OVER-close balance (extra </div>) — runs in BOTH paths

WHY a dedicated no-Chromium test file
-------------------------------------
The OTHER suites (test_validate_static_rules / test_imported_canvas_downgrade /
test_doc_integrity) exercise the SAME rule CODES through the rendered-DOM engine
(engine_helpers → run_unified_engine(dom_rules=True)) and SKIP when Chromium is
absent. This file pins the BYTE implementations of those codes: it calls
run_unified_engine(dom_rules=False) (M9) and the runner byte functions directly
(C9), so these source-text assertions EXECUTE (not skip) in a browserless
environment. The genuinely DOM/geometry rules stay on the engine path elsewhere.

It also pins the byte implementations to their PARITY REFERENCE (C9 — the
pre-migration Python rule engine @ git 076dc44, mirrored verbatim) and asserts
N1: run-audits.py's hand-mirrored constants/regexes match the canonical ones in
_validate_common.py (drift = bug, per the _validate_common module docstring).
"""
import importlib.util
import json
import re
import sys
import tempfile
import pathlib

HERE = pathlib.Path(__file__).resolve()
ASSETS = HERE.parents[2] / "assets"
sys.path.insert(0, str(ASSETS))

# Load run-audits.py (hyphenated → importlib) — the single shared engine entry.
_spec = importlib.util.spec_from_file_location("run_audits_bytes", ASSETS / "run-audits.py")
RA = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(RA)

import _validate_common as VC  # noqa: E402  (canonical mirror source for N1)


# ---------------------------------------------------------------------------
#  Fixture builders (pure source bytes — NO browser needed)
# ---------------------------------------------------------------------------
def _frame(layout="content", body="", *, key="k", label="x", lifted=False):
    lifted_attr = ' data-lifted="pptx:demo#1"' if lifted else ""
    label_attr = f' data-screen-label="{label}"' if label is not None else ""
    layout_attr = f' data-layout="{layout}"' if layout is not None else ""
    key_attr = f' data-slide-key="{key}"' if key is not None else ""
    return (
        f'<div class="slide-frame"><div class="slide"{layout_attr}{label_attr}'
        f'{key_attr}{lifted_attr}>{body}</div></div>'
    )


def _deck(frames, *, imported=False, extra_close=0):
    meta = ('<meta name="fs-deck-origin" content="imported">' if imported else "")
    closes = "</div>" * extra_close
    return (
        '<!doctype html><html><head><meta charset="utf-8">' + meta + "</head>"
        '<body><div class="deck">' + "".join(frames) + "</div>" + closes
        + "</body></html>"
    )


def _no_visual(html, scope=None):
    """Run the unified engine on the NO-BROWSER (dom_rules=False) path against the
    raw bytes — the M9 contract: source-text rules execute without Chromium.
    `scope` (1-based frame ordinals / None=whole deck) is fed through exactly as
    validate.py --scope-frames / run-audits.py --slide do."""
    with tempfile.TemporaryDirectory() as td:
        idx = pathlib.Path(td) / "index.html"
        idx.write_text(html, encoding="utf-8")
        result = RA.run_unified_engine(idx, scope, dom_rules=False)
    return result


def _codes(result, rule=None):
    return [f["rule"] for f in result["findings"]
            if rule is None or f["rule"] == rule]


def _by_rule(result, rule):
    return [f for f in result["findings"] if f["rule"] == rule]


# ==========================================================================
# M9 — the restored no-browser rules EXECUTE (not skip) without Chromium,
#      via run_unified_engine(dom_rules=False).
# ==========================================================================

def test_no_visual_path_is_browserless():
    # Sanity: the dom_rules=False run never touches a browser and reports it.
    result = _no_visual(_deck([_frame()]))
    assert result["dom_rules"] is False


def test_rkey_duplicate_fires_no_browser():
    html = _deck([_frame(key="dup"), _frame(key="dup")])
    assert "R-KEY" in _codes(_no_visual(html), "R-KEY")


def test_rkey_missing_fires_no_browser():
    html = _deck([_frame(key=None)])
    msgs = [f["message"] for f in _by_rule(_no_visual(html), "R-KEY")]
    assert any("missing data-slide-key" in m for m in msgs), msgs


def test_rkey_positional_authored_warns_no_browser():
    # positional slug on an AUTHORED slide → warn (not error, not soft).
    res = _no_visual(_deck([_frame(key="slide-06")]))
    rkey = _by_rule(res, "R-KEY")
    assert rkey and all(f["severity"] == "warn" for f in rkey), rkey


def test_rkey_positional_imported_softens_no_browser():
    # positional slug on a LIFTED slide → warn_soft (import downgrade).
    res = _no_visual(_deck([_frame(key="slide-06", lifted=True)]))
    rkey = _by_rule(res, "R-KEY")
    assert rkey and all(f["severity"] == "warn_soft" for f in rkey), rkey


def test_esc_html_fires_no_browser():
    html = _deck([_frame(body="<p>正文 &lt;span class=x&gt;裸标签文本</p>")])
    assert "R-ESC-HTML" in _codes(_no_visual(html), "R-ESC-HTML")


def test_esc_html_quiet_on_clean_text_no_browser():
    html = _deck([_frame(body="<p>正文里没有被转义的标签</p>")])
    assert "R-ESC-HTML" not in _codes(_no_visual(html), "R-ESC-HTML")


# ==========================================================================
# audits-js-2 — the no-browser path must HONOR scope for the per-slide rules
# (R02 / R07 / R-ESC-HTML), mirroring the audits.js driver's
# `scopeSet.has(slide_idx)` filter on the --visual path. Without this,
# `--no-visual --scope-frames N` leaked a pre-existing off-scope finding and
# diverged from `--visual --scope-frames N`, blocking a scoped edit.
# ==========================================================================

def test_scope_filters_off_scope_esc_html_no_browser():
    # escaped tag ONLY on slide 2; scope=[1] must NOT report slide 2's R-ESC-HTML.
    html = _deck([
        _frame(body="<p>干净正文</p>", key="a"),
        _frame(body="<p>裸 &lt;span class=x&gt;标签</p>", key="b"),
    ])
    in_scope = _by_rule(_no_visual(html, scope=[1]), "R-ESC-HTML")
    assert in_scope == [], in_scope
    # scope=[2] DOES report it (the finding is real, just off-scope above).
    on_target = _by_rule(_no_visual(html, scope=[2]), "R-ESC-HTML")
    assert any("slide 2" in f["message"] for f in on_target), on_target


def test_scope_filters_off_scope_structure_no_browser():
    # slide 2 missing data-layout (R02); scope=[1] must skip it.
    html = _deck([
        _frame("content", body="<div class='wordmark'></div>", key="a"),
        _frame(layout=None, body="<div class='wordmark'></div>", key="b"),
    ])
    in_scope = [f for f in _by_rule(_no_visual(html, scope=[1]), "R02")
                if "missing data-layout" in f["message"]]
    assert in_scope == [], in_scope
    on_target = [f for f in _by_rule(_no_visual(html, scope=[2]), "R02")
                 if "missing data-layout" in f["message"]]
    assert on_target, on_target


def test_scope_keeps_deck_level_rules_unscoped_no_browser():
    # R-KEY (deck-level) stays scope-independent: a duplicate key still fires
    # under a scope that excludes one of the dup frames — matching its audits.js
    # deck-level (isFirstInScope) twin.
    html = _deck([_frame(key="dup"), _frame(key="dup")])
    assert "R-KEY" in _codes(_no_visual(html, scope=[1]), "R-KEY")


def test_r02_missing_layout_fires_no_browser():
    html = _deck([_frame(layout=None, body="<div class='wordmark'></div>")])
    msgs = [f["message"] for f in _by_rule(_no_visual(html), "R02")]
    assert any("missing data-layout" in m for m in msgs), msgs


def test_r02_missing_screen_label_fires_no_browser():
    html = _deck([_frame(label=None, body="<div class='wordmark'></div>")])
    msgs = [f["message"] for f in _by_rule(_no_visual(html), "R02")]
    assert any("missing data-screen-label" in m for m in msgs), msgs


def test_r07_missing_wordmark_fires_no_browser():
    html = _deck([_frame("content", "<p>no wordmark here</p>")])
    assert "R07" in _codes(_no_visual(html), "R07")


def test_r07_canvas_exempt_no_browser():
    # parity with audits.js: canvas slide w/o .wordmark is EXEMPT from R07.
    html = _deck([_frame("canvas", "<p>纯净画布</p>")])
    assert "R07" not in _codes(_no_visual(html), "R07")


def test_r07_imported_deck_exempt_no_browser():
    # imported deck (deck-level fs-deck-origin=imported) → R07 exempt on all frames.
    html = _deck([_frame("content", "<p>x</p>")], imported=True)
    assert "R07" not in _codes(_no_visual(html), "R07")


def test_r05_emoji_authored_errors_no_browser():
    html = _deck([_frame(body="<p>太棒了😀</p>")])
    r05 = _by_rule(_no_visual(html), "R05")
    assert r05 and any(f["severity"] == "error" for f in r05), r05


def test_r05_imported_downgrades_no_browser():
    html = _deck([_frame(body="<p>未完待续…</p>", lifted=True)], imported=True)
    r05 = _by_rule(_no_visual(html), "R05")
    assert r05 and all(f["severity"] == "warn_soft" for f in r05), r05


def test_r_dom_over_close_fires_no_browser():
    # an EXTRA </div> at the body level → R-DOM over-close.
    html = _deck([_frame()], extra_close=1)
    assert "R-DOM" in _codes(_no_visual(html), "R-DOM")


def test_r_dom_balanced_quiet_no_browser():
    html = _deck([_frame()])
    assert "R-DOM" not in _codes(_no_visual(html), "R-DOM")


# ==========================================================================
# C9 — pin the runner byte-rule implementations to their parity reference
#      (assert R-KEY / R-ESC-HTML / R-DOM fire on crafted byte fixtures
#       under --no-visual), exercising the byte functions directly too.
# ==========================================================================

def test_c9_byte_functions_fire_directly():
    """The runner BYTE functions (not just the engine wrapper) fire on crafted
    byte fixtures — pins the pure-Python implementations themselves."""
    dup = _deck([_frame(key="dup"), _frame(key="dup")])
    assert any(f["rule"] == "R-KEY" and "already used" in f["message"]
               for f in RA.audit_slide_keys_bytes(dup))

    esc = _deck([_frame(body="<p>裸 &lt;b&gt;粗体&lt;/b&gt; 进了文本</p>")])
    assert any(f["rule"] == "R-ESC-HTML" for f in RA.audit_escaped_html_bytes(esc))

    over = _deck([_frame()], extra_close=2)
    dom = RA.audit_dom_balance_bytes(over)
    assert dom and dom[0]["rule"] == "R-DOM" and "extra </div>" in dom[0]["message"], dom


def test_c9_byte_rules_present_in_no_browser_run():
    """A single crafted deck that trips ALL the restored byte rules → the
    no-browser run surfaces each code (R-KEY / R-ESC-HTML / R02 / R07 / R05 /
    R-DOM). Guards against any code silently dropping off the byte path."""
    html = _deck([
        _frame("content", body="<p>太棒了! &lt;span class=x&gt;裸</p>", key="dup"),
        _frame("content", body="<p>正文</p>", key="dup"),
    ], extra_close=1)
    codes = set(_codes(_no_visual(html)))
    for expected in ("R-KEY", "R-ESC-HTML", "R07", "R05", "R-DOM"):
        assert expected in codes, f"{expected} missing from no-browser run: {codes}"


def test_c9_parity_reference_matches_old_engine():
    """Parity guard: the byte rules mirror the pre-migration Python rule engine
    @ git 076dc44 (skills/feishu-deck-h5/assets/_validate_audits.py). The slug
    validity / positional regexes and the escaped-tag detector are the load-bearing
    pieces; pin them to the EXACT pre-migration patterns so a mirror that drifts is
    caught even without the old file present.

    Source-of-truth patterns transcribed from 076dc44:_validate_audits.py:
      _KEY_VALID_SLUG_RE     = r'^[a-z][a-z0-9-]*$'
      _KEY_POSITIONAL_RE     = r'^(slide|page|section|frame)-?\\d+$'
      _ESC_TAGS              = span|b|i|em|strong|div|p|br|h[1-6]|ul|ol|li|a|svg|img|
                               small|sup|sub|mark|code
    """
    assert RA._KEY_VALID_SLUG_RE.pattern == r'^[a-z][a-z0-9-]*$'
    assert RA._KEY_POSITIONAL_RE.pattern == r'^(slide|page|section|frame)-?\d+$'
    assert RA._ESC_TAGS == (
        r'span|b|i|em|strong|div|p|br|h[1-6]|ul|ol|li|a|svg|img|'
        r'small|sup|sub|mark|code')
    # Behavioral parity probes against the transcribed semantics:
    assert RA._KEY_VALID_SLUG_RE.match("arr-history")
    assert not RA._KEY_VALID_SLUG_RE.match("ARR_History")
    assert RA._KEY_POSITIONAL_RE.match("slide-06")
    assert RA._KEY_POSITIONAL_RE.match("page12")
    assert not RA._KEY_POSITIONAL_RE.match("arr-history")


# ==========================================================================
# N1 — drift test: run-audits.py's hand-mirrored constants/regexes must match
#      the canonical ones in _validate_common.py (or single-source via import).
#      The _validate_common module docstring documents this exact contract.
# ==========================================================================

def test_n1_slide_frame_open_regex_mirror_matches():
    assert RA._SLIDE_FRAME_OPEN_RE.pattern == VC._SLIDE_FRAME_OPEN_RE.pattern, \
        "run-audits.py _SLIDE_FRAME_OPEN_RE drifted from _validate_common"


def test_n1_style_block_regex_mirror_matches():
    assert RA._STYLE_BLOCK_RE.pattern == VC._STYLE_BLOCK_RE.pattern, \
        "run-audits.py _STYLE_BLOCK_RE drifted from _validate_common"


def test_n1_allowed_decor_mirror_matches():
    # R38 ship list — audits.js mirrors _validate_common.ALLOWED_DECOR; the
    # audits.js copy is verified elsewhere, here pin the canonical set membership
    # so the documented single source can't silently shrink.
    js = (ASSETS / "audits.js").read_text(encoding="utf-8")
    m = re.search(r"const ALLOWED_DECOR = new Set\(\[(.*?)\]\)", js, re.S)
    assert m, "ALLOWED_DECOR not found in audits.js"
    js_set = set(re.findall(r"'([^']+)'", m.group(1)))
    assert js_set == VC.ALLOWED_DECOR, \
        f"audits.js ALLOWED_DECOR {js_set} != _validate_common {VC.ALLOWED_DECOR}"


def test_n1_iter_style_blocks_mirror_behaves_identically():
    # Behavioral mirror: the framework-flagging logic must be identical between
    # the hand-mirrored RA._iter_style_blocks and the canonical VC one.
    css = ('<style data-source="framework">.a{}</style>'
           '<style>.b{}</style>')
    ra_blocks = list(RA._iter_style_blocks(css))
    vc_blocks = list(VC._iter_style_blocks(css))
    assert ra_blocks == vc_blocks, \
        f"_iter_style_blocks drift: {ra_blocks} != {vc_blocks}"
    # include_framework=False must drop the framework block in both.
    ra_no_fw = list(RA._iter_style_blocks(css, include_framework=False))
    vc_no_fw = list(VC._iter_style_blocks(css, include_framework=False))
    assert ra_no_fw == vc_no_fw == [(".b{}", False)], (ra_no_fw, vc_no_fw)


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
