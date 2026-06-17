"""verify-portable.py (F-343) must-fire / must-not-fire guards.

The portability gate replaces an ad-hoc shell check that kept mangling paths via
BSD sed/tr quote handling. It flags the four ways a run output/ breaks once it
leaves the skill folder: skill-relative refs, parent-escaping refs, missing local
files, and symlink members. JS-escaped-string noise and non-file refs must NOT
fire.
"""
import importlib.util
import os
import pathlib
import sys

ASSETS = pathlib.Path(__file__).resolve().parents[1] / "assets"

_spec = importlib.util.spec_from_file_location(
    "verify_portable", ASSETS / "verify-portable.py")
_VP = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_VP)


def _kinds(output_dir):
    return sorted({p["kind"] for p in _VP.scan(str(output_dir))})


def _write(p: pathlib.Path, text: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _portable_output(tmp_path):
    """A minimal self-contained output/ — index.html + a real local asset."""
    out = tmp_path / "output"
    _write(out / "assets" / "feishu-deck.css", "body{}")
    _write(out / "input" / "cover.png", "x")
    _write(out / "index.html",
           '<html><head><link href="assets/feishu-deck.css" rel="stylesheet">'
           '</head><body><img src="input/cover.png"></body></html>')
    return out


def test_clean_output_is_portable(tmp_path):
    out = _portable_output(tmp_path)
    assert _VP.scan(str(out)) == []


def test_skill_relative_ref_fires(tmp_path):
    out = _portable_output(tmp_path)
    _write(out / "index.html",
           '<img src="../../../../skills/feishu-deck-h5/assets/lark-logo.png">')
    assert "skill-relative" in _kinds(out)


def test_parent_escape_ref_fires(tmp_path):
    out = _portable_output(tmp_path)
    # ../input escapes output/ entirely
    _write(out / "index.html", '<img src="../../elsewhere/photo.jpg">')
    assert "escapes" in _kinds(out)


def test_missing_local_ref_fires(tmp_path):
    out = _portable_output(tmp_path)
    _write(out / "index.html", '<img src="input/does-not-exist.png">')
    assert "missing" in _kinds(out)


def test_symlink_member_fires(tmp_path):
    out = _portable_output(tmp_path)
    real = tmp_path / "outside-shared"
    real.mkdir()
    (real / "a.png").write_text("x", encoding="utf-8")
    link = out / "assets" / "shared"
    os.symlink(real, link)
    assert "symlink" in _kinds(out)


def test_js_escaped_string_noise_does_not_fire(tmp_path):
    out = _portable_output(tmp_path)
    # escaped-quote uuid inside an inline <script> must be ignored, and a
    # remote/data ref must be ignored too.
    _write(out / "index.html",
           '<html><body><img src="input/cover.png">'
           '<script>var x = "src=\\"a3b5-not-a-file\\"";</script>'
           '<img src="https://cdn.example.com/x.png">'
           '<img src="data:image/png;base64,AAAA"></body></html>')
    assert _VP.scan(str(out)) == []


def test_non_file_href_does_not_fire(tmp_path):
    out = _portable_output(tmp_path)
    _write(out / "index.html",
           '<html><body><a href="#section-2">jump</a>'
           '<a href="mailto:x@y.com">mail</a>'
           '<img src="input/cover.png"></body></html>')
    assert _VP.scan(str(out)) == []


def test_embedded_prototype_self_contained_does_not_fire(tmp_path):
    """A prototype HTML in a subdir referencing its own sibling asset is fine."""
    out = _portable_output(tmp_path)
    _write(out / "prototypes" / "demo" / "assets" / "p.png", "x")
    _write(out / "prototypes" / "demo" / "index.html",
           '<img src="assets/p.png">')
    assert _VP.scan(str(out)) == []


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
