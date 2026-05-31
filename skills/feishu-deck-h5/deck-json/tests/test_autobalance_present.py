"""R-AUTOBALANCE-PRESENT · auto-balance runtime 指纹硬闸 (2026-05-31).

The most lethal process root-cause this session: a raw deck NOT re-bundled with
the current feishu-deck.js has 0 lines of auto-balance — the runtime box-crowd
fix never runs. Static gate: deck must carry the `balanceSlide` fingerprint.

Static — no Chromium needed.
"""
import sys
import pathlib

ASSETS = pathlib.Path(__file__).resolve().parents[2] / "assets"
sys.path.insert(0, str(ASSETS))
from _validate_common import Issues          # noqa: E402
from _validate_audits import (               # noqa: E402
    audit_autobalance_present, _AUTOBALANCE_SIG,
)

_SIG_SCRIPT = '<script>' + _AUTOBALANCE_SIG + ' { /* ... */ }</script>'


def _run(html):
    i = Issues()
    audit_autobalance_present(html, i)
    return [c for c, _ in i.errors]


def test_fires_on_raw_deck_without_autobalance():
    html = '<div class="deck"><div class="slide"></div></div>'   # no runtime
    assert "R-AUTOBALANCE-PRESENT" in _run(html), "raw deck missing auto-balance not gated"


def test_quiet_when_runtime_bundled():
    html = '<div class="deck"><div class="slide"></div></div>' + _SIG_SCRIPT
    assert _run(html) == [], "deck WITH balanceSlide fingerprint should pass"


def test_quiet_with_explicit_opt_out():
    html = '<div class="deck" data-no-autobalance><div class="slide"></div></div>'
    assert _run(html) == [], "data-no-autobalance deck should be exempt"


def test_quiet_on_non_deck_html():
    html = '<div class="replica"><img src="x.png"></div>'   # not a deck
    assert _run(html) == [], "non-deck HTML should be skipped"


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
