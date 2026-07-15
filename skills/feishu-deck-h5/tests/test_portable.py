"""verify-portable.py (F-343) must-fire / must-not-fire guards.

The portability gate replaces an ad-hoc shell check that kept mangling paths via
BSD sed/tr quote handling. It flags the four ways a run output/ breaks once it
leaves the skill folder: skill-relative refs, parent-escaping refs, missing local
files, and symlink members. JS-escaped-string noise and non-file refs must NOT
fire.
"""
import importlib.util
import hashlib
import os
import pathlib
import stat
import subprocess
import sys
import zipfile

ASSETS = pathlib.Path(__file__).resolve().parents[1] / "assets"

_spec = importlib.util.spec_from_file_location(
    "verify_portable", ASSETS / "verify-portable.py")
_VP = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_VP)


def _kinds(output_dir):
    return sorted({p["kind"] for p in _VP.scan(str(output_dir))})


def _zip_kinds(zip_path, source_html=None):
    return sorted({p["kind"] for p in _VP.scan_zip(str(zip_path), source_html)})


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


def _write_output_zip(output_dir, zip_path):
    with zipfile.ZipFile(zip_path, "w") as archive:
        for path in output_dir.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(output_dir).as_posix())


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


def test_clean_zip_is_portable_and_matches_source_html(tmp_path):
    out = _portable_output(tmp_path)
    archive = tmp_path / "deck.zip"
    _write_output_zip(out, archive)

    assert _VP.scan_zip(str(archive), str(out / "index.html")) == []


def test_zip_integrity_check_is_mandatory(tmp_path, monkeypatch):
    out = _portable_output(tmp_path)
    archive = tmp_path / "deck.zip"
    _write_output_zip(out, archive)
    monkeypatch.setattr(_VP.zipfile.ZipFile, "testzip", lambda _self: "index.html")

    assert "zip-corrupt" in _zip_kinds(archive)


def test_zip_rejects_absolute_and_parent_traversal_members(tmp_path):
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr(
            "index.html",
            '<img src="/absolute.png"><img src="../escape.png">',
        )
        zipped.writestr("/absolute.txt", "x")
        zipped.writestr("../escape.txt", "x")

    kinds = _zip_kinds(archive)
    assert "zip-absolute" in kinds
    assert "zip-absolute-ref" in kinds
    assert "zip-traversal" in kinds
    assert "escapes" in kinds


def test_zip_rejects_symlink_members(tmp_path):
    archive = tmp_path / "symlink.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("index.html", "<html></html>")
        link = zipfile.ZipInfo("assets/shared")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        zipped.writestr(link, "/tmp/shared")

    assert "zip-symlink" in _zip_kinds(archive)


def test_zip_requires_root_index_html(tmp_path):
    archive = tmp_path / "missing-index.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("README.txt", "x")

    assert "zip-missing-index" in _zip_kinds(archive)


def test_zip_requires_local_references_to_exist_as_members(tmp_path):
    archive = tmp_path / "missing-ref.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("index.html", '<img src="assets/missing.png">')

    assert "zip-missing" in _zip_kinds(archive)


def test_zip_index_must_match_selected_source_html(tmp_path):
    source = tmp_path / "source.html"
    _write(source, "<html>source</html>")
    archive = tmp_path / "mismatch.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("index.html", "<html>changed</html>")

    assert "index-mismatch" in _zip_kinds(archive, str(source))


def test_package_deliverable_verifies_zip_without_changing_source(tmp_path):
    out = _portable_output(tmp_path)
    source_before = hashlib.sha256((out / "index.html").read_bytes()).hexdigest()
    script = ASSETS / "package-deliverable.sh"

    result = subprocess.run(
        ["bash", str(script), str(out), "--name", "verified-deck"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "PACKAGE_VERIFIED=1 VISUAL_RECHECK_REQUIRED=0 STOP=1" in result.stdout
    assert hashlib.sha256((out / "index.html").read_bytes()).hexdigest() == source_before
    assert _VP.scan_zip(
        str(out / "verified-deck.zip"), str(out / "index.html")) == []


def test_package_delivery_failure_is_labeled_and_source_is_unchanged(tmp_path):
    out = _portable_output(tmp_path)
    source_before = hashlib.sha256((out / "index.html").read_bytes()).hexdigest()
    fake_bin = tmp_path / "bin"
    fake_zip = fake_bin / "zip"
    _write(
        fake_zip,
        "#!/usr/bin/env python3\n"
        "import sys, zipfile\n"
        "with zipfile.ZipFile(sys.argv[4], 'w') as archive:\n"
        "    archive.writestr('index.html', '<html>tampered</html>')\n"
        "    archive.writestr('README.txt', 'x')\n",
    )
    fake_zip.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"

    result = subprocess.run(
        ["bash", str(ASSETS / "package-deliverable.sh"), str(out),
         "--name", "broken-deck"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    assert result.returncode == 2
    assert "FAIL_DOMAIN=delivery DO_NOT_EDIT_DECK=1" in result.stderr
    assert hashlib.sha256((out / "index.html").read_bytes()).hexdigest() == source_before
    assert not (out / "broken-deck.zip").exists()


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
