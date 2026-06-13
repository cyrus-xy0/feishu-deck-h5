#!/usr/bin/env python3
"""validate-deck.py — DeckJSON schema validator (stdlib only).

Implements the subset of JSON Schema Draft 2020-12 used by deck-schema.json:
type / required / properties / additionalProperties / enum / const / pattern /
minLength / minItems / maxItems / uniqueItems / items / oneOf / allOf /
if-then / $ref (local) / minimum / maximum / $defs.

On top of pure JSON Schema, applies a few cross-field business rules that
the schema alone can't express:

  - slide.key uniqueness across the deck
  - table.rows[*].length == headers.length
  - agenda.items has at most one `active: true`
  - one-pager-case fit-check (placeholder / short-beat / duplicate-beat)
  - language warnings (R-LANG-ish): zh-only deck shouldn't carry title_en
    in non-agenda layouts

Usage:
  python3 validate-deck.py <deck.json> [--schema <path>] [--strict] [--no-business-rules]

Exit codes:
  0 = valid
  1 = invalid (schema or business-rule errors)
  2 = file or schema load error
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_SCHEMA = HERE / "deck-schema.json"

# PLACEHOLDER_PATTERNS single-sourced in _story_case_fit.py (F-15) — shared
# with render-deck.py so the two fit-checks can't drift apart.
sys.path.insert(0, str(HERE))
from _story_case_fit import PLACEHOLDER_PATTERNS  # noqa: E402


# ---------------------------------------------------------------------------
# Result accumulator
# ---------------------------------------------------------------------------

class Result:
    def __init__(self):
        self.errors: list[tuple[str, str]] = []   # (instance_path, message)
        self.warnings: list[tuple[str, str]] = [] # (instance_path, message)
        # Soft (advisory) warnings are SURFACED but NEVER promoted to errors by
        # --strict and never affect `ok`. They're for heuristic, design-relative
        # findings (e.g. R-FAMILY-DRIFT consensus drift) that must not break a
        # render — render-deck calls validate-deck --strict and aborts on a hard
        # error, so a hard family-drift rule would false-fail legitimate per-page
        # design variation. See check_family_drift.
        self.soft_warnings: list[tuple[str, str]] = []

    def err(self, path: str, msg: str):
        self.errors.append((path, msg))

    def warn(self, path: str, msg: str):
        self.warnings.append((path, msg))

    def warn_soft(self, path: str, msg: str):
        self.soft_warnings.append((path, msg))

    @property
    def ok(self) -> bool:
        return not self.errors


# ---------------------------------------------------------------------------
# JSON Schema validator (Draft 2020-12 subset)
# ---------------------------------------------------------------------------

JSON_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "integer": int,
    "boolean": bool,
    "number": (int, float),
    "null": type(None),
}


class SchemaValidator:
    def __init__(self, schema: dict):
        self.schema = schema
        self.defs = schema.get("$defs", {})

    def validate(self, instance, result: Result) -> None:
        self._check(instance, self.schema, result, path="$")

    def _resolve_ref(self, ref: str) -> dict:
        if not ref.startswith("#/$defs/"):
            raise ValueError(f"unsupported $ref: {ref!r} (only local #/$defs/ refs supported)")
        name = ref[len("#/$defs/"):]
        if name not in self.defs:
            raise ValueError(f"unknown $defs entry: {name}")
        return self.defs[name]

    def _check(self, instance, schema: dict, result: Result, path: str) -> None:
        if not isinstance(schema, dict):
            return  # nothing to check
        if "$ref" in schema:
            schema = self._resolve_ref(schema["$ref"])

        # type
        if "type" in schema:
            expected = schema["type"]
            types = expected if isinstance(expected, list) else [expected]
            py_types = tuple(JSON_TYPES[t] for t in types)
            # int is a subtype of bool in Python — reject True/False when "integer" required
            if isinstance(instance, bool) and "integer" in types and "boolean" not in types:
                result.err(path, f"expected integer, got boolean ({instance!r})")
                return
            if not isinstance(instance, py_types):
                result.err(path, f"expected {expected}, got {type(instance).__name__} ({instance!r})")
                return

        # const
        if "const" in schema:
            if instance != schema["const"]:
                result.err(path, f"expected const {schema['const']!r}, got {instance!r}")

        # enum
        if "enum" in schema:
            if instance not in schema["enum"]:
                result.err(path, f"value {instance!r} not in enum {schema['enum']}")

        # string-specific
        if isinstance(instance, str):
            if "minLength" in schema and len(instance) < schema["minLength"]:
                result.err(path, f"length {len(instance)} < minLength {schema['minLength']} (value: {instance!r})")
            if "pattern" in schema:
                # fullmatch (not search): every deck-schema pattern is anchored
                # ^…$, and re.search lets `$` match BEFORE a trailing newline —
                # so e.g. a key "cover\n" wrongly passed. (Verified all patterns
                # are anchored, so fullmatch is equivalent + closes that hole.)
                if not re.fullmatch(schema["pattern"], instance):
                    result.err(path, f"value {instance!r} does not match pattern {schema['pattern']!r}")

        # integer/number
        if isinstance(instance, (int, float)) and not isinstance(instance, bool):
            if "minimum" in schema and instance < schema["minimum"]:
                result.err(path, f"{instance} < minimum {schema['minimum']}")
            if "maximum" in schema and instance > schema["maximum"]:
                result.err(path, f"{instance} > maximum {schema['maximum']}")

        # object-specific
        if isinstance(instance, dict):
            self._check_object(instance, schema, result, path)

        # array-specific
        if isinstance(instance, list):
            self._check_array(instance, schema, result, path)

        # allOf
        for i, sub in enumerate(schema.get("allOf", [])):
            self._check(instance, sub, result, path + f"<allOf[{i}]>")

        # oneOf
        if "oneOf" in schema:
            matched = []
            sub_errors = []
            for i, sub in enumerate(schema["oneOf"]):
                trial = Result()
                self._check(instance, sub, trial, path)
                if trial.ok:
                    matched.append(i)
                else:
                    sub_errors.append((i, trial.errors))
            if len(matched) == 0:
                result.err(path, f"value did not match any of {len(schema['oneOf'])} oneOf branches")
                # surface the *least-failing* branch for diagnostic
                least_bad = min(sub_errors, key=lambda x: len(x[1]))
                for sub_path, sub_msg in least_bad[1][:5]:
                    result.err(sub_path, f"  ↳ (best-match branch [{least_bad[0]}]) {sub_msg}")
            elif len(matched) > 1:
                result.err(path, f"value matched multiple oneOf branches: {matched}")

        # if / then / else
        if "if" in schema:
            trial = Result()
            self._check(instance, schema["if"], trial, path)
            if trial.ok and "then" in schema:
                self._check(instance, schema["then"], result, path)
            elif not trial.ok and "else" in schema:
                self._check(instance, schema["else"], result, path)

    def _check_object(self, instance: dict, schema: dict, result: Result, path: str) -> None:
        for key in schema.get("required", []):
            if key not in instance:
                result.err(path, f"required property {key!r} missing")

        properties = schema.get("properties", {})
        for key, value in instance.items():
            child_path = f"{path}.{key}" if path != "$" else f"$.{key}"
            if key in properties:
                self._check(value, properties[key], result, child_path)

        if schema.get("additionalProperties") is False:
            extra = set(instance) - set(properties)
            for key in extra:
                # if/then schemas add data, so additionalProperties=false is
                # incompatible with the parent's allOf/if-then layering.
                # We only enforce it when this schema *itself* declared
                # properties — if it's a plain {"type": "object"} parent
                # with no properties, skip.
                if properties:
                    result.err(path, f"unknown property {key!r} (additionalProperties: false)")

    def _check_array(self, instance: list, schema: dict, result: Result, path: str) -> None:
        if "minItems" in schema and len(instance) < schema["minItems"]:
            result.err(path, f"length {len(instance)} < minItems {schema['minItems']}")
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            result.err(path, f"length {len(instance)} > maxItems {schema['maxItems']}")
        if schema.get("uniqueItems"):
            seen = []
            for item in instance:
                if item in seen:
                    result.err(path, f"duplicate item {item!r} (uniqueItems: true)")
                seen.append(item)
        if "items" in schema:
            for i, item in enumerate(instance):
                self._check(item, schema["items"], result, f"{path}[{i}]")


# ---------------------------------------------------------------------------
# Cross-field business rules
# ---------------------------------------------------------------------------

def is_variant(slide: dict, layout: str, variant: str) -> bool:
    return slide.get("layout") == layout and slide.get("variant") == variant


def check_business_rules(deck: dict, result: Result, strict: bool) -> None:
    slides = deck.get("slides", [])
    deck_lang = deck.get("deck", {}).get("language", "zh-only")

    # 1. slide.key uniqueness
    seen_keys: dict[str, int] = {}
    for i, slide in enumerate(slides):
        key = slide.get("key")
        if not key:
            continue
        if key in seen_keys:
            result.err(f"$.slides[{i}].key",
                       f"duplicate key {key!r} (also used at slides[{seen_keys[key]}]) (R-KEY)")
        else:
            seen_keys[key] = i

    # 2. Per-(layout, variant) cross-field rules
    for i, slide in enumerate(slides):
        sp = f"$.slides[{i}]"
        layout = slide.get("layout")
        data = slide.get("data") or {}
        if not isinstance(data, dict):
            continue  # a non-dict `data` type is already recorded by schema
                      # validation; don't let the business-rule checks below
                      # crash on it (would mask the real schema errors).
        lang = slide.get("language_override") or deck_lang

        if layout == "table":
            headers = data.get("headers") or []
            for r, row in enumerate(data.get("rows") or []):
                if len(row) != len(headers):
                    result.err(f"{sp}.data.rows[{r}]",
                               f"cell count {len(row)} != headers count {len(headers)}")

        if layout == "agenda":
            actives = [j for j, item in enumerate(data.get("items") or []) if item.get("active")]
            if len(actives) > 1:
                result.err(f"{sp}.data.items",
                           f"agenda has {len(actives)} items marked active; max 1 allowed (recap variant)")

        # R-CANVAS: structured positioned elements — ids unique, geometry
        # numeric, images carry a src. A placeholder page may legitimately
        # have no elements (it renders a '待重做' notice instead).
        if layout == "canvas":
            elements = data.get("elements") or []
            if not data.get("placeholder") and not elements:
                result.err(f"{sp}.data.elements",
                           "canvas slide has no elements and is not a placeholder (R-CANVAS)")
            seen_el_ids: dict[str, int] = {}
            for e, el in enumerate(elements):
                if not isinstance(el, dict):
                    continue
                eid = el.get("id")
                if eid in seen_el_ids:
                    result.err(f"{sp}.data.elements[{e}].id",
                               f"duplicate element id {eid!r} (also at elements[{seen_el_ids[eid]}]) (R-CANVAS)")
                elif eid is not None:
                    seen_el_ids[eid] = e
                for geo in ("x", "y", "w", "h"):
                    if geo in el and not isinstance(el[geo], (int, float)):
                        result.err(f"{sp}.data.elements[{e}].{geo}",
                                   f"geometry {geo!r} must be numeric, got {el[geo]!r} (R-CANVAS)")
                if el.get("type") == "image" and not el.get("src"):
                    result.err(f"{sp}.data.elements[{e}].src",
                               "image element has no src (R-CANVAS)")

        # Only warn when `cols` is EXPLICITLY present and mismatched. `cols` is
        # optional; the renderer DERIVES the column count from the node/step
        # count when omitted. Synthesizing a default 4 and comparing it against
        # the real count (the old code) made any 3/5/6-step flow without an
        # explicit `cols` warn → render runs validate-deck --strict → warning
        # promoted to error → the valid slide was unrenderable.
        if is_variant(slide, "flow", "timeline") and "cols" in data:
            nodes_len = len(data.get("nodes") or [])
            if data["cols"] != nodes_len:
                result.warn(f"{sp}.data.cols",
                            f"cols={data['cols']} doesn't match nodes count {nodes_len}; renderer will use nodes count")

        if is_variant(slide, "flow", "process") and "cols" in data:
            steps_len = len(data.get("steps") or [])
            if data["cols"] != steps_len:
                result.warn(f"{sp}.data.cols",
                            f"cols={data['cols']} doesn't match steps count {steps_len}")

        # 3. content/story-case schema-fit (mirrors render.py ONE_PAGER_FIT_CHECK)
        if is_variant(slide, "content", "story-case"):
            arc = data.get("arc", {})
            fit_fields = {
                "hook.lead":         (data.get("hook", {}).get("lead"), 1),
                "hook.accent":       (data.get("hook", {}).get("accent"), 2),
                "hook.tail":         (data.get("hook", {}).get("tail"), 1),
                "arc.pain":          (arc.get("pain"), 10),
                "arc.conflict":      (arc.get("conflict"), 10),
                "arc.solution":      (arc.get("solution"), 10),
                "arc.value.lead":    (arc.get("value", {}).get("lead"), 1),
                "arc.value.accent":  (arc.get("value", {}).get("accent"), 2),
                "arc.value.tail":    (arc.get("value", {}).get("tail"), 1),
            }
            seen_text: dict[str, str] = {}
            for field, (text, min_len) in fit_fields.items():
                if text is None:
                    continue
                clean = text.strip()
                # placeholder
                for pat in PLACEHOLDER_PATTERNS:
                    if re.search(pat, clean, flags=re.IGNORECASE):
                        result.err(f"{sp}.data.{field}",
                                   f"looks like placeholder ({clean!r}) — story doesn't fit schema, take Path B")
                        break
                else:
                    if len(clean) < min_len:
                        result.err(f"{sp}.data.{field}",
                                   f"only {len(clean)} chars ({clean!r}) — too short to carry this beat")
                    elif clean in seen_text and not field.endswith((".lead", ".tail", ".accent")):
                        result.err(f"{sp}.data.{field}",
                                   f"identical to {seen_text[clean]} — beat probably absent")
                    else:
                        seen_text[clean] = field

        # 4. R-LANG-ish: title_en on content (3up/2col) in zh-only mode warns
        if lang == "zh-only" and is_variant(slide, "content", "3up"):
            for c, card in enumerate(data.get("cards") or []):
                if isinstance(card, dict) and card.get("title_en"):
                    result.warn(f"{sp}.data.cards[{c}].title_en",
                                f"deck.language='zh-only' but title_en provided (R-LANG)")

        # 5. R49: cyan in accent (already enforced by schema enum; here just defense)
        if slide.get("accent") == "cyan":
            result.err(f"{sp}.accent", "cyan is inline-highlight only, not slide accent (R49)")

        # R-DEMO-IFRAME: a slide imported/lifted from an iframe-embed page keeps
        # the `_orig_layout: "iframe-embed"` marker — it WAS an embedded
        # interactive demo. If its html no longer contains an <iframe>, the live
        # demo has been silently rewritten into a static mock, which is exactly
        # the loss the marker exists to guard against. Slide-level
        # `"allow": ["no-iframe"]` accepts the replacement explicitly (same
        # channel as the other slide-scoped opt-outs).
        if slide.get("_orig_layout") == "iframe-embed" \
                and "no-iframe" not in (slide.get("allow") or []):
            html_src = data.get("html")
            html_text = html_src if isinstance(html_src, str) \
                else json.dumps(data, ensure_ascii=False)
            if "<iframe" not in html_text.lower():
                result.err(f"{sp}.data.html",
                           "this page was originally an embedded interactive demo "
                           "(_orig_layout='iframe-embed') but its html no longer "
                           "contains an <iframe> — the live demo has been removed/"
                           "replaced by a static mock. Restore the iframe embed, or "
                           "accept the static replacement explicitly with "
                           "\"allow\": [\"no-iframe\"] (R-DEMO-IFRAME)")

    # 6. Strict mode: promote warnings to errors
    if strict and result.warnings:
        result.errors.extend(result.warnings)
        result.warnings = []


# ---------------------------------------------------------------------------
# R-FAMILY-DRIFT (F-300) — SOFT backstop for the "adopt a foreign page into a
# house-styled deck" gap. A page joining a deck should match the conventions of
# its sibling content pages; the siblings ARE the spec. This surfaces (never
# blocks) raw content pages that diverge on the structural house-chrome trio so
# a reskinned/rebuilt outlier doesn't reach delivery un-noticed even when the
# conform step was skipped. The deterministic fixes live in conform-to-deck.py.
# ---------------------------------------------------------------------------

_FAMILY_DRIFT_MIN_PAGES = 3   # need >= 3 raw content pages to form a consensus


def check_family_drift(deck: dict, result: Result) -> None:
    """Emit SOFT R-FAMILY-DRIFT advisories for content pages diverging from the
    sibling consensus on: D1 own page-background, D2 title placement, D3 pre-title
    chrome. Cheap boolean signals only (no font-snap / luminance pass) so it adds
    negligible cost to the render-time validate. D4 (font ladder) is R20's job;
    D5 (body luminance) needs the composited bg and is left to a visual rule."""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "conform_to_deck",
            Path(__file__).resolve().parent / "conform-to-deck.py")
        conform = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(conform)
    except Exception:
        return  # detector unavailable → skip silently (never block validation)

    slides = deck.get("slides", [])
    if not isinstance(slides, list):
        return
    sigs = [(i,
             conform.sets_own_page_bg(s)[0],
             conform.title_in_header(s),
             conform.has_pretitle_chrome(s)[0])
            for i, s in enumerate(slides)
            if isinstance(s, dict) and conform.is_content_raw(s)]
    if len(sigs) < _FAMILY_DRIFT_MIN_PAGES:
        return  # no family consensus to conform against

    FIX = " — `conform-to-deck.py --apply` fixes this"
    for idx, bg, hdr, chrome in sigs:
        bg_c = conform._bool_consensus([x[1] for x in sigs if x[0] != idx])
        hdr_c = conform._bool_consensus([x[2] for x in sigs if x[0] != idx])
        chrome_c = conform._bool_consensus([x[3] for x in sigs if x[0] != idx])
        sp = f"slides[{idx}]"
        if bg_c is not None and bg != bg_c:
            result.warn_soft(sp, (
                "D1 page-background: page "
                f"{'paints its own background' if bg else 'inherits the master bg'}, "
                f"but the family {'paints its own' if bg_c else 'inherits the master content-bg'} "
                "(R-FAMILY-DRIFT)" + (FIX if bg and not bg_c else "")))
        if hdr_c is not None and hdr != hdr_c:
            result.warn_soft(sp, (
                "D2 title placement: page uses "
                f"{'the framework .header' if hdr else 'a bespoke title block'}, "
                f"but the family uses {'the framework .header > .title-zh' if hdr_c else 'bespoke titles'} "
                "(R-FAMILY-DRIFT)"))
        if chrome_c is not None and chrome != chrome_c:
            result.warn_soft(sp, (
                "D3 pre-title chrome: page "
                f"{'carries an eyebrow/topbar above the title' if chrome else 'has no pre-title chrome'}, "
                f"but the family {'carries one' if chrome_c else 'has none'} "
                "(R-FAMILY-DRIFT)" + (FIX if chrome and not chrome_c else "")))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def format_path(path: str, slide_keys: dict[int, str] | None = None) -> str:
    # Strip the <allOf[N]> annotations to keep output readable.
    path = re.sub(r"<allOf\[\d+\]>", "", path)
    # F-280b · unified error-locator coordinate system. Every other surface
    # (deck-cli list / URL #N / frame_index) is 1-based and carries the slide
    # key; the validator alone reported a bare 0-based `slides[i]`. Keep the
    # JSON-path body 0-based (tools/jq still resolve it) but append a
    # human-readable annotation with the key + 1-based position right after the
    # FIRST `slides[i]` segment so cross-model / self-repair flows can find the
    # page without arithmetic. Done here (the single formatter applied to both
    # schema errors AND business-rule errors) so the two can't drift apart.
    if slide_keys is not None:
        def _annotate(m: re.Match) -> str:
            i = int(m.group(1))
            key = slide_keys.get(i)
            return f"$.slides[{i}] (key={key!r}, 第{i + 1}项)"
        path = re.sub(r"\$\.slides\[(\d+)\]", _annotate, path, count=1)
    return path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="validate-deck.py", description=__doc__.split("\n")[0])
    ap.add_argument("deck", type=Path, help="path to deck.json")
    ap.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA, help="schema file (default: deck-schema.json beside this script)")
    ap.add_argument("--strict", action="store_true", help="promote warnings to errors")
    ap.add_argument("--no-business-rules", action="store_true", help="skip cross-field business rules")
    ap.add_argument("--json", action="store_true",
                    help="emit findings as JSON {ok, errors, warnings, soft_warnings}, "
                         "each item {path, msg, slide, key} (slide = 0-based index parsed "
                         "from the instance path, key = that slide's key). For scoped / "
                         "programmatic gating (F-320: deck-cli's scope-aware pre-write lint).")
    args = ap.parse_args(argv)

    try:
        deck = json.loads(args.deck.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"validate-deck: deck file not found: {args.deck}", file=sys.stderr); return 2
    except json.JSONDecodeError as e:
        print(f"validate-deck: invalid JSON in {args.deck}: {e}", file=sys.stderr); return 2

    try:
        schema = json.loads(args.schema.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"validate-deck: schema not found: {args.schema}", file=sys.stderr); return 2
    except json.JSONDecodeError as e:
        print(f"validate-deck: invalid JSON in {args.schema}: {e}", file=sys.stderr); return 2

    result = Result()
    validator = SchemaValidator(schema)
    try:
        validator.validate(deck, result)
    except Exception as e:
        print(f"validate-deck: validator crashed: {e}", file=sys.stderr); return 2

    if not args.no_business_rules:
        check_business_rules(deck, result, args.strict)
        check_family_drift(deck, result)   # SOFT — never blocks; surfaces drift

    # Render output
    title = deck.get("deck", {}).get("title", "<no title>")
    slides = deck.get("slides", [])
    n_slides = len(slides)
    # F-280b: idx → key map used by format_path to annotate `slides[i]` paths
    # with the human-readable key + 1-based position. Use {} for non-list decks
    # (a malformed top-level `slides`) so .get() stays safe.
    slide_keys = {
        i: (s.get("key") if isinstance(s, dict) else None)
        for i, s in enumerate(slides)
    } if isinstance(slides, list) else {}

    if args.json:
        # F-320 · machine-readable findings for deck-cli's scope-aware pre-write
        # lint. `errors` is the EFFECTIVE blocking set (under --strict the warning
        # promotion at the end of check_business_rules has already extended it);
        # `soft_warnings` are advisory and never block. Each item carries the
        # 0-based slide index parsed from its instance path + that slide's key, so
        # a caller can demote findings on pages its edit did not touch.
        import re as _re

        def _pack(items):
            out = []
            for p, m in items:
                _mi = _re.search(r"slides\[(\d+)\]", str(p))
                si = int(_mi.group(1)) if _mi else None
                out.append({"path": str(p), "msg": m, "slide": si,
                            "key": slide_keys.get(si) if si is not None else None})
            return out

        print(json.dumps({
            "ok": result.ok,
            "errors": _pack(result.errors),
            "warnings": _pack(result.warnings),
            "soft_warnings": _pack(result.soft_warnings),
        }, ensure_ascii=False))
        return 0 if result.ok else 1

    print(f"DeckJSON validation · {args.deck.name}")
    print(f"  deck: {title}")
    print(f"  slides: {n_slides}")
    print(f"  schema: {args.schema}")
    print()

    if result.errors:
        print(f"✗ {len(result.errors)} error(s):")
        for path, msg in result.errors:
            print(f"  {format_path(path, slide_keys):<60}  {msg}")
        print()

    if result.warnings:
        print(f"! {len(result.warnings)} warning(s):")
        for path, msg in result.warnings:
            print(f"  {format_path(path, slide_keys):<60}  {msg}")
        print()

    if result.soft_warnings:
        print(f"ℹ {len(result.soft_warnings)} advisory (non-blocking):")
        for path, msg in result.soft_warnings:
            print(f"  {format_path(path, slide_keys):<60}  {msg}")
        print()

    if result.ok:
        if result.warnings:
            print(f"PASS (with {len(result.warnings)} warnings)")
        else:
            print("PASS")
        return 0
    else:
        print(f"FAIL · {len(result.errors)} error(s){' (warnings promoted in --strict)' if args.strict else ''}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
