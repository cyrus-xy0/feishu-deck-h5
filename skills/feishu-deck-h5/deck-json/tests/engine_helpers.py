"""Headless engine harness for unit tests (UNIFY-VALIDATE-ARCH step 4b).

Background — why this file exists
---------------------------------
Before step 4, ~90 unit assertions called the OLD Python audit functions
directly (`V.audit_font_sizes(html, iss)`), which parsed HTML/CSS *source* text
synchronously with no browser. Step 4 retired that dual registry: there is now a
SINGLE rule source, `assets/audits.js`, evaluated against the RENDERED DOM by
`run-audits.py`'s `run_unified_engine`. So a rule can no longer be invoked on a
bare source string — it must run inside a headless Chromium against a rendered
deck.

This helper is the minimal bridge that keeps those unit tests exercising the
*same rules* with *minimal churn*: give it an HTML fragment (or a list of slide
fragments, or a full document), and it wraps it into a minimal renderable deck,
runs the unified engine once, and returns that run's findings — optionally
filtered to one rule code. Tests that used to read `iss.errors` now read
`err_codes("R06", html)`; tests that read errors+warnings+soft read
`all_codes(...)`.

Key rendering facts the wrapper handles
---------------------------------------
* The audits.js driver iterates `document.querySelectorAll('.slide')` and runs
  NO rule when there are zero `.slide` elements. Many legacy fixtures are just a
  `<style>` block referencing `.slide` with no actual `.slide` node (the old
  Python audits parsed CSS text regardless of DOM). So when the fragment carries
  no `.slide`, we inject a minimal carrier `.slide` (inside the required
  `.deck > .slide-frame > .slide` shell) so the deck-level rules (R06/R10/R20/
  R-CSSVAR/R12/R-WHITE-TEXT/L*/…) actually run against the author CSS.
* The engine reads a sibling `deck.json` (R-LAYOUT-DEPRECATED source-of-truth for
  each slide's true authored `layout`) and injects framework CSS/JS. We render
  against a temp dir; absent deck.json is fine (rule skips).
* Chromium is REQUIRED (the rules are DOM/geometry). If Playwright/Chromium is
  unavailable the helper raises `EngineUnavailable`; tests skip via `skip_if_no_engine`.

This is a TEST harness, not a second rule path — it calls the very same
`run_unified_engine` that validate.py / check-only / render-deck use.
"""
from __future__ import annotations

import importlib.util
import json
import re
import tempfile
from pathlib import Path

ASSETS = Path(__file__).resolve().parents[2] / "assets"
_RUN_AUDITS = ASSETS / "run-audits.py"

# Load run-audits.py (hyphenated → importlib), the single shared engine entry.
_spec = importlib.util.spec_from_file_location("run_audits_for_tests", _RUN_AUDITS)
_ENGINE = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ENGINE)

EngineUnavailable = _ENGINE.EngineUnavailable

_HAS_SLIDE_RE = re.compile(r'class="(?:[^"]*\s)?slide(?:\s[^"]*)?"')
_HAS_DECK_RE = re.compile(r'class="(?:[^"]*\s)?deck(?:\s[^"]*)?"')


def _wrap(html_or_slides, *, raw=False) -> str:
    """Normalise the test input into ONE complete, renderable deck document.

    `raw=True` disables the carrier-`.slide` injection: the fragment is used
    EXACTLY as authored (only wrapped in <html><body> when it isn't already a
    full doc). Use it for whole-document / deck-level rules whose firing
    condition is the presence/absence of `.deck` / `.slide` itself (R-DOM,
    R-DOC-INTEGRITY, R-AUTOBALANCE-PRESENT) — there, injecting a carrier slide
    would CHANGE the very thing under test (a non-deck fragment must stay
    non-deck so the rule correctly skips it).

    Accepts:
      * a list/tuple of slide-frame fragments (joined) — e.g. richness/echo tests
        that pass `slides`;
      * a string that is already a full <html>…</html> doc (used verbatim, but a
        carrier .slide is injected if it has none — see module docstring);
      * a string fragment (wrapped in the .deck shell, carrier added if needed).

    Wrapping rules (so we never CHANGE the fragment's deck-ness — critical for
    rules like R-AUTOBALANCE-PRESENT / R-DOC-INTEGRITY whose firing condition IS
    `.deck` presence / `data-no-autobalance` / non-deck-skip):
      * fragment already contains a `.deck`  → use it verbatim (NO extra wrap, NO
        carrier — a non-deck `.replica` fragment stays non-deck; a
        `data-no-autobalance` deck keeps its attribute on the real deck node);
      * else, fragment has `.slide` markup    → wrap in a plain `.deck`;
      * else (just a <style> referencing .slide / .card …) → wrap in `.deck >
        .slide-frame > .slide` carrier so CSS-source deck-level rules have a
        driver slide.
    """
    if isinstance(html_or_slides, (list, tuple)):
        body_inner = "".join(html_or_slides)
        head = ""
        joined = body_inner
        has_slide = any(_HAS_SLIDE_RE.search(s) for s in html_or_slides)
        has_deck = bool(_HAS_DECK_RE.search(joined))
        full = False
    else:
        s = html_or_slides
        full = "<html" in s.lower()
        has_slide = bool(_HAS_SLIDE_RE.search(s))
        has_deck = bool(_HAS_DECK_RE.search(s))
        if full:
            # Already a full doc. If it lacks BOTH a .deck and a .slide carrier,
            # inject one just before </body> so deck-level CSS rules have a driver
            # slide. (If it already declares a .deck or .slide, leave it exactly
            # as authored — the fragment's own deck-ness must be preserved.)
            if not has_slide and not has_deck and not raw:
                carrier = (
                    '<div class="deck"><div class="slide-frame">'
                    '<div class="slide" data-layout="content" '
                    'data-screen-label="x" data-slide-key="__carrier__">'
                    '</div></div></div>'
                )
                m = re.search(r"</body>", s, re.I)
                if m:
                    return s[: m.start()] + carrier + s[m.start():]
                return s + carrier
            return s
        body_inner = s
        head = ""

    # Build the body. Preserve the fragment's deck-ness exactly.
    if has_deck or raw:
        deck = body_inner                       # verbatim — already deck-shaped / raw
    elif has_slide:
        deck = '<div class="deck">' + body_inner + "</div>"
    else:
        deck = (
            '<div class="deck"><div class="slide-frame">'
            '<div class="slide" data-layout="content" '
            'data-screen-label="x" data-slide-key="__carrier__">'
            + body_inner
            + "</div></div></div>"
        )
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        + head
        + "</head><body>"
        + deck
        + "</body></html>"
    )


def run(html_or_slides, *, scope=None, deck_json=None, settle_ms=200, raw=False,
        verbatim=False):
    """Render the wrapped fragment + run the unified engine; return its findings
    list (each {rule, severity, slide_idx, message, …}).

    `deck_json` (a dict) is written next to index.html so deck.json-sourced rules
    (R-LAYOUT-DEPRECATED) see it. `raw=True` uses the fragment verbatim inside an
    <html><body> shell (see _wrap). `verbatim=True` writes the EXACT bytes to
    index.html with NO wrapping at all — required for the runner SOURCE-BYTE rule
    R-DOC-INTEGRITY, whose whole point is detecting truncated tags / a missing
    </body></html> in the raw file (any wrapping would mask the truncation).
    Raises EngineUnavailable if Chromium can't run."""
    doc = (html_or_slides if verbatim else _wrap(html_or_slides, raw=raw))
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        idx = d / "index.html"
        idx.write_text(doc, encoding="utf-8")
        if deck_json is not None:
            (d / "deck.json").write_text(
                json.dumps(deck_json, ensure_ascii=False), encoding="utf-8")
        result = _ENGINE.run_unified_engine(
            idx, scope, settle_ms=settle_ms, dom_rules=True)
    return result.get("findings", [])


def _codes_by_sev(findings, rule=None):
    err, warn, soft = [], [], []
    for f in findings:
        if rule is not None and f.get("rule") != rule:
            continue
        sev = f.get("severity")
        code = f.get("rule", "?")
        if sev == "error":
            err.append(code)
        elif sev == "warn_soft":
            soft.append(code)
        else:
            warn.append(code)
    return err, warn, soft


def err_codes(rule, html_or_slides, **kw):
    """Error-severity rule codes from one engine run (optionally filtered to
    `rule`; pass rule=None for ALL codes). Mirrors the legacy `_err_codes`."""
    err, _, _ = _codes_by_sev(run(html_or_slides, **kw), rule)
    return err


def all_codes(rule, html_or_slides, **kw):
    """error + warn + warn_soft codes (mirrors the legacy `_all_codes`)."""
    err, warn, soft = _codes_by_sev(run(html_or_slides, **kw), rule)
    return err + warn + soft


def soft_codes(rule, html_or_slides, **kw):
    """warn_soft codes only (mirrors `_soft_codes`)."""
    _, _, soft = _codes_by_sev(run(html_or_slides, **kw), rule)
    return soft


def buckets(html_or_slides, *, rule=None, **kw):
    """One engine run → a dict of severity bucket → list of rule codes, mapping
    the engine's severity vocab onto the historical Issues bucket names so tests
    that asserted on `iss.errors / iss.warnings / iss.soft_warnings` still read
    naturally:  error→'errors', warn→'warnings', warn_soft→'soft_warnings'.
    Optionally filter to a single `rule`."""
    err, warn, soft = _codes_by_sev(run(html_or_slides, **kw), rule)
    return {"errors": err, "warnings": warn, "soft_warnings": soft}


def messages(rule, html_or_slides, **kw):
    """Full messages for `rule` (None = all) — for tests asserting on text."""
    return [f.get("message", "") for f in run(html_or_slides, **kw)
            if rule is None or f.get("rule") == rule]


def findings_for(rule, html_or_slides, *, kind=None, **kw):
    """All engine findings for `rule` (optionally filtered to a `kind` payload
    field), preserving full payload (kind/axis/slack/selector/…). The drop-in
    replacement for the old `rep.get("<bucket>")` reads in the test_vis_*.py
    files — the unified engine carries the same payload fields on each finding."""
    out = [f for f in run(html_or_slides, **kw) if f.get("rule") == rule]
    if kind is not None:
        out = [f for f in out if f.get("kind") == kind]
    return out


_AUDITS_JS = ASSETS / "audits.js"


def audits_js_text():
    """Source text of the unified engine (audits.js) — for the wiring/parity
    tests that statically assert a rule is declared in the single rule source."""
    return _AUDITS_JS.read_text(encoding="utf-8")


def rule_in_engine(rule):
    """True if `rule` is emitted by the unified engine (audits.js `rule:` literal
    or a runner byte-rule). The single-source replacement for the old
    "bucket declared in visual-audit.js AND mapped in validate.py" wiring check."""
    js = audits_js_text()
    if re.search(r"\brule:\s*['\"]" + re.escape(rule) + r"['\"]", js):
        return True
    runner = (ASSETS / "run-audits.py").read_text(encoding="utf-8")
    return ('"' + rule + '"') in runner


def skip_if_no_engine():
    """Probe Chromium once; pytest.skip if unavailable. Call at the top of a
    test (or use the `engine` fixture) so a no-Chromium CI skips rather than
    errors — same graceful-degrade contract as the sibling test_vis_*.py."""
    try:
        run('<div class="slide" data-layout="content"></div>')
    except EngineUnavailable as e:  # noqa: F841
        import pytest
        pytest.skip(f"unified engine unavailable: {e}")
