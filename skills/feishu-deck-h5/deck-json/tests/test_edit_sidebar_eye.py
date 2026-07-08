import pathlib
import re


ASSETS = pathlib.Path(__file__).resolve().parents[2] / "assets"
EDIT_CSS = ASSETS / "edit-mode" / "deck-edit-mode.css"


def _css_rule(selector: str) -> str:
    css = EDIT_CSS.read_text(encoding="utf-8")
    m = re.search(rf"{re.escape(selector)}\s*\{{(?P<body>.*?)\n\}}", css, re.S)
    assert m, f"missing CSS rule for {selector}"
    return m.group("body")


def test_sidebar_eye_toggle_is_visible_without_hover():
    base_rule = _css_rule(".es-eye")
    assert not re.search(r"\bopacity\s*:\s*0\s*(?:;|/)", base_rule), (
        "The edit sidebar eye button must be discoverable without row hover."
    )
    assert re.search(r"\bdisplay\s*:\s*inline-flex\s*;", base_rule)
