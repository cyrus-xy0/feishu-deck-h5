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


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
