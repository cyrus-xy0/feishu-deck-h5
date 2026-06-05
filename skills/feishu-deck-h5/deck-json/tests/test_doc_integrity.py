"""R-DOC-INTEGRITY · whole-document completeness gate (F-85, 2026-06-03).

Production gap: a deck index.html lost its closing tags — missing `.deck` close
`</div>`, the `<script src=…feishu-deck.js>` runtime gone, no trailing
`</body></html>`. In the browser the present-mode runtime never initializes
(`is-current` never set on any frame) → the deck "显示不全 / 显示什么都没有".
Yet R-DOM reported CLEAN: `audit_dom_integrity` only checks per-frame NESTING,
and its body parse RETURNS EARLY on a `<body…>(.*)</body>` regex that doesn't
match a truncated (no `</body>`) document — so the broken deck sailed through.

R-DOC-INTEGRITY closes that gap with three ERROR-severity invariants on the
document AS A WHOLE: (1) .deck opened AND closed (no mid-deck truncation),
(2) present-mode runtime present (linked src OR inlined runtime fingerprint),
(3) document ends with </body> and </html>.

UNIFY-VALIDATE-ARCH step 4b: R-DOC-INTEGRITY is a runner SOURCE-BYTE rule (it
MUST read the raw index.html bytes — the browser auto-closes tags, so a rendered
DOM is always balanced). The tests render via engine_helpers with verbatim=True
(the exact fragment bytes are written to index.html, NO wrapping) so truncation
is detectable. R-DOM stays a rendered-DOM rule and is correctly BLIND to byte
truncation (the gap this rule closes). Requires Chromium.
"""
import sys
import pathlib

ASSETS = pathlib.Path(__file__).resolve().parents[2] / "assets"
sys.path.insert(0, str(ASSETS))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import engine_helpers as E  # noqa: E402

# The auto-balance fingerprint the engine recognizes as an inlined runtime.
_AUTOBALANCE_SIG = "function balanceSlide(slide)"

# A minimal but COMPLETE deck: .deck open+close, a runtime script (carries the
# `is-current` toggle the present-mode runtime sets — version-independent
# fingerprint), and well-formed </body></html>.
_RUNTIME = ('<script>(function(){var f=document.querySelector(".slide-frame");'
            'f.classList.add("is-current");})();</script>')


def _healthy(body_runtime=_RUNTIME, end='</body></html>'):
    return ('<html><body>'
            '<div class="deck">'
            '<div class="slide-frame"><div class="slide">hi</div></div>'
            '</div><!-- /.deck -->'
            + body_runtime + end)


def _doc_msgs(html):
    """R-DOC-INTEGRITY messages (the runner reads raw bytes → verbatim=True)."""
    E.skip_if_no_engine()
    return [f["message"] for f in E.run(html, verbatim=True)
            if f.get("rule") == "R-DOC-INTEGRITY"]


def _run(html):
    return ["R-DOC-INTEGRITY"] * len(_doc_msgs(html))


def test_healthy_deck_passes():
    assert _run(_healthy()) == [], "complete deck must pass R-DOC-INTEGRITY"


def test_passes_with_inlined_balanceslide_fingerprint():
    # newest single-file builds: runtime present via balanceSlide fingerprint
    rt = '<script>function ' + _AUTOBALANCE_SIG.split()[1] + ' { /* ... */ }</script>'
    assert _run(_healthy(body_runtime=rt)) == [], "inlined balanceSlide build must pass"


def test_passes_with_linked_src():
    rt = '<script src="../../../skills/feishu-deck-h5/assets/feishu-deck.js"></script>'
    assert _run(_healthy(body_runtime=rt)) == [], "linked feishu-deck.js deck must pass"


def test_skips_non_deck_fragment():
    html = '<div class="replica"><img src="x.png"></div>'   # no .deck container
    assert _run(html) == [], "non-deck HTML fragment must be skipped"


def test_author_opt_out():
    html = '<div class="deck"><div class="slide"></div>' + '<!-- allow:doc-integrity -->'
    assert _run(html) == [], "allow:doc-integrity must suppress the audit"


# ---- the production bug: truncated tail (closes + runtime both lost) ----

def test_truncated_tail_errors():
    # missing .deck close, runtime script, and </body></html>
    broken = ('<html><body><div class="deck">'
              '<div class="slide-frame"><div class="slide">hi</div></div>')
    errs = _run(broken)
    assert errs.count("R-DOC-INTEGRITY") == 3, \
        "truncated tail must fire all three invariants (close/runtime/end)"


def test_truncated_tail_is_the_GAP_rdom_is_blind():
    # The exact gap: R-DOM returns CLEAN on a doc with no </body> (the rendered
    # DOM is always balanced — the browser auto-closes tags), but R-DOC-INTEGRITY
    # (raw bytes) catches it. Guards against regressing the regression.
    broken = ('<html><body><div class="deck">'
              '<div class="slide-frame"><div class="slide">hi</div></div>')
    E.skip_if_no_engine()
    rdom = [f for f in E.run(broken, verbatim=True) if f.get("rule") == "R-DOM"]
    assert rdom == [], \
        "R-DOM is expected to be blind here (rendered DOM is auto-balanced)"
    assert "R-DOC-INTEGRITY" in _run(broken), "R-DOC-INTEGRITY must close the gap"


# ---- (b) .deck opened but truncated mid-way ----

def test_deck_opened_but_unclosed_errors():
    broken = ('<html><body><div class="deck">'
              '<div class="slide-frame"><div class="slide">hi</div></div>'
              + _RUNTIME + '</body></html>')   # .deck never closed
    errs = _run(broken)
    assert "R-DOC-INTEGRITY" in errs, "unclosed .deck must error"
    # specifically the div-balance invariant
    assert any('opens vs' in m for m in _doc_msgs(broken)), \
        "must report div open/close imbalance"


# ---- (c) missing ONLY the runtime script ----

def test_missing_only_runtime_errors_once():
    broken = _healthy(body_runtime='')   # closes intact, runtime gone
    msgs = _doc_msgs(broken)
    assert len(msgs) == 1, "only the runtime-absent invariant should fire"
    assert 'runtime is ABSENT' in msgs[0]


# ---- end-of-doc truncation only ----

def test_missing_end_tags_errors():
    broken = _healthy(end='')   # .deck closed + runtime present, but no </body></html>
    msgs = _doc_msgs(broken)
    assert len(msgs) == 1 and 'truncated at the end' in msgs[0], \
        "only the end-of-doc invariant should fire"


# ---- does NOT false-positive on a stale-runtime deck (R-AUTOBALANCE's job) ----

def test_stale_runtime_present_passes_docintegrity():
    # A complete deck whose runtime lacks balanceSlide but DOES toggle
    # is-current (older build). R-DOC-INTEGRITY (runtime PRESENT) must pass;
    # R-AUTOBALANCE-PRESENT is the one that polices the stale build.
    stale = ('<script>var f=document.querySelector(".slide-frame");'
             'f.classList.add("is-current");</script>')
    assert _AUTOBALANCE_SIG not in stale
    assert _run(_healthy(body_runtime=stale)) == [], \
        "deck with a present-but-stale runtime must pass R-DOC-INTEGRITY"


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
