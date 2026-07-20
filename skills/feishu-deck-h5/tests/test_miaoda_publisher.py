from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PUBLISHER = ROOT / "subskills" / "miaoda-publisher" / "publish.py"


def load_publisher():
    spec = importlib.util.spec_from_file_location("miaoda_publisher", PUBLISHER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PUBLISH = load_publisher()


def make_fake_cli(path: Path) -> Path:
    cli = path / "lark-cli"
    cli.write_text(
        """#!/usr/bin/env python3
import json
import sys
from pathlib import Path

args = sys.argv[1:]
if "+html-publish" in args:
    site = args[args.index("--path") + 1]
    root = Path(site)
    files = sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    )
    print(json.dumps({
        "ok": True,
        "data": {
            "file_count": len(files),
            "files": files,
            "path": site,
        },
    }))
else:
    print(json.dumps({"ok": True, "data": {}}))
""",
        encoding="utf-8",
    )
    cli.chmod(0o755)
    return cli


def test_dry_run_materializes_shared_symlink_without_touching_live_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source_root = tmp_path / "runs" / "source"
    output = source_root / "output"
    output.mkdir(parents=True)
    (source_root / "input").mkdir()
    (source_root / "input" / "nested.jpg").write_bytes(b"nested")
    canonical = ROOT / "assets" / "shared"
    shared_file = next(path for path in canonical.rglob("*") if path.is_file())
    relative = shared_file.relative_to(canonical)
    (output / "assets").mkdir()
    (output / "assets" / "shared").symlink_to(canonical, target_is_directory=True)
    legacy = output / "legacy-bundle"
    legacy.mkdir()
    (legacy / "photo.png").write_bytes(b"legacy")
    prototype = output / "prototypes" / "nested"
    prototype.mkdir(parents=True)
    (prototype / "index.html").write_text(
        '<img src="../../input/nested.jpg">',
        encoding="utf-8",
    )
    (output / "index.html").write_text(
        (
            "<!doctype html><html><head><title>Deck</title></head><body>"
            f'<img src="assets/shared/{relative.as_posix()}">'
            '<img src="legacy-bundle/photo.png">'
            '<iframe src="prototypes/nested/index.html"></iframe>'
            "</body></html>"
        ),
        encoding="utf-8",
    )

    catalog_root = tmp_path / "catalog-root"
    monkeypatch.setattr(
        PUBLISH,
        "capture_catalog_cover",
        lambda _site, destination: (
            destination.parent.mkdir(parents=True, exist_ok=True),
            destination.write_bytes(b"jpeg-cover"),
        ),
    )
    result = PUBLISH.main(
        [
            "--html",
            str(output / "index.html"),
            "--slug",
            "shared-link",
            "--catalog-root",
            str(catalog_root),
            "--lark-cli",
            str(make_fake_cli(tmp_path)),
            "--dry-run",
        ]
    )

    assert result == 0
    manifest = json.loads(capsys.readouterr().out)
    assert manifest["status"] == "dry-run"
    staged = catalog_root / ".dry-run" / "shared-link"
    copied = staged / "decks" / "shared-link" / "site" / "assets" / "shared" / relative
    assert copied.is_file()
    assert not copied.is_symlink()
    assert (
        staged
        / "decks"
        / "shared-link"
        / "site"
        / "legacy-bundle"
        / "photo.png"
    ).is_file()
    assert (
        staged
        / "decks"
        / "shared-link"
        / "site"
        / "input"
        / "nested.jpg"
    ).is_file()
    catalog_site = staged / "catalog" / "site"
    assert (catalog_site / "assets" / "lark-cover-bg.jpg").is_file()
    assert (catalog_site / "assets" / "lark-logo.png").is_file()
    assert (catalog_site / "covers" / "shared-link.jpg").read_bytes() == b"jpeg-cover"
    catalog_html = (catalog_site / "index.html").read_text(encoding="utf-8")
    assert 'url("assets/lark-cover-bg.jpg")' in catalog_html
    assert 'src="assets/lark-logo.png"' in catalog_html
    assert 'src="covers/shared-link.jpg"' in catalog_html
    assert "object-fit:contain" in catalog_html
    catalog = json.loads((staged / "catalog" / "catalog.json").read_text(encoding="utf-8"))
    entry = next(item for item in catalog["entries"] if item["slug"] == "shared-link")
    assert entry["cover_content_sha256"] == entry["content_sha256"]
    assert not (catalog_root / "decks").exists()
    assert not (catalog_root / "catalog").exists()


def test_copy_static_tree_rejects_symlinked_file(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    target = tmp_path / "target.png"
    target.write_bytes(b"png")
    (source / "linked.png").symlink_to(target)

    with pytest.raises(PUBLISH.PublishError, match="symlinked resource"):
        PUBLISH.copy_static_tree(source, tmp_path / "destination")


def test_miaoda_readonly_policy_is_staged_and_idempotent(tmp_path: Path) -> None:
    source = tmp_path / "source.html"
    staged = tmp_path / "index.html"
    original = "<!doctype html><html><head><title>Deck</title></head><body></body></html>"
    source.write_text(original, encoding="utf-8")
    staged.write_text(original, encoding="utf-8")

    PUBLISH.apply_miaoda_readonly_policy(staged)
    once = staged.read_text(encoding="utf-8")
    PUBLISH.apply_miaoda_readonly_policy(staged)

    assert source.read_text(encoding="utf-8") == original
    assert staged.read_text(encoding="utf-8") == once
    assert PUBLISH.READONLY_POLICY_META in once
    assert once.count(PUBLISH.READONLY_GUARD_MARKER) == 1
    assert "window.addEventListener('keydown'" in once
    assert "当前为妙搭线上只读版本" in once


def test_miaoda_cover_compatibility_is_explicit_and_idempotent(tmp_path: Path) -> None:
    staged = tmp_path / "index.html"
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "lark-cover-bg.jpg").write_bytes(b"cover-jpg")
    (assets / "lark-logo.png").write_bytes(b"logo-png")
    staged.write_text(
        """<!doctype html><html><head><title>Deck</title></head><body>
<div class="deck">
  <div class="slide-frame">
    <div class="slide" data-layout="cover"><div class="wordmark">飞书</div></div>
  </div>
  <div class="slide-frame">
    <div class="slide" data-layout="content-2col"></div>
  </div>
</div>
</body></html>""",
        encoding="utf-8",
    )

    PUBLISH.apply_miaoda_cover_compatibility(staged)
    once = staged.read_text(encoding="utf-8")
    PUBLISH.apply_miaoda_cover_compatibility(staged)

    assert staged.read_text(encoding="utf-8") == once
    assert once.count(PUBLISH.MIAODA_COVER_COMPAT_MARKER) == 1
    assert (
        '<div class="slide-frame" data-fs-miaoda-cover-frame>'
        in once
    )
    assert (
        '<div class="slide-frame">\n'
        '    <div class="slide" data-layout="content-2col">'
        in once
    )
    assert 'url("data:image/jpeg;base64,Y292ZXItanBn")' in once
    assert 'url("data:image/png;base64,bG9nby1wbmc=")' in once
    assert "__MIAODA_COVER_DATA_URI__" not in once
    assert "__MIAODA_LOGO_DATA_URI__" not in once


def test_miaoda_cover_compatibility_replaces_legacy_external_style(
    tmp_path: Path,
) -> None:
    staged = tmp_path / "index.html"
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "lark-cover-bg.jpg").write_bytes(b"cover-jpg")
    (assets / "lark-logo.png").write_bytes(b"logo-png")
    staged.write_text(
        """<!doctype html><html><head><title>Deck</title>
<style data-fs-miaoda-cover-compat>
.slide[data-layout="cover"] {
  background: url("assets/lark-cover-bg.jpg") center/cover no-repeat;
}
.slide[data-layout="cover"] .wordmark {
  background-image: url("assets/lark-logo.png");
}
</style>
</head><body><div class="deck">
  <div class="slide-frame" data-fs-miaoda-cover-frame>
    <div class="slide" data-layout="cover"><div class="wordmark">飞书</div></div>
  </div>
</div></body></html>""",
        encoding="utf-8",
    )

    PUBLISH.apply_miaoda_cover_compatibility(staged)

    rewritten = staged.read_text(encoding="utf-8")
    assert rewritten.count(PUBLISH.MIAODA_COVER_COMPAT_MARKER) == 1
    assert (
        rewritten.count(
            '<div class="slide-frame" data-fs-miaoda-cover-frame>'
        )
        == 1
    )
    assert (
        "data-fs-miaoda-cover-frame data-fs-miaoda-cover-frame"
        not in rewritten
    )
    assert 'url("data:image/jpeg;base64,Y292ZXItanBn")' in rewritten
    assert 'url("data:image/png;base64,bG9nby1wbmc=")' in rewritten
    assert 'url("assets/lark-cover-bg.jpg")' not in rewritten
    assert 'url("assets/lark-logo.png")' not in rewritten


def test_capture_catalog_cover_writes_jpeg_atomically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deck_site = tmp_path / "deck"
    deck_site.mkdir()
    (deck_site / "index.html").write_text("<html></html>", encoding="utf-8")
    destination = tmp_path / "catalog" / "covers" / "deck.jpg"

    def fake_run(command: list[str], *, cwd: Path, timeout: int = 300):
        output = Path(command[command.index("--out") + 1])
        assert output.suffix == ".jpg"
        assert command[command.index("--viewport") + 1] == "960x540"
        assert "--hide-ui" in command
        output.write_bytes(b"jpeg")

    monkeypatch.setattr(PUBLISH, "run_checked", fake_run)

    PUBLISH.capture_catalog_cover(deck_site, destination)

    assert destination.read_bytes() == b"jpeg"
    assert not list(destination.parent.glob(".*.jpg"))


def test_render_catalog_has_flower_hero_and_full_cover() -> None:
    rendered = PUBLISH.render_catalog(
        [
            {
                "slug": "deck-one",
                "title": "Deck One",
                "description": "",
                "category": "客户交流",
                "published_url": "https://bytedance.feishuapp.com/app/app_deckone",
                "access_scope": "creator",
                "listed": True,
                "cover_image": "covers/deck-one.jpg",
            }
        ],
        "飞书方案演示集",
    )

    assert 'url("assets/lark-cover-bg.jpg")' in rendered
    assert 'src="assets/lark-logo.png"' in rendered
    assert 'src="covers/deck-one.jpg"' in rendered
    assert "object-fit:contain" in rendered
    assert 'href="https://bytedance.feishuapp.com/app/app_deckone/#1"' in rendered


def test_canonical_app_url_adds_required_trailing_slash() -> None:
    root = "https://bytedance.feishuapp.com/app/app_17ag0shqr3t"

    assert PUBLISH.canonical_app_url(root) == root + "/"
    assert PUBLISH.canonical_app_url(root + "/") == root + "/"
    assert PUBLISH.first_slide_url(root) == root + "/#1"


def test_archive_limit_stops_before_lark_cli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "index.html"
    source.write_text(
        "<!doctype html><html><head><title>Deck</title></head><body>Deck</body></html>",
        encoding="utf-8",
    )
    cli_marker = tmp_path / "cli-called"
    cli = tmp_path / "lark-cli"
    cli.write_text(
        (
            "#!/usr/bin/env python3\n"
            "from pathlib import Path\n"
            f"Path({str(cli_marker)!r}).write_text('called')\n"
        ),
        encoding="utf-8",
    )
    cli.chmod(0o755)
    monkeypatch.setattr(PUBLISH, "ARCHIVE_LIMIT", 1)

    result = PUBLISH.main(
        [
            "--html",
            str(source),
            "--title",
            "Deck",
            "--slug",
            "size-gate",
            "--catalog-root",
            str(tmp_path / "catalog"),
            "--lark-cli",
            str(cli),
            "--dry-run",
        ]
    )

    assert result == 1
    assert "Miaoda size gate failed" in capsys.readouterr().err
    assert not cli_marker.exists()


def test_saved_and_explicit_app_ids_must_match(tmp_path: Path) -> None:
    state = tmp_path / "app.json"
    state.write_text('{"app_id":"app_saved"}', encoding="utf-8")

    with pytest.raises(PUBLISH.PublishError, match="app_id mismatch"):
        PUBLISH.ensure_app(
            cli="unused",
            cwd=tmp_path,
            state_path=state,
            override="app_other",
            name="Deck",
            description="Deck",
            dry_run=True,
            fake_id="app_fake",
        )
