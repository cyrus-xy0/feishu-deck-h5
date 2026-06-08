#!/usr/bin/env python3
"""rerender-deck.py — 重渲一份已存在的 canvas deck.json, 保住前端增强 + 自包含.

canvas deck(layout:canvas,build_pptx.py 代码重建产物;若有 bg/ 像素背景则叠加)的
index.html 不是 render-deck.py 单独能产全的:还需要 canvas_finish 的两步收尾——
  · make_portable  : 框架 CSS/JS 拷进 assets/ 并改写成 deck 本地相对引用(可移动);
  · post_process   : 注入 letterbox 背景 CSS + fitText 超框自适配脚本(文字贴合不裁切)。

直接 `render-deck.py deck.json out` 会丢这两步 → 资源 404 / 文字溢出被裁。
翻译(apply-text-pairs)或编辑改过 canvas deck.json 后,用本脚本一条命令重渲:

    python3 rerender-deck.py <deck.json> <out_dir> [--renderer DIR]

它只跑 render + make_portable + post_process —— 秒级(背景图 bg/ 与原图 input/ 若有
则已在 out_dir 里)。依赖方向正确:本脚本在 pptx-to-deck(它本就依赖 feishu-deck-h5
当渲染后端),不让 base 反向耦合。
"""
from __future__ import annotations
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

# post_process / make_portable / _default_renderer 住在同目录的 canvas_finish
# (纯 stdlib,无 fitz/PIL)— 混合管线退役后这三个收尾件剥到此处共用。
sys.path.insert(0, str(Path(__file__).resolve().parent))
from canvas_finish import post_process, make_portable, _default_renderer  # noqa: E402


def rerender(deck_path: Path, out: Path, renderer: Path) -> None:
    deck = json.loads(deck_path.read_text(encoding="utf-8"))
    render = renderer / "deck-json/render-deck.py"
    # C3: internal render — suppress render-deck.py's auto-snapshot so re-renders
    # (e.g. after translation / edit) don't trip a deck-log making-of snapshot.
    render_env = {**os.environ, "DECK_LOG_NO_AUTOSNAP": "1"}
    subprocess.run([sys.executable, str(render), str(deck_path), str(out),
                    "--skip-copy-assets", "--skip-validate-html"],
                   check=True, capture_output=True, text=True, timeout=600,
                   env=render_env)
    make_portable(out, renderer)
    post_process(out, deck)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="重渲已存在的混合 canvas deck.json(render + 自包含 + 前端增强)")
    ap.add_argument("deck", type=Path, help="deck.json(其 bg/ 与 input/ 资产应已在 out_dir)")
    ap.add_argument("out_dir", type=Path, help="deck 输出目录(含 bg/ input/)")
    ap.add_argument("--renderer", type=Path, default=_default_renderer(),
                    help="feishu-deck-h5 skill 根(默认自动定位兄弟目录)")
    args = ap.parse_args(argv)

    if not args.deck.is_file():
        print(f"rerender-deck: deck 不存在: {args.deck}", file=sys.stderr)
        return 2
    if not (args.renderer / "deck-json/render-deck.py").is_file():
        print(f"rerender-deck: renderer 无效(找不到 deck-json/render-deck.py): "
              f"{args.renderer}", file=sys.stderr)
        return 2
    try:
        rerender(args.deck, args.out_dir, args.renderer)
    except subprocess.CalledProcessError as e:
        print(f"rerender-deck: render-deck.py 失败:\n{e.stderr}", file=sys.stderr)
        return 1
    except subprocess.TimeoutExpired:
        print("rerender-deck: render-deck.py 超时(>600s)", file=sys.stderr)
        return 1
    print(f"==> 重渲完成 → {args.out_dir / 'index.html'}(自包含 + 前端增强)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
