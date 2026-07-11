"""End-to-end contract tests for PPT-derived Template Pack rendering."""

from __future__ import annotations

import json
import importlib.util
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


HERE = Path(__file__).resolve().parent
DECK_JSON = HERE.parent
RENDERER = DECK_JSON / "render-deck.py"
PREVIEW = DECK_JSON / "preview-slide.py"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PREVIEW_MODULE = _load_module("_template_preview_attrs", PREVIEW)


def _pack(root: Path, *, status: str = "approved") -> Path:
    pack_dir = root / "input" / "runtime-library" / "template-pack"
    assets = pack_dir / "assets"
    assets.mkdir(parents=True)
    (assets / "brand.png").write_bytes(b"\x89PNG\r\n\x1a\nfixture")
    payload = {
        "schema_version": "1.0",
        "template_id": "customer-wide",
        "version": "1.0.0",
        "status": status,
        "source": {"path": "fixture.pptx"},
        "canvas": {
            "source_width_emu": 14630400,
            "source_height_emu": 2743200,
            "aspect_ratio": {"label": "16:3", "value": 16 / 3},
            "recommended_design_canvas": {
                "width": 1920,
                "height": 360,
                "policy": "preserve-source-aspect-ratio",
            },
        },
        "tokens": {
            "colors": [{
                "token": "dk1",
                "value": {"kind": "rgb", "value": "101828", "transforms": []},
            }],
            "fonts": [],
            "typography": [],
            "source_policy": "exact-ooxml-facts-no-normalization",
        },
        "brand": {},
        "layouts": {
            "role-cover": {
                "semantic_role": "cover",
                "fixed_elements": [{
                    "id": "brand",
                    "shape_type": "picture",
                    "src": "assets/brand.png",
                    "geometry": {"x": 40, "y": 24, "w": 120, "h": 48},
                    "z_index": 2,
                    "content_plane": "foreground",
                    "fixed_by_source": True,
                }],
                "slots": [
                    {
                        "id": "title",
                        "semantic_name": "title",
                        "geometry": {"x": 160, "y": 110, "w": 1500, "h": 110},
                        "style": {
                            "font_family": "Aptos, sans-serif",
                            "font_size": 88,
                            "font_size_pt": 44,
                            "font_weight": 700,
                            "color": "theme:dk1",
                            "alignment": "left",
                        },
                    },
                    {
                        "id": "author",
                        "semantic_name": "author",
                        "geometry": {"x": 160, "y": 286, "w": 880, "h": 48},
                        "style": {"font_size": 20, "color": "theme:dk1"},
                    },
                ],
                "safe_area": {
                    "status": "candidate",
                    "geometry": {"x": 160, "y": 110, "w": 1500, "h": 180},
                },
                "source": {},
                "status": "native",
                "confidence": 1.0,
            },
        },
        "layout_coverage": {
            "cover": {"status": "native", "layout_id": "role-cover", "source": {}, "confidence": 1.0},
            "raw": {"status": "unsupported", "source": {}, "confidence": 1.0},
            "section": {"status": "unsupported", "source": {}, "confidence": 1.0},
            "quote": {"status": "unsupported", "source": {}, "confidence": 1.0},
            "agenda": {"status": "unsupported", "source": {}, "confidence": 1.0},
            "end": {"status": "unsupported", "source": {}, "confidence": 1.0},
        },
        "policies": {"missing_layout_behavior": "block"},
        "extraction_report": {},
    }
    path = pack_dir / "template-pack.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _deck(root: Path, *, layout: str = "cover") -> Path:
    out = root / "output"
    out.mkdir(parents=True)
    data = (
        {"title": "企业模板标题", "author": "Jason", "date": "2026.07.11"}
        if layout == "cover"
        else {"quote": {"lead": "模板", "accent": "不能", "tail": "静默降级"}, "attribution": "测试"}
    )
    payload = {
        "version": "1.0",
        "deck": {
            "title": "Template integration",
            "canvas": {
                "width": 1920,
                "height": 360,
                "source_width_emu": 14630400,
                "source_height_emu": 2743200,
                "aspect_ratio": "16:3",
            },
            "template_ref": {
                "id": "customer-wide",
                "version": "1.0.0",
                "path": "../input/runtime-library/template-pack/template-pack.json",
                "mode": "strict",
            },
        },
        "slides": [{"key": "opening", "layout": layout, "data": data}],
    }
    path = out / "deck.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _render(deck: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(RENDERER),
            str(deck),
            str(deck.parent),
            "--skip-validate-html",
            "--skip-copy-assets",
            *extra,
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_existing_cover_layout_receives_pack_vi_slots_and_wide_canvas(tmp_path: Path):
    _pack(tmp_path)
    deck = _deck(tmp_path)
    result = _render(deck, "--quick")
    assert result.returncode == 0, result.stdout + result.stderr
    output = (deck.parent / "index.html").read_text(encoding="utf-8")
    assert 'data-layout="cover"' in output
    assert 'data-template-id="customer-wide"' in output
    assert 'data-template-layout-id="role-cover"' in output
    assert 'data-deck-width="1920"' in output
    assert 'data-deck-height="360"' in output
    assert "../input/runtime-library/template-pack/assets/brand.png" in output
    assert "font-size:88px !important" in output
    assert "color:#101828 !important" in output
    assert "> .wordmark{display:none !important;}" in output
    assert 'class="fs-template-fixed-layer" data-allow-dual-anchor' in output
    assert 'data-template-fixed-layer="background"' in output
    assert 'data-template-fixed-layer="foreground"' in output
    assert 'data-template-fixed-layer="background"]{z-index:-1 !important;}' in output
    assert 'data-template-fixed-layer="foreground"]{z-index:1000 !important;}' in output
    assert output.index('data-template-fixed-layer="background"') < output.index(
        'data-template-fixed-layer="foreground"'
    )


def test_strict_binding_reports_each_authored_field_without_a_slot(tmp_path: Path):
    _pack(tmp_path)
    deck = _deck(tmp_path)
    authored = json.loads(deck.read_text(encoding="utf-8"))
    authored["slides"][0]["data"]["subtitle"] = "这个字段不能落回默认飞书位置"
    deck.write_text(json.dumps(authored, ensure_ascii=False), encoding="utf-8")

    result = _render(deck, "--quick")
    assert result.returncode == 2
    assert "no corresponding slot for authored field" in result.stderr
    assert "data.subtitle" in result.stderr
    assert "requested role 'cover'" in result.stderr
    assert "layout 'role-cover'" in result.stderr


def test_template_cover_can_omit_default_author_and_date_when_slots_do_not_exist(tmp_path: Path):
    pack = _pack(tmp_path)
    payload = json.loads(pack.read_text(encoding="utf-8"))
    payload["layouts"]["role-cover"]["slots"] = [
        slot for slot in payload["layouts"]["role-cover"]["slots"]
        if slot["semantic_name"] == "title"
    ]
    pack.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    deck = _deck(tmp_path)
    authored = json.loads(deck.read_text(encoding="utf-8"))
    authored["slides"][0]["data"] = {"title": "只有标题的企业封面"}
    deck.write_text(json.dumps(authored, ensure_ascii=False), encoding="utf-8")

    result = _render(deck, "--quick")
    assert result.returncode == 0, result.stdout + result.stderr
    output = (deck.parent / "index.html").read_text(encoding="utf-8")
    assert "只有标题的企业封面" in output


@pytest.mark.parametrize(
    ("role", "data", "slot_name"),
    [
        ("section", {"title": "只有标题的章节页"}, "title"),
        (
            "quote",
            {"quote": {"lead": "只保留", "accent": "金句", "tail": "正文"}},
            "quote",
        ),
    ],
)
def test_template_ceremonial_pages_can_omit_default_only_fields(
    tmp_path: Path, role: str, data: dict, slot_name: str,
):
    pack = _pack(tmp_path)
    payload = json.loads(pack.read_text(encoding="utf-8"))
    layout_id = f"role-{role}"
    payload["layouts"][layout_id] = {
        "semantic_role": role,
        "fixed_elements": [],
        "slots": [{
            "id": slot_name,
            "semantic_name": slot_name,
            "geometry": {"x": 160, "y": 80, "w": 1500, "h": 180},
            "style": {"font_size": 72, "color": "theme:dk1"},
        }],
        "safe_area": {
            "status": "candidate",
            "geometry": {"x": 160, "y": 80, "w": 1500, "h": 180},
        },
        "source": {},
        "status": "native",
        "confidence": 1.0,
    }
    payload["layout_coverage"][role] = {
        "status": "native",
        "layout_id": layout_id,
        "source": {},
        "confidence": 1.0,
    }
    pack.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    deck = _deck(tmp_path)
    authored = json.loads(deck.read_text(encoding="utf-8"))
    authored["slides"] = [{"key": f"only-{role}", "layout": role, "data": data}]
    deck.write_text(json.dumps(authored, ensure_ascii=False), encoding="utf-8")
    result = _render(deck, "--quick")
    assert result.returncode == 0, result.stdout + result.stderr


def test_strict_raw_safe_area_does_not_silently_replace_a_content_slot(tmp_path: Path):
    pack = _pack(tmp_path)
    payload = json.loads(pack.read_text(encoding="utf-8"))
    payload["layouts"]["role-raw"] = {
        "semantic_role": "raw",
        "fixed_elements": [],
        "slots": [],
        "safe_area": {
            "status": "candidate",
            "geometry": {"x": 120, "y": 60, "w": 1680, "h": 260},
        },
        "source": {},
        "status": "native",
        "confidence": 1.0,
    }
    payload["layout_coverage"]["raw"] = {
        "status": "native", "layout_id": "role-raw", "source": {}, "confidence": 1.0,
    }
    pack.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    deck = _deck(tmp_path)
    authored = json.loads(deck.read_text(encoding="utf-8"))
    authored["slides"] = [{
        "key": "body", "layout": "raw",
        "data": {"html": '<div class="stage">必须进入内容槽位</div>'},
    }]
    deck.write_text(json.dumps(authored, ensure_ascii=False), encoding="utf-8")
    refused = _render(deck, "--quick")
    assert refused.returncode == 2
    assert "data.html" in refused.stderr
    assert "requested role 'raw'" in refused.stderr

    payload["layouts"]["role-raw"]["slots"] = [{
        "id": "content", "semantic_name": "content",
        "geometry": {"x": 120, "y": 60, "w": 1680, "h": 260},
    }]
    pack.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    accepted = _render(deck, "--quick")
    assert accepted.returncode == 0, accepted.stdout + accepted.stderr


def test_final_render_refuses_draft_even_if_deck_requests_allow_draft(tmp_path: Path):
    pack = _pack(tmp_path, status="draft")
    payload = json.loads(pack.read_text(encoding="utf-8"))
    pack.write_text(json.dumps(payload), encoding="utf-8")
    deck = _deck(tmp_path)
    authored = json.loads(deck.read_text(encoding="utf-8"))
    authored["deck"]["template_ref"]["allow_draft"] = True
    deck.write_text(json.dumps(authored), encoding="utf-8")
    result = _render(deck, "--final")
    assert result.returncode == 2
    assert "final render requires status='approved'" in result.stderr


def test_draft_preview_requires_explicit_opt_in(tmp_path: Path):
    _pack(tmp_path, status="draft")
    deck = _deck(tmp_path)
    refused = _render(deck, "--quick")
    assert refused.returncode == 2
    assert "allow_draft=true" in refused.stderr

    authored = json.loads(deck.read_text(encoding="utf-8"))
    authored["deck"]["template_ref"]["allow_draft"] = True
    deck.write_text(json.dumps(authored), encoding="utf-8")
    preview = _render(deck, "--quick")
    assert preview.returncode == 0, preview.stdout + preview.stderr


def test_strict_binding_refuses_role_explicitly_marked_unsupported(tmp_path: Path):
    _pack(tmp_path)
    deck = _deck(tmp_path, layout="quote")
    result = _render(deck, "--quick")
    assert result.returncode == 2
    assert "layout_coverage.quote" in result.stderr
    assert "unsupported" in result.stderr


def test_pack_canvas_must_match_deck_canvas(tmp_path: Path):
    _pack(tmp_path)
    deck = _deck(tmp_path)
    authored = json.loads(deck.read_text(encoding="utf-8"))
    authored["deck"]["canvas"]["height"] = 1080
    authored["deck"]["canvas"]["aspect_ratio"] = "16:9"
    deck.write_text(json.dumps(authored), encoding="utf-8")
    result = _render(deck, "--quick")
    assert result.returncode == 2
    assert "does not match Template Pack canvas" in result.stderr


def test_alias_reuses_fixed_shell_but_binds_native_end_content_semantics(tmp_path: Path):
    pack = _pack(tmp_path)
    payload = json.loads(pack.read_text(encoding="utf-8"))
    payload["layout_coverage"]["end"] = {
        "status": "alias",
        "alias_to": "cover",
        "source": {
            "kind": "alias",
            "declared_target": "cover",
            "resolved_layout_id": "role-cover",
        },
        "confidence": 1.0,
    }
    payload["layouts"]["role-cover"]["slots"].append({
        "id": "subtitle",
        "semantic_name": "subtitle",
        "geometry": {"x": 160, "y": 240, "w": 1200, "h": 52},
        "style": {"font_size": 28, "font_weight": 400, "color": "theme:dk1"},
    })
    pack.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    deck = _deck(tmp_path)
    authored = json.loads(deck.read_text(encoding="utf-8"))
    authored["slides"] = [{
        "key": "closing",
        "layout": "end",
        "data": {"slogan": "感谢聆听", "contact": "contact@example.com"},
    }]
    deck.write_text(json.dumps(authored, ensure_ascii=False), encoding="utf-8")

    result = _render(deck, "--quick")
    assert result.returncode == 0, result.stdout + result.stderr
    output = (deck.parent / "index.html").read_text(encoding="utf-8")
    assert 'data-template-role="end"' in output
    assert 'data-template-layout-id="role-cover"' in output
    scope = '.slide[data-slide-key="closing"][data-template-id="customer-wide"]'
    assert f"{scope} > .slogan{{" in output
    assert f"{scope} > .contact{{" in output
    assert ">感谢聆听</div>" in output
    assert ">contact@example.com</div>" in output
    assert f"{scope} .stage .title-zh" not in output


def test_preview_template_provenance_attributes_are_html_escaped():
    attrs = PREVIEW_MODULE._template_root_attrs(SimpleNamespace(
        template_id='customer"<&',
        version='1.0.0+build"<&',
        status='approved"<&',
    ))
    assert "&amp;quot;" not in attrs
    assert 'data-template-id="customer&quot;&lt;&amp;"' in attrs
    assert 'data-template-version="1.0.0+build&quot;&lt;&amp;"' in attrs
    assert 'data-template-status="approved&quot;&lt;&amp;"' in attrs
    assert 'customer"<&' not in attrs


def test_single_slide_preview_validates_only_the_selected_template_role(tmp_path: Path):
    _pack(tmp_path)
    deck = _deck(tmp_path)
    authored = json.loads(deck.read_text(encoding="utf-8"))
    authored["slides"].append({
        "key": "unsupported-later",
        "layout": "quote",
        "data": {
            "quote": {"lead": "这页", "accent": "尚未映射", "tail": ""},
            "attribution": "review",
        },
    })

    renderer = PREVIEW_MODULE._load_renderer()
    with pytest.raises(Exception, match=r"layout_coverage\.quote"):
        renderer.load_template_context(
            authored,
            deck_path=deck,
            output_dir=deck.parent,
            final=False,
        )

    scoped = PREVIEW_MODULE._single_slide_deck(authored, authored["slides"][0])
    context = renderer.load_template_context(
        scoped,
        deck_path=deck,
        output_dir=deck.parent,
        final=False,
    )
    assert context is not None
    assert set(context["bindings"]) == {"opening"}
    assert len(authored["slides"]) == 2


def test_template_browser_preserves_slots_and_fixed_layer_z_planes(tmp_path: Path):
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        pytest.skip("playwright not installed")

    pack = _pack(tmp_path)
    payload = json.loads(pack.read_text(encoding="utf-8"))
    payload["layouts"]["role-cover"]["fixed_elements"].extend([
        {
            "id": "background-probe",
            "shape_type": "rectangle",
            "geometry": {"x": 20, "y": 240, "w": 100, "h": 90},
            "style": {"fill": "#0057FF"},
            # A high PPT z-index is not enough to call this foreground: it may
            # still be below a later content placeholder in the same tree.
            "z_index": 99,
        },
        {
            "id": "foreground-probe",
            "shape_type": "rectangle",
            "geometry": {"x": 220, "y": 240, "w": 100, "h": 90},
            "style": {"fill": "#FF3B30"},
            "z_index": 1,
            "content_plane": "foreground",
        },
    ])
    pack.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    deck = _deck(tmp_path)
    result = _render(deck, "--quick")
    assert result.returncode == 0, result.stdout + result.stderr
    rendered = deck.parent / "index.html"

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1920, "height": 360})
            page.goto(rendered.as_uri() + "?mode=present", wait_until="domcontentloaded")
            page.wait_for_function("() => document.querySelector('.deck[data-js-ready]')")
            page.wait_for_timeout(250)
            state = page.evaluate("""() => {
              const slide = document.querySelector('.slide[data-template-id]');
              const title = slide.querySelector('.title-zh');
              const sr = slide.getBoundingClientRect();
              const tr = title.getBoundingClientRect();
              const bgLayer = slide.querySelector('[data-template-fixed-layer="background"]');
              const fgLayer = slide.querySelector('[data-template-fixed-layer="foreground"]');
              for (const el of slide.querySelectorAll('.fs-template-fixed-layer, .fs-template-fixed')) {
                el.style.pointerEvents = 'auto';
              }
              return {
                balanced: slide.hasAttribute('data-fs-balanced'),
                canvasCentered: slide.hasAttribute('data-fs-canvascentered'),
                titleTop: Math.round(tr.top - sr.top),
                backgroundZ: getComputedStyle(bgLayer).zIndex,
                foregroundZ: getComputedStyle(fgLayer).zIndex,
                backgroundHit: document.elementFromPoint(60, 280)?.getAttribute('data-template-fixed-id'),
                foregroundHit: document.elementFromPoint(260, 280)?.getAttribute('data-template-fixed-id'),
              };
            }""")
            browser.close()
    except Exception as exc:
        pytest.skip(f"chromium unavailable: {exc}")

    assert state["balanced"] is False
    assert state["canvasCentered"] is False
    assert state["titleTop"] == pytest.approx(110, abs=1)
    assert state["backgroundZ"] == "-1"
    assert state["foregroundZ"] == "1000"
    assert state["backgroundHit"] != "background-probe"
    assert state["foregroundHit"] == "foreground-probe"


def test_interleaved_source_plane_requires_review_in_strict_mode(tmp_path: Path):
    pack = _pack(tmp_path)
    payload = json.loads(pack.read_text(encoding="utf-8"))
    payload["layouts"]["role-cover"]["fixed_elements"][0].pop("content_plane")
    payload["layouts"]["role-cover"]["fixed_elements"][0]["source_stack_plane"] = "interleaved"
    pack.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    deck = _deck(tmp_path)

    refused = _render(deck, "--quick")
    assert refused.returncode == 2
    assert "source_stack_plane='interleaved'" in refused.stderr
    assert "content_plane/stack_plane" in refused.stderr
    assert "brand" in refused.stderr

    authored = json.loads(deck.read_text(encoding="utf-8"))
    authored["deck"]["template_ref"]["mode"] = "flexible"
    deck.write_text(json.dumps(authored, ensure_ascii=False), encoding="utf-8")
    preview = _render(deck, "--quick")
    assert preview.returncode == 0, preview.stdout + preview.stderr
    output = (deck.parent / "index.html").read_text(encoding="utf-8")
    foreground_layer = (
        '<div class="fs-template-fixed-layer" data-allow-dual-anchor '
        'data-template-fixed-layer="foreground"'
    )
    assert 'data-template-fixed-layer="background" data-template-stack-status="interleaved"' in output
    assert output.index('data-template-stack-status="interleaved"') < output.index(
        'data-template-fixed-id="brand"'
    ) < output.index(foreground_layer)

    payload["layouts"]["role-cover"]["fixed_elements"][0]["content_plane"] = "foreground"
    pack.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    authored["deck"]["template_ref"]["mode"] = "strict"
    deck.write_text(json.dumps(authored, ensure_ascii=False), encoding="utf-8")
    approved = _render(deck, "--quick")
    assert approved.returncode == 0, approved.stdout + approved.stderr
    output = (deck.parent / "index.html").read_text(encoding="utf-8")
    assert output.index(foreground_layer) < output.index(
        'data-template-fixed-id="brand"'
    )


def test_fixed_layer_cannot_inject_active_markup_or_escape_style(tmp_path: Path):
    pack = _pack(tmp_path)
    payload = json.loads(pack.read_text(encoding="utf-8"))
    payload["layouts"]["role-cover"]["fixed_html"] = "<script>alert(1)</script>"
    pack.write_text(json.dumps(payload), encoding="utf-8")
    deck = _deck(tmp_path)
    result = _render(deck, "--quick")
    assert result.returncode == 2
    assert "active markup" in result.stderr

    payload["layouts"]["role-cover"].pop("fixed_html")
    payload["layouts"]["role-cover"]["fixed_css"] = "</style><script>alert(1)</script>"
    pack.write_text(json.dumps(payload), encoding="utf-8")
    result = _render(deck, "--quick")
    assert result.returncode == 2
    assert "active/escaping content" in result.stderr


def test_normal_copy_assets_materialises_pack_relative_media(tmp_path: Path):
    run = tmp_path / "runs" / "job"
    _pack(run)
    deck = _deck(run)
    result = subprocess.run(
        [
            sys.executable,
            str(RENDERER),
            str(deck),
            str(deck.parent),
            "--skip-validate-html",
            "--quick",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    copied = (
        deck.parent / "input" / "runtime-library" / "template-pack" / "assets" / "brand.png"
    )
    assert copied.is_file()
    output = (deck.parent / "index.html").read_text(encoding="utf-8")
    assert 'src="input/runtime-library/template-pack/assets/brand.png"' in output
