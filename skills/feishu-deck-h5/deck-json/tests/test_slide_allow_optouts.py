"""Slide-level visual-audit opt-out channel (2026-06-04).

`_build_data_attrs` is the ONLY authoring path for the three slide-scoped
opt-outs the visual engine checks via `slide.hasAttribute` (imbalance /
no-focal / title-gap). Before this, a raw/schema slide that was by-design
parallel (R-FOCAL) or asymmetric (R-VIS-BALANCE) had no way to mark intent
through deck.json. These tests lock: (1) the renderer emits `data-allow-<token>`
on .slide for allowlisted tokens, warns+skips unknown ones; (2) the schema
accepts the `allow` field and rejects bad tokens.
"""
import importlib.util
import json
import sys
import pathlib

DECK_JSON = pathlib.Path(__file__).resolve().parents[1]
SCHEMA = DECK_JSON / "deck-schema.json"


def _load_render():
    sys.path.insert(0, str(DECK_JSON))
    spec = importlib.util.spec_from_file_location("render_deck", DECK_JSON / "render-deck.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_build_data_attrs_emits_slide_allow():
    m = _load_render()
    out = m._build_data_attrs({"key": "s1", "accent": "violet", "allow": ["no-focal"]})
    assert 'data-allow-no-focal' in out
    assert 'data-accent="violet"' in out

    out2 = m._build_data_attrs({"key": "s2", "allow": ["imbalance", "title-gap"]})
    assert 'data-allow-imbalance' in out2
    assert 'data-allow-title-gap' in out2


def test_build_data_attrs_skips_unknown_token():
    m = _load_render()
    out = m._build_data_attrs({"key": "s3", "allow": ["bogus", "no-focal"]})
    assert 'data-allow-no-focal' in out
    assert 'bogus' not in out  # unknown token never reaches the DOM


def test_build_data_attrs_empty_when_no_allow():
    m = _load_render()
    assert 'data-allow' not in m._build_data_attrs({"key": "s4"})


def test_build_data_attrs_emits_data_hidden_for_hidden_true():
    m = _load_render()
    assert 'data-hidden' in m._build_data_attrs({"key": "h1", "hidden": True})


def test_build_data_attrs_no_data_hidden_when_false_or_missing():
    m = _load_render()
    # hidden:false must NOT emit data-hidden (the renderer treats absence/false
    # identically — a visible slide).
    assert 'data-hidden' not in m._build_data_attrs({"key": "h2", "hidden": False})
    # missing hidden key → visible → no attribute
    assert 'data-hidden' not in m._build_data_attrs({"key": "h3"})


def test_schema_accepts_allow_and_rejects_bad_token():
    try:
        import jsonschema
    except Exception:
        import pytest
        pytest.skip("jsonschema not installed")
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    slide_def = schema["$defs"]["slide"]
    # standalone-validate just the slide subschema against the root $defs
    base = {"$defs": schema["$defs"]}
    good = {**slide_def, **base}
    jsonschema.validate({"key": "k", "layout": "raw", "data": {"html": "<div></div>"}, "allow": ["no-focal", "imbalance"]}, good)
    bad = False
    try:
        jsonschema.validate({"key": "k", "layout": "raw", "data": {"html": "<div></div>"}, "allow": ["not-a-real-optout"]}, good)
    except jsonschema.ValidationError:
        bad = True
    assert bad, "schema must reject an unknown allow token"


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
