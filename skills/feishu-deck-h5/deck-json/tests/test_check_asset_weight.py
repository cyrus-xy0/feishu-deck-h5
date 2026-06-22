"""Unit tests for check-asset-weight.py (F-366 delivery asset-bloat gate).
Deterministic: builds a temp deck dir with fixed-size dummy files + a hand-written
index.html, then asserts the four finding classes. stdlib only."""
import importlib.util, os, pathlib, sys, tempfile

HERE = pathlib.Path(__file__).resolve().parents[1]  # deck-json/
_spec = importlib.util.spec_from_file_location("check_asset_weight", HERE / "check-asset-weight.py")
caw = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(caw)
MB = 1024 * 1024


def _mk(path, size):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"\0" * size)


def _deck(tmp, html):
    with open(os.path.join(tmp, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)


def test_oversized_image_flagged_small_one_not():
    with tempfile.TemporaryDirectory() as t:
        _mk(os.path.join(t, "assets/big.png"), 3 * MB)
        _mk(os.path.join(t, "assets/ok.png"), 1 * MB)  # under 2MB → not flagged
        _deck(t, '<img src="assets/big.png"><img src="assets/ok.png">')
        f = caw.audit(t)
        rels = [r for r, _ in f["oversized"]]
        assert "assets/big.png" in rels
        assert "assets/ok.png" not in rels


def test_video_oversized_with_video_hint():
    with tempfile.TemporaryDirectory() as t:
        _mk(os.path.join(t, "input/media/clip.mp4"), 5 * MB)
        _deck(t, '<video><source src="input/media/clip.mp4"></video>')
        f = caw.audit(t)
        assert any(r.endswith("clip.mp4") for r, _ in f["oversized"])
        assert "压缩视频" in caw.format_report(f)


def test_embed_whole_subdeck_flagged():
    with tempfile.TemporaryDirectory() as t:
        _mk(os.path.join(t, "assets/custom-lift/src-deck/index.html"), 1024)
        _mk(os.path.join(t, "assets/custom-lift/src-deck/media/raw.png"), 6 * MB)
        _deck(t, '<iframe src="assets/custom-lift/src-deck/index.html#3"></iframe>')
        f = caw.audit(t)
        assert any("src-deck/index.html" in s for s, _ in f["embeds"])
        assert "静态化" in caw.format_report(f)


def test_small_iframe_not_embed():
    with tempfile.TemporaryDirectory() as t:
        _mk(os.path.join(t, "proto/demo/index.html"), 1024)
        _mk(os.path.join(t, "proto/demo/a.png"), 200 * 1024)  # tiny dir
        _deck(t, '<iframe src="proto/demo/index.html"></iframe>')
        f = caw.audit(t)
        assert f["embeds"] == []


def test_orphan_flagged_referenced_not():
    with tempfile.TemporaryDirectory() as t:
        _mk(os.path.join(t, "assets/used.png"), 1024)
        _mk(os.path.join(t, "assets/leftover.mp4"), 3 * MB)   # unreferenced, chunky → orphan
        _mk(os.path.join(t, "assets/tiny-orphan.png"), 100 * 1024)  # unreferenced but <1MB → ignored
        _deck(t, '<img src="assets/used.png">')
        f = caw.audit(t)
        rels = [r for r, _ in f["orphans"]]
        assert "assets/leftover.mp4" in rels
        assert "assets/tiny-orphan.png" not in rels


def test_nondelivery_excluded_from_heavy_and_orphan():
    with tempfile.TemporaryDirectory() as t:
        _mk(os.path.join(t, "assets/real.png"), 1 * MB)
        _mk(os.path.join(t, "deck.json.bak-pre-set-20260101"), 50 * MB)  # backup cruft
        _deck(t, '<img src="assets/real.png">')
        f = caw.audit(t, deck_max=10 * MB)
        # 50MB backup must NOT count toward delivered weight, nor be an orphan
        assert f["deck_bytes"] < 5 * MB
        assert f["heavy"] is False
        assert not any("bak" in r for r, _ in f["orphans"])


def test_heavy_total_over_limit():
    with tempfile.TemporaryDirectory() as t:
        _mk(os.path.join(t, "assets/a.png"), 1 * MB)
        _deck(t, '<img src="assets/a.png">')
        assert caw.audit(t, deck_max=10 * MB)["heavy"] is False
        assert caw.audit(t, deck_max=500 * 1024)["heavy"] is True


def test_clean_deck_no_findings():
    with tempfile.TemporaryDirectory() as t:
        _mk(os.path.join(t, "assets/a.png"), 300 * 1024)
        _deck(t, '<img src="assets/a.png">')
        f = caw.audit(t)
        assert f["oversized"] == [] and f["embeds"] == [] and f["orphans"] == []
        assert f["heavy"] is False
        assert caw.format_report(f, compact=True) == ""   # silent when clean


def test_compact_report_when_bloated():
    with tempfile.TemporaryDirectory() as t:
        _mk(os.path.join(t, "assets/big.png"), 4 * MB)
        _deck(t, '<img src="assets/big.png">')
        line = caw.format_report(caw.audit(t), compact=True)
        assert "[asset-weight]" in line and "超大图" in line


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
