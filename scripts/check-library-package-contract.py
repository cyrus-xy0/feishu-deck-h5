#!/usr/bin/env python3
"""Generate a deck.zip and prove the current slide-library accepts it."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DECK_SKILL = REPO_ROOT / "skills" / "feishu-deck-h5"
PACKAGE_INGEST = DECK_SKILL / "assets" / "package-ingest.sh"


def write_contract_fixture(output: Path) -> None:
    output.mkdir(parents=True)
    (output / "index.html").write_text(
        """<!doctype html>
<html><body>
<main><div class="slide" data-slide-key="cover" data-layout="raw" data-screen-label="契约测试">
<h1>deck.zip 跨仓契约测试</h1>
<iframe src="assets/prototype/index.html"></iframe>
</div></main>
</body></html>
""",
        encoding="utf-8",
    )
    (output / "deck.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "deck": {"title": "deck.zip 跨仓契约测试"},
                "slides": [{"key": "cover", "layout": "raw"}],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (output / "assets-manifest.yaml").write_text(
        "deck-local:\n"
        "  - assets/prototype/index.html\n"
        "  - assets/prototype/style.css\n"
        "  - assets/prototype/app.js\n"
        "  - assets/prototype/module.js\n"
        "  - assets/prototype/pixel.png\n",
        encoding="utf-8",
    )
    prototype = output / "assets" / "prototype"
    prototype.mkdir(parents=True)
    (prototype / "index.html").write_text(
        '<!doctype html><link rel="stylesheet" href="style.css">'
        '<body><img src="pixel.png"><script type="module" src="app.js"></script></body>',
        encoding="utf-8",
    )
    (prototype / "style.css").write_text("body{background-image:url('pixel.png')}\n", encoding="utf-8")
    (prototype / "app.js").write_text('import { ready } from "./module.js"; ready();\n', encoding="utf-8")
    (prototype / "module.js").write_text("export function ready(){ return true; }\n", encoding="utf-8")
    (prototype / "pixel.png").write_bytes(b"contract-image")


def run_checked(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        raise RuntimeError(f"command failed: {' '.join(command)}\n{detail}")
    return result


def verify_contract(library_root: Path) -> dict:
    ingest_package = library_root / "skills" / "feishu-slide-library" / "assets" / "ingest-package.py"
    if not ingest_package.is_file():
        raise FileNotFoundError(f"slide-library ingest script not found: {ingest_package}")
    with tempfile.TemporaryDirectory(prefix="deck-zip-contract-") as td:
        temp_root = Path(td)
        output = temp_root / "output"
        write_contract_fixture(output)
        run_checked(
            [
                "bash",
                str(PACKAGE_INGEST),
                str(output),
                "--deck-id",
                "lark-deck-zip-contract-2026-07-10",
            ],
            cwd=REPO_ROOT,
        )
        manifest = json.loads((output / "ingestion-manifest.json").read_text(encoding="utf-8"))
        if manifest.get("asset_closure", {}).get("status") != "verified":
            raise RuntimeError("generated package has no verified asset_closure evidence")
        result = run_checked(
            [
                sys.executable,
                str(ingest_package),
                str(output / "deck.zip"),
                "--deck-id",
                "lark-deck-zip-contract-2026-07-10",
                "--job-id",
                "deck-zip-contract",
                "--staging-root",
                str(temp_root / "staging"),
                "--library-root",
                str(library_root),
                "--submitted-by",
                "GitHub Actions Contract Test",
                "--overwrite",
                "--no-deck-h5-gate",
                "--resource-checks-only",
            ],
            cwd=library_root,
        )
        payload = json.loads(result.stdout)
        blocking = payload.get("assessment", {}).get("ingest_decision", {}).get("blocking_issues") or []
        if not payload.get("ready_for_confirm") or blocking:
            raise RuntimeError(f"slide-library rejected generated deck.zip: {blocking}")
        return {
            "ok": True,
            "package_flavor": payload.get("package_flavor"),
            "slide_count": len(payload.get("slides") or []),
            "closure": manifest["asset_closure"],
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = verify_contract(args.library_root.resolve())
    except (FileNotFoundError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
