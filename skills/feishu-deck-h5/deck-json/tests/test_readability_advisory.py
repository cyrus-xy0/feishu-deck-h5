"""F-253 · render-deck readability advisory.

The default render gate is STATIC-only (`--no-visual`), so the visual
readability audits — chiefly R-VIS-BODY-FLOOR, which catches REAL content
rendered below the 24px body floor (the silent "字偏小" miss where 16px content
in an ambiguously-named class passes both R20 and the static R06 heuristic) —
never run. render-deck now runs them as a NON-BLOCKING advisory for real decks
under runs/, so the miss is surfaced automatically. Tests in /tmp are skipped
(the same /runs/ convention copy-assets uses) and the exit code is never
affected. These wiring tests pin those invariants without spawning Playwright.
"""
import pathlib

HERE = pathlib.Path(__file__).resolve()
RENDER = HERE.parents[2] / "deck-json" / "render-deck.py"


def test_advisory_wired():
    src = RENDER.read_text(encoding="utf-8")
    assert "readability advisory" in src
    assert "F-253" in src
    assert '"/runs/"' in src                       # gated to real decks; /tmp tests skip
    assert '"--visual"' in src and '"--json"' in src  # reuses existing visual audits
    assert "R-VIS" in src                          # surfaces the existing R-VIS findings
    assert "--slide" in src                        # points at the F-254 single-page focus flag


def test_advisory_is_non_blocking():
    src = RENDER.read_text(encoding="utf-8")
    # Guarded by `not args.visual` (when --visual is set the gate already covers it)
    assert "not args.visual" in src
    # Must swallow its own errors so it can never break a render
    assert "an advisory must NEVER break a render" in src


if __name__ == "__main__":
    import sys
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
