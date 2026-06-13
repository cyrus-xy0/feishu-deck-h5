"""F-315 · index.html self-integrity signature — stop a re-render from silently
destroying browser edit-mode (or hand) edits that were never synced into deck.json.

THE BUG THIS GUARDS: `deck.json` is the source of truth; `index.html` is derived
and FULLY regenerated on every render. The in-browser edit-mode (`e` + ⌘S, see
assets/edit-mode/deck-edit-mode.js) writes the colleague's edits ONLY into
index.html — never into deck.json. The next render/edit then overwrites index.html
from the untouched deck.json and the edits vanish. (Recovery path is
sync-index-to-deck.py, but nothing FORCED a sync, so it was a silent footgun.)

MECHANISM (layout-agnostic — works for canvas / raw / schema slides alike, unlike
a per-slide content diff which is non-idempotent for canvas round-trips):

  • render-deck.py stamps `<meta name="fs-render-sig" content="…">` into every
    index.html it writes — a hash of the CANONICAL form of that exact HTML.
  • Any later external edit (edit-mode ⌘S re-serializes the DOM; a hand-patch
    changes bytes) makes the on-disk content no longer hash to the embedded sig.
  • verify() = "is this index.html still byte-faithful to the render that produced
    it?" → "ok" / "edited" / "unstamped". It compares the file against ITS OWN
    embedded sig — no deck.json read, no mtime, no canvas reverse-map.

GUARD (guard_should_refuse): refuse to clobber when index.html is "edited" AND
deck.json is NOT newer than it. The mtime side is what lets the legitimate
"sync-index-to-deck.py → re-render" recovery flow through: once a sync folds the
edits into deck.json, deck.json becomes newer, so re-rendering is safe and allowed.

Canonicalization strips only the bits that legitimately differ between two faithful
renders / post-processing passes of the SAME deck (so the sig is stable across
copy-assets and the per-render deck_id), and preserves ALL authored content (so any
real edit changes the sig)."""

import hashlib
import re
import subprocess
import sys
from pathlib import Path

SIG_META_NAME = "fs-render-sig"
SIG_LEN = 16

_SYNC_SCRIPT = Path(__file__).resolve().parent / "sync-index-to-deck.py"

# deck.json must be MORE than this many seconds newer than index.html to count as
# "the source moved ahead" (→ a re-render is the safe, intended direction). Matches
# sync-index-to-deck.py's _DIRECTION_TOLERANCE_S — a render writes both files
# back-to-back, and render utime-aligns index.html to deck.json, so the slack only
# absorbs FS mtime granularity / clock jitter.
DIRECTION_TOLERANCE_S = 2.0

_RE_DECK_ID = re.compile(r'(data-deck-id=")dk-[0-9a-z]+(")')
_RE_OUR_META = re.compile(
    r'\s*<meta name="fs-(?:deck-generator|deck-hash|render-sig)" content="[^"]*">')
_RE_ASSET_SRC = re.compile(r'((?:src|href)=")[^"]*?/?(assets/)')
_RE_ASSET_URL = re.compile(r'(url\(\s*[\'"]?)[^)\'"]*?/?(assets/)')
_RE_SIG_VALUE = re.compile(r'<meta name="fs-render-sig" content="([0-9a-f]+)">')


def _canonicalize(html: str) -> str:
    """Reduce index.html to a content-only canonical form for hashing.

    Removed (legitimately volatile / non-authored):
      • the per-render minted deck_id (data-deck-id="dk-…")
      • our own provenance + sig <meta> tags
      • asset path PREFIXES — copy-assets.py rewrites skill-relative refs to
        ./assets/…; collapse any …/assets/ → assets/ so the path rewrite is not
        seen as an edit. (--inline produces data: URIs with no "assets/" segment;
        the sig is stamped AFTER post-processing, so the inlined bytes are simply
        part of the canonical form and round-trip exactly.)
    Everything else — every byte of authored slide content — is preserved."""
    html = _RE_DECK_ID.sub(r'\1\2', html)
    html = _RE_OUR_META.sub("", html)
    html = _RE_ASSET_SRC.sub(r'\1\2', html)
    html = _RE_ASSET_URL.sub(r'\1\2', html)
    return html


def compute_sig(html: str) -> str:
    return hashlib.sha256(_canonicalize(html).encode("utf-8")).hexdigest()[:SIG_LEN]


def extract_sig(html: str):
    m = _RE_SIG_VALUE.search(html)
    return m.group(1) if m else None


def stamp_sig(html: str) -> str:
    """Inject/replace the fs-render-sig <meta>. Idempotent: _canonicalize strips
    any existing sig meta before hashing, so re-stamping an already-stamped file
    yields the same sig. Placed right after the fs-deck-hash provenance meta (or
    after <head> if absent). Pure string op — never raises on odd input."""
    sig = compute_sig(html)
    html = re.sub(r'\s*<meta name="fs-render-sig" content="[^"]*">', "", html)
    stamp = f'\n  <meta name="{SIG_META_NAME}" content="{sig}">'
    m = re.search(r'<meta name="fs-deck-hash" content="[^"]*">', html)
    if m:
        return html[:m.end()] + stamp + html[m.end():]
    m = re.search(r'<head[^>]*>', html, re.I)
    if m:
        return html[:m.end()] + stamp + html[m.end():]
    return html  # no <head> → leave untouched (never break the writer)


def verify(index_path: Path) -> str:
    """'ok' = unmodified since render · 'edited' = content changed after the sig was
    stamped (un-synced external edits) · 'unstamped' = no sig (legacy/foreign render
    or unreadable — caller decides; the guard treats it as not-refusable)."""
    try:
        html = Path(index_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "unstamped"
    sig = extract_sig(html)
    if sig is None:
        return "unstamped"
    return "ok" if compute_sig(html) == sig else "edited"


def deck_is_newer(deck_json: Path, index_html: Path,
                  tol: float = DIRECTION_TOLERANCE_S) -> bool:
    """True if deck.json's mtime is MORE than `tol` seconds newer than index.html
    (the source moved ahead of the render → a re-render is the safe direction, and
    any index.html edits were presumably already folded back via sync). Fail-open
    to False (do NOT suppress the guard) on any FS read error."""
    try:
        return (Path(deck_json).stat().st_mtime
                - Path(index_html).stat().st_mtime) > tol
    except OSError:
        return False


def align_mtime(index_html: Path, deck_json: Path) -> None:
    """After a successful render, set index.html's mtime to deck.json's so a
    freshly-rendered (unedited) index.html is NOT seen as 'newer than its source'.
    This keeps the guard's cheap mtime side quiet on the normal set-page→render
    loop; only a real post-render external write bumps index.html ahead again.
    Best-effort — never raises."""
    try:
        m = Path(deck_json).stat().st_mtime
        import os
        os.utime(index_html, (m, m))
    except OSError:
        pass


def guard_should_refuse(deck_json: Path, index_html: Path) -> "str | None":
    """Shared verdict for deck-cli (before mutating deck.json) and render-deck
    (before overwriting index.html).

    Returns a human-readable reason string when the operation MUST be refused
    (index.html carries un-synced external edits that the op would destroy), or
    None when it is safe to proceed.

    Refuse iff: index.html exists AND is 'edited' (fails its self-sig) AND
    deck.json is NOT newer than it (the edits have NOT been synced/superseded)."""
    index_html = Path(index_html)
    if not index_html.exists():
        return None
    if verify(index_html) != "edited":
        return None
    if deck_is_newer(deck_json, index_html):
        # deck.json moved ahead (e.g. a sync already folded these edits in, or the
        # source was intentionally re-authored) → re-render is the safe direction.
        return None
    return (
        f"{index_html.name} has edits made after its last render (browser edit-mode "
        f"⌘S or a hand-patch) that are NOT in {Path(deck_json).name}. "
        f"Proceeding would regenerate {index_html.name} from {Path(deck_json).name} "
        f"and DESTROY those edits.")


def _check_drift_code(deck_json: Path, index_html: Path) -> int:
    """Shell `sync-index-to-deck.py --check-drift` (read-only) and return its exit
    code: 0 = no slide drift · 10 = drift, all lossless · 11 = drift, some lossy
    (canvas / baked) · 2 = error. -1 on subprocess failure."""
    try:
        r = subprocess.run(
            [sys.executable, str(_SYNC_SCRIPT), "--check-drift",
             str(index_html), str(deck_json)],
            capture_output=True, text=True)
        return r.returncode
    except Exception:
        return -1


def auto_sync(deck_json: Path, index_html: Path) -> "tuple[bool, str]":
    """Reverse-feed index.html → deck.json (the lossless recovery), so the
    un-synced browser edits land in the source BEFORE the caller mutates/renders.
    `--index-is-newer` forces the reverse direction (index.html IS the newer side
    here — that is why the guard fired). Returns (ok, combined output)."""
    try:
        r = subprocess.run(
            [sys.executable, str(_SYNC_SCRIPT),
             str(index_html), str(deck_json), "--index-is-newer"],
            capture_output=True, text=True)
        return (r.returncode == 0, (r.stdout or "") + (r.stderr or ""))
    except Exception as e:  # pragma: no cover
        return (False, str(e))


def resolve_clobber(deck_json: Path, index_html: Path) -> "tuple[str, str | None]":
    """F-315 Option A — decide how to handle un-synced index.html edits before a
    deck.json mutation / re-render:

      ("ok",       None)   — no un-synced edit; proceed directly (fast path).
      ("autosync", None)   — un-synced edits are ALL lossless (raw / custom_css /
                             order / hidden / notes) → caller should auto_sync()
                             them into deck.json, then proceed.
      ("refuse",   reason) — lossy (a canvas slide edited), baked DOM, an edit
                             outside any slide (chrome/<head> — sync can't fold it),
                             or a drift-check error → caller must STOP and let the
                             human sync/decide (or --force to discard).

    The cheap sig+mtime guard runs first; the (subprocess) drift classification only
    runs when there actually IS an un-synced edit, so the normal loop pays nothing."""
    reason = guard_should_refuse(deck_json, index_html)
    if reason is None:
        return ("ok", None)
    code = _check_drift_code(deck_json, index_html)
    if code == 10:
        return ("autosync", None)
    if code == 0:
        # sig says edited, but sync found no AUTO-FOLDABLE slide drift. Two cases,
        # indistinguishable to sync (it doesn't compare schema slides): the change
        # is in chrome / <head> / <title>, OR it's on a schema-layout slide (sync
        # only converts those with --force, lossily). Either way: not auto-syncable.
        return ("refuse", reason +
                " sync-index-to-deck.py found no auto-foldable drift — the edit is in "
                "chrome/<head> or a schema-layout slide it won't fold losslessly. "
                "Re-apply it in deck.json, or --force to discard.")
    # 11 (lossy: canvas / baked) or 2 / -1 (error)
    return ("refuse", reason +
            " It involves a canvas slide or a baked DOM, where the reverse-sync is "
            "lossy — handle it manually (sync-index-to-deck.py with judgement), or "
            "--force to discard.")
