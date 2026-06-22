"""Unit tests for _css_utils.scope_selectors / iter_css_rules (LIFT-ARCHITECTURE
step 1). scope_selectors is the shared primitive both lift tracks depend on, so
its corner cases (comma groups, @media recursion, @keyframes passthrough,
already-scoped idempotency, [data-page] back-compat, :is()/[attr] comma traps)
get explicit coverage — a silent mis-scope ships a slide that styles its
siblings or renders unstyled after a lift.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import _css_utils  # noqa: E402

scope = _css_utils.scope_selectors
KEY = "five-judgments"
PREFIX = f'.slide[data-slide-key="{KEY}"]'


def test_bare_descendant_is_prefixed():
    out = scope(".ns-card { color: red; }", KEY)
    assert out.strip() == f'{PREFIX} .ns-card {{ color: red; }}'


def test_element_selector_is_prefixed():
    out = scope("h4 { font-weight: 700; }", KEY)
    assert out.strip().startswith(f'{PREFIX} h4 {{')


def test_comma_group_each_part_scoped():
    out = scope(".a, .b { x: 1; }", KEY)
    assert f'{PREFIX} .a' in out
    assert f'{PREFIX} .b' in out
    # exactly two scoped parts, one rule
    assert out.count(PREFIX) == 2


def test_slide_root_is_merged_not_descended():
    # `.slide` means the slide itself → must become the scope, NOT a descendant
    out = scope(".slide { background: #000; }", KEY)
    assert out.strip().startswith(f'{PREFIX} {{')
    assert ".slide .slide" not in out


def test_slide_root_with_descendant():
    out = scope(".slide .header { top: 40px; }", KEY)
    assert out.strip().startswith(f'{PREFIX} .header {{')


def test_already_scoped_passthrough_idempotent():
    src = f'{PREFIX} .ns-card {{ color: red; }}'
    out = scope(src, KEY)
    # idempotent: scoping an already-scoped selector must not double-prefix
    assert out.count("data-slide-key") == 1
    assert out.strip() == src


def test_data_page_backcompat_rewrite():
    out = scope('[data-page="07"] .ns-card { color: red; }', KEY)
    assert "[data-page=" not in out
    assert f'{PREFIX} .ns-card' in out


def test_ampersand_means_slide_root():
    out = scope("&.is-blue { color: blue; }", KEY)
    assert out.strip().startswith(f'{PREFIX}.is-blue {{')


def test_media_query_recurses_keeps_wrapper():
    out = scope("@media (max-width: 768px) { .ns-card { x: 1; } }", KEY)
    assert "@media (max-width: 768px)" in out
    assert f'{PREFIX} .ns-card' in out


def test_keyframes_passthrough_verbatim():
    src = "@keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }"
    out = scope(src, KEY)
    # name + % steps untouched, never scoped
    assert "@keyframes fadeIn" in out
    assert PREFIX not in out


def test_keyframes_and_rule_mixed():
    src = "@keyframes spin { to { transform: rotate(360deg); } } .ns-card { animation: spin 2s; }"
    out = scope(src, KEY)
    assert "@keyframes spin" in out
    assert f'{PREFIX} .ns-card' in out
    # the keyframe block itself is not scoped
    assert out.count(PREFIX) == 1


def test_is_pseudo_comma_not_split():
    out = scope(":is(.a, .b) .c { x: 1; }", KEY)
    # the inner comma in :is() must NOT create two scoped rules
    assert out.count(PREFIX) == 1
    assert ":is(.a, .b)" in out


def test_attribute_selector_comma_not_split():
    out = scope('[data-x="a,b"] { x: 1; }', KEY)
    assert out.count(PREFIX) == 1


def test_comments_preserved():
    out = scope("/* hi */ .a { x: 1; }", KEY)
    assert "/* hi */" in out


def test_empty_input_returns_empty():
    assert scope("", KEY) == ""
    assert scope("   \n  ", KEY) == ""


def test_font_face_passthrough():
    src = "@font-face { font-family: X; src: url(x.woff2); }"
    out = scope(src, KEY)
    assert "@font-face" in out
    assert PREFIX not in out


def test_iter_css_rules_skips_at_rules():
    rules = list(_css_utils.iter_css_rules(
        "@media x { .a { x:1; } } .b { y: 2; } /* c */ .c { z: 3; }"))
    sels = [s for s, _ in rules]
    assert ".b" in sels and ".c" in sels
    # the .a inside @media is skipped (at-rules are not descended by iter)
    assert ".a" not in sels


# ---------------------------------------------------------------------------
# F-364 · promote_root_bg_to_frame — letterbox 黑边 root cure
# ---------------------------------------------------------------------------
promote = _css_utils.promote_root_bg_to_frame
FRAME_SEL = f'.deck[data-mode="present"] .slide-frame:has(> .slide[data-slide-key="{KEY}"])'
SCROLL_SEL = f'.deck[data-mode="scroll"] .slide[data-slide-key="{KEY}"]'


def _bg_rules_only_on_frame_or_scroll(css):
    """The seam-killing invariant: NO present-mode rule whose SUBJECT is the
    slide root may set a background (that is what ties + defeats F-318). A
    descendant rule (`.slide .card`) paints a child, not the letterbox, so it is
    fine — and a full-bleed descendant is markBleedPanels' job, not ours. A
    scroll-mode slide-root bg is fine too (scroll has no letterbox)."""
    for sel, body in _css_utils.iter_css_rules(css):
        if "background" not in body or 'data-mode="scroll"' in sel:
            continue
        for part in _css_utils._split_top_level_commas(sel):
            assert not _css_utils._targets_slide_root(part), \
                f"present-mode slide-root background can defeat F-318: {part!r}"


def test_promote_basic_root_bg():
    out = promote(".slide { background: red; }", KEY)
    assert FRAME_SEL in out
    assert SCROLL_SEL in out
    assert out.count("background: red") == 2          # frame (present) + slide (scroll)
    _bg_rules_only_on_frame_or_scroll(out)


def test_promote_attr_qualified_root_like_real_decks():
    # the real #8/#9 authored form
    css = ('.slide[data-layout="raw"][data-slide-key] {\n'
           '  background: linear-gradient(135deg, #07142b, #050509) !important;\n}')
    out = promote(css, KEY)
    assert FRAME_SEL in out and SCROLL_SEL in out
    assert "!important" in out
    _bg_rules_only_on_frame_or_scroll(out)


def test_promote_keeps_non_bg_decls_on_slide_both_modes():
    out = promote(".slide { background: red; color: white; }", KEY)
    # color stays on the slide root (F-318 only zeroes bg, not color)
    rules = {sel.strip(): body for sel, body in _css_utils.iter_css_rules(out)}
    slide_rules = [b for s, b in rules.items()
                   if s == ".slide" or s.startswith(".slide ")]
    assert any("color: white" in b for b in slide_rules)
    assert all("background" not in b for b in slide_rules)   # bg hoisted away
    _bg_rules_only_on_frame_or_scroll(out)


def test_promote_descendant_subject_untouched():
    src = ".slide .card { background: red; }"
    assert promote(src, KEY) == src          # byte-identical passthrough


def test_promote_slide_frame_untouched():
    src = ".slide-frame { background: red; }"
    assert promote(src, KEY) == src


def test_promote_slideshow_untouched():
    src = ".slideshow { background: red; }"
    assert promote(src, KEY) == src


def test_promote_reset_bg_skipped():
    for v in ("transparent", "none", "inherit"):
        src = ".slide { background: %s; }" % v
        assert promote(src, KEY) == src      # nothing worth hoisting


def test_promote_idempotent():
    once = promote(".slide { background: red; }", KEY)
    twice = promote(once, KEY)
    assert once == twice                     # emitted rules are not re-promoted


def test_promote_comma_mixed_root_and_descendant():
    out = promote(".slide, .slide .card { background: red; }", KEY)
    assert ".slide .card" in out             # descendant part keeps its full rule
    assert FRAME_SEL in out                  # root part is hoisted
    _bg_rules_only_on_frame_or_scroll(out)


def test_promote_background_longhands():
    css = ".slide { background-color: #07142b; background-image: url(x.png); }"
    out = promote(css, KEY)
    assert FRAME_SEL in out
    assert "background-color: #07142b" in out
    assert "background-image: url(x.png)" in out
    _bg_rules_only_on_frame_or_scroll(out)


def test_promote_then_scope_no_root_bg_survives():
    # END-TO-END: the renderer runs promote() THEN scope_selectors(). After both,
    # there must be NO present-mode slide-root background rule left to tie F-318.
    css = '.slide[data-layout="raw"] { background: linear-gradient(135deg, #07142b, #050509); }'
    out = scope(promote(css, KEY), KEY)
    assert FRAME_SEL in out                  # frame selector survives scoping verbatim
    assert SCROLL_SEL in out
    _bg_rules_only_on_frame_or_scroll(out)


def test_promote_non_bg_root_rule_untouched():
    src = ".slide { color: white; font-family: serif; }"
    assert promote(src, KEY) == src          # no background -> nothing to do


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
