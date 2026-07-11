from __future__ import annotations

import importlib.util
from pathlib import Path
import socket
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
sys.path.insert(0, str(ASSETS))

import safe_resources as SR  # noqa: E402
from safe_resources import (  # noqa: E402
    UnsafeResourceError,
    _SafeRedirectHandler,
    resolve_local_file,
    validate_remote_url,
)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_local_resolution_accepts_only_contained_files(tmp_path: Path):
    root = tmp_path / "deck"
    root.mkdir()
    inside = root / "assets" / "ok.png"
    inside.parent.mkdir()
    inside.write_bytes(b"ok")
    assert resolve_local_file(root, "assets/ok.png", allowed_roots=(root,)) == inside

    outside = tmp_path / "secret.txt"
    outside.write_text("secret", encoding="utf-8")
    with pytest.raises(UnsafeResourceError, match="escapes allowed roots"):
        resolve_local_file(root, "../secret.txt", allowed_roots=(root,))
    with pytest.raises(UnsafeResourceError, match="absolute"):
        resolve_local_file(root, "/etc/hosts", allowed_roots=(root,))


def test_local_resolution_rejects_symlink_escape(tmp_path: Path):
    root = tmp_path / "deck"
    root.mkdir()
    outside = tmp_path / "outside.html"
    outside.write_text("secret", encoding="utf-8")
    link = root / "demo.html"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks unavailable")
    with pytest.raises(UnsafeResourceError, match="escapes allowed roots"):
        resolve_local_file(root, "demo.html", allowed_roots=(root,))


def test_actual_asset_resolvers_reject_absolute_and_parent_escape(tmp_path: Path):
    inline = _load("inline_assets_security", ASSETS / "inline-assets.py")
    magic = _load("magic_assets_security", ASSETS / "magic-page-assets.py")
    iframe = _load("iframe_assets_security", ASSETS / "magic-iframe-faas.py")
    deck = tmp_path / "deck"
    deck.mkdir()
    index = deck / "index.html"
    index.write_text("<html></html>", encoding="utf-8")
    outside = tmp_path / "outside.html"
    outside.write_text("outside", encoding="utf-8")
    (deck / ".magic-token").write_text("token", encoding="utf-8")
    (deck / "secret.py").write_text("SECRET = 1", encoding="utf-8")

    with pytest.raises(UnsafeResourceError):
        inline.resolve_asset(index, "/etc/hosts")
    with pytest.raises(UnsafeResourceError):
        magic.resolve_asset(index, "/etc/hosts", base_dir=deck)
    with pytest.raises(UnsafeResourceError):
        iframe.resolve_local_iframe("../outside.html", deck)
    with pytest.raises(UnsafeResourceError, match="hidden"):
        magic.resolve_asset(index, ".magic-token", base_dir=deck)
    with pytest.raises(UnsafeResourceError, match="type"):
        inline.resolve_asset(index, "secret.py")


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/x",
    "http://[::1]/x",
    "http://169.254.169.254/latest/meta-data/",
    "http://10.0.0.1/x",
])
def test_remote_validation_rejects_non_public_destinations(url: str):
    with pytest.raises(UnsafeResourceError, match="non-public"):
        validate_remote_url(url)


def test_remote_validation_rejects_mixed_public_private_dns():
    def resolver(_host, _port, *, type):  # noqa: A002
        assert type == socket.SOCK_STREAM
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443)),
        ]

    with pytest.raises(UnsafeResourceError, match="non-public"):
        validate_remote_url("https://public.example/x", resolver=resolver)


def test_redirect_handler_rejects_redirect_to_loopback():
    handler = _SafeRedirectHandler()
    request = type("Req", (), {"full_url": "https://8.8.8.8/start"})()
    with pytest.raises(UnsafeResourceError, match="non-public"):
        handler.redirect_request(request, None, 302, "Found", {}, "http://127.0.0.1/admin")


def test_all_automatic_downloaders_reject_loopback_before_writing(tmp_path: Path):
    magic = _load("magic_assets_download_security", ASSETS / "magic-page-assets.py")
    materialize = _load("materialize_download_security", ASSETS / "materialize-remote-images.py")
    lift_insert = _load("lift_insert_download_security", ROOT / "deck-json" / "lift-insert.py")
    url = "http://127.0.0.1:9/private.html"

    with pytest.raises(UnsafeResourceError, match="non-public"):
        magic.download_external_ref(url, temp_dir=tmp_path, cache={})
    with pytest.raises(RuntimeError, match="non-public"):
        materialize.download_image(url, output_dir=tmp_path, cache={})
    target = tmp_path / "prototype.html"
    with pytest.raises(UnsafeResourceError, match="non-public"):
        lift_insert._download_remote(url, target)
    assert not target.exists()


@pytest.mark.parametrize("content_type", [
    "text/css",
    "text/javascript",
    "application/javascript",
    "application/ecmascript",
    "application/x-javascript",
    "font/woff2",
    "application/wasm",
])
def test_magic_remote_resource_allowlist_preserves_valid_types(monkeypatch, content_type: str):
    magic = _load("magic_assets_mime_security", ASSETS / "magic-page-assets.py")

    class Response:
        status = 200
        headers = {"content-type": content_type, "content-length": "7"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def geturl(self):
            return "https://public.example/resource"

        def read(self, _size):
            if getattr(self, "done", False):
                return b""
            self.done = True
            return b"payload"

    class Opener:
        def open(self, _request, *, timeout):
            assert timeout == 5
            return Response()

    def resolver(_host, _port, *, type):  # noqa: A002
        assert type == socket.SOCK_STREAM
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]

    monkeypatch.setattr(SR, "build_opener", lambda *_handlers: Opener())
    monkeypatch.setattr(SR, "_response_peer_ip", lambda _response: "8.8.8.8")
    result = SR.download_public_resource(
        "https://public.example/resource",
        max_bytes=1024,
        timeout=5,
        user_agent="test",
        allowed_types=magic.EXTERNAL_RESOURCE_TYPES,
        allowed_type_prefixes=("image/", "font/", "audio/", "video/"),
        resolver=resolver,
    )
    assert result.payload == b"payload"
    assert result.content_type == content_type
