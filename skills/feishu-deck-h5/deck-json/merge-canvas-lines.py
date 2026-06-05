#!/usr/bin/env python3
"""merge-canvas-lines.py — 把 PDF 抽词拆碎的 canvas 同行碎片合并成整逻辑行.

混合管线(pptx-to-deck build_pptx_hybrid)用 LibreOffice 把幻灯片渲成 PDF 再抽
文字位置时,**一条视觉文本行常被 PDF 抽词拆成许多各自定位的小 text 元素**
(常单字一个),彼此边到边相接。逐元素翻译 CJK→EN 会乱;本工具按几何把它们
聚类还原成逻辑行,让 extract/apply-text-pairs 能对「整行」操作。

算法(每个 canvas 页):
  1. 按样式签名分组 = (round(size), color, font) —— 一条行的碎片同字号同色同体。
  2. 组内按中心 y 分行(band):y 差 ≤ y_tol 视为同一视觉行。
  3. 行内按 x 排序,在水平间距 > gap_max 处切段(段内 = 边到边相接的碎片;
     段间 = 不同列/独立标签,间距远)。
  4. 多元素段 → 合并:文本按 x 序拼进**最左 host** 的首 run(沿用 host 字号色重),
     host.w 扩展到覆盖整段;**其余 sibling 元素整体删除**(不留空 run,避免
     extract 抽到空串 / 渲染留空盒)。单元素段不动 → 幂等(再跑一次是 no-op)。

只改 layout==canvas 页;不新增元素;id / 几何外字段不动。结构安全。

阈值默认按字号自适配:gap_max = max(12, size*gap_scale),y_tol = max(8, size*y_tol_scale)。
经验:一行碎片间距 0~10px,跨列/独立标签间距 100px+,默认 0.6 能干净区分。
复杂打散页(文字叠图、负间距重叠)仍可能小误合 —— 用 --review 落清单人工核。

用法:
    python3 merge-canvas-lines.py <deck.json> [--dry-run] [--force]
        [--gap-scale 0.6] [--y-tol-scale 0.6] [--review <out.json>]

退出码: 0 成功 / 2 文件错误 / 4 并发改动被拒(乐观锁)
"""
from __future__ import annotations
import argparse
import datetime
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

CJK = re.compile(r"[㐀-鿿豈-﫿]")


def _el_text(el) -> str:
    parts = []
    for r in el.get("runs", []):
        t = r.get("text", "")
        parts.append(t if isinstance(t, str) else ("" if t is None else str(t)))
    return "".join(parts)


def _sig(run) -> tuple:
    """Style signature shared by fragments of one line: size + color + font + grad.

    grad (gradient-text fill) is part of the signature (C7): two fragments that
    differ ONLY in grad are different logical runs and must not be merged into one
    line (that would erase one fragment's gradient onto the host's solid/other grad).
    grad may be a dict — normalize to a stable hashable key for grouping."""
    grad = run.get("grad")
    if isinstance(grad, (dict, list)):
        grad = json.dumps(grad, sort_keys=True, ensure_ascii=False)
    return (round(float(run.get("size", 0))), run.get("color"), run.get("font"), grad)


def merge_slide(slide, gap_scale: float, y_tol_scale: float) -> list:
    """Mutate one canvas slide's elements in place. Return merge records."""
    data = slide.get("data") or {}
    els = [e for e in data.get("elements", [])
           if e.get("type") == "text" and e.get("runs")]
    drop_ids = set()
    records = []
    groups: dict[tuple, list] = defaultdict(list)
    for e in els:
        groups[_sig(e["runs"][0])].append(e)

    for (size, _color, _font, _grad), gels in groups.items():
        y_tol = max(8.0, size * y_tol_scale)
        gap_max = max(12.0, size * gap_scale)
        # band by center-y
        gels.sort(key=lambda e: e.get("y", 0) + e.get("h", 0) / 2)
        bands: list[list] = []
        for e in gels:
            cy = e.get("y", 0) + e.get("h", 0) / 2
            if bands and abs(cy - bands[-1][0]) <= y_tol:
                row = bands[-1][1]
                row.append(e)
                bands[-1][0] = (bands[-1][0] * (len(row) - 1) + cy) / len(row)
            else:
                bands.append([cy, [e]])
        # within each band, sort by x and split into x-contiguous segments
        for _cy, row in bands:
            row.sort(key=lambda e: e.get("x", 0))
            seg = [row[0]]
            segments = [seg]
            for prev, cur in zip(row, row[1:]):
                gap = cur.get("x", 0) - (prev.get("x", 0) + prev.get("w", 0))
                if gap > gap_max:
                    seg = [cur]
                    segments.append(seg)
                else:
                    seg.append(cur)
            for seg in segments:
                if len(seg) < 2:
                    continue
                merged = "".join(_el_text(e) for e in seg)
                host = seg[0]
                right = max(e.get("x", 0) + e.get("w", 0) for e in seg)
                host["w"] = round(right - host.get("x", 0), 2)
                host_run = dict(host["runs"][0])
                host_run["text"] = merged
                host["runs"] = [host_run]
                for e in seg[1:]:
                    drop_ids.add(id(e))
                records.append({
                    "host_id": host.get("id"),
                    "n_elements": len(seg),
                    "member_ids": [e.get("id") for e in seg],
                    "merged_text": merged,
                    "has_cjk": bool(CJK.search(merged)),
                })

    if drop_ids:
        data["elements"] = [e for e in data.get("elements", [])
                            if id(e) not in drop_ids]
    return records


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="把 PDF 抽词拆碎的 canvas 同行碎片合并成整逻辑行(翻译/编辑前置归一化)")
    ap.add_argument("deck", type=Path, help="目标 deck.json")
    ap.add_argument("--dry-run", action="store_true", help="只报告合并,不写盘")
    ap.add_argument("--force", action="store_true", help="绕过乐观锁,强制写回")
    ap.add_argument("--gap-scale", type=float, default=0.6,
                    help="水平切段阈值 = max(12, size*gap_scale)(默认 0.6)")
    ap.add_argument("--y-tol-scale", type=float, default=0.6,
                    help="同行 y 容差 = max(8, size*y_tol_scale)(默认 0.6)")
    ap.add_argument("--review", type=Path, help="把每页合并清单落成 JSON 供人工核对")
    args = ap.parse_args(argv)

    if not args.deck.is_file():
        print(f"merge-canvas-lines: deck 不存在: {args.deck}", file=sys.stderr)
        return 2

    deck_mtime = args.deck.stat().st_mtime
    try:
        deck = json.loads(args.deck.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"merge-canvas-lines: deck JSON 解析失败: {e}", file=sys.stderr)
        return 2

    review = []
    n_canvas = n_merged = n_dropped = 0
    for s in deck.get("slides", []):
        if s.get("layout") != "canvas":
            continue
        n_canvas += 1
        before = len((s.get("data") or {}).get("elements", []))
        recs = merge_slide(s, args.gap_scale, args.y_tol_scale)
        after = len((s.get("data") or {}).get("elements", []))
        n_merged += len(recs)
        n_dropped += before - after
        if recs:
            review.append({"key": s.get("key"), "merged": recs})

    print(f"merge-canvas-lines: {n_canvas} canvas 页, 合并 {n_merged} 条逻辑行"
          f"(删除 {n_dropped} 个碎片元素)"
          + (" [dry-run, 未写盘]" if args.dry_run else ""))

    # L7: write the --review sidecar even under --dry-run (the natural preflight:
    # `--dry-run --review` to inspect what WOULD merge without touching the deck).
    # The old `not args.dry_run` condition silently produced no file in that case.
    if args.review and n_merged > 0:
        args.review.write_text(
            json.dumps(review, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"  ✓ 合并清单 → {args.review}"
              + (" [dry-run]" if args.dry_run else ""))
    elif args.review and n_merged == 0:
        print(f"  (无可合并条目, 未写 --review {args.review})")

    if args.dry_run or n_merged == 0:
        if n_merged == 0:
            print("  (无可合并碎片, 不写盘)")
        return 0

    if (not args.force
            and abs(args.deck.stat().st_mtime - deck_mtime) > 1e-6):
        print(f"\n✗ {args.deck.name} 自读取后已被其他进程改动;重读重试或 --force",
              file=sys.stderr)
        return 4

    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    bak = args.deck.parent / f"{args.deck.name}.bak-pre-merge-{ts}"
    n = 0
    while bak.exists():
        n += 1
        bak = args.deck.parent / f"{args.deck.name}.bak-pre-merge-{ts}.{n}"
    bak.write_text(args.deck.read_text(encoding="utf-8"), encoding="utf-8")
    args.deck.write_text(
        json.dumps(deck, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"  ✓ 写回 {args.deck.name} (备份 {bak.name})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
