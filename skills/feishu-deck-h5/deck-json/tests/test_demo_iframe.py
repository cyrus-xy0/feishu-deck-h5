"""R-DEMO-IFRAME · iframe-embed provenance guard (validate-deck.py, 2026-06-11).

A slide imported/lifted from an `iframe-embed` page keeps the
`_orig_layout: "iframe-embed"` marker — it WAS an embedded interactive demo.
An edit pass that rewrites such a page into a static mock silently destroys the
live demo the author cared about (the validator is the only gate that can see
the marker + the missing `<iframe>` together, deck.json-side).

These cases pin: marker + no `<iframe>` in data.html → ERROR; marker + iframe
present → clean; the slide-level `"allow": ["no-iframe"]` escape hatch silences
it (and the schema accepts the token); an ordinary raw slide WITHOUT the marker
never fires.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
DECK_JSON = HERE.parent
VALIDATE = DECK_JSON / "validate-deck.py"

RULE = "R-DEMO-IFRAME"


def _deck(slide_extra=None, html="<div class=\"mock\">static mock</div>"):
    slide = {
        "key": "demo",
        "layout": "raw",
        "data": {"html": html},
    }
    slide.update(slide_extra or {})
    return {
        "version": "1.0",
        "deck": {"title": "T", "language": "zh-only"},
        "slides": [slide],
    }


def _run_validate(deck: dict, *extra) -> tuple[int, str]:
    tmp = tempfile.NamedTemporaryFile(
        "w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(deck, tmp, ensure_ascii=False)
    tmp.flush()
    tmp.close()
    path = Path(tmp.name)
    try:
        proc = subprocess.run(
            [sys.executable, str(VALIDATE), str(path), *extra],
            capture_output=True, text=True,
        )
        return proc.returncode, proc.stdout + proc.stderr
    finally:
        path.unlink(missing_ok=True)


def test_iframe_embed_origin_without_iframe_errors():
    """_orig_layout='iframe-embed' + no <iframe> in html → ERROR (demo lost)."""
    rc, log = _run_validate(_deck({"_orig_layout": "iframe-embed"}))
    assert rc == 1, f"expected validation failure:\n{log}"
    assert RULE in log, f"{RULE} not reported:\n{log}"


def test_iframe_embed_origin_with_iframe_is_clean():
    """The marker + a live <iframe> still in the html → no finding."""
    rc, log = _run_validate(_deck(
        {"_orig_layout": "iframe-embed"},
        html='<iframe src="./demo/index.html" style="width:100%;height:100%"></iframe>',
    ))
    assert rc == 0, f"expected PASS:\n{log}"
    assert RULE not in log, f"{RULE} must not fire when the iframe survives:\n{log}"


def test_allow_no_iframe_silences():
    """Slide-level "allow": ["no-iframe"] explicitly accepts the static rebuild
    (and proves the schema accepts the token — schema + business rules both run)."""
    rc, log = _run_validate(_deck(
        {"_orig_layout": "iframe-embed", "allow": ["no-iframe"]}))
    assert rc == 0, f"expected PASS with allow:no-iframe:\n{log}"
    assert RULE not in log, f"{RULE} must be silenced by allow:no-iframe:\n{log}"


def test_plain_raw_slide_without_marker_never_fires():
    """No _orig_layout marker → an iframe-less raw page is perfectly normal."""
    rc, log = _run_validate(_deck())
    assert rc == 0, f"expected PASS:\n{log}"
    assert RULE not in log, f"{RULE} fired without the iframe-embed marker:\n{log}"


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
