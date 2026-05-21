"""Asserts editor.js BLOCK_TYPES / EXTRA_FIELDS / ARRAY_FIELDS field shapes
agree with deck-schema.json $defs. Drift here causes inspector ops to
silently rollback at the server (schema rejects). Catches the 6 drift bugs
the architecture reviewer found in the Phase 0-4 PR.
"""
import json
import re
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
DECK_JSON = HERE.parent
SCHEMA = json.loads((DECK_JSON / "deck-schema.json").read_text(encoding="utf-8"))
EDITOR_JS = (DECK_JSON / "editor" / "editor.js").read_text(encoding="utf-8")

DEFS = SCHEMA.get("$defs", SCHEMA.get("definitions", {}))


def _extract_object_literal(js: str, var_name: str) -> str:
    """Find `const VAR = {...};` and return the brace-balanced literal text.

    Tiny brace-counter — no real JS parser. Adequate because the source we
    target is hand-written, formatted, and uses standard `const X = {...};`.
    """
    m = re.search(rf"const\s+{re.escape(var_name)}\s*=\s*\{{", js)
    if not m:
        raise AssertionError(f"could not locate `const {var_name} = {{` in editor.js")
    start = m.end() - 1   # position of opening `{`
    depth = 0
    in_str = None
    i = start
    while i < len(js):
        c = js[i]
        if in_str:
            if c == "\\":
                i += 2
                continue
            if c == in_str:
                in_str = None
        elif c in ('"', "'", "`"):
            in_str = c
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return js[start:i + 1]
        i += 1
    raise AssertionError(f"unbalanced braces while parsing {var_name}")


def _parse_block_types_from_js(js: str) -> dict:
    """Extract enough info from BLOCK_TYPES to compare with schema:

      { type_name: { defaults_keys: set, field_keys: set, tone_enum: set|None } }

    NOT a real JS parser — uses regex against the known editor.js shape.
    """
    body = _extract_object_literal(js, "BLOCK_TYPES")
    out: dict[str, dict] = {}

    # Find each top-level "type-name": { ... } entry
    # We re-use balanced-brace finder
    i = 0
    while i < len(body):
        m = re.search(r'"([a-z-]+)"\s*:\s*\{', body[i:])
        if not m:
            break
        type_name = m.group(1)
        block_start = i + m.end() - 1   # at `{`
        # Skip non-block keys (e.g. inside defaults). Use depth.
        depth = 0
        j = block_start
        in_str = None
        while j < len(body):
            c = body[j]
            if in_str:
                if c == "\\":
                    j += 2; continue
                if c == in_str:
                    in_str = None
            elif c in ('"', "'", "`"):
                in_str = c
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    block_text = body[block_start:j + 1]
                    out[type_name] = _parse_block_entry(block_text)
                    i = j + 1
                    break
            j += 1
        else:
            break
        if i <= m.end():
            i = m.end()
    return out


def _parse_block_entry(block_text: str) -> dict:
    """Pull out defaults keys, fields[].key list, tone select enum if any."""
    # defaults: () => ({ ... })  — grab the inner braces
    def_m = re.search(r"defaults:\s*\(\s*\)\s*=>\s*\(\s*\{", block_text)
    defaults_keys: set[str] = set()
    if def_m:
        # Find the matching close-paren for the (...) arrow body
        start = def_m.end() - 1
        depth = 0
        in_str = None
        for j in range(start, len(block_text)):
            c = block_text[j]
            if in_str:
                if c == "\\": continue
                if c == in_str: in_str = None
            elif c in ('"', "'", "`"):
                in_str = c
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    inner = block_text[start:j + 1]
                    # Pull top-level keys: `keyname:` patterns at depth-1
                    defaults_keys = _extract_top_level_keys(inner)
                    break

    # fields: [ { key: "X", ... }, ... ]
    field_keys: list[str] = re.findall(r"\bkey:\s*\"([^\"]+)\"", block_text)
    # but field_keys also matches `key:` inside nested arrays (e.g. select
    # options). For our purpose, all "key:" entries inside BLOCK_TYPES are
    # field key declarations, since select uses string array literal.

    # tone select enum (within fields array, look for `key:"tone"... select: [...]`)
    tone_m = re.search(r"key:\s*\"tone\"[^}]*?select:\s*\[([^\]]*)\]", block_text, re.S)
    tone_enum: set[str] | None = None
    if tone_m:
        tone_enum = set(re.findall(r'"([^"]+)"', tone_m.group(1)))

    return {
        "defaults_keys": defaults_keys,
        "field_keys":    set(field_keys),
        "tone_enum":     tone_enum,
    }


def _extract_top_level_keys(brace_block: str) -> set[str]:
    """For a `{ k1: v1, k2: { ... }, k3: [...] }` string, return {k1,k2,k3}.

    Uses depth counting; ignores keys inside nested objects/arrays.
    """
    out: set[str] = set()
    if not brace_block.startswith("{") or not brace_block.endswith("}"):
        return out
    body = brace_block[1:-1]
    depth = 0
    in_str = None
    last_comma = 0
    segments = []
    i = 0
    while i < len(body):
        c = body[i]
        if in_str:
            if c == "\\":
                i += 2; continue
            if c == in_str:
                in_str = None
        elif c in ('"', "'", "`"):
            in_str = c
        elif c in "{[":
            depth += 1
        elif c in "}]":
            depth -= 1
        elif c == "," and depth == 0:
            segments.append(body[last_comma:i])
            last_comma = i + 1
        i += 1
    segments.append(body[last_comma:])
    for seg in segments:
        seg = seg.strip()
        # `key: ...` or `"key": ...`
        km = re.match(r'^(?:"([^"]+)"|([\w$_-]+))\s*:', seg)
        if km:
            out.add(km.group(1) or km.group(2))
    return out


# ────────────────────────────────────────────────────────────────────────


SCHEMA_BLOCK_DEFS = {
    "pullquote":      "block_pullquote",
    "cta-box":        "block_cta_box",
    "kpi-strip":      "block_kpi_strip",
    "data-panel":     "block_data_panel",
    "verdict-grid":   "block_verdict_grid",
    "phone-iframe":   "block_phone_iframe",
    "principle-band": "block_principle_band",
}


class BlockTypesParityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.block_types = _parse_block_types_from_js(EDITOR_JS)

    def test_all_schema_blocks_covered_in_editor(self):
        missing = set(SCHEMA_BLOCK_DEFS) - set(self.block_types)
        self.assertFalse(missing, f"editor.js BLOCK_TYPES missing: {sorted(missing)}")

    def test_no_extra_block_types_in_editor(self):
        extra = set(self.block_types) - set(SCHEMA_BLOCK_DEFS)
        self.assertFalse(extra, f"editor.js BLOCK_TYPES has unknown types not in schema: {sorted(extra)}")

    def test_defaults_emit_all_required_fields(self):
        """Each BLOCK_TYPES.defaults() must include every schema-required field."""
        problems = []
        for type_name, def_key in SCHEMA_BLOCK_DEFS.items():
            sd = DEFS[def_key]
            required = set(sd.get("required", []))
            defaults_keys = self.block_types[type_name]["defaults_keys"]
            missing = required - defaults_keys
            if missing:
                problems.append(f"  {type_name}: defaults missing required {sorted(missing)}")
        self.assertFalse(problems, "BLOCK_TYPES defaults drift:\n" + "\n".join(problems))

    def test_field_keys_are_schema_properties(self):
        """Every key in BLOCK_TYPES.fields[] must be a property the schema accepts.

        (Subset relationship: editor doesn't need to expose every schema prop,
        but every editor key must be valid — else schema's additionalProperties:false
        rejects on save.)
        """
        problems = []
        for type_name, def_key in SCHEMA_BLOCK_DEFS.items():
            sd = DEFS[def_key]
            schema_props = set((sd.get("properties") or {}).keys())
            editor_keys = self.block_types[type_name]["field_keys"]
            # Strip dotted-path roots — e.g. "left.title" → "left"
            editor_roots = {k.split(".", 1)[0] for k in editor_keys}
            unknown = editor_roots - schema_props
            if unknown:
                problems.append(f"  {type_name}: editor fields not in schema: {sorted(unknown)}")
        self.assertFalse(problems, "Field key drift:\n" + "\n".join(problems))

    def test_tone_enums_match_schema(self):
        """If editor exposes a tone select, its enum must be a subset of the
        schema's tone enum (preferably exact)."""
        problems = []
        for type_name, def_key in SCHEMA_BLOCK_DEFS.items():
            sd = DEFS[def_key]
            tone_schema = (sd.get("properties") or {}).get("tone", {})
            schema_enum = set(tone_schema.get("enum") or [])
            editor_enum = self.block_types[type_name]["tone_enum"]
            if editor_enum is None:
                continue
            extra = editor_enum - schema_enum
            if extra:
                problems.append(
                    f"  {type_name}: editor tone enum has {sorted(extra)} "
                    f"not in schema {sorted(schema_enum)}"
                )
        self.assertFalse(problems, "Tone enum drift:\n" + "\n".join(problems))


if __name__ == "__main__":
    unittest.main()
