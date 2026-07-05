from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_rel(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_raw_header_contract_uses_auto_create_wording() -> None:
    controller = read_rel("SKILL.md")
    renderer = read_rel("subskills/renderer/SKILL.md")

    combined = controller + "\n" + renderer
    assert "raw renders no header" not in combined
    assert "raw renders no `.header`" not in combined
    assert "raw does not auto-create a header" in controller
    assert "raw does not auto-create a\n   `.header`" in renderer


def test_new_body_card_pages_stay_raw_first_in_docs() -> None:
    renderer = read_rel("subskills/renderer/SKILL.md")
    design_first = read_rel("references/design-first.md")

    assert "use `content/3up` or `content/blocks` instead" not in renderer
    assert "回退 `content/3up`" not in design_first
    assert 'still author it as `layout: "raw"`' in renderer
    assert "纯并列 3 卡仍是正文页 → raw 自排" in design_first
