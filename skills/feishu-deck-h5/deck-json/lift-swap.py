#!/usr/bin/env python3
"""Plan-first, transactional single-slide lift+swap helper.

This is the fast/safe path for requests shaped like:

    lift source/index.html#10 into target/index.html#10

It wraps assets/lift-slides.py --replace, but adds machine-enforced direction,
fidelity, and transaction guardrails:

  - understands file://...#N, path#N, and key fragments;
  - requires a read-only plan before named --source/--target may write;
  - binds the plan to both endpoint titles and current file fingerprints;
  - treats cross-deck source control files as byte-read-only;
  - stages the complete target and commits it atomically only after render+shot;
  - asserts page count and key set are unchanged after the swap;
  - rejects same-deck trees unless explicitly allowed.

The target slot keeps its own key and screen_label. Only that slide's body/style
payload is replaced by the lifted source slide.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import json
import os
import shlex
import shutil
import subprocess
import sys
import uuid
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


def _load_insert_module():
    """Reuse lift-insert's already-tested staging and tree fingerprint helpers."""
    path = HERE / "lift-insert.py"
    spec = importlib.util.spec_from_file_location("_lift_insert", path)
    if not spec or not spec.loader:
        raise RuntimeError(f"cannot import {path}")
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


def _source_page_details(src_index: Path, frame: int) -> tuple[str | None, str]:
    lift_mod = _load_lift_module()
    lines = src_index.read_text(encoding="utf-8").splitlines(keepends=True)
    starts = lift_mod.find_frame_lines(lines)
    if not (1 <= frame <= len(starts)):
        raise ValueError(f"source #{frame} out of range; source has {len(starts)} frames")
    start = starts[frame - 1]
    end = starts[frame] - 1 if frame < len(starts) else len(lines)
    info, inner = lift_mod.extract_one(lines, start, end)
    title = lift_mod._slide_visible_title(inner) or info.get("label") or "(no visible title)"
    return info.get("key"), str(title)


def _target_title(slide: dict) -> str:
    lift_mod = _load_lift_module()
    html = ((slide.get("data") or {}).get("html") or "")
    return lift_mod._slide_visible_title(html) or slide.get("screen_label") or "(no visible title)"


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_snapshot(src_index: Path) -> tuple[tuple[str, int, str], ...]:
    """Fingerprint source control files; a cross-deck lift must never change them."""
    names = ("index.html", "deck.json", "slide-index.json")
    rows = []
    for name in names:
        path = src_index.with_name(name)
        if path.is_file():
            rows.append((name, path.stat().st_size, _hash_file(path)))
    return tuple(rows)


def _same_artifact(src_index: Path, target_dir: Path) -> bool:
    src_dir = src_index.parent.resolve()
    target_dir = target_dir.resolve()
    return (src_dir == target_dir
            or src_dir in target_dir.parents
            or target_dir in src_dir.parents)


def _plan_token(plan: dict) -> str:
    payload = json.dumps(plan, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def _commit_staged_directory(stage_dir: Path, target_dir: Path,
                             expected_fingerprint) -> None:
    insert_mod = _load_insert_module()
    if insert_mod._tree_fingerprint(target_dir) != expected_fingerprint:
        raise RuntimeError(
            "destination changed while lift-swap was running; staged result was not committed")

    backup = target_dir.parent / f".{target_dir.name}.lift-swap-rollback-{uuid.uuid4().hex}"
    os.replace(target_dir, backup)
    try:
        os.replace(stage_dir, target_dir)
    except BaseException as swap_error:
        try:
            os.replace(backup, target_dir)
        except BaseException as restore_error:
            raise RuntimeError(
                f"staged commit failed and automatic restore failed; recover "
                f"{target_dir} from {backup}: {restore_error}") from swap_error
        raise
    try:
        shutil.rmtree(backup)
    except OSError as exc:
        print(f"  warning: committed, but rollback directory remains: {backup} ({exc})",
              file=sys.stderr)


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
        description=("Plan-first, transactional single-page lift+swap from "
                     "source#index into target#index."),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  # Step 1: read-only plan (default)\n"
            "  lift-swap.py --source file:///a/src/index.html#10 "
            "--target file:///b/out/index.html#3\n"
            "  # Step 2: copy the printed token exactly\n"
            "  lift-swap.py --source file:///a/src/index.html#10 "
            "--target file:///b/out/index.html#3 --apply --confirm TOKEN\n"
            "\nLegacy positional SRC DST is accepted for planning only; it can never write.\n"
        ),
    )
    ap.add_argument("refs", nargs="*", metavar="REF",
                    help="legacy positional SRC DST refs (read-only plan only)")
    ap.add_argument("--source", help="READ-ONLY source index.html/deck dir/deck.json with #page or #key")
    ap.add_argument("--target", help="WRITABLE target index.html/deck dir/deck.json with #page or #key")
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
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true",
                      help="apply a previously reviewed plan; requires --confirm TOKEN")
    mode.add_argument("--dry-run", action="store_true",
                      help="deprecated alias for the default read-only plan")
    ap.add_argument("--confirm", metavar="TOKEN",
                    help="exact plan token printed by the immediately preceding read-only run")
    ap.add_argument("--render", action="store_true",
                    help="deprecated compatibility flag; --apply always renders and shoots")
    ap.add_argument("--render-force", action="store_true",
                    help="with --apply, pass --force to the staged scoped render")
    ap.add_argument("--allow-same-deck", action="store_true",
                    help="explicitly allow source and target inside the same deck tree")
    args = ap.parse_args(argv)

    named = bool(args.source or args.target)
    if named:
        if args.refs:
            print("lift-swap: do not mix positional refs with --source/--target",
                  file=sys.stderr)
            return 2
        if not args.source or not args.target:
            missing = "--source" if not args.source else "--target"
            print(f"lift-swap: missing {missing}; both endpoints are mandatory",
                  file=sys.stderr)
            return 2
        source_ref, target_ref = args.source, args.target
    else:
        if len(args.refs) != 2:
            print("lift-swap: need two endpoints: --source SRC --target DST",
                  file=sys.stderr)
            return 2
        source_ref, target_ref = args.refs
        if args.apply:
            print("lift-swap: writes require named --source and --target; "
                  "legacy positional refs are plan-only", file=sys.stderr)
            return 2

    try:
        src_path, src_frag = _parse_ref(source_ref)
        tgt_path, tgt_frag = _parse_ref(target_ref)
        src_index = _source_index(src_path)
        deck_path, out_dir = _target_deck_and_output(tgt_path)
        source_args, source_layout, source_frame = _source_arg_and_layout(src_index, src_frag)
    except Exception as exc:
        print(f"lift-swap: {exc}", file=sys.stderr)
        return 2

    auto_shake = bool(source_layout and source_layout != "raw")
    use_shake = auto_shake if args.shake is None else bool(args.shake)

    with _deck_lock(deck_path):
        before_deck = _load_deck(deck_path)
        replace_index = _resolve_target_index(before_deck, tgt_frag)
        before_keys = _keys(before_deck)
        before_count = len(before_keys)
        target_key = before_keys[replace_index - 1]
        target_slide = before_deck["slides"][replace_index - 1]
        source_key, source_title = _source_page_details(src_index, source_frame)
        target_title = _target_title(target_slide)
        source_before = _source_snapshot(src_index)
        same_artifact = _same_artifact(src_index, deck_path.parent)

        plan = {
            "schema": 1,
            "operation": "lift-swap-replace",
            "source": {
                "index": str(src_index), "fragment": str(src_frag),
                "frame": source_frame, "key": source_key,
                "title": source_title, "snapshot": source_before,
            },
            "target": {
                "deck": str(deck_path), "frame": replace_index,
                "key": target_key, "title": target_title,
                "snapshot": _source_snapshot(deck_path.with_name("index.html")),
            },
            "preserve": {
                "source_layout": True,
                "target_key_order_count": True,
                "keep_target_title": bool(args.keep_title),
            },
            "options": {
                "shake": use_shake,
                "force": bool(args.force),
                "render_force": bool(args.render_force),
                "allow_same_deck": bool(args.allow_same_deck),
            },
            "same_artifact": same_artifact,
        }
        token = _plan_token(plan)

        print("lift-swap plan · READ ONLY" if not args.apply else "lift-swap apply plan")
        print(f"  SOURCE [READ-ONLY]  {src_index}#{src_frag}")
        print(f"         #{source_frame} key={source_key or '?'} title={source_title!r}")
        print("                    ↓ replace target slot; preserve source layout")
        print(f"  TARGET [WRITABLE]   {deck_path}#{replace_index}")
        print(f"         key={target_key} title={target_title!r}")
        print(f"  output: {out_dir}")
        print(f"  shake : {use_shake} ({'auto: non-raw source layout' if args.shake is None else 'explicit'})")
        print(f"  same deck tree: {same_artifact}")
        print(f"  confirm token: {token}")

        if same_artifact and not args.allow_same_deck:
            print("lift-swap: source and target are inside the same deck tree; "
                  "refusing by default. Re-plan with --allow-same-deck only when intentional.",
                  file=sys.stderr)
            return 3

        if not args.apply:
            print("plan-only: no files changed (default safe mode)")
            apply_cmd = [sys.executable, str(Path(__file__).resolve()),
                         "--source", source_ref, "--target", target_ref]
            if args.keep_title:
                apply_cmd.append("--keep-title")
            if args.shake is True:
                apply_cmd.append("--shake")
            elif args.shake is False:
                apply_cmd.append("--no-shake")
            if args.allow_same_deck:
                apply_cmd.append("--allow-same-deck")
            if args.force:
                apply_cmd.append("--force")
            if args.render_force:
                apply_cmd.append("--render-force")
            apply_cmd += ["--apply", "--confirm", token]
            print("apply only after reviewing the arrow above:")
            print("  " + " ".join(shlex.quote(str(x)) for x in apply_cmd))
            return 0

        if args.confirm != token:
            print("lift-swap: confirmation token missing or stale; run the read-only "
                  "plan again and copy its token exactly", file=sys.stderr)
            return 4

        insert_mod = _load_insert_module()
        target_dir = deck_path.parent.resolve()
        if (target_dir / ".git").exists():
            print("lift-swap: refusing to atomically swap a directory containing .git",
                  file=sys.stderr)
            return 2
        target_fingerprint = insert_mod._tree_fingerprint(target_dir)

        stage_root = None
        committed = False
        try:
            stage_root, stage_dir, _uses_runs_gate = insert_mod._stage_destination(target_dir)
            if insert_mod._tree_fingerprint(target_dir) != target_fingerprint:
                raise RuntimeError("destination changed while its staged copy was being created")

            staged_deck = stage_dir / deck_path.relative_to(target_dir)
            staged_out = stage_dir / out_dir.relative_to(target_dir)
            staged_shot = staged_out / f".shoot-p{replace_index}.png"
            staged_shot.unlink(missing_ok=True)

            cmd = [sys.executable, str(LIFT_SLIDES), str(src_index), *source_args,
                   str(staged_deck), str(staged_out), "--replace", str(replace_index)]
            if use_shake:
                cmd.append("--shake")
            if args.keep_title:
                cmd.append("--keep-title")
            if args.force:
                cmd.append("--force")

            proc = _run(cmd)
            if proc.returncode != 0:
                raise RuntimeError(f"lift failed in staging ({proc.returncode})")

            after_deck = _load_deck(staged_deck)
            after_keys = _keys(after_deck)
            if len(after_keys) != before_count:
                raise RuntimeError(f"page count changed {before_count} -> {len(after_keys)}")
            if after_keys != before_keys:
                raise RuntimeError("slide key order changed; single-slot replace must preserve key set")
            if after_keys[replace_index - 1] != target_key:
                raise RuntimeError(
                    f"target slot key changed {target_key!r} -> {after_keys[replace_index - 1]!r}")
            lifted_slide = after_deck["slides"][replace_index - 1]
            if not lifted_slide.get("lifted"):
                raise RuntimeError("replacement lost lifted provenance")

            if not same_artifact and _source_snapshot(src_index) != source_before:
                raise RuntimeError("source control files changed during lift; refusing commit")

            render_cmd = [sys.executable, str(RENDER_DECK), str(staged_deck),
                          str(staged_out), "--scope", str(replace_index), "--shoot"]
            if args.render_force:
                render_cmd.append("--force")
            rproc = _run(render_cmd)
            if rproc.returncode != 0:
                raise RuntimeError(f"staged scoped render failed ({rproc.returncode})")
            if not staged_shot.is_file() or staged_shot.stat().st_size == 0:
                raise RuntimeError(
                    f"staged visual gate produced no screenshot: {staged_shot.name}")

            if not same_artifact and _source_snapshot(src_index) != source_before:
                raise RuntimeError("source control files changed before commit; refusing commit")

            _commit_staged_directory(stage_dir, target_dir, target_fingerprint)
            committed = True
            print(f"✓ committed transactional lift-swap: source unchanged; "
                  f"target #{replace_index} rendered and shot")
            print(f"  screenshot: {target_dir / staged_shot.relative_to(stage_dir)}")
            return 0
        except Exception as exc:
            print(f"lift-swap: transaction aborted; official target unchanged: {exc}",
                  file=sys.stderr)
            return 7
        finally:
            if stage_root is not None and (not committed or stage_root.exists()):
                shutil.rmtree(stage_root, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
