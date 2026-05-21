#!/usr/bin/env python3
"""deck-editor.py — Phase 4 visual editor (local server).

Usage:
  python3 deck-editor.py <deck.json> [--port N] [--no-browser]

What it does:
  1. Auto-render deck to a sibling "_preview/" folder so the iframe has
     something to show on first paint.
  2. Start a local HTTP server (auto-picks a free port).
  3. Open the editor in your default browser.
  4. Editor frontend (vanilla JS) talks to a small REST API:
       GET  /                    → editor.html
       GET  /api/deck            → current deck.json contents
       POST /api/op              → run a deck-cli.py subcommand
       POST /api/render          → re-render preview (auto-fired after op)
       GET  /preview/...         → serve _preview/ output
       POST /api/import-slide    → import a slide from another deck.json
       GET  /editor/...          → static frontend assets (CSS/JS)

stdlib-only Python 3.11+ (http.server + subprocess). Reuses Phase 0-3
artifacts (deck-cli.py + render-deck.py + validate-deck.py).
"""
from __future__ import annotations

import argparse
import copy
import hmac
import http.server
import json
import os
import secrets
import socket
import socketserver
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from urllib.parse import urlparse, parse_qs

HERE        = Path(__file__).resolve().parent
EDITOR_DIR  = HERE / "editor"
DECK_CLI    = HERE / "deck-cli.py"
RENDER_DECK = HERE / "render-deck.py"

# Server state (single-deck per editor instance — simple)
STATE = {
    "deck_path":    None,    # Path to deck.json being edited
    "preview_dir":  None,    # Path to _preview/ render output
    "csrf_token":   None,    # 32-byte hex random per-launch; binds GET/POST sessions
    "allowed_decks": set(),  # snapshot of decks discoverable at launch; switch-deck enforces this
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def find_free_port(preferred: int | None = None) -> int:
    if preferred:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", preferred))
                return preferred
            except OSError:
                pass
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def run_deck_cli(args: list[str]) -> tuple[int, str, str]:
    cmd = [sys.executable, str(DECK_CLI), str(STATE["deck_path"]), "--yes"] + args
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def re_render() -> tuple[bool, str]:
    """Re-render preview into _preview/ dir. Returns (success, log)."""
    # Drop --skip-copy-assets so asset refs in raw slides (assets/shared/*,
    # input/*, ./scene.png) resolve correctly under _preview/. copy-assets
    # now accepts sibling output dirs (output-deckjson, _preview) via the
    # find_run_root sibling fallback.
    cmd = [sys.executable, str(RENDER_DECK), str(STATE["deck_path"]),
           str(STATE["preview_dir"])]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.returncode == 0, proc.stdout + proc.stderr


def load_deck() -> dict:
    return json.loads(STATE["deck_path"].read_text(encoding="utf-8"))


def write_deck(deck: dict) -> None:
    STATE["deck_path"].write_text(
        json.dumps(deck, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class EditorHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_):
        # Quiet by default — uncomment for debug
        # super().log_message(*_)
        return

    # ---- response helpers ----
    def _send(self, status: int, body: bytes, content_type: str = "application/json"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        # Loopback-only single-user editor — no cross-origin use case. Default
        # to same-origin (omit Access-Control-Allow-Origin) so cross-tab fetch()
        # is blocked at the browser. Combined with the per-launch CSRF token
        # this is defense-in-depth against malicious-tab CSRF attacks.
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.end_headers()
        self.wfile.write(body)

    def _check_csrf(self) -> bool:
        """Verify the per-launch token. Accept it either from `X-Editor-Token`
        header (POST default) or `?token=` query (used by the initial GET that
        loads index.html and bootstraps the token into the SPA)."""
        token = STATE.get("csrf_token")
        if not token:                                # token not initialized — fail closed
            return False
        # Header form
        hdr = self.headers.get("X-Editor-Token") or ""
        if hdr and hmac.compare_digest(hdr, token):
            return True
        # Query form
        qs  = parse_qs(urlparse(self.path).query)
        qtok = (qs.get("token") or [""])[0]
        if qtok and hmac.compare_digest(qtok, token):
            return True
        return False

    def _send_json(self, obj, status: int = 200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _send_error_json(self, msg: str, status: int = 400):
        self._send_json({"ok": False, "error": msg}, status)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    # ---- GET ----
    def do_GET(self):
        url = urlparse(self.path)
        path = url.path

        # Public root: serves index.html. The HTML embeds the token via the
        # query string of its own URL, so the SPA can read it from
        # location.search and attach it to subsequent /api/* calls.
        # Note: a request without ?token= still gets index.html, but it can't
        # do anything useful — every /api/* requires the token.
        if path in ("/", "/index.html"):
            return self._serve_static(EDITOR_DIR / "index.html", EDITOR_DIR,
                                      "text/html; charset=utf-8")

        # /editor/* → frontend assets (JS / CSS). Public; no secrets here.
        if path.startswith("/editor/"):
            rel = path[len("/editor/"):]
            return self._serve_static(EDITOR_DIR / rel, EDITOR_DIR)

        # /preview/* → rendered HTML. NOT token-gated for GET — the iframe
        # loads CSS/JS via relative URLs that wouldn't inherit the token,
        # breaking the preview. Defense against cross-origin read: we omit
        # Access-Control-Allow-Origin (see _send) so the browser blocks
        # cross-origin fetch from reading the body via Same-Origin Policy.
        if path.startswith("/preview/"):
            rel = path[len("/preview/"):] or "index.html"
            return self._serve_static(STATE["preview_dir"] / rel, STATE["preview_dir"])

        # /skills/feishu-deck-h5/* → skill assets (CSS / JS / images the
        # preview iframe needs). Strict prefix match (was substring `in path`
        # — fixed H2). Not token-gated for the same reason as /preview/*
        # (relative URLs in preview HTML can't propagate token).
        skill_root = HERE.parent
        if path.startswith("/skills/feishu-deck-h5/"):
            rel = path[len("/skills/feishu-deck-h5/"):]
            return self._serve_static(skill_root / rel, skill_root)

        # /api/* GET endpoints — token-gated. /api/deck returns user content;
        # /api/decks lists deck.json files. Without token, cross-tab attacker
        # can't enumerate.
        if path.startswith("/api/"):
            if not self._check_csrf():
                return self._send_error_json("forbidden — missing or invalid token", 403)

        # /api/deck → current deck.json
        if path == "/api/deck":
            try:
                deck = load_deck()
            except Exception as e:
                return self._send_error_json(f"failed to read deck: {e}", 500)
            return self._send_json({"ok": True, "deck": deck, "path": str(STATE["deck_path"])})

        # /api/decks → list all discoverable deck.json files (for switcher).
        # Also refreshes STATE["allowed_decks"] — /api/switch-deck consults
        # this allow-list, plugging C2 (arbitrary-path read).
        if path == "/api/decks":
            cands: list[Path] = []
            for parent in [Path.cwd(), HERE, *HERE.parents]:
                if (parent / "runs").is_dir():
                    cands.extend((parent / "runs").glob("*/output/deck.json"))
            cands = sorted({c.resolve() for c in cands if c.is_file()},
                           key=lambda p: p.stat().st_mtime, reverse=True)
            STATE["allowed_decks"] = {str(c) for c in cands}
            out = []
            for c in cands:
                try:
                    d = json.loads(c.read_text(encoding="utf-8"))
                    title = d.get("deck", {}).get("title", "<no title>")
                    n = len(d.get("slides", []))
                except Exception:
                    title, n = "<unreadable>", 0
                out.append({
                    "path":     str(c),
                    "title":    title,
                    "n_slides": n,
                    "is_current": str(c) == str(STATE["deck_path"]),
                    "mtime":    c.stat().st_mtime,
                })
            return self._send_json({"ok": True, "decks": out})

        return self._send_error_json(f"not found: {path}", 404)

    def _serve_static(self, path: Path, base: Path, ctype: str | None = None):
        """Serve a file from disk, with a strict containment check.

        `base` is the legal directory tree this route is allowed to read from
        (e.g. EDITOR_DIR for /editor/*, STATE['preview_dir'] for /preview/*,
        skill_root for /skills/feishu-deck-h5/*). The resolved target must be
        a descendant of `base`, else 403. Plugs H1 — without this an attacker
        could `GET /editor/../../etc/passwd` and read arbitrary readable files
        (because urlparse doesn't collapse `..`).
        """
        try:
            target = path.resolve(strict=False)
            base_r = base.resolve(strict=False)
        except Exception:
            return self._send_error_json("invalid path", 400)
        # Use is_relative_to (Py 3.9+) — explicit, no string-prefix tricks
        try:
            target.relative_to(base_r)
        except ValueError:
            return self._send_error_json("forbidden — path outside route base", 403)
        if not target.is_file():
            return self._send_error_json(f"static not found: {target}", 404)
        if ctype is None:
            ctype = {
                ".html": "text/html; charset=utf-8",
                ".css":  "text/css; charset=utf-8",
                ".js":   "application/javascript; charset=utf-8",
                ".json": "application/json; charset=utf-8",
                ".png":  "image/png",
                ".jpg":  "image/jpeg",
                ".jpeg": "image/jpeg",
                ".svg":  "image/svg+xml",
                ".md":   "text/markdown; charset=utf-8",
            }.get(target.suffix.lower(), "application/octet-stream")
        return self._send(200, target.read_bytes(), ctype)

    # ---- POST ----
    def do_POST(self):
        path = urlparse(self.path).path

        # ALL POST endpoints require the per-launch CSRF token — plugs C1.
        if not self._check_csrf():
            return self._send_error_json("forbidden — missing or invalid token", 403)

        if path == "/api/op":
            return self._handle_op()
        if path == "/api/render":
            return self._handle_render()
        if path == "/api/import-slide":
            return self._handle_import_slide()
        if path == "/api/import-upload":
            return self._handle_import_upload()
        if path == "/api/switch-deck":
            return self._handle_switch_deck()
        if path == "/api/upload-image":
            return self._handle_upload_image()
        if path == "/api/import-pdf":
            return self._handle_import_pdf()
        return self._send_error_json(f"not found: {path}", 404)

    def _handle_op(self):
        """Run a deck-cli.py subcommand. Body: {"cmd": "...", "args": [...]}.
        After success, re-render preview so the iframe reload picks up the change."""
        body = self._read_body()
        cmd = body.get("cmd")
        args = body.get("args") or []
        if not cmd:
            return self._send_error_json("missing 'cmd' field")
        rc, stdout, stderr = run_deck_cli([cmd, *map(str, args)])
        if rc != 0:
            return self._send_error_json(
                f"deck-cli {cmd} failed (rc={rc}):\n{stdout}\n{stderr}", 400,
            )
        # Re-render after successful op so preview is fresh
        rok, rlog = re_render()
        deck = load_deck()
        return self._send_json({
            "ok": True,
            "stdout": stdout,
            "deck": deck,
            "render_ok": rok,
            "render_log": rlog if not rok else "",
        })

    def _handle_render(self):
        ok, log = re_render()
        return self._send_json({"ok": ok, "log": log})

    def _handle_import_pdf(self):
        """Convert an uploaded PDF into N replica slides appended to the deck.

        Body: {filename, base64_content}
        Pipeline:
          1. Decode base64 → /tmp/<uuid>.pdf
          2. Run `pdftoppm -jpeg -r 144 <pdf> <output_dir>/assets/pdf-NNN`
             → produces <output_dir>/assets/pdf-NNN-1.jpg, -2.jpg, ...
          3. For each page, append a {layout: replica, data: {page_image: ...}}
             slide to the current deck.
          4. Re-render and report total appended.
        Requires `pdftoppm` (poppler-utils) on PATH.
        """
        import base64, shutil as _shutil, subprocess as _sp, tempfile, uuid

        if _shutil.which("pdftoppm") is None:
            return self._send_error_json(
                "pdftoppm not found on PATH. Install poppler-utils: "
                "macOS `brew install poppler` · Linux `apt install poppler-utils`",
                500,
            )

        body = self._read_body()
        b64 = body.get("base64_content")
        filename = body.get("filename") or "import.pdf"
        if not b64:
            return self._send_error_json("missing base64_content")
        try:
            pdf_bytes = base64.b64decode(b64)
        except Exception as e:
            return self._send_error_json(f"base64 decode failed: {e}", 400)

        # Stem for filenames: pdf source name without extension, sanitized
        stem = Path(filename).stem
        import re as _re
        stem = _re.sub(r"[^a-zA-Z0-9._-]", "_", stem) or "pdf"
        # Make unique to avoid collisions if user imports same PDF twice
        unique = uuid.uuid4().hex[:6]
        prefix = f"pdf-{stem}-{unique}"

        # Write PDF to tmp
        tmp_pdf = Path(tempfile.gettempdir()) / f"{prefix}.pdf"
        tmp_pdf.write_bytes(pdf_bytes)

        # Ensure assets dir
        assets_dir = STATE["deck_path"].parent / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)

        # Run pdftoppm. -scale-to-x 1920 → 1920px wide, height proportional.
        # timeout=120s — a hostile PDF (poppler bug / pathological structure)
        # can't hang the server indefinitely. 120s is generous: 1920px
        # rasterization of a typical 50-page PDF finishes in ~10s.
        out_prefix = assets_dir / prefix
        try:
            _sp.run(
                ["pdftoppm", "-jpeg", "-jpegopt", "quality=85",
                 "-scale-to-x", "1920", "-scale-to-y", "-1",
                 str(tmp_pdf), str(out_prefix)],
                check=True, capture_output=True, text=True, timeout=120,
            )
        except _sp.TimeoutExpired:
            return self._send_error_json(
                "pdftoppm timed out after 120s — likely a pathological PDF "
                "or poppler bug. Try a smaller PDF or pre-process locally.", 500,
            )
        except _sp.CalledProcessError as e:
            return self._send_error_json(
                f"pdftoppm failed (rc={e.returncode}):\n{e.stderr}", 500,
            )
        finally:
            try: tmp_pdf.unlink()
            except OSError: pass

        # Find produced pages, sort by numeric suffix
        pages = sorted(assets_dir.glob(f"{prefix}-*.jpg"),
                       key=lambda p: int(_re.search(r"-(\d+)\.jpg$", p.name).group(1)))
        if not pages:
            return self._send_error_json("pdftoppm produced no pages", 500)

        # Append replica slides to deck
        deck = load_deck()
        existing_keys = {s.get("key") for s in deck["slides"]}
        added = []
        for page in pages:
            # page filename like "pdf-stem-abcdef-1.jpg"
            m = _re.search(r"-(\d+)\.jpg$", page.name)
            page_no = int(m.group(1))
            base_key = f"{stem}-p{page_no:02d}"
            key = base_key
            n = 2
            while key in existing_keys:
                key = f"{base_key}-{n}"
                n += 1
            existing_keys.add(key)
            deck["slides"].append({
                "key":          key,
                "layout":       "replica",
                "screen_label": f"PDF p{page_no}",
                "data": {
                    "page_image":  f"assets/{page.name}",
                    "alt":         f"{stem} page {page_no}",
                    "source_page": page_no,
                },
            })
            added.append(key)

        write_deck(deck)
        rok, rlog = re_render()
        return self._send_json({
            "ok":         True,
            "n_pages":    len(pages),
            "added_keys": added,
            "deck":       deck,
            "render_ok":  rok,
            "render_log": rlog if not rok else "",
        })

    def _handle_upload_image(self):
        """Write a base64-encoded image into <deck_dir>/assets/<filename>,
        return the relative path to use in the slide's image.src field.

        Body: {filename, base64_content}
        Response: {ok, src: "assets/<filename>"}
        """
        import base64, re as _re
        body = self._read_body()
        filename = body.get("filename")
        b64      = body.get("base64_content")
        if not filename or not b64:
            return self._send_error_json("require filename + base64_content")
        # Sanitize filename — no path traversal, only [a-zA-Z0-9._-]
        safe = _re.sub(r"[^a-zA-Z0-9._-]", "_", filename)
        if not safe or safe.startswith("."):
            return self._send_error_json("invalid filename")
        try:
            raw = base64.b64decode(b64)
        except Exception as e:
            return self._send_error_json(f"base64 decode failed: {e}", 400)
        assets_dir = STATE["deck_path"].parent / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        target = assets_dir / safe
        target.write_bytes(raw)
        return self._send_json({
            "ok": True,
            "src":  f"assets/{safe}",
            "abs":  str(target),
            "size": len(raw),
        })

    def _handle_switch_deck(self):
        """Switch the editor to a different deck.json.

        Body: {"path": "/abs/path/to/another/deck.json"}
        Updates STATE.deck_path + STATE.preview_dir, re-renders, returns ok.
        Frontend should then reload the page to fetch new deck.

        Security: target path MUST be in STATE['allowed_decks'] — populated
        each time /api/decks is called (which the frontend hits when opening
        the deck-switcher modal). This plugs C2 (arbitrary-file read) — an
        attacker can't switch to /etc/passwd / SSH key paths even with the
        CSRF token, because they weren't surveyed at deck-discovery time.
        """
        body = self._read_body()
        new_path = body.get("path")
        if not new_path:
            return self._send_error_json("missing 'path' field")
        target = Path(new_path).resolve()
        target_s = str(target)
        if target_s not in STATE["allowed_decks"]:
            return self._send_error_json(
                "forbidden — target not in deck allow-list. Use /api/decks "
                "first to refresh the survey set.", 403,
            )
        if not target.is_file():
            return self._send_error_json(f"file not found: {target}", 404)
        try:
            json.loads(target.read_text(encoding="utf-8"))
        except Exception as e:
            return self._send_error_json(f"target is not valid JSON: {e}", 400)
        STATE["deck_path"]   = target
        STATE["preview_dir"] = target.parent / "_preview"
        STATE["preview_dir"].mkdir(parents=True, exist_ok=True)
        rok, rlog = re_render()
        return self._send_json({"ok": True, "path": str(target),
                                "render_ok": rok, "render_log": rlog if not rok else ""})

    def _handle_import_upload(self):
        """Browser-friendly import: accept base64 file content (no absolute
        path needed). Body shapes:
          {filename, base64_content}                  → parse, return slide list
          {filename, base64_content, slide_key}       → import that slide
        """
        import base64, tempfile, uuid
        body = self._read_body()
        b64  = body.get("base64_content")
        if not b64:
            return self._send_error_json("missing base64_content")
        try:
            raw = base64.b64decode(b64)
            source = json.loads(raw.decode("utf-8"))
        except Exception as e:
            return self._send_error_json(f"failed to decode/parse: {e}", 400)
        if not source.get("slides"):
            return self._send_error_json("uploaded file has no slides array", 400)

        slide_key = body.get("slide_key")
        if not slide_key:
            # First request — just return the slide list so the picker can render
            return self._send_json({
                "ok": True,
                "filename": body.get("filename", "<uploaded>"),
                "slides": [
                    {"key": s.get("key"), "layout": s.get("layout"),
                     "variant": s.get("variant"), "screen_label": s.get("screen_label")}
                    for s in source["slides"]
                ],
            })

        # Second request — perform the import. Find the slide, deep-copy it
        # into our deck. Handle key collision.
        src_slide = next((s for s in source["slides"] if s.get("key") == slide_key), None)
        if src_slide is None:
            return self._send_error_json(f"slide '{slide_key}' not in upload", 404)

        new_slide = copy.deepcopy(src_slide)
        deck = load_deck()
        existing = {s.get("key") for s in deck["slides"]}
        if new_slide.get("key") in existing:
            base = new_slide["key"]
            n = 1
            while f"{base}-imported-{n}" in existing:
                n += 1
            new_slide["key"] = f"{base}-imported-{n}"
        deck["slides"].append(new_slide)
        write_deck(deck)

        rok, rlog = re_render()
        return self._send_json({
            "ok": True,
            "imported_key": new_slide["key"],
            "position": len(deck["slides"]),
            "deck": deck,
            "render_ok": rok,
            "render_log": rlog if not rok else "",
        })


    def _handle_import_slide(self):
        """Import a slide from another deck.json into the current deck.

        Body: {"source_path": "/abs/path/to/other.json", "slide_key": "...",
               "position": int (1-indexed, default end)}

        Phase 4.a behavior: appends to current deck. If key collides, rename
        to "<key>-imported-N".
        """
        body = self._read_body()
        source_path = body.get("source_path")
        slide_key = body.get("slide_key")
        position = body.get("position")
        if not source_path or not slide_key:
            return self._send_error_json("require source_path + slide_key")

        try:
            source = json.loads(Path(source_path).read_text(encoding="utf-8"))
        except Exception as e:
            return self._send_error_json(f"failed to read source deck: {e}", 400)

        src_slides = source.get("slides", [])
        src_slide = next((s for s in src_slides if s.get("key") == slide_key), None)
        if src_slide is None:
            return self._send_error_json(
                f"slide '{slide_key}' not found in source deck", 404,
            )

        # Clone the slide
        new_slide = copy.deepcopy(src_slide)

        # Rename if key collision
        deck = load_deck()
        existing = {s.get("key") for s in deck["slides"]}
        if new_slide.get("key") in existing:
            base = new_slide["key"]
            n = 1
            while f"{base}-imported-{n}" in existing:
                n += 1
            new_slide["key"] = f"{base}-imported-{n}"

        # Insert
        if position is None or position > len(deck["slides"]):
            deck["slides"].append(new_slide)
            final_pos = len(deck["slides"])
        else:
            deck["slides"].insert(max(0, position - 1), new_slide)
            final_pos = position

        write_deck(deck)
        rok, rlog = re_render()
        return self._send_json({
            "ok": True,
            "imported_key": new_slide["key"],
            "position": final_pos,
            "deck": deck,
            "render_ok": rok,
            "render_log": rlog if not rok else "",
        })


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def find_default_deck() -> Path | None:
    """Auto-detect a deck.json when the user runs deck-editor without args.
    Lookup order (first hit wins, ties broken by most recent mtime):
      1. ./deck.json in cwd
      2. ./runs/*/output/deck.json relative to cwd
      3. climb cwd's parents looking for a dir with `runs/`, scan its output/s
      4. climb the SCRIPT's parents (deck-editor.py location → deck-json →
         skill → repo root) looking for `runs/` — covers running the
         editor from any cwd (~ / /tmp / wherever), as long as the script
         itself is inside a repo with a runs/ folder.
    Returns None if nothing found.
    """
    cands: list[Path] = []
    cwd = Path.cwd()

    # 1. cwd/deck.json
    if (cwd / "deck.json").is_file():
        cands.append(cwd / "deck.json")

    # 2. cwd/runs/*/output/deck.json
    cands.extend(cwd.glob("runs/*/output/deck.json"))

    # 3. climb cwd's parents, scan EVERY runs/ found (don't break — the
    #    first hit might be empty, e.g. skill-local runs/ vs real repo runs/)
    for parent in [cwd, *cwd.parents]:
        if (parent / "runs").is_dir():
            cands.extend((parent / "runs").glob("*/output/deck.json"))

    # 4. climb script location's parents — covers "edit from anywhere"
    for parent in [HERE, *HERE.parents]:
        if (parent / "runs").is_dir():
            cands.extend((parent / "runs").glob("*/output/deck.json"))

    cands = [c for c in cands if c.is_file()]
    cands = sorted(set(cands), key=lambda p: p.stat().st_mtime, reverse=True)
    return cands[0] if cands else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="deck-editor.py", description=__doc__.split("\n")[0])
    ap.add_argument("deck", type=Path, nargs="?", default=None,
                    help="path to deck.json (optional — auto-detected from "
                         "cwd/deck.json or runs/<latest>/output/deck.json)")
    ap.add_argument("--port", type=int, default=None, help="preferred port (default: auto)")
    ap.add_argument("--no-browser", action="store_true", help="don't auto-open browser")
    args = ap.parse_args(argv)

    if args.deck is None:
        args.deck = find_default_deck()
        if args.deck is None:
            print("deck-editor: no deck path given and none auto-detected", file=sys.stderr)
            print("  · pass a path explicitly: deck-editor.py path/to/deck.json", file=sys.stderr)
            print("  · or place deck.json in cwd / runs/<ts>/output/", file=sys.stderr)
            return 2
        print(f"  auto-detected deck: {args.deck}", file=sys.stderr)

    if not args.deck.is_file():
        print(f"deck-editor: deck not found: {args.deck}", file=sys.stderr); return 2
    try:
        json.loads(args.deck.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"deck-editor: invalid JSON in deck: {e}", file=sys.stderr); return 2

    STATE["deck_path"]   = args.deck.resolve()
    STATE["preview_dir"] = args.deck.resolve().parent / "_preview"
    STATE["preview_dir"].mkdir(parents=True, exist_ok=True)

    # Per-launch CSRF token — bound into the URL passed to the browser. Every
    # /api/* request must echo it via X-Editor-Token header or ?token=. Plugs
    # C1 (cross-tab fetch hijack). secrets.token_urlsafe → 32 random bytes,
    # ~256 bits of entropy, URL-safe characters.
    STATE["csrf_token"] = secrets.token_urlsafe(32)
    # Seed allowed_decks with the currently-opened deck — so switch-deck back
    # to self always works even before /api/decks is called.
    STATE["allowed_decks"] = {str(STATE["deck_path"])}

    # Initial render so iframe has something to show
    print("→ Initial render...", file=sys.stderr)
    ok, log = re_render()
    if not ok:
        print(f"deck-editor: initial render failed:\n{log}", file=sys.stderr)
        print("→ Starting editor anyway; fix issues in deck.json and click 'Render'.",
              file=sys.stderr)

    port = find_free_port(args.port)
    addr = ("127.0.0.1", port)
    url  = f"http://127.0.0.1:{port}/?token={STATE['csrf_token']}"
    print(f"\n  deck-editor · {url}", file=sys.stderr)
    print(f"  editing:  {STATE['deck_path']}", file=sys.stderr)
    print(f"  preview:  {STATE['preview_dir']}/index.html", file=sys.stderr)
    print(f"  ^C to stop\n", file=sys.stderr)

    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()

    httpd = socketserver.TCPServer(addr, EditorHandler)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  stopped.", file=sys.stderr)
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
