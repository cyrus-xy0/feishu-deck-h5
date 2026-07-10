#!/usr/bin/env python3
"""Fail-closed runtime asset closure validation for library deck packages."""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import html as html_lib
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urlparse


HTML_EXTENSIONS = {".html", ".htm"}
CSS_EXTENSIONS = {".css"}
JAVASCRIPT_EXTENSIONS = {".js", ".mjs", ".cjs"}
TRAVERSABLE_EXTENSIONS = HTML_EXTENSIONS | CSS_EXTENSIONS | JAVASCRIPT_EXTENSIONS
ASSET_EXTENSIONS = TRAVERSABLE_EXTENSIONS | {
    ".aac", ".apng", ".avif", ".gif", ".ico", ".jpg", ".jpeg", ".json",
    ".m4a", ".mov", ".mp3", ".mp4", ".mpeg", ".oga", ".ogg", ".ogv",
    ".otf", ".pdf", ".png", ".svg", ".ttc", ".ttf", ".wav", ".webm",
    ".webp", ".woff", ".woff2", ".xml", ".yaml", ".yml",
}
REMOTE_SCHEMES = {"http", "https", "data", "blob", "mailto", "tel", "javascript"}
LOCAL_SCHEMES = {"file", "vscode", "x-apple-ql-id"}
REFERENCE_ATTRS = {
    "src", "poster", "data-src", "data-original", "data-full", "data-href",
    "xlink:href",
}
ASSET_HREF_TAGS = {"link", "image", "use"}
URL_RE = re.compile(r"url\(\s*(?:\"([^\"]*)\"|'([^']*)'|([^)]*))\s*\)", re.I)
CSS_IMPORT_RE = re.compile(
    r"@import\s+(?:url\(\s*)?(?:['\"]([^'\"]+)['\"]|([^\s;)]+))",
    re.I,
)
SCRIPT_LITERAL_REF_RE = re.compile(
    r"(?P<quote>['\"])(?P<ref>(?:\.\.?/)*(?:assets|input|reuse-src|prototypes|runtime-library|grafts)/[^'\"<>\s]+?\.[A-Za-z0-9]{2,6}(?:[?#][^'\"<>\s]*)?)(?P=quote)",
    re.I,
)
JAVASCRIPT_REFERENCE_RE = re.compile(
    r"(?:\b(?:import|export)\s+(?:[^'\";()]+?\s+from\s+)?|\bimport\s*\(\s*)(['\"])([^'\"\\]+)\1",
    re.I,
)
JAVASCRIPT_NEW_URL_RE = re.compile(
    r"\bnew\s+URL\(\s*(['\"])([^'\"\\]+)\1\s*,\s*import\.meta\.url\s*\)",
    re.I,
)
META_REFRESH_CONTENT_RE = re.compile(r"(?:^|;)\s*url\s*=\s*['\"]?([^'\";]+)", re.I)
JS_LOCATION_RE = re.compile(r"(?:window\.)?location(?:\.href)?\s*=\s*['\"]([^'\"]+)['\"]", re.I)
WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:[/\\]")


@dataclasses.dataclass(frozen=True)
class ClosureIssue:
    code: str
    required_by: str
    reference: str


@dataclasses.dataclass(frozen=True)
class ClosureReport:
    issues: tuple[ClosureIssue, ...]
    reachable_files: tuple[str, ...]
    manifest_files: tuple[str, ...]
    total_bytes: int
    digest_sha256: str

    def to_dict(self) -> dict:
        return {
            "status": "blocked" if self.issues else "verified",
            "issues": [dataclasses.asdict(issue) for issue in self.issues],
            "reachable_files": list(self.reachable_files),
            "manifest_files": list(self.manifest_files),
            "reachable_file_count": len(self.reachable_files),
            "manifest_file_count": len(self.manifest_files),
            "total_bytes": self.total_bytes,
            "digest_sha256": self.digest_sha256,
        }


class _HTMLReferenceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.references: list[str] = []
        self._style_depth = 0
        self._inline_script_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {str(name or "").lower(): str(value or "") for name, value in attrs}
        self._record(tag, values)
        lowered = str(tag or "").lower()
        if lowered == "style":
            self._style_depth += 1
        elif lowered == "script" and not values.get("src"):
            self._inline_script_depth += 1

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._record(tag, {str(name or "").lower(): str(value or "") for name, value in attrs})

    def handle_endtag(self, tag: str) -> None:
        lowered = str(tag or "").lower()
        if lowered == "style" and self._style_depth:
            self._style_depth -= 1
        elif lowered == "script" and self._inline_script_depth:
            self._inline_script_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._style_depth:
            self.references.extend(extract_css_references(data))
        if self._inline_script_depth:
            self.references.extend(extract_literal_asset_references(data))
            self.references.extend(clean_reference(match.group(1)) for match in JS_LOCATION_RE.finditer(data))

    def _record(self, tag: str, values: dict[str, str]) -> None:
        lowered = str(tag or "").lower().split("}")[-1]
        for attr in REFERENCE_ATTRS:
            value = values.get(attr)
            if value:
                self.references.append(clean_reference(value))
        href = values.get("href")
        if href and lowered in ASSET_HREF_TAGS:
            self.references.append(clean_reference(href))
        if lowered == "object" and values.get("data"):
            self.references.append(clean_reference(values["data"]))
        if lowered == "meta" and values.get("http-equiv", "").lower() == "refresh":
            match = META_REFRESH_CONTENT_RE.search(values.get("content", ""))
            if match:
                self.references.append(clean_reference(match.group(1)))
        if values.get("style"):
            self.references.extend(extract_css_references(values["style"]))
        if values.get("srcset"):
            self.references.extend(extract_srcset_references(values["srcset"]))


def clean_reference(value: str) -> str:
    return html_lib.unescape(str(value or "").strip().strip("\"'"))


def extract_srcset_references(text: str) -> tuple[str, ...]:
    return tuple(clean_reference(item.strip().split()[0]) for item in text.split(",") if item.strip())


def extract_css_references(text: str) -> tuple[str, ...]:
    references = [clean_reference(single or double or bare) for single, double, bare in URL_RE.findall(text or "")]
    references.extend(clean_reference(quoted or bare) for quoted, bare in CSS_IMPORT_RE.findall(text or ""))
    return tuple(references)


def extract_literal_asset_references(text: str) -> tuple[str, ...]:
    return tuple(clean_reference(match.group("ref")) for match in SCRIPT_LITERAL_REF_RE.finditer(text or ""))


def extract_javascript_references(text: str) -> tuple[str, ...]:
    references = [clean_reference(match.group(2)) for match in JAVASCRIPT_REFERENCE_RE.finditer(text or "")]
    references.extend(clean_reference(match.group(2)) for match in JAVASCRIPT_NEW_URL_RE.finditer(text or ""))
    references.extend(extract_literal_asset_references(text))
    return tuple(references)


def file_references(path: Path) -> tuple[str, ...]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ()
    suffix = path.suffix.lower()
    if suffix in HTML_EXTENSIONS:
        parser = _HTMLReferenceParser()
        parser.feed(text)
        parser.close()
        return tuple(parser.references)
    if suffix in CSS_EXTENSIONS:
        return extract_css_references(text)
    if suffix in JAVASCRIPT_EXTENSIONS:
        return extract_javascript_references(text)
    return ()


def should_ignore_reference(reference: str) -> bool:
    if not reference or reference.startswith("#") or reference in {"...", "…"}:
        return True
    parsed = urlparse(reference)
    if not parsed.scheme and not parsed.netloc and not parsed.path and (parsed.query or parsed.fragment):
        return True
    if not parsed.scheme and parsed.path.startswith("/media/"):
        return True
    return parsed.scheme.lower() in REMOTE_SCHEMES


def looks_like_asset_reference(reference: str) -> bool:
    parsed = urlparse(reference)
    path_text = unquote(parsed.path or reference)
    if not path_text:
        return False
    path = Path(path_text)
    if path.suffix.lower() in ASSET_EXTENSIONS:
        return True
    first = next((part for part in path.parts if part not in {".", ".."}), "")
    return first in {"assets", "input", "reuse-src", "prototypes", "runtime-library", "grafts"}


def is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def resolve_reference_candidates(reference: str, *, source_dir: Path, package_root: Path) -> tuple[Path, ...]:
    parsed = urlparse(reference)
    path_text = unquote(parsed.path or reference)
    primary = (source_dir / path_text).resolve()
    candidates = [primary]
    path = Path(path_text)
    if "assets" in path.parts:
        parts = list(path.parts)
        assets_index = parts.index("assets")
        asset_tail = Path(*parts[assets_index + 1 :])
        if str(asset_tail):
            candidates.append((package_root / "assets" / asset_tail).resolve())
    if ".." not in path.parts:
        if path.parts[:1] != ("assets",):
            candidates.append((source_dir / "assets" / path).resolve())
            candidates.append((package_root / "assets" / path).resolve())
        candidates.append((package_root / path).resolve())
    return tuple(dict.fromkeys(candidates))


def parse_manifest_paths(path: Path) -> tuple[str, ...]:
    paths: set[str] = set()
    active_section = ""
    in_assets = False
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not line.startswith((" ", "\t")) and stripped.endswith(":"):
            active_section = stripped[:-1].strip()
            in_assets = active_section == "assets"
            continue
        if stripped.startswith("- "):
            value = stripped[2:].strip().strip("'\"")
            if value.startswith("path:"):
                value = value.split(":", 1)[1].strip().strip("'\"")
            if value and (in_assets or active_section in {"shared", "framework", "deck-local", "deck_local"}):
                paths.add(value)
    return tuple(sorted(path for path in paths if path and not should_ignore_reference(path)))


class ClosureScanner:
    def __init__(self, package_root: Path, primary_html: Path, manifest_path: Path) -> None:
        self.package_root = package_root.resolve()
        self.primary_html = primary_html.resolve()
        self.manifest_path = manifest_path.resolve()

    def inspect(self) -> ClosureReport:
        issues: dict[tuple[str, str, str], ClosureIssue] = {}
        reachable: dict[str, Path] = {}
        queue = [self.primary_html]
        visited: set[Path] = set()

        while queue:
            current = queue.pop(0).resolve()
            if current in visited or not current.is_file() or not is_relative_to(current, self.package_root):
                continue
            visited.add(current)
            current_rel = current.relative_to(self.package_root).as_posix()
            reachable[current_rel] = current
            for reference in sorted(set(file_references(current))):
                if should_ignore_reference(reference):
                    continue
                if self._obviously_unsafe(reference):
                    self._add_issue(issues, "LOCAL_REF_ESCAPE", current_rel, reference)
                    continue
                candidates = resolve_reference_candidates(
                    reference,
                    source_dir=current.parent,
                    package_root=self.package_root,
                )
                safe_candidates = [candidate for candidate in candidates if is_relative_to(candidate, self.package_root)]
                if not safe_candidates:
                    self._add_issue(issues, "LOCAL_REF_ESCAPE", current_rel, reference)
                    continue
                resolved = next((candidate for candidate in safe_candidates if candidate.is_file()), None)
                if resolved is None:
                    if looks_like_asset_reference(reference):
                        self._add_issue(issues, "LOCAL_REF_MISSING", current_rel, reference)
                    continue
                resolved_rel = resolved.relative_to(self.package_root).as_posix()
                reachable[resolved_rel] = resolved
                if resolved.stat().st_size == 0:
                    self._add_issue(issues, "LOCAL_ASSET_EMPTY", current_rel, reference)
                    continue
                if resolved.suffix.lower() in TRAVERSABLE_EXTENSIONS:
                    queue.append(resolved)

        manifest_files: dict[str, Path] = {}
        if not self.manifest_path.is_file():
            self._add_issue(issues, "MANIFEST_REF_MISSING", "assets-manifest.yaml", "assets-manifest.yaml")
        else:
            for reference in parse_manifest_paths(self.manifest_path):
                if self._obviously_unsafe(reference):
                    self._add_issue(issues, "MANIFEST_REF_ESCAPE", "assets-manifest.yaml", reference)
                    continue
                candidates = resolve_reference_candidates(
                    reference,
                    source_dir=self.package_root,
                    package_root=self.package_root,
                )
                safe_candidates = [candidate for candidate in candidates if is_relative_to(candidate, self.package_root)]
                resolved = next((candidate for candidate in safe_candidates if candidate.is_file()), None)
                if resolved is None:
                    self._add_issue(issues, "MANIFEST_REF_MISSING", "assets-manifest.yaml", reference)
                    continue
                rel = resolved.relative_to(self.package_root).as_posix()
                manifest_files[rel] = resolved
                if resolved.stat().st_size == 0:
                    self._add_issue(issues, "MANIFEST_ASSET_EMPTY", "assets-manifest.yaml", reference)

        all_files = dict(reachable)
        all_files.update(manifest_files)
        digest = hashlib.sha256()
        total_bytes = 0
        for relative, path in sorted(all_files.items()):
            size = path.stat().st_size
            total_bytes += size
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            digest.update(str(size).encode("ascii"))
            digest.update(b"\0")
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)

        return ClosureReport(
            issues=tuple(issues[key] for key in sorted(issues)),
            reachable_files=tuple(sorted(reachable)),
            manifest_files=tuple(sorted(manifest_files)),
            total_bytes=total_bytes,
            digest_sha256=digest.hexdigest(),
        )

    @staticmethod
    def _add_issue(
        issues: dict[tuple[str, str, str], ClosureIssue],
        code: str,
        required_by: str,
        reference: str,
    ) -> None:
        issue = ClosureIssue(code=code, required_by=required_by, reference=reference)
        issues[(code, required_by, reference)] = issue

    @staticmethod
    def _obviously_unsafe(reference: str) -> bool:
        parsed = urlparse(reference)
        return bool(
            "\\" in reference
            or WINDOWS_DRIVE_RE.match(reference)
            or parsed.scheme.lower() in LOCAL_SCHEMES
            or (parsed.scheme and parsed.scheme.lower() not in REMOTE_SCHEMES)
            or unquote(parsed.path or reference).startswith("/")
        )


def inspect_package(package_root: Path, primary_html: Path, manifest_path: Path) -> ClosureReport:
    return ClosureScanner(package_root, primary_html, manifest_path).inspect()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package_root", type=Path)
    parser.add_argument("--primary-html", default="index.html")
    parser.add_argument("--manifest", default="assets-manifest.yaml")
    parser.add_argument("--report", type=Path)
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    package_root = args.package_root.resolve()
    primary_html = (package_root / args.primary_html).resolve()
    manifest_path = (package_root / args.manifest).resolve()
    if not package_root.is_dir():
        print(f"ERROR: package root not found: {package_root}", file=sys.stderr)
        return 2
    if not primary_html.is_file() or not is_relative_to(primary_html, package_root):
        print(f"ERROR: primary HTML not found or unsafe: {args.primary_html}", file=sys.stderr)
        return 2
    report = inspect_package(package_root, primary_html, manifest_path)
    payload = report.to_dict()
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if report.issues:
        print(f"ERROR: runtime asset closure blocked by {len(report.issues)} issue(s)", file=sys.stderr)
        for issue in report.issues:
            print(f"{issue.code} {issue.required_by} -> {issue.reference}", file=sys.stderr)
        return 1
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
