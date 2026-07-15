import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ASSET_FAAS = ROOT / "assets" / "magic-asset-faas.py"


class MagicAssetFaasTest(unittest.TestCase):
    def test_magic_tos_assets_are_rewritten_to_closed_binary_proxy(self) -> None:
        with tempfile.TemporaryDirectory(prefix="magic-asset-faas-") as td:
            tmp = Path(td)
            first = "https://magic-builder.tos-cn-beijing.volces.com/deck/logo.png"
            second = "https://magic-builder.tos-cn-beijing.volces.com/deck/bg.jpg"
            html = tmp / "index.html"
            html.write_text(
                f'<img src="{first}"><style>.hero{{background:url("{second}")}}</style>',
                encoding="utf-8",
            )
            out = tmp / "out.html"
            report = tmp / "report.json"
            proc = subprocess.run(
                [
                    sys.executable,
                    str(ASSET_FAAS),
                    str(html),
                    "--out",
                    str(out),
                    "--report",
                    str(report),
                    "--base-url",
                    "https://magic.example.test",
                    "--dry-run",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
            rendered = out.read_text(encoding="utf-8")
            self.assertNotIn(first, rendered)
            self.assertNotIn(second, rendered)
            self.assertEqual(rendered.count("https://magic.example.test/api/faas/"), 2)
            payload = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(payload["rewritten"], 2)
            self.assertTrue(payload["faas"]["dry_run"])
            self.assertEqual(len(payload["faas_shards"]), 2)
            self.assertEqual(
                {row["content_type"] for row in payload["assets"]},
                {"image/png", "image/jpeg"},
            )

            second_run = subprocess.run(
                [
                    sys.executable,
                    str(ASSET_FAAS),
                    str(html),
                    "--out",
                    str(out),
                    "--report",
                    str(report),
                    "--base-url",
                    "https://magic.example.test",
                    "--dry-run",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
            self.assertEqual(second_run.returncode, 0, second_run.stderr or second_run.stdout)
            reused = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(reused["reused_shards"], 2)
            self.assertEqual(reused["published_shards"], 0)
            self.assertTrue(all(row["reused"] for row in reused["faas_shards"]))

    def test_non_magic_urls_are_left_untouched_without_publishing_faas(self) -> None:
        with tempfile.TemporaryDirectory(prefix="magic-asset-faas-noop-") as td:
            tmp = Path(td)
            html = tmp / "index.html"
            html.write_text('<img src="https://cdn.example.test/logo.png">', encoding="utf-8")
            out = tmp / "out.html"
            report = tmp / "report.json"
            proc = subprocess.run(
                [
                    sys.executable,
                    str(ASSET_FAAS),
                    str(html),
                    "--out",
                    str(out),
                    "--report",
                    str(report),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
            self.assertEqual(out.read_text(encoding="utf-8"), html.read_text(encoding="utf-8"))
            self.assertEqual(json.loads(report.read_text(encoding="utf-8"))["rewritten"], 0)

    def test_prior_proxy_report_can_be_reversed_and_resharded(self) -> None:
        with tempfile.TemporaryDirectory(prefix="magic-asset-faas-reshard-") as td:
            tmp = Path(td)
            key = "0123456789abcdef0123"
            upstream = "https://magic-builder.tos-cn-beijing.volces.com/deck/logo.png"
            old_proxy = f"https://magic.solutionsuite.cn/api/faas/old?a={key}"
            html = tmp / "index.html"
            html.write_text(f'<img src="{old_proxy}">', encoding="utf-8")
            prior = tmp / "prior.json"
            prior.write_text(
                json.dumps({"assets": [{"key": key, "url": upstream}]}, ensure_ascii=False),
                encoding="utf-8",
            )
            out = tmp / "out.html"
            report = tmp / "report.json"
            proc = subprocess.run(
                [
                    sys.executable,
                    str(ASSET_FAAS),
                    str(html),
                    "--out",
                    str(out),
                    "--report",
                    str(report),
                    "--source-report",
                    str(prior),
                    "--base-url",
                    "https://magic.example.test",
                    "--dry-run",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
            rendered = out.read_text(encoding="utf-8")
            self.assertNotIn(old_proxy, rendered)
            self.assertNotIn(upstream, rendered)
            self.assertIn("https://magic.example.test/api/faas/", rendered)


if __name__ == "__main__":
    unittest.main()
