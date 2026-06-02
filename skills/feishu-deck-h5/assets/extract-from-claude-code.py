#!/usr/bin/env python3
"""extract-from-claude-code.py — Claude Code adapter for the canonical
PROMPTS.md log format (see PROMPTS-format.md next to this file).

This is ONE OF SEVERAL adapters. Each agent (Claude Code, Codex, Mira,
Cursor, Aider, …) stores transcripts differently; each needs its own
adapter. They all emit the same canonical PROMPTS.md so downstream
analysis tools don't care which agent produced the prompts.

Source: Claude Code's per-session transcripts at
  ~/.claude/projects/<encoded-cwd>/<session-id>.jsonl
Each line is a JSON entry; `type:user` + string content + no system-
prefix tag = real user-authored prompt.

The canonical analysis path consumes PROMPTS.md, NOT these JSONL files.
Future analysis tools (`analyze-prompts.py`) read PROMPTS.md and never
go back to source transcripts. Adapters are decoupled from analysis.

Usage:

    # one transcript → stdout
    python3 extract-from-claude-code.py SESSION.jsonl

    # multiple transcripts → file, filtered to one deck
    python3 extract-from-claude-code.py ~/.claude/projects/*/sess*.jsonl \\
        --filter-deck ai-consumer-growth \\
        --out runs/<ts>/output/PROMPTS.md

Tagging is heuristic by design:

  - slide refs come from `#NN` matches in the prompt text
  - modification type comes from a leading-prefix check + keyword scan
    (confirm / add-slide / init / bug-report / delete / edit-slide /
    meta), see `classify()` below

If a tag looks wrong, edit the keyword lists — DO NOT introduce an LLM
classifier here. Prompt log integrity matters more than tag accuracy;
later analysis can re-tag with fresh rules.
"""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

# ---- Tag patterns -----------------------------------------------------------

# `#17` → slide ordinal reference (the hash convention deck.js uses).
# IMPORTANT: don't add `(?<![\w#])` lookbehind — user prompts very often
# include URLs like `…/index.html#17` where the char before `#` IS a word
# char. Plain `#NN\b` is fine; false positives (e.g. issue #123) are rare
# in deck-authoring prompts.
SLIDE_HASH_RE = re.compile(r'#(\d{1,3})\b')

# `slide-NN` text mention (less common in prompts but possible)
SLIDE_KEY_RE = re.compile(r'\bslide[-_](\d{1,3})\b', re.IGNORECASE)

# `runs/<timestamp>-<slug>/...`  — deck-dir path mentions
DECK_PATH_RE = re.compile(r'runs/(\d{8}-\d{6}-[\w-]+)/')

# Skip user-entries whose content starts with these system-injected tags.
# These are not user-authored prompts — they're slash-command echoes,
# command stdouts, environment caveats, and post-tool system reminders.
SYSTEM_PREFIXES = (
    '<command-name>',
    '<command-message>',
    '<command-args>',
    '<command-stdout>',
    '<command-stderr>',
    '<local-command-caveat>',
    '<system-reminder>',
)

# Modification type — first matching keyword wins. Order matters:
# bug-report > delete > edit-slide > init. `confirm` is detected by
# regex (short messages only); `meta` is the fallback for anything
# that doesn't classify.
TYPE_KEYWORDS = [
    ('bug-report', [
        # visual position / overflow
        '位置', '靠下', '靠上', '靠左', '靠右', '重叠', '溢出', '出界',
        '挤', '太空', '没对齐', '不对齐', '错位',
        # font / sizing
        '字小', '字大', '小了', '大了', '层级不',
        # color / contrast
        '颜色不对', '太暗', '太亮', '融背景', '看不清', '褪色',
        # generic dissatisfaction
        '不对', '有问题', '错了', '丑', '难看', '炸了', '崩了', '坏了',
        'overflow', 'overlap', 'broken', 'wrong', 'misaligned',
    ]),
    ('delete', [
        '删', '去掉', '不要了', '砍掉', '移除',
        'delete', 'remove', 'drop',
    ]),
    ('edit-slide', [
        # change verbs
        '改', '换', '调整', '修', '替换', '更新', '调',
        # additive (still slide-level edit)
        '加一页', '加一张', '加', '插入', '追加',
        'edit', 'change', 'add', 'fix', 'replace', 'tweak',
    ]),
    ('init', [
        '做一份', '起草', '做一个', '新建', '从头', '开始做',
        '帮我做', '生成一个', 'create', 'init', 'start',
    ]),
]

# `confirm`: very short approval / continuation messages. Matched by
# regex on the WHOLE message — must be tight so "加一页 X" doesn't get
# misclassified as a confirmation.
CONFIRM_RE = re.compile(
    r'^(OK|ok|好|好的|对|对的|可以|加|嗯|嗯嗯|是|是的|继续|push|commit|'
    r'go|go ahead|yes|y|done|完了|搞|来|开始|先执行|执行吧|先执行吧|'
    r'同意|赞成|approved?)[\s。,，.!！？?~～\-]*$'
)

# `add-slide`: when the prompt STARTS with "下一页" / "第N页" / "再加一页"
# etc., it's a new-slide briefing — the rest of the prompt is the slide's
# CONTENT, which may contain bug-keywords by coincidence (e.g. marketing
# copy "整体溢出"). Detect leading-prefix BEFORE the bug-keyword scan so
# this content doesn't get misclassified as a complaint.
ADD_SLIDE_PREFIX_RE = re.compile(
    r'^\s*('
    r'下一页|下一張|下一张|'             # next page
    r'第[一二三四五六七八九十百\d]+页|'    # 第N页
    r'第[一二三四五六七八九十百\d]+张|'
    r'再做一页|再加一页|再来一页|'
    r'新增一页|新加一页|插入一页|'
    r'接下来一页|接下来做|接下来'
    r')'
)
# Same idea for explicit deck-start prompts.
DECK_INIT_PREFIX_RE = re.compile(
    r'^\s*('
    r'帮我(画|做|生成|起草|起|搞|搞一个)(一个|一份)?(新的|新)?deck|'
    r'(新|new)\s*deck|'
    r'起草一份|从头(做|来)|做一份|做一个deck|'
    r'生成一个(deck|HTML|h5)'
    r')',
    re.IGNORECASE,
)

# ---- Helpers ----------------------------------------------------------------

def classify(text: str) -> str:
    """Guess modification type from prompt text.

    Order:
      1. confirm (short OK / 加 / push)
      2. add-slide (leading "下一页" / "第N页" — content brief, BUG keywords
         inside the brief are coincidental, not complaints)
      3. deck-init (leading "帮我做一个 deck" / "起草" — same logic)
      4. bug-report (keyword scan)
      5. delete / edit-slide / meta
    """
    s = text.strip()
    if len(s) < 30 and CONFIRM_RE.match(s):
        return 'confirm'
    # Leading-prefix detection BEFORE bug-keyword scan so that slide-content
    # briefs (which may contain marketing words like "溢出" / "看不清" /
    # "不对") don't get misclassified as visual bug reports.
    if ADD_SLIDE_PREFIX_RE.match(s):
        return 'add-slide'
    if DECK_INIT_PREFIX_RE.match(s):
        return 'init'
    for typ, kws in TYPE_KEYWORDS:
        if any(kw in s for kw in kws):
            return typ
    return 'meta'


def extract_slide_refs(text: str) -> list:
    """Pull slide references — `#NN` hash and `slide-NN` mentions."""
    refs = set()
    for m in SLIDE_HASH_RE.finditer(text):
        refs.add(f'#{m.group(1)}')
    for m in SLIDE_KEY_RE.finditer(text):
        refs.add(f'#{m.group(1)}')
    return sorted(refs, key=lambda r: int(r[1:]))


def extract_deck_refs(text: str) -> list:
    """Pull deck-dir slugs mentioned in the prompt."""
    return sorted(set(m.group(1) for m in DECK_PATH_RE.finditer(text)))


def parse_iso(ts: str):
    """Parse ISO timestamp; tolerate trailing Z."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace('Z', '+00:00'))
    except Exception:
        return None


def iter_user_prompts(path: Path):
    """Yield (timestamp, content, cwd, session_id) for each real user prompt
    in a Claude Code transcript JSONL.

    Skips:
      - non-user entries
      - tool results (content is a list, not a string)
      - system-prefixed entries (slash commands, caveats, reminders)
      - empty content
    """
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if e.get('type') != 'user':
                continue
            msg = e.get('message')
            if not isinstance(msg, dict):
                continue
            content = msg.get('content')
            if isinstance(content, list):
                # User messages can be list-of-blocks (text + attachments) — pull
                # the text blocks. tool_result/tool_use blocks contribute nothing,
                # so a pure tool-result message still yields '' and is skipped
                # below (the old code dropped ALL list content, losing real
                # user-authored prompts that arrive as blocks).
                content = '\n'.join(
                    b.get('text', '') for b in content
                    if isinstance(b, dict) and b.get('type') == 'text')
            if not isinstance(content, str):
                continue
            content = content.strip()
            if not content:
                continue
            if any(content.startswith(p) for p in SYSTEM_PREFIXES):
                continue
            yield {
                'ts': e.get('timestamp', ''),
                'content': content,
                'cwd': e.get('cwd', ''),
                'session': e.get('sessionId', ''),
            }


# ---- Main -------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description='Extract user prompts from Claude Code transcripts '
                    'into a clean PROMPTS.md log.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split('Usage:', 1)[-1] if 'Usage:' in __doc__ else None,
    )
    ap.add_argument('transcripts', nargs='+', type=Path,
                    help='one or more Claude Code transcript JSONL files '
                         '(usually under ~/.claude/projects/.../*.jsonl)')
    ap.add_argument('--out', '-o', type=Path,
                    help='write PROMPTS.md to this path (default: stdout)')
    ap.add_argument('--filter-deck', '-d',
                    help='only keep prompts whose text or cwd mentions this '
                         'deck slug or run-dir name '
                         '(e.g. "ai-consumer-growth")')
    ap.add_argument('--filter-cwd',
                    help='only keep prompts whose cwd matches this path '
                         '(useful when one transcript spans multiple projects)')
    ap.add_argument('--title',
                    help='title for the output markdown')
    args = ap.parse_args()

    entries = []
    for path in args.transcripts:
        if not path.exists():
            print(f'WARN: {path} not found, skipping', file=sys.stderr)
            continue
        # Collect ALL prompts in this transcript first.
        session_prompts = []
        for e in iter_user_prompts(path):
            if args.filter_cwd and args.filter_cwd not in e['cwd']:
                continue
            e['transcript'] = path.name
            session_prompts.append(e)
        # Apply --filter-deck at the SESSION level: if ANY prompt (or its
        # cwd) in this transcript mentions the slug, keep ALL prompts
        # from this session. A single conversation usually focuses on
        # one deck — once we know the session "is about" that deck,
        # confirm-style prompts ("加", "OK") deserve to be kept too,
        # since they're part of the deck's authoring history.
        if args.filter_deck:
            session_touches_deck = any(
                args.filter_deck in p['content'] or args.filter_deck in p['cwd']
                for p in session_prompts
            )
            if not session_touches_deck:
                continue
        entries.extend(session_prompts)

    # Sort by timestamp (lexicographic ISO works)
    entries.sort(key=lambda x: x['ts'])

    # Render markdown
    title = args.title or 'Prompts log'
    lines = [f'# {title}', '']
    deck_refs = set()
    for e in entries:
        deck_refs.update(extract_deck_refs(e['content']))
        if e['cwd']:
            m = re.search(r'runs/(\d{8}-\d{6}-[\w-]+)/', e['cwd'])
            if m:
                deck_refs.add(m.group(1))
    lines.append(
        f'> Extracted **{len(entries)}** user prompts from '
        f'**{len(args.transcripts)}** transcript(s) at '
        f'{datetime.now().strftime("%Y-%m-%d %H:%M")}.'
    )
    if deck_refs:
        lines.append(f'> Decks referenced: {", ".join(sorted(deck_refs))}.')
    lines.append('>')
    lines.append('> Each entry: `## <timestamp>  <type>  <slide-refs>`.')
    lines.append('> Types: `init / add-slide / bug-report / edit-slide / '
                 'delete / confirm / meta` (keyword heuristic; see '
                 '`classify()` in extract-from-claude-code.py).')
    lines.append('')

    # Stats summary
    type_counts = {}
    for e in entries:
        t = classify(e['content'])
        type_counts[t] = type_counts.get(t, 0) + 1
    if type_counts:
        lines.append('**By type**: '
                     + ' · '.join(f'{t}={n}' for t, n in
                                  sorted(type_counts.items(),
                                         key=lambda x: -x[1])))
        lines.append('')

    # Entries
    for e in entries:
        ts = parse_iso(e['ts'])
        ts_str = ts.strftime('%Y-%m-%d %H:%M:%S') if ts else e['ts'] or '?'
        typ = classify(e['content'])
        refs = extract_slide_refs(e['content'])
        refs_str = (' ' + ' '.join(refs)) if refs else ''
        lines.append(f'## {ts_str}  `{typ}`{refs_str}')
        # Block-quote the prompt; preserve multi-line structure.
        for ln in e['content'].split('\n'):
            lines.append('> ' + ln if ln else '>')
        lines.append('')

    output = '\n'.join(lines)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(output, encoding="utf-8")
        print(f'wrote {len(entries)} prompts → {args.out}', file=sys.stderr)
    else:
        sys.stdout.write(output)


if __name__ == '__main__':
    main()
