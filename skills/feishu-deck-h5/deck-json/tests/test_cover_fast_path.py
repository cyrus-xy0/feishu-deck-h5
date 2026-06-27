import importlib.util
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parents[1]


def _load_fast_path():
    spec = importlib.util.spec_from_file_location(
        "_new_cover_deck", SKILL_ROOT / "assets" / "new-cover-deck.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class NewCoverDeckFastPathTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load_fast_path()

    def test_cover_title_splits_chinese_colon(self):
        self.assertEqual(
            self.mod.default_cover_title("让 AI 进入组织：从工具到同事"),
            "让 AI 进入组织：\n从工具到同事",
        )

    def test_cover_title_keeps_explicit_newline(self):
        self.assertEqual(self.mod.default_cover_title("第一行\n第二行"), "第一行\n第二行")

    def test_normalize_iso_date_accepts_dotted_date(self):
        self.assertEqual(self.mod.normalize_iso_date("2026.6.28"), "2026-06-28")
        self.assertEqual(self.mod.normalize_iso_date("2026-06-28"), "2026-06-28")

    def test_delivery_name_uses_lark_convention(self):
        self.assertEqual(
            self.mod.delivery_name("ai-into-org", "2026-06-28"),
            "lark-ai-into-org-2026-06-28",
        )

    def test_slug_inference_keeps_ascii_words(self):
        self.assertEqual(self.mod.infer_slug("让 AI 进入组织：从工具到同事"), "ai")
        self.assertEqual(self.mod.infer_slug("纯中文标题"), "cover-deck")


if __name__ == "__main__":
    unittest.main()
