#!/usr/bin/env python3
"""Create a feishu-deck-h5 source dossier from uploaded materials.

The parser is intentionally conservative: it inventories files, extracts
plain text and provenance where the standard library can do so safely, and
hands structured knowledge/material/slide layers to designer, renderer, and
publisher. It does not decide the final deck outline and does not write Base.
By default, artifacts are written to the current run's input/runtime-library
directory because parser output is task input for downstream skills.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
import zlib
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from xml.etree import ElementTree as ET


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "server"))

import slide_library  # noqa: E402


IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
VIDEO_EXTS = {".mp4", ".mov", ".webm", ".m4v"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".oga", ".flac", ".aiff", ".aif"}
MEDIA_EXTS = IMAGE_EXTS | VIDEO_EXTS | AUDIO_EXTS
DOC_EXTS = {".pdf", ".ppt", ".pptx", ".key", ".html", ".htm", ".md", ".txt", ".json"}
LARK_HOST_SUFFIXES = ("feishu.cn", "larkoffice.com", "larksuite.com")
LARK_FILE_URL_RE = re.compile(r"https?://[^\s\"'<>]+/file/[A-Za-z0-9_-]+[^\s\"'<>]*")
SOURCE_HTML_INTENT_RE = re.compile(
    r"参考|照着|重新做|重新生成|重做|复刻|模仿|借鉴|学习.*风格|style reference|reference|remake|recreate",
    re.I,
)
TARGET_HTML_INTENT_RE = re.compile(
    r"修改|调整|优化|修|改|替换|继续|当前|这个\s*html|这份\s*html|on this|modify|edit|adjust|fix|optimi[sz]e",
    re.I,
)
VOID_HTML_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}


def default_lark_identity() -> str:
    return "user"


def default_media_identity() -> str:
    return "user"


def now_slug() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def repo_rel(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO).as_posix()
    except ValueError:
        return str(resolved)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def is_url(value: str) -> bool:
    return bool(re.match(r"https?://", value))


def is_lark_doc_url(value: str) -> bool:
    return bool(re.search(r"(larkoffice\.com|feishu\.cn)/(docx|docs|wiki)/", value))


def is_lark_host(host: str) -> bool:
    host = host.lower().strip()
    return any(host == suffix or host.endswith("." + suffix) for suffix in LARK_HOST_SUFFIXES)


def token_from_lark_file_url(value: str) -> str:
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or not is_lark_host(parsed.netloc):
        return ""
    parts = [part for part in parsed.path.split("/") if part]
    try:
        idx = parts.index("file")
    except ValueError:
        return ""
    if idx + 1 >= len(parts):
        return ""
    token = parts[idx + 1].strip()
    return token if re.fullmatch(r"[A-Za-z0-9_-]+", token) else ""


def safe_source_stem(source: str) -> str:
    stem = Path(source).stem if not is_url(source) else re.sub(r"[^a-zA-Z0-9]+", "-", source).strip("-")
    stem = re.sub(r"[^a-zA-Z0-9._-]+", "-", stem).strip("-._")
    digest = hashlib.sha1(source.encode("utf-8")).hexdigest()[:10]
    return f"{stem[:48] or 'source'}-{digest}"


def ascii_slug(value: str, fallback: str = "") -> str:
    raw = value.lower()
    raw = re.sub(r"[^a-z0-9]+", "-", raw)
    raw = re.sub(r"-+", "-", raw).strip("-")
    return raw[:48] or fallback


def unique_media_preview_path(asset_dir: Path, token: str, hint: str = "") -> Path:
    hint_slug = ascii_slug(hint)
    stem = f"{hint_slug}-{token[:12]}" if hint_slug else f"feishu-file-{token[:12]}"
    candidate = asset_dir / f"{stem}.png"
    if not candidate.exists():
        return candidate
    suffix = 2
    while True:
        candidate = asset_dir / f"{stem}-{suffix}.png"
        if not candidate.exists():
            return candidate
        suffix += 1


def fetch_lark_doc(source: str, target: Path) -> tuple[Path | None, list[str]]:
    if not shutil.which("lark-cli"):
        return None, ["lark-cli not found; Lark document URL was preserved but not fetched."]
    cmd = [
        "lark-cli",
        "docs",
        "+fetch",
        "--api-version",
        "v2",
        "--doc",
        source,
        "--doc-format",
        "markdown",
        "--format",
        "json",
        "--as",
        default_lark_identity(),
    ]
    try:
        proc = subprocess.run(cmd, cwd=REPO, text=True, capture_output=True, timeout=60)
    except subprocess.TimeoutExpired:
        return None, ["lark-cli docs +fetch timed out; Lark document URL was preserved but not parsed."]
    if proc.returncode != 0:
        raw = (proc.stderr or proc.stdout).strip()
        reason = raw
        try:
            payload = json.loads(raw)
            error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
            reason = str(error.get("message") or error.get("hint") or raw)
        except json.JSONDecodeError:
            reason = " ".join(raw.splitlines()[:4])
        return None, ["lark-cli docs +fetch failed: " + reason[:600]]
    content = ""
    try:
        payload = json.loads(proc.stdout)
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        document = data.get("document") if isinstance(data.get("document"), dict) else {}
        content = str(document.get("content") or payload.get("content") or "")
    except json.JSONDecodeError:
        content = proc.stdout
    if not content.strip():
        return None, ["lark-cli docs +fetch returned no readable content."]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target, []


def fetch_lark_media_preview(token: str, destination: Path) -> dict[str, Any]:
    identity = default_media_identity()
    result: dict[str, Any] = {
        "ok": False,
        "token": token,
        "path": repo_rel(destination),
        "method": "media-preview",
        "identity": identity,
    }
    if not shutil.which("lark-cli"):
        return {**result, "error": "lark-cli not found"}

    destination.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "lark-cli",
        "docs",
        "+media-preview",
        "--token",
        token,
        "--output",
        destination.name,
        "--overwrite",
        "--as",
        identity,
    ]
    try:
        proc = subprocess.run(cmd, cwd=destination.parent, text=True, capture_output=True, timeout=60)
    except subprocess.TimeoutExpired:
        return {**result, "error": "lark-cli docs +media-preview timed out"}

    if proc.returncode == 0 and destination.exists() and destination.stat().st_size > 0:
        return {**result, "ok": True, "stdout": proc.stdout.strip()[-1200:]}
    raw = (proc.stderr or proc.stdout).strip()
    return {**result, "error": " ".join(raw.splitlines()[:4])[:600]}


def prepare_runtime_source(source: str, library_dir: Path) -> dict[str, Any]:
    record: dict[str, Any] = {
        "original_source": source,
        "runtime_source": source,
        "preserved": False,
        "warnings": [],
    }
    if is_lark_doc_url(source):
        fetched = library_dir / "fetched" / f"{safe_source_stem(source)}.md"
        target, warnings = fetch_lark_doc(source, fetched)
        record["warnings"].extend(warnings)
        if target:
            record.update({
                "runtime_source": str(target),
                "runtime_library_path": repo_rel(target),
                "preserved": True,
                "preservation_kind": "lark-doc-fetch",
            })
        return record
    if is_url(source):
        record["preservation_kind"] = "url-reference"
        return record

    path = Path(source)
    if not path.exists():
        return record
    raw_dir = library_dir / "raw"
    target = raw_dir / f"{safe_source_stem(source)}{path.suffix if path.is_file() else ''}"
    if path.is_dir():
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(path, target)
        kind = "directory-copy"
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        kind = "file-copy"
    record.update({
        "runtime_source": str(target),
        "runtime_library_path": repo_rel(target),
        "preserved": True,
        "preservation_kind": kind,
    })
    return record


def normalize_list(values: list[str] | None) -> list[str]:
    out: list[str] = []
    for value in values or []:
        for part in str(value).replace("，", ",").replace("、", ",").split(","):
            part = part.strip()
            if part:
                out.append(part)
    return list(dict.fromkeys(out))


def pdf_page_count(path: Path) -> int:
    try:
        raw = path.read_bytes()
    except OSError:
        return 0
    count = len(re.findall(rb"/Type\s*/Page\b", raw))
    return max(1, count)


def pdf_text_light(path: Path, limit: int = 12000) -> str:
    """Best-effort PDF text extraction using only the standard library.

    This is intentionally conservative. It handles common unencrypted PDFs
    with literal text strings in plain or Flate-compressed streams, and leaves
    provenance/confirmation gaps when text cannot be safely recovered.
    """
    try:
        raw = path.read_bytes()
    except OSError:
        return ""
    chunks: list[bytes] = []
    chunks.extend(match.group(1) for match in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", raw, re.S))
    expanded: list[bytes] = []
    for chunk in chunks[:80]:
        expanded.append(chunk)
        try:
            expanded.append(zlib.decompress(chunk.strip()))
        except Exception:
            pass

    texts: list[str] = []
    string_re = re.compile(rb"\((?:\\.|[^\\()]){2,}\)")
    for chunk in expanded:
        for match in string_re.finditer(chunk):
            value = match.group(0)[1:-1]
            value = re.sub(rb"\\([nrtbf()\\])", lambda m: {
                b"n": b"\n",
                b"r": b"\n",
                b"t": b"\t",
                b"b": b"",
                b"f": b"",
                b"(": b"(",
                b")": b")",
                b"\\": b"\\",
            }[m.group(1)], value)
            decoded = value.decode("utf-8", errors="ignore") or value.decode("latin1", errors="ignore")
            decoded = re.sub(r"\s+", " ", decoded).strip()
            if len(decoded) >= 2 and not re.fullmatch(r"[\W_]+", decoded):
                texts.append(decoded)
        if sum(len(item) for item in texts) >= limit:
            break
    return "\n".join(dict.fromkeys(texts))[:limit]


def xml_texts(raw: bytes) -> list[str]:
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return []
    texts: list[str] = []
    for el in root.iter():
        if el.tag.endswith("}t") or el.tag == "t":
            if el.text and el.text.strip():
                texts.append(el.text.strip())
    return texts


# ── PPTX → structured `canvas` deck.json (build_pptx backend) ────────────────
# .pptx is the ONLY native-PowerPoint entry. It is converted to a structured
# `canvas` deck.json (code reconstruction of every element — text runs, embedded
# images, shapes — NO screenshots) by build_pptx.py, which lives in the
# `pptx-to-deck` skill and runs in ITS OWN venv (python-pptx is not in the
# parser's stdlib world). Un-reconstructable pages (live chart / SmartArt / OLE)
# become text placeholders and are reported back as `unreconstructed slides` for
# the user to redo. The image / dual-background path (pptx-to-editable-html) is
# RETIRED per the 不要图 decision — we never produce screenshots here.
#
# `pptx-to-deck` was promoted out of feishu-deck-h5 into a TOP-LEVEL sibling skill
# (it uses feishu-deck-h5 as its render backend). Resolve it as a sibling, with
# fallbacks to the legacy nested location and the registered ~/.claude symlink so
# the parser keeps working across layouts.
PPTX_SKILL_DIR = next(
    (d for d in (REPO.parent / "pptx-to-deck",                 # sibling (new layout)
                 REPO / "pptx-to-html",                         # legacy nested
                 Path.home() / ".claude" / "skills" / "pptx-to-deck")  # registered symlink
     if (d / "assets" / "build_pptx.py").is_file()),
    REPO.parent / "pptx-to-deck",                              # default for the warning path
)
PPTX_VENV_PY = PPTX_SKILL_DIR / ".venv" / "bin" / "python3"
BUILD_PPTX = PPTX_SKILL_DIR / "assets" / "build_pptx.py"
UNRECONSTRUCTED_RE = re.compile(r"unreconstructed slides:\s*\[([^\]]*)\]")


def build_pptx_canvas(pptx_path: Path, out_dir: Path, title: str = "") -> dict[str, Any]:
    """Convert a .pptx to a structured `canvas` deck.json via build_pptx.py
    (run in the pptx-to-deck venv). Emits deck.json + extracted images under
    `out_dir`, then renders index.html. Returns a structured result record for
    the source-dossier: deck.json path, slide count, the `unreconstructed`
    page-number report, and any warnings. Never raises — a conversion failure is
    recorded as a warning so the dossier still writes."""
    result: dict[str, Any] = {
        "engine": "build_pptx",
        "layout": "canvas",
        "reconstruction": "structured-code-no-screenshots",
        "ok": False,
        "deck_json": "",
        "output_dir": repo_rel(out_dir),
        "unreconstructed_slides": [],
        "warnings": [],
    }
    if not PPTX_VENV_PY.is_file():
        result["warnings"].append(
            f"pptx-to-deck venv python not found at {repo_rel(PPTX_VENV_PY)}; "
            "PPTX was preserved but not converted to canvas deck.json."
        )
        return result
    if not BUILD_PPTX.is_file():
        result["warnings"].append(
            f"build_pptx.py not found at {repo_rel(BUILD_PPTX)}; PPTX not converted."
        )
        return result
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(PPTX_VENV_PY),
        str(BUILD_PPTX),
        str(pptx_path),
        str(out_dir),
        "--renderer",
        str(REPO),
    ]
    # The parser copies the source .pptx to a hashed runtime path, so build_pptx's
    # default `<stem>` title would be the hash. Pass the ORIGINAL filename stem so
    # the deck title is human-readable.
    if title:
        cmd += ["--title", title]
    try:
        proc = subprocess.run(cmd, cwd=REPO, text=True, capture_output=True, timeout=600)
    except subprocess.TimeoutExpired:
        result["warnings"].append("build_pptx.py timed out converting PPTX to canvas deck.json.")
        return result
    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    match = UNRECONSTRUCTED_RE.search(stdout)
    if match:
        result["unreconstructed_slides"] = [
            int(piece) for piece in re.findall(r"\d+", match.group(1))
        ]
    deck_path = out_dir / "deck.json"
    if proc.returncode != 0 or not deck_path.is_file():
        reason = " ".join((stderr or stdout).splitlines()[-6:])[:600]
        result["warnings"].append(
            "build_pptx.py failed to produce a canvas deck.json: " + (reason or "unknown error")
        )
        return result
    result["ok"] = True
    result["deck_json"] = repo_rel(deck_path)
    index_html = out_dir / "index.html"
    if index_html.is_file():
        result["index_html"] = repo_rel(index_html)
    try:
        deck = json.loads(deck_path.read_text(encoding="utf-8"))
        result["slide_count"] = len(deck.get("slides") or [])
    except (json.JSONDecodeError, OSError):
        pass
    if result["unreconstructed_slides"]:
        result["warnings"].append(
            "unreconstructed slides (live chart / SmartArt / OLE → placeholder, "
            "redo these pages): " + ", ".join(str(n) for n in result["unreconstructed_slides"])
        )
    return result


def pptx_slides(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    slides: list[dict[str, Any]] = []
    media: list[str] = []
    with zipfile.ZipFile(path) as zf:
        slide_names = sorted(
            [name for name in zf.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", name)],
            key=lambda item: int(re.search(r"slide(\d+)\.xml$", item).group(1)),
        )
        media = sorted(name for name in zf.namelist() if name.startswith("ppt/media/"))
        for idx, name in enumerate(slide_names, 1):
            texts = xml_texts(zf.read(name))
            title = next((text for text in texts if text), f"Slide {idx}")
            slides.append({
                "page": idx,
                "title": title[:120],
                "text": "\n".join(texts),
                "text_items": texts,
                "source_node": name,
            })
    return slides, media


class SlideHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.current_slide: dict[str, Any] | None = None
        self.current_depth = 0
        self.skip_text_stack: list[str] = []
        self.slides: list[dict[str, Any]] = []
        self.images: list[str] = []
        self.scripts: list[str] = []
        self.stylesheets: list[str] = []

    def collect_asset(self, tag: str, attr: dict[str, str]) -> None:
        if tag == "img" and attr.get("src"):
            self.images.append(attr["src"])
        if tag == "script" and attr.get("src"):
            self.scripts.append(attr["src"])
        if tag == "link" and attr.get("rel", "").lower() == "stylesheet" and attr.get("href"):
            self.stylesheets.append(attr["href"])

    def handle_slide_start(self, tag: str, attr: dict[str, str]) -> None:
        classes = set(attr.get("class", "").split())
        is_slide = tag in {"section", "div", "article"} and ("slide" in classes or attr.get("data-slide-key"))
        if is_slide:
            if self.current_slide is not None:
                self.close_slide()
            self.current_slide = {
                "tag": tag,
                "key": attr.get("data-slide-key", ""),
                "layout": attr.get("data-layout", ""),
                "screen_label": attr.get("data-screen-label", ""),
                "texts": [],
            }
            self.current_depth = 0 if tag in VOID_HTML_TAGS else 1
        elif self.current_slide is not None and tag not in VOID_HTML_TAGS:
            self.current_depth += 1

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {k: v or "" for k, v in attrs}
        self.collect_asset(tag, attr)
        if tag in {"style", "script", "svg"}:
            self.skip_text_stack.append(tag)
        self.handle_slide_start(tag, attr)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {k: v or "" for k, v in attrs}
        self.collect_asset(tag, attr)

    def handle_endtag(self, tag: str) -> None:
        if self.skip_text_stack and tag == self.skip_text_stack[-1]:
            self.skip_text_stack.pop()
        if self.current_slide is None or tag in VOID_HTML_TAGS:
            return
        self.current_depth -= 1
        if self.current_depth <= 0:
            self.close_slide()

    def close_slide(self) -> None:
        if self.current_slide is None:
            return
        slide = self.current_slide
        texts = [text for text in slide.pop("texts") if text]
        slide["title"] = texts[0][:120] if texts else slide.get("key") or "slide"
        slide["text"] = "\n".join(texts)
        slide["text_items"] = texts
        slide["page"] = len(self.slides) + 1
        self.slides.append(slide)
        self.current_slide = None
        self.current_depth = 0

    def handle_data(self, data: str) -> None:
        if self.current_slide is None or self.skip_text_stack:
            return
        text = html.unescape(re.sub(r"\s+", " ", data)).strip()
        if text:
            self.current_slide["texts"].append(text)

    def close(self) -> None:
        super().close()
        if self.current_slide is not None:
            self.close_slide()


def inspect_html(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    parser = SlideHTMLParser()
    parser.feed(raw)
    parser.close()
    expected = len(re.findall(r"\bdata-slide-key\s*=", raw))
    warnings = []
    if expected and expected != len(parser.slides):
        warnings.append(f"HTML declares {expected} data-slide-key values but parser extracted {len(parser.slides)} slides")
    return parser.slides, {
        "images": sorted(set(parser.images)),
        "scripts": sorted(set(parser.scripts)),
        "stylesheets": sorted(set(parser.stylesheets)),
        "declared_slide_keys": expected,
        "warnings": warnings,
    }


def local_html_asset_path(html_path: Path, ref: str) -> Path | None:
    """Resolve a local HTML asset ref, ignoring remote/data/hash refs."""
    ref = str(ref).strip()
    if not ref or is_url(ref) or ref.startswith(("data:", "#", "mailto:", "tel:")):
        return None
    clean = ref.split("#", 1)[0].split("?", 1)[0]
    if not clean:
        return None
    candidate = (html_path.parent / clean).resolve()
    return candidate if candidate.is_file() else None


def materialize_html_assets(inventory: list[dict[str, Any]], out_dir: Path) -> None:
    """Copy local assets referenced by HTML sources into runtime-library/assets.

    Parser docs promise downstream renderer can consume local assets from
    input/runtime-library/assets/. Source HTML previously recorded relative
    paths only, which broke once the original HTML folder was no longer next to
    the renderer. Keep remote/data refs as-is; copy local refs and rewrite the
    inventory path to the copied runtime path.
    """
    for src in inventory:
        if src.get("type") not in {"html", "htm"}:
            continue
        runtime_path = Path(str(src.get("path") or ""))
        original_path = Path(str(src.get("original_source") or runtime_path))
        source_path = original_path if original_path.is_file() else runtime_path
        if not source_path.is_file():
            continue
        html_assets = src.get("html_assets")
        if not isinstance(html_assets, dict):
            continue
        bucket = ascii_slug(source_path.stem, "html-source")
        materialized = src.setdefault("html_assets_materialized", {})
        for kind in ("images", "scripts", "stylesheets"):
            rewritten: list[str] = []
            for ref in html_assets.get(kind) or []:
                ref_text = str(ref).strip()
                origin = local_html_asset_path(source_path, ref_text)
                if origin is None:
                    rewritten.append(ref_text)
                    if ref_text and not (is_url(ref_text) or ref_text.startswith(("data:", "#"))):
                        src.setdefault("warnings", []).append(
                            f"HTML {kind[:-1] if kind.endswith('s') else kind} asset not found: {ref_text}"
                        )
                    continue
                rel = ref_text.split("#", 1)[0].split("?", 1)[0]
                rel_path = Path(rel)
                if rel_path.is_absolute() or any(part == ".." for part in rel_path.parts):
                    rel_path = Path(origin.name)
                dest = out_dir / "assets" / "html" / bucket / rel_path
                dest.parent.mkdir(parents=True, exist_ok=True)
                if not dest.exists() or dest.stat().st_size != origin.stat().st_size:
                    shutil.copy2(origin, dest)
                rewritten.append(str(dest))
            materialized[kind] = rewritten


def infer_html_role(brief: str, requested_role: str) -> str:
    if requested_role in {"source-html", "target-html"}:
        return requested_role
    if TARGET_HTML_INTENT_RE.search(brief):
        return "target-html"
    if SOURCE_HTML_INTENT_RE.search(brief):
        return "source-html"
    return "source-html"


def image_dimensions(path: Path) -> dict[str, int] | None:
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    suffix = path.suffix.lower()
    try:
        if suffix == ".png" and raw.startswith(b"\x89PNG\r\n\x1a\n") and len(raw) >= 24:
            return {"width": int.from_bytes(raw[16:20], "big"), "height": int.from_bytes(raw[20:24], "big")}
        if suffix in {".jpg", ".jpeg"} and raw[:2] == b"\xff\xd8":
            i = 2
            while i + 9 < len(raw):
                if raw[i] != 0xFF:
                    i += 1
                    continue
                marker = raw[i + 1]
                i += 2
                if marker in {0xD8, 0xD9}:
                    continue
                length = int.from_bytes(raw[i:i + 2], "big")
                if marker in set(range(0xC0, 0xC4)) | set(range(0xC5, 0xC8)) | set(range(0xC9, 0xCC)) | set(range(0xCD, 0xD0)):
                    return {"height": int.from_bytes(raw[i + 3:i + 5], "big"), "width": int.from_bytes(raw[i + 5:i + 7], "big")}
                i += max(length, 2)
        if suffix == ".webp" and raw.startswith(b"RIFF") and raw[8:12] == b"WEBP":
            if raw[12:16] == b"VP8X" and len(raw) >= 30:
                return {
                    "width": int.from_bytes(raw[24:27] + b"\x00", "little") + 1,
                    "height": int.from_bytes(raw[27:30] + b"\x00", "little") + 1,
                }
        if suffix == ".svg":
            text = raw[:2000].decode("utf-8", errors="ignore")
            width = re.search(r'\bwidth=["\']?(\d+)', text)
            height = re.search(r'\bheight=["\']?(\d+)', text)
            if width and height:
                return {"width": int(width.group(1)), "height": int(height.group(1))}
            viewbox = re.search(r'\bviewBox=["\'][^"\']*?\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)["\']', text)
            if viewbox:
                return {"width": int(float(viewbox.group(1))), "height": int(float(viewbox.group(2)))}
    except Exception:
        return None
    return None


def resolve_markdown_media(path: Path, ref: str) -> Path | None:
    if is_url(ref) or ref.startswith(("data:", "#")):
        return None
    candidate = (path.parent / ref.split("#", 1)[0].split("?", 1)[0]).resolve()
    return candidate if candidate.is_file() else None


def classify_image_usage(ref: str, *, alt: str = "", context: str = "", dimensions: dict[str, int] | None = None) -> dict[str, Any]:
    text = f"{ref}\n{alt}\n{context}"
    lower = text.lower()
    signals: list[str] = []
    reconstruct_score = 0
    direct_score = 0

    explicit_image_page_re = r"单独放一页|直接插入图片|无需标题"
    if re.search(explicit_image_page_re, text, flags=re.I):
        return {
            "render_mode": "direct_image_page",
            "confidence": "high",
            "rationale": "Source explicitly asks for this image to be inserted as a standalone page with no title; designer/renderer must preserve it as an image page.",
            "signals": [f"direct-image-page:{explicit_image_page_re}"],
        }

    reconstruct_patterns = [
        r"第\s*\d+\s*页",
        r"\bslide\s*\d+\b",
        r"\bppt\b",
        r"演示页|页面截图|截图了一页|整页截图|全页图|整页图",
        r"单独放一页|直接插入图片|无需标题",
        r"复刻|复现|还原|重建",
        r"业务领域|应用场景|能力层级|成熟度分层|建设路径|路线图|架构图|流程图|矩阵|泳道|表格",
    ]
    for pattern in reconstruct_patterns:
        if re.search(pattern, text, flags=re.I):
            reconstruct_score += 2
            signals.append(f"reconstruct:{pattern}")

    direct_patterns = [
        r"logo|图标|icon|二维码|头像",
        r"照片|实拍|门店照|产品图|商品图",
        r"背景图|封面图|氛围图|海报|banner",
        r"系统截图|界面截图|产品截图",
    ]
    for pattern in direct_patterns:
        if re.search(pattern, lower, flags=re.I):
            direct_score += 2
            signals.append(f"direct:{pattern}")

    if dimensions:
        width = dimensions.get("width", 0)
        height = dimensions.get("height", 0)
        ratio = width / height if height else 0
        if width >= 900 and height >= 500 and 1.45 <= ratio <= 1.9:
            reconstruct_score += 2
            signals.append("reconstruct:large-16x9-like-image")
        elif width <= 400 or height <= 260:
            direct_score += 1
            signals.append("direct:small-supporting-asset")

    if reconstruct_score >= 3 and reconstruct_score >= direct_score:
        return {
            "render_mode": "reconstruct_html",
            "confidence": "high" if reconstruct_score >= 5 else "medium",
            "rationale": "Image appears to be a slide/page screenshot or diagram that should be rebuilt as editable HTML instead of embedded as a flat bitmap.",
            "signals": signals,
        }
    return {
        "render_mode": "direct_asset",
        "confidence": "medium" if direct_score else "low",
        "rationale": "Image appears to be supporting visual material that can be used directly if selected by designer/renderer.",
        "signals": signals,
    }


def markdown_image_entries(text: str, path: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    lines = text.splitlines()
    seen: set[str] = set()
    for line_no, line in enumerate(lines):
        for match in re.finditer(r"!\[([^\]]*)\]\(([^)]+)\)", line):
            alt = match.group(1).strip()
            ref = match.group(2).strip()
            if not ref or ref in seen:
                continue
            seen.add(ref)
            context_lines = [
                item.strip()
                for item in lines[max(0, line_no - 3): min(len(lines), line_no + 4)]
                if item.strip() and item.strip() != line.strip()
            ]
            context = "\n".join(context_lines)[:1200]
            local = resolve_markdown_media(path, ref)
            dims = image_dimensions(local) if local else None
            entries.append({
                "path": ref,
                "alt": alt,
                "context": context,
                "line": line_no + 1,
                "local_path": repo_rel(local) if local else "",
                "dimensions": dims or {},
                "render_decision": classify_image_usage(ref, alt=alt, context=context, dimensions=dims),
            })
    return entries


def markdown_image_refs(text: str) -> list[str]:
    refs = []
    for match in re.finditer(r"!\[[^\]]*\]\(([^)]+)\)", text):
        ref = match.group(1).strip()
        if ref:
            refs.append(ref)
    return list(dict.fromkeys(refs))


MARKDOWN_PAGE_HEADING_RE = re.compile(
    r"^(?:第\s*([0-9０-９一二三四五六七八九十百]+)\s*页|P\s*([0-9０-９]+))"
    r"(?:\s*[｜|:：\-]\s*)?(.*)$",
    re.I,
)


def normalize_page_number(value: str | None, fallback: int) -> int | str:
    if not value:
        return fallback
    table = str.maketrans("０１２３４５６７８９", "0123456789")
    normalized = value.translate(table).strip()
    if normalized.isdigit():
        return int(normalized)
    return normalized or fallback


def markdown_page_heading(line: str) -> dict[str, Any] | None:
    stripped = line.strip()
    if not stripped:
        return None
    heading = re.sub(r"^#{1,6}\s*", "", stripped).strip()
    if re.match(r"^P\s*\d+\s*-\s*P\s*\d+", heading, re.I):
        return None
    match = MARKDOWN_PAGE_HEADING_RE.match(heading)
    if not match:
        return None
    page_label = match.group(1) or match.group(2)
    suffix = (match.group(3) or "").strip()
    title = heading[:160] if heading else suffix[:160]
    return {
        "page_label": page_label,
        "title": title or f"第{page_label}页",
        "suffix": suffix,
    }


def markdown_table_count(text: str) -> int:
    separator = re.compile(r"^\s*\|?\s*:?-{1,}:?\s*(?:\|\s*:?-{1,}:?\s*)+\|?\s*$")
    return sum(1 for line in text.splitlines() if separator.match(line))


SOURCE_LAYOUT_DIRECTIVE_RE = re.compile(
    r"(视觉建议|(?:左侧|右侧)页面|直接插入图片|单独放一页|"
    r"(?:左边|左侧|右边|右侧)(?:表格|配图)|左表右图|左表格右配图|倒漏斗|阶梯)"
)

BATCH_LAYOUT_DIRECTIVE_RE = re.compile(
    r"P\s*([0-9０-９]+)\s*-\s*P\s*([0-9０-９]+)[^\n。；;]*?"
    r"(?:左边表格|左表|右边配图|右图|左表右图|表格[^\n。；;]*配图)",
    re.I,
)


def extract_source_layout_directives(text: str) -> tuple[list[str], list[str]]:
    directives: list[str] = []
    markers: list[str] = []
    marker_re = re.compile(r"[【\[]\s*((?:左侧|右侧)页面)\s*[】\]]")
    for line in text.splitlines():
        stripped = re.sub(r"^[>\s#*`-]+", "", line).strip()
        if not stripped:
            continue
        if SOURCE_LAYOUT_DIRECTIVE_RE.search(stripped):
            directives.append(stripped[:240])
        for marker in marker_re.findall(stripped):
            markers.append(marker)
    return list(dict.fromkeys(directives)), list(dict.fromkeys(markers))


def page_number_int(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    normalized = normalize_page_number(str(value or ""), -1)
    return normalized if isinstance(normalized, int) and normalized >= 0 else None


def extract_batch_layout_directives(text: str) -> list[dict[str, Any]]:
    directives: list[dict[str, Any]] = []
    for match in BATCH_LAYOUT_DIRECTIVE_RE.finditer(text):
        start = page_number_int(match.group(1))
        end = page_number_int(match.group(2))
        if start is None or end is None:
            continue
        if end < start:
            start, end = end, start
        directive = re.sub(r"\s+", " ", match.group(0)).strip()
        directives.append({
            "start_page": start,
            "end_page": end,
            "directive": directive[:240],
            "layout": "left-table-right-image",
        })
    return directives


def apply_batch_layout_directives(sections: list[dict[str, Any]], text: str) -> None:
    for directive in extract_batch_layout_directives(text):
        start = int(directive["start_page"])
        end = int(directive["end_page"])
        for section in sections:
            page = page_number_int(section.get("page"))
            if page is None or page < start or page > end:
                continue
            section["layout"] = "source-directed-layout"
            section["detail_fidelity"] = "preserve-layout"
            directives = list(section.get("design_directives") or [])
            directives.append(str(directive["directive"]))
            section["design_directives"] = list(dict.fromkeys(directives))
            section["batch_layout_directive"] = directive


def markdown_page_sections(text: str, fallback_title: str) -> list[dict[str, Any]]:
    lines = text.splitlines()
    starts: list[tuple[int, dict[str, Any]]] = []
    for idx, line in enumerate(lines):
        heading = markdown_page_heading(line)
        if heading:
            starts.append((idx, heading))

    if not starts:
        tables = markdown_table_count(text)
        directives, markers = extract_source_layout_directives(text)
        return [{
            "page": 1,
            "title": fallback_title[:120],
            "text": text,
            "source_node": "markdown-section-001",
            "table_count": tables,
            "detail_fidelity": "preserve-layout" if directives else ("preserve-table" if tables else "summarize-ok"),
            "layout": "source-directed-layout" if directives else ("markdown-table-detail" if tables else "markdown-section"),
            "design_directives": directives,
            "section_markers": markers,
        }]

    sections: list[dict[str, Any]] = []
    preamble = lines[:starts[0][0]]
    for section_idx, (start_idx, heading) in enumerate(starts):
        end_idx = starts[section_idx + 1][0] if section_idx + 1 < len(starts) else len(lines)
        section_lines = lines[start_idx:end_idx]
        if section_idx == 0 and any(item.strip() for item in preamble):
            section_lines = preamble + [""] + section_lines
        section_text = "\n".join(section_lines).strip()
        tables = markdown_table_count(section_text)
        directives, markers = extract_source_layout_directives(section_text)
        page = normalize_page_number(str(heading.get("page_label") or ""), section_idx + 1)
        sections.append({
            "page": page,
            "title": str(heading.get("title") or f"第{page}页")[:120],
            "text": section_text,
            "source_node": f"markdown-page-{section_idx + 1:03d}",
            "table_count": tables,
            "detail_fidelity": "preserve-layout" if directives else ("preserve-table" if tables else "summarize-ok"),
            "layout": "source-directed-layout" if directives else ("markdown-table-detail" if tables else "markdown-section"),
            "design_directives": directives,
            "section_markers": markers,
        })
    apply_batch_layout_directives(sections, text)
    return sections


def inspect_text(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    title = next((line.lstrip("#").strip() for line in text.splitlines() if line.strip()), path.stem)
    sections = markdown_page_sections(text, title) if path.suffix.lower() == ".md" else [{
        "page": 1,
        "title": title[:120],
        "text": text,
        "source_node": "text-section-001",
        "table_count": markdown_table_count(text),
        "detail_fidelity": "preserve-table" if markdown_table_count(text) else "summarize-ok",
    }]

    slides: list[dict[str, Any]] = []
    for idx, section in enumerate(sections, 1):
        section_text = str(section.get("text") or "")
        table_count = int(section.get("table_count") or 0)
        design_directives = [str(item) for item in section.get("design_directives") or [] if str(item).strip()]
        section_markers = [str(item) for item in section.get("section_markers") or [] if str(item).strip()]
        slide: dict[str, Any] = {
            "page": section.get("page", idx),
            "key": f"{path.stem}-p{idx:03d}",
            "title": str(section.get("title") or title)[:120],
            "text": section_text[:20000],
            "text_items": [section_text[:20000]] if section_text else [],
            "source_node": section.get("source_node") or f"markdown-section-{idx:03d}",
            "layout": section.get("layout") or ("markdown-table-detail" if table_count else "markdown-section"),
            "table_count": table_count,
            "detail_fidelity": section.get("detail_fidelity") or ("preserve-table" if table_count else "summarize-ok"),
        }
        if design_directives:
            slide["design_directives"] = design_directives
            slide["section_markers"] = section_markers
            if isinstance(section.get("batch_layout_directive"), dict):
                slide["batch_layout_directive"] = section["batch_layout_directive"]
        if table_count or design_directives:
            detail_preservation = "preserve-layout" if design_directives else "preserve-table"
            slide["reconstruction_hint"] = {
                "source_kind": "markdown-page",
                "table_count": table_count,
                "detail_preservation": detail_preservation,
                "rationale": "Source page contains explicit layout instructions, tables, or matrices; designer/renderer should preserve the instructed structure and row-level details or explicitly split them across pages.",
            }
            if design_directives:
                slide["reconstruction_hint"]["design_directives"] = design_directives
                slide["reconstruction_hint"]["section_markers"] = section_markers
                if isinstance(section.get("batch_layout_directive"), dict):
                    slide["reconstruction_hint"]["batch_layout_directive"] = section["batch_layout_directive"]
                    slide["reconstruction_hint"]["preferred_layout"] = section["batch_layout_directive"].get("layout")
            if table_count and design_directives:
                slide["reconstruction_hint"]["table_detail_preservation"] = "preserve-table"
        slides.append(slide)
    return slides, markdown_image_refs(text)


def slide_text_budget(slide: dict[str, Any], *, long: int, short: int) -> int:
    if slide.get("detail_fidelity") in {"preserve-table", "preserve-layout"} or int(slide.get("table_count") or 0) > 0:
        return long
    return short


TEXT_SKIP_KEYS = {
    "src",
    "image",
    "video",
    "poster",
    "thumbnail",
    "page_image",
    "href",
    "fit",
    "position",
    "type",
    "tone",
    "icon",
    "decor",
    "layout",
    "variant",
}


def collect_text_values(value: Any, key: str = "") -> list[str]:
    texts: list[str] = []
    if key in TEXT_SKIP_KEYS:
        return texts
    if isinstance(value, str):
        text = re.sub(r"\s+", " ", value).strip()
        if key == "accent" and text.lower() in {"blue", "teal", "orange", "green", "red", "purple", "gray", "dark"}:
            return texts
        if text:
            texts.append(text)
    elif isinstance(value, list):
        for item in value:
            texts.extend(collect_text_values(item, key))
    elif isinstance(value, dict):
        for item_key, item in value.items():
            texts.extend(collect_text_values(item, str(item_key)))
    return texts


def collect_media_refs(value: Any) -> list[str]:
    refs: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"src", "image", "video", "poster", "thumbnail", "page_image", "href"} and isinstance(item, str):
                if Path(item).suffix.lower() in MEDIA_EXTS | {".html", ".htm"}:
                    refs.append(item)
            refs.extend(collect_media_refs(item))
    elif isinstance(value, list):
        for item in value:
            refs.extend(collect_media_refs(item))
    return refs


def inspect_json(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return inspect_text(path), []
    if not isinstance(data, dict) or not isinstance(data.get("slides"), list):
        return inspect_text(path), []
    slides: list[dict[str, Any]] = []
    media: list[str] = []
    for idx, slide in enumerate(data.get("slides") or [], 1):
        if not isinstance(slide, dict):
            continue
        payload = slide.get("data") if isinstance(slide.get("data"), dict) else slide
        texts = list(dict.fromkeys(collect_text_values(payload)))[:80]
        media.extend(collect_media_refs(payload))
        title = (
            slide.get("screen_label")
            or (payload.get("title") if isinstance(payload, dict) else "")
            or slide.get("key")
            or f"Slide {idx}"
        )
        slides.append({
            "page": idx,
            "key": str(slide.get("key") or f"{path.stem}-p{idx:03d}"),
            "title": str(title)[:120],
            "layout": str(slide.get("layout") or ""),
            "variant": str(slide.get("variant") or ""),
            "text": "\n".join(texts),
            "text_items": texts,
        })
    return slides, sorted(set(media))


def inventory_path(path: Path) -> dict[str, Any]:
    suffix = path.suffix.lower()
    base: dict[str, Any] = {
        "path": repo_rel(path),
        "name": path.name,
        "type": "directory" if path.is_dir() else suffix.lstrip(".") or "file",
        "exists": path.exists(),
    }
    if not path.exists():
        return {**base, "error": "not found"}
    if path.is_file():
        base.update({"size_bytes": path.stat().st_size, "sha256": sha256(path)})
    if path.is_dir():
        children = sorted(p for p in path.rglob("*") if p.is_file())
        base["file_count"] = len(children)
        base["children"] = [repo_rel(p) for p in children[:200]]
        base["media"] = [repo_rel(p) for p in children if p.suffix.lower() in MEDIA_EXTS][:200]
        return base
    if suffix == ".pptx":
        slides, media = pptx_slides(path)
        return {**base, "slide_count": len(slides), "slides": slides, "media": media}
    if suffix == ".ppt":
        return {
            **base,
            "processing_status": "needs_conversion",
            "slides": [],
            "warnings": ["Legacy .ppt text extraction is not available in the stdlib parser; convert to .pptx or PDF."],
        }
    if suffix == ".key":
        return {
            **base,
            "processing_status": "needs_keynote_to_html",
            "slides": [],
            "recommended_reuse": {
                "skill": "keynote-to-html",
                "command": "bash skills/keynote-to-html/assets/run.sh <key-file> <input/runtime-library/assets/keynote-html/<stem>>",
                "outputs_to_register": ["deck.json", "index.html", "assets/slide-NN/*"],
            },
            "warnings": [
                "Keynote files require keynote-to-html for page-level text, image, and video extraction; this stdlib parser only preserved the source file.",
            ],
        }
    if suffix == ".pdf":
        pages = pdf_page_count(path)
        text = pdf_text_light(path)
        slides = [
            {
                "page": idx,
                "title": f"{path.stem} · Page {idx}",
                "text": text if idx == 1 else "",
                "text_items": [text] if text and idx == 1 else [],
                "source_node": f"page-{idx}",
            }
            for idx in range(1, pages + 1)
        ]
        warnings = [] if text else ["PDF page count extracted, but no selectable text was recovered; renderer should use page replica or ask for source text."]
        return {**base, "page_count": pages, "slide_count": pages, "slides": slides, "warnings": warnings}
    if suffix in {".html", ".htm"}:
        slides, assets = inspect_html(path)
        return {**base, "slide_count": len(slides), "slides": slides, "html_assets": assets}
    if suffix == ".json":
        slides, media = inspect_json(path)
        return {**base, "slide_count": len(slides), "slides": slides, "media": media}
    if suffix in {".md", ".txt"}:
        slides, media = inspect_text(path)
        text = path.read_text(encoding="utf-8", errors="ignore")
        return {**base, "slides": slides, "media": media, "media_annotations": markdown_image_entries(text, path)}
    if suffix in IMAGE_EXTS:
        dims = image_dimensions(path) or {}
        return {
            **base,
            "material_kind": "image",
            "image_dimensions": dims,
            "render_decision": classify_image_usage(path.name, dimensions=dims),
        }
    if suffix in VIDEO_EXTS:
        return {**base, "material_kind": "video"}
    if suffix in AUDIO_EXTS:
        return {**base, "material_kind": "audio"}
    return base


def inventory_source(source: str) -> dict[str, Any]:
    if re.match(r"https?://", source):
        source_type = "larkdoc-url" if re.search(r"(larkoffice\.com|feishu\.cn)/(docx|docs|wiki|file|slides)/", source) else "url"
        return {
            "path": source,
            "name": source.rsplit("/", 1)[-1],
            "type": source_type,
            "exists": True,
            "processing_status": "metadata-only",
            "warnings": ["URL content was not fetched by the stdlib parser; provide an exported file or run the Lark document reader before planning."],
        }
    return inventory_path(Path(source))


def slide_item_covering_media(slide_items: list[dict[str, Any]], source_path: str, media_ref: str) -> dict[str, Any] | None:
    for slide in reversed(slide_items):
        if str(slide.get("runtime_source") or "") != str(source_path):
            continue
        if media_ref and media_ref in str(slide.get("text_summary") or ""):
            return slide
    return None


def apply_direct_image_hint(slide: dict[str, Any], media_ref: str, render_decision: dict[str, Any]) -> None:
    slide["layout_hint"] = "direct-image-page"
    hint = slide.setdefault("reconstruction_hint", {})
    hint["source_image"] = media_ref
    hint["render_mode"] = render_decision.get("render_mode")
    hint["rationale"] = render_decision.get("rationale", "")
    hint["signals"] = render_decision.get("signals", [])
    hint["detail_preservation"] = "preserve-image-page"
    hint["image_page_behavior"] = "standalone-no-title"


def build_layers(inventory: list[dict[str, Any]], brief: str) -> dict[str, Any]:
    knowledge_items: list[dict[str, Any]] = []
    material_items: list[dict[str, Any]] = []
    slide_items: list[dict[str, Any]] = []
    needs_confirmation: list[str] = []
    for src in inventory:
        source_path = src.get("path", "")
        original_source = src.get("original_source") or source_path
        annotations_by_path = {
            str(item.get("path")): item
            for item in src.get("media_annotations") or []
            if isinstance(item, dict) and item.get("path")
        }
        if not src.get("exists", True):
            needs_confirmation.append(f"source not found: {source_path}")
        for warning in src.get("warnings") or []:
            needs_confirmation.append(f"{source_path}: {warning}")
        if src.get("processing_status") in {"needs_conversion", "needs_keynote_to_html", "metadata-only"}:
            needs_confirmation.append(f"{source_path}: {src.get('processing_status')}")
        for idx, slide in enumerate(src.get("slides") or [], 1):
            text = str(slide.get("text") or "")
            slide_key = str(slide.get("key") or f"{Path(str(source_path)).stem or 'source'}-p{idx:03d}")
            content_limit = slide_text_budget(slide, long=12000, short=3000)
            summary_limit = slide_text_budget(slide, long=1600, short=500)
            if text:
                knowledge_items.append({
                    "id": f"know-{slide_key}",
                    "title": slide.get("title") or slide_key,
                    "content": text[:content_limit],
                    "provenance": {
                        "source": original_source,
                        "runtime_source": source_path,
                        "page": slide.get("page", idx),
                        "slide_key": slide_key,
                    },
                    "confidence": "extracted-text",
                })
            slide_item = {
                "slide_key": slide_key,
                "title": slide.get("title") or slide_key,
                "source": original_source,
                "runtime_source": source_path,
                "page": slide.get("page", idx),
                "layout_hint": slide.get("layout", ""),
                "text_summary": text[:summary_limit],
            }
            if isinstance(slide.get("reconstruction_hint"), dict):
                slide_item["reconstruction_hint"] = slide["reconstruction_hint"]
            slide_items.append(slide_item)
        for item in src.get("media") or []:
            annotation = annotations_by_path.get(str(item), {})
            render_decision = annotation.get("render_decision") if isinstance(annotation.get("render_decision"), dict) else None
            material_item = {
                "id": f"media-{hashlib.sha1(str(item).encode()).hexdigest()[:10]}",
                "type": Path(str(item)).suffix.lower().lstrip(".") or "media",
                "path": item,
                "provenance": {"source": original_source, "runtime_source": source_path},
            }
            if render_decision:
                material_item["render_decision"] = render_decision
            if annotation.get("context"):
                material_item["context"] = str(annotation.get("context"))[:1200]
            if annotation.get("alt"):
                material_item["alt"] = str(annotation.get("alt"))[:240]
            material_items.append(material_item)

            if render_decision and render_decision.get("render_mode") in {"reconstruct_html", "direct_image_page"}:
                digest = hashlib.sha1(f"{source_path}:{item}".encode("utf-8")).hexdigest()[:10]
                is_direct_image_page = render_decision.get("render_mode") == "direct_image_page"
                slide_key = f"{'image-page' if is_direct_image_page else 'reconstruct'}-{digest}"
                context = str(annotation.get("context") or annotation.get("alt") or "")
                title = str(annotation.get("alt") or ("图片页" if is_direct_image_page else "图片页需重建")).strip()
                knowledge_items.append({
                    "id": f"know-{slide_key}",
                    "title": title[:120],
                    "content": (
                        (
                            "Parser 判断源文档明确要求该图片单独成页且无需标题。"
                            "请把它作为独立图片页保留,不要改写成普通图表、流程页或摘要页。"
                        )
                        if is_direct_image_page else
                        (
                            "Parser 判断该图片更像 PPT/页面截图或复杂图表,不应作为整页扁平图片直接嵌入最终 HTML。"
                            "请将其作为知识和版式线索,用可编辑 HTML 重新复刻。"
                        )
                        + (f"\n\n上下文:\n{context[:1200]}" if context else "")
                    ),
                    "provenance": {
                        "source": original_source,
                        "runtime_source": source_path,
                        "page": annotation.get("line") or "",
                        "slide_key": slide_key,
                    },
                    "confidence": "image-reconstruction-hint",
                })
                if is_direct_image_page:
                    covered_slide = slide_item_covering_media(slide_items, str(source_path), str(item))
                    if covered_slide:
                        apply_direct_image_hint(covered_slide, str(item), render_decision)
                        continue
                slide_items.append({
                    "slide_key": slide_key,
                    "title": title[:120],
                    "source": original_source,
                    "runtime_source": source_path,
                    "page": annotation.get("line") or "",
                    "layout_hint": "direct-image-page" if is_direct_image_page else "reconstruct-html",
                    "text_summary": (
                        context[:500] or "Image should be inserted as a standalone no-title page."
                        if is_direct_image_page else
                        context[:500] or "Image should be rebuilt as editable HTML, not embedded as a flat bitmap."
                    ),
                    "reconstruction_hint": {
                        "source_image": item,
                        "render_mode": render_decision.get("render_mode"),
                        "rationale": render_decision.get("rationale", ""),
                        "signals": render_decision.get("signals", []),
                    },
                })
                if is_direct_image_page:
                    slide_items[-1]["reconstruction_hint"]["detail_preservation"] = "preserve-image-page"
                    slide_items[-1]["reconstruction_hint"]["image_page_behavior"] = "standalone-no-title"
                else:
                    needs_confirmation.append(f"{source_path}: image `{item}` should be rebuilt as editable HTML before final rendering")
        html_assets = src.get("html_assets") if isinstance(src.get("html_assets"), dict) else {}
        html_assets_materialized = (
            src.get("html_assets_materialized")
            if isinstance(src.get("html_assets_materialized"), dict)
            else {}
        )
        for kind, asset_type in [
            ("images", "image"),
            ("scripts", "script"),
            ("stylesheets", "stylesheet"),
        ]:
            items = html_assets_materialized.get(kind) or html_assets.get(kind) or []
            for item in items:
                item_text = str(item).strip()
                if not item_text:
                    continue
                digest = hashlib.sha1(f"{source_path}:{kind}:{item_text}".encode("utf-8")).hexdigest()[:10]
                material_items.append({
                    "id": f"html-{asset_type}-{digest}",
                    "type": asset_type,
                    "path": item_text,
                    "provenance": {"source": original_source, "runtime_source": source_path},
                })
        if src.get("material_kind"):
            material_item = {
                "id": f"asset-{hashlib.sha1(str(source_path).encode()).hexdigest()[:10]}",
                "type": src.get("material_kind"),
                "path": source_path,
                "provenance": {"source": original_source, "runtime_source": source_path},
            }
            if isinstance(src.get("render_decision"), dict):
                material_item["render_decision"] = src["render_decision"]
            if isinstance(src.get("image_dimensions"), dict) and src.get("image_dimensions"):
                material_item["dimensions"] = src["image_dimensions"]
            material_items.append(material_item)
    if not any(item.get("content") for item in knowledge_items) and brief:
        needs_confirmation.append("source text could not be extracted; designer should rely on brief and ask for proof.")
    return {
        "knowledge_layer": knowledge_items,
        "material_layer": material_items,
        "slide_layer": slide_items,
        "confidence": {"needs_confirmation": list(dict.fromkeys(needs_confirmation))},
    }


def ensure_render_decision(material: dict[str, Any]) -> dict[str, Any]:
    render_decision = material.get("render_decision")
    if isinstance(render_decision, dict):
        return render_decision
    render_decision = {
        "render_mode": "direct_asset",
        "confidence": "medium",
        "rationale": "Lark document media was materialized as a local preview asset for downstream rendering.",
    }
    material["render_decision"] = render_decision
    return render_decision


def materialize_lark_media_previews(dossier: dict[str, Any], out_dir: Path) -> None:
    asset_dir = out_dir / "assets" / "source-media"
    token_to_local_path: dict[str, str] = {}
    warnings: list[str] = []
    for material in dossier.get("material_layer") or []:
        if not isinstance(material, dict):
            continue
        source_url = str(material.get("path") or "")
        token = token_from_lark_file_url(source_url)
        if not token:
            continue
        hint = str(material.get("alt") or material.get("id") or "")
        destination = unique_media_preview_path(asset_dir, token, hint)
        result = fetch_lark_media_preview(token, destination)
        render_decision = ensure_render_decision(material)
        render_decision["source_url"] = source_url
        render_decision["media_preview"] = result
        if result.get("ok"):
            local_path = repo_rel(destination)
            material["path"] = local_path
            dimensions = image_dimensions(destination)
            if dimensions:
                material["dimensions"] = dimensions
            token_to_local_path[token] = local_path
        else:
            warnings.append(f"{source_url}: docs +media-preview failed: {result.get('error') or 'unknown error'}")

    if token_to_local_path:
        for slide in dossier.get("slide_layer") or []:
            if not isinstance(slide, dict) or not isinstance(slide.get("reconstruction_hint"), dict):
                continue
            hint = slide["reconstruction_hint"]
            source_image = str(hint.get("source_image") or "")
            token = token_from_lark_file_url(source_image)
            if token and token in token_to_local_path:
                hint["source_image_url"] = source_image
                hint["source_image"] = token_to_local_path[token]

    if warnings:
        confidence = dossier.setdefault("confidence", {"needs_confirmation": []})
        needs = list(confidence.get("needs_confirmation") or [])
        needs.extend(warnings)
        confidence["needs_confirmation"] = list(dict.fromkeys(needs))


def render_markdown(dossier: dict[str, Any]) -> str:
    lines = [
        "# Source Dossier",
        "",
        f"- brief: {dossier.get('brief') or '(empty)'}",
        f"- sources: {len(dossier.get('source_inventory') or [])}",
        f"- knowledge_items: {len(dossier.get('knowledge_layer') or [])}",
        f"- material_items: {len(dossier.get('material_layer') or [])}",
        f"- slide_items: {len(dossier.get('slide_layer') or [])}",
        "",
        "## Sources",
    ]
    for src in dossier.get("source_inventory") or []:
        count = src.get("slide_count") or src.get("page_count") or src.get("file_count") or ""
        original = src.get("original_source")
        suffix = f" · original=`{original}`" if original and original != src.get("path") else ""
        lines.append(f"- `{src.get('path')}` · {src.get('type')} {count}{suffix}")
    if dossier.get("confidence", {}).get("needs_confirmation"):
        lines.extend(["", "## Needs Confirmation"])
        lines.extend(f"- {item}" for item in dossier["confidence"]["needs_confirmation"])
    reconstruction_items = [
        item for item in dossier.get("material_layer") or []
        if isinstance(item.get("render_decision"), dict)
        and item["render_decision"].get("render_mode") == "reconstruct_html"
    ]
    if reconstruction_items:
        lines.extend(["", "## Image Render Decisions"])
        for item in reconstruction_items:
            lines.append(
                f"- `{item.get('path')}` · reconstruct_html · "
                f"{item.get('render_decision', {}).get('rationale', '')}"
            )
    failed = [src for src in dossier.get("source_inventory") or [] if not src.get("exists", True)]
    if failed:
        lines.extend(["", "## Failed Sources"])
        lines.extend(f"- `{src.get('path')}` · {src.get('error') or 'unavailable'}" for src in failed)
    if dossier.get("ppt_library_uploads"):
        lines.extend(["", "## PPT Library Uploads"])
        for item in dossier["ppt_library_uploads"]:
            lines.append(f"- `{item.get('source')}` · registered={len(item.get('registered') or [])}")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("sources", nargs="+", help="source files, folders, or URLs")
    ap.add_argument("--brief", default="")
    ap.add_argument("--output-dir", type=Path)
    ap.add_argument("--task-id", default="")
    ap.add_argument("--register-ppt-library", action="store_true")
    ap.add_argument("--page", action="append", type=int, default=[])
    ap.add_argument("--title", default="")
    ap.add_argument("--industry", action="append", default=[])
    ap.add_argument("--product", action="append", default=[])
    ap.add_argument("--tag", action="append", default=[])
    ap.add_argument(
        "--html-role",
        choices=["auto", "source-html", "target-html"],
        default="auto",
        help="classify HTML inputs as reference source material or the target artifact to edit",
    )
    ap.add_argument("--allow-missing", action="store_true", help="write dossier but exit 0 even when local source files are missing")
    args = ap.parse_args(argv)

    task_id = args.task_id or f"parser-{now_slug()}"
    out_dir = args.output_dir or (REPO / "runs" / task_id / "input" / "runtime-library")
    if not out_dir.is_absolute():
        out_dir = REPO / out_dir

    library_dir = out_dir / "source-library"
    # Run output dir for PPTX → canvas deck.json conversion. Canonical layout is
    # runs/<task-id>/input/runtime-library, so the run output is the sibling
    # `output/` of the run root (out_dir.parents[1] == runs/<task-id>). If
    # --output-dir points somewhere non-canonical, fall back to a `pptx-canvas`
    # subdir under it so the conversion artifacts still have a home.
    try:
        run_root = out_dir.parents[1]
        pptx_canvas_root = run_root / "output"
    except IndexError:
        pptx_canvas_root = out_dir / "pptx-canvas"
    prepared_sources = [prepare_runtime_source(source, library_dir) for source in args.sources]
    inventory = []
    for prepared in prepared_sources:
        item = inventory_source(str(prepared["runtime_source"]))
        item["original_source"] = prepared["original_source"]
        item["runtime_source"] = prepared["runtime_source"]
        if prepared.get("runtime_library_path"):
            item["runtime_library_path"] = prepared["runtime_library_path"]
        item["preservation_status"] = "preserved" if prepared.get("preserved") else "reference-only"
        item["preservation_kind"] = prepared.get("preservation_kind", "")
        warnings = list(item.get("warnings") or [])
        warnings.extend(prepared.get("warnings") or [])
        if warnings:
            item["warnings"] = list(dict.fromkeys(warnings))
        if item.get("type") in {"html", "htm"}:
            source_role = infer_html_role(args.brief, args.html_role)
            item["source_role"] = source_role
            item["html_import_mode"] = "imported_existing_state" if source_role == "target-html" else "source_material"
            if source_role == "target-html":
                item["editor_bootstrap"] = {
                    "required_artifacts": [
                        "input/source.html",
                        "input/runtime-library/source-dossier.json",
                        "output/DESIGN-PLAN.md",
                        "output/outline.json",
                        "output/deck.json",
                        "output/index.html",
                    ],
                    "deckjson_strategy": "preserve slides/data-slide-key when detected; otherwise wrap page or major sections as raw slides",
                }
        # PPTX → structured `canvas` deck.json (single .pptx entry point). Run
        # build_pptx via the pptx-to-deck venv; record the canvas deck.json + the
        # `unreconstructed slides` report on this inventory item. Multiple .pptx
        # sources get per-source output dirs so they don't clobber each other.
        if item.get("type") == "pptx" and item.get("exists", True):
            pptx_path = Path(str(prepared["runtime_source"]))
            multi = sum(1 for s in args.sources if str(s).lower().endswith(".pptx")) > 1
            conv_dir = (pptx_canvas_root / safe_source_stem(item["original_source"])
                        if multi else pptx_canvas_root)
            orig_stem = Path(str(item.get("original_source") or pptx_path)).stem
            conv = build_pptx_canvas(pptx_path, conv_dir, title=orig_stem)
            item["canvas_conversion"] = conv
            if conv.get("ok"):
                item["deck_json"] = conv.get("deck_json", "")
                item["unreconstructed_slides"] = conv.get("unreconstructed_slides", [])
            warnings = list(item.get("warnings") or [])
            warnings.extend(conv.get("warnings") or [])
            if warnings:
                item["warnings"] = list(dict.fromkeys(warnings))
        inventory.append(item)
    materialize_html_assets(inventory, out_dir)
    layers = build_layers(inventory, args.brief)
    html_roles = sorted({
        str(src.get("source_role"))
        for src in inventory
        if src.get("source_role")
    })
    ppt_uploads = []
    if args.register_ppt_library:
        for source in args.sources:
            path = Path(source)
            if path.suffix.lower() not in {".ppt", ".pptx"} or not path.exists():
                continue
            ppt_uploads.append(
                slide_library.register_ppt_upload(
                    path,
                    {
                        "title": args.title or path.stem,
                        "industry": normalize_list(args.industry) or ["待标注"],
                        "product": normalize_list(args.product) or ["待标注"],
                        "tags": normalize_list(args.tag) or ["ppt-upload", "needs-review"],
                    },
                    pages=args.page,
                )
            )

    dossier = {
        "version": "1.0",
        "task_id": task_id,
        "brief": args.brief,
        "source_library": {
            "root": repo_rel(library_dir),
            "items": prepared_sources,
        },
        "source_inventory": inventory,
        **layers,
        "ppt_library_uploads": ppt_uploads,
        "handoff": {
            "deck_designer": {
                "target_skill": "deck-designer",
                "payload_schema": "skills/feishu-deck-h5/schema/source-dossier.schema.json",
                "consumes": ["knowledge_layer", "confidence.needs_confirmation", "source_inventory"],
                "ready": True,
                "source_roles": html_roles,
                "notes": ["Use knowledge_layer as sourced facts; keep confidence gaps as open questions."],
            },
            "deck_renderer": {
                "target_skill": "deck-renderer",
                "payload_schema": "skills/feishu-deck-h5/deck-json/deck-schema.json",
                "consumes": ["material_layer", "slide_layer", "source_library"],
                "ready": True,
                "source_roles": html_roles,
                "notes": ["Use material_layer and slide_layer only after designer has produced a confirmed outline."],
            },
            "publisher": {
                "target_skill": "publisher",
                "payload_schema": "skills/feishu-deck-h5/schema/source-dossier.schema.json",
                "consumes": ["knowledge_layer", "material_layer", "slide_layer", "provenance"],
                "ready": False,
                "source_roles": html_roles,
                "notes": ["Ingest only after deck-validator passes or the user marks records as knowledge-only candidates."],
            },
        },
        "validation": {
            "schema": "skills/feishu-deck-h5/schema/source-dossier.schema.json",
            "validated": False,
        },
    }
    if any(src.get("source_role") == "target-html" for src in inventory):
        dossier["handoff"]["deck_editor"] = {
            "target_skill": "deck-editor",
            "payload_schema": "skills/feishu-deck-h5/schema/source-dossier.schema.json",
            "consumes": ["source_inventory", "slide_layer", "material_layer", "source_library"],
            "ready": True,
            "notes": [
                "Treat uploaded HTML as the current target state, not source inspiration.",
                "Bootstrap imported_existing_state artifacts before edits, then prefer deck.json edits and rerender.",
            ],
        }
        dossier["handoff"]["deck_designer"]["ready"] = False
        dossier["handoff"]["deck_designer"]["notes"].append(
            "HTML role is target-html; designer is only needed if the user explicitly asks to redesign/regenerate."
        )
    materialize_lark_media_previews(dossier, out_dir)
    dossier_path = out_dir / "source-dossier.json"
    write_json(dossier_path, dossier)
    print(json.dumps({"dossier": str(dossier_path), **dossier}, ensure_ascii=False, indent=2))
    missing = [src for src in inventory if not src.get("exists", True)]
    return 0 if args.allow_missing or not missing else 2


if __name__ == "__main__":
    raise SystemExit(main())
