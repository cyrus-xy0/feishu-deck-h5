"""F-292 · tuning F-256's hard visual BLOCK so it is strict on NEW decks but
does NOT add friction on stock/imported ones.

Two adjustments under test:

  Step 1 — DEAD-CODE class is demoted from the hard _vis_block to advisory.
    R-VIS-DEAD-ANIM / R-VIS-DEAD-RULE are CODE HYGIENE (a dead @keyframes / a
    never-matched rule — not visible on screen). They print an advisory ("run
    the cleaner") but never gate delivery. Real audit motivation: 80/107 of an
    imported deck's "blocking" findings were these two.

  Step 2 — STOCK/IMPORTED exemption. The _vis_block demotes to advisory (prints,
    does NOT return 4) when EITHER deck_meta.gate == "advisory" OR the deck is
    imported (every active slide lifted, or <meta fs-deck-origin=imported> in
    the rendered HTML). HARD GEOMETRY (_geom_block) and the static gate stay
    full BLOCK even in advisory mode.

These tests DO NOT require Playwright. They drive render-deck.py in-process
(RD.main) and monkeypatch RD.subprocess.run so the validate.py `--visual --json`
call returns CRAFTED findings — the exact pattern test_atomic_render.py uses for
the static gate. The deck.json schema-validate + every non-validator subprocess
run for real (so the new `gate` schema field is exercised end-to-end).
"""
import importlib.util
import json
import pathlib
import subprocess
import sys

import pytest

DECK_JSON = pathlib.Path(__file__).resolve().parents[1]
RENDER = DECK_JSON / "render-deck.py"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


RD = _load("_rd_gate_tuning", RENDER)
VH = str(RD.VALIDATE_HTML)
CD = str(RD.CHECK_DIST)


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------
def _runs_output(td) -> pathlib.Path:
    """A runs/<ts>/output/ path — the real-delivery layout the gate keys on so
    _is_runs is True and the F-256 visual gate actually fires."""
    out = pathlib.Path(td) / "runs" / "20260610-000000" / "output"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _deck(*, gate=None, lifted=False, title="T",
          body="这是一段足够长的正文内容用来填充页面文本区域确保有内容"):
    """A minimal single-slide raw deck. `gate` sets deck_meta.gate; `lifted`
    marks the slide lifted (→ imported-deck auto-exemption)."""
    d = {
        "version": "1.0",
        "deck": {"title": title, "author": "a", "date": "2026.06.10",
                 "presentation_date": "2026-06-10", "customer_slug": "wa-gt",
                 "language": "zh-only", "mode": "rewrite"},
        "slides": [{
            "key": "k", "layout": "raw", "screen_label": "01 X",
            "data": {"html": f'<div class="stage"><p style="color:#ddd;'
                             f'font-size:24px">{body}</p></div>'},
        }],
    }
    if gate is not None:
        d["deck"]["gate"] = gate
    if lifted:
        d["slides"][0]["lifted"] = "some-deck#1"
    return d


def _write(td, deck, name="deck.json") -> pathlib.Path:
    p = pathlib.Path(td) / name
    p.write_text(json.dumps(deck, ensure_ascii=False), encoding="utf-8")
    return p


def _fake_validate(monkeypatch, *, visual_errors=(), visual_warnings=()):
    """Monkeypatch RD.subprocess.run so the validator calls are STUBBED with
    crafted findings (no Playwright); everything else (deck.json schema validate,
    asset copy, etc.) runs for real.

      • validate.py WITHOUT --json (the static gate) → rc=0 (PASS).
      • validate.py WITH --json (the visual advisory)  → crafted JSON.
      • check-distribution.py --json                    → [] (no findings).
    """
    real_run = subprocess.run

    def fake_run(cmd, *a, **k):
        toks = [str(c) for c in cmd] if isinstance(cmd, (list, tuple)) else [str(cmd)]
        is_vh = VH in toks
        is_cd = CD in toks
        if is_vh and "--json" in toks:
            payload = {
                "deck": "x", "slides": 1,
                "errors": [dict(f) for f in visual_errors],
                "warnings": [dict(f) for f in visual_warnings],
            }
            return subprocess.CompletedProcess(
                cmd, 0, stdout=json.dumps(payload), stderr="")
        if is_vh:  # static gate, no --json → pass
            return subprocess.CompletedProcess(cmd, 0, stdout="PASS\n", stderr="")
        if is_cd:  # distribution audit → no findings
            return subprocess.CompletedProcess(cmd, 0, stdout="[]", stderr="")
        return real_run(cmd, *a, **k)

    monkeypatch.setattr(RD.subprocess, "run", fake_run)


def _gate_line(err: str):
    for ln in err.splitlines():
        if ln.startswith("GATE-COVERAGE "):
            return ln
    return None


# A real, user-visible visual error (content below the readability floor).
_FLOOR_ERR = {"code": "R-VIS-BODY-FLOOR", "slide": 1,
              "msg": "正文 16px < 24px 可读底线"}
_TIER_ERR = {"code": "R-VIS-TIER", "slide": 1,
             "msg": "层级反转:正文大于标题"}
# Dead-code (code hygiene) errors — must NOT block.
_DEAD_ANIM = {"code": "R-VIS-DEAD-ANIM", "slide": 1,
              "msg": "@keyframes foo 定义但无引用"}
_DEAD_RULE = {"code": "R-VIS-DEAD-RULE", "slide": 1,
              "msg": ".never-used 规则无匹配元素"}
# Hard geometry — must STILL block, even in advisory mode.
_OVERFLOW_ERR = {"code": "R-OVERFLOW", "slide": 1,
                 "msg": "内容溢出容器 scrollHeight>clientHeight"}


# ==========================================================================
# Step 1 · dead-code class demotes to advisory (never blocks)
# ==========================================================================
def test_dead_code_only_does_not_block(monkeypatch, tmp_path, capsys):
    _fake_validate(monkeypatch, visual_errors=[_DEAD_ANIM, _DEAD_RULE])
    out = _runs_output(tmp_path)
    deck = _write(tmp_path, _deck())
    rc = RD.main([str(deck), str(out) + "/", "--skip-copy-assets"])
    err = capsys.readouterr().err
    assert rc == 0, f"dead-code-only must NOT block delivery:\n{err}"
    assert "死代码" in err, f"dead-code advisory must be printed:\n{err}"
    # it is advisory, not a BLOCK
    assert "BLOCKING · error-level visual defects" not in err


def test_dead_code_mixed_with_real_error_still_blocks(monkeypatch, tmp_path, capsys):
    # Dead-code is exempt, but a REAL visual error in the same render still
    # blocks (block decks default to block).
    _fake_validate(monkeypatch, visual_errors=[_DEAD_ANIM, _FLOOR_ERR])
    out = _runs_output(tmp_path)
    deck = _write(tmp_path, _deck())
    rc = RD.main([str(deck), str(out) + "/", "--skip-copy-assets"])
    err = capsys.readouterr().err
    assert rc == 4, f"a real visual error alongside dead-code must still BLOCK:\n{err}"
    assert "死代码" in err          # dead-code still surfaced as advisory
    assert "BLOCKING" in err        # real error blocked


# ==========================================================================
# Step 1/2 · real visual error on a default-block deck STILL blocks
# ==========================================================================
@pytest.mark.parametrize("vis_err", [_FLOOR_ERR, _TIER_ERR])
def test_real_visual_error_blocks_default_block_deck(monkeypatch, tmp_path, capsys, vis_err):
    _fake_validate(monkeypatch, visual_errors=[vis_err])
    out = _runs_output(tmp_path)
    deck = _write(tmp_path, _deck())  # no gate field → default block
    rc = RD.main([str(deck), str(out) + "/", "--skip-copy-assets"])
    err = capsys.readouterr().err
    assert rc == 4, f"{vis_err['code']} on a default-block deck must BLOCK:\n{err}"
    assert "BLOCKING" in err
    line = _gate_line(err)
    assert line and "visual=ran" in line, f"gate should report visual=ran:\n{line}"


# ==========================================================================
# Step 2 · deck_meta.gate == "advisory" demotes the visual BLOCK
# ==========================================================================
def test_gate_advisory_demotes_real_visual_error(monkeypatch, tmp_path, capsys):
    _fake_validate(monkeypatch, visual_errors=[_FLOOR_ERR])
    out = _runs_output(tmp_path)
    deck = _write(tmp_path, _deck(gate="advisory"))
    rc = RD.main([str(deck), str(out) + "/", "--skip-copy-assets"])
    err = capsys.readouterr().err
    assert rc == 0, f"gate=advisory must NOT block on a visual error:\n{err}"
    assert "advisory 模式,未阻断交付" in err, f"expected advisory wording:\n{err}"
    line = _gate_line(err)
    assert line and "visual=advisory(deck-gate)" in line, \
        f"coverage must record advisory(deck-gate):\n{line}"


# ==========================================================================
# Step 2 · imported deck (all slides lifted) auto-demotes the visual BLOCK
# ==========================================================================
def test_imported_deck_auto_demotes_real_visual_error(monkeypatch, tmp_path, capsys):
    _fake_validate(monkeypatch, visual_errors=[_FLOOR_ERR])
    out = _runs_output(tmp_path)
    deck = _write(tmp_path, _deck(lifted=True))  # all slides lifted → imported
    rc = RD.main([str(deck), str(out) + "/", "--skip-copy-assets"])
    err = capsys.readouterr().err
    assert rc == 0, f"imported deck must NOT block on a visual error:\n{err}"
    assert "advisory 模式,未阻断交付" in err
    line = _gate_line(err)
    assert line and "visual=advisory(imported)" in line, \
        f"coverage must record advisory(imported):\n{line}"


# ==========================================================================
# Step 2 · HARD GEOMETRY still blocks even in advisory mode
# ==========================================================================
def test_advisory_mode_still_blocks_hard_geometry(monkeypatch, tmp_path, capsys):
    # gate=advisory relaxes the font/floor/tier class, but a content OVERFLOW is
    # the most plainly user-visible breakage — _geom_block must still return 4.
    _fake_validate(monkeypatch, visual_errors=[_OVERFLOW_ERR])
    out = _runs_output(tmp_path)
    deck = _write(tmp_path, _deck(gate="advisory"))
    rc = RD.main([str(deck), str(out) + "/", "--skip-copy-assets"])
    err = capsys.readouterr().err
    assert rc == 4, f"advisory mode must STILL block hard geometry:\n{err}"
    assert "geometry breakage" in err, f"expected the geometry BLOCK notice:\n{err}"


def test_advisory_mode_geometry_block_honours_overflow_escape(monkeypatch, tmp_path, capsys):
    # The geometry block keeps its OWN narrow escape hatch even in advisory mode.
    _fake_validate(monkeypatch, visual_errors=[_OVERFLOW_ERR])
    out = _runs_output(tmp_path)
    deck = _write(tmp_path, _deck(gate="advisory"))
    # main() reads os.environ directly; set it for the duration of this test.
    monkeypatch.setenv("DECK_ALLOW_GEOM_OVERFLOW", "1")
    rc = RD.main([str(deck), str(out) + "/", "--skip-copy-assets"])
    err = capsys.readouterr().err
    assert rc == 0, f"DECK_ALLOW_GEOM_OVERFLOW=1 must let it through:\n{err}"


# ==========================================================================
# regression · a default-block deck with NO findings passes clean
# ==========================================================================
def test_clean_default_deck_passes(monkeypatch, tmp_path, capsys):
    _fake_validate(monkeypatch, visual_errors=[], visual_warnings=[])
    out = _runs_output(tmp_path)
    deck = _write(tmp_path, _deck())
    rc = RD.main([str(deck), str(out) + "/", "--skip-copy-assets"])
    err = capsys.readouterr().err
    assert rc == 0, f"a clean default deck must pass:\n{err}"
    line = _gate_line(err)
    assert line and "visual=ran" in line, f"clean gate should report visual=ran:\n{line}"
    assert "advisory(" not in line, f"no advisory tag on a clean deck:\n{line}"


# ==========================================================================
# schema · deck_meta.gate is a legal optional field
# ==========================================================================
def test_schema_accepts_gate_field(tmp_path):
    """deck.json with deck_meta.gate=advisory passes the real schema validator
    (VALIDATE_DECK --strict, run as a subprocess for real)."""
    deck = _write(tmp_path, _deck(gate="advisory"))
    r = subprocess.run(
        [sys.executable, str(RD.VALIDATE_DECK), str(deck), "--strict"],
        capture_output=True, text=True)
    assert r.returncode == 0, \
        f"deck_meta.gate=advisory must pass schema validation:\n{r.stdout}\n{r.stderr}"


def test_schema_rejects_bad_gate_value(tmp_path):
    """An out-of-enum gate value is rejected (the field is constrained)."""
    deck = _write(tmp_path, _deck(gate="loose"))
    r = subprocess.run(
        [sys.executable, str(RD.VALIDATE_DECK), str(deck), "--strict"],
        capture_output=True, text=True)
    assert r.returncode != 0, \
        f"an out-of-enum gate value must be rejected:\n{r.stdout}\n{r.stderr}"


if __name__ == "__main__":
    import traceback
    import inspect
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    ran = 0
    for fn in fns:
        if inspect.signature(fn).parameters:
            print(f"skip  {fn.__name__} (needs pytest fixtures)")
            continue
        ran += 1
        try:
            fn()
            print(f"  ok  {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL  {fn.__name__}")
            traceback.print_exc()
    print(f"\n{ran - failed}/{ran} ran")
    sys.exit(1 if failed else 0)
