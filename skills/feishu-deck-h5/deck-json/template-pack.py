#!/usr/bin/env python3
"""Runtime primitives for approved PPT-derived Template Packs.

This module deliberately does *not* add another DeckJSON layout enum.  It maps
the layouts already authored in DeckJSON onto six semantic template roles:

    cover, raw, section, quote, agenda, end

Legacy body layouts (content/stats/flow/...) map to ``raw``.  Mechanism layouts
(``canvas``, ``replica`` and ``iframe-embed``) do not select a visual template.

The module is stdlib-only and import-safe.  ``render-deck.py`` can load it by
path (the filename contains a hyphen) and consume ``build_slide_binding``'s
plain-dict packet without depending on the dataclasses below.

Canonical pack shape (the validator is intentionally a little tolerant while
the extractor evolves)::

    {
      "schema_version": "1.0",
      "template_id": "acme-2026",
      "version": "1.0.0",
      "status": "approved",
      "canvas": {...},
      "layouts": {
        "cover-main": {
          "semantic_role": "cover",
          "fixed_elements": [...],
          "slots": [...],
          "safe_area": {...}
        }
      },
      "layout_coverage": {
        "cover":  {"status": "native", "layout_id": "cover-main"},
        "raw":    {"status": "native", "layout_id": "body-main"},
        "section":{"status": "derived", "layout_id": "section-derived"},
        "quote":  {"status": "unsupported"},
        "agenda": {"status": "alias", "alias_to": "raw"},
        "end":    {"status": "alias", "alias_to": "cover"}
      },
      "policies": {"mode": "strict"}
    }

Missing template roles are legal for a pack.  A strict *deck binding* reports
missing/unsupported roles only when the deck actually needs them.  Call
``validate_template_pack(..., strict=True)`` to audit all six roles up front.
"""

import argparse
import copy
import json
import os
import re
import sys
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import unquote


SEMANTIC_ROLES: tuple[str, ...] = (
    "cover", "raw", "section", "quote", "agenda", "end",
)

ROLE_BY_AUTHORED_LAYOUT: dict[str, str] = {
    "cover": "cover",
    "raw": "raw",
    "section": "section",
    "quote": "quote",
    "agenda": "agenda",
    "end": "end",
}

# F-305 body layouts remain renderable for old decks.  A Template Pack treats
# them as content recipes inside the single semantic `raw` shell.
LEGACY_BODY_LAYOUTS: frozenset[str] = frozenset({
    "content", "stats", "flow", "image-text", "table", "logo-wall",
    "arch-stack", "chart",
})

# These are transport/render mechanisms rather than visual template roles.
MECHANISM_LAYOUTS: frozenset[str] = frozenset({
    "canvas", "replica", "iframe-embed",
})

COVERAGE_STATUSES: frozenset[str] = frozenset({
    "native", "derived", "alias", "unsupported",
})
PACK_STATUSES: frozenset[str] = frozenset({"draft", "approved", "retired"})

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_WINDOWS_ABS_RE = re.compile(r"^[A-Za-z]:[\\/]")
_CSS_URL_RE = re.compile(
    r"url\(\s*(?P<q>['\"]?)(?P<url>.*?)(?P=q)\s*\)", re.I | re.S,
)
_MAX_PACK_BYTES = 8 * 1024 * 1024
_MAX_TEXT_ASSET_BYTES = 2 * 1024 * 1024


class TemplatePackError(ValueError):
    """Base error raised by Template Pack runtime primitives."""


class TemplatePackValidationError(TemplatePackError):
    """The pack violates its structural or requested strict contract."""

    def __init__(self, issues: Sequence["PackIssue"]):
        self.issues = tuple(issues)
        summary = "; ".join(f"{i.code} {i.path}: {i.message}" for i in issues)
        super().__init__(summary or "template pack validation failed")


class TemplatePackStateError(TemplatePackError):
    """A draft pack was requested for a final render without opt-in."""


class TemplateCoverageError(TemplatePackError):
    """A required semantic role is missing or unsupported."""


class UnsafeTemplateAssetError(TemplatePackError):
    """A pack asset reference escapes the pack or uses a remote/active URI."""


@dataclass(frozen=True)
class PackIssue:
    level: str
    code: str
    path: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {
            "level": self.level,
            "code": self.code,
            "path": self.path,
            "message": self.message,
        }


@dataclass(frozen=True)
class CoverageResolution:
    requested_role: str
    declared_status: str
    effective_status: str
    resolved_role: str | None
    layout_id: str | None
    alias_chain: tuple[str, ...]
    derived_from: str | None = None

    @property
    def available(self) -> bool:
        return self.effective_status in {"native", "derived"} and bool(self.layout_id)

    def as_dict(self) -> dict[str, Any]:
        return {
            "requested_role": self.requested_role,
            "declared_status": self.declared_status,
            "effective_status": self.effective_status,
            "resolved_role": self.resolved_role,
            "layout_id": self.layout_id,
            "alias_chain": list(self.alias_chain),
            "derived_from": self.derived_from,
            "available": self.available,
        }


@dataclass(frozen=True)
class TemplatePack:
    """Validated Template Pack plus the containment root for local assets."""

    raw: dict[str, Any]
    base_dir: Path
    source_path: Path | None = None

    @property
    def template_id(self) -> str:
        return str(self.raw.get("template_id", ""))

    @property
    def version(self) -> str:
        return str(self.raw.get("version", ""))

    @property
    def schema_version(self) -> str:
        return str(self.raw.get("schema_version", ""))

    @property
    def status(self) -> str:
        return str(self.raw.get("status", "")).lower()

    @property
    def strict_mode(self) -> bool:
        return _pack_strict_mode(self.raw)

    @property
    def layouts(self) -> dict[str, dict[str, Any]]:
        return _normalise_layouts(self.raw.get("layouts", {}))[0]

    @property
    def coverage(self) -> dict[str, Any]:
        value = self.raw.get("layout_coverage", self.raw.get("coverage", {}))
        return dict(value) if isinstance(value, Mapping) else {}


def semantic_role_for_layout(layout: str, *, unknown: str = "error") -> str | None:
    """Map an authored DeckJSON layout to its Template Pack semantic role.

    ``unknown`` may be ``"error"`` (default) or ``"none"``.  Mechanism layouts
    always return ``None`` because they intentionally bypass visual layouts.
    """

    name = str(layout or "").strip().lower()
    if name in ROLE_BY_AUTHORED_LAYOUT:
        return ROLE_BY_AUTHORED_LAYOUT[name]
    if name in LEGACY_BODY_LAYOUTS:
        return "raw"
    if name in MECHANISM_LAYOUTS:
        return None
    if unknown == "none":
        return None
    raise TemplateCoverageError(f"unknown authored DeckJSON layout: {layout!r}")


def _pack_strict_mode(raw: Mapping[str, Any]) -> bool:
    policies = raw.get("policies", {})
    if isinstance(policies, Mapping):
        if isinstance(policies.get("strict"), bool):
            return bool(policies["strict"])
        for key in ("mode", "template_mode", "fit_mode"):
            value = policies.get(key)
            if isinstance(value, str):
                return value.lower() == "strict"
    value = raw.get("mode")
    if isinstance(value, str):
        return value.lower() == "strict"
    # The approved design contract defaults to no silent substitution.
    return True


def _normalise_layouts(value: Any) -> tuple[dict[str, dict[str, Any]], list[PackIssue]]:
    issues: list[PackIssue] = []
    if isinstance(value, Mapping):
        out: dict[str, dict[str, Any]] = {}
        for layout_id, item in value.items():
            if not isinstance(item, Mapping):
                issues.append(PackIssue(
                    "error", "TP-LAYOUT-TYPE", f"layouts.{layout_id}",
                    "layout definition must be an object",
                ))
                continue
            data = dict(item)
            data.setdefault("layout_id", str(layout_id))
            out[str(layout_id)] = data
        return out, issues

    if isinstance(value, list):
        out = {}
        for index, item in enumerate(value):
            path = f"layouts.{index}"
            if not isinstance(item, Mapping):
                issues.append(PackIssue(
                    "error", "TP-LAYOUT-TYPE", path,
                    "layout definition must be an object",
                ))
                continue
            layout_id = item.get("layout_id", item.get("id"))
            if not isinstance(layout_id, str) or not layout_id:
                issues.append(PackIssue(
                    "error", "TP-LAYOUT-ID", path,
                    "layout array item requires layout_id",
                ))
                continue
            if layout_id in out:
                issues.append(PackIssue(
                    "error", "TP-LAYOUT-DUPLICATE", path,
                    f"duplicate layout_id {layout_id!r}",
                ))
                continue
            out[layout_id] = dict(item)
        return out, issues

    return {}, [PackIssue(
        "error", "TP-LAYOUTS-TYPE", "layouts", "layouts must be an object or array",
    )]


def _normalise_coverage_entry(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        text = value.strip().lower()
        if text.startswith("alias:"):
            return {"status": "alias", "alias_to": text.split(":", 1)[1].strip()}
        return {"status": text}
    if isinstance(value, Mapping):
        entry = dict(value)
        status = entry.get("status")
        if status is None and entry.get("layout_id"):
            status = "native"
        if isinstance(status, str):
            entry["status"] = status.lower()
        if "alias_to" not in entry:
            for key in ("alias", "alias_of", "target"):
                if key in entry:
                    entry["alias_to"] = entry[key]
                    break
        return entry
    return {"status": "invalid", "_raw": value}


def _coverage_map(raw: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    value = raw.get("layout_coverage", raw.get("coverage", {}))
    if not isinstance(value, Mapping):
        return {}
    return {str(role): _normalise_coverage_entry(entry) for role, entry in value.items()}


def _fully_unquote(value: str) -> str:
    current = value
    for _ in range(4):
        decoded = unquote(current)
        if decoded == current:
            break
        current = decoded
    return current


def normalize_asset_ref(ref: str) -> str:
    """Return a canonical pack-relative asset ref or raise.

    Remote URLs, active/data URIs, absolute paths, traversal (including percent
    encoded traversal), Windows paths, query strings and fragments are rejected.
    """

    if not isinstance(ref, str) or not ref.strip():
        raise UnsafeTemplateAssetError("asset reference must be a non-empty string")
    raw = ref.strip()
    decoded = _fully_unquote(raw)
    if "\x00" in decoded:
        raise UnsafeTemplateAssetError(f"NUL byte in template asset reference: {ref!r}")
    if decoded.startswith(("/", "//", "~")) or _WINDOWS_ABS_RE.match(decoded):
        raise UnsafeTemplateAssetError(f"absolute template asset path is not allowed: {ref!r}")
    if _SCHEME_RE.match(decoded):
        raise UnsafeTemplateAssetError(f"URI schemes are not allowed in template assets: {ref!r}")
    if "\\" in decoded:
        raise UnsafeTemplateAssetError(f"backslashes are not allowed in template assets: {ref!r}")
    if "?" in decoded or "#" in decoded:
        raise UnsafeTemplateAssetError(
            f"query strings and fragments are not allowed in template assets: {ref!r}")
    path = PurePosixPath(decoded)
    if any(part in {"", ".", ".."} for part in path.parts):
        # PurePosixPath removes a leading './'; reject traversal explicitly and
        # canonicalise benign './' below rather than relying on that collapse.
        if ".." in decoded.split("/"):
            raise UnsafeTemplateAssetError(f"asset path traversal is not allowed: {ref!r}")
    parts = [part for part in decoded.split("/") if part not in {"", "."}]
    if not parts or any(part == ".." for part in parts):
        raise UnsafeTemplateAssetError(f"invalid template asset path: {ref!r}")
    return "/".join(parts)


def resolve_pack_asset(
    pack: TemplatePack,
    ref: str,
    *,
    must_exist: bool = False,
) -> Path:
    """Resolve a safe local asset and prove it remains inside pack.base_dir."""

    normal = normalize_asset_ref(ref)
    root = pack.base_dir.resolve()
    candidate = (root / normal).resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise UnsafeTemplateAssetError(
            f"template asset escapes pack root: {ref!r}",
        ) from exc
    if must_exist:
        if not candidate.exists():
            raise UnsafeTemplateAssetError(f"template asset does not exist: {ref!r}")
        if not candidate.is_file():
            raise UnsafeTemplateAssetError(f"template asset is not a file: {ref!r}")
    return candidate


class _MarkupAssetParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.refs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del tag
        for key, value in attrs:
            if not value:
                continue
            lower = key.lower()
            if lower in {"src", "href", "poster"}:
                if value.startswith("#"):
                    continue
                self.refs.append(value)
            elif lower == "srcset":
                for candidate in value.split(","):
                    ref = candidate.strip().split(None, 1)[0]
                    if ref:
                        self.refs.append(ref)
            elif lower == "style":
                self.refs.extend(_css_asset_refs(value))


def _css_asset_refs(css: str) -> list[str]:
    refs = []
    for match in _CSS_URL_RE.finditer(str(css or "")):
        ref = match.group("url").strip()
        if ref and not ref.startswith("#"):
            refs.append(ref)
    return refs


def _markup_asset_refs(markup: str) -> list[str]:
    parser = _MarkupAssetParser()
    parser.feed(str(markup or ""))
    parser.close()
    return parser.refs


_ASSET_KEYS = frozenset({
    "src", "href", "path", "asset", "asset_ref", "asset_path", "file",
    "file_path", "image_path", "font_path", "html_path", "css_path",
    "fragment_path", "fixed_layer_path",
})
_ASSET_COLLECTION_KEYS = frozenset({
    "assets", "asset_refs", "images", "image_assets", "font_files",
    "css_paths", "html_paths",
})


def _iter_declared_asset_refs(value: Any, *, parent_key: str = "") -> Iterable[str]:
    """Yield explicit runtime asset refs, skipping provenance `source` trees."""

    if isinstance(value, Mapping):
        for key, child in value.items():
            name = str(key).lower()
            if name in {"source", "extraction_report"}:
                continue
            if name in _ASSET_KEYS and isinstance(child, str):
                yield child
                continue
            if name in _ASSET_COLLECTION_KEYS:
                if isinstance(child, str):
                    yield child
                elif isinstance(child, Mapping):
                    for item in child.values():
                        if isinstance(item, str):
                            yield item
                        else:
                            yield from _iter_declared_asset_refs(item, parent_key=name)
                elif isinstance(child, list):
                    for item in child:
                        if isinstance(item, str):
                            yield item
                        else:
                            yield from _iter_declared_asset_refs(item, parent_key=name)
                continue
            if name in {"html", "markup", "fixed_html"} and isinstance(child, str):
                yield from _markup_asset_refs(child)
            elif name in {"css", "fixed_css"} and isinstance(child, str):
                yield from _css_asset_refs(child)
            else:
                yield from _iter_declared_asset_refs(child, parent_key=name)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_declared_asset_refs(child, parent_key=parent_key)


def _error(code: str, path: str, message: str) -> PackIssue:
    return PackIssue("error", code, path, message)


def _resolve_coverage_raw(
    raw: Mapping[str, Any],
    role: str,
) -> CoverageResolution:
    if role not in SEMANTIC_ROLES:
        raise TemplateCoverageError(f"unknown template role: {role!r}")
    coverage = _coverage_map(raw)
    requested = role
    chain: list[str] = []
    first_status = "missing"
    current = role

    while True:
        if current in chain:
            cycle = " -> ".join([*chain, current])
            raise TemplateCoverageError(f"template layout alias cycle: {cycle}")
        chain.append(current)
        entry = coverage.get(current)
        if entry is None:
            return CoverageResolution(
                requested, first_status, "missing", None, None, tuple(chain),
            )
        status = str(entry.get("status", "invalid")).lower()
        if len(chain) == 1:
            first_status = status
        if status == "alias":
            target = entry.get("alias_to")
            if not isinstance(target, str) or target not in SEMANTIC_ROLES:
                return CoverageResolution(
                    requested, first_status, "invalid", None, None, tuple(chain),
                )
            current = target
            continue
        if status == "unsupported":
            return CoverageResolution(
                requested, first_status, "unsupported", current, None, tuple(chain),
            )
        if status not in {"native", "derived"}:
            return CoverageResolution(
                requested, first_status, "invalid", current, None, tuple(chain),
            )
        layout_id = entry.get("layout_id")
        derived_from = None
        if status == "derived":
            candidate = entry.get("derived_from", entry.get("source_role"))
            if isinstance(candidate, str) and candidate in SEMANTIC_ROLES:
                derived_from = candidate
        return CoverageResolution(
            requested, first_status, status, current,
            str(layout_id) if isinstance(layout_id, str) and layout_id else None,
            tuple(chain), derived_from,
        )


def resolve_coverage(
    pack: TemplatePack | Mapping[str, Any],
    role: str,
    *,
    strict: bool = False,
) -> CoverageResolution:
    """Resolve native/derived/alias/unsupported coverage for one role."""

    raw = pack.raw if isinstance(pack, TemplatePack) else pack
    result = _resolve_coverage_raw(raw, role)
    if strict and not result.available:
        raise TemplateCoverageError(
            f"template role {role!r} is {result.effective_status}; "
            "strict mode forbids silent layout substitution",
        )
    return result


def coverage_report(
    pack: TemplatePack | Mapping[str, Any],
    roles: Iterable[str] = SEMANTIC_ROLES,
) -> dict[str, dict[str, Any]]:
    """Return a serialisable coverage report; cycles are reported, not hidden."""

    report: dict[str, dict[str, Any]] = {}
    for role in roles:
        try:
            report[role] = resolve_coverage(pack, role).as_dict()
        except TemplateCoverageError as exc:
            report[role] = {
                "requested_role": role,
                "available": False,
                "effective_status": "invalid",
                "error": str(exc),
            }
    return report


def validate_template_pack(
    raw: Mapping[str, Any],
    *,
    base_dir: str | os.PathLike[str] | None = None,
    strict: bool = False,
    required_roles: Iterable[str] | None = None,
    verify_assets: bool = False,
) -> list[PackIssue]:
    """Validate a pack and return issues instead of printing or exiting.

    Structural problems and alias cycles are always errors.  In strict mode,
    missing/unsupported roles are also errors.  If ``required_roles`` is omitted
    strict mode checks all six roles; a deck integration should pass only the
    roles used by that deck.
    """

    issues: list[PackIssue] = []
    if not isinstance(raw, Mapping):
        return [_error("TP-ROOT-TYPE", "$", "template pack must be an object")]

    for key in ("schema_version", "template_id", "version", "status", "layouts", "layout_coverage"):
        if key not in raw:
            issues.append(_error("TP-REQUIRED", key, "required field is missing"))

    for key in ("schema_version", "template_id", "version"):
        value = raw.get(key)
        if value is not None and (not isinstance(value, str) or not value.strip()):
            issues.append(_error("TP-STRING", key, "must be a non-empty string"))
    if raw.get("schema_version") not in {None, "1.0"}:
        issues.append(_error(
            "TP-SCHEMA-VERSION", "schema_version",
            "unsupported Template Pack schema_version; expected '1.0'",
        ))

    template_id = raw.get("template_id")
    if isinstance(template_id, str) and template_id and not _ID_RE.match(template_id):
        issues.append(_error(
            "TP-ID", "template_id",
            "use letters, digits, dot, underscore or hyphen; start alphanumeric",
        ))

    status = raw.get("status")
    if status is not None and (not isinstance(status, str) or status.lower() not in PACK_STATUSES):
        issues.append(_error(
            "TP-STATUS", "status", "status must be 'draft', 'approved' or 'retired'",
        ))

    canvas = raw.get("canvas")
    canvas_box = None
    if isinstance(canvas, Mapping):
        recommended = canvas.get("recommended_design_canvas")
        canvas_box = recommended if isinstance(recommended, Mapping) else canvas
    if not isinstance(canvas_box, Mapping):
        issues.append(_error(
            "TP-CANVAS", "canvas",
            "canvas must declare width/height or recommended_design_canvas",
        ))
    else:
        for key in ("width", "height"):
            value = canvas_box.get(key)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                issues.append(_error(
                    "TP-CANVAS", f"canvas.{key}",
                    "resolved design canvas dimension must be a positive integer",
                ))

    layouts, layout_issues = _normalise_layouts(raw.get("layouts", {}))
    issues.extend(layout_issues)
    for layout_id, layout in layouts.items():
        path = f"layouts.{layout_id}"
        if not _ID_RE.match(layout_id):
            issues.append(_error("TP-LAYOUT-ID", path, "invalid layout_id"))
        role = layout.get("semantic_role")
        if role is not None and role not in SEMANTIC_ROLES:
            issues.append(_error(
                "TP-LAYOUT-ROLE", f"{path}.semantic_role",
                f"must be one of {', '.join(SEMANTIC_ROLES)}",
            ))
        for collection in ("fixed_elements", "slots"):
            value = layout.get(collection)
            if value is not None and not isinstance(value, list):
                issues.append(_error(
                    "TP-LAYOUT-FIELD", f"{path}.{collection}", "must be an array",
                ))
        safe_area = layout.get("safe_area")
        if safe_area is not None and not isinstance(safe_area, Mapping):
            issues.append(_error(
                "TP-LAYOUT-FIELD", f"{path}.safe_area", "must be an object",
            ))

    coverage_value = raw.get("layout_coverage", raw.get("coverage", {}))
    if not isinstance(coverage_value, Mapping):
        issues.append(_error(
            "TP-COVERAGE-TYPE", "layout_coverage", "must be an object",
        ))
        coverage: dict[str, dict[str, Any]] = {}
    else:
        coverage = _coverage_map(raw)

    for role, entry in coverage.items():
        path = f"layout_coverage.{role}"
        if role not in SEMANTIC_ROLES:
            issues.append(_error(
                "TP-COVERAGE-ROLE", path,
                f"unknown role; use only {', '.join(SEMANTIC_ROLES)}",
            ))
            continue
        status_value = entry.get("status")
        if status_value not in COVERAGE_STATUSES:
            issues.append(_error(
                "TP-COVERAGE-STATUS", f"{path}.status",
                f"must be one of {', '.join(sorted(COVERAGE_STATUSES))}",
            ))
            continue
        confidence = entry.get("confidence")
        if confidence is not None and (
            not isinstance(confidence, (int, float)) or isinstance(confidence, bool)
            or not 0 <= confidence <= 1
        ):
            issues.append(_error(
                "TP-CONFIDENCE", f"{path}.confidence", "must be between 0 and 1",
            ))
        if status_value in {"native", "derived"}:
            layout_id = entry.get("layout_id")
            if not isinstance(layout_id, str) or not layout_id:
                issues.append(_error(
                    "TP-COVERAGE-LAYOUT", f"{path}.layout_id",
                    f"{status_value} coverage requires layout_id",
                ))
            elif layout_id not in layouts:
                issues.append(_error(
                    "TP-COVERAGE-LAYOUT", f"{path}.layout_id",
                    f"unknown layout_id {layout_id!r}",
                ))
            elif status_value == "native":
                semantic_role = layouts[layout_id].get("semantic_role")
                if semantic_role is not None and semantic_role != role:
                    issues.append(_error(
                        "TP-NATIVE-ROLE", f"{path}.layout_id",
                        f"native layout declares semantic_role {semantic_role!r}, not {role!r}",
                    ))
        elif status_value == "alias":
            alias_to = entry.get("alias_to")
            if alias_to not in SEMANTIC_ROLES:
                issues.append(_error(
                    "TP-ALIAS-TARGET", f"{path}.alias_to",
                    f"must be one of {', '.join(SEMANTIC_ROLES)}",
                ))

    # Resolve every declared role so cycles are detected even when the current
    # deck does not happen to use that role.
    cycle_messages: set[str] = set()
    for role in SEMANTIC_ROLES:
        try:
            _resolve_coverage_raw(raw, role)
        except TemplateCoverageError as exc:
            message = str(exc)
            if message not in cycle_messages:
                cycle_messages.add(message)
                issues.append(_error("TP-ALIAS-CYCLE", "layout_coverage", message))

    root = Path(base_dir or ".").expanduser().resolve()
    pack_for_assets = TemplatePack(dict(raw), root)
    for index, ref in enumerate(_iter_declared_asset_refs({
        "brand": raw.get("brand", {}),
        "tokens": raw.get("tokens", {}),
        "layouts": raw.get("layouts", {}),
    })):
        try:
            resolve_pack_asset(pack_for_assets, ref, must_exist=verify_assets)
        except UnsafeTemplateAssetError as exc:
            issues.append(_error(
                "TP-ASSET-PATH", f"assets[{index}]", str(exc),
            ))

    if strict:
        roles = tuple(required_roles) if required_roles is not None else SEMANTIC_ROLES
        for role in dict.fromkeys(roles):
            if role not in SEMANTIC_ROLES:
                issues.append(_error(
                    "TP-STRICT-ROLE", "layout_coverage",
                    f"unknown required role {role!r}",
                ))
                continue
            try:
                resolved = _resolve_coverage_raw(raw, role)
            except TemplateCoverageError:
                continue  # already reported as alias-cycle above
            if not resolved.available:
                issues.append(_error(
                    "TP-STRICT-COVERAGE", f"layout_coverage.{role}",
                    f"required role is {resolved.effective_status}; strict mode "
                    "forbids silent substitution",
                ))

    return issues


def _object_pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise TemplatePackError(f"duplicate JSON key in template pack: {key!r}")
        out[key] = value
    return out


def load_template_pack(
    source: str | os.PathLike[str] | Mapping[str, Any],
    *,
    base_dir: str | os.PathLike[str] | None = None,
    final: bool = False,
    allow_draft: bool = False,
    strict: bool = False,
    required_roles: Iterable[str] | None = None,
    verify_assets: bool = False,
) -> TemplatePack:
    """Load and validate a Template Pack from JSON or an in-memory mapping.

    ``final=True`` enforces the approval gate.  A draft may pass only when the
    caller explicitly sets ``allow_draft=True``; merely using a non-strict pack
    policy does not bypass the final-render state gate.
    """

    source_path: Path | None = None
    if isinstance(source, Mapping):
        raw = copy.deepcopy(dict(source))
        root = Path(base_dir or ".").expanduser().resolve()
    else:
        source_path = Path(source).expanduser().resolve()
        if not source_path.is_file():
            raise TemplatePackError(f"template pack JSON does not exist: {source_path}")
        if source_path.stat().st_size > _MAX_PACK_BYTES:
            raise TemplatePackError(
                f"template pack JSON exceeds {_MAX_PACK_BYTES} bytes: {source_path}",
            )
        try:
            raw = json.loads(
                source_path.read_text(encoding="utf-8"),
                object_pairs_hook=_object_pairs_no_duplicates,
            )
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise TemplatePackError(f"cannot read template pack {source_path}: {exc}") from exc
        if not isinstance(raw, dict):
            raise TemplatePackError("template pack JSON root must be an object")
        root = Path(base_dir).expanduser().resolve() if base_dir else source_path.parent

    issues = validate_template_pack(
        raw,
        base_dir=root,
        strict=strict,
        required_roles=required_roles,
        verify_assets=verify_assets,
    )
    errors = [issue for issue in issues if issue.level == "error"]
    if errors:
        raise TemplatePackValidationError(errors)

    pack = TemplatePack(raw, root, source_path)
    ensure_pack_state(pack, final=final, allow_draft=allow_draft)
    return pack


def ensure_pack_state(
    pack: TemplatePack,
    *,
    final: bool,
    allow_draft: bool = False,
) -> None:
    """Enforce the draft/approved gate at the render boundary."""

    if final and pack.status != "approved" and not allow_draft:
        raise TemplatePackStateError(
            f"template pack {pack.template_id!r}@{pack.version or '?'} is "
            f"{pack.status or 'unapproved'}; final render requires status='approved' "
            "unless allow_draft=True is explicit",
        )
    if final and pack.status == "approved":
        brand = pack.raw.get("brand", {})
        lock_status = brand.get("lock_status") if isinstance(brand, Mapping) else None
        if lock_status == "pending_confirmation":
            raise TemplatePackStateError(
                f"template pack {pack.template_id!r}@{pack.version or '?'} still has "
                "brand.lock_status='pending_confirmation'; confirm and lock VI before final render",
            )
        report = pack.raw.get("extraction_report", {})
        needs = report.get("needs_confirmation") if isinstance(report, Mapping) else None
        if isinstance(needs, list) and needs:
            raise TemplatePackStateError(
                f"template pack {pack.template_id!r}@{pack.version or '?'} still has "
                f"unresolved review items: {', '.join(map(str, needs))}",
            )


def get_layout_override(
    pack: TemplatePack,
    role_or_authored_layout: str,
    *,
    strict: bool | None = None,
) -> dict[str, Any] | None:
    """Return the selected layout definition for a role/authored layout.

    The canonical source is ``layout_coverage[role].layout_id -> layouts``.
    A legacy ``layout_overrides`` object is merged on top when present, keeping
    this runtime usable during migration without changing DeckJSON's enum.
    """

    role = (
        role_or_authored_layout
        if role_or_authored_layout in SEMANTIC_ROLES
        else semantic_role_for_layout(role_or_authored_layout)
    )
    if role is None:
        return None
    use_strict = pack.strict_mode if strict is None else strict
    resolution = resolve_coverage(pack, role, strict=use_strict)
    if not resolution.available or not resolution.layout_id:
        return None
    layout = pack.layouts.get(resolution.layout_id)
    if layout is None:
        if use_strict:
            raise TemplateCoverageError(
                f"layout_id {resolution.layout_id!r} for role {role!r} is missing",
            )
        return None
    result = copy.deepcopy(layout)
    result.setdefault("layout_id", resolution.layout_id)

    legacy = pack.raw.get("layout_overrides", {})
    if isinstance(legacy, Mapping):
        extra = legacy.get(role, legacy.get(resolution.layout_id))
        if isinstance(extra, Mapping):
            result.update(copy.deepcopy(dict(extra)))
    return result


def _read_text_asset(pack: TemplatePack, ref: str, kind: str) -> str:
    path = resolve_pack_asset(pack, ref, must_exist=True)
    if path.stat().st_size > _MAX_TEXT_ASSET_BYTES:
        raise UnsafeTemplateAssetError(
            f"template {kind} asset exceeds {_MAX_TEXT_ASSET_BYTES} bytes: {ref!r}",
        )
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise UnsafeTemplateAssetError(f"cannot read template {kind} asset {ref!r}: {exc}") from exc


def _as_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


def _fixed_layer_packet(pack: TemplatePack, layout: Mapping[str, Any]) -> dict[str, Any]:
    """Materialise explicit fixed-layer markup/CSS and retain structured VI."""

    html_parts: list[str] = []
    css_parts: list[str] = []
    fixed_elements = copy.deepcopy(layout.get("fixed_elements", []))
    if not isinstance(fixed_elements, list):
        fixed_elements = []

    containers: list[Mapping[str, Any]] = [layout]
    fixed_layer = layout.get("fixed_layer")
    if isinstance(fixed_layer, Mapping):
        containers.append(fixed_layer)
    containers.extend(item for item in fixed_elements if isinstance(item, Mapping))

    asset_refs: list[str] = []
    for container in containers:
        for key in ("fixed_html", "html", "markup"):
            value = container.get(key)
            if isinstance(value, str) and value:
                for ref in _markup_asset_refs(value):
                    normal = normalize_asset_ref(ref)
                    resolve_pack_asset(pack, normal)
                    asset_refs.append(normal)
                html_parts.append(value)
        for key in ("html_path", "fragment_path", "fixed_layer_path"):
            for ref in _as_string_list(container.get(key)):
                text = _read_text_asset(pack, ref, "HTML")
                for nested in _markup_asset_refs(text):
                    normal = normalize_asset_ref(nested)
                    resolve_pack_asset(pack, normal)
                    asset_refs.append(normal)
                html_parts.append(text)
                asset_refs.append(normalize_asset_ref(ref))
        for key in ("fixed_css", "css"):
            value = container.get(key)
            if isinstance(value, str) and value:
                for ref in _css_asset_refs(value):
                    normal = normalize_asset_ref(ref)
                    resolve_pack_asset(pack, normal)
                    asset_refs.append(normal)
                css_parts.append(value)
        for key in ("css_path", "css_paths"):
            for ref in _as_string_list(container.get(key)):
                text = _read_text_asset(pack, ref, "CSS")
                for nested in _css_asset_refs(text):
                    normal = normalize_asset_ref(nested)
                    resolve_pack_asset(pack, normal)
                    asset_refs.append(normal)
                css_parts.append(text)
                asset_refs.append(normalize_asset_ref(ref))

    for ref in _iter_declared_asset_refs({"fixed_elements": fixed_elements}):
        normal = normalize_asset_ref(ref)
        resolve_pack_asset(pack, normal)
        asset_refs.append(normal)

    unique_refs = list(dict.fromkeys(asset_refs))
    return {
        "html": "\n".join(part for part in html_parts if part),
        "css": "\n".join(part for part in css_parts if part),
        "fixed_elements": fixed_elements,
        "asset_refs": unique_refs,
        "asset_files": [str(resolve_pack_asset(pack, ref)) for ref in unique_refs],
    }


def build_slide_binding(
    pack: TemplatePack,
    slide: Mapping[str, Any],
    *,
    final: bool = False,
    allow_draft: bool = False,
    strict: bool | None = None,
) -> dict[str, Any]:
    """Return a renderer-ready, serialisable binding packet for one slide.

    The packet intentionally contains both structured ``fixed_elements`` and
    materialised ``fixed_html``/``fixed_css``.  A renderer can support precise
    extracted primitives immediately, while still accepting frozen HTML/CSS
    fixed layers from a later extractor.
    """

    ensure_pack_state(pack, final=final, allow_draft=allow_draft)
    authored_layout = str(slide.get("layout", ""))
    role = semantic_role_for_layout(authored_layout)
    base = {
        "active": False,
        "template_id": pack.template_id,
        "template_version": pack.version,
        "template_status": pack.status,
        "schema_version": pack.schema_version,
        "slide_key": str(slide.get("key", "")),
        "authored_layout": authored_layout,
        "role": role,
    }
    if role is None:
        base["reason"] = "mechanism-layout"
        return base

    use_strict = pack.strict_mode if strict is None else strict
    resolution = resolve_coverage(pack, role, strict=use_strict)
    base["coverage"] = resolution.as_dict()
    if not resolution.available:
        base["reason"] = f"coverage-{resolution.effective_status}"
        return base

    layout = get_layout_override(pack, role, strict=use_strict)
    if layout is None:
        base["reason"] = "layout-missing"
        return base
    explicit_layout_id = slide.get("template_layout_id")
    if explicit_layout_id is not None:
        if not isinstance(explicit_layout_id, str) or not explicit_layout_id:
            raise TemplateCoverageError(
                f"slide {base['slide_key']!r} has invalid template_layout_id",
            )
        explicit_layout = pack.layouts.get(explicit_layout_id)
        if explicit_layout is None:
            raise TemplateCoverageError(
                f"slide {base['slide_key']!r} selects unknown template layout "
                f"{explicit_layout_id!r}",
            )
        explicit_role = explicit_layout.get("semantic_role")
        allowed_roles = {role, resolution.resolved_role}
        if explicit_role is not None and explicit_role not in allowed_roles:
            raise TemplateCoverageError(
                f"slide {base['slide_key']!r} role {role!r} cannot use template "
                f"layout {explicit_layout_id!r} declared for {explicit_role!r}",
            )
        layout = copy.deepcopy(explicit_layout)
        layout.setdefault("layout_id", explicit_layout_id)
    fixed = _fixed_layer_packet(pack, layout)
    layout_id = str(layout.get("layout_id", resolution.layout_id or ""))
    base.update({
        "active": True,
        "layout_id": layout_id,
        "resolved_role": resolution.resolved_role,
        "semantic_role": layout.get("semantic_role", resolution.resolved_role),
        "safe_area": copy.deepcopy(layout.get("safe_area")),
        "slots": copy.deepcopy(layout.get("slots", [])),
        "fixed_elements": fixed["fixed_elements"],
        "fixed_html": fixed["html"],
        "fixed_css": fixed["css"],
        "asset_refs": fixed["asset_refs"],
        "asset_files": fixed["asset_files"],
        "data_attrs": {
            "data-template-id": pack.template_id,
            "data-template-version": pack.version,
            "data-template-role": role,
            "data-template-layout-id": layout_id,
            "data-template-coverage": resolution.declared_status,
        },
    })
    return base


def build_deck_bindings(
    pack: TemplatePack,
    slides: Sequence[Mapping[str, Any]],
    *,
    final: bool = False,
    allow_draft: bool = False,
    strict: bool | None = None,
) -> list[dict[str, Any]]:
    """Bind a deck, aggregating strict coverage errors before rendering."""

    ensure_pack_state(pack, final=final, allow_draft=allow_draft)
    use_strict = pack.strict_mode if strict is None else strict
    needed: list[str] = []
    for slide in slides:
        role = semantic_role_for_layout(str(slide.get("layout", "")))
        if role is not None and role not in needed:
            needed.append(role)
    if use_strict:
        issues = validate_template_pack(
            pack.raw,
            base_dir=pack.base_dir,
            strict=True,
            required_roles=needed,
        )
        coverage_errors = [
            issue for issue in issues
            if issue.level == "error" and issue.code.startswith("TP-STRICT-")
        ]
        if coverage_errors:
            raise TemplatePackValidationError(coverage_errors)
    return [
        build_slide_binding(
            pack, slide, final=final, allow_draft=allow_draft, strict=use_strict,
        )
        for slide in slides
    ]


__all__ = [
    "SEMANTIC_ROLES",
    "ROLE_BY_AUTHORED_LAYOUT",
    "LEGACY_BODY_LAYOUTS",
    "MECHANISM_LAYOUTS",
    "TemplatePack",
    "PackIssue",
    "CoverageResolution",
    "TemplatePackError",
    "TemplatePackValidationError",
    "TemplatePackStateError",
    "TemplateCoverageError",
    "UnsafeTemplateAssetError",
    "semantic_role_for_layout",
    "normalize_asset_ref",
    "resolve_pack_asset",
    "validate_template_pack",
    "load_template_pack",
    "ensure_pack_state",
    "resolve_coverage",
    "coverage_report",
    "get_layout_override",
    "build_slide_binding",
    "build_deck_bindings",
]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="template-pack.py",
        description="Validate a local feishu-deck-h5 Template Pack runtime contract.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate")
    validate.add_argument("pack", type=Path)
    validate.add_argument("--verify-assets", action="store_true")
    validate.add_argument("--final", action="store_true")
    validate.add_argument(
        "--required-role",
        action="append",
        choices=SEMANTIC_ROLES,
        default=[],
        help="role required by the consuming deck; repeat as needed",
    )
    args = parser.parse_args(argv)
    try:
        pack = load_template_pack(
            args.pack,
            final=bool(args.final),
            strict=bool(args.required_role),
            required_roles=args.required_role or None,
            verify_assets=bool(args.verify_assets),
        )
    except TemplatePackError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps({
        "ok": True,
        "template_id": pack.template_id,
        "version": pack.version,
        "status": pack.status,
        "coverage": coverage_report(pack),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
