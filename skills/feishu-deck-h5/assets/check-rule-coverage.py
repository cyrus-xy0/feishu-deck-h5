#!/usr/bin/env python3
"""feishu-deck-h5 · 规则覆盖自检 (anti-drift gate)

杜绝"规则三处维护、各自漂移"的硬闸门。规则只有一套源(validate 引擎),
本脚本检查另外两份"附属清单"是否还跟引擎对齐:

  ① 引擎全集  = validate.py / _validate_audits.py / _validate_common.py 里
                所有 iss.err/warn/warn_soft 与 lev/_lev 第一参的规则码 (权威源)
  ② FAMILIES  = check-only.py 的 FAMILIES 表 (--by-rule 工程师视图分组)
  ③ yaml      = business-rules.yaml 的业务文案 (逐页报告 / ingest 门禁)

引擎是唯一真理。② 和 ③ 必须 100% 覆盖 ①, 且不含 ① 里没有的死码。
任何缺口 → 退兜底句 / 落"未分类" / 死文案永不触发 —— 都是漂移。

用法:
  python3 check-rule-coverage.py          # 报告 + 退出码 (0=对齐, 1=漂移)
  python3 check-rule-coverage.py --quiet  # 只在漂移时打印

提取逻辑复用 check-only.py 的 enumerate_validate_rules() + FAMILIES, 不另起
一套扫描 —— 自检脚本本身也不许成为"第 N 处维护点"。
"""
import sys
import importlib.util
from pathlib import Path


def _load():
    here = Path(__file__).resolve().parent
    spec = importlib.util.spec_from_file_location("check_only", here / "check-only.py")
    co = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(co)
    engine = co.enumerate_validate_rules()
    families = {c for _name, codes in co.FAMILIES for c in codes}
    rules = co.load_business_rules()
    yaml_codes = {k for k, v in rules.items() if isinstance(v, dict)}
    return engine, families, yaml_codes


def main() -> int:
    quiet = '--quiet' in sys.argv
    engine, families, yaml_codes = _load()

    miss_fam = sorted(engine - families)       # 引擎有, FAMILIES 没列 → 落"未分类"
    miss_yaml = sorted(engine - yaml_codes)    # 引擎有, yaml 没文案 → 退兜底句
    dead_fam = sorted(families - engine)       # FAMILIES 有, 引擎无 → 死分组
    dead_yaml = sorted(yaml_codes - engine)    # yaml 有, 引擎无 → 死文案

    drift = bool(miss_fam or miss_yaml or dead_fam or dead_yaml)

    if drift:
        print('❌ 规则覆盖漂移 —— 三处不对齐:')
        print(f'   引擎={len(engine)}  FAMILIES={len(families)}  yaml={len(yaml_codes)}')
        if miss_yaml:
            print(f'\n  · yaml 缺业务文案 ({len(miss_yaml)}) —— 这些触发时会退兜底句, 业务看不懂:')
            print('      ' + ' '.join(miss_yaml))
            print('      修: 在 business-rules.yaml 各加一段 concern/symptom/consequence/fix')
        if miss_fam:
            print(f'\n  · FAMILIES 缺分组 ({len(miss_fam)}) —— 这些会落 --by-rule 的"未分类"段:')
            print('      ' + ' '.join(miss_fam))
            print('      修: 在 check-only.py 的 FAMILIES 表把它归到对应家族')
        if dead_yaml:
            print(f'\n  · yaml 死文案 ({len(dead_yaml)}) —— 引擎已不发这些码, 文案永不触发:')
            print('      ' + ' '.join(dead_yaml))
            print('      修: 从 business-rules.yaml 删掉, 或改成引擎真用的码名')
        if dead_fam:
            print(f'\n  · FAMILIES 死分组 ({len(dead_fam)}) —— 引擎已不发这些码:')
            print('      ' + ' '.join(dead_fam))
            print('      修: 从 check-only.py 的 FAMILIES 表删掉')
        print('\n规则只有一套源 (validate 引擎). 改了引擎的规则码, 这两份附属清单要同步.')
        return 1

    if not quiet:
        print(f'✅ 规则覆盖对齐 —— 引擎 / FAMILIES / yaml 三方都是 {len(engine)} 条, 无漂移。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
