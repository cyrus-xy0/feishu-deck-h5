"""F-18 tests: the ingest gate must not silently drop a rule whose code was
renamed in validate.py but left stale in business-rules.yaml. The drift guard
warns (never blocks) and stays silent on clean code (all yaml codes covered).

Also a light guard that the shared V.inline_linked (F-14) is importable.
"""
import contextlib
import importlib.util
import io
import json
import re
import sys
import pathlib
import tempfile
import zipfile

ASSETS = pathlib.Path(__file__).resolve().parents[2] / "assets"
sys.path.insert(0, str(ASSETS))
import validate as V  # noqa: E402

# check-only.py has a hyphen → load via importlib
_spec = importlib.util.spec_from_file_location("check_only", ASSETS / "check-only.py")
CO = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(CO)


def test_enumerate_covers_all_yaml_codes():
    """On clean code the yaml gate codes must all be emitted by validate.py —
    otherwise the gate is silently dropping a mandatory rule today."""
    emitted = CO.enumerate_validate_rules()
    assert emitted, "expected to extract some rule codes from validate.py"
    yaml_codes = set(CO.load_business_rules().keys())
    orphaned = yaml_codes - emitted
    assert orphaned == set(), f"yaml codes not emitted by validate.py: {orphaned}"


def test_drift_warns_on_orphan_code():
    """A yaml code absent from validate.py emissions → explicit stderr warning."""
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        CO.warn_on_gate_rule_drift({"R06", "R-PHANTOM-XYZ"}, {"R06", "R02"})
    err = buf.getvalue()
    assert "R-PHANTOM-XYZ" in err
    assert "R06" not in err  # covered code must not be reported


def test_drift_silent_when_subset():
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        CO.warn_on_gate_rule_drift({"R06", "R02"}, {"R06", "R02", "R10"})
    assert buf.getvalue() == ""


def test_drift_silent_when_validate_unreadable():
    """If validate.py couldn't be scanned (empty emitted set), skip quietly —
    never block the gate on a read failure."""
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        CO.warn_on_gate_rule_drift({"R06"}, set())
    assert buf.getvalue() == ""


def test_enumerate_captures_lev_indirection():
    """Codes emitted via the lev/_lev aliases (not iss.err/warn directly) must
    still be captured — else they'd be mis-flagged as gate drift if ever gated."""
    emitted = CO.enumerate_validate_rules()
    # R-VIS-TIER is emitted only via _lev(...) in validate.py
    assert "R-VIS-TIER" in emitted


def test_inline_linked_is_shared():
    """F-14: single source — helper lives on validate.py, check-only keeps no
    copy and references the shared one, and it actually inlines a local link."""
    import tempfile
    assert callable(getattr(V, "inline_linked", None))
    assert not hasattr(CO, "_inline_linked")  # no leftover copy
    src = (ASSETS / "check-only.py").read_text(encoding="utf-8")
    assert "V.inline_linked(" in src  # call site uses the shared helper
    # behavioral round-trip: local <link> inlined, external left untouched
    with tempfile.TemporaryDirectory() as td:
        d = pathlib.Path(td)
        (d / "x.css").write_text("body{color:#fff}", encoding="utf-8")
        html = ('<link rel="stylesheet" href="x.css">'
                '<link rel="stylesheet" href="https://e.com/y.css">')
        out = V.inline_linked(html, d)
        assert '<style data-source="framework">body{color:#fff}</style>' in out
        assert 'href="https://e.com/y.css"' in out


def test_check_only_runs_full_audit_registry():
    """F-08 → UNIFY-VALIDATE step 4b: check-only and validate.py can no longer run
    DIFFERENT rule sets because there is now ONE rule source — the unified engine.
    Both fold the engine's findings in via the SAME shared entry point
    (V.run_unified_audits); the old STATIC_AUDITS / run_static_audits dual
    registry is retired, so the F-08 drift class is structurally impossible.
    Guard the new single-source wiring at the source level (no Chromium)."""
    src = (ASSETS / "check-only.py").read_text(encoding="utf-8")
    assert "run_unified_audits(" in src, \
        "check-only must fold findings via the shared V.run_unified_audits"
    # the legacy dual-registry call must be gone
    assert "run_static_audits(" not in src and "STATIC_AUDITS" not in src
    # the 6 audits check-only historically skipped are now ALL in the single
    # engine source (so default review mode can never under-report them again).
    js = (ASSETS / "audits.js").read_text(encoding="utf-8")
    for rule in ("R-VIS-LIFT-STYLE-LOST", "R-CSSVAR", "R-BULLET-DASH",
                 "R-EMPTY-HEADER-ZONE", "R-ECHO", "R-VIS-NO-IMAGERY"):
        assert ("'" + rule + "'") in js, f"{rule} missing from the unified engine"


def test_all_emitted_codes_documented_in_families():
    """F-03 anti-drift: every rule code validate.py can emit must be
    categorized in check-only's FAMILIES table — so a new rule can't ship
    undocumented (it would otherwise dump into the '未分类' fallback). This is
    the single guard that keeps the rule docs in lockstep with the code."""
    emitted = CO.enumerate_validate_rules()
    fam = {c for _, codes in CO.FAMILIES for c in codes}
    undocumented = sorted(emitted - fam)
    assert not undocumented, \
        f"rule codes emitted by validate.py but missing from FAMILIES: {undocumented}"


def test_validator_rules_reference_documents_every_code():
    """F-03: references/validator-rules.md must document every rule code the
    validator emits — so the human rule reference can't silently drift from the
    code. (Complements the FAMILIES guard above; both doc surfaces stay synced.)"""
    ref = (ASSETS.parent / "references" / "validator-rules.md").read_text(encoding="utf-8")
    documented = set(re.findall(r'\b(R-[A-Z][A-Z0-9-]*|R\d+|L\d+|T\d+|P\d+|UI1)\b', ref))
    for m in re.finditer(r'\bP(\d+)-P?(\d+)\b', ref):          # P50-P55 → P50..P55
        documented |= {f'P{n}' for n in range(int(m.group(1)), int(m.group(2)) + 1)}
    if 'R29-R32' in ref or 'R29-32' in ref:                    # range token alias
        documented.add('R29-32')
    undocumented = sorted(CO.enumerate_validate_rules() - documented)
    assert not undocumented, \
        f"emitted but undocumented in validator-rules.md: {undocumented}"


# Rule-shaped tokens that legitimately appear in validator-rules.md prose but are
# NOT emitted codes — the REVERSE-direction guard's allowlist (contract-2). Each
# must be justified; a code that drifts in (retired rule kept as if live, a typo'd
# row, a never-shipped rule documented as shipped) is NOT here → the test fails,
# forcing a doc fix or an explicit, reviewed addition to this list.
_REVERSE_GUARD_EXEMPT = {
    'L3',                 # explicitly "L3 is not currently shipped"
    'L7',                 # the L7 head-CSS→custom_css CODEMOD task, not a rule code
    'R-RAW-LOOKS-SCHEMA', # RETIRED 2026-06-12 (documented as retired, not live)
    'R-VIS',              # the "R-VIS-*" prefix fragment, not a standalone code
    'R29', 'R32',         # halves of the R29-32 range token (the real code is R29-32)
    'P1', 'P4', 'P7', 'P10', 'P11',  # PAGE references in calibration notes (页 P11 封面…), not P-rules
}


def test_validator_rules_reference_has_no_dead_codes():
    """contract-2 · REVERSE direction of the guard above: a rule-shaped code that
    appears in references/validator-rules.md but is NOT emitted by the validator
    (and is not an explicitly-exempt prose token) is a dead/retired/typo'd code
    lingering in the human reference as if live. The forward test only proves
    engine ⊆ md; this proves md ⊆ engine ∪ exemptions, closing the gap where a
    retired rule (or a typo) stays documented after the code stopped emitting it."""
    ref = (ASSETS.parent / "references" / "validator-rules.md").read_text(encoding="utf-8")
    documented = set(re.findall(r'\b(R-[A-Z][A-Z0-9-]*|R\d+|L\d+|T\d+|P\d+|UI1)\b', ref))
    for m in re.finditer(r'\bP(\d+)-P?(\d+)\b', ref):          # P50-P55 → P50..P55
        documented |= {f'P{n}' for n in range(int(m.group(1)), int(m.group(2)) + 1)}
    if 'R29-R32' in ref or 'R29-32' in ref:                    # range token alias
        documented.add('R29-32')
    emitted = CO.enumerate_validate_rules()
    dead = sorted(documented - emitted - _REVERSE_GUARD_EXEMPT)
    assert not dead, (
        "rule codes documented in validator-rules.md but NOT emitted by the "
        f"validator (retired/typo'd? remove the row or fix the code): {dead}. "
        "If a token is legitimate prose (a retired/unshipped rule, a page ref, a "
        "prefix), add it to _REVERSE_GUARD_EXEMPT with a justification.")


def test_families_cover_newly_surfaced_codes():
    """The previously-skipped audits' codes must be categorized in FAMILIES so
    check-only's review groups them instead of dumping to '未分类'."""
    fam_codes = {c for _, codes in CO.FAMILIES for c in codes}
    for code in ('R-ECHO', 'R-BULLET-DASH', 'R-CSSVAR',
                 'R-EMPTY-HEADER-ZONE', 'R-VIS-LIFT-STYLE-LOST'):
        assert code in fam_codes, f"{code} not categorized in FAMILIES"


def test_visual_defaults_on_parity_with_validate():
    """2026-05-31: check-only's visual audits must default ON, matching
    validate.py — else the canonical `check-only.sh deck.html` silently skips
    the R-VIS-* / R-FOCAL renderer audits and reports a half-checked PASS.
    Same drift class F-08 closed at the registry level, reopened via the
    --visual default. Guard at the CLI layer (no chromium needed)."""
    assert CO.build_parser().parse_args(["deck.html"]).visual is True, \
        "check-only --visual must default to True"
    # explicit --no-visual still works as the CI / no-chromium escape hatch
    assert CO.build_parser().parse_args(
        ["deck.html", "--no-visual"]).visual is False
    # validate.py must agree (BooleanOptionalAction default-on) — source-level
    # parity check, mirroring this file's other validate.py source scans.
    vsrc = (ASSETS / "validate.py").read_text(encoding="utf-8")
    assert re.search(r"--visual.*BooleanOptionalAction", vsrc, re.S), \
        "validate.py --visual must stay BooleanOptionalAction default-on"


def _write_library_zip(path, members):
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in members.items():
            if isinstance(data, str):
                data = data.encode("utf-8")
            zf.writestr(name, data)


def _base_zip_members(html=None):
    html = html or """<!doctype html>
<html><head><link rel="stylesheet" href="assets/style.css"></head>
<body><img src="assets/local.png"></body></html>
"""
    return {
        "index.html": html,
        "deck.json": json.dumps({"schema_version": "1.0", "slides": []}),
        "assets-manifest.yaml": "assets:\n  - assets/local.png\n",
        "ingestion-manifest.json": json.dumps({
            "deck_id": "lark-test-2026-06-11",
            "package_type": "feishu-deck-h5-library",
            "primary_html": "index.html",
        }),
        "assets/style.css": "body{background:url(local.png)}",
        "assets/local.png": b"fake-png",
    }


def test_zip_package_contract_accepts_top_level_deck_zip():
    with tempfile.TemporaryDirectory() as td:
        td = pathlib.Path(td)
        archive = td / "deck.zip"
        _write_library_zip(archive, _base_zip_members())
        primary, errors, warnings = CO.inspect_zip_package(archive, td / "extract")
        assert errors == []
        assert primary.name == "index.html"
        assert "缺软必需文件: README.md" in warnings


def test_zip_package_contract_rejects_output_wrapper():
    with tempfile.TemporaryDirectory() as td:
        td = pathlib.Path(td)
        archive = td / "deck.zip"
        _write_library_zip(archive, {
            "output/index.html": "<html></html>",
            "output/deck.json": "{}",
            "output/assets-manifest.yaml": "assets: []\n",
            "output/ingestion-manifest.json": '{"primary_html":"index.html"}',
            "output/assets/local.png": b"x",
        })
        primary, errors, _warnings = CO.inspect_zip_package(archive, td / "extract")
        assert primary is None
        assert any("顶层只有 output/" in item for item in errors)


def test_zip_package_contract_rejects_missing_asset_reference():
    with tempfile.TemporaryDirectory() as td:
        td = pathlib.Path(td)
        archive = td / "deck.zip"
        members = _base_zip_members(
            '<!doctype html><html><body><img src="assets/missing.png"></body></html>'
        )
        _write_library_zip(archive, members)
        primary, errors, _warnings = CO.inspect_zip_package(archive, td / "extract")
        assert primary is not None
        assert any("HTML 引用资产缺失: assets/missing.png" in item for item in errors)


def test_zip_package_contract_rejects_missing_nested_script():
    with tempfile.TemporaryDirectory() as td:
        td = pathlib.Path(td)
        archive = td / "deck.zip"
        members = _base_zip_members(
            '<!doctype html><html><body><iframe src="assets/prototypes/demo/index.html"></iframe></body></html>'
        )
        members["assets/prototypes/demo/index.html"] = '<script type="module" src="app.js"></script>'
        _write_library_zip(archive, members)

        primary, errors, _warnings = CO.inspect_zip_package(archive, td / "extract")

        assert primary is not None
        assert any(
            "LOCAL_REF_MISSING assets/prototypes/demo/index.html -> app.js" in item
            for item in errors
        )


def test_zip_package_contract_rejects_missing_javascript_module():
    with tempfile.TemporaryDirectory() as td:
        td = pathlib.Path(td)
        archive = td / "deck.zip"
        members = _base_zip_members(
            '<!doctype html><html><body><script type="module" src="assets/app.js"></script></body></html>'
        )
        members["assets/app.js"] = 'import "./missing-module.js";\n'
        _write_library_zip(archive, members)

        primary, errors, _warnings = CO.inspect_zip_package(archive, td / "extract")

        assert primary is not None
        assert any("LOCAL_REF_MISSING assets/app.js -> ./missing-module.js" in item for item in errors)


def test_zip_package_contract_rejects_zero_byte_asset():
    with tempfile.TemporaryDirectory() as td:
        td = pathlib.Path(td)
        archive = td / "deck.zip"
        members = _base_zip_members()
        members["assets/local.png"] = b""
        _write_library_zip(archive, members)

        primary, errors, _warnings = CO.inspect_zip_package(archive, td / "extract")

        assert primary is not None
        assert any("LOCAL_ASSET_EMPTY index.html -> assets/local.png" in item for item in errors)


def test_zip_package_contract_rejects_stale_manifest_path():
    with tempfile.TemporaryDirectory() as td:
        td = pathlib.Path(td)
        archive = td / "deck.zip"
        members = _base_zip_members()
        members["assets-manifest.yaml"] += "  - assets/stale.png\n"
        _write_library_zip(archive, members)

        primary, errors, _warnings = CO.inspect_zip_package(archive, td / "extract")

        assert primary is not None
        assert any("MANIFEST_REF_MISSING assets-manifest.yaml -> assets/stale.png" in item for item in errors)


def test_zip_package_contract_rejects_empty_manifest_only_asset():
    with tempfile.TemporaryDirectory() as td:
        td = pathlib.Path(td)
        archive = td / "deck.zip"
        members = _base_zip_members()
        members["assets-manifest.yaml"] += "  - assets/unused-empty.png\n"
        members["assets/unused-empty.png"] = b""
        _write_library_zip(archive, members)

        primary, errors, _warnings = CO.inspect_zip_package(archive, td / "extract")

        assert primary is not None
        assert any(
            "MANIFEST_ASSET_EMPTY assets-manifest.yaml -> assets/unused-empty.png" in item
            for item in errors
        )


def test_zip_package_contract_rejects_redirect_shell_primary_html():
    with tempfile.TemporaryDirectory() as td:
        td = pathlib.Path(td)
        archive = td / "deck.zip"
        members = _base_zip_members(
            """<!doctype html>
<html><head><meta http-equiv="refresh" content="0; url=deck.html"></head>
<body><a href="deck.html">open</a></body></html>
"""
        )
        members["deck.html"] = (
            '<!doctype html><html><body><div class="slide" '
            'data-slide-key="cover">Cover</div></body></html>'
        )
        _write_library_zip(archive, members)

        primary, errors, _warnings = CO.inspect_zip_package(archive, td / "extract")

        assert primary is not None
        assert any("primary_html 是跳转壳" in item for item in errors)


def test_zip_package_contract_accepts_viewer_download_roundtrip_manifest():
    with tempfile.TemporaryDirectory() as td:
        td = pathlib.Path(td)
        archive = td / "download.zip"
        members = _base_zip_members(
            """<!doctype html>
<html><head><link rel="stylesheet" href="assets/feishu-deck.css"></head>
<body><div class="slide" data-slide-key="cover">Cover</div></body></html>
"""
        )
        members["assets-manifest.yaml"] = "framework:\n  - assets/feishu-deck.css\n  - assets/feishu-deck.js\n"
        members["ingestion-manifest.json"] = json.dumps({
            "schema_version": "1.0",
            "package_type": "feishu-deck-h5-library",
            "deck_id": "download-roundtrip",
            "primary_html": "index.html",
            "generated_by": "feishu-slide-library viewer download",
            "source": "viewer-download",
        })
        members["assets/feishu-deck.css"] = "body{margin:0}"
        members["assets/feishu-deck.js"] = "window.FeishuDeck = {};"
        members.pop("assets/style.css", None)
        members.pop("assets/local.png", None)

        _write_library_zip(archive, members)
        primary, errors, warnings = CO.inspect_zip_package(archive, td / "extract")

        assert primary is not None
        assert errors == []
        assert any("缺软必需文件: README.md" in item for item in warnings)


def test_zip_package_contract_rejects_local_and_escape_paths():
    with tempfile.TemporaryDirectory() as td:
        td = pathlib.Path(td)
        archive = td / "deck.zip"
        members = _base_zip_members(
            '<!doctype html><html><body>'
            '<img src="../outside.png">'
            '<img src="file:///Users/me/secret.png">'
            '<img src="C:\\\\tmp\\\\x.png">'
            '</body></html>'
        )
        _write_library_zip(archive, members)
        primary, errors, _warnings = CO.inspect_zip_package(archive, td / "extract")
        assert primary is not None
        joined = "\n".join(errors)
        assert "../ 越界路径" in joined
        assert "本机路径" in joined
        assert "Windows 盘符路径" in joined


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn(); print(f"  ok  {fn.__name__}")
        except Exception:
            failed += 1; print(f"FAIL  {fn.__name__}"); traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
