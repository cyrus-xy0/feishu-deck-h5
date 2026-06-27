#!/usr/bin/env python3
"""Create a cover-only deck through the feishu-deck-h5 pipeline.

This is the fast path for the common "open a new deck with this title, speaker
and date" request. It keeps the hard gates that matter for delivery while
collapsing the repeated controller/designer/renderer/finalize shell work into
one command:

  new-run -> minimal design artifacts -> deck-cli new-deck -> render --final
  -> named inline HTML.

It intentionally handles only a single standard cover page. If body pages,
source material, bespoke raw pages, or asset lookup are needed, use the normal
designer/renderer path.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent
DECK_JSON = SKILL_ROOT / "deck-json"


def _repo_root() -> Path:
    proc = subprocess.run(
        ["git", "-C", str(SKILL_ROOT), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    if proc.returncode == 0:
        return Path(proc.stdout.strip()).resolve()
    return SKILL_ROOT


REPO_ROOT = _repo_root()


def run(cmd: list[str], *, cwd: Path = REPO_ROOT, capture: bool = False) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=capture)
    if proc.returncode != 0:
        if capture:
            if proc.stdout:
                print(proc.stdout, end="")
            if proc.stderr:
                print(proc.stderr, end="", file=sys.stderr)
        raise SystemExit(proc.returncode)
    return proc


def infer_slug(title: str, fallback: str = "cover-deck") -> str:
    words = re.findall(r"[A-Za-z0-9]+", title.lower())
    slug = "-".join(words[:6])
    return slug or fallback


def normalize_iso_date(date_text: str) -> str:
    s = date_text.strip()
    m = re.match(r"^(\d{4})[./-](\d{1,2})[./-](\d{1,2})$", s)
    if not m:
        raise ValueError(f"date must look like YYYY.M.D or YYYY-MM-DD, got: {date_text}")
    y, mo, d = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return f"{y:04d}-{mo:02d}-{d:02d}"


def default_cover_title(title: str) -> str:
    if "\n" in title:
        return title
    for sep in ("：", ":"):
        if sep in title:
            head, tail = title.split(sep, 1)
            tail = tail.strip()
            if tail:
                return f"{head.strip()}{sep}\n{tail}"
    return title


def delivery_name(slug: str, iso_date: str) -> str:
    clean = re.sub(r"[^a-z0-9-]+", "-", slug.lower()).strip("-")
    clean = re.sub(r"-+", "-", clean) or "cover-deck"
    return f"lark-{clean}-{iso_date}"


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def create_artifacts(run_dir: Path, *, title: str, cover_title: str, author: str,
                     date_text: str, iso_date: str, slug: str) -> None:
    output = run_dir / "output"
    prompt = (
        "# Prompts\n\n"
        "## cover-only fast path\n\n"
        f"- 用户要求：开一个新的单页封面 deck，标题「{title}」，分享人 {author}，日期 {date_text}。\n"
        "- 范围锁定：single-slide cover only。\n"
        "- 模式锁定：GENERATION / cover-only fast path。\n"
        "- 目标锁定：output/index.html + named inline HTML。\n"
    )
    write_text(run_dir / "PROMPTS.md", prompt)

    design_plan = (
        "# DESIGN PLAN\n\n"
        "## Router Lock\n\n"
        "- Mode: GENERATION / cover-only fast path\n"
        "- Scope: single-slide starter deck, cover only\n"
        "- Target: output/index.html and named inline HTML\n\n"
        "## Scenario\n\n"
        f"- Goal: create a polished opening cover for `{title}`.\n"
        "- Audience: presentation audience; no body content was provided.\n"
        f"- Setting: opening page, dated {date_text}.\n"
        "- Language: zh-only.\n"
        "- Proof requirements: none; the cover introduces no factual claims.\n"
        "- Cloud assets: not needed; use the built-in Feishu cover schema.\n\n"
        "## Design Pass\n\n"
        "| # | Page / Topic | Role (Q0) | Single Focus (Q1) | A Tier (Q2) | Mood Conflict (Q4) | Layout |\n"
        "|---|---|---|---|---|---|---|\n"
        f"| P0 | 封面 | 结论页 | `{title}` | cover title, framework hero treatment | no conflict for a standard technology/collaboration cover | schema:cover |\n\n"
        "## Density\n\n"
        "Core information blocks: 2 (title + speaker/date). Supporting evidence: 0. "
        "Layout capacity: cover schema; fits without compression.\n"
    )
    write_text(output / "DESIGN-PLAN.md", design_plan)

    outline = {
        "scenario": {
            "goal": f"Create a polished opening cover for {title}.",
            "audience": "Presentation audience; no body content was provided.",
            "setting": f"Opening page, dated {date_text}.",
            "decision": "Establish the talk topic and speaker identity before future pages are added.",
            "language": "zh-only",
            "source_summary": ["User provided title, speaker and date only."],
        },
        "design_plan": {
            "title": title,
            "narrative_arc": "Single opening cover for a new deck.",
            "visual_direction": "Standard Feishu-style cover.",
            "hero_pages": ["cover"],
            "risks": ["No body outline was provided, so no body pages are generated."],
            "open_questions": [],
        },
        "slides": [
            {
                "key": "cover",
                "role": "cover",
                "layout_intent": "schema:cover",
                "is_hero": True,
                "single_focus": title,
                "content": {"title": cover_title, "author": author, "date": date_text},
                "evidence": [],
                "assets_needed": [],
                "density_budget": "Core blocks: 2; supporting evidence: 0; cover schema capacity fits.",
                "design_spec": {
                    "A": {
                        "element": "cover title",
                        "font_size": "framework cover hero title",
                        "container_level": "page-level cover hero",
                        "decoration": "framework cover treatment",
                        "alignment": "cover default",
                        "letter_spacing": "0",
                        "font_weight": "framework cover title weight",
                    },
                    "B": {
                        "element": "speaker and date",
                        "font_size": "framework cover metadata",
                        "container_level": "cover metadata line",
                        "decoration": "none",
                        "alignment": "cover default",
                        "letter_spacing": "0",
                        "font_weight": "framework metadata weight",
                    },
                    "C": {"element": "none"},
                    "D": {"element": "none"},
                    "notes": f"Pure standard cover shape; slug={slug}; presentation_date={iso_date}.",
                },
            }
        ],
    }
    write_json(output / "outline.json", outline)


def parse_args(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Create a one-slide cover deck fast.")
    ap.add_argument("--title", required=True)
    ap.add_argument("--author", required=True)
    ap.add_argument("--date", required=True, help="Display date, e.g. 2026.6.28")
    ap.add_argument("--slug", default="", help="ASCII run/customer slug; inferred from title if omitted")
    ap.add_argument("--cover-title", default="", help="Optional cover title with \\n line breaks")
    ap.add_argument("--presentation-date", default="", help="ISO date for metadata/name; inferred from --date")
    ap.add_argument("--name", default="", help="Delivery basename; defaults to lark-<slug>-<presentation-date>")
    ap.add_argument("--no-render", action="store_true", help="Only create run artifacts and deck.json")
    ap.add_argument("--no-inline", action="store_true", help="Skip named inline HTML creation")
    ap.add_argument("--review-shot", action="store_true", help="After inline, shoot one review screenshot")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    slug = args.slug or infer_slug(args.title)
    cover_title = args.cover_title or default_cover_title(args.title)
    iso_date = args.presentation_date or normalize_iso_date(args.date)
    name = args.name or delivery_name(slug, iso_date)

    run_proc = run(["bash", str(HERE / "new-run.sh"), slug], capture=True)
    print(run_proc.stdout, end="")
    sys.stdout.flush()
    run_dir = Path(run_proc.stdout.strip().splitlines()[-1]).resolve()
    out_dir = run_dir / "output"
    deck = out_dir / "deck.json"

    create_artifacts(
        run_dir,
        title=args.title,
        cover_title=cover_title,
        author=args.author,
        date_text=args.date,
        iso_date=iso_date,
        slug=slug,
    )

    run(["python3", str(DECK_JSON / "outline-lint.py"), str(out_dir / "outline.json")])
    run([
        "python3", str(DECK_JSON / "deck-cli.py"), str(deck), "new-deck",
        "--title", args.title,
        "--author", args.author,
        "--date", args.date,
        "--cover-title", cover_title,
        "--customer-slug", slug,
        "--presentation-date", iso_date,
    ])

    inline_path = out_dir / f"{name}-inline.html"
    shot_dir = out_dir / "review-inline"

    if not args.no_render:
        run(["python3", str(DECK_JSON / "render-deck.py"), str(deck), str(out_dir), "--final"])
        if not args.no_inline:
            run(["python3", str(HERE / "inline-assets.py"), str(out_dir / "index.html"), "--out", str(inline_path)])
        if args.review_shot and not args.no_inline:
            run(["python3", str(DECK_JSON / "shoot.py"), str(inline_path), "--pages", "1", "--out", str(shot_dir)])

    print("\nCOVER-DECK OK")
    print(f"  run     : {run_dir}")
    print(f"  deck    : {deck}")
    if not args.no_render:
        print(f"  working : {out_dir / 'index.html'}")
        if not args.no_inline:
            print(f"  inline  : {inline_path}")
        if args.review_shot and not args.no_inline:
            print(f"  review  : {shot_dir / 'p01-cover.png'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
