#!/usr/bin/env python3
"""Insert one or more DeckJSON-native slides after a target page.

Fast path for requests shaped like:

    put source/index.html#14 and #15 after target/index.html#9

The helper keeps the high-risk parts deterministic and transactional:
  - resolves URL #N against the current deck order before writing;
  - delegates slide copying to deck-cli paste, so assets and key collisions use
    the standard path;
  - optionally localizes remote iframe-embed src URLs into prototypes/;
  - performs every mutation, download, render, gate and screenshot in a staged
    copy of the destination directory;
  - verifies the regenerated HTML provenance/signature/notes and renderer
    sidecars before replacing the destination directory.

No rendered frame strings are patched into an old index.html.  Browser edits
that must survive need ``--preserve-index``; that option reverse-syncs them into
the staged deck.json before the one authoritative full render.
"""
from __future__ import annotations

import argparse
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid
from urllib.parse import unquote, urlparse

HERE = Path(__file__).resolve().parent
DECK_CLI = HERE / "deck-cli.py"
RENDER_DECK = HERE / "render-deck.py"
SYNC_INDEX = HERE / "sync-index-to-deck.py"

sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "assets"))
from _safe_write import atomic_write_text, validate_and_write_deck  # noqa: E402
from _index_sig import verify as verify_index_signature  # noqa: E402
from safe_resources import download_public_resource  # noqa: E402


MAX_REMOTE_IFRAME_BYTES = 32 * 1024 * 1024


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


def _frame_keys(html: str) -> list[str]:
    parser = FrameParser(html)
    parser.feed(html)
    return [str(frame["key"]) for frame in parser.frames]


def _run(cmd: list[str], *, check: bool = True,
         env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, text=True, capture_output=True, env=env)
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
    downloaded = download_public_resource(
        src,
        max_bytes=MAX_REMOTE_IFRAME_BYTES,
        timeout=60,
        user_agent="feishu-deck-h5 lift-insert",
        allowed_types=("text/html", "application/xhtml+xml"),
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f".{dest.name}.tmp")
    tmp.write_bytes(downloaded.payload)
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
        # The whole destination directory is already a rollback boundary.  A
        # per-write .bak in the staged copy would be committed as stray output.
        ok = validate_and_write_deck(
            deck_path, deck, "lift-insert-localize", no_backup=True, strict=True)
        if not ok:
            raise RuntimeError("deck validation failed after iframe localization")
    return changed


def _active_index_for_key(deck: dict, key: str) -> int:
    for frame, _raw_i, slide in _active_rows(deck):
        if slide.get("key") == key:
            return frame
    raise ValueError(f"inserted key not found after write: {key}")


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _tree_fingerprint(root: Path) -> tuple[tuple[str, str, int], ...]:
    """Content fingerprint used to reject a concurrent destination change.

    Symlinks are fingerprinted by link text, never followed.  File contents,
    entry types, names and permission bits are covered; timestamps are not
    authored bytes and copying a tree legitimately preserves/adjusts them.
    """
    root = Path(root)
    if not root.is_dir():
        raise RuntimeError(f"destination directory disappeared: {root}")
    rows: list[tuple[str, str, int]] = []

    def walk(directory: Path) -> None:
        with os.scandir(directory) as entries:
            ordered = sorted(entries, key=lambda entry: entry.name)
        for entry in ordered:
            path = Path(entry.path)
            rel = path.relative_to(root).as_posix()
            mode = stat.S_IMODE(path.lstat().st_mode)
            if entry.is_symlink():
                rows.append((rel, "L:" + os.readlink(path), mode))
            elif entry.is_dir(follow_symlinks=False):
                rows.append((rel, "D", mode))
                walk(path)
            elif entry.is_file(follow_symlinks=False):
                rows.append((rel, "F:" + _hash_file(path), mode))
            else:
                rows.append((rel, "O", mode))

    walk(root)
    return tuple(rows)


def _materialize_symlink(path: Path) -> None:
    """Detach a mutable staged root from an external symlink target."""
    if not path.is_symlink():
        return
    try:
        target = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise RuntimeError(f"cannot stage dangling mutable symlink: {path}") from exc
    path.unlink()
    if target.is_dir():
        # Follow nested links too: writes below this staged mutable root must not
        # leak through a second symlink into the official deck/framework pool.
        shutil.copytree(target, path, symlinks=False,
                        ignore_dangling_symlinks=True)
    elif target.is_file():
        shutil.copy2(target, path)
    else:
        raise RuntimeError(f"unsupported mutable symlink target: {path} -> {target}")


def _stage_destination(target_dir: Path) -> tuple[Path, Path, bool]:
    """Return ``(stage_root, staged_target_dir, uses_runs_gate)``.

    A runs/<id>/<output-like> target is staged as another run child at the same
    path depth.  That preserves relative asset paths and makes render-deck use
    its real delivery gate.  Other targets use a same-depth sibling directory
    and are rendered with an explicit ``--visual`` gate.
    """
    target_dir = target_dir.resolve()
    uses_runs_gate = target_dir.parent.parent.name == "runs"
    stage_root: Path | None = None
    try:
        if uses_runs_gate:
            runs_dir = target_dir.parent.parent
            stage_root = Path(tempfile.mkdtemp(
                prefix=".lift-insert-stage-", dir=str(runs_dir)))
            stage_dir = stage_root / target_dir.name
            shutil.copytree(target_dir, stage_dir, symlinks=True)

            # copy-assets resolves canonical input from the run root.  Keep that
            # dependency staged as well, even though paste writes deck-local input/
            # beneath stage_dir and only stage_dir is eventually committed.
            source_input = target_dir.parent / "input"
            staged_input = stage_root / "input"
            if target_dir.name != "input" and source_input.exists():
                if source_input.is_dir():
                    shutil.copytree(source_input, staged_input, symlinks=True)
                else:
                    shutil.copy2(source_input, staged_input, follow_symlinks=True)
        else:
            stage_dir = Path(tempfile.mkdtemp(
                prefix=f".{target_dir.name}.lift-stage-", dir=str(target_dir.parent)))
            stage_root = stage_dir
            shutil.copytree(target_dir, stage_dir, symlinks=True, dirs_exist_ok=True)

        # deck-cli paste/localization can write these roots.  Never let a symlink in
        # the copied destination tunnel those writes back into official data.
        for mutable in (stage_dir / "input", stage_dir / "prototypes",
                        stage_dir / "assets", stage_dir / "assets" / "shared"):
            _materialize_symlink(mutable)
        return stage_root, stage_dir, uses_runs_gate
    except BaseException:
        if stage_root is not None:
            shutil.rmtree(stage_root, ignore_errors=True)
        raise


def _remove_new_sync_backups(stage_dir: Path, before: set[Path]) -> None:
    for path in set(stage_dir.glob("deck.json.bak-pre-sync-*")) - before:
        path.unlink(missing_ok=True)


def _clear_stale_screenshots(stage_dir: Path) -> None:
    # Inserting pages shifts frame numbers; retaining an old .shoot-pN image
    # would make the committed artifact bundle internally dishonest.  --verify
    # regenerates only the requested inserted-page shots after this cleanup.
    for path in stage_dir.glob(".shoot-p*.png"):
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)


def _write_clean_validation_baseline(path: Path) -> None:
    atomic_write_text(path, json.dumps({
        "schema": 1,
        "note": "lift-insert staged visual gate passed with no error-level "
                "visual/geometry findings; regenerated for this index.html.",
        "fingerprints": [],
    }, ensure_ascii=False, indent=1) + "\n")


def _notes_from_index(html: str) -> dict:
    match = re.search(
        r'<script\b[^>]*\bid=["\']fs-deck-notes["\'][^>]*>(.*?)</script\s*>',
        html, re.I | re.S)
    if not match:
        return {}
    value = json.loads(match.group(1))
    if not isinstance(value, dict):
        raise RuntimeError("#fs-deck-notes is not a JSON object")
    return value


def _verify_rendered_bundle(stage_dir: Path, *, anchor_key: str,
                            inserted_keys: list[str], verify_shots: bool) -> None:
    deck_path = stage_dir / "deck.json"
    index_path = stage_dir / "index.html"
    slide_index_path = stage_dir / "slide-index.json"
    hashes_path = stage_dir / ".slide-hashes.json"
    baseline_path = stage_dir / "validate-findings.json"
    required = (deck_path, index_path, slide_index_path, hashes_path, baseline_path)
    missing = [path.name for path in required if not path.is_file()]
    if missing:
        raise RuntimeError("staged render missing artifact(s): " + ", ".join(missing))

    deck = _load_deck(deck_path)
    active = [slide for _, _, slide in _active_rows(deck)]
    active_keys = [str(slide.get("key") or "") for slide in active]
    if not all(active_keys) or len(set(active_keys)) != len(active_keys):
        raise RuntimeError("staged deck has missing or duplicate active slide keys")
    try:
        anchor_pos = active_keys.index(anchor_key)
    except ValueError as exc:
        raise RuntimeError(f"staged deck lost anchor slide: {anchor_key}") from exc
    if active_keys[anchor_pos + 1:anchor_pos + 1 + len(inserted_keys)] != inserted_keys:
        raise RuntimeError("staged deck insertion order does not follow the anchor")

    html = index_path.read_text(encoding="utf-8")
    if _frame_keys(html) != active_keys:
        raise RuntimeError("index.html frame keys/order do not match deck.json")
    if verify_index_signature(index_path) != "ok":
        raise RuntimeError("index.html render signature is missing or invalid")

    generators = re.findall(
        r'<meta\s+name=["\']fs-deck-generator["\']\s+content=["\']([^"\']+)', html, re.I)
    hashes = re.findall(
        r'<meta\s+name=["\']fs-deck-hash["\']\s+content=["\']([^"\']+)', html, re.I)
    expected_hash = hashlib.sha256(deck_path.read_bytes()).hexdigest()[:12]
    if generators != ["render-deck"] or hashes != [expected_hash]:
        raise RuntimeError("index.html provenance does not match staged deck.json")

    expected_notes = {
        str(slide["key"]): slide["notes"] for slide in active
        if isinstance(slide.get("notes"), str) and slide["notes"].strip()
    }
    if _notes_from_index(html) != expected_notes:
        raise RuntimeError("index.html notes island does not match deck.json notes")

    try:
        slide_index = json.loads(slide_index_path.read_text(encoding="utf-8"))
        index_rows = slide_index["slides"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("invalid slide-index.json") from exc
    if ([row.get("key") for row in index_rows] != active_keys
            or [row.get("frame_index") for row in index_rows]
            != list(range(1, len(active_keys) + 1))):
        raise RuntimeError("slide-index.json does not match deck.json")

    try:
        sidecar = json.loads(hashes_path.read_text(encoding="utf-8"))
        sidecar_keys = [str(row[0]) for row in sidecar["slides"]]
    except (OSError, KeyError, TypeError, IndexError, json.JSONDecodeError) as exc:
        raise RuntimeError("invalid .slide-hashes.json") from exc
    if not isinstance(sidecar.get("schema"), int) or sidecar_keys != active_keys:
        raise RuntimeError(".slide-hashes.json does not match deck.json")

    try:
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("invalid validate-findings.json") from exc
    if baseline.get("schema") != 1 or not isinstance(baseline.get("fingerprints"), list):
        raise RuntimeError("validate-findings.json has an invalid schema")

    expected_shots = ({f".shoot-p{_active_index_for_key(deck, key)}.png"
                       for key in inserted_keys} if verify_shots else set())
    actual_shots = {path.name for path in stage_dir.glob(".shoot-p*.png")
                    if path.is_file()}
    if actual_shots != expected_shots:
        raise RuntimeError(
            "staged screenshots do not match inserted-page verification: "
            f"expected {sorted(expected_shots)}, got {sorted(actual_shots)}")


def _commit_staged_directory(stage_dir: Path, target_dir: Path,
                             expected_fingerprint: tuple[tuple[str, str, int], ...]) -> None:
    """Commit with same-filesystem directory renames and rollback on swap error."""
    if _tree_fingerprint(target_dir) != expected_fingerprint:
        raise RuntimeError(
            "destination changed while lift-insert was running; staged result was "
            "not committed (retry against the new destination state)")

    backup = target_dir.parent / (
        f".{target_dir.name}.lift-insert-rollback-{uuid.uuid4().hex}")
    os.replace(target_dir, backup)
    try:
        os.replace(stage_dir, target_dir)
    except BaseException as swap_error:
        try:
            os.replace(backup, target_dir)
        except BaseException as restore_error:
            raise RuntimeError(
                f"staged commit failed and automatic directory restore also failed; "
                f"recover {target_dir} from {backup}: {restore_error}") from swap_error
        raise

    # The commit point has passed.  A cleanup failure must not be reported as a
    # failed transaction (the official directory is already the coherent staged
    # bundle); retain the rollback copy and print a recovery/cleanup hint instead.
    try:
        shutil.rmtree(backup)
    except OSError as exc:
        print(f"  warning: committed, but old rollback directory remains: "
              f"{backup} ({exc})", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Insert DeckJSON-native lifted pages after a target page.")
    ap.add_argument("--after", required=True, help="target index.html/deck.json/dir with #page or #key")
    ap.add_argument("sources", nargs="+", help="source index.html/deck.json/dir refs with #page or #key")
    ap.add_argument("--preserve-index", action="store_true",
                    help="reverse-sync browser/hand edits from index.html into the "
                         "staged deck before the full render (template edits may "
                         "be converted to raw); official files stay untouched until commit")
    ap.add_argument("--no-localize-remote-iframes", action="store_true",
                    help="leave iframe-embed http(s) src values remote")
    ap.add_argument("--dry-run", action="store_true", help="print the resolved plan and write nothing")
    ap.add_argument("--verify", action="store_true",
                    help="run the scoped visual gate and capture inserted-page "
                         "screenshots inside the transaction before commit")
    args = ap.parse_args(argv)

    target_path, target_selector = _parse_ref(args.after)
    target_deck, target_index = _deck_and_index(target_path)
    if target_index.name != "index.html":
        raise ValueError(
            "transactional lift-insert requires the canonical sibling index.html")
    target_dir = target_deck.parent
    if (target_dir / ".git").exists():
        raise ValueError("refusing to swap a directory that contains .git")
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

    expected_fingerprint = _tree_fingerprint(target_dir)
    stage_root: Path | None = None
    try:
        stage_root, stage_dir, uses_runs_gate = _stage_destination(target_dir)
        # Detect a target mutation that raced the copy itself before doing any
        # expensive staged work.  Such an external edit is never overwritten.
        if _tree_fingerprint(target_dir) != expected_fingerprint:
            raise RuntimeError(
                "destination changed while its staged snapshot was being created")
        staged_deck = stage_dir / "deck.json"
        staged_index = stage_dir / "index.html"
        staged_lock = stage_dir / ".deck.json.lock"
        lock_existed_before = staged_lock.exists()
        print(f"stage:  {stage_dir}")

        if args.preserve_index:
            existing_sync_backups = set(stage_dir.glob("deck.json.bak-pre-sync-*"))
            try:
                _run([sys.executable, str(SYNC_INDEX), str(staged_index),
                      str(staged_deck), "--force", "--index-is-newer"])
            finally:
                _remove_new_sync_backups(stage_dir, existing_sync_backups)

            # Browser reorder/hidden edits can change both the raw insertion
            # position and which key a numeric #N selector names.
            staged_target = _load_deck(staged_deck)
            staged_anchor_frame, staged_anchor_raw_i, staged_anchor = _resolve_selector(
                staged_target, target_selector, role="target")
            anchor_key = staged_anchor.get("key")
            if not anchor_key:
                raise RuntimeError("staged target anchor slide has no key")
            insert_position = staged_anchor_raw_i + 2
            print(f"  preserved index edits; resolved anchor → "
                  f"#{staged_anchor_frame} {anchor_key}, position {insert_position}")

        actual_keys: list[str] = []
        pos = insert_position
        for src_deck, _src_index, _src_frame, src_key in resolved_sources:
            cmd = [sys.executable, str(DECK_CLI), str(staged_deck),
                   "--yes", "--no-backup"]
            if args.preserve_index:
                # The reverse-sync above intentionally made staged deck.json the
                # source of truth.  Bypass only the staged stale-index guard.
                cmd.append("--force")
            cmd += ["paste", "--from", str(src_deck), "--key", src_key, str(pos)]
            proc = _run(cmd, check=False)
            if proc.returncode == 6 and not args.preserve_index:
                raise RuntimeError(
                    "deck-cli refused because target index.html has browser-only "
                    "edits. Rerun with --preserve-index to reverse-sync those edits "
                    "inside the transaction before the full render."
                )
            if proc.returncode != 0:
                raise RuntimeError(f"deck-cli paste failed ({proc.returncode})")
            deck_after = _load_deck(staged_deck)
            actual_key = deck_after["slides"][pos - 1].get("key")
            if not actual_key:
                raise RuntimeError(f"pasted slide at position {pos} has no key")
            actual_keys.append(str(actual_key))
            pos += 1

        # deck-cli's advisory flock file persists by design.  It belongs to the
        # staged process, not the rendered artifact; preserve a pre-existing one
        # but do not introduce a new lock file into the committed destination.
        if not lock_existed_before:
            staged_lock.unlink(missing_ok=True)

        if not args.no_localize_remote_iframes:
            _localize_remote_iframes(staged_deck, actual_keys)

        _clear_stale_screenshots(stage_dir)
        baseline_path = stage_dir / "validate-findings.json"
        if not uses_runs_gate:
            # render-deck's non-runs visual gate does not manage the F-302
            # baseline.  Remove the old HTML's baseline before the new gate.
            baseline_path.unlink(missing_ok=True)

        render_cmd = [sys.executable, str(RENDER_DECK), str(staged_deck),
                      str(stage_dir), "--scope", ",".join(actual_keys)]
        if not uses_runs_gate:
            render_cmd.append("--visual")
        if args.verify:
            render_cmd.append("--shoot")
        render_env = dict(os.environ, DECK_LOG_NO_AUTOSNAP="1")
        _run(render_cmd, env=render_env)

        if not uses_runs_gate and not baseline_path.exists():
            # A passing explicit --visual gate has no error-level fingerprints;
            # keep the sidecar tied to this HTML instead of carrying stale state.
            _write_clean_validation_baseline(baseline_path)

        _verify_rendered_bundle(
            stage_dir, anchor_key=str(anchor_key), inserted_keys=actual_keys,
            verify_shots=args.verify)
        _commit_staged_directory(stage_dir, target_dir, expected_fingerprint)
        print(f"  committed coherent bundle: {target_dir}")
        print(f"  inserted: {', '.join(actual_keys)}")
        return 0
    finally:
        if stage_root is not None and stage_root.exists():
            shutil.rmtree(stage_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
