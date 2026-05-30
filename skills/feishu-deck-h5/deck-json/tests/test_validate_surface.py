"""F-10 safety net: validate.py's public surface (every name check-only,
render-deck, and the test suite reference as V.X — audit functions, the Issues
class, extract_slides, the constants, the regex helpers) MUST survive the
module split intact. If the physical split drops or renames a symbol, this
fails loudly — catching breakage the other tests might miss (e.g. a symbol used
only by the Playwright-driven run_visual_audits, which can't run here).

The snapshot in _validate_surface.json is the contract; regenerate it
deliberately only when intentionally removing a public symbol.
"""
import json
import sys
import pathlib

ASSETS = pathlib.Path(__file__).resolve().parents[2] / "assets"
sys.path.insert(0, str(ASSETS))
import validate as V  # noqa: E402

SNAPSHOT = set(json.loads(
    (pathlib.Path(__file__).resolve().parent / "_validate_surface.json").read_text(encoding="utf-8")))


def test_public_surface_preserved():
    current = {n for n in dir(V) if not n.startswith('__')}
    missing = sorted(SNAPSHOT - current)
    assert not missing, f"validate.py lost public symbols across the split: {missing}"


if __name__ == "__main__":
    test_public_surface_preserved()
    print("ok")
