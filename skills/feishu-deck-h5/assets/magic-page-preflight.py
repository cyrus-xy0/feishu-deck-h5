#!/usr/bin/env python3
"""Magic Page publish pre-flight: audit (and optionally fix) oversized resources.

Why this exists (delivery-8 / publish-perf):
Magic Page (妙笔) rejects any single uploaded resource over a hard per-resource
size limit (64 MB). Historically the publisher only learned about an oversized
video at the moment `node magic-page-publish.js` called the upload API — so a
video-heavy deck failed *one resource at a time*: fail on local video A → compress
A by hand → re-package → re-validate → re-publish → fail on remote video B →
repeat. A single publish burned ~40 minutes in that serial fail/fix loop.

This pre-flight runs ONCE, up front, BEFORE asset upload, and reports EVERY
oversized resource (local files, `data:` payloads, remote URLs) in a single pass,
so the whole size problem is fixed in one shot instead of discovered serially.

When `--compress` is set it also auto-fixes the common case: a video that is only
oversized because it was authored at capture resolution/bitrate but renders into a
small on-slide window. It transcodes such videos to a publish-safe profile
(downscale to fit 1920×1080, cap 30 fps, drop audio, H.264 CRF) and rewrites the
HTML ref to the compressed file. A video that is STILL oversized after compression,
a non-video oversized resource, or any oversized resource when ffmpeg is absent,
stays BLOCKING and is reported with the exact remediation command.

Scope: this is a SIZE gate, not a content/visual gate (that is check-only.py).
It deliberately does nothing to in-limit resources — magic-page-assets.py still
owns uploading/rewriting them to TOS.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, unquote_to_bytes, urlparse
from urllib.request import Request, urlopen


# Magic Page hard per-resource upload limit. Keep in sync with
# assets/magic-page-assets.py MAX_EXTERNAL_BYTES.
DEFAULT_MAX_RESOURCE_BYTES = 64 * 1024 * 1024  # 64 MB
# Compress to comfortably under the limit (leave headroom for container overhead).
COMPRESS_TARGET_BYTES = 48 * 1024 * 1024  # 48 MB
REMOTE_HEAD_TIMEOUT = 8

VIDEO_EXTS = {".mp4", ".webm", ".mov", ".m4v", ".ogv", ".mkv"}
RESOURCE_ATTR_RE = re.compile(
    r"<(?P<tag>[A-Za-z][\w:-]*)\b[^>]*?(?<![\w-])(?P<attr>src|poster)\s*=\s*([\"'])(?P<ref>.*?)\3",
    re.I | re.S,
)
URL_FUNC_RE = re.compile(r"url\(\s*(?:\"([^\"]*)\"|'([^']*)'|([^)]*))\s*\)", re.I)
DATA_URI_RE = re.compile(r"^data:([^;,]+)(?:;([^,]*))?,(.*)$", re.I | re.S)


def is_data_uri(ref: str) -> bool:
    return ref.strip().lower().startswith("data:")


def is_http_ref(ref: str) -> bool:
    return ref.strip().lower().startswith(("http://", "https://", "//"))


def is_skippable_ref(ref: str) -> bool:
    raw = ref.strip().lower()
    return not raw or raw.startswith(("#", "blob:", "javascript:", "mailto:", "tel:", "about:"))


def data_uri_size_and_mime(ref: str) -> tuple[int, str] | None:
    """Return (decoded_byte_len, mime) for a data: URI, or None if unparseable."""
    match = DATA_URI_RE.match(ref.strip())
    if not match:
        return None
    mime = (match.group(1) or "").lower()
    flags = (match.group(2) or "").lower()
    payload = match.group(3)
    try:
        if "base64" in {p.strip() for p in flags.split(";") if p.strip()}:
            return len(base64.b64decode(re.sub(r"\s+", "", payload), validate=False)), mime
        return len(unquote_to_bytes(payload)), mime
    except Exception:
        return None


def data_uri_bytes(ref: str) -> tuple[bytes, str] | None:
    match = DATA_URI_RE.match(ref.strip())
    if not match:
        return None
    mime = (match.group(1) or "").lower()
    flags = (match.group(2) or "").lower()
    payload = match.group(3)
    try:
        if "base64" in {p.strip() for p in flags.split(";") if p.strip()}:
            return base64.b64decode(re.sub(r"\s+", "", payload), validate=False), mime
        return unquote_to_bytes(payload), mime
    except Exception:
        return None


def is_video_ref(ref: str, mime: str = "") -> bool:
    if mime.startswith("video/"):
        return True
    if is_data_uri(ref):
        parsed = data_uri_size_and_mime(ref)
        return bool(parsed and parsed[1].startswith("video/"))
    path = urlparse(ref).path if is_http_ref(ref) else ref.split("?", 1)[0].split("#", 1)[0]
    return Path(path).suffix.lower() in VIDEO_EXTS


def resolve_local(html_path: Path, ref: str) -> Path | None:
    if is_data_uri(ref) or is_http_ref(ref) or is_skippable_ref(ref):
        return None
    raw = unquote(ref).split("#", 1)[0].split("?", 1)[0].strip()
    if not raw:
        return None
    candidate = (html_path.parent / raw).resolve()
    return candidate if candidate.is_file() else None


def remote_size(ref: str) -> int | None:
    """Best-effort Content-Length for a remote ref. None when undeterminable
    (network error / no header) — we never fail the build on a network hiccup;
    magic-page-assets.py still caps the actual download at the hard limit."""
    url = ref.strip()
    if url.startswith("//"):
        url = "https:" + url
    try:
        req = Request(url, method="HEAD", headers={"User-Agent": "feishu-deck-h5-preflight/1.0"})
        with urlopen(req, timeout=REMOTE_HEAD_TIMEOUT) as resp:
            cl = resp.headers.get("content-length")
            return int(cl) if cl and cl.isdigit() else None
    except Exception:
        return None


def iter_refs(html: str):
    """Yield (ref, kind) for every resource reference. kind ∈ {attr, css}."""
    for m in RESOURCE_ATTR_RE.finditer(html):
        yield m.group("ref").strip(), "attr"
    for m in URL_FUNC_RE.finditer(html):
        ref = next((g for g in m.groups() if g), "").strip().strip("\"'")
        yield ref, "css"


def build_ffmpeg_cmd(src: Path, dst: Path, *, width: int | None, height: int | None) -> list[str]:
    """Construct the publish-safe transcode command.

    Downscale-only: a scale filter is added ONLY when the source exceeds 1920×1080
    (so we never upscale). Caps 30 fps, drops audio, H.264 CRF 28 — visually clean
    in a small on-slide window while shrinking 4K/60fps capture by ~10-30×. Pure
    function (no execution) so it is unit-testable without ffmpeg installed."""
    cmd = ["ffmpeg", "-y", "-i", str(src)]
    needs_scale = (width and width > 1920) or (height and height > 1080) or (width is None or height is None)
    if needs_scale:
        cmd += ["-vf", "scale=1920:1080:force_original_aspect_ratio=decrease:force_divisible_by=2"]
    cmd += [
        "-r", "30",
        "-an",
        "-c:v", "libx264",
        "-crf", "28",
        "-preset", "veryfast",
        "-movflags", "+faststart",
        str(dst),
    ]
    return cmd


def probe_dimensions(src: Path) -> tuple[int | None, int | None]:
    if not shutil.which("ffprobe"):
        return None, None
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", str(src)],
            text=True, capture_output=True, timeout=30,
        )
        if out.returncode == 0 and "x" in out.stdout:
            w, h = out.stdout.strip().split("x")[:2]
            return int(w), int(h)
    except Exception:
        pass
    return None, None


def compress_video_file(src: Path, work_dir: Path, *, max_bytes: int) -> Path | None:
    """Transcode src to a publish-safe profile. Returns the compressed path if it
    came out under max_bytes, else None (caller keeps it BLOCKING)."""
    if not shutil.which("ffmpeg"):
        return None
    work_dir.mkdir(parents=True, exist_ok=True)
    dst = work_dir / (src.stem + "-mp" + ".mp4")
    width, height = probe_dimensions(src)
    cmd = build_ffmpeg_cmd(src, dst, width=width, height=height)
    try:
        proc = subprocess.run(cmd, text=True, capture_output=True, timeout=900)
    except Exception:
        return None
    if proc.returncode != 0 or not dst.is_file():
        return None
    if dst.stat().st_size > max_bytes:
        return None
    return dst


def human(n: int) -> str:
    mb = n / (1024 * 1024)
    return f"{mb:.1f} MB"


def remediation_cmd(ref_or_path: str) -> str:
    return (
        f"ffmpeg -y -i '{ref_or_path}' "
        "-vf \"scale=1920:1080:force_original_aspect_ratio=decrease:force_divisible_by=2\" "
        "-r 30 -an -c:v libx264 -crf 28 -movflags +faststart '<out>.mp4'"
    )


def run_preflight(
    html_path: Path,
    *,
    out_path: Path | None,
    max_bytes: int,
    compress: bool,
    check_remote: bool,
) -> dict:
    html = html_path.read_text(encoding="utf-8", errors="ignore")
    oversized: list[dict] = []
    compressed: list[dict] = []
    rewrites: list[tuple[str, str]] = []  # (old_ref, new_ref)
    seen_refs: set[str] = set()
    work_dir = (out_path.parent if out_path else html_path.parent) / ".magic-preflight"

    for ref, _kind in iter_refs(html):
        if not ref or ref in seen_refs or is_skippable_ref(ref):
            continue
        seen_refs.add(ref)

        size: int | None = None
        kind = ""
        local: Path | None = None
        mime = ""

        if is_data_uri(ref):
            parsed = data_uri_size_and_mime(ref)
            if parsed is None:
                continue
            size, mime = parsed
            kind = "data-uri"
        elif is_http_ref(ref):
            kind = "remote"
            size = remote_size(ref) if check_remote else None
        else:
            local = resolve_local(html_path, ref)
            if local is None:
                continue
            size = local.stat().st_size
            kind = "local"

        if size is None or size <= max_bytes:
            continue

        label = ref if len(ref) < 120 else ref[:100] + f"...[{kind}]"
        is_video = is_video_ref(ref, mime)

        # Try to auto-fix oversized VIDEOS (the common, fixable case).
        if compress and is_video:
            if kind == "local" and local is not None:
                fixed = compress_video_file(local, work_dir, max_bytes=max_bytes)
                if fixed is not None:
                    rewrites.append((ref, str(fixed.resolve())))
                    compressed.append({"ref": label, "kind": kind,
                                       "from_bytes": size, "to_bytes": fixed.stat().st_size,
                                       "to": str(fixed.resolve())})
                    continue
            elif kind == "data-uri":
                payload = data_uri_bytes(ref)
                if payload is not None and shutil.which("ffmpeg"):
                    work_dir.mkdir(parents=True, exist_ok=True)
                    raw = work_dir / ("inline-" + str(abs(hash(ref)) % (10 ** 10)) + ".mp4")
                    raw.write_bytes(payload[0])
                    fixed = compress_video_file(raw, work_dir, max_bytes=max_bytes)
                    if fixed is not None:
                        rewrites.append((ref, str(fixed.resolve())))
                        compressed.append({"ref": label, "kind": kind,
                                           "from_bytes": size, "to_bytes": fixed.stat().st_size,
                                           "to": str(fixed.resolve())})
                        continue

        # Could not auto-fix → BLOCKING.
        target = str(local) if local else (ref if kind != "data-uri" else "<inline data: video — extract first>")
        oversized.append({
            "ref": label,
            "kind": kind,
            "bytes": size,
            "is_video": is_video,
            "remediation": remediation_cmd(target) if is_video else
                           "resize/optimize this asset under the 64 MB limit, or host it on a CDN",
        })

    # Apply rewrites (compressed refs) to a new HTML artifact.
    new_html = html
    for old, new in rewrites:
        new_html = new_html.replace(old, new)
    if out_path is not None:
        out_path.write_text(new_html, encoding="utf-8")

    ok = not oversized
    return {
        "ok": ok,
        "max_bytes": max_bytes,
        "oversized": oversized,
        "compressed": compressed,
        "ffmpeg_available": bool(shutil.which("ffmpeg")),
        "out": str(out_path) if out_path else "",
    }


def format_report(result: dict) -> str:
    lines = ["# Magic Page publish pre-flight (resource size audit)", ""]
    lines.append(f"- per-resource limit: {human(result['max_bytes'])}")
    lines.append(f"- ffmpeg available: {result['ffmpeg_available']}")
    if result["compressed"]:
        lines.append("")
        lines.append("## Auto-compressed (oversized videos fixed)")
        for c in result["compressed"]:
            lines.append(f"- {c['ref']}: {human(c['from_bytes'])} → {human(c['to_bytes'])}")
    if result["oversized"]:
        lines.append("")
        lines.append("## BLOCKING — still over the limit")
        for o in result["oversized"]:
            lines.append(f"- {o['ref']} ({o['kind']}, {human(o['bytes'])})")
            lines.append(f"  fix: {o['remediation']}")
        if not result["ffmpeg_available"]:
            lines.append("")
            lines.append("> ffmpeg not found — install it to let the publisher auto-compress, "
                         "or run the fix commands above and re-publish.")
    if result["ok"]:
        lines.append("")
        lines.append("All resources within the per-resource limit. ✔")
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Audit/auto-fix oversized Magic Page resources before upload.")
    p.add_argument("html", help="Input HTML (post-inline, pre-upload)")
    p.add_argument("--out", default="", help="Write a preflighted HTML (with compressed-video refs) here")
    p.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_RESOURCE_BYTES)
    p.add_argument("--compress", action="store_true", help="auto-compress oversized videos (needs ffmpeg)")
    p.add_argument("--check-remote", action="store_true", help="HEAD remote refs to size them (network)")
    p.add_argument("--report", default="", help="Write a markdown report here")
    p.add_argument("--json", action="store_true", help="print the machine-readable result to stdout")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    src = Path(args.html).resolve()
    if not src.is_file():
        print(f"ERROR: input not found: {src}", file=sys.stderr)
        return 2
    out_path = Path(args.out).resolve() if args.out else None
    result = run_preflight(
        src,
        out_path=out_path,
        max_bytes=args.max_bytes,
        compress=args.compress,
        check_remote=args.check_remote,
    )
    report = format_report(result)
    if args.report:
        Path(args.report).write_text(report, encoding="utf-8")
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        sys.stdout.write(report)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
