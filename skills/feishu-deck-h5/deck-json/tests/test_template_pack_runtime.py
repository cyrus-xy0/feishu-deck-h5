import copy
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
MODULE_PATH = HERE.parent / "template-pack.py"
SPEC = importlib.util.spec_from_file_location("template_pack_runtime", MODULE_PATH)
tp = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tp)


def canonical_pack(status="approved"):
    return {
        "schema_version": "1.0",
        "template_id": "acme-2026",
        "version": "1.2.0",
        "status": status,
        "source": {"kind": "pptx", "path": "/provenance/may/be/absolute.pptx"},
        "canvas": {"width": 1920, "height": 1080},
        "tokens": {},
        "brand": {},
        "layouts": {
            "cover-main": {
                "semantic_role": "cover",
                "fixed_elements": [],
                "slots": [{"name": "title"}],
                "safe_area": {"x": 120, "y": 180, "width": 1500, "height": 620},
            },
            "body-main": {
                "semantic_role": "raw",
                "fixed_elements": [],
                "slots": [{"name": "content"}],
                "safe_area": {"x": 96, "y": 160, "width": 1728, "height": 800},
            },
            "section-derived": {
                "semantic_role": "section",
                "fixed_elements": [],
                "slots": [{"name": "title"}],
                "safe_area": {"x": 120, "y": 240, "width": 1500, "height": 500},
            },
        },
        "layout_coverage": {
            "cover": {"status": "native", "layout_id": "cover-main"},
            "raw": {"status": "native", "layout_id": "body-main"},
            "section": {
                "status": "derived",
                "layout_id": "section-derived",
                "source_role": "cover",
            },
            "quote": {"status": "unsupported"},
            "agenda": {"status": "alias", "alias_to": "raw"},
            "end": {"status": "alias", "alias_to": "cover"},
        },
        "policies": {"mode": "strict"},
        "extraction_report": {},
    }


class SemanticRoleTest(unittest.TestCase):
    def test_maps_six_roles_and_legacy_body_without_new_layout_enum(self):
        for role in tp.SEMANTIC_ROLES:
            self.assertEqual(tp.semantic_role_for_layout(role), role)
        for layout in ("content", "stats", "flow", "image-text", "table",
                       "logo-wall", "arch-stack", "chart"):
            self.assertEqual(tp.semantic_role_for_layout(layout), "raw")

    def test_mechanism_layouts_bypass_visual_template(self):
        for layout in ("canvas", "replica", "iframe-embed"):
            self.assertIsNone(tp.semantic_role_for_layout(layout))

    def test_unknown_layout_is_not_silently_treated_as_content(self):
        with self.assertRaises(tp.TemplateCoverageError):
            tp.semantic_role_for_layout("invented-business-layout")


class PackStateAndValidationTest(unittest.TestCase):
    def test_draft_allowed_for_preview_but_blocked_for_final(self):
        pack = tp.load_template_pack(canonical_pack("draft"))
        self.assertEqual(pack.status, "draft")
        with self.assertRaises(tp.TemplatePackStateError):
            tp.load_template_pack(canonical_pack("draft"), final=True)
        allowed = tp.load_template_pack(
            canonical_pack("draft"), final=True, allow_draft=True,
        )
        self.assertEqual(allowed.status, "draft")

    def test_approved_pack_passes_final_state_gate(self):
        pack = tp.load_template_pack(canonical_pack(), final=True)
        self.assertEqual(pack.status, "approved")

    def test_unknown_schema_version_and_missing_canvas_are_refused(self):
        raw = canonical_pack()
        raw["schema_version"] = "2.0"
        with self.assertRaises(tp.TemplatePackValidationError):
            tp.load_template_pack(raw)
        raw = canonical_pack()
        raw["canvas"] = {}
        with self.assertRaises(tp.TemplatePackValidationError):
            tp.load_template_pack(raw)

    def test_final_refuses_approved_label_with_unresolved_human_review(self):
        raw = canonical_pack()
        raw["brand"] = {"lock_status": "pending_confirmation"}
        raw["extraction_report"] = {
            "needs_confirmation": ["font availability and embedding rights"],
        }
        with self.assertRaises(tp.TemplatePackStateError):
            tp.load_template_pack(raw, final=True)

        raw["brand"]["lock_status"] = "locked"
        raw["extraction_report"]["needs_confirmation"] = []
        self.assertEqual(tp.load_template_pack(raw, final=True).status, "approved")

    def test_retired_pack_is_readable_for_audit_but_never_final(self):
        pack = tp.load_template_pack(canonical_pack("retired"))
        self.assertEqual(pack.status, "retired")
        with self.assertRaises(tp.TemplatePackStateError):
            tp.load_template_pack(canonical_pack("retired"), final=True)

    def test_strict_audit_reports_unsupported_or_missing_roles(self):
        raw = canonical_pack()
        del raw["layout_coverage"]["section"]
        issues = tp.validate_template_pack(raw, strict=True)
        paths = {
            issue.path for issue in issues if issue.code == "TP-STRICT-COVERAGE"
        }
        self.assertIn("layout_coverage.quote", paths)
        self.assertIn("layout_coverage.section", paths)

    def test_incomplete_pack_remains_loadable_until_missing_role_is_needed(self):
        pack = tp.load_template_pack(canonical_pack())
        cover = tp.build_slide_binding(
            pack, {"key": "cover", "layout": "cover"},
        )
        self.assertTrue(cover["active"])
        with self.assertRaises(tp.TemplateCoverageError):
            tp.build_slide_binding(pack, {"key": "q", "layout": "quote"})
        inactive = tp.build_slide_binding(
            pack, {"key": "q", "layout": "quote"}, strict=False,
        )
        self.assertFalse(inactive["active"])
        self.assertEqual(inactive["reason"], "coverage-unsupported")

    def test_layouts_array_is_accepted_for_extractor_compatibility(self):
        raw = canonical_pack()
        raw["layouts"] = [
            dict(layout, layout_id=layout_id)
            for layout_id, layout in raw["layouts"].items()
        ]
        pack = tp.load_template_pack(raw)
        self.assertIn("body-main", pack.layouts)


class CoverageResolutionTest(unittest.TestCase):
    def setUp(self):
        self.pack = tp.load_template_pack(canonical_pack())

    def test_native_derived_and_alias_resolve_to_real_layouts(self):
        cover = tp.resolve_coverage(self.pack, "cover")
        self.assertEqual(cover.effective_status, "native")
        self.assertEqual(cover.layout_id, "cover-main")

        section = tp.resolve_coverage(self.pack, "section")
        self.assertEqual(section.effective_status, "derived")
        self.assertEqual(section.derived_from, "cover")

        agenda = tp.resolve_coverage(self.pack, "agenda")
        self.assertEqual(agenda.declared_status, "alias")
        self.assertEqual(agenda.resolved_role, "raw")
        self.assertEqual(agenda.layout_id, "body-main")
        self.assertEqual(agenda.alias_chain, ("agenda", "raw"))

    def test_layout_override_lookup_maps_legacy_body_to_raw(self):
        layout = tp.get_layout_override(self.pack, "stats")
        self.assertEqual(layout["layout_id"], "body-main")
        self.assertEqual(layout["semantic_role"], "raw")

    def test_slide_can_pin_an_alternate_layout_for_the_same_role(self):
        raw = canonical_pack()
        raw["layouts"]["cover-alt"] = {
            "semantic_role": "cover",
            "fixed_elements": [],
            "slots": [{"name": "title"}],
            "safe_area": {"x": 80, "y": 80, "width": 1600, "height": 700},
        }
        pack = tp.load_template_pack(raw)
        binding = tp.build_slide_binding(pack, {
            "key": "opening",
            "layout": "cover",
            "template_layout_id": "cover-alt",
        })
        self.assertEqual(binding["layout_id"], "cover-alt")

    def test_slide_cannot_pin_a_layout_owned_by_another_role(self):
        with self.assertRaises(tp.TemplateCoverageError):
            tp.build_slide_binding(self.pack, {
                "key": "opening",
                "layout": "cover",
                "template_layout_id": "body-main",
            })

    def test_alias_cycle_is_a_structural_error_even_without_strict_audit(self):
        raw = canonical_pack()
        raw["layout_coverage"]["agenda"] = {
            "status": "alias", "alias_to": "end",
        }
        raw["layout_coverage"]["end"] = {
            "status": "alias", "alias_to": "agenda",
        }
        with self.assertRaises(tp.TemplatePackValidationError) as caught:
            tp.load_template_pack(raw)
        self.assertIn("TP-ALIAS-CYCLE", str(caught.exception))

    def test_strict_deck_binding_aggregates_only_roles_the_deck_uses(self):
        # Quote is unsupported in the pack, but a cover + body deck is valid.
        bindings = tp.build_deck_bindings(self.pack, [
            {"key": "c", "layout": "cover"},
            {"key": "b", "layout": "content", "variant": "2col"},
        ])
        self.assertEqual([item["role"] for item in bindings], ["cover", "raw"])
        with self.assertRaises(tp.TemplatePackValidationError) as caught:
            tp.build_deck_bindings(self.pack, [
                {"key": "c", "layout": "cover"},
                {"key": "q", "layout": "quote"},
            ])
        self.assertIn("layout_coverage.quote", str(caught.exception))


class AssetSafetyAndBindingTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="template-pack-test-")
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_rejects_remote_absolute_and_encoded_traversal_refs(self):
        bad = (
            "https://example.com/logo.svg",
            "/etc/passwd",
            "C:\\Windows\\system.ini",
            "..%2fsecret.txt",
            "assets/%252e%252e/secret.txt",
            "data:image/svg+xml,evil",
        )
        for ref in bad:
            with self.subTest(ref=ref):
                with self.assertRaises(tp.UnsafeTemplateAssetError):
                    tp.normalize_asset_ref(ref)

    def test_validation_checks_fixed_element_asset_paths_but_not_source_provenance(self):
        raw = canonical_pack()
        # Absolute source.path is provenance and intentionally ignored.
        self.assertFalse([
            issue for issue in tp.validate_template_pack(raw, base_dir=self.root)
            if issue.code == "TP-ASSET-PATH"
        ])
        raw["layouts"]["cover-main"]["fixed_elements"] = [
            {"type": "image", "src": "../../outside.svg"},
        ]
        issues = tp.validate_template_pack(raw, base_dir=self.root)
        self.assertTrue(any(issue.code == "TP-ASSET-PATH" for issue in issues))

    def test_resolver_rejects_symlink_that_escapes_pack_root(self):
        outside = self.root.parent / f"{self.root.name}-outside.svg"
        outside.write_text("outside", encoding="utf-8")
        try:
            os.symlink(outside, self.root / "logo.svg")
            pack = tp.load_template_pack(canonical_pack(), base_dir=self.root)
            with self.assertRaises(tp.UnsafeTemplateAssetError):
                tp.resolve_pack_asset(pack, "logo.svg", must_exist=True)
        finally:
            outside.unlink(missing_ok=True)

    def test_binding_materialises_fixed_markup_css_and_normalized_assets(self):
        (self.root / "fixed").mkdir()
        (self.root / "assets").mkdir()
        (self.root / "assets" / "logo.svg").write_text("<svg/>", encoding="utf-8")
        (self.root / "assets" / "bg.png").write_bytes(b"PNG")
        (self.root / "fixed" / "cover.html").write_text(
            '<div class="brand"><img src="assets/logo.svg" alt=""></div>',
            encoding="utf-8",
        )
        (self.root / "fixed" / "cover.css").write_text(
            '.brand{background-image:url("assets/bg.png")}',
            encoding="utf-8",
        )

        raw = canonical_pack()
        raw["layouts"]["cover-main"]["fixed_layer"] = {
            "html_path": "fixed/cover.html",
            "css_path": "fixed/cover.css",
        }
        raw["layouts"]["cover-main"]["fixed_elements"] = [
            {"type": "image", "src": "assets/logo.svg", "locked": True},
        ]
        pack_file = self.root / "template-pack.json"
        pack_file.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        pack = tp.load_template_pack(pack_file, verify_assets=True)
        binding = tp.build_slide_binding(
            pack, {"key": "opening", "layout": "cover"}, final=True,
        )

        self.assertTrue(binding["active"])
        self.assertEqual(binding["layout_id"], "cover-main")
        self.assertIn('class="brand"', binding["fixed_html"])
        self.assertIn("background-image", binding["fixed_css"])
        self.assertEqual(binding["fixed_elements"][0]["locked"], True)
        self.assertEqual(
            set(binding["asset_refs"]),
            {"fixed/cover.html", "fixed/cover.css", "assets/logo.svg", "assets/bg.png"},
        )
        self.assertEqual(binding["data_attrs"]["data-template-role"], "cover")

    def test_mechanism_binding_is_explicitly_inactive(self):
        pack = tp.load_template_pack(canonical_pack(), base_dir=self.root)
        binding = tp.build_slide_binding(
            pack, {"key": "demo", "layout": "iframe-embed"}, final=True,
        )
        self.assertFalse(binding["active"])
        self.assertEqual(binding["reason"], "mechanism-layout")


if __name__ == "__main__":
    unittest.main()
