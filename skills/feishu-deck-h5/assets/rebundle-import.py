#!/usr/bin/env python3
"""L5 (2026-05-30): re-bundle a foreign / imported raw HTML deck with the
CURRENT framework runtime (feishu-deck.js — incl. the runtime auto-balance
pass) WITHOUT touching its design.

This is the SAFE增益 path for an imported deck (see SKILL.md "导入外来 raw HTML
deck" + IMPORT-RAW-DECK-LESSONS):
  · swaps in the current feishu-deck.js so the runtime auto-balance fixes
    box-crowd (文字贴底) on load. Fonts / chrome / content are untouched.
  · stamps `<meta name="fs-deck-origin" content="imported">` purely as a
    PROVENANCE marker (records that the deck is a foreign import).

NOTE (2026-05-30): the stamp does NOT downgrade font severity. The earlier L1
behavior (imported → font rules advisory) was REVERTED — small body text is
unreadable regardless of origin and an off-size hero is still wrong, so the
validator flags them for every deck. The right font fix is enlarge-to-floor +
grow-box (small body) / hero at the layout's size — NOT a severity downgrade,
and NOT a px-snap that ignores the box. This tool only re-bundles the runtime
(auto-balance box-crowd); it never changes fonts. Full canvas-centering (L1
offset) is a separate auto-balance enhancement.

Usage:
  python3 assets/rebundle-import.py <deck.html>            # writes <deck>-rebundled.html
  python3 assets/rebundle-import.py <deck.html> --inplace  # edits in place (back up first)
"""
import sys
import re
import shutil
import argparse
import pathlib

ASSETS = pathlib.Path(__file__).resolve().parent
CUR_JS = ASSETS / "feishu-deck.js"
_RUNTIME_SIG = ("feishu-deck-h5 · runtime", "DESIGN_W = 1920", "function init()")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("deck", help="path to the foreign/imported deck .html")
    ap.add_argument("--inplace", action="store_true",
                    help="edit the deck in place (default: write <deck>-rebundled.html)")
    args = ap.parse_args()

    deck = pathlib.Path(args.deck).resolve()
    if not deck.exists():
        print(f"✗ not found: {deck}"); sys.exit(2)
    html = deck.read_text(encoding="utf-8")
    notes = []

    # 1. stamp imported origin as a PROVENANCE marker (no font-severity effect;
    #    L1's "imported → font advisory" was reverted — see module docstring)
    if "fs-deck-origin" not in html:
        html = html.replace(
            "</head>", '<meta name="fs-deck-origin" content="imported">\n</head>', 1)
        notes.append("stamped <meta fs-deck-origin=imported>(来源标记;不改字号严重度)")
    else:
        notes.append("已是 imported,跳过 stamp")

    # 2. re-bundle the framework runtime (linked OR inlined)
    # Allow other attributes (defer / type=module / crossorigin) and an optional
    # ?query / #fragment cache-buster on the src. Capture ONLY the path portion
    # (no query/fragment) for the path-traversal containment guard below.
    link_m = re.search(
        r'<script\b[^>]*\bsrc="([^"?#]*feishu-deck\.js)(?:[?#][^"]*)?"[^>]*>\s*</script>',
        html)
    if link_m:
        rel = link_m.group(1)
        target = (deck.parent / rel)
        if not target.resolve().is_relative_to(deck.parent.resolve()):
            # src points OUTSIDE the deck dir (e.g. ../../../skills/.../feishu-deck.js
            # — the SHARED skill runtime). Don't shutil.copy2 over the skill /
            # external file (path traversal / clobber).
            notes.append(f"linked runtime 指向 deck 目录外({rel})—— 跳过(不覆盖技能/外部文件)")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            old = target.read_text(encoding="utf-8") if target.exists() else ""
            had_ab = "data-fs-autobalanced" in old or "balanceSlide" in old
            shutil.copy2(CUR_JS, target)
            notes.append(f"linked runtime → 拷当前 feishu-deck.js 到 {target.name}"
                         f"（原版{'已含' if had_ab else '不含'} auto-balance）")
    else:
        cur_js = CUR_JS.read_text(encoding="utf-8")
        replaced = [0]

        def _repl(m):
            body = m.group(1)
            if replaced[0] == 0 and any(s in body for s in _RUNTIME_SIG):
                replaced[0] = 1
                return f"<script>{cur_js}</script>"
            return m.group(0)
        html = re.sub(r"<script>(.*?)</script>", _repl, html, flags=re.S)
        if replaced[0]:
            notes.append("inlined runtime → 替换框架 <script> 块为当前版")
        else:
            notes.append("⚠️ 没找到内联框架 runtime <script>(未 re-bundle JS)")

    out = deck if args.inplace else deck.with_name(deck.stem + "-rebundled" + deck.suffix)
    out.write_text(html, encoding="utf-8")
    print("rebundle-import:")
    for n in notes:
        print("  ·", n)
    print("  → 写出", out)
    print("  （auto-balance 加载时修 box-crowd;字号/chrome/内容零改动。"
          "字号问题仍由 validator 照报;修小字=enlarge+grow-box,修 hero=layout 尺寸。）")


if __name__ == "__main__":
    main()
