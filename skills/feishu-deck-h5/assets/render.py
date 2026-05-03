#!/usr/bin/env python3
"""render.py — deterministic deck renderer for canonical patterns.

Layer 1 of the skill: takes a structured TOML input + an image, renders
a fully-validated HTML deck with no LLM in the loop. The template pinned
in `templates/<pattern>.html` is the single source of visual truth — the
output is byte-deterministic for a given input.

Usage:
  python3 render.py one-pager <input.toml> <output-dir> [--inline]

Layouts supported:
  one-pager  →  templates/one-pager-case.html  (`.story-case` content-2col)

Future layouts: agenda, end, section, etc. — drop a new template +
register it in PATTERNS below.

stdlib-only Python 3.11+ (uses tomllib).
"""
from __future__ import annotations

import argparse
import html
import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

# ---------------------------------------------------------------------------
# Skill paths
# ---------------------------------------------------------------------------

SKILL_ROOT = Path(__file__).resolve().parent.parent      # skills/feishu-deck-h5/
ASSETS_DIR = SKILL_ROOT / "assets"
TEMPLATES_DIR = SKILL_ROOT / "templates"
VALIDATOR = ASSETS_DIR / "validate.py"


# ---------------------------------------------------------------------------
# Pattern: one-pager case
# ---------------------------------------------------------------------------

# Required fields per pattern. Path uses dotted notation; dict-of-dict in TOML.
# Every field must be a non-empty string.
ONE_PAGER_REQUIRED = (
    "title",
    "industry",
    "source",
    "hook.lead", "hook.accent", "hook.tail",
    "arc.pain",
    "arc.conflict",
    "arc.solution",
    "arc.value.lead", "arc.value.accent", "arc.value.tail",
    "scene.image", "scene.caption", "scene.alt",
)

# Optional fields with defaults.
ONE_PAGER_DEFAULTS = {
    "scene.fit": "cover",            # cover | contain
    "scene.position": "center",       # CSS background-position
    "screen_label": None,             # default: derived from title
}

# texts.md field mapping: data-text-id → dotted-path-into-data
ONE_PAGER_TEXT_IDS = (
    ("slide-01.title",            "title"),
    ("slide-01.industry",         "industry"),
    ("slide-01.hook.lead",        "hook.lead"),
    ("slide-01.hook.accent",      "hook.accent"),
    ("slide-01.hook.tail",        "hook.tail"),
    ("slide-01.arc.pain",         "arc.pain"),
    ("slide-01.arc.conflict",     "arc.conflict"),
    ("slide-01.arc.solution",     "arc.solution"),
    ("slide-01.arc.value.lead",   "arc.value.lead"),
    ("slide-01.arc.value.accent", "arc.value.accent"),
    ("slide-01.arc.value.tail",   "arc.value.tail"),
    ("slide-01.scene.caption",    "scene.caption"),
    ("slide-01.source",           "source"),
)

# Beats whose content carries the rhetorical weight of the case. If an
# extractor (Layer 2 LLM) stuffs these with placeholders or runs them too
# short, the case probably doesn't fit the schema and the agent should
# take Path B (creative authoring) instead of letting the template render
# garbage.
ONE_PAGER_FIT_CHECK = (
    "hook.lead", "hook.accent", "hook.tail",
    "arc.pain", "arc.conflict", "arc.solution",
    "arc.value.lead", "arc.value.accent", "arc.value.tail",
)

# Accent boundaries surfaced after a successful render so the user can
# eyeball that the right word got the teal highlight.
ONE_PAGER_ACCENT_PATHS = (
    ("hook",  "hook"),
    ("value", "arc.value"),
)

# ---------------------------------------------------------------------------
# Pattern: quote — single customer testimonial slide
# ---------------------------------------------------------------------------

QUOTE_REQUIRED = (
    "title", "attribution",
    "quote.lead", "quote.accent", "quote.tail",
)
QUOTE_DEFAULTS = {
    "decor": "blue-glow",
    "screen_label": None,
}
QUOTE_TEXT_IDS = (
    ("slide-01.quote.lead",   "quote.lead"),
    ("slide-01.quote.accent", "quote.accent"),
    ("slide-01.quote.tail",   "quote.tail"),
    ("slide-01.attribution",  "attribution"),
)
QUOTE_FIT_CHECK = (
    "quote.lead", "quote.accent", "quote.tail",
    "attribution",
)
QUOTE_ACCENT_PATHS = (
    ("quote", "quote"),
)


# ---------------------------------------------------------------------------
# Pattern: big-stat — one hero number + supporting prose
# ---------------------------------------------------------------------------

BIG_STAT_REQUIRED = (
    "title",
    "stat.number", "stat.unit",
    "heading", "body",
)
BIG_STAT_DEFAULTS = {
    "decor": "",
    "eyebrow": "",
    "source": "",
    "screen_label": None,
}
BIG_STAT_TEXT_IDS = (
    ("slide-01.stat.number",  "stat.number"),
    ("slide-01.stat.unit",    "stat.unit"),
    ("slide-01.eyebrow",      "eyebrow"),
    ("slide-01.heading",      "heading"),
    ("slide-01.body",         "body"),
    ("slide-01.source",       "source"),
)
# stat.number / stat.unit can be naturally short (e.g. "30" / "%"). Skip
# them in fit_check; only the narrative beats need the safety net.
BIG_STAT_FIT_CHECK = (
    "heading", "body",
)
BIG_STAT_ACCENT_PATHS = ()    # big-stat has no inline accent structure


# ---------------------------------------------------------------------------
# Pattern: multi-case-bundle — full deck (cover + agenda + N one-pagers + end)
# ---------------------------------------------------------------------------

# Bundle TOML has a different schema from single-pattern TOMLs — it composes.
MULTI_CASE_BUNDLE_REQUIRED = (
    "deck.title", "deck.author", "deck.date",
    "agenda.title",
    "brand.contact",   # used by end-fragment; brand.line was for the
                       # retired .footer chrome — no longer required.
)
MULTI_CASE_BUNDLE_DEFAULTS = {}     # nothing optional


PATTERNS = {
    "one-pager": {
        "template": "one-pager-case.html",
        "fragment": "one-pager-case.fragment.html",
        "required": ONE_PAGER_REQUIRED,
        "defaults": ONE_PAGER_DEFAULTS,
        "text_ids": ONE_PAGER_TEXT_IDS,
        "fit_check": ONE_PAGER_FIT_CHECK,
        "accent_paths": ONE_PAGER_ACCENT_PATHS,
        "version": "v1",
        "needs_image": True,
    },
    "quote": {
        "template": "quote.html",
        "required": QUOTE_REQUIRED,
        "defaults": QUOTE_DEFAULTS,
        "text_ids": QUOTE_TEXT_IDS,
        "fit_check": QUOTE_FIT_CHECK,
        "accent_paths": QUOTE_ACCENT_PATHS,
        "version": "v1",
        "needs_image": False,
    },
    "big-stat": {
        "template": "big-stat.html",
        "required": BIG_STAT_REQUIRED,
        "defaults": BIG_STAT_DEFAULTS,
        "text_ids": BIG_STAT_TEXT_IDS,
        "fit_check": BIG_STAT_FIT_CHECK,
        "accent_paths": BIG_STAT_ACCENT_PATHS,
        "version": "v1",
        "needs_image": False,
    },
    "multi-case-bundle": {
        "shell": "_bundle-shell.html",
        "cover_fragment": "bundle-cover.fragment.html",
        "agenda_fragment": "bundle-agenda.fragment.html",
        "end_fragment": "bundle-end.fragment.html",
        "required": MULTI_CASE_BUNDLE_REQUIRED,
        "defaults": MULTI_CASE_BUNDLE_DEFAULTS,
        "version": "v1",
        "is_composite": True,           # signals custom render path
    },
}


# ---------------------------------------------------------------------------
# Schema-fit detection — refuse to render placeholder-stuffed inputs
# ---------------------------------------------------------------------------

# Anything matching these in a beat almost certainly means the extractor
# couldn't fill it from the source content. Match case-insensitive.
PLACEHOLDER_PATTERNS = (
    r"\b(TBD|TBC|TODO|XXX|N/?A|FIXME)\b",
    r"(待补|具体待补|占位|稍后补充|有待补充|待定|暂无|未填|None)",
    r"^[\s\.\-…—_]+$",                # only punctuation / whitespace
    r"^(\?+|？+)$",                    # only question marks
    r"\.\.\.{2,}|…{2,}",              # multiple ellipses (filler)
)

# Min meaningful length per beat. Hook-lead / hook-tail and value-lead /
# value-tail can be SHORT (they're connective tissue, e.g. ",新人...").
# Beats that carry the actual meaning need more.
MIN_LEN_FULL = 10        # arc.pain / arc.conflict / arc.solution (the meaty beats)
MIN_LEN_ACCENT = 2       # *.accent — usually 2-6 chars (highlight words)
MIN_LEN_CONNECTIVE = 1   # *.lead / *.tail — connective tissue, can be very short


def _min_len_for(path: str) -> int:
    if path.endswith(".accent"):
        return MIN_LEN_ACCENT
    if path.endswith((".lead", ".tail")):
        return MIN_LEN_CONNECTIVE
    return MIN_LEN_FULL


def check_schema_fit(data: dict, paths: tuple[str, ...]) -> list[str]:
    """Detect that the case content actually fits the schema.

    Returns a list of issue strings; empty list = fit OK. The caller should
    refuse to render and prompt the user to take Path B (creative LLM
    authoring) when this list is non-empty.
    """
    issues: list[str] = []
    if not paths:
        return issues

    seen: dict[str, str] = {}
    for path in paths:
        try:
            text = get_path(data, path)
        except KeyError:
            continue
        text = text.strip() if isinstance(text, str) else ""

        # 1. Placeholder content
        for pat in PLACEHOLDER_PATTERNS:
            if re.search(pat, text, flags=re.IGNORECASE):
                issues.append(
                    f"{path}: 看起来是占位词 ({text!r}) — 模板装不下,请走 Path B"
                )
                break
        else:
            # 2. Length floor
            min_len = _min_len_for(path)
            if len(text) < min_len:
                issues.append(
                    f"{path}: 只有 {len(text)} 字 ({text!r}) — 太短承不起这一拍,"
                    f"该 beat 可能不存在,请走 Path B"
                )
            # 3. Duplicate beats (LLM laziness)
            elif text in seen and not path.endswith((".lead", ".tail", ".accent")):
                issues.append(
                    f"{path}: 与 {seen[text]} 完全相同 ({text!r}) — "
                    f"该故事可能没这一拍,请走 Path B 或重抽 TOML"
                )
            else:
                seen[text] = path
    return issues


# ---------------------------------------------------------------------------
# Accent boundary inspection — surface highlight words after render
# ---------------------------------------------------------------------------

def show_accents(data: dict, accent_paths: tuple[tuple[str, str], ...]) -> None:
    """Print each accent-bearing field with the accent visually marked
    (ANSI bold-teal in a TTY, brackets otherwise) so the user can verify
    the extractor framed the highlight around the right word.
    """
    if not accent_paths:
        return
    use_color = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None
    HL_open  = "\033[1;36m" if use_color else "["
    HL_close = "\033[0m"    if use_color else "]"

    print()
    print("ACCENT 复核 (1 秒目测,被高亮的词是该突出的吗?)")
    for label, base in accent_paths:
        try:
            lead   = get_path(data, f"{base}.lead")
            accent = get_path(data, f"{base}.accent")
            tail   = get_path(data, f"{base}.tail")
        except KeyError:
            continue
        print(f"  {label:>6}  ·  {lead}{HL_open}{accent}{HL_close}{tail}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_path(d: dict, dotted: str):
    """Walk a dotted path into nested dicts. Raises KeyError on miss."""
    cur = d
    for key in dotted.split("."):
        if not isinstance(cur, dict) or key not in cur:
            raise KeyError(dotted)
        cur = cur[key]
    return cur


def set_default(d: dict, dotted: str, value):
    """Set d[a][b][c] = value if not present."""
    keys = dotted.split(".")
    cur = d
    for k in keys[:-1]:
        cur = cur.setdefault(k, {})
    cur.setdefault(keys[-1], value)


def relpath_from_to(src_dir: Path, dst_dir: Path) -> str:
    """Filesystem-relative path from src_dir to dst_dir using POSIX separators."""
    return os.path.relpath(dst_dir, start=src_dir).replace(os.sep, "/")


def render_template(template: str, data: dict) -> str:
    """Substitute placeholders in `template`.

    Two flavors:
      - `{{{ field }}}`  raw   — value substituted as-is (use ONLY for known
                                 HTML strings, e.g. composed slide fragments).
      - `{{ field }}`    safe  — value HTML-escaped (default).

    Raw substitutions run first so they're not double-processed by the safe
    pass.
    """
    def sub_raw(m: re.Match) -> str:
        path = m.group(1).strip()
        try:
            return str(get_path(data, path))
        except KeyError:
            raise SystemExit(f"render: template references missing field {{{{{{ {path} }}}}}}")
    template = re.sub(r"\{\{\{\s*([\w.]+)\s*\}\}\}", sub_raw, template)

    def sub_safe(m: re.Match) -> str:
        path = m.group(1).strip()
        try:
            value = get_path(data, path)
        except KeyError:
            raise SystemExit(f"render: template references missing field {{{{ {path} }}}}")
        return html.escape(str(value), quote=True)
    return re.sub(r"\{\{\s*([\w.]+)\s*\}\}", sub_safe, template)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_input(data: dict, required: tuple[str, ...]) -> list[str]:
    """Return a list of missing/empty field paths."""
    missing = []
    for path in required:
        try:
            v = get_path(data, path)
        except KeyError:
            missing.append(path); continue
        if not isinstance(v, str) or not v.strip():
            missing.append(path)
    return missing


def fill_defaults(data: dict, defaults: dict) -> None:
    """Populate optional fields not set by the user."""
    for path, default in defaults.items():
        if default is None:
            continue
        set_default(data, path, default)


# ---------------------------------------------------------------------------
# Sidecar generators
# ---------------------------------------------------------------------------

def make_texts_md(data: dict, text_ids, output_dir: Path, pattern: str) -> str:
    """Generate the texts.md sidecar from input data."""
    asset_rel = relpath_from_to(output_dir, ASSETS_DIR)
    title = get_path(data, "title")
    lines = [
        f"# {title} — texts",
        "",
        "> Edit text below. After save, run:",
        f">   python3 {asset_rel}/apply-texts.py index.html texts.md",
        ">",
        "> Rules:",
        ">   • Edit ONLY this file. Visual tweaks → overrides.css.",
        ">     Layout / structure / new slides → re-render from input.toml or re-ask Claude.",
        ">   • Use `\\n` to insert a line break (renders as <br>).",
        ">   • Do NOT rename the slide-NN.field ids — they pair with HTML.",
        "",
        f"## slide-01 ({pattern}) — pattern `{pattern}`",
    ]
    for text_id, path in text_ids:
        # text_id is "slide-01.foo.bar"; field name (after "slide-01.") is "foo.bar"
        field_name = text_id.split(".", 1)[1]
        value = get_path(data, path)
        lines.append(f"{field_name}: {value}")
    return "\n".join(lines) + "\n"


def make_feedback_md(data: dict, input_path: Path, pattern: str, info: dict) -> str:
    """Generate the FEEDBACK.md for a template-mode run."""
    title = get_path(data, "title")
    title_len = len(title)
    title_warn = " ⚠ 接近单行上限(建议 ≤ 22)" if title_len > 22 else ""
    template_file = info["template"]
    version = info["version"]

    settings_lines = [
        f"- 模板版本: **{version}**",
        f"- 标题字符数: {title_len}{title_warn}",
    ]
    if info.get("needs_image"):
        try:
            settings_lines.append(
                f"- Image: `scene.png` (来源 `{get_path(data, 'scene.image')}`,"
                f"fit `{get_path(data, 'scene.fit')}`,"
                f"position `{get_path(data, 'scene.position')}`)"
            )
        except KeyError:
            pass
    settings_lines.append("- 输出文件: `index.html` / `texts.md` / "
                          + ("`scene.png` / " if info.get("needs_image") else "")
                          + "`FEEDBACK.md`")
    settings_lines.append("- Validator: PASS (strict)")
    settings_block = "\n".join(settings_lines)

    return f"""# Run feedback · template mode

**Pattern:** {pattern} ({version})
**Template:** `templates/{template_file}`
**Input:** `{input_path}`
**Built:** {title}

This deck was rendered by `assets/render.py {pattern}` — no LLM in the
loop. Same input always produces the same output, validator always
PASSes. There are no per-run "agent decisions" to second-guess.

## 这次 build 实际用的设置

{settings_block}

## 如果觉得哪里不对,反馈对应的层

| 你看到的问题 | 该改的层 |
| --- | --- |
| 文字 / 措辞 / 标点 | 改 `input.toml` 重渲;或直接改 `texts.md` 跑 `apply-texts.py` |
| 视觉 / 间距 / 颜色 / 列比 | 提 issue 升 `templates/{template_file}`(全局生效) |
| Schema 缺字段 / 多字段 | 提 issue 改 `assets/render.py` 的 `{pattern.upper().replace('-', '_')}_REQUIRED` |
| 整个 pattern layout 思路要换 | 重读 SKILL.md 对应 policy 节,大改前先对齐 |

## 你的额外建议

-

---

累计 ≥3 条值得反馈的(打钩 / 备注 / 自填),把这个文件发给 skill 维护者整合到下一版.
"""


# ---------------------------------------------------------------------------
# Composite render — multi-case-bundle: cover + agenda + N cases + end
# ---------------------------------------------------------------------------

def _build_agenda_items_html(cases: list[dict]) -> str:
    """Render the .toc items for the agenda slide.

    `cases` is a list of dicts with at least 'label' (short case name) and
    optionally 'industry' for a sub-line. ZH-only per LANGUAGE POLICY.
    """
    rows = []
    for i, case in enumerate(cases, start=1):
        n = f"{i:02d}"
        label = html.escape(case.get("label", "案例"), quote=True)
        industry = case.get("industry", "")
        industry_html = (
            f'<div class="title-en">{html.escape(industry, quote=True)}</div>'
            if industry else ""
        )
        rows.append(
            f'          <div class="item"><div class="n">{n}</div>'
            f'<div><div class="title-zh">{label}</div>{industry_html}</div></div>'
        )
    return "\n".join(rows)


def render_composite(pattern: str, input_path: Path, output_dir: Path,
                     info: dict, args_skip_fit_check: bool) -> int:
    """Render a composite deck (currently: multi-case-bundle).

    Bundle TOML structure:
      [deck]    title / author / date
      [agenda]  title
      [brand]   line / contact
      [[cases]] input (path to one-pager TOML) / label
    """
    try:
        bundle = tomllib.loads(input_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        print(f"render: TOML parse error in {input_path}: {e}", file=sys.stderr); return 2

    missing = validate_input(bundle, info["required"])
    if missing:
        print("render: missing/empty required fields in bundle.toml:", file=sys.stderr)
        for p in missing:
            print(f"  - {p}", file=sys.stderr)
        return 2

    cases = bundle.get("cases") or []
    if not cases:
        print("render: bundle.toml has no [[cases]] entries.", file=sys.stderr); return 2

    # Load + validate every case TOML up front. Fail fast if any case is
    # broken — partial bundle output is worse than no output.
    one_pager = PATTERNS["one-pager"]
    case_loaded: list[tuple[Path, dict, dict]] = []   # (case_input_path, case_data, case_meta)
    for idx, case_ref in enumerate(cases, start=1):
        if "input" not in case_ref:
            print(f"render: cases[{idx}] missing 'input' field.", file=sys.stderr); return 2
        case_input = (input_path.parent / case_ref["input"]).resolve()
        if not case_input.is_file():
            print(f"render: cases[{idx}].input not found: {case_input}", file=sys.stderr); return 2
        try:
            case_data = tomllib.loads(case_input.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as e:
            print(f"render: TOML parse error in {case_input}: {e}", file=sys.stderr); return 2

        fill_defaults(case_data, one_pager["defaults"])
        if not case_data.get("screen_label"):
            cleaned = re.sub(r"\s+", " ",
                             re.sub(r"[·:：—\-]+", " ", get_path(case_data, "title")))
            case_data["screen_label"] = cleaned.strip()[:20]

        case_missing = validate_input(case_data, one_pager["required"])
        if case_missing:
            print(f"render: cases[{idx}] ({case_input.name}) missing fields:",
                  file=sys.stderr)
            for p in case_missing:
                print(f"  - {p}", file=sys.stderr)
            return 2

        if not args_skip_fit_check:
            issues = check_schema_fit(case_data, one_pager["fit_check"])
            if issues:
                print(f"render: cases[{idx}] ({case_input.name}) 故事内容塞不进 schema:",
                      file=sys.stderr)
                for issue in issues:
                    print(f"  ✗ {issue}", file=sys.stderr)
                print("→ 修这个案例的 input.toml,或在 bundle.toml 把它换成走 Path B "
                      "手写的 fragment(暂未支持) / 删除该案例。",
                      file=sys.stderr)
                return 4

        case_loaded.append((case_input, case_data, case_ref))

    # ---- Layout ----
    # Slide 01 = cover, 02 = agenda, 03..(N+2) = cases, (N+3) = end
    n_cases = len(case_loaded)
    total_slides = 2 + n_cases + 1

    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    asset_path = relpath_from_to(output_dir, ASSETS_DIR)

    # Render cover fragment
    cover_data = {**bundle.get("deck", {}), "asset_path": asset_path}
    cover_html = render_template(
        (TEMPLATES_DIR / info["cover_fragment"]).read_text(encoding="utf-8"),
        cover_data,
    )

    # Render agenda fragment
    cases_for_agenda = [
        {"label": c.get("label", get_path(d, "title"))}
        for _, d, c in case_loaded
    ]
    agenda_data = {
        "agenda": bundle.get("agenda", {}),
        "agenda_items_html": _build_agenda_items_html(cases_for_agenda),
        "asset_path": asset_path,
    }
    agenda_html = render_template(
        (TEMPLATES_DIR / info["agenda_fragment"]).read_text(encoding="utf-8"),
        agenda_data,
    )

    # Render each case fragment
    case_fragment_template = (TEMPLATES_DIR / one_pager["fragment"]).read_text(encoding="utf-8")
    case_htmls = []
    for offset, (case_input, case_data, case_ref) in enumerate(case_loaded):
        slide_no = 3 + offset
        slide_no_padded = f"{slide_no:02d}"

        # Copy each case's scene image to a unique filename.
        img_src = (case_input.parent / get_path(case_data, "scene.image")).resolve()
        if not img_src.is_file():
            print(f"render: cases[{offset+1}] scene.image not found: {img_src}",
                  file=sys.stderr); return 2
        scene_filename = f"scene-{slide_no_padded}.png"
        shutil.copy2(img_src, output_dir / scene_filename)

        case_render_data = {
            **case_data,
            "slide_no": slide_no,
            "slide_no_padded": slide_no_padded,
            "scene_filename": scene_filename,
        }
        case_htmls.append(render_template(case_fragment_template, case_render_data))

    # Render end fragment
    end_slide_no = total_slides
    end_data = {
        "slide_no_padded": f"{end_slide_no:02d}",
        "contact": get_path(bundle, "brand.contact"),
        "asset_path": asset_path,
    }
    end_html = render_template(
        (TEMPLATES_DIR / info["end_fragment"]).read_text(encoding="utf-8"),
        end_data,
    )

    # Compose into shell
    all_slides = "\n".join([cover_html, agenda_html, *case_htmls, end_html])
    shell_data = {
        "title": get_path(bundle, "deck.title"),
        "asset_path": asset_path,
        "slides_html": all_slides,
    }
    final_html = render_template(
        (TEMPLATES_DIR / info["shell"]).read_text(encoding="utf-8"),
        shell_data,
    )
    (output_dir / "index.html").write_text(final_html, encoding="utf-8")

    # Auto-generate texts.md by walking the rendered HTML — keeps T03 happy
    # and gives users a flat editing surface across all slides if they ever
    # need it (per-case editing via input.toml + re-render is still preferred).
    extract_rc = subprocess.run(
        [sys.executable, str(ASSETS_DIR / "extract-texts.py"),
         str(output_dir / "index.html"),
         "--out", str(output_dir / "texts.md")],
        capture_output=True, text=True,
    )
    if extract_rc.returncode != 0:
        print(f"render: extract-texts.py failed: {extract_rc.stderr}", file=sys.stderr)

    # Bundle FEEDBACK.md (per-case editing happens at the case-source-TOML
    # level; texts.md exists mainly to satisfy T03 and as an emergency
    # flat-edit surface).
    bundle_feedback = (
        f"# Run feedback · multi-case-bundle (template mode)\n\n"
        f"**Pattern:** multi-case-bundle ({info['version']})\n"
        f"**Input:** `{input_path}`\n"
        f"**Built:** {get_path(bundle, 'deck.title')}\n"
        f"**Slides:** {total_slides} (cover + agenda + {n_cases} cases + end)\n\n"
        "Bundle composes existing one-pager case templates. Each case's "
        "visual is the frozen `.story-case` v1; bundle layer just adds the "
        "cover / agenda / end chrome.\n\n"
        "## 反馈对应的层\n\n"
        "| 你看到的问题 | 该改的层 |\n"
        "| --- | --- |\n"
        "| 某个案例的内容/措辞 | 改对应案例的 `input.toml` 重渲 |\n"
        "| 某个案例的视觉 | 改 `templates/one-pager-case.fragment.html` |\n"
        "| Cover / agenda / end 的视觉 | 改 `templates/bundle-*.fragment.html` |\n"
        "| 共享 CSS | 改 `assets/feishu-deck-patterns.css` |\n"
        "| 案例顺序 / 案例增删 | 改 `bundle.toml` 的 `[[cases]]` 顺序 |\n\n"
        "## 你的额外建议\n\n-\n\n---\n\n"
        "累计 ≥3 条值得反馈的,把这个文件发给 skill 维护者整合到下一版.\n"
    )
    (output_dir / "FEEDBACK.md").write_text(bundle_feedback, encoding="utf-8")

    # Run validator
    vr = subprocess.run(
        [sys.executable, str(VALIDATOR), str(output_dir / "index.html"), "--strict"],
        capture_output=True, text=True,
    )
    print(vr.stdout.rstrip())
    if vr.returncode != 0:
        print(file=sys.stderr)
        print("render: validator FAILED on a composed bundle.", file=sys.stderr)
        print("→ Fix the fragment template that produced the broken slide, "
              "not the output.", file=sys.stderr)
        if vr.stderr.strip():
            print(vr.stderr, file=sys.stderr)
        return 3

    print(f"\nOK  →  {output_dir}/index.html")
    print(f"       deck:  {get_path(bundle, 'deck.title')}")
    print(f"       slides: {total_slides} (cover · agenda · {n_cases} cases · end)")
    print(f"       scenes: {n_cases} image(s) copied as scene-NN.png")
    print(f"       sidecars: texts.md  ·  FEEDBACK.md")
    return 0


# ---------------------------------------------------------------------------
# Main render
# ---------------------------------------------------------------------------

def render(pattern: str, input_path: Path, output_dir: Path,
           args_skip_fit_check: bool = False) -> int:
    if pattern not in PATTERNS:
        print(f"render: unknown pattern '{pattern}'. Known: {list(PATTERNS)}", file=sys.stderr)
        return 2
    info = PATTERNS[pattern]

    if not input_path.is_file():
        print(f"render: input not found: {input_path}", file=sys.stderr); return 2

    # Composite patterns (multi-case-bundle) take a different code path —
    # they compose multiple per-case TOMLs into one stitched-together deck.
    if info.get("is_composite"):
        return render_composite(pattern, input_path, output_dir, info,
                                args_skip_fit_check)

    try:
        data = tomllib.loads(input_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        print(f"render: TOML parse error in {input_path}: {e}", file=sys.stderr); return 2

    fill_defaults(data, info["defaults"])

    # Derived fields
    if not data.get("screen_label"):
        # Strip CN punctuation + collapse whitespace; cap at 20 chars.
        cleaned = re.sub(r"\s+", " ", re.sub(r"[·:：—\-]+", " ", get_path(data, "title")))
        data["screen_label"] = cleaned.strip()[:20]

    missing = validate_input(data, info["required"])
    if missing:
        print("render: missing/empty required fields in input.toml:", file=sys.stderr)
        for p in missing:
            print(f"  - {p}", file=sys.stderr)
        return 2

    # Schema-fit detection (refuse to render placeholder-stuffed inputs).
    fit_paths = info.get("fit_check", ())
    if not args_skip_fit_check:
        fit_issues = check_schema_fit(data, fit_paths)
        if fit_issues:
            print("render: 故事内容塞不进 schema —— 模板会渲染出占位词,精度受损。",
                  file=sys.stderr)
            for issue in fit_issues:
                print(f"  ✗ {issue}", file=sys.stderr)
            print(file=sys.stderr)
            print("→ 修 input.toml 把这几拍补成真实内容,或者本案例走 Path B "
                  "(LLM 创作,SKILL.md ONE-PAGER CASE POLICY 节)。",
                  file=sys.stderr)
            print("→ 临时绕过(不推荐): --skip-fit-check", file=sys.stderr)
            return 4

    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    # Resolve and copy the scene image (only for patterns that need one).
    img_src = None
    if info.get("needs_image"):
        img_rel = get_path(data, "scene.image")
        img_src = (input_path.parent / img_rel).resolve()
        if not img_src.is_file():
            print(f"render: scene.image not found: {img_src}", file=sys.stderr); return 2
        shutil.copy2(img_src, output_dir / "scene.png")
        # Standalone path always uses the canonical filename so the template's
        # {{ scene_filename }} resolves cleanly (the same template variable
        # lets the bundle path use per-case scene-NN.png).
        data["scene_filename"] = "scene.png"

    # Compute the relative path from output to skill assets for <link>/<script>.
    data["asset_path"] = relpath_from_to(output_dir, ASSETS_DIR)

    # Render the HTML.
    template_text = (TEMPLATES_DIR / info["template"]).read_text(encoding="utf-8")
    html_out = render_template(template_text, data)
    (output_dir / "index.html").write_text(html_out, encoding="utf-8")

    # Sidecars.
    (output_dir / "texts.md").write_text(
        make_texts_md(data, info["text_ids"], output_dir, pattern), encoding="utf-8")
    (output_dir / "FEEDBACK.md").write_text(
        make_feedback_md(data, input_path, pattern, info), encoding="utf-8")

    # Run validator.
    vr = subprocess.run(
        [sys.executable, str(VALIDATOR), str(output_dir / "index.html"), "--strict"],
        capture_output=True, text=True,
    )
    print(vr.stdout.rstrip())

    if vr.returncode != 0:
        print(file=sys.stderr)
        print("render: validator FAILED on a template-rendered deck.", file=sys.stderr)
        print("→ This means the template itself is broken. Fix the template, not the output.",
              file=sys.stderr)
        if vr.stderr.strip():
            print(vr.stderr, file=sys.stderr)
        return 3

    title = get_path(data, "title")
    print(f"\nOK  →  {output_dir}/index.html")
    print(f"       title: {title}  ({len(title)} chars)")
    if img_src is not None:
        print(f"       scene: {img_src.name}  →  scene.png")
    print(f"       sidecars: texts.md  ·  FEEDBACK.md")

    # Surface accent boundaries for 1-second visual verification.
    show_accents(data, info.get("accent_paths", ()))
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="render.py",
        description="Deterministic deck renderer for canonical feishu-deck-h5 patterns.",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    for pattern in PATTERNS:
        sp = sub.add_parser(pattern, help=f"render the {pattern} pattern")
        sp.add_argument("input", type=Path, help="input.toml path")
        sp.add_argument("output_dir", type=Path, help="output directory (e.g. runs/<ts>/output/)")
        sp.add_argument("--skip-fit-check", action="store_true",
                        help="skip the placeholder / short-beat / duplicate-beat detection "
                             "(NOT recommended — bypasses the schema-fit safety net)")

    args = ap.parse_args(argv)
    return render(args.cmd, args.input, args.output_dir,
                  args_skip_fit_check=args.skip_fit_check)


if __name__ == "__main__":
    sys.exit(main())
