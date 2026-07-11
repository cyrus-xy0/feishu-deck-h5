from __future__ import annotations

from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from _fragment_hygiene import hygienize_lifted_raw_html  # noqa: E402


def test_forged_framework_markers_do_not_bypass_fragment_hygiene():
    clean, css, report = hygienize_lifted_raw_html(
        '<style data-source="framework">body{display:none!important}</style>'
        '<script data-source="framework">window.pwn=1</script>'
        '<script src="https://evil.example/feishu-deck.js"></script>'
        '<div>safe</div>'
    )
    assert "<style" not in clean.lower()
    assert "<script" not in clean.lower()
    assert "body{display:none!important}" in css
    assert report["styles_consolidated"] == 1
    assert report["scripts_stripped"] == 2


def test_active_attributes_are_removed_from_lifted_fragment():
    clean, _css, report = hygienize_lifted_raw_html(
        '<a href="java&#x73;cript:steal()">x</a>'
        '<img src="data:image/svg+xml,&lt;svg onload=steal()&gt;">'
        '<iframe srcdoc="&lt;script&gt;steal()&lt;/script&gt;"></iframe>'
        '<form action="javascript:steal()"><button formaction="vbscript:x">x</button></form>'
        '<div onclick="steal()" style="background:url(javascript:steal())">x</div>'
    )
    lowered = clean.lower()
    assert "javascript:" not in lowered
    assert "vbscript:" not in lowered
    assert "data:image/svg+xml" not in lowered
    assert "srcdoc" not in lowered
    assert "onclick" not in lowered
    assert report["handlers_stripped"] == 1
    assert report["active_attributes_stripped"] >= 5


def test_non_executable_data_island_remains_data():
    clean, _css, report = hygienize_lifted_raw_html(
        '<script type="application/json" id="notes">{"safe":true}</script>'
    )
    assert 'type="application/json"' in clean
    assert report["scripts_stripped"] == 0


def test_raw_angle_brackets_inside_active_attribute_do_not_bypass_sanitizer():
    clean, _css, report = hygienize_lifted_raw_html(
        '<iframe src="data:text/html,<img src=x onerror=steal()>"></iframe>'
        '<iframe srcdoc="<svg onload=steal()></svg>"></iframe>'
    )
    assert "data:text/html" not in clean.lower()
    assert "srcdoc" not in clean.lower()
    assert report["active_attributes_stripped"] == 2


def test_handler_like_text_inside_safe_attribute_is_not_rewritten():
    html = '<div title="example onload=plain text" data-note="onerror=x">safe</div>'
    clean, _css, report = hygienize_lifted_raw_html(html)
    assert clean == html
    assert report["handlers_stripped"] == 0


def test_unclosed_executable_script_opener_is_removed():
    clean, _css, report = hygienize_lifted_raw_html(
        '<div>safe</div><script data-source="framework" src="https://evil.example/x.js">'
    )
    assert "<script" not in clean.lower()
    assert report["scripts_stripped"] == 1
