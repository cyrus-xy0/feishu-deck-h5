#!/usr/bin/env python3
"""apply-text-pairs.py — 安全的 "只换字、不动结构" text-swap (audit F-44).

把一份 find/replace 对(通常由 text-swap workflow / agent 产出)程序化套进
deck.json,**只做字符串替换、绝不让 LLM 重写 markup**:

  · raw / schema 页 → per-slide `data.html` 子串替换(结构 / CSS / SVG /
    data-text-id 100% 不动);
  · canvas 页(PPTX/混合导入)→ `data.elements[].runs[].text` 按「整 run 精确
    匹配(strip 后相等)」替换(几何 / id / 每个 run 的字号色重 100% 不动)。
    extract-text-pairs.py 对 canvas 走 runs_from_canvas 抽 strip 后的 run 文本,
    本工具按同一粒度套回 —— 两端对齐。翻译 canvas deck 前通常先跑
    merge-canvas-lines.py 把 PDF 抽词拆碎的同行碎片合并成整逻辑行再抽译。

lift 一份外来 deck 后要把文案换成新客户时用:让 agent 只产出
`[{key, replacements:[{find,replace}]}]`,本工具负责确定性套用 + 报告未命中
(raw 页常见未命中 = 源/产物间 <br>/emoji/空白归一化差异,需手查)。

Pairs 文件格式 (JSON)：
    [
      {"key": "cover", "replacements": [
        {"find": "星巴克", "replace": "众安保险"},
        {"find": "门店",   "replace": "保单"}
      ]},
      ...
    ]
其中 key 匹配 deck.json slide 的 data-slide-key。缺 key 的页不动。

用法:
    python3 apply-text-pairs.py <deck.json> <pairs.json> [--dry-run] [--force]

    --dry-run  只报告每页将命中/未命中多少,不写盘
    --force    绕过乐观锁(并发改动检查),强制写回

退出码: 0 成功 / 2 文件错误 / 4 并发改动被拒(乐观锁) / 5 有未命中(非 dry-run
仍会写已命中的,但以 5 退出提示你手查未命中项)
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path


def load_pairs(pairs_path: Path) -> dict:
    """Return {slide_key: [(find, replace), ...]} from the pairs JSON."""
    data = json.loads(pairs_path.read_text(encoding="utf-8"))
    by_key: dict[str, list[tuple[str, str]]] = {}
    for entry in data:
        key = entry.get("key")
        if not key:
            continue
        reps = []
        for r in entry.get("replacements", []):
            f = r.get("find", "")
            if f:
                reps.append((f, r.get("replace", "")))
        if reps:
            by_key.setdefault(key, []).extend(reps)
    return by_key


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="安全套用 find/replace text-swap 对到 deck.json(只换字不动结构, F-44)")
    ap.add_argument("deck", type=Path, help="目标 deck.json")
    ap.add_argument("pairs", type=Path, help="find/replace 对的 JSON")
    ap.add_argument("--dry-run", action="store_true",
                    help="只报告命中/未命中,不写盘")
    ap.add_argument("--force", action="store_true",
                    help="绕过并发改动(乐观锁)检查,强制写回")
    args = ap.parse_args(argv)

    if not args.deck.is_file():
        print(f"apply-text-pairs: deck 不存在: {args.deck}", file=sys.stderr)
        return 2
    if not args.pairs.is_file():
        print(f"apply-text-pairs: pairs 不存在: {args.pairs}", file=sys.stderr)
        return 2

    try:
        by_key = load_pairs(args.pairs)
    except json.JSONDecodeError as e:
        print(f"apply-text-pairs: pairs JSON 解析失败: {e}", file=sys.stderr)
        return 2

    # Optimistic lock (F-48/F-53 同款): 记读时 mtime,写回前比对。
    deck_mtime = args.deck.stat().st_mtime
    try:
        deck = json.loads(args.deck.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"apply-text-pairs: deck JSON 解析失败: {e}", file=sys.stderr)
        return 2

    total = hit = miss = 0
    miss_list: list[tuple[str, str]] = []
    # C8: finds that matched NOTHING on a CANVAS slide get an explicit,
    # separately-listed warning — the most common cause is a phrase split across
    # multiple format runs (PowerPoint format-split), which the per-run matcher
    # cannot match by design. The operator must hand-resolve these.
    canvas_miss_list: list[tuple[str, str]] = []
    touched_keys: set[str] = set()
    seen_keys = {s.get("key") for s in deck.get("slides", [])}

    for s in deck.get("slides", []):
        reps = by_key.get(s.get("key"), [])
        if not reps:
            continue
        data = s.get("data") or {}
        h = data.get("html")
        if not isinstance(h, str):
            elements = data.get("elements")
            if isinstance(elements, list) and elements:
                # canvas 页 — 文本在 elements[].runs[].text。按「整 run strip 后相等」
                # 替换(extract-text-pairs 对 canvas 抽的就是 strip 后的 run 文本)。
                # 只改 run["text"];id / 几何 / 其它每-run 样式字段一律不动。
                for f, t in reps:
                    total += 1
                    n = 0
                    for el in elements:
                        if el.get("type") != "text":
                            continue
                        for run in el.get("runs") or []:
                            txt = run.get("text", "")
                            if isinstance(txt, str) and txt.strip() == f:
                                run["text"] = t
                                n += 1
                    if n:
                        hit += 1
                        touched_keys.add(s["key"])
                    else:
                        miss += 1
                        miss_list.append((s.get("key"), f[:40]))
                        canvas_miss_list.append((s.get("key"), f[:40]))
                s["data"] = data
                continue
            # 既无 data.html 也无 canvas elements — text-swap 不适用,提示
            for f, _t in reps:
                miss_list.append((s.get("key"), f"(该页无 data.html/canvas, 跳过) {f[:30]}"))
                total += 1
                miss += 1
            continue
        for f, t in reps:
            total += 1
            n = h.count(f)
            if n:
                h = h.replace(f, t)
                hit += 1
                touched_keys.add(s["key"])
            else:
                miss += 1
                miss_list.append((s.get("key"), f[:40]))
        data["html"] = h
        s["data"] = data

    # pairs 里引用了 deck 中不存在的 key — 单独提示
    orphan_keys = sorted(set(by_key) - {k for k in seen_keys if k})

    print(f"apply-text-pairs: {hit}/{total} 命中, {miss} 未命中, "
          f"touched {len(touched_keys)} 页"
          + (" [dry-run, 未写盘]" if args.dry_run else ""))
    if orphan_keys:
        print(f"  ⚠ pairs 引用了 deck 中不存在的 key: {', '.join(orphan_keys)}")
    if miss_list:
        print("  --- 未命中(常见原因: 源/产物间 <br>/emoji/全半角/空白归一化差异, 需手查)---")
        for k, f in miss_list[:40]:
            print(f"    [{k}] {f}")
        if len(miss_list) > 40:
            print(f"    … 还有 {len(miss_list) - 40} 条")
    if canvas_miss_list:
        # C8: per-run-match limitation. A canvas find matches ONLY when it equals a
        # SINGLE run's stripped text; a phrase split across multiple format runs
        # (PowerPoint format-split) can never match and must be hand-resolved
        # (or pre-merged where same-style with merge-canvas-lines.py).
        print(f"  ⚠ {len(canvas_miss_list)} canvas find(s) matched NO run — likely a phrase "
              "split across multiple FORMAT runs (per-run match limitation); hand-resolve these:")
        for k, f in canvas_miss_list[:40]:
            print(f"    [{k}] {f!r}")
        if len(canvas_miss_list) > 40:
            print(f"    … 还有 {len(canvas_miss_list) - 40} 条")

    if args.dry_run:
        return 5 if miss else 0

    if hit == 0:
        print("  (0 命中, 不写盘)")
        return 5 if miss else 0

    # 乐观锁: 写回前确认没被并发改过
    if (not args.force
            and abs(args.deck.stat().st_mtime - deck_mtime) > 1e-6):
        print(f"\n✗ {args.deck.name} 自读取后已被其他进程改动(并发编辑);"
              f"重读后重试, 或 --force 覆盖", file=sys.stderr)
        return 4

    # Timestamped backup (collision-safe) — a FIXED name let a second text-swap
    # run overwrite the only pre-first-swap backup, losing the original.
    import datetime
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    bak = args.deck.parent / f"{args.deck.name}.bak-pre-textswap-{ts}"
    n = 0
    while bak.exists():
        n += 1
        bak = args.deck.parent / f"{args.deck.name}.bak-pre-textswap-{ts}.{n}"
    bak.write_text(args.deck.read_text(encoding="utf-8"), encoding="utf-8")
    args.deck.write_text(
        json.dumps(deck, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"  ✓ 写回 {args.deck.name} (备份 {bak.name})")
    return 5 if miss else 0


if __name__ == "__main__":
    sys.exit(main())
