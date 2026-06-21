"""R-EMBED-OPAQUE-BG · embedded-dashboard opaque inner background = black edge.

A raw slide that full-bleed-embeds a dashboard via `<iframe src="data:text/html;…">`
can have its OUTER layers (iframe element, `.slide`, the letterbox `.slide-frame`)
made transparent / deck-bg — but if the iframe's INNER content paints an opaque
dark background on a full-cover wrapper (`html`/`body`/`.stage-host`/the fit
`.slide`), that inner layer covers the deck's near-black navy and shows a
harder-than-deck black edge at the slide/letterbox border. This was the
齐鲁 指挥中心 #27/#28/#29 root cause: the outer layer was "fixed" three times before
the inner layer was found, because the inner content is base64-encoded in the
`data:` URI and NO prior rule could see it (every other rule strips `data:` URIs).

The rule decodes the `data:text/html` payload (base64 / percent), resolves one
level of `var()`, and flags a background whose first color is OPAQUE (alpha ≥ .5)
AND DARK (relative luminance < .18) on a full-cover selector. Low-alpha glow
gradients / `transparent` / light full-bleed (white dashboards) do NOT fire.
name-free (keys on the `data:text/html` src, not the `embed-frame` class).
Opt-out: `data-allow-embed-bg` on the iframe or an ancestor.
"""
import base64
import importlib.util
import pathlib
import sys
import urllib.parse

HERE = pathlib.Path(__file__).resolve()
sys.path.insert(0, str(HERE.parent))
import engine_helpers as E  # noqa: E402

RULE = "R-EMBED-OPAQUE-BG"
ASSETS = HERE.parents[2] / "assets"
ROOT = HERE.parents[2]


# ── fixtures ─────────────────────────────────────────────────────────────────
def _embed_src(inner_css, *, b64=True):
    """A data:text/html iframe src whose inner doc carries `inner_css`."""
    inner = (
        '<!doctype html><html><head><meta charset="utf-8"><style>'
        + inner_css
        + '</style></head><body><div class="stage-host">'
        '<div class="slide">x</div></div></body></html>'
    )
    if b64:
        return "data:text/html;base64," + base64.b64encode(inner.encode()).decode()
    return "data:text/html," + urllib.parse.quote(inner)


def _iframe(inner_css, *, b64=True, attrs=""):
    return f'<iframe{attrs} src="{_embed_src(inner_css, b64=b64)}"></iframe>'


def _slide(inner, *, extra_attrs=""):
    return (
        f'<div class="slide" data-layout="raw" data-screen-label="x" '
        f'data-slide-key="t"{extra_attrs} '
        'style="position:relative;width:1920px;height:1080px">' + inner + "</div>"
    )


def _run(html, **kw):
    E.skip_if_no_engine()
    return E.findings_for(RULE, html, **kw)


def test_rule_wired():
    assert E.rule_in_engine(RULE)


# ── must-fire: opaque dark inner background ──────────────────────────────────
def test_opaque_dark_body_fires_warn():
    """The exact #28/#29 shape: inner body{background:#04070E} (near-black) fires."""
    hits = _run(_slide(_iframe("body{background:#04070E;}")))
    assert len(hits) >= 1, f"opaque dark inner body not flagged: {hits}"
    assert all(h["severity"] == "warn" for h in hits), \
        f"must be WARN: {[h['severity'] for h in hits]}"


def test_dark_gradient_fit_slide_fires():
    """Inner .slide{linear-gradient(#0A0F1A…)} — the dark canvas gradient fires
    (first color stop is near-black, opaque)."""
    hits = _run(_slide(_iframe(
        ".slide{background:linear-gradient(155deg,#0A0F1A 0%,#070B14 60%,#0A0E18 100%);}")))
    assert len(hits) >= 1, f"dark gradient canvas not flagged: {hits}"


def test_var_resolved_body_fires():
    """qilu-digital-avatar-section shape: body{background:var(--ink)} where
    --ink:#080912 — one level of var() is resolved, so it fires."""
    hits = _run(_slide(_iframe(":root{--ink:#080912;} body{background:var(--ink);}")))
    assert len(hits) >= 1, f"var(--ink) opaque dark not flagged: {hits}"


def test_percent_encoded_payload_fires():
    """A non-base64 (percent-encoded) data: URI is decoded and flagged too."""
    hits = _run(_slide(_iframe("body{background:#04070E;}", b64=False)))
    assert len(hits) >= 1, f"percent-encoded inner not flagged: {hits}"


def test_html_body_combined_selector_fires():
    """`html,body{background:#04070E}` (comma list) is matched on either token."""
    hits = _run(_slide(_iframe("html,body{background:#04070E;}")))
    assert len(hits) >= 1, f"html,body combined selector not flagged: {hits}"


# ── must-NOT-fire: the fixed shape + non-bugs (zero false positives) ─────────
def test_all_transparent_silent():
    """The #27 fix shape — every cover wrapper transparent → silent."""
    hits = _run(_slide(_iframe(
        "html,body{background:transparent;} .stage-host{background:transparent;} "
        ".slide{background:transparent;}")))
    assert hits == [], f"transparent inner false-positived: {hits}"


def test_light_full_bleed_silent():
    """A deliberately light (white) full-bleed dashboard is not a black edge."""
    hits = _run(_slide(_iframe("body{background:#ffffff;}")))
    assert hits == [], f"light inner false-positived: {hits}"


def test_low_alpha_glow_silent():
    """A subtle low-alpha glow gradient on .stage-host (the real #28 stage-host)
    is effectively transparent → silent."""
    hits = _run(_slide(_iframe(
        ".stage-host{background:radial-gradient(1100px 640px at 60% 0%, "
        "rgba(80,120,255,.06), transparent 70%);}")))
    assert hits == [], f"low-alpha glow false-positived: {hits}"


def test_midtone_color_silent():
    """A mid-tone (not near-black) opaque bg is above the darkness floor → silent."""
    hits = _run(_slide(_iframe("body{background:#1a3a6b;}")))
    assert hits == [], f"mid-tone bg false-positived: {hits}"


def test_remote_iframe_silent():
    """A remote (http) iframe is R-IFRAME-REMOTE's job, not this rule → silent."""
    hits = _run(_slide('<iframe src="https://example.com/dash"></iframe>'))
    assert hits == [], f"remote iframe false-positived: {hits}"


def test_local_src_iframe_silent():
    """A local/relative-src iframe (no inline content to inspect) → silent."""
    hits = _run(_slide('<iframe src="sub/page.html"></iframe>'))
    assert hits == [], f"local-src iframe false-positived: {hits}"


def test_no_iframe_silent():
    """A plain raw slide with no embedded iframe → silent."""
    hits = _run(_slide('<div style="font-size:24px">正文</div>'))
    assert hits == [], f"no-iframe slide false-positived: {hits}"


# ── opt-out ──────────────────────────────────────────────────────────────────
def test_opt_out_on_iframe_silences():
    """data-allow-embed-bg on the iframe silences an intentional dark embed."""
    hits = _run(_slide(_iframe("body{background:#04070E;}", attrs=" data-allow-embed-bg")))
    assert hits == [], f"data-allow-embed-bg on iframe did not silence: {hits}"


def test_opt_out_on_slide_ancestor_silences():
    """data-allow-embed-bg on an ancestor (the slide) also silences."""
    hits = _run(_slide(_iframe("body{background:#04070E;}"),
                       extra_attrs=" data-allow-embed-bg"))
    assert hits == [], f"data-allow-embed-bg on slide did not silence: {hits}"


# ── doc-sync: the rule must be registered across every surface ───────────────
def test_rule_literal_in_audits_js():
    js = (ASSETS / "audits.js").read_text(encoding="utf-8")
    assert f"rule: '{RULE}'" in js, f"{RULE} not emitted as a rule literal in audits.js"
    assert f"id: '{RULE}'" in js, f"{RULE} has no rule object (id) in audits.js"
    assert f"'{RULE}':" in js, f"{RULE} missing a RULE_META entry"


def test_code_in_check_only_families():
    spec = importlib.util.spec_from_file_location("check_only_eob", ASSETS / "check-only.py")
    CO = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(CO)
    fam = {c for _, codes in CO.FAMILIES for c in codes}
    assert RULE in fam, f"{RULE} not categorized in check-only FAMILIES"


def test_code_in_business_rules_yaml():
    txt = (ASSETS / "business-rules.yaml").read_text(encoding="utf-8")
    assert f"{RULE}:" in txt, f"{RULE} missing a business-rules.yaml entry"


def test_code_documented_in_reference():
    doc = (ROOT / "references" / "validator-rules.md").read_text(encoding="utf-8")
    assert RULE in doc, f"{RULE} missing from references/validator-rules.md"


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
