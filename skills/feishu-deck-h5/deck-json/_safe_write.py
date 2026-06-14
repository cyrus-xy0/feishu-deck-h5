"""Shared safe deck.json writer — atomic write + post-write validate + rollback.

Extracted (F-323) so the writers that are NOT deck-cli — `import-html-slide.py`,
`apply-text-pairs.py`, `reconcile-reflow.py`, `merge-canvas-lines.py` — get the
same data-integrity guarantee the single-writer `deck-cli.py` already has, instead
of each doing a bare `path.write_text(json.dumps(...))` (no atomicity, no schema
re-validation, no rollback).

deck-cli keeps its OWN richer `write_deck_with_validation` (it also carries the
optimistic lock + F-320 scope-demote, which are command-specific); this module is
the minimal reusable core for the other writers. The atomic-write / backup logic
is intentionally identical to deck-cli's so behaviour stays uniform.

Also provides `contained_dest()` — the path-traversal guard the asset-copy loops
need so a crafted/foreign source deck cannot write outside the destination dir.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
VALIDATE_DECK = _HERE / "validate-deck.py"


# --------------------------------------------------------------------------- #
# Atomic write (same contract as deck-cli.atomic_write_text)
# --------------------------------------------------------------------------- #
def atomic_write_text(path, text: str, encoding: str = "utf-8") -> None:
    """Write `text` to `path` atomically (sibling temp file + os.replace).

    A reader sees either the complete old file or the complete new one, never a
    torn one; a crash mid-write never leaves a `.tmp` turd behind. The temp file
    MUST be a sibling (same filesystem) for os.replace to be atomic."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding) as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def atomic_write_json(path, obj, encoding: str = "utf-8") -> None:
    atomic_write_text(path, json.dumps(obj, ensure_ascii=False, indent=2), encoding=encoding)


def backup_path(deck_path: Path, command: str) -> Path:
    ts = time.strftime("%Y%m%d-%H%M%S")
    base = deck_path.with_suffix(f".json.bak-pre-{command}-{ts}")
    if not base.exists():
        return base
    n = 1
    while (cand := deck_path.parent / f"{base.name}.{n}").exists():
        n += 1
    return cand


# --------------------------------------------------------------------------- #
# Validate + write + rollback
# --------------------------------------------------------------------------- #
def validate_and_write_deck(deck_path, deck: dict, command: str, *,
                            no_backup: bool = False, strict: bool = True,
                            validate: bool = True) -> bool:
    """Backup → atomic write → `validate-deck.py [--strict]` → rollback on fail.

    Returns True on success; False if the post-write validation failed (in which
    case the previous on-disk content has been restored from the .bak, or from an
    in-memory copy when `no_backup`). Mirrors deck-cli.write_deck_with_validation
    minus the optimistic-lock / scope-demote (caller-specific) bits.
    """
    deck_path = Path(deck_path)
    orig_text = None
    bak = None
    if deck_path.exists():
        try:
            orig_text = deck_path.read_text(encoding="utf-8")
        except OSError:
            pass
        if not no_backup:
            bak = backup_path(deck_path, command)
            shutil.copy2(deck_path, bak)

    atomic_write_json(deck_path, deck)

    if validate:
        rc = subprocess.run(
            [sys.executable, str(VALIDATE_DECK), str(deck_path)] + (["--strict"] if strict else []),
            capture_output=True, text=True,
        )
        if rc.returncode != 0:
            print(f"safe-write: post-{command} validation FAILED. Rolling back.", file=sys.stderr)
            if rc.stdout:
                print(rc.stdout, file=sys.stderr)
            restore_deck(deck_path, bak, orig_text, command)
            return False

    if bak:
        print(f"safe-write: backup at {bak.name}", file=sys.stderr)
    return True


def deck_is_valid(deck_path, *, strict: bool = True) -> bool:
    """True if `deck_path` currently passes validate-deck.py. Lets a post-hoc
    writer (apply-text-pairs, merge-canvas-lines …) gate its OUTPUT only when the
    INPUT was already valid — so it never refuses a legitimate edit because of a
    PRE-EXISTING schema violation it didn't introduce (and can't fix)."""
    try:
        rc = subprocess.run(
            [sys.executable, str(VALIDATE_DECK), str(deck_path)] + (["--strict"] if strict else []),
            capture_output=True, text=True)
        return rc.returncode == 0
    except Exception:
        return False


def restore_deck(deck_path, bak, orig_text, command: str) -> None:
    """Roll a deck.json back to its pre-write state. Used both by the validate
    failure path above and by callers whose POST-write step (e.g. a re-render)
    fails and need to undo the deck.json change too."""
    deck_path = Path(deck_path)
    if bak and Path(bak).exists():
        shutil.copy2(bak, deck_path)
        print(f"safe-write: restored from {Path(bak).name}", file=sys.stderr)
    elif orig_text is not None:
        atomic_write_text(deck_path, orig_text)
        print("safe-write: restored pre-write content (in-memory copy)", file=sys.stderr)


# --------------------------------------------------------------------------- #
# Path-traversal guard (F-324) for asset-copy loops
# --------------------------------------------------------------------------- #
def contained_dest(base_dir, ref: str):
    """Resolve `ref` (a relative path taken from a possibly-crafted source deck)
    under `base_dir` and return the absolute destination Path ONLY if it stays
    inside `base_dir`; return None if it would escape (e.g. '../../etc/x',
    absolute paths, symlink games). Callers must skip a None.

    >>> contained_dest('/d', 'a/b.png')        # -> Path('/d/a/b.png')
    >>> contained_dest('/d', '../../etc/pwn')   # -> None
    """
    base = Path(base_dir).resolve()
    # An absolute ref is never "under base" by join semantics; reject up front.
    cand = (base / ref)
    try:
        resolved = cand.resolve()
    except (OSError, RuntimeError):
        return None
    if resolved == base or base in resolved.parents:
        return resolved
    return None
