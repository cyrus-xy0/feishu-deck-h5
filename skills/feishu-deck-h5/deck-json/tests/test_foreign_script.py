"""R-FOREIGN-SCRIPT · injection-surface minimum line of defense (F-287).

The parser ingests external HTML/PPTX/Lark docs whose instruction-like text flows
into the model context (prompt injection) while the executing model holds
render/publish/ingest write power; raw pages allow arbitrary markup; lifting a
page from a foreign deck drags arbitrary `<script>` that spreads cross-deck via
slide-library; publishing to the Feishu-login CF viewer = XSS in an internal
audience's browser.

R-FOREIGN-SCRIPT (audits.js) detects executable content inside a `.slide` —
scripts, event handlers, srcdoc, and active URLs. It is **provenance-graded**:
lifted (`data-lifted`) /
imported (`<meta name="fs-deck-origin" content="imported">`) slides = ERROR (the
foreign script spreads on ingest); ordinary authored pages = WARN.

Real framework scripts sit at `<body>` level, never inside a `.slide`. A marker
or framework-looking basename inside a slide is author-controlled and must not
be trusted. Non-executable `type` islands remain safe.

These cases pin: foreign `<script>` (inline + src) and `on*` handlers fire;
severity grades by lift/import provenance; body-level framework scripts produce
ZERO findings; an authored page may opt out, but lifted markup cannot self-grant
that permission.
"""
import sys
import pathlib

HERE = pathlib.Path(__file__).resolve()
sys.path.insert(0, str(HERE.parent))
import engine_helpers as E  # noqa: E402

RULE = "R-FOREIGN-SCRIPT"


def _slide(inner, *, layout="raw", lifted=False, extra_attrs=""):
    """A `.slide` carrying `inner` markup. `lifted=True` stamps data-lifted."""
    lift = " data-lifted" if lifted else ""
    return (
        f'<div class="slide" data-layout="{layout}" data-screen-label="x" '
        f'data-slide-key="t"{lift}{extra_attrs} '
        'style="position:relative;width:1920px;height:1080px">'
        + inner
        + "</div>"
    )


def _full_doc(slide_inner, *, imported=False):
    """A FULL document so deck-level provenance (fs-deck-origin meta) is read."""
    meta = ('<meta name="fs-deck-origin" content="imported">' if imported else "")
    return (
        '<!doctype html><html><head><meta charset="utf-8">' + meta + "</head>"
        '<body><div class="deck"><div class="slide-frame">'
        + _slide(slide_inner, layout="raw")
        + "</div></div></body></html>"
    )


def _run(html, **kw):
    E.skip_if_no_engine()
    return E.findings_for(RULE, html, **kw)


def test_rule_wired():
    assert E.rule_in_engine(RULE)


# ── must-fire: foreign executable content ────────────────────────────────────
def test_inline_script_in_authored_raw_fires_warn():
    """An inline <script> in an authored raw page fires — at WARN (authored)."""
    hits = _run(_slide('<script>window.x=alert("hi")</script>'))
    assert len(hits) >= 1, f"inline <script> not flagged: {hits}"
    assert all(h["severity"] == "warn" for h in hits), \
        f"authored page script must be WARN: {[(h['severity']) for h in hits]}"


def test_external_script_src_fires():
    """A non-framework <script src> fires (the lift/XSS vector)."""
    hits = _run(_slide('<script src="https://evil.example/x.js"></script>'))
    assert len(hits) >= 1, f"foreign <script src> not flagged: {hits}"
    assert any("evil.example" in h.get("sample", "") for h in hits), \
        f"finding should sample the offending src: {hits}"


def test_inline_event_handler_fires():
    """An on* inline event attribute is executable code → fires (name-free)."""
    hits = _run(_slide('<div onclick="steal()">click</div>'))
    assert len(hits) >= 1, f"onclick handler not flagged: {hits}"


def test_onerror_handler_fires():
    """A different on* attribute (onerror, the classic img XSS) is just as covered."""
    hits = _run(_slide('<img src="x" onerror="fetch(\'//evil\')">'))
    assert len(hits) >= 1, f"onerror handler not flagged: {hits}"


def test_javascript_url_and_srcdoc_fire():
    hits = _run(_slide('<a href="java&#x73;cript:steal()">x</a>'
                       '<iframe srcdoc="&lt;script&gt;steal()&lt;/script&gt;"></iframe>'))
    assert len(hits) >= 2, f"active URL/srcdoc not flagged: {hits}"


def test_active_data_url_fires():
    hits = _run(_slide('<iframe src="data:text/html,&lt;script&gt;x()&lt;/script&gt;"></iframe>'))
    assert hits, f"active data URL not flagged: {hits}"


# ── severity grading by provenance ───────────────────────────────────────────
def test_lifted_slide_script_is_error():
    """A lifted slide (data-lifted, untrusted source) → ERROR, not warn."""
    hits = _run(_slide('<script>evil()</script>', lifted=True))
    assert len(hits) >= 1, f"lifted-slide script not flagged: {hits}"
    assert all(h["severity"] == "error" for h in hits), \
        f"lifted/imported foreign script must be ERROR: {[h['severity'] for h in hits]}"


def test_imported_deck_script_is_error():
    """An imported deck (<meta fs-deck-origin=imported>) → ERROR for any slide."""
    hits = _run(_full_doc('<script>evil()</script>', imported=True))
    assert len(hits) >= 1, f"imported-deck script not flagged: {hits}"
    assert all(h["severity"] == "error" for h in hits), \
        f"imported deck foreign script must be ERROR: {[h['severity'] for h in hits]}"


# ── forged provenance must fire; true framework remains outside slides ───────
def test_forged_framework_marker_inside_slide_fires():
    """An imported fragment cannot self-assert framework provenance."""
    hits = _run(_slide('<script data-source="framework">deckInit()</script>'))
    assert hits, f"forged framework marker bypassed audit: {hits}"


def test_framework_looking_basename_inside_slide_fires():
    """A filename is not provenance; real runtime lives outside the slide."""
    hits = _run(_slide('<script src="../../assets/feishu-deck.js"></script>'))
    assert hits, f"framework-looking basename bypassed audit: {hits}"
    hits2 = _run(_slide('<script src="../assets/edit-mode/deck-edit-mode.js" defer></script>'))
    assert hits2, f"framework-looking edit-mode basename bypassed audit: {hits2}"


def test_json_data_island_exempt():
    """A <script type="application/json"> is a non-executable data island (the
    fs-deck-notes pattern), not code → exempt."""
    hits = _run(_slide('<script type="application/json" id="fs-deck-notes">{"a":1}</script>'))
    assert hits == [], f"JSON data island false-positived: {hits}"


def test_text_plain_source_copy_exempt():
    """A <script type="text/plain"> (runner's non-executing framework source
    copy) is not executable → exempt."""
    hits = _run(_slide('<script type="text/plain" data-source="framework">x</script>'))
    assert hits == [], f"text/plain script false-positived: {hits}"


def test_clean_slide_no_script_silent():
    """A normal raw slide with no script / no on* handler → silent."""
    hits = _run(_slide('<div class="raw-stage" style="font-size:24px">正文内容</div>'))
    assert hits == [], f"clean slide false-positived: {hits}"


def test_body_level_framework_scripts_not_in_slide_scope():
    """The realistic clean-deck shape: framework <script src> at <body> level,
    OUTSIDE every .slide. The rule scopes to the .slide subtree, so a clean deck
    that legitimately carries framework scripts triggers ZERO findings."""
    doc = (
        '<!doctype html><html><head><meta charset="utf-8"></head><body>'
        '<div class="deck"><div class="slide-frame">'
        + _slide('<div style="font-size:24px">干净正文</div>', layout="content")
        + "</div></div>"
        '<script src="../assets/feishu-deck.js"></script>'
        '<script src="../assets/edit-mode/deck-edit-mode.js" defer></script>'
        '<script type="application/json" id="fs-deck-notes">{}</script>'
        "</body></html>"
    )
    hits = _run(doc)
    assert hits == [], f"body-level framework scripts leaked into slide scope: {hits}"


# ── opt-out ──────────────────────────────────────────────────────────────────
def test_opt_out_silences_intentional_script():
    """data-allow-foreign-script on the slide silences a deliberately-scripted
    bespoke raw page (the documented last escape)."""
    hits = _run(_slide('<script>intentional()</script>',
                       extra_attrs=' data-allow-foreign-script'))
    assert hits == [], f"data-allow-foreign-script opt-out did not silence: {hits}"


def test_opt_out_cannot_be_forged_by_lifted_fragment():
    """Untrusted markup cannot self-grant an execution escape hatch."""
    hits = _run(_slide('<script>intentional()</script>', lifted=True,
                       extra_attrs=' data-allow-foreign-script'))
    assert hits and all(h["severity"] == "error" for h in hits), \
        f"lifted opt-out incorrectly bypassed audit: {hits}"


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
