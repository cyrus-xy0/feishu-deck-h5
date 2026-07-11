#!/usr/bin/env python3
"""Fast single-slide preview for feishu-deck-h5.

Reads ONE slide from a deck.json, drops it into the framework shell
(`.deck > .slide-frame.is-current > .slide`), forces the deck canvas static
(no present-mode scaling / no JS), screenshots it 1:1, and — by default —
runs the unified audit engine (audits.js) on the rendered slide so you get
the per-slide GATE findings (geometry / typescale / overflow / drop-shadow /
soft-white-text / focal …) in the SAME ~2s pass — no 12s render-deck
round-trip just to discover a layout-rule violation.

Use it for fast VISUAL + GATE iteration (layout / text / wrapping / color +
the rules that would otherwise only surface in render-deck). Then run
`render-deck.py <deck.json> . --scope <key> --final` once at the end to
commit + run the FULL deck-wide gate (palette / title drift, present-mode
chrome, cross-slide rules) + the making-of snapshot.

Caveat: JS-driven motion, iframe-embed content, and fitText won't run here —
those need the real render. The gate here is SINGLE-SLIDE + STATIC, so it
deliberately SUPPRESSES framework / present-mode / whole-deck rules that
cannot be evaluated on one static slide (they run at render-deck --final):
present-mode chrome (R29-32 / R36), every-layout centering (R48), wordmark
default (L1), CSS-var source scan over a linked sheet (R-CSSVAR), and
deck-wide drift (R-DECK-*). Pass --no-gate for screenshot only.

Usage:
  preview-slide.py <deck.json> <page>            # 1-based page number
  preview-slide.py <deck.json> --key <slide_key>
  preview-slide.py <deck.json> 21 --out /tmp/p21.png
  preview-slide.py <deck.json> --key foo --no-gate   # screenshot only
"""
import sys, os, json, argparse, time, pathlib, importlib.util, html

HERE = pathlib.Path(__file__).resolve().parent
AUDITS_JS = HERE.parent / "assets" / "audits.js"
ASSETS_DIR = HERE.parent / "assets"


def _load_renderer():
    spec = importlib.util.spec_from_file_location("_preview_render_deck", HERE / "render-deck.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load render-deck.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

# Rules that structurally CANNOT be judged on a single static slide preview —
# they validate the framework shell / present-mode chrome / whole-deck
# consistency, none of which exists in the one-slide harness. Suppressed in the
# preview gate (informational); they still run at render-deck --final.
GATE_SUPPRESS_IDS = {
    "R29-32",   # present-mode chrome (progress bar / controls / fullscreen JS)
    "R36",      # present-mode slide centering (absolute + negative margin)
    "R48",      # every framework layout needs a vertical-centering rule
    "R07",      # framework structure: raw slide "missing .wordmark" (logo is
                # framework chrome, not authored on the slide)
    "R-AUTOBALANCE-PRESENT",  # deck must inline feishu-deck.js runtime — a build
                # concern; the one-slide harness has no present-mode JS
    "L1",       # wordmark default → var(--fs-asset-logo)
    "R-CSSVAR", # CSS-var source scan: a linked sheet's cssRules are unreadable
                # here (link, not inlined) → false "var never defined"
}


def _suppressed(rule: str) -> bool:
    if rule in GATE_SUPPRESS_IDS:
        return True
    if rule.startswith("R-DECK-"):   # deck-wide drift (palette/radius/title) — needs all slides
        return True
    return False


def _template_root_attrs(pack) -> str:
    """Return escaped provenance attrs for the standalone preview harness."""
    return (
        f' data-template-id="{html.escape(str(pack.template_id), quote=True)}"'
        f' data-template-version="{html.escape(str(pack.version), quote=True)}"'
        f' data-template-status="{html.escape(str(pack.status), quote=True)}"'
    )


def _single_slide_deck(deck: dict, slide: dict) -> dict:
    """Return a non-mutating deck view for page-scoped template validation.

    ``preview-slide`` is deliberately a one-page command.  A supported cover
    must remain previewable while another page is still mapped to an explicit
    ``unsupported`` role during Template Pack review; the full/final renderer
    continues to validate every authored slide.
    """
    scoped = dict(deck)
    scoped["slides"] = [slide]
    return scoped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("deck", help="path to deck.json")
    ap.add_argument("page", nargs="?", type=int, help="1-based page number")
    ap.add_argument("--key", help="slide key instead of page number")
    ap.add_argument("--out", default=None, help="output PNG path")
    ap.add_argument("--width", type=int, default=None,
                    help="screenshot viewport width (default: deck canvas width)")
    ap.add_argument("--height", type=int, default=None,
                    help="screenshot viewport height (default: deck canvas height)")
    ap.add_argument("--scale", type=int, default=1, help="device_scale_factor (2 for retina detail)")
    ap.add_argument("--wait", type=int, default=500, help="ms settle before shot")
    ap.add_argument("--no-gate", action="store_true",
                    help="skip the in-preview audit gate (screenshot only)")
    args = ap.parse_args()

    deck_path = os.path.abspath(args.deck)
    rundir = os.path.dirname(deck_path)
    d = json.load(open(deck_path, encoding="utf-8"))
    canvas = (d.get("deck") or {}).get("canvas") or {}
    design_w = int(canvas.get("width") or 1920)
    design_h = int(canvas.get("height") or 1080)
    viewport_w = args.width or design_w
    viewport_h = args.height or design_h
    slides = d["slides"]
    if args.key:
        matches = [i for i, s in enumerate(slides) if s.get("key") == args.key]
        if not matches:
            sys.exit(f"preview-slide: key '{args.key}' not found")
        idx = matches[0]
    elif args.page:
        idx = args.page - 1
    else:
        sys.exit("preview-slide: give a <page> number or --key")
    if not (0 <= idx < len(slides)):
        sys.exit(f"preview-slide: page out of range (1..{len(slides)})")

    s = slides[idx]
    key = s.get("key", "")
    layout = s.get("layout", "raw")
    title_style = (d.get("deck") or {}).get("title_style") or "left-double"

    # Use the production slide dispatcher instead of hand-wrapping data.html.
    # This makes schema layouts and Template Pack bindings preview exactly the
    # same DOM/CSS as a real render while keeping the one-page fast harness.
    renderer = _load_renderer()
    asset_path = pathlib.Path(os.path.relpath(ASSETS_DIR, rundir)).as_posix()
    try:
        rendered_slide = renderer.render_slide(
            s,
            idx,
            asset_path,
            deck_dir=pathlib.Path(rundir),
            deck_canvas=(design_w, design_h),
        )
        template_context = renderer.load_template_context(
            _single_slide_deck(d, s),
            deck_path=pathlib.Path(deck_path),
            output_dir=pathlib.Path(rundir),
            final=False,
        )
        if template_context is not None:
            rendered_slide = renderer.apply_template_binding(
                rendered_slide,
                template_context["bindings"].get(key),
                pack=template_context["pack"],
                web_prefix=template_context["web_prefix"],
            )
    except Exception as exc:
        sys.exit(f"preview-slide: render failed for key '{key}' layout='{layout}': {exc}")
    rendered_slide = rendered_slide.replace(
        'class="slide-frame"', 'class="slide-frame is-current"', 1)
    template_root_attrs = ""
    if template_context is not None:
        pack = template_context["pack"]
        template_root_attrs = _template_root_attrs(pack)

    harness = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<link rel="stylesheet" href="{asset_path}/feishu-deck.css">
<style>
  html,body{{margin:0;padding:0;background:#000;width:{viewport_w}px;height:{viewport_h}px;overflow:hidden}}
  .deck{{position:static!important;margin:0!important;padding:0!important;width:{viewport_w}px;height:{viewport_h}px;background:#000}}
  .slide-frame{{position:static!important;transform:none!important;opacity:1!important;left:0!important;top:0!important;
    margin:0!important;width:{viewport_w}px;height:{viewport_h}px;display:block!important;visibility:visible!important}}
  .slide-frame > .slide,.slide{{transform:none!important;width:{design_w}px!important;height:{design_h}px!important;
    position:relative!important;left:0!important;top:0!important}}
</style></head>
<body>
<div class="deck" data-title-style="{title_style}" data-deck-width="{design_w}"
  data-deck-height="{design_h}" data-deck-aspect="{design_w}:{design_h}"
  {template_root_attrs}
  style="--fs-deck-width:{design_w}px;--fs-deck-height:{design_h}px;--fs-deck-half-width:{design_w / 2:g}px;--fs-deck-half-height:{design_h / 2:g}px;--fs-deck-aspect:{design_w} / {design_h}">
{rendered_slide}
</div>
</body></html>"""

    prev = os.path.join(rundir, ".__preview_slide.html")
    with open(prev, "w", encoding="utf-8") as f:
        f.write(harness)

    out = args.out or os.path.join(rundir, f".__preview_p{idx+1}.png")
    t0 = time.time()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit("preview-slide: python playwright not installed")
    url = pathlib.Path(prev).as_uri()
    gate = None
    gate_err = None
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page(viewport={"width": viewport_w, "height": viewport_h},
                        device_scale_factor=args.scale)
        pg.goto(url)
        pg.wait_for_timeout(args.wait)
        pg.screenshot(path=out)
        if not args.no_gate and AUDITS_JS.exists():
            # contract: set window.__AUDIT_SCOPE__ (null = every .slide in DOM =
            # the one preview slide), then evaluate audits.js source; the IIFE
            # returns { engine, version, findings:[{rule, severity, message,...}] }
            try:
                pg.evaluate("window.__AUDIT_SCOPE__ = null")
                gate = pg.evaluate(AUDITS_JS.read_text(encoding="utf-8"))
            except Exception as e:  # a rule throwing must NOT kill the preview
                gate_err = str(e)
        b.close()
    try:
        os.remove(prev)
    except OSError:
        pass
    print(f"preview p{idx+1} ({key}) -> {out}  "
          f"[{design_w}x{design_h} · {time.time()-t0:.1f}s]")

    # ---- in-preview gate report (single-slide, static; framework/deck rules suppressed) ----
    if args.no_gate:
        return
    if gate_err:
        print(f"  gate: skipped (audit error: {gate_err[:90]})")
        return
    if gate is None:
        print(f"  gate: skipped (audits.js not found at {AUDITS_JS})")
        return
    findings = gate.get("findings", []) or []
    shown, suppressed = [], 0
    for f in findings:
        if _suppressed(f.get("rule", "")):
            suppressed += 1
        else:
            shown.append(f)
    errs = [f for f in shown if f.get("severity") == "error"]
    warns = [f for f in shown if f.get("severity") != "error"]
    tail = f"  (suppressed {suppressed} framework/preview-only)" if suppressed else ""
    if not shown:
        print(f"  gate: ✓ clean{tail}")
        return
    print(f"  gate: {len(errs)} error · {len(warns)} warn{tail}")
    for f in errs + warns:
        sev = "✗" if f.get("severity") == "error" else "!"
        msg = " ".join(str(f.get("message", "")).split())
        print(f"   {sev} [{f.get('rule')}] {msg[:120]}")


if __name__ == "__main__":
    main()
