#!/usr/bin/env python3
from __future__ import annotations

"""
optimize-images.py — shrink a finished deck's raster images for fast loading
(especially on mobile, where 4K JPEG decode + oversized PNGs are the dominant
cost — see F-341).

A rendered/imported deck routinely ships images far larger than it can ever
display: the canvas is 1920×1080, yet imported decks carry full-page background
JPEGs at 3840×2160 (4K — 4× the pixels, ~4× the decode CPU/memory) and content
photos stored as multi-megabyte lossless PNG. None of that resolution reaches
the screen; it's pure download + decode waste on every open.

This pass walks the deck folder and, IN PLACE:
  • downscales any raster whose longest edge exceeds --max-edge (default 1920,
    the canvas longest edge) to fit, preserving aspect ratio;
  • transcodes FULLY-OPAQUE PNGs (no real transparency) ≥ --transcode-min-bytes
    to JPEG (10–15× smaller for photos), rewriting every reference to the new
    .jpg path across index.html / deck.json / slide-index.json / *.html;
  • leaves PNGs that actually use transparency as PNG (only downscales them),
    and never touches SVG / GIF / already-small / already-right-sized files.

IDEMPOTENT by construction: downscaling only ever shrinks (an image already
≤ max-edge is skipped), and a transcoded PNG is deleted in favour of its .jpg,
so a second run finds nothing left to do. Safe to wire into finalize.sh and
re-run after edits.

DEPENDENCY-LIGHT: uses Pillow when importable (required for alpha detection +
transcode); otherwise falls back to macOS `sips` for downscale-only; if neither
is available it prints a notice and does nothing (never fails the build).

USAGE:
    python3 assets/optimize-images.py <deck-dir> [options]

    <deck-dir>                 folder containing index.html (e.g. runs/<ts>/output/
                               or an imported deck's run root)
    --max-edge N               longest-edge cap in px (default 1920)
    --quality Q                JPEG/WebP quality 1–100 (default 86 — high enough
                               to keep title text baked into background images
                               crisp; the big win is the downscale, not the q)
    --no-transcode             downscale only; never change PNG → JPEG
    --transcode-min-bytes N    only transcode opaque PNGs at least this big
                               (default 150000 — leave small icons/logos as PNG)
    --dry-run                  report what WOULD change; touch nothing
    --quiet                    only print the final summary line

Exits 0 on success (including the no-backend no-op). Exits 1 on bad arguments.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

RASTER_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
# Directories we never descend into / optimize: the shared library pool is a
# symlink to the 30 MB cross-deck asset pool (owned/managed elsewhere — never
# rewrite or shrink it per-deck), and dotdirs are housekeeping.
SKIP_DIR_NAMES = {"shared"}
# Files whose references we rewrite when a transcode renames <name>.png →
# <name>.jpg. deck.json / slide-index.json keep the deck re-renderable.
REF_FILE_SUFFIXES = (".html", ".json", ".css")


def _human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024 or unit == "GB":
            return f"{n:.1f}{unit}" if unit != "B" else f"{int(n)}B"
        n /= 1024
    return f"{n:.1f}GB"


def _iter_rasters(deck_dir: Path):
    """Yield raster files under deck_dir, skipping symlinked dirs (the shared
    pool symlink), the shared pool, and dotdirs."""
    for dirpath, dirnames, filenames in os.walk(deck_dir, followlinks=False):
        # prune: don't descend into shared pool / dot dirs / symlinked dirs
        dirnames[:] = [
            d for d in dirnames
            if d not in SKIP_DIR_NAMES
            and not d.startswith(".")
            and not (Path(dirpath) / d).is_symlink()
        ]
        for name in filenames:
            p = Path(dirpath) / name
            if p.is_symlink():
                continue
            if p.suffix.lower() in RASTER_EXTS:
                yield p


# ── Pillow backend ──────────────────────────────────────────────────────────
def _pillow():
    try:
        from PIL import Image
        return Image
    except Exception:
        return None


def _png_is_opaque(img) -> bool:
    """True if the image has no meaningful transparency (safe to flatten to
    JPEG). Conservative: any real alpha < 255, or palette transparency, keeps
    it a PNG."""
    if img.mode in ("RGB", "L"):
        return True
    if img.mode == "P":
        return "transparency" not in img.info
    if img.mode in ("RGBA", "LA"):
        alpha = img.getchannel("A")
        lo, _hi = alpha.getextrema()
        return lo >= 255  # fully opaque
    # any other mode (CMYK, etc.) — treat as opaque (no alpha)
    return True


def _plan(img_path: Path, Image, max_edge: int, transcode: bool, min_bytes: int):
    """Decide what to do with one image. Returns (action, new_path) where
    action in {'skip','downscale','transcode'} and new_path is the post-action
    path (== img_path unless transcoding renames .png→.jpg)."""
    try:
        with Image.open(img_path) as im:
            w, h = im.size
            ext = img_path.suffix.lower()
            oversized = max(w, h) > max_edge
            opaque_png = (
                ext == ".png"
                and transcode
                and img_path.stat().st_size >= min_bytes
                and _png_is_opaque(im)
            )
    except Exception:
        return ("skip", img_path)
    if opaque_png:
        return ("transcode", img_path.with_suffix(".jpg"))
    if oversized:
        return ("downscale", img_path)
    return ("skip", img_path)


def _apply_pillow(img_path: Path, new_path: Path, action: str, Image,
                  max_edge: int, quality: int) -> None:
    from PIL import Image as _I
    with Image.open(img_path) as im:
        w, h = im.size
        if max(w, h) > max_edge:
            scale = max_edge / float(max(w, h))
            im = im.resize((max(1, round(w * scale)), max(1, round(h * scale))),
                           _I.LANCZOS)
        ext = new_path.suffix.lower()
        if ext in (".jpg", ".jpeg"):
            rgb = im.convert("RGB")
            rgb.save(new_path, "JPEG", quality=quality, optimize=True,
                     progressive=True)
        elif ext == ".webp":
            im.save(new_path, "WEBP", quality=quality, method=6)
        else:  # .png — downscale, keep lossless + alpha
            im.save(new_path, "PNG", optimize=True)
    if action == "transcode" and new_path != img_path:
        img_path.unlink()


# ── sips fallback (downscale only — no alpha detection, no transcode) ────────
def _sips_available() -> bool:
    try:
        subprocess.run(["sips", "--help"], capture_output=True, check=False)
        return True
    except Exception:
        return False


def _sips_dims(path: Path):
    try:
        out = subprocess.run(
            ["sips", "-g", "pixelWidth", "-g", "pixelHeight", str(path)],
            capture_output=True, text=True, check=True).stdout
        w = h = None
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("pixelWidth:"):
                w = int(line.split(":")[1])
            elif line.startswith("pixelHeight:"):
                h = int(line.split(":")[1])
        return (w, h) if w and h else None
    except Exception:
        return None


def _sips_downscale(path: Path, max_edge: int) -> bool:
    try:
        subprocess.run(["sips", "-Z", str(max_edge), str(path)],
                       capture_output=True, check=True)
        return True
    except Exception:
        return False


def _rewrite_refs(deck_dir: Path, renames: list[tuple[str, str]], dry: bool) -> int:
    """Rewrite <old-rel-path> → <new-rel-path> across text files (html/json/css)
    for every transcode rename. Matches the plain relative path and its
    percent-encoded form (Chinese filenames). Returns count of files changed."""
    if not renames:
        return 0
    # Build replacement pairs: plain + url-encoded. Longest-first so a path that
    # is a prefix of another doesn't partially match.
    pairs: list[tuple[str, str]] = []
    for old, new in renames:
        pairs.append((old, new))
        old_q, new_q = quote(old), quote(new)
        if old_q != old:
            pairs.append((old_q, new_q))
    pairs.sort(key=lambda t: len(t[0]), reverse=True)

    changed = 0
    for dirpath, dirnames, filenames in os.walk(deck_dir, followlinks=False):
        dirnames[:] = [d for d in dirnames
                       if not d.startswith(".")
                       and not (Path(dirpath) / d).is_symlink()]
        for name in filenames:
            if not name.endswith(REF_FILE_SUFFIXES):
                continue
            f = Path(dirpath) / name
            try:
                text = f.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            new_text = text
            for old, new in pairs:
                if old in new_text:
                    new_text = new_text.replace(old, new)
            if new_text != text:
                changed += 1
                if not dry:
                    f.write_text(new_text, encoding="utf-8")
    return changed


def main() -> int:
    ap = argparse.ArgumentParser(add_help=True, description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("deck_dir")
    ap.add_argument("--max-edge", type=int, default=1920)
    ap.add_argument("--quality", type=int, default=86)
    ap.add_argument("--no-transcode", action="store_true")
    ap.add_argument("--transcode-min-bytes", type=int, default=150_000)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    deck_dir = Path(args.deck_dir).resolve()
    if not deck_dir.is_dir():
        print(f"optimize-images: not a directory: {deck_dir}", file=sys.stderr)
        return 1

    transcode = not args.no_transcode
    Image = _pillow()
    use_sips = Image is None and _sips_available()
    if Image is None and not use_sips:
        print("optimize-images: neither Pillow nor sips available — skipping "
              "(images left as-is; install Pillow for image optimization).",
              file=sys.stderr)
        return 0
    if Image is None and transcode:
        # sips can't safely detect alpha → never transcode on the sips path.
        transcode = False

    rasters = sorted(_iter_rasters(deck_dir))
    before_total = after_total = 0
    n_downscaled = n_transcoded = n_skipped = 0
    renames: list[tuple[str, str]] = []

    for p in rasters:
        before = p.stat().st_size
        before_total += before

        if Image is not None:
            action, new_path = _plan(p, Image, args.max_edge, transcode,
                                     args.transcode_min_bytes)
            if action == "skip":
                n_skipped += 1
                after_total += before
                continue
            if args.dry_run:
                # estimate: we don't re-encode on dry-run, just report intent
                if action == "transcode":
                    n_transcoded += 1
                else:
                    n_downscaled += 1
                after_total += before  # unknown; report no byte delta in dry-run
                if not args.quiet:
                    rel = p.relative_to(deck_dir)
                    tag = "transcode→jpg" if action == "transcode" else "downscale"
                    print(f"  [dry] {tag:14s} {rel}")
                if action == "transcode":
                    renames.append((str(p.relative_to(deck_dir)).replace(os.sep, "/"),
                                    str(new_path.relative_to(deck_dir)).replace(os.sep, "/")))
                continue
            try:
                _apply_pillow(p, new_path, action, Image, args.max_edge, args.quality)
            except Exception as e:
                print(f"  [WARN] failed to optimize {p.relative_to(deck_dir)}: {e}",
                      file=sys.stderr)
                n_skipped += 1
                after_total += before
                continue
            after = new_path.stat().st_size
            after_total += after
            if action == "transcode":
                n_transcoded += 1
                renames.append((str(p.relative_to(deck_dir)).replace(os.sep, "/"),
                                str(new_path.relative_to(deck_dir)).replace(os.sep, "/")))
            else:
                n_downscaled += 1
            if not args.quiet:
                rel = new_path.relative_to(deck_dir)
                tag = "transcoded" if action == "transcode" else "downscaled"
                print(f"  {tag:11s} {rel}  {_human(before)} → {_human(after)}")
        else:
            # sips downscale-only path
            dims = _sips_dims(p)
            if not dims or max(dims) <= args.max_edge:
                n_skipped += 1
                after_total += before
                continue
            if args.dry_run:
                n_downscaled += 1
                after_total += before
                if not args.quiet:
                    print(f"  [dry] downscale     {p.relative_to(deck_dir)}")
                continue
            if _sips_downscale(p, args.max_edge):
                after = p.stat().st_size
                after_total += after
                n_downscaled += 1
                if not args.quiet:
                    print(f"  downscaled  {p.relative_to(deck_dir)}  "
                          f"{_human(before)} → {_human(after)}")
            else:
                n_skipped += 1
                after_total += before

    files_changed = _rewrite_refs(deck_dir, renames, args.dry_run)

    saved = before_total - after_total
    backend = "Pillow" if Image is not None else "sips"
    prefix = "[dry-run] would optimize" if args.dry_run else "optimized"
    pct = (saved / before_total * 100) if before_total else 0
    print(f"optimize-images [{backend}]: {prefix} {n_downscaled} downscaled · "
          f"{n_transcoded} transcoded · {n_skipped} already-optimal · "
          f"{_human(before_total)} → {_human(after_total)} "
          f"({pct:.0f}% smaller)"
          + (f" · {files_changed} ref file(s) updated" if renames else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
