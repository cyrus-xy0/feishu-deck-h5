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
# for its DEFAULT (full) path. `--no-visual` runs ONLY the no-browser byte/source
# rules (see main()); it is documented as a partial check, never a silent green.
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
                       want_screenshots=False):
    """Run the unified engine against the rendered deck and fold its findings
    into `iss`. This REPLACES the old run_static_audits + run_visual_audits.

    dom_rules=True  → full engine: render in headless Chromium + audits.js
                      (geometry / DOM-text / structure rules) PLUS runner
                      byte/source rules. Requires playwright.
    dom_rules=False → `--no-visual`: NO browser; only the runner byte/source
                      rules (R-DOC-INTEGRITY / R-SELF-CONTAINED / perf). The
                      DOM/geometry rules do NOT run — documented partial check.

    Mirrors the old run_visual_audits failure semantics: an INABILITY to render
    (playwright missing / Chromium launch flake / nav timeout) is an environment
    glitch, NOT a deck defect, so it degrades to a single soft advisory rather
    than blocking a good deck under --strict. A real rule VIOLATION found by the
    engine still errs/warns normally."""
    eng = _engine()
    try:
        result = eng.run_unified_engine(
            path, scope, dom_rules=dom_rules)
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
            page.goto(url, wait_until='load', timeout=60_000)
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
    args = p.parse_args()
    if args.screenshots and not args.visual:
        args.visual = True   # --screenshots implies --visual

    path = Path(args.html)
    if not path.is_file():
        print(f'ERROR: file not found: {path}', file=sys.stderr)
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
    #   · `--no-visual`: byte/source rules ONLY (no browser). A documented
    #     PARTIAL check — the DOM/geometry rules (R-VIS-*, R06/R20/R10/R-DOM/…)
    #     do not run. Use only where Chromium is unavailable.
    try:
        run_unified_audits(path, iss, dom_rules=args.visual,
                           want_screenshots=args.screenshots)
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
        payload = {
            'deck': str(path),
            'slides': len(slides),
            'errors': [_entry(c, m, 'error') for c, m in iss.errors],
            'warnings': (
                [_entry(c, m, 'warning') for c, m in iss.warnings]
                + [_entry(c, m, 'warning_soft') for c, m in iss.soft_warnings]
            ),
            'pass': not iss.errors,
        }
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
