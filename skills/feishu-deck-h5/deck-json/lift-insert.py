#!/usr/bin/env python3
"""Insert one or more DeckJSON-native slides after a target page.

Fast path for requests shaped like:

    put source/index.html#14 and #15 after target/index.html#9

The helper keeps the high-risk parts deterministic:
  - resolves URL #N against the current deck order before writing;
  - delegates slide copying to deck-cli paste, so assets and key collisions use
    the standard path;
  - optionally localizes remote iframe-embed src URLs into prototypes/;
  - renders only the inserted pages to a temporary directory, then structurally
    inserts those .slide-frame chunks into the existing target index.html.

It intentionally avoids a full target re-render, so browser-edited or manually
patched pages elsewhere in the deck are not clobbered.
"""
from __future__ import annotations

import argparse
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.parse import unquote, urlparse
import urllib.request

HERE = Path(__file__).resolve().parent
DECK_CLI = HERE / "deck-cli.py"
RENDER_DECK = HERE / "render-deck.py"
SYNC_INDEX = HERE / "sync-index-to-deck.py"
VALIDATE_HTML = HERE.parent / "assets" / "validate.py"
SHOOT_PAGE = HERE.parent / "assets" / "shoot-page.py"

sys.path.insert(0, str(HERE))
from _safe_write import atomic_write_text, validate_and_write_deck  # noqa: E402


def _parse_ref(ref: str) -> tuple[Path, str | None]:
    if ref.startswith("file://"):
        parsed = urlparse(ref)
        if parsed.netloc and parsed.netloc not in ("", "localhost"):
            raise ValueError(f"only local file:// refs are supported: {ref}")
        return Path(unquote(parsed.path)).expanduser().resolve(), (parsed.fragment or None)
    if "#" in ref:
        path, frag = ref.rsplit("#", 1)
        return Path(path).expanduser().resolve(), (frag or None)
    return Path(ref).expanduser().resolve(), None


def _deck_and_index(path: Path) -> tuple[Path, Path]:
    if path.is_dir():
        deck = path / "deck.json"
        index = path / "index.html"
    elif path.name == "deck.json":
        deck = path
        index = path.with_name("index.html")
    elif path.suffix.lower() in (".html", ".htm"):
        index = path
        deck = path.with_name("deck.json")
    else:
        raise ValueError(f"unsupported deck ref: {path}")
    if not deck.is_file():
        raise FileNotFoundError(f"deck.json not found: {deck}")
    if not index.is_file():
        raise FileNotFoundError(f"index.html not found: {index}")
    return deck.resolve(), index.resolve()


def _load_deck(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _active_rows(deck: dict) -> list[tuple[int, int, dict]]:
    rows: list[tuple[int, int, dict]] = []
    frame = 0
    for raw_i, slide in enumerate(deck.get("slides") or []):
        if slide.get("_disabled"):
            continue
        frame += 1
        rows.append((frame, raw_i, slide))
    return rows


def _resolve_selector(deck: dict, selector: str | None, *, role: str) -> tuple[int, int, dict]:
    if not selector:
        raise ValueError(f"{role} ref needs #page or #slide-key")
    rows = _active_rows(deck)
    if selector.isdigit():
        n = int(selector)
        for frame, raw_i, slide in rows:
            if frame == n:
                return frame, raw_i, slide
        raise ValueError(f"{role} #{n} out of range; deck has {len(rows)} active slides")
    for frame, raw_i, slide in rows:
        if slide.get("key") == selector:
            return frame, raw_i, slide
    raise ValueError(f"{role} slide key not found: {selector}")


class FrameParser(HTMLParser):
    def __init__(self, html: str):
        super().__init__(convert_charrefs=False)
        self.html = html
        self.line_starts = [0]
        for idx, ch in enumerate(html):
            if ch == "\n":
                self.line_starts.append(idx + 1)
        self.div_depth = 0
        self.stack: list[dict[str, int | str | None]] = []
        self.frames: list[dict[str, int | str]] = []

    def abs_pos(self) -> int:
        line, col = self.getpos()
        return self.line_starts[line - 1] + col

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "div":
            return
        pos = self.abs_pos()
        data = {k: v or "" for k, v in attrs}
        classes = set(data.get("class", "").split())
        if "slide-frame" in classes:
            self.stack.append({"start": pos, "depth": self.div_depth, "key": None})
        if (self.stack and "slide" in classes and data.get("data-slide-key")
                and self.div_depth == int(self.stack[-1]["depth"]) + 1):
            self.stack[-1]["key"] = data["data-slide-key"]
        self.div_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag != "div":
            return
        pos = self.abs_pos()
        if self.stack and self.div_depth == int(self.stack[-1]["depth"]) + 1:
            end = self.html.find(">", pos)
            if end == -1:
                raise ValueError("malformed HTML: closing div without >")
            frame = self.stack.pop()
            key = frame.get("key")
            if isinstance(key, str) and key:
                self.frames.append({"key": key, "start": int(frame["start"]), "end": end + 1})
        self.div_depth -= 1


def _frame_chunks(html: str) -> dict[str, str]:
    parser = FrameParser(html)
    parser.feed(html)
    return {
        str(frame["key"]): html[int(frame["start"]):int(frame["end"])]
        for frame in parser.frames
    }


def _insert_frames(index_path: Path, rendered_index: Path, anchor_key: str, keys: list[str]) -> Path:
    target_html = index_path.read_text(encoding="utf-8")
    source_html = rendered_index.read_text(encoding="utf-8")
    target_parser = FrameParser(target_html)
    target_parser.feed(target_html)
    source_chunks = _frame_chunks(source_html)
    missing = [key for key in keys if key not in source_chunks]
    if missing:
        raise RuntimeError(f"rendered temp index is missing frame(s): {', '.join(missing)}")
    if anchor_key not in {str(frame["key"]) for frame in target_parser.frames}:
        raise RuntimeError(f"target index is missing anchor frame: {anchor_key}")

    move_set = set(keys)
    output: list[str] = []
    cursor = 0
    for frame in sorted(target_parser.frames, key=lambda item: int(item["start"])):
        key = str(frame["key"])
        start = int(frame["start"])
        end = int(frame["end"])
        output.append(target_html[cursor:start])
        if key not in move_set:
            output.append(target_html[start:end])
            if key == anchor_key:
                output.append("\n\n")
                output.append("\n\n".join(source_chunks[k] for k in keys))
        cursor = end
    output.append(target_html[cursor:])

    backup = index_path.with_name(f"{index_path.name}.bak-pre-lift-insert-{time.strftime('%Y%m%d-%H%M%S')}")
    shutil.copy2(index_path, backup)
    atomic_write_text(index_path, "".join(output))
    return backup


def _run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, text=True, capture_output=True)
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    if check and proc.returncode != 0:
        raise RuntimeError(f"command failed ({proc.returncode}): {' '.join(cmd)}")
    return proc


def _slug(s: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", s).strip("-._").lower()
    return stem or "iframe"


def _download_remote(src: str, dest: Path) -> None:
    req = urllib.request.Request(src, headers={"User-Agent": "feishu-deck-h5 lift-insert"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read()
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f".{dest.name}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, dest)


def _localize_remote_iframes(deck_path: Path, keys: list[str]) -> list[tuple[str, str, str]]:
    deck = _load_deck(deck_path)
    by_key = {s.get("key"): s for s in deck.get("slides") or []}
    changed: list[tuple[str, str, str]] = []
    for key in keys:
        slide = by_key.get(key)
        if not slide or slide.get("layout") != "iframe-embed":
            continue
        data = slide.get("data") or {}
        src = str(data.get("src") or "")
        parsed = urlparse(src)
        if parsed.scheme not in ("http", "https"):
            continue
        basename = Path(unquote(parsed.path)).name
        if basename and "." in basename:
            stem = Path(basename).stem
            suffix = Path(basename).suffix or ".html"
        else:
            stem = key
            suffix = ".html"
        rel = f"prototypes/{_slug(stem)}{suffix}"
        dest = deck_path.parent / rel
        print(f"  localizing remote iframe for {key}: {src} -> {rel}")
        _download_remote(src, dest)
        data["src"] = rel
        slide["data"] = data
        changed.append((key, src, rel))
    if changed:
        ok = validate_and_write_deck(deck_path, deck, "lift-insert-localize", strict=True)
        if not ok:
            raise RuntimeError("deck validation failed after iframe localization")
    return changed


def _active_index_for_key(deck: dict, key: str) -> int:
    for frame, _raw_i, slide in _active_rows(deck):
        if slide.get("key") == key:
            return frame
    raise ValueError(f"inserted key not found after write: {key}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Insert DeckJSON-native lifted pages after a target page.")
    ap.add_argument("--after", required=True, help="target index.html/deck.json/dir with #page or #key")
    ap.add_argument("sources", nargs="+", help="source index.html/deck.json/dir refs with #page or #key")
    ap.add_argument("--preserve-index", action="store_true",
                    help="pass --force to deck-cli paste and patch index.html structurally; use after checking browser edits must be preserved")
    ap.add_argument("--no-localize-remote-iframes", action="store_true",
                    help="leave iframe-embed http(s) src values remote")
    ap.add_argument("--dry-run", action="store_true", help="print the resolved plan and write nothing")
    ap.add_argument("--verify", action="store_true",
                    help="run single-page validate + screenshot for inserted pages after patching")
    args = ap.parse_args(argv)

    target_path, target_selector = _parse_ref(args.after)
    target_deck, target_index = _deck_and_index(target_path)
    target = _load_deck(target_deck)
    anchor_frame, anchor_raw_i, anchor_slide = _resolve_selector(target, target_selector, role="target")
    anchor_key = anchor_slide.get("key")
    if not anchor_key:
        raise ValueError("target anchor slide has no key")

    resolved_sources = []
    for ref in args.sources:
        src_path, src_selector = _parse_ref(ref)
        src_deck, src_index = _deck_and_index(src_path)
        src = _load_deck(src_deck)
        src_frame, _src_raw_i, src_slide = _resolve_selector(src, src_selector, role="source")
        src_key = src_slide.get("key")
        if not src_key:
            raise ValueError(f"source {ref} has no slide key")
        resolved_sources.append((src_deck, src_index, src_frame, src_key))

    insert_position = anchor_raw_i + 2
    print(f"target: {target_deck}")
    print(f"after:  #{anchor_frame} {anchor_key} -> insert position {insert_position}")
    for i, (src_deck, _src_index, src_frame, src_key) in enumerate(resolved_sources, 1):
        print(f"source {i}: #{src_frame} {src_key} from {src_deck}")
    if args.dry_run:
        return 0

    actual_keys: list[str] = []
    pos = insert_position
    for src_deck, _src_index, _src_frame, src_key in resolved_sources:
        cmd = [sys.executable, str(DECK_CLI), "--yes"]
        if args.preserve_index:
            cmd.append("--force")
        cmd += [str(target_deck), "paste", "--from", str(src_deck), "--key", src_key, str(pos)]
        proc = _run(cmd, check=False)
        if proc.returncode == 6 and not args.preserve_index:
            raise RuntimeError(
                "deck-cli refused because target index.html has browser-only edits. "
                "Run sync-index-to-deck.py --dry-run, then rerun lift-insert.py with "
                "--preserve-index if you need to keep the current index.html and avoid a full render."
            )
        if proc.returncode != 0:
            raise RuntimeError(f"deck-cli paste failed ({proc.returncode})")
        deck_after = _load_deck(target_deck)
        actual_key = deck_after["slides"][pos - 1].get("key")
        if not actual_key:
            raise RuntimeError(f"pasted slide at position {pos} has no key")
        actual_keys.append(actual_key)
        pos += 1

    if not args.no_localize_remote_iframes:
        _localize_remote_iframes(target_deck, actual_keys)

    with tempfile.TemporaryDirectory(prefix="lift-insert-render-") as tmp:
        tmpdir = Path(tmp)
        _run([sys.executable, str(RENDER_DECK), str(target_deck), str(tmpdir),
              "--scope", ",".join(actual_keys)])
        backup = _insert_frames(target_index, tmpdir / "index.html", anchor_key, actual_keys)
        print(f"  patched index.html with {len(actual_keys)} frame(s)")
        print(f"  backup: {backup}")

    _run([sys.executable, str(SYNC_INDEX), str(target_index), str(target_deck), "--dry-run"], check=False)

    if args.verify:
        deck_final = _load_deck(target_deck)
        for key in actual_keys:
            frame = _active_index_for_key(deck_final, key)
            _run([sys.executable, str(VALIDATE_HTML), str(target_index),
                  "--visual", "--scope-frames", str(frame), "--slide", str(frame)])
            out = target_index.parent / f".shoot-p{frame:02d}-{_slug(key)}.png"
            _run([sys.executable, str(SHOOT_PAGE), str(target_index), str(frame),
                  "--wait", "3000", "--cap", "60", "--out", str(out)])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
