#!/usr/bin/env python3
"""
feishu-deck-h5  ·  deck-edit

Precision editing tool for feishu-deck HTML files.
Supports structured modification commands that target specific slides/fields.

Usage:
    python3 deck-edit.py <deck.html> --list                    # list all editable fields
    python3 deck-edit.py <deck.html> --set slide-04.title "新标题"  # set a field value
    python3 deck-edit.py <deck.html> --set slide-08.card1-body "新内容"
    python3 deck-edit.py <deck.html> --replace "旧文字" "新文字"   # global find & replace
    python3 deck-edit.py <deck.html> --slide 4 --title "新标题"    # slide-oriented syntax
    python3 deck-edit.py <deck.html> --batch edits.json          # batch edits from JSON
    python3 deck-edit.py <deck.html> --diff                     # show current vs texts.md diff

All modifications are applied to the linked HTML (not inline).
After editing, re-run inline-assets.py to regenerate the inline version.

Exit codes:
    0  ok
    1  field not found / bad arguments
    2  io error
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

TEXT_LEAF_RE = re.compile(
    r'(<(?P<tag>[a-zA-Z][a-zA-Z0-9]*)\s[^<>]*?'
    r'data-text-id="(?P<id>[^"]+)"[^<>]*?>)'
    r'(?P<inner>(?:(?!</(?P=tag)>).)*?)'
    r'(?P<close></(?P=tag)>)',
    re.S,
)

SLIDE_KEY_RE = re.compile(r'data-slide-key="([^"]+)"')
SCREEN_LABEL_RE = re.compile(r'data-screen-label="([^"]*)"')
LAYOUT_RE = re.compile(r'data-layout="([^"]+)"')


def find_leaves(html: str):
    found = []
    for m in TEXT_LEAF_RE.finditer(html):
        found.append({
            'id': m.group('id'),
            'start': m.start(),
            'end': m.end(),
            'open_tag': m.group(1),
            'inner': m.group('inner'),
            'close_tag': m.group('close'),
            'full': m.group(0),
        })
    return found


def find_slides(html: str):
    slides = []
    for m in re.finditer(r'<div class="slide"\s[^>]*?>', html):
        chunk_start = m.start()
        slide_html = html[chunk_start:chunk_start + 500]
        key_m = SLIDE_KEY_RE.search(slide_html)
        label_m = SCREEN_LABEL_RE.search(slide_html)
        layout_m = LAYOUT_RE.search(slide_html)
        slides.append({
            'key': key_m.group(1) if key_m else '',
            'label': label_m.group(1) if label_m else '',
            'layout': layout_m.group(1) if layout_m else '',
            'pos': chunk_start,
        })
    return slides


def decode_inner(inner: str) -> str:
    s = re.sub(r'<br\s*/?>', '\n', inner, flags=re.I)
    s = s.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    return s.strip()


def encode_value(value: str) -> str:
    parts = value.split('\n')
    escaped = [
        p.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        for p in parts
    ]
    return '<br>'.join(escaped)


def cmd_list(html: str):
    leaves = find_leaves(html)
    slides = find_slides(html)

    slide_num = 0
    current_slide_pos = -1
    for s in slides:
        slide_num += 1
        current_slide_pos = s['pos']
        print(f'\n📄 Slide {slide_num:02d} — {s["label"]} (layout={s["layout"]}, key={s["key"]})')

        for lf in leaves:
            if lf['start'] < current_slide_pos:
                continue
            if slide_num < len(slides) and lf['start'] >= slides[slide_num]['pos'] if slide_num < len(slides) else False:
                break
            value = decode_inner(lf['inner'])
            field = lf['id'].split('.', 1)[1] if '.' in lf['id'] else lf['id']
            preview = value[:60].replace('\n', '\\n')
            if len(value) > 60:
                preview += '…'
            print(f'  {lf["id"]:40s} = {preview}')

    for lf in leaves:
        if lf['start'] >= slides[-1]['pos'] if slides else True:
            value = decode_inner(lf['inner'])
            field = lf['id'].split('.', 1)[1] if '.' in lf['id'] else lf['id']
            preview = value[:60].replace('\n', '\\n')
            print(f'  {lf["id"]:40s} = {preview}')

    print(f'\n总计: {len(leaves)} 个可编辑字段, {len(slides)} 页')


def cmd_set(html: str, field_id: str, new_value: str, no_backup: bool = False) -> str:
    leaves = find_leaves(html)
    target = None
    for lf in leaves:
        if lf['id'] == field_id:
            target = lf
            break

    if not target:
        close_matches = [lf['id'] for lf in leaves if field_id in lf['id']]
        print(f'❌ 字段未找到: {field_id}', file=sys.stderr)
        if close_matches:
            print(f'   相似字段:', file=sys.stderr)
            for cm in close_matches[:5]:
                print(f'     - {cm}', file=sys.stderr)
        return html

    old_value = decode_inner(target['inner'])
    if old_value == new_value:
        print(f'⏭️  {field_id}: 值未变化，跳过')
        return html

    new_inner = encode_value(new_value)
    new_full = target['open_tag'] + new_inner + target['close_tag']
    new_html = html[:target['start']] + new_full + html[target['end']:]

    print(f'✅ {field_id}:')
    print(f'   - {old_value!r}')
    print(f'   + {new_value!r}')
    return new_html


def cmd_replace(html: str, old_text: str, new_text: str, no_backup: bool = False) -> str:
    leaves = find_leaves(html)
    changes = 0
    new_html = html

    for lf in reversed(leaves):
        value = decode_inner(lf['inner'])
        if old_text in value:
            new_value = value.replace(old_text, new_text)
            new_inner = encode_value(new_value)
            new_full = lf['open_tag'] + new_inner + lf['close_tag']
            new_html = new_html[:lf['start']] + new_full + new_html[lf['end']:]
            print(f'✅ {lf["id"]}: "{old_text}" → "{new_text}"')
            changes += 1

    if changes == 0:
        print(f'❌ 未找到匹配文本: "{old_text}"', file=sys.stderr)
    else:
        print(f'\n共修改 {changes} 处')
    return new_html


def cmd_batch(html: str, edits_path: str) -> str:
    with open(edits_path, 'r', encoding='utf-8') as f:
        edits = json.load(f)

    new_html = html
    total = 0

    for edit in edits:
        if 'id' in edit and 'value' in edit:
            new_html = cmd_set(new_html, edit['id'], edit['value'], no_backup=True)
            total += 1
        elif 'find' in edit and 'replace' in edit:
            new_html = cmd_replace(new_html, edit['find'], edit['replace'])
            total += 1

    print(f'\n批量编辑完成: {total} 条指令')
    return new_html


def cmd_diff(html: str, texts_path: str):
    if not texts_path or not Path(texts_path).is_file():
        print('❌ 需要指定 texts.md 路径 (--texts)', file=sys.stderr)
        return

    from pathlib import Path
    texts_md = Path(texts_path).read_text(encoding='utf-8')

    SLIDE_HEADER_RE = re.compile(r'^##\s+(slide-\d+)\b')
    KV_RE = re.compile(r'^([A-Za-z0-9_.\-]+)\s*:\s*(.*)$')

    md_texts = {}
    current_slide = None
    for line in texts_md.splitlines():
        m = SLIDE_HEADER_RE.match(line)
        if m:
            current_slide = m.group(1)
            continue
        m = KV_RE.match(line)
        if m and current_slide:
            md_texts[f'{current_slide}.{m.group(1)}'] = m.group(2).replace('\\n', '\n')

    leaves = find_leaves(html)
    drifts = 0
    for lf in leaves:
        html_val = decode_inner(lf['inner'])
        if lf['id'] in md_texts:
            md_val = md_texts[lf['id']]
            if html_val != md_val:
                print(f'⚠️  {lf["id"]} 漂移:')
                print(f'   HTML: {html_val!r}')
                print(f'   MD:   {md_val!r}')
                drifts += 1

    if drifts == 0:
        print('✅ HTML 和 texts.md 完全同步')
    else:
        print(f'\n⚠️  发现 {drifts} 处漂移')


def main() -> int:
    ap = argparse.ArgumentParser(
        description='feishu-deck-h5 deck-edit — precision editing tool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # 列出所有可编辑字段
  %(prog)s deck.html --list

  # 修改单个字段
  %(prog)s deck.html --set slide-04.title "新标题"

  # 全局查找替换
  %(prog)s deck.html --replace "飞书AI录音豆" "飞书妙记"

  # 批量编辑（从 JSON 文件）
  %(prog)s deck.html --batch edits.json

  # 检查 HTML 与 texts.md 的同步状态
  %(prog)s deck.html --diff --texts texts.md
""")
    ap.add_argument('html', help='deck HTML file')
    ap.add_argument('--list', action='store_true', help='list all editable fields')
    ap.add_argument('--set', nargs=2, metavar=('ID', 'VALUE'), help='set field value')
    ap.add_argument('--replace', nargs=2, metavar=('OLD', 'NEW'), help='global find & replace')
    ap.add_argument('--batch', metavar='JSON', help='batch edits from JSON file')
    ap.add_argument('--diff', action='store_true', help='check drift vs texts.md')
    ap.add_argument('--texts', help='texts.md path (for --diff)')
    ap.add_argument('--no-backup', action='store_true', help='skip .bak backup')
    ap.add_argument('--dry-run', action='store_true', help='preview changes, write nothing')

    args = ap.parse_args()

    html_path = Path(args.html)
    if not html_path.is_file():
        print(f'ERROR: {html_path} not found', file=sys.stderr)
        return 2

    html = html_path.read_text(encoding='utf-8')

    if args.list:
        cmd_list(html)
        return 0

    new_html = html

    if args.set:
        new_html = cmd_set(html, args.set[0], args.set[1])

    elif args.replace:
        new_html = cmd_replace(html, args.replace[0], args.replace[1])

    elif args.batch:
        new_html = cmd_batch(html, args.batch)

    elif args.diff:
        cmd_diff(html, args.texts)
        return 0

    else:
        ap.print_help()
        return 1

    if new_html is html:
        return 0

    if args.dry_run:
        print('\n(dry-run, wrote nothing)')
        return 0

    if not args.no_backup:
        bak = html_path.with_suffix(html_path.suffix + '.bak')
        shutil.copy2(html_path, bak)
        print(f'📦 备份: {bak.name}')

    html_path.write_text(new_html, encoding='utf-8')
    print(f'💾 已写入: {html_path.name}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
