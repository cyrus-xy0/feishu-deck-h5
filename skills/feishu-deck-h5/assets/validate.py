#!/usr/bin/env python3
"""
feishu-deck-h5  ·  programmatic self-check

Runs the SKILL.md self-check items that can be enforced by static analysis.
This is a HARD GATE: a deck is not "done" until this script exits 0.

Usage:
    python3 assets/validate.py path/to/deck.html [--strict]

    --strict  also fails on warnings (mono-logo usage, large unknown hex
              values inside slide markup, etc.)

Exit codes:
    0   all checks pass
    1   one or more violations
    2   internal error (cannot parse file)
"""

from __future__ import annotations
import functools, re, sys, argparse
from collections import Counter
from pathlib import Path

# ===========================================================================
#  VALIDATOR MAP — UNIFY-VALIDATE-ARCH step 4: the rules live in ONE source.
#  Find a rule fast: rule code → its evaluate() in `assets/audits.js`
#  (`grep "id: 'R06'"`). validate.py is now just the CLI / OUTPUT-CONTRACT
#  adapter (parse flags → call the engine → map findings → exit code); it holds
#  NO rule logic of its own.
#
#    · DOM / geometry / structure / CSS-source rules (R02/R05/R06/R07/R10/R12/
#      R13/R20/R36/R38/R47/R48/R49/R56/R-DOM/R-KEY/R-LANG/R-WHITE-TEXT/
#      R-HIERARCHY/R-ECHO/R-BULLET-DASH/R-CSSVAR/R-EMPTY-HEADER-ZONE/L1/L2/L4/
#      UI1/R29-32 and every R-VIS-* / R-OVERFLOW / R-OVERLAP / R-FOCAL-CHECK …)
#      → `assets/audits.js`, evaluated against the RENDERED DOM in headless
#      Chromium by `run-audits.py`'s run_unified_engine.
#    · runner SOURCE-BYTE / file-system rules a browser can't see faithfully
#      (R-DOC-INTEGRITY truncation, R-SELF-CONTAINED head/deck <style> leak,
#      perf P50-P55) → `assets/run-audits.py`.
#
#  The old STATIC_AUDITS / _validate_audits.py / visual-audit.js dual registries
#  are retired. See UNIFY-VALIDATE-ARCH-2026-06-03.md.
# ===========================================================================

# ---------------------------------------------------------------------------
#  F-10 module split · re-export the shared KERNEL surface
# ---------------------------------------------------------------------------
# validate.py stays the single import target (`import validate as V`) and the
# script entry. The shared kernel lives in _validate_common; re-export every
# public name (and the underscore-prefixed kernel symbols star-import skips) so
# downstream consumers (check-only, render-deck, tests) keep their V.X surface.
#
# UNIFY-VALIDATE-ARCH step 4: the OLD audit registry module `_validate_audits`
# is RETIRED — its rules now live in the unified engine (audits.js + the runner
# byte/source checks). validate.py no longer imports it; the only rule path is
# the engine (see run_unified_audits below).
from _validate_common import *
from _validate_common import (
    _FS_TOKEN_FALLBACK, _load_fs_tokens, _FS_TOKENS,
    _SLIDE_FRAME_OPEN_RE,
    _STYLE_BLOCK_RE, _iter_style_blocks,
    _RULE_WITH_COMMENTS_RE,
    _DECK_VW, _DECK_VH, _MQ_FEATURE_RE, _media_query_matches,
    _strip_nested_at_rules,
    _BOX_SHADOW_GLOW_RING_RE, _BOX_SHADOW_INSET_RE,
    _BODY_CLASS_RE, _CHROME_CLASS_RE,
    _CJK_RE, _HTML_LEAF_TAGS, _HTML_VOID_TAGS, _HTML_SKIP_CONTAINERS,
    _walk_text_leaves,
    _CHART_SCAFFOLD_CLASSES, _is_chart_scaffold_class,
    _LAYOUT_ONLY_PARENT_TAGS,
)

# ---------------------------------------------------------------------------
#  UNIFY-VALIDATE-ARCH (2026-06-03/04) · single rule source = the unified engine
# ---------------------------------------------------------------------------
# validate.py no longer runs its own audit registries. ALL rule findings are
# sourced from the unified engine (`assets/audits.js`, evaluated against the
# RENDERED DOM by `run-audits.py`'s shared `run_unified_engine`) + a handful of
# source-byte / file-system checks that live in the runner (R-DOC-INTEGRITY /
# R-SELF-CONTAINED / perf — things a browser can't see faithfully). One rule
# source, one language; the old STATIC_AUDITS / _validate_audits.py /
# visual-audit.js dual registries are retired (step 4).
#
# validate.py's job is now purely the CLI / OUTPUT-CONTRACT adapter: parse flags,
# call the engine, map its findings into the historical {code, severity, msg,
# slide, selector_hint} shape (errors / warnings split, --strict promotion,
# --json, --slide, exit codes) that render-deck / delivery / the write-hook /
# the test suite depend on.
#
# DEPENDENCY: the engine is DOM/browser-based → validate.py now needs playwright
# for its DEFAULT (full) path. `--no-visual` runs the no-browser checks: the
# byte/source rules (R-DOC-INTEGRITY / R-DOM over-close / R-SELF-CONTAINED / perf)
# PLUS the restored no-browser SOURCE-TEXT rules (R-KEY / R-ESC-HTML / R02 / R07 /
# R05) — real static enforcement without Chromium. It is still a PARTIAL check
# (geometry / pure DOM-text rules don't run), documented as such, never a silent
# green.
import importlib.util as _importlib_util

_RUN_AUDITS_PATH = Path(__file__).resolve().parent / 'run-audits.py'
_ENGINE = None  # lazily-loaded module handle (run-audits.py has a hyphen)


def _engine():
    """Lazily import run-audits.py (hyphenated → importlib). Cached. Returns the
    module exposing run_unified_engine + EngineUnavailable. Lazy so that merely
    importing validate (e.g. check-only's source scan, the surface test) never
    forces the engine module to load."""
    global _ENGINE
    if _ENGINE is None:
        spec = _importlib_util.spec_from_file_location(
            'run_audits', _RUN_AUDITS_PATH)
        mod = _importlib_util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _ENGINE = mod
    return _ENGINE


_CHECK_DIST_PATH = Path(__file__).resolve().parent / 'check-distribution.py'
_DISTRIBUTION = None  # lazily-loaded module handle (check-distribution.py has a hyphen)


def _distribution():
    """Lazily import check-distribution.py (hyphenated → importlib). Cached.
    Exposes MEASURE_JS + signals_for so --with-distribution can fold the
    layout-distribution geometry audit into the visual engine's SINGLE browser
    pass (F-290) instead of paying a second Chromium launch + full reload."""
    global _DISTRIBUTION
    if _DISTRIBUTION is None:
        spec = _importlib_util.spec_from_file_location(
            'check_distribution', _CHECK_DIST_PATH)
        mod = _importlib_util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _DISTRIBUTION = mod
    return _DISTRIBUTION


# Map the engine's severity vocabulary → the Issues buckets. The engine emits
# 'error' / 'warn' / 'warn_soft' (1:1 with iss.err / iss.warn / iss.warn_soft).
_SEV_TO_BUCKET = {
    'error': 'err',
    'warn': 'warn',
    'warn_soft': 'warn_soft',
}


def engine_findings_to_issues(findings, iss):
    """Pour unified-engine findings (each {rule, severity, slide_idx, message,
    ...}) into the Issues buckets, preserving the (code, msg) tuple shape every
    downstream consumer expects. Unknown severities default to a warning (never
    silently dropped)."""
    for f in findings:
        code = f.get('rule', '?')
        msg = f.get('message', '')
        bucket = _SEV_TO_BUCKET.get(f.get('severity'), 'warn')
        getattr(iss, bucket)(code, msg)


def run_unified_audits(path, iss, *, dom_rules=True, scope=None,
                       want_screenshots=False, with_distribution=False):
    """Run the unified engine against the rendered deck and fold its findings
    into `iss`. This REPLACES the old run_static_audits + run_visual_audits.

    dom_rules=True  → full engine: render in headless Chromium + audits.js
                      (geometry / DOM-text / structure rules) PLUS runner
                      byte/source rules. Requires playwright.
    dom_rules=False → `--no-visual`: NO browser. Runs the runner byte/source
                      rules (R-DOC-INTEGRITY / R-DOM over-close / R-SELF-CONTAINED
                      / perf) PLUS the no-browser source-text rules (R-KEY /
                      R-ESC-HTML / R02 / R07 / R05). Geometry / pure DOM-text
                      rules (R-VIS-*, R06/R20/R10/R-OVERFLOW/…) do NOT run —
                      documented partial check.

    Mirrors the old run_visual_audits failure semantics: an INABILITY to render
    (playwright missing / Chromium launch flake / nav timeout) is an environment
    glitch, NOT a deck defect, so it degrades to a single soft advisory rather
    than blocking a good deck under --strict. A real rule VIOLATION found by the
    engine still errs/warns normally."""
    eng = _engine()
    # F-290: fold the layout-distribution geometry audit into THIS single browser
    # pass — pass its MEASURE_JS as an extra eval the engine runs on the same
    # settled present-mode page (saves a second Chromium launch + full reload).
    _extra = None
    if with_distribution and dom_rules:
        try:
            _extra = {'distribution': _distribution().MEASURE_JS}
        except Exception:
            _extra = None    # distribution module unavailable → just skip the fold
    try:
        result = eng.run_unified_engine(
            path, scope, dom_rules=dom_rules, extra_evals=_extra)
    except eng.EngineUnavailable as e:
        if not dom_rules:
            # byte-only path should never raise for env reasons (no browser),
            # but be defensive — surface as a soft advisory, never block.
            iss.warn_soft('R-VISUAL',
                f'byte/source checks could not run ({type(e).__name__}: {e}).')
            return
        # Full path needs a browser. Missing playwright / Chromium flake →
        # degrade to static-only-ish: still run the byte/source rules (no
        # browser) so R-DOC-INTEGRITY etc. are never skipped, then advise.
        try:
            result = eng.run_unified_engine(path, scope, dom_rules=False)
            engine_findings_to_issues(result.get('findings', []), iss)
        except Exception:
            pass
        iss.warn_soft('R-VISUAL',
            f'visual/DOM checks could not run ({type(e).__name__}: {e}). '
            'Install with `pip install playwright && python -m playwright '
            'install chromium`, or open the deck in a browser to verify. '
            'Byte/source rules (R-DOC-INTEGRITY / R-SELF-CONTAINED / perf) '
            'still ran.')
        return
    engine_findings_to_issues(result.get('findings', []), iss)
    if want_screenshots and dom_rules:
        _archive_screenshots(path)
    # F-290: enrich the raw distribution measurement with signals_for — the SAME
    # shape the standalone check-distribution.py --json emits — and hand it back so
    # the caller can surface it under a top-level "distribution" key.
    _dist_raw = (result.get('extra') or {}).get('distribution')
    if _dist_raw:
        try:
            cd = _distribution()
            return [{**s, 'signals': cd.signals_for(s)} for s in _dist_raw]
        except Exception:
            return None
    return None


def _archive_screenshots(html_path):
    """Optional PNG archival of each slide (preserves the legacy --screenshots
    flag). Independent of rule sourcing — a separate lightweight Chromium pass.
    Degrades silently if playwright is unavailable (the engine path already
    advised)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return
    shots_dir = html_path.parent / (html_path.stem + '-previews')
    try:
        shots_dir.mkdir(parents=True, exist_ok=True)
        url = html_path.resolve().as_uri()
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_context(
                viewport={'width': 1920, 'height': 1080}).new_page()
            page.goto(url, wait_until='domcontentloaded', timeout=60_000)
            # Bounded settle (B/2026-06-06): an embedded live demo can keep the
            # 'load' event pending ~30s, taxing the whole visual audit. Prefer full
            # load for fidelity but cap it, then await fonts so CJK text doesn't
            # measure/shoot in a fallback face. This deck: ~31s (load) → ~1-5s.
            try:
                page.wait_for_load_state('load', timeout=4_000)
            except Exception:
                pass
            try:
                page.evaluate("() => Promise.race([(document.fonts && document.fonts.ready) || Promise.resolve(), new Promise(r => setTimeout(r, 2000))])")
            except Exception:
                pass
            try:
                page.wait_for_function(
                    "() => document.querySelector('.deck[data-js-ready] "
                    ".slide-frame.is-current') !== null", timeout=3000)
            except Exception:
                pass
            slide_count = page.evaluate(
                "() => document.querySelectorAll('.slide').length")
            for i in range(1, slide_count + 1):
                page.evaluate(f"window.location.hash = '#{i}'")
                page.wait_for_timeout(350)
                page.screenshot(path=str(shots_dir / f's{i:02d}.png'),
                                full_page=False)
            browser.close()
    except Exception:
        pass  # archival is best-effort; never break validation


# ---------------------------------------------------------------------------
#  F-283 step 1 · CJK font-fingerprint (DIAGNOSTIC, not a rule)
# ---------------------------------------------------------------------------
# The framework's CJK face (方正兰亭黑 Pro GB18030) is a LOCALLY-LICENSED font
# with NO @font-face / NO bundling. Consequence: every visual-audit geometry
# number (overflow / balance / title-position) is measured against THIS
# machine's glyph metrics. The same deck on a host WITHOUT that font (e.g. a
# cloud Linux box that falls back to Noto / a tofu box) measures DIFFERENTLY —
# a silent, physical source of "passes here, fails there". This probe makes the
# actually-rendered CJK face VISIBLE so a cross-machine verdict carries its own
# font fingerprint. It changes NO gate and emits NO finding — pure metadata for
# the --json payload. (Full subsetting / @font-face packaging is F-283 B, TBD.)

# Sentinel returned when the probe cannot run (no Chromium) — keeps the field a
# string for downstream consumers rather than silently absent.
_CJK_FONT_UNKNOWN = 'unknown(no-engine)'

# In-page measureText fingerprint. NOTE on method: the classic width-diff trick
# must use a LATIN probe string, NOT CJK. CJK ideographs are uniformly full-width
# (em-square), so measureText() reports an IDENTICAL advance for every face —
# even a bogus family or a plain generic — and cannot discriminate. The Latin
# glyphs inside each CJK-stack family (方正兰亭黑 / PingFang / Noto / YaHei all
# ship Latin) DO have face-specific advances, so we measure those. For each
# candidate family we compare "<family>, <baseline>" against the bare baseline
# over THREE generics (monospace / sans-serif / serif); the family is "available"
# when at least one comparison DIFFERS — i.e. the named family resolved and its
# (Latin) metrics replaced the generic's rather than falling through. We walk the
# deck's real computed CJK font-family list (read off a rendered element, else the
# --fs-font-cjk custom property) IN ORDER and return the first available name —
# the face the browser actually paints, the one ALL geometry was measured against.
# (document.fonts.check() is useless here: it returns true even for a nonexistent
# family / a not-installed name, because it reports loaded @font-face faces, not
# which locally-installed family wins the cascade. Verified — so we measure.)
_CJK_FINGERPRINT_JS = r"""
() => {
  // Latin probe — wide spread of glyph widths so face differences surface.
  const PROBE = 'ABCWMlijgpqy 0123456789 ABCWMlijgpqy ABCWMlijgpqy';
  const BASELINES = ['monospace', 'sans-serif', 'serif'];
  const PX = '64px';
  const cv = document.createElement('canvas');
  const ctx = cv.getContext('2d');
  const widthOf = (family) => {
    ctx.font = PX + ' ' + family;
    return ctx.measureText(PROBE).width;
  };
  // Quote a family token for the canvas font shorthand unless it's already
  // quoted or a bare CSS keyword (generic family / system-ui).
  const KEYWORDS = new Set(['system-ui','sans-serif','serif','monospace',
                            'ui-sans-serif','ui-serif','ui-monospace',
                            'cursive','fantasy','-apple-system']);
  const q = (name) => {
    name = name.trim().replace(/^['"]|['"]$/g, '');
    if (!name) return null;
    if (KEYWORDS.has(name.toLowerCase())) return name;
    return '"' + name.replace(/"/g, '\\"') + '"';
  };
  const isAvailable = (name) => {
    const fam = q(name);
    if (!fam) return false;
    if (KEYWORDS.has(name.trim().toLowerCase())) return true;  // generic always 'resolves'
    return BASELINES.some((base) => {
      const baseW = widthOf(base);
      const testW = widthOf(fam + ', ' + base);
      return Math.abs(testW - baseW) > 0.5;
    });
  };
  // Read the real cascade the deck uses: prefer a rendered CJK element's
  // computed font-family, else the framework custom property, else the literal.
  const sampleEl = document.querySelector(
    '.title-zh, .slide .title, .slide h1, .slide h2, .slide') || document.body;
  let famList = getComputedStyle(sampleEl).fontFamily || '';
  if (!famList || !/[一-鿿]/.test(famList)) {
    const v = getComputedStyle(document.documentElement)
                .getPropertyValue('--fs-font-cjk');
    if (v && v.trim()) famList = v.trim();
  }
  // Split on top-level commas (font-family names have no nested commas).
  const families = famList.split(',').map((s) => s.trim()).filter(Boolean);
  let effective = null;
  for (const name of families) {
    if (isAvailable(name)) { effective = name.replace(/^['"]|['"]$/g, ''); break; }
  }
  // Last resort: report whatever the cascade head was, marked as a guess.
  if (!effective && families.length) {
    effective = families[families.length - 1].replace(/^['"]|['"]$/g, '');
  }
  return {
    effective_cjk_font: effective || null,
    cjk_font_stack: families,
  };
}
"""


# ---------------------------------------------------------------------------
#  PERF-A (AUDIT-2026-06-17) · per-host memoize of the CJK font probe.
#  probe_effective_cjk_font() launches a whole headless Chromium (~0.4s) on
#  EVERY `validate.py --visual --json` call (the default advisory 6b pass + every
#  --json gate), for a result that is a PURE FUNCTION of (a) the framework CSS
#  `--fs-font-cjk` stack and (b) which of those faces are installed on THIS host
#  — identical for every deck and every render until one of those changes. We
#  memoize it keyed on BOTH, so editing feishu-deck.css OR installing/removing a
#  font forces a fresh probe (otherwise the cache would lie in exactly the
#  scenario the probe exists to detect). The probe is metadata, NEVER a gate
#  (see docstring), so the cache can never flip a verdict — it only removes a
#  redundant browser launch. Fail-safe: any cache problem → live probe.
#  Set DECK_NO_FONT_PROBE_CACHE=1 to bypass entirely (used by the parity test).
# ---------------------------------------------------------------------------
_CJK_PROBE_CACHE_FILE = Path.home() / '.cache' / 'feishu-deck-h5' / 'cjk-font-probe.json'
_FONT_EXT = ('.ttf', '.otf', '.ttc', '.otc', '.dfont', '.woff', '.woff2')


def _host_font_fingerprint():
    """Cheap, Chromium-free signature of the host's installed fonts. Changes when
    a font is installed / removed / updated, so a cached probe result keyed on it
    is invalidated in exactly the scenario the probe exists to detect. Returns a
    short hex digest, or None when fonts can't be enumerated (→ caller must NOT
    use the cache and must fall through to a live probe). Never raises."""
    import os, platform, hashlib
    try:
        home = Path.home()
        sysname = platform.system()
        if sysname == 'Darwin':
            dirs = [Path('/System/Library/Fonts'),
                    Path('/System/Library/Fonts/Supplemental'),
                    Path('/Library/Fonts'), home / 'Library' / 'Fonts']
        elif sysname == 'Linux':
            dirs = [Path('/usr/share/fonts'), Path('/usr/local/share/fonts'),
                    home / '.fonts', home / '.local' / 'share' / 'fonts']
        elif sysname == 'Windows':
            dirs = [Path(os.environ.get('WINDIR', r'C:\Windows')) / 'Fonts',
                    home / 'AppData' / 'Local' / 'Microsoft' / 'Windows' / 'Fonts']
        else:
            return None
        h = hashlib.sha256()
        seen = False
        for d in dirs:
            try:
                if not d.is_dir():
                    continue
                rows = []
                for root, _subdirs, files in os.walk(d):
                    for f in files:
                        if f.lower().endswith(_FONT_EXT):
                            try:
                                st = os.stat(os.path.join(root, f))
                                rows.append(f'{root}/{f}:{int(st.st_mtime)}:{st.st_size}')
                            except OSError:
                                rows.append(f'{root}/{f}')
                rows.sort()
                for r in rows:
                    h.update(r.encode('utf-8', 'replace'))
                    h.update(b'\n')
                if rows:
                    seen = True
            except OSError:
                continue
        return h.hexdigest()[:32] if seen else None
    except Exception:
        return None


def _cjk_probe_cache_key(css_text):
    """sha256(framework CSS bytes + host font fingerprint), or None when the host
    fonts can't be fingerprinted (→ no caching: live probe every time)."""
    import hashlib
    fp = _host_font_fingerprint()
    if not fp:
        return None
    h = hashlib.sha256()
    h.update(css_text.encode('utf-8', 'replace'))
    h.update(b'\x00')
    h.update(fp.encode('ascii'))
    return h.hexdigest()


def _cjk_probe_cache_get(key):
    import json
    try:
        data = json.loads(_CJK_PROBE_CACHE_FILE.read_text(encoding='utf-8'))
        v = data.get(key)
        return v if isinstance(v, str) and v else None
    except (OSError, ValueError, TypeError):
        return None


def _cjk_probe_cache_put(key, family):
    import json
    try:
        _CJK_PROBE_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = json.loads(_CJK_PROBE_CACHE_FILE.read_text(encoding='utf-8'))
            if not isinstance(data, dict):
                data = {}
        except (OSError, ValueError, TypeError):
            data = {}
        data[key] = family
        if len(data) > 32:                       # keep the cache file bounded
            data = dict(list(data.items())[-32:])
        tmp = _CJK_PROBE_CACHE_FILE.with_name(_CJK_PROBE_CACHE_FILE.name + '.tmp')
        tmp.write_text(json.dumps(data), encoding='utf-8')
        tmp.replace(_CJK_PROBE_CACHE_FILE)
    except OSError:
        pass


def probe_effective_cjk_font(html_path):
    """F-283 step 1 · return the CJK font-family the browser ACTUALLY paints for
    this deck on THIS machine (a fingerprint for cross-machine verdict diffing).

    Renders a minimal synthetic page (framework CSS only — F-293) in a short
    headless Chromium pass, awaits fonts, then runs an in-page measureText
    fingerprint that walks the deck's computed CJK font-family list and returns
    the first family that actually resolves on this host.

    PERF-A (AUDIT-2026-06-17): the result is a pure function of the framework CSS
    + host fonts, so it is memoized per-host (see _cjk_probe_cache_*) — a cache
    hit returns WITHOUT launching Chromium. The probe is metadata, never a gate,
    so the cache can never change a verdict.

    Returns the family name (str), or `_CJK_FONT_UNKNOWN` when no engine is
    available, or None if the page exposes no CJK cascade. NEVER raises — a probe
    failure must not break validation (it is metadata, not a gate)."""
    import os
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return _CJK_FONT_UNKNOWN
    # The probe depends only on the framework CSS + host fonts (F-293), so read
    # the CSS once: it feeds both the cache key and the synthetic probe page.
    _css_path = Path(__file__).resolve().parent / 'feishu-deck.css'
    try:
        _fw_css = _css_path.read_text(encoding='utf-8')
    except OSError:
        _fw_css = ':root{--fs-font-cjk:"方正兰亭黑 Pro GB18030",sans-serif}'
    _use_cache = not os.environ.get('DECK_NO_FONT_PROBE_CACHE')
    _key = _cjk_probe_cache_key(_fw_css) if _use_cache else None
    if _key is not None:
        _hit = _cjk_probe_cache_get(_key)
        if _hit is not None:
            return _hit                          # cache hit → NO Chromium launch
    try:
        # F-293 perf: fingerprint a MINIMAL synthetic page (framework CSS + one
        # CJK element), NOT the real deck — the result is identical to a tiny page
        # and ~0.3s regardless of deck size. (html_path kept for signature/back-
        # compat; no longer loaded.)
        _probe_html = (
            '<!doctype html><html><head><meta charset="utf-8"><style>'
            + _fw_css
            + '</style></head><body style="font-family:var(--fs-font-cjk)">'
            '<div class="title-zh">中文字体指纹 ABCabc 0123</div></body></html>')
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                page = browser.new_context(
                    viewport={'width': 1920, 'height': 1080}).new_page()
                page.set_content(_probe_html, wait_until='domcontentloaded',
                                 timeout=30_000)
                # Await fonts (bounded) so we fingerprint the settled face, not a
                # mid-swap fallback — same pattern as _archive_screenshots.
                try:
                    page.evaluate(
                        "() => Promise.race(["
                        "(document.fonts && document.fonts.ready) || Promise.resolve(),"
                        " new Promise(r => setTimeout(r, 2000))])")
                except Exception:
                    pass
                result = page.evaluate(_CJK_FINGERPRINT_JS)
            finally:
                browser.close()
        family = result.get('effective_cjk_font') if isinstance(result, dict) else None
        if family and _key is not None:
            _cjk_probe_cache_put(_key, family)   # only cache concrete results
        return family
    except Exception:
        # Chromium launch flake / nav timeout / eval error → environment glitch,
        # not a deck defect. Mark unknown rather than crashing validate.
        return _CJK_FONT_UNKNOWN


def inline_linked(html_text, base_dir):
    """Inline <link rel=stylesheet> / <script src> into the HTML so audits can
    see framework CSS/JS content. External (http/https/data:) refs and missing
    files are left untouched. Shared by main() here and check-only.py — was
    copy-pasted in both, unified per F-14."""
    def repl_link(m):
        tag = m.group(0)
        # Order-independent: match ANY <link> tag, inline only if it's a local
        # stylesheet. The old `rel="stylesheet" … href=` regex missed
        # `<link href="…" rel="stylesheet">`, so that framework CSS was
        # invisible to the audits (they then under-reported).
        if 'rel="stylesheet"' not in tag:
            return tag
        hm = re.search(r'href="([^"]+)"', tag)
        if not hm:
            return tag
        href = hm.group(1)
        if href.startswith(('http:', 'https:', 'data:')): return tag
        target = (base_dir / href).resolve()
        if not target.is_file(): return tag
        return ('<style data-source="framework">'
                + target.read_text(encoding='utf-8')
                + '</style>')
    html_text = re.sub(r'<link\b[^>]*>', repl_link, html_text)
    def repl_script(m):
        src = m.group(1)
        if src.startswith(('http:', 'https:', 'data:')): return m.group(0)
        target = (base_dir / src).resolve()
        if not target.is_file(): return m.group(0)
        return ('<script data-source="framework">'
                + target.read_text(encoding='utf-8')
                + '</script>')
    html_text = re.sub(
        r'<script[^>]*src="([^"]+)"[^>]*>\s*</script>',
        repl_script, html_text)
    return html_text




def filter_issues_to_slide(slide_arg, slides, iss):
    """F-254 · diagnostic single-slide filter.

    Mutate `iss` in place, keeping only findings that pertain to ONE slide so a
    one-page edit isn't buried in deck-wide pre-existing noise. `slide_arg` is a
    data-slide-key ("cover") or a 1-based ordinal ("30" / "#30"). A finding
    matches when its message contains `data-slide-key="<key>"` OR `slide <N>`
    (the two conventions every audit emits). Returns a short human note.
    """
    idx_to_key = {}
    for i, s in enumerate(slides, 1):
        m = re.search(r'data-slide-key="([^"]+)"', s)
        if m:
            idx_to_key[i] = m.group(1)
    key_to_idx = {v: k for k, v in idx_to_key.items()}

    arg = slide_arg.strip().lstrip('#')
    if arg.isdigit():
        ordinal = int(arg)
        key = idx_to_key.get(ordinal)
    else:
        key = arg
        ordinal = key_to_idx.get(key)

    known = (key in key_to_idx) or (ordinal in idx_to_key)

    def _match(msg):
        if key and f'data-slide-key="{key}"' in msg:
            return True
        if ordinal and re.search(rf'\bslide {ordinal}\b', msg):
            return True
        return False

    iss.errors        = [e for e in iss.errors        if _match(e[1])]
    iss.warnings      = [w for w in iss.warnings      if _match(w[1])]
    iss.soft_warnings = [w for w in iss.soft_warnings if _match(w[1])]

    label = (f'#{ordinal} {key}' if (ordinal and key)
             else f'#{ordinal}' if ordinal else (key or arg))
    if not known:
        return (f'⚠ slide "{slide_arg}" not found among {len(slides)} slides — '
                'matched by substring anyway (0 findings likely means a typo).')
    return f'filtered to slide {label}'


def main():
    p = argparse.ArgumentParser(description='feishu-deck-h5 self-check')
    p.add_argument('html', help='Path to the assembled deck HTML file')
    p.add_argument('--strict', action='store_true',
                   help='Promote warnings to errors')
    p.add_argument('--visual', action=argparse.BooleanOptionalAction,
                   default=True,
                   help='Run the Playwright-based renderer-side audits: '
                        'R-OVERFLOW (canvas overflow — catches the P05-style '
                        '"column bleeds into legend" bug that static CSS '
                        'analysis cannot), R-VIS-TIER (computed fontSize on '
                        '4-tier ladder), R-VIS-HIER (meta ≤ body in each '
                        'card). '
                        'DEFAULT: on (~1-5s extra per deck). Use --no-visual '
                        'to skip (e.g. CI without Chromium). Gracefully '
                        'skips when playwright is not installed.')
    p.add_argument('--screenshots', action='store_true',
                   help='In addition to --visual checks, archive PNG '
                        'screenshots of each slide to '
                        '<deck-stem>-previews/sNN.png. Useful for visual '
                        'baseline / human review; not needed for CI.')
    p.add_argument('--json', action='store_true',
                   help='Emit a stable JSON blob to stdout instead of the '
                        'human-readable report. Format: '
                        '{"deck": <path>, "slides": <N>, "errors": [...], '
                        '"warnings": [...]} where each issue is '
                        '{"code", "msg", "slide" (parsed if present), '
                        '"severity"}. Use this when downstream tools '
                        '(run-regression.py, analyze-prompts.py) consume '
                        'validator output — parsing the human report via '
                        'regex is brittle to format tweaks.')
    p.add_argument('--slide', metavar='KEY_OR_N', default=None,
                   help='Diagnostic single-slide filter (F-254): keep only '
                        'findings for ONE slide — by data-slide-key (e.g. '
                        '"cover") or 1-based ordinal (e.g. "30" / "#30"). Exit '
                        'code reflects ONLY that slide. Use when editing a single '
                        'page so its findings are not buried in deck-wide '
                        'pre-existing noise. Does NOT change which audits run — '
                        'only what is reported/exited on; NOT a delivery gate.')
    p.add_argument('--scope-frames', metavar='N[,N,...]', default=None,
                   help='F-293 · feed a render SCOPE into the engine so per-slide '
                        'audits only run on these frames (1-based ordinals, '
                        'comma-separated, e.g. "2" or "2,3"). UNLIKE --slide '
                        '(which runs every audit on the whole deck then FILTERS '
                        'the report), this sets window.__AUDIT_SCOPE__ so the '
                        'engine SKIPS evaluating off-scope slides entirely — the '
                        'single-page `--scope` render fast path (audits 50 pages → '
                        'just the changed one). Deck-level rules (R10 / R-KEY / '
                        'R-CSSVAR / R-DECK-* / R-VIS-NO-IMAGERY …) still scan the '
                        'whole DOM and emit once, anchored on the first in-scope '
                        'frame — they are NOT suppressed by scope.')
    p.add_argument('--full', action='store_true',
                   help='F-352 · force the full-deck gate even right after a '
                        'page-SCOPED render. Without it, an unscoped full run '
                        'whose sibling last-render.log shows the last render was '
                        'page-scoped is REFUSED — a full validate then surfaces '
                        'pre-existing out-of-scope debt unrelated to the confined '
                        'edit (the "改一页却校验很多页" trap). This is the delivery '
                        '/ render-pipeline path; for a confined edit use --slide '
                        'or --scope-frames instead.')
    p.add_argument('--with-distribution', action='store_true',
                   help='F-290 · ALSO run the layout-distribution geometry audit '
                        '(check-distribution) in the SAME visual browser pass and '
                        'include it under a top-level "distribution" key in --json '
                        'output — saves a second Chromium launch + full reload. '
                        'Only meaningful with --visual --json.')
    args = p.parse_args()
    # F-293 · parse --scope-frames into the engine scope list (1-based ordinals).
    # Distinct from --slide (post-run report filter); this is the REAL scope fed
    # to run_unified_audits → run_unified_engine → window.__AUDIT_SCOPE__.
    scope_frames = None
    if args.scope_frames is not None:
        try:
            scope_frames = [int(t) for t in args.scope_frames.split(',')
                            if t.strip()]
        except ValueError:
            print(f'ERROR: --scope-frames must be comma-separated 1-based '
                  f'integers, got {args.scope_frames!r}', file=sys.stderr)
            return 2
        # Slide ordinals are 1-based: 0 / negative silently match NO frame, turning
        # a scoped run into a no-op false PASS. Reject loudly (parity with
        # run-audits.parse_scope, audits-js-4).
        if any(n < 1 for n in scope_frames):
            print(f'ERROR: --scope-frames are 1-based; 0/negative not allowed, '
                  f'got {args.scope_frames!r}', file=sys.stderr)
            return 2
        if not scope_frames:
            scope_frames = None
    if args.screenshots and not args.visual:
        args.visual = True   # --screenshots implies --visual

    path = Path(args.html)
    if not path.is_file():
        print(f'ERROR: file not found: {path}', file=sys.stderr)
        return 2

    # F-352 · scoped-edit guardrail. A full-deck `validate.py <html>` run right
    # after a page-SCOPED render surfaces pre-existing out-of-scope debt that has
    # nothing to do with the confined edit (the recurring "改一页却校验/渲染很多页"
    # trap). Detect it from the sibling last-render.log GATE-COVERAGE line: a
    # page-scoped render records scope=<digits> / scope=auto:N (a full render
    # records scope=full / --quick — no digit). On an unscoped full run (no
    # --slide / --scope-frames) without the --full override, refuse and point at
    # the scoped flags. render-deck.py's own internal gate passes --full (it IS
    # the full-deck gate, with its own F-319 scope demotion), so the render
    # pipeline is unaffected.
    if args.slide is None and scope_frames is None and not args.full:
        _rlog = path.parent / 'last-render.log'
        _scope_tok = None
        if _rlog.is_file():
            try:
                for _line in reversed(_rlog.read_text(
                        encoding='utf-8', errors='replace').splitlines()):
                    _m = re.search(r'GATE-COVERAGE\b.*\bscope=(\S+)', _line)
                    if _m:
                        _scope_tok = _m.group(1)
                        break
            except OSError:
                pass
        if _scope_tok and re.search(r'\d', _scope_tok):
            print(f'⛔ REFUSED: the last render was page-scoped '
                  f'(last-render.log: scope={_scope_tok}).', file=sys.stderr)
            print('   A full-deck validate would surface pre-existing '
                  'out-of-scope findings unrelated to your edit '
                  '(the 改一页却校验很多页 trap).', file=sys.stderr)
            print('   · validate only what you changed:  '
                  '--slide <key>   or   --scope-frames <N[,N]>', file=sys.stderr)
            print('   · really want the delivery-grade full pass:  --full',
                  file=sys.stderr)
            return 2

    html = path.read_text(encoding='utf-8')
    # `slides` is still needed for the human header count (`slides: N`) and the
    # --slide diagnostic filter. extract_slides reads the raw frame markup; the
    # engine does its OWN framework inlining / rendering, so we no longer need
    # inline_linked here on the rule path (kept as a public helper for
    # check-only / tests via F-14).
    slides = extract_slides(html)

    iss = Issues()
    # UNIFY-VALIDATE-ARCH: ALL rule findings come from the single unified engine
    # (audits.js on the rendered DOM + runner byte/source rules). No more
    # STATIC_AUDITS / visual-audit.js dual registries. `--strict` still promotes
    # warnings → errors after the run (see end of main()).
    #   · DEFAULT (`--visual`): full engine — geometry / DOM-text / structure +
    #     byte/source rules. Needs playwright; degrades to byte/source-only +
    #     advisory if Chromium is unavailable (never blocks a good deck on a CI
    #     hiccup; never a silent green either).
    #   · `--no-visual`: NO browser. Runs the byte/source rules (R-DOC-INTEGRITY
    #     / R-DOM over-close / R-SELF-CONTAINED / perf) PLUS the restored
    #     no-browser source-text rules (R-KEY / R-ESC-HTML / R02 / R07 / R05) — so
    #     this default-gate / write-hook path keeps real static enforcement. Still
    #     a documented PARTIAL check: the geometry / pure DOM-text rules (R-VIS-*,
    #     R06/R20/R10/R-OVERFLOW and the audits.js R-DOM nesting invariants) do
    #     NOT run. Use where Chromium is unavailable.
    _dist_data = None
    try:
        _dist_data = run_unified_audits(path, iss, dom_rules=args.visual,
                           scope=scope_frames,
                           want_screenshots=args.screenshots,
                           with_distribution=args.with_distribution)
    except Exception as e:
        # The engine adapter should self-degrade; a leak here must still never
        # crash the whole validate — emit a soft advisory and continue so any
        # findings already folded in survive.
        iss.warn_soft('R-VISUAL',
            f'unified engine failed ({type(e).__name__}: {e}) — '
            'findings may be incomplete.')

    slide_filter_note = None
    if args.slide is not None:
        slide_filter_note = filter_issues_to_slide(args.slide, slides, iss)

    if args.strict:
        # Promote regular warnings to errors. SOFT warnings (R-VIS-NO-IMAGERY,
        # R-SELF-CONTAINED, etc.) stay as warnings — they are editorial
        # advisories that should never fail CI.
        iss.errors.extend(iss.warnings)
        iss.warnings = []

    # Soft warnings render alongside regular warnings, no separate header.
    all_warnings = iss.warnings + iss.soft_warnings

    if args.json:
        # Stable machine-readable output. Downstream tools (run-regression,
        # analyze-prompts) read this instead of regex-parsing the human
        # narrative. Slide ordinal parsed from msg when present ("slide N ·")
        # — same convention every audit emit follows. selector_hint is best-
        # effort: backtick-quoted token inside the msg (most audits include).
        _SLIDE_IN_MSG = re.compile(r'slide\s+(\d+)\b')
        _BACKTICK_IN_MSG = re.compile(r'`([^`]+)`')
        def _entry(code, msg, severity):
            s = _SLIDE_IN_MSG.search(msg)
            sel = _BACKTICK_IN_MSG.search(msg)
            return {
                'code': code,
                'severity': severity,
                'msg': msg,
                'slide': int(s.group(1)) if s else None,
                'selector_hint': sel.group(1) if sel else None,
            }
        # F-283 step 1 · CJK font fingerprint. Only meaningful on the visual
        # path (Chromium rendered the deck); on --no-visual we did not measure,
        # so report the no-engine sentinel rather than a guess. This stamps each
        # cross-machine verdict with the CJK face geometry was actually measured
        # against (the silent "passes here / fails there" font-metric source).
        if args.visual:
            effective_cjk_font = probe_effective_cjk_font(path)
        else:
            effective_cjk_font = _CJK_FONT_UNKNOWN
        payload = {
            'deck': str(path),
            'slides': len(slides),
            'effective_cjk_font': effective_cjk_font,
            'errors': [_entry(c, m, 'error') for c, m in iss.errors],
            'warnings': (
                [_entry(c, m, 'warning') for c, m in iss.warnings]
                + [_entry(c, m, 'warning_soft') for c, m in iss.soft_warnings]
            ),
            'pass': not iss.errors,
        }
        if _dist_data is not None:
            # F-290 · same enriched shape as check-distribution.py --json, folded
            # into THIS pass so render-deck needn't spawn a second Chromium.
            payload['distribution'] = _dist_data
        import json as _json
        print(_json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if not iss.errors else 1

    print(f'feishu-deck-h5 validator  ·  {path.name}')
    if slide_filter_note:
        print(f'  ⟂ {slide_filter_note} · F-254 single-slide diagnostic (NOT a delivery gate)')
    print(f'  slides: {len(slides)}')
    print(f'  errors:   {len(iss.errors)}')
    print(f'  warnings: {len(all_warnings)}')

    if iss.errors:
        print('\nERRORS')
        for code, msg in iss.errors:
            print(f'  ✗ [{code}] {msg}')
    if all_warnings:
        print('\nWARNINGS')
        for code, msg in all_warnings:
            print(f'  ! [{code}] {msg}')

    if iss.errors:
        print('\nFAIL — fix the errors above before delivering.')
        return 1
    print('\nPASS — all programmatic checks satisfied.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
