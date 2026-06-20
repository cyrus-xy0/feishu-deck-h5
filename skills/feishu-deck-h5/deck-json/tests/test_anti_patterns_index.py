"""Anti-pattern index honesty gate (#5).

`references/anti-patterns.md` is the single-source index of recurring
anti-patterns. Each row's «执行通道» column may name a concrete `R-*` validator
rule as the machine gate that enforces it. This test parses every `R-*` token
appearing in that column and asserts it is a REAL rule in the validate engine —
so the index can never claim a rule that does not exist (a renamed/retired rule
in the index would silently become a lie about what is enforced).

Mechanism mirrors `assets/check-rule-coverage.py`: load `assets/check-only.py`
via importlib and call `enumerate_validate_rules()` for the engine's full rule
set. Path is resolved relative to this test file (skill root = parents[2]).
The repo's tests use stdlib unittest, not pytest.
"""
import importlib.util
import re
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[2]
ASSETS = SKILL_ROOT / "assets"
INDEX_MD = SKILL_ROOT / "references" / "anti-patterns.md"

# R-* token: uppercase rule codes like R-PROVENANCE, R-VIS-OPT-OUT-ABUSE, R-DOM.
_RULE_TOKEN = re.compile(r"\bR-[A-Z0-9]+(?:-[A-Z0-9]+)*\b")


def _load_engine_rules():
    """Engine rule set, same source as check-rule-coverage.py."""
    spec = importlib.util.spec_from_file_location("check_only", ASSETS / "check-only.py")
    co = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(co)
    return set(co.enumerate_validate_rules())


def _execution_channel_cells(md_text):
    """Yield the «执行通道» (3rd) cell of each anti-pattern table data row.

    The table header order is fixed: | 简名 | 禁令 | 执行通道 | 借口→封死语 | 文件 |.
    A data row is a markdown table line that is NOT the header and NOT the
    `|---|` separator. We skip the header by requiring the cell not to read
    literally '执行通道'.
    """
    for line in md_text.splitlines():
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) < 3:
            continue
        third = cells[2]
        if third in ("执行通道", ""):
            continue
        if set(third) <= {"-", ":"}:  # separator row
            continue
        yield third


class TestAntiPatternsIndex(unittest.TestCase):
    def test_index_file_exists(self):
        self.assertTrue(INDEX_MD.is_file(), f"missing anti-pattern index: {INDEX_MD}")

    def test_referenced_rules_exist_in_engine(self):
        md = INDEX_MD.read_text(encoding="utf-8")
        engine = _load_engine_rules()
        self.assertTrue(engine, "engine rule set came back empty — loader broke")

        referenced = set()
        for cell in _execution_channel_cells(md):
            referenced.update(_RULE_TOKEN.findall(cell))

        # Sanity: the index is supposed to carry real machine gates, so at least
        # one row's channel must be an R-* rule (else the test guards nothing).
        self.assertTrue(
            referenced,
            "no R-* rule found in any 执行通道 cell — index lost its machine "
            "gates, or the column parse broke",
        )

        unknown = sorted(referenced - engine)
        self.assertEqual(
            unknown,
            [],
            "anti-patterns.md 执行通道 references rule(s) that do NOT exist in "
            f"the validate engine: {unknown}. Fix the index: correct the rule "
            "name, or relabel that channel as 人工 / deck-cli / lint. "
            f"(engine has {len(engine)} rules)",
        )


if __name__ == "__main__":
    unittest.main()
