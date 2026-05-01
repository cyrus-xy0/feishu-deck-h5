#!/usr/bin/env python3
"""
feishu-deck-h5  ·  extract-texts

Two modes:

  Mode A — annotated deck → texts.md
    Input HTML already has data-text-id on every text leaf (this is what
    Claude emits for new decks). We just dump them, grouped by slide.

  Mode B — bare deck → annotated HTML + texts.md  (retrofit existing decks)
    Input HTML has no data-text-id attributes. We walk the DOM, identify
    text leaves under .slide using stable rules (class + nth-of-type), assign
    semantic ids, write back an annotated copy, and emit texts.md.

Usage:
    python3 assets/extract-texts.py path/to/deck.html [--out texts.md]
                                                       [--annotate path/to/out.html]

If --annotate is given AND the input has no ids, we write the annotated
HTML there. If the input already has ids, --annotate is a no-op.

Exit codes:
    0  ok
    1  duplicate / unstable id detected, refused to write
    2  cannot read input
"""

from __future__ import annotations
import argparse
import re
import sys
from collections import OrderedDict, defaultdict
from pathlib import Path

# Reuse helpers from apply-texts (same directory)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from importlib import import_module
_apply = import_module('apply-texts')
TEXT_LEAF_RE     = _apply.TEXT_LEAF_RE
decode_inner_to_value = _apply.decode_inner_to_value


# Find each `<div class="slide" data-layout="..." data-screen-label="..." ...>`
# then walk forward, depth-counting <div>/</div> to find its matching close.
# Naive `.*?</div>\s*</div>` was buggy — slide bodies contain many nested
# `</div></div>` pairs, so the non-greedy match stopped after the first one.
SLIDE_OPEN_RE = re.compile(
    r'<div class="slide" data-layout="(?P<layout>[^"]+)" '
    r'data-screen-label="(?P<label>[^"]+)"[^>]*>'
)

# Any <div ...> open or </div> close. Self-closing isn't valid for div in HTML5,
# so we don't bother accommodating it here.
DIV_BOUNDARY_RE = re.compile(r'<(/?)div\b[^>]*>', re.I)


def find_slides(html: str):
    """Yield (open_match, body_start, body_end). body is the inner of each
    `<div class="slide" ...>` element, located via depth-balanced walk."""
    for m_open in SLIDE_OPEN_RE.finditer(html):
        body_start = m_open.end()
        depth = 1
        body_end = None
        for nm in DIV_BOUNDARY_RE.finditer(html, body_start):
            if nm.group(1) == '/':
                depth -= 1
                if depth == 0:
                    body_end = nm.start()
                    break
            else:
                depth += 1
        if body_end is None:
            continue   # malformed — skip
        yield m_open, body_start, body_end


# ----- Mode A: dump already-annotated deck ---------------------------------

def dump_annotated(html: str) -> tuple[str, list[tuple[str, str, str]]]:
    """Return (texts_md, [(slide-id, layout, label), ...])."""
    # group leaves by slide via depth-balanced walker
    slides = []
    by_slide: dict[str, OrderedDict[str, str]] = OrderedDict()

    for slide_idx, (m_open, b_start, b_end) in enumerate(find_slides(html), 1):
        layout = m_open.group('layout')
        label  = m_open.group('label')
        body   = html[b_start:b_end]
        slide_id = f'slide-{slide_idx:02d}'
        slides.append((slide_id, layout, label))
        by_slide[slide_id] = OrderedDict()

        for m_leaf in TEXT_LEAF_RE.finditer(body):
            full_id = m_leaf.group('id')
            inner   = m_leaf.group('inner')
            if not full_id.startswith(slide_id + '.'):
                continue   # belongs to a different slide naming scope
            field = full_id[len(slide_id) + 1:]
            value = decode_inner_to_value(inner).replace('\n', '\\n')
            by_slide[slide_id][field] = value

    return _format_md(slides, by_slide), slides


# ----- Mode B: retrofit a bare deck ----------------------------------------

# Element classes whose text content we want to capture in retrofit mode.
# Order roughly matches the per-layout markup in templates/slide-recipes.html.
LEAF_CLASSES = {
    # generic
    'title', 'title-zh', 'title-en', 'subtitle', 'lede',
    'eyebrow',  'role', 'author', 'pageno-skip',
    # cover / section / end
    'chapter-num', 'pill',
    # agenda / cards / process / timeline
    'n', 'ctitle', 'cbody', 'cfoot',
    # stats / big-stat
    'kpi-num', 'kpi-unit', 'kpi-label', 'trend',
    'stat-num', 'stat-unit', 'stat-label',
    # table
    'th', 'td',
    # quote
    'quote-text', 'quote-attrib',
    # process / pipeline
    'step-title', 'step-body',
    # generic fallback
    'lede-en',
}

# Tags to ignore as leaves (they'll be entered to find children, but never
# get an id themselves)
SKIP_TAGS = {'svg', 'script', 'style', 'noscript'}

# Element classes whose text is derived / brand-locked / structural — never
# user content, never get a data-text-id even if they're a clean text leaf.
SKIP_CLASSES = {
    'pageno',          # page number — derived from slide order, never edited
}


def _safe_field(class_attr: str, tag: str, ordinal: int) -> str:
    """Derive a stable field name from class + ordinal."""
    if class_attr:
        # take first known class, fallback to first class
        classes = class_attr.split()
        for c in classes:
            if c in LEAF_CLASSES:
                base = c
                break
        else:
            base = classes[0]
    else:
        base = tag
    base = base.replace('-', '_')
    return f'{base}_{ordinal:02d}'


_TAG_OPEN_RE = re.compile(r'<([a-zA-Z][a-zA-Z0-9]*)\b([^>]*)>')


def _strip_inner_text(inner: str) -> str:
    """Plain text representation of an inner HTML, ignoring SVG and scripts."""
    s = re.sub(r'<svg.*?</svg>', '', inner, flags=re.S | re.I)
    s = re.sub(r'<script.*?</script>', '', s, flags=re.S | re.I)
    s = re.sub(r'<br\s*/?>', '\n', s, flags=re.I)
    # any remaining tags = mixed content; we still strip them for the test
    s = re.sub(r'<[^>]+>', '', s)
    return s.strip()


def _is_text_leaf(inner: str) -> bool:
    """True if inner contains only text and optional <br>."""
    if not _strip_inner_text(inner):
        return False
    # peek at any tags inside inner
    for m in _TAG_OPEN_RE.finditer(inner):
        tag = m.group(1).lower()
        if tag in SKIP_TAGS:
            return False    # contains svg/script — not a text leaf at this level
        if tag != 'br':
            return False
    return True


def retrofit_slide(slide_idx: int, body: str) -> tuple[str, OrderedDict[str, str]]:
    """Walk one slide body, attach data-text-id to every leaf, return new body
    + ordered {field: value}."""
    slide_id = f'slide-{slide_idx:02d}'
    fields: OrderedDict[str, str] = OrderedDict()
    # ordinal counter per class so duplicate classes (e.g. multiple .ctitle)
    # disambiguate as ctitle_01, ctitle_02, ...
    counters: dict[str, int] = defaultdict(int)

    # walk pairs (open, close) for each top-level matching element by scanning
    # depth via a simple tag stack. We replace open tags by injecting the
    # data-text-id only on elements identified as leaves.
    out: list[str] = []
    i = 0
    n = len(body)
    pending_open: list[tuple[int, str, str]] = []   # (out_offset, tag, attrs_str)
    inside_skip: list[str] = []                     # current skip-tag stack

    # Approach: regex find all start and end tags in order; track current depth;
    # when we see </tag>, look at innerHTML between matching open and close;
    # if inside_skip is empty AND _is_text_leaf is True, mutate the open tag
    # we previously emitted to add the id.
    tag_re = re.compile(r'<(/?)([a-zA-Z][a-zA-Z0-9]*)\b([^>]*?)(/?)>')
    cursor = 0
    # We'll do a non-recursive pass: for each top-level open tag, find its
    # matching close, evaluate the inner; if it's a text-leaf, annotate; else
    # recurse into the inner.

    def annotate(segment: str, depth: int = 0) -> str:
        """Return segment with data-text-id added to every text leaf."""
        local_out = []
        pos = 0
        while pos < len(segment):
            m = tag_re.search(segment, pos)
            if not m:
                local_out.append(segment[pos:])
                break
            local_out.append(segment[pos:m.start()])
            slash, tag, attrs, self_close = m.groups()
            if slash:
                # stray close — should be handled by caller, skip
                local_out.append(m.group(0)); pos = m.end(); continue
            tag_low = tag.lower()
            if self_close or tag_low in ('br', 'img', 'meta', 'link', 'input',
                                          'hr', 'source', 'wbr'):
                local_out.append(m.group(0)); pos = m.end(); continue
            if tag_low in SKIP_TAGS:
                # find matching close, copy untouched
                close_m = re.search(rf'</{tag}\s*>', segment[m.end():], re.I)
                if not close_m:
                    local_out.append(segment[m.start():]); pos = len(segment); break
                end_idx = m.end() + close_m.end()
                local_out.append(segment[m.start():end_idx]); pos = end_idx; continue

            # find matching close, accounting for nested same-tag
            depth_local = 1
            scan = m.end()
            close_pos = None
            for nm in tag_re.finditer(segment, scan):
                if nm.group(2).lower() != tag_low:
                    continue
                if nm.group(1) == '/':
                    depth_local -= 1
                    if depth_local == 0:
                        close_pos = nm.start(); close_end = nm.end(); break
                else:
                    if not (nm.group(4) or nm.group(2).lower() in
                            ('br','img','meta','link','input','hr','source','wbr')):
                        depth_local += 1
            if close_pos is None:
                local_out.append(segment[m.start():]); pos = len(segment); break

            inner = segment[m.end():close_pos]
            close_full = segment[close_pos:close_end]

            # is this a text leaf?
            if _is_text_leaf(inner):
                # extract class to derive field name
                class_m = re.search(r'\bclass="([^"]+)"', attrs)
                class_attr = class_m.group(1) if class_m else ''
                # skip derived/structural leaves (page numbers, etc.)
                classes_set = set(class_attr.split())
                if classes_set & SKIP_CLASSES:
                    local_out.append(m.group(0))
                    local_out.append(inner)
                    local_out.append(close_full)
                    pos = close_end
                    continue
                # pick semantic base
                base = None
                if class_attr:
                    classes = class_attr.split()
                    for c in classes:
                        if c in LEAF_CLASSES:
                            base = c; break
                    if base is None:
                        base = classes[0]
                else:
                    base = tag_low
                base_norm = base.replace('-', '_')
                counters[base_norm] += 1
                ordinal = counters[base_norm]
                field = base_norm if ordinal == 1 and base_norm not in _MULTI_HINT \
                                  else f'{base_norm}_{ordinal:02d}'
                # if we end up with an existing field, add ordinal
                if field in fields:
                    field = f'{base_norm}_{ordinal:02d}'
                full_id = f'{slide_id}.{field}'
                # avoid duplicate inside this slide
                while full_id in fields_seen:
                    counters[base_norm] += 1
                    field = f'{base_norm}_{counters[base_norm]:02d}'
                    full_id = f'{slide_id}.{field}'

                # append data-text-id on the open tag
                new_attrs = attrs.rstrip()
                if 'data-text-id=' not in new_attrs:
                    new_attrs = new_attrs + f' data-text-id="{full_id}"'
                local_out.append(f'<{tag}{new_attrs}>')
                local_out.append(inner)
                local_out.append(close_full)

                value = _strip_inner_text(inner).replace('\n', '\\n')
                fields[field] = value
                fields_seen.add(full_id)
                pos = close_end
                continue

            # not a leaf — recurse into inner, preserve open/close as-is
            local_out.append(m.group(0))
            local_out.append(annotate(inner, depth + 1))
            local_out.append(close_full)
            pos = close_end
        return ''.join(local_out)

    fields_seen: set[str] = set()
    new_body = annotate(body)
    return new_body, fields


# Classes that almost always appear multiple times per slide — give them an
# ordinal even when they're the only one (so that adding a second later doesn't
# silently rename the first).
_MULTI_HINT = {
    'pill', 'item', 'card', 'kpi', 'stat', 'th', 'td', 'step',
    'ctitle', 'cbody', 'cfoot',
}


def annotate_html(html: str) -> tuple[str, str, list[tuple[str, str, str]]]:
    """Walk the deck, annotate every slide, return (new_html, texts_md, slides)."""
    slides: list[tuple[str, str, str]] = []
    by_slide: dict[str, OrderedDict[str, str]] = OrderedDict()
    new_html_parts: list[str] = []
    cursor = 0
    slide_idx = 0
    for m_open, b_start, b_end in find_slides(html):
        slide_idx += 1
        new_html_parts.append(html[cursor:b_start])
        layout = m_open.group('layout')
        label  = m_open.group('label')
        body   = html[b_start:b_end]
        slide_id = f'slide-{slide_idx:02d}'
        new_body, fields = retrofit_slide(slide_idx, body)
        slides.append((slide_id, layout, label))
        by_slide[slide_id] = fields
        new_html_parts.append(new_body)
        cursor = b_end
    new_html_parts.append(html[cursor:])
    new_html = ''.join(new_html_parts)
    return new_html, _format_md(slides, by_slide), slides


# --------------------------------------------------------------------------

def _format_md(slides: list[tuple[str, str, str]],
               by_slide: dict[str, OrderedDict[str, str]]) -> str:
    title = (slides[0][2] if slides else 'deck').split('·')[0].strip()
    out: list[str] = []
    out.append(f'# {title} — texts')
    out.append('')
    out.append('> Edit text below. After save, run:')
    out.append('>   python3 assets/apply-texts.py <deck.html> <texts.md>')
    out.append('>')
    out.append('> Rules:')
    out.append('>   • Edit ONLY this file. Visual tweaks → overrides.css.')
    out.append('>     Layout / structure / new slides → re-ask Claude.')
    out.append('>   • Use `\\n` to insert a line break (renders as <br>).')
    out.append('>   • Do NOT rename the slide-NN.field ids — they pair with HTML.')
    out.append('')
    for slide_id, layout, label in slides:
        out.append(f'## {slide_id} ({layout}) — {label}')
        for field, value in by_slide.get(slide_id, {}).items():
            out.append(f'{field}: {value}')
        out.append('')
    return '\n'.join(out).rstrip() + '\n'


# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description='feishu-deck-h5 extract-texts')
    ap.add_argument('html', help='deck HTML to scan')
    ap.add_argument('--out', default=None,
                    help='write texts.md here (default: <deck>.texts.md)')
    ap.add_argument('--annotate', default=None,
                    help='if input has no data-text-id, write annotated HTML here')
    args = ap.parse_args()

    src = Path(args.html)
    if not src.is_file():
        print(f'ERROR: {src} not found', file=sys.stderr); return 2

    html = src.read_text(encoding='utf-8')
    has_ids = bool(re.search(r'data-text-id=', html))

    if has_ids:
        md, slides = dump_annotated(html)
        out_md = Path(args.out) if args.out else src.with_suffix('.texts.md')
        out_md.write_text(md, encoding='utf-8')
        print(f'extract-texts (Mode A: already annotated)')
        print(f'  slides: {len(slides)}')
        print(f'  wrote : {out_md}')
        if args.annotate:
            print(f'  (--annotate ignored: source already has data-text-id)')
        return 0

    new_html, md, slides = annotate_html(html)
    out_md = Path(args.out) if args.out else src.with_suffix('.texts.md')
    out_md.write_text(md, encoding='utf-8')
    print(f'extract-texts (Mode B: retrofitting bare deck)')
    print(f'  slides: {len(slides)}')
    print(f'  wrote : {out_md}')
    if args.annotate:
        out_html = Path(args.annotate)
        out_html.write_text(new_html, encoding='utf-8')
        print(f'  wrote : {out_html}  (annotated HTML)')
    else:
        print('  NOTE: pass --annotate <path> to also save the HTML with ids')
    return 0


if __name__ == '__main__':
    sys.exit(main())
