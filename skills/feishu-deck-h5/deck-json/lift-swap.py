#!/usr/bin/env python3
"""Atomic single-slide lift+swap helper.

This is the fast/safe path for requests shaped like:

    lift source/index.html#10 into target/index.html#10

It wraps assets/lift-slides.py --replace, but adds the business-level guardrails
that are easy to forget when composing commands by hand:

  - understands file://...#N, path#N, and key fragments;
  - resolves target index.html -> sibling deck.json automatically;
  - makes one pre-write backup and restores it on any failure;
  - asserts page count and key set are unchanged after the swap;
  - prints the exact scoped render command, without running a whole-deck pass.

The target slot keeps its own key and screen_label. Only that slide's body/style
payload is replaced by the lifted source slide.
"""
from __future__ import annotations

import argparse
import contextlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import unquote, urlparse

try:
    import fcntl
except ImportError:  # pragma: no cover - POSIX gets the real lock.
    fcntl = None


HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent
LIFT_SLIDES = SKILL_ROOT / "assets" / "lift-slides.py"
RENDER_DECK = HERE / "render-deck.py"


def _atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.lift-swap.tmp")
    try:
        tmp.write_text(text, encoding=encoding)
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def _parse_ref(ref: str) -> tuple[Path, str | None]:
    """Return (local_path, fragment) for file://...#N or ordinary path#N."""
    if ref.startswith("file://"):
        parsed = urlparse(ref)
        if parsed.netloc and parsed.netloc not in ("localhost", ""):
            raise ValueError(f"only local file:// refs are supported: {ref}")
        return Path(unquote(parsed.path)).expanduser().resolve(), (parsed.fragment or None)
    if "#" in ref:
        path, frag = ref.rsplit("#", 1)
        return Path(path).expanduser().resolve(), (frag or None)
    return Path(ref).expanduser().resolve(), None


def _source_index(path: Path) -> Path:
    if path.is_dir():
        path = path / "index.html"
    elif path.name == "deck.json":
        path = path.with_name("index.html")
    if path.suffix.lower() not in (".html", ".htm"):
        raise ValueError(f"source must be index.html, deck.json sibling, or deck dir: {path}")
    if not path.is_file():
        raise FileNotFoundError(f"source index.html not found: {path}")
    return path


def _target_deck_and_output(path: Path) -> tuple[Path, Path]:
    if path.is_dir():
        deck = path / "deck.json"
        out_dir = path
    elif path.name == "deck.json":
        deck = path
        out_dir = path.parent
    elif path.suffix.lower() in (".html", ".htm"):
        deck = path.with_name("deck.json")
        out_dir = path.parent
    else:
        raise ValueError(f"target must be index.html, deck.json, or output dir: {path}")
    if not deck.is_file():
        raise FileNotFoundError(f"target deck.json not found: {deck}")
    return deck.resolve(), out_dir.resolve()


def _load_deck(deck_path: Path) -> dict:
    try:
        return json.loads(deck_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"cannot read target deck.json: {deck_path}: {exc}") from exc


def _keys(deck: dict) -> list[str | None]:
    return [s.get("key") for s in deck.get("slides") or []]


def _resolve_target_index(deck: dict, selector: str | None) -> int:
    slides = deck.get("slides") or []
    if not selector:
        raise ValueError("target ref needs a #page or #slide-key fragment")
    sel = selector.strip()
    if sel.isdigit():
        idx = int(sel)
        if 1 <= idx <= len(slides):
            return idx
        raise ValueError(f"target #{idx} out of range; target deck has {len(slides)} slides")
    for i, slide in enumerate(slides, start=1):
        if slide.get("key") == sel:
            return i
    raise ValueError(f"target slide key not found: {sel}")


def _load_lift_module():
    spec = importlib.util.spec_from_file_location("_lift_slides", LIFT_SLIDES)
    if not spec or not spec.loader:
        raise RuntimeError(f"cannot import {LIFT_SLIDES}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _source_arg_and_layout(src_index: Path, selector: str | None) -> tuple[list[str], str | None, int]:
    if not selector:
        raise ValueError("source ref needs a #page or #slide-key fragment")
    sel = selector.strip()
    lift_mod = _load_lift_module()
    rows = lift_mod.build_manifest(src_index)
    if sel.isdigit():
        frame = int(sel)
        if not (1 <= frame <= len(rows)):
            raise ValueError(f"source #{frame} out of range; source has {len(rows)} frames")
        row = rows[frame - 1]
        return [str(frame)], row.get("layout"), frame
    for row in rows:
        if row.get("key") == sel:
            return ["--key", sel], row.get("layout"), int(row["frame_index"])
    raise ValueError(f"source slide key not found: {sel}")


def _backup_path(deck_path: Path) -> Path:
    ts = time.strftime("%Y%m%d-%H%M%S")
    base = deck_path.with_name(f"{deck_path.name}.bak-pre-lift-swap-{ts}")
    if not base.exists():
        return base
    n = 1
    while True:
        cand = deck_path.with_name(f"{base.name}.{n}")
        if not cand.exists():
            return cand
        n += 1


def _restore(deck_path: Path, original_text: str) -> None:
    _atomic_write_text(deck_path, original_text)


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    return proc


@contextlib.contextmanager
def _deck_lock(deck_path: Path):
    lock_path = deck_path.parent / f".{deck_path.name}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+", encoding="utf-8") as fh:
        if fcntl is not None:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Atomic single-page lift+swap from source#index into target#index.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  lift-swap.py file:///a/src/output/index.html#10 file:///b/out/index.html#10\n"
            "  lift-swap.py /a/src/index.html#knowledge /b/out/deck.json#target-key --render\n"
        ),
    )
    ap.add_argument("source", help="source index.html/deck dir/deck.json with #page or #key")
    ap.add_argument("target", help="target index.html/deck dir/deck.json with #page or #key")
    shake = ap.add_mutually_exclusive_group()
    shake.add_argument("--shake", dest="shake", action="store_true",
                       help="force lift-slides.py --shake")
    shake.add_argument("--no-shake", dest="shake", action="store_false",
                       help="force no --shake")
    ap.set_defaults(shake=None)
    ap.add_argument("--keep-title", action="store_true",
                    help="keep the target slot's visible title while replacing body content")
    ap.add_argument("--force", action="store_true",
                    help="pass --force through to lift-slides.py optimistic-lock check")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the resolved plan and write nothing")
    ap.add_argument("--render", action="store_true",
                    help="after a successful swap, run one scoped render --scope N --shoot")
    ap.add_argument("--render-force", action="store_true",
                    help="with --render, pass --force to render-deck.py")
    args = ap.parse_args(argv)

    try:
        src_path, src_frag = _parse_ref(args.source)
        tgt_path, tgt_frag = _parse_ref(args.target)
        src_index = _source_index(src_path)
        deck_path, out_dir = _target_deck_and_output(tgt_path)
        source_args, source_layout, source_frame = _source_arg_and_layout(src_index, src_frag)
    except Exception as exc:
        print(f"lift-swap: {exc}", file=sys.stderr)
        return 2

    auto_shake = bool(source_layout and source_layout != "raw")
    use_shake = auto_shake if args.shake is None else bool(args.shake)

    with _deck_lock(deck_path):
        before_text = deck_path.read_text(encoding="utf-8")
        before_deck = _load_deck(deck_path)
        replace_index = _resolve_target_index(before_deck, tgt_frag)
        before_keys = _keys(before_deck)
        before_count = len(before_keys)
        target_key = before_keys[replace_index - 1]

        print("lift-swap plan")
        print(f"  source: {src_index}#{src_frag}  (frame {source_frame}, layout={source_layout or '?'})")
        print(f"  target: {deck_path}#{replace_index}  (key={target_key})")
        print(f"  output: {out_dir}")
        print(f"  shake : {use_shake} ({'auto: non-raw source layout' if args.shake is None else 'explicit'})")

        if args.dry_run:
            print("dry-run: no files changed")
            return 0

        bak = _backup_path(deck_path)
        shutil.copy2(deck_path, bak)
        print(f"  backup: {bak.name}")

        cmd = [sys.executable, str(LIFT_SLIDES), str(src_index), *source_args,
               str(deck_path), str(out_dir), "--replace", str(replace_index)]
        if use_shake:
            cmd.append("--shake")
        if args.keep_title:
            cmd.append("--keep-title")
        if args.force:
            cmd.append("--force")

        proc = _run(cmd)
        if proc.returncode != 0:
            _restore(deck_path, before_text)
            print(f"lift-swap: lift failed; restored {deck_path.name} from pre-swap state",
                  file=sys.stderr)
            return proc.returncode

        try:
            after_deck = _load_deck(deck_path)
            after_keys = _keys(after_deck)
            if len(after_keys) != before_count:
                raise RuntimeError(f"page count changed {before_count} -> {len(after_keys)}")
            if after_keys != before_keys:
                raise RuntimeError("slide key order changed; single-slot replace must preserve key set")
            if after_keys[replace_index - 1] != target_key:
                raise RuntimeError(
                    f"target slot key changed {target_key!r} -> {after_keys[replace_index - 1]!r}")
        except Exception as exc:
            _restore(deck_path, before_text)
            print(f"lift-swap: guard failed; restored pre-swap deck.json: {exc}",
                  file=sys.stderr)
            return 7

        print(f"✓ lift-swap guard passed: {before_count} slides, key order unchanged")

    render_cmd = [sys.executable, str(RENDER_DECK), str(deck_path), str(out_dir),
                  "--scope", str(replace_index), "--shoot"]
    if args.render_force:
        render_cmd.append("--force")
    if args.render:
        rproc = _run(render_cmd)
        if rproc.returncode != 0:
            print("lift-swap: scoped render failed; deck.json swap remains applied",
                  file=sys.stderr)
            return rproc.returncode
    else:
        print("next:")
        print("  " + " ".join(str(x) for x in render_cmd))
    return 0


if __name__ == "__main__":
    sys.exit(main())
