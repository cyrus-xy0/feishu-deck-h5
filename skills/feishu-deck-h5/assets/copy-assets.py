#!/usr/bin/env python3
from __future__ import annotations

"""
copy-assets.py — Make a per-run output self-contained.

For every HTML file under runs/<ts>/output/, scan for references to:
  ../../../../skills/feishu-deck-h5/assets/<path>     (single-pages/* depth)
  ../../../skills/feishu-deck-h5/assets/<path>        (output/* depth)
  ../skills/feishu-deck-h5/assets/<path>              (any other depth)
  ../../input/<file>                                   (input asset)

…and the corresponding feishu-deck.css / .js. Copy each referenced asset
into runs/<ts>/output/assets/ (preserving subfolders), and rewrite the
HTML path to a relative local path. Result: output/ is portable; the
deck runs standalone when copied/zipped/uploaded anywhere.

USAGE:
    python3 assets/copy-assets.py runs/<timestamp>/output/ [--shared=MODE]

    --shared=link    (default) create a single symlink at output/assets/shared
                     pointing at skill's assets/shared/ (absolute path) instead
                     of copying files. Output uses local-looking refs
                     (assets/shared/foo.png) that resolve through the symlink.
                     zip / Finder-compress / IM-upload follow the symlink and
                     embed real files for the recipient — output is still
                     "send-the-folder" friendly. Saves ~5–30 MB per run vs copy.
    --shared=copy    full self-contained copy of every referenced shared file
                     into output/assets/shared/. Use as a final hardening step
                     when the destination tool doesn't follow symlinks (rsync
                     without -L, archival snapshots, etc.).
    --shared=skip    don't copy or symlink. Leave HTML refs to shared/*
                     pointing skill-relative (../...skills/feishu-deck-h5/
                     assets/shared/...) — output runs only while next to skill,
                     but downstream tools like the slide library resolve those
                     refs against their own shared pool. The manifest still
                     lists every shared file referenced, so consumers know
                     what to dedupe against.

Exits 0 on success. Idempotent: running twice is fine. Prints a summary
of bytes copied and HTML files patched.
"""

import os, re, sys, shutil
from pathlib import Path

# Match any reference of form:
#   *path*?/skills/feishu-deck-h5/(assets|...)/<file>
#   *path*?/(assets|deck-json/templates|...)/<file> when output lives inside skill root
# and any input/ reference. Captures: prefix path back-tracking + the asset path.
# Path char class excludes ? and # so cache-busting query strings (e.g.
# `assets/foo.png?v=3`) don't get glued onto the captured rest.
RX_SKILL = re.compile(
    r'((?:\.\./)+)(?:skills/feishu-deck-h5/)?(assets|examples|templates|deck-json/templates)/([^\'")\s?#]+)'
)
RX_INPUT = re.compile(
    r'((?:\.\./)*)input/([^\'")\s?#]+)'
)
# AFTER first rewrite, HTMLs use assets/<file> or ../assets/<file>
# (no skills/feishu-deck-h5 prefix). Both bare and ../-prefixed refs must
# be tracked so prune doesn't delete them.
# `*` (zero-or-more `../`) covers BOTH the deck root case (index.html in
# output/, refs like `assets/feishu-deck.css`) AND the sub-folder case
# (output/single-pages/p-NN.html, refs like `../assets/foo.png`).
# The `(?<!...)` negative lookbehind avoids matching the `assets/...`
# segment INSIDE a still-skill-relative path like
# `../../../skills/feishu-deck-h5/assets/clientlogo/x.png` — those are
# left unchanged in --shared=skip mode and shouldn't be classified as
# already-local refs.
RX_LOCAL_ASSET = re.compile(
    r'((?:url\(\s*[\'"]?|(?:src|href|poster|data-src|data-poster)=["\']?))((?:\.\./)*)assets/([^\'")\s?#<]+)'
)
RX_LOCAL_INPUT = re.compile(
    r'(?<!skills/feishu-deck-h5/)((?:\.\./)*)input/([^\'")\s?#]+)'
)

def find_skill_root() -> Path:
    """Walk up from this script to find skill root (feishu-deck-h5/)."""
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        if (parent / "SKILL.md").exists():
            return parent
    raise SystemExit("Cannot locate feishu-deck-h5 skill root from script location.")

# Subtrees of assets/ that count as the "library-grade shared content pool"
# (cross-deck reusable: client logos, digital employee avatars, third-party
# tool logos, feishu sub-product brand kit). The slide library dedupes these
# via assets-manifest.yaml; everything else under assets/ is framework
# (CSS/JS/lark brand) that every deck self-contains.
SHARED_PREFIX = "shared/"

# 字体缺失不算硬伤：@font-face 找不到字体文件会回退到系统字体，deck 仍可正常渲染。
# 打包时字体未找到只做温和提示，不当成“上传会被拦”的资源缺失（与素材网入库口径一致）。
FONT_EXTS = {".otf", ".ttf", ".ttc", ".woff", ".woff2", ".eot"}


def _is_font_ref(value: str) -> bool:
    base = str(value or "").split("?", 1)[0].split("#", 1)[0]
    return os.path.splitext(base)[1].lower() in FONT_EXTS

# Back-compat for old decks that still reference the pre-reorg paths
# (assets/clientlogo/foo.png instead of assets/shared/clientlogo/foo.png).
# When the original location is missing, retry with these prefixes.
LEGACY_DIR_REDIRECTS = {
    "clientlogo/": "shared/clientlogo/",
    "digital_employee_avatars_50/": "shared/digital_employee_avatars_50/",
    "mydigitalemployee/": "shared/mydigitalemployee/",
}

def resolve_asset(skill_root: Path, sub: str, rest: str) -> tuple[Path, str]:
    """Return (origin_path, possibly-redirected-rest) for an asset reference.
    If `rest` points to a legacy location, return the new shared/ location."""
    direct = skill_root / sub / rest
    if direct.exists():
        return direct, rest
    if sub != "assets":
        return direct, rest  # only assets/ has the shared/ reorg
    # Legacy directory prefix match
    for old, new in LEGACY_DIR_REDIRECTS.items():
        if rest.startswith(old):
            redirected = new + rest[len(old):]
            cand = skill_root / sub / redirected
            if cand.exists():
                return cand, redirected
    # Legacy top-level filename — search shared/ subtree by basename
    if "/" not in rest:
        shared_root = skill_root / "assets" / "shared"
        if shared_root.is_dir():
            matches = list(shared_root.rglob(rest))
            if len(matches) == 1:
                redirected = str(matches[0].relative_to(skill_root / "assets"))
                return matches[0], redirected
    return direct, rest  # not found — caller will warn

def find_run_root(out_dir: Path) -> Path:
    """Find runs/<ts>/ root from any nested output path.

    Canonical layout is `runs/<ts>/output/`. Also accept sibling output dirs
    under the same run (`output-deckjson/`, `_preview/`, `output-foo/`) so
    the editor's auto-render and ad-hoc compare renders can resolve assets."""
    for parent in [out_dir, *out_dir.parents]:
        # canonical: runs/<ts>/output/
        if parent.name == "output" and parent.parent.parent.name == "runs":
            return parent.parent
        # sibling under runs/<ts>/<anything>/  (output-deckjson, _preview, ...)
        if parent.parent.parent and parent.parent.parent.name == "runs":
            return parent.parent
    raise SystemExit(f"Cannot find run root from {out_dir}; expected runs/<ts>/output/.")

def ensure_shared_symlink(local_assets: Path, skill_root: Path) -> Path:
    """Ensure output/assets/shared is a symlink to the canonical assets/shared/.

    Idempotent. Auto-migrates a real directory (left over from a prior
    --shared=copy run) by removing it and replacing with a symlink. Uses an
    absolute path so moving the output/ folder elsewhere on the same machine
    doesn't break the link. Returns the symlink path."""
    target = local_assets / "shared"
    canonical = (skill_root / "assets" / "shared").resolve()
    local_assets.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        if Path(os.readlink(target)) == canonical:
            return target
        target.unlink()
    elif target.exists():
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
    target.symlink_to(canonical)
    return target

def main():
    args = sys.argv[1:]
    shared_mode = "link"
    positional = []
    for a in args:
        if a.startswith("--shared="):
            shared_mode = a.split("=", 1)[1]
            if shared_mode not in ("copy", "link", "skip"):
                sys.exit(f"Invalid --shared value: {shared_mode!r} (expected 'copy', 'link', or 'skip')")
        elif a in ("-h", "--help"):
            print(__doc__)
            sys.exit(0)
        else:
            positional.append(a)
    if len(positional) != 1:
        print(__doc__)
        sys.exit(1)

    out_dir = Path(positional[0]).resolve()
    if not out_dir.is_dir():
        sys.exit(f"Not a directory: {out_dir}")

    skill_root = find_skill_root()
    run_root = find_run_root(out_dir)
    input_root = run_root / "input"

    # Local asset target inside output/
    local_assets = out_dir / "assets"
    local_input = out_dir / "input"
    local_assets.mkdir(parents=True, exist_ok=True)
    if input_root.exists():
        local_input.mkdir(parents=True, exist_ok=True)

    bytes_copied = 0
    files_copied = set()
    htmls_patched = 0
    referenced = set()      # files that exist (or should exist) in output/ — protects from prune
    shared_refs = set()     # all assets/shared/* logical refs (for manifest, regardless of mode)
    shared_skipped = 0      # count of shared/* refs left as skill-relative under --shared=skip
    css_origins = {}        # copied CSS path -> original skill CSS path, for internal url(...) rewrites
    missing_sources = set() # 被 HTML/CSS 引用、但打包时找不到源文件的资源（打包结尾汇总，左移到打包阶段暴露）

    for html_path in out_dir.rglob("*.html"):
        # Prototype bundles are self-contained worlds (R-SELF-CONTAINED):
        # their internal `assets/...` refs are THEIR OWN files, not the deck's
        # framework assets. Depth-prefixing them (`../../assets/...`) pointed
        # e.g. a profile demo's ud-tokens.css at output/assets/ — which never
        # receives it — so the demo's styles died silently on file:// AND on
        # the published site (FWD people-profile, 2026-06-12). Never rewrite
        # inside prototypes/.
        if html_path.relative_to(out_dir).parts[:1] == ("prototypes",):
            continue
        # Compute relative depth for new local paths
        # output/index.html             → assets/  / input/
        # output/single-pages/p01.html  → ../assets/ / ../input/
        depth = len(html_path.relative_to(out_dir).parts) - 1
        prefix = "../" * depth

        src = html_path.read_text(encoding="utf-8")
        original = src

        def replace_skill(m):
            nonlocal bytes_copied, shared_skipped
            sub = m.group(2)  # assets / examples / templates
            rest = m.group(3)
            origin, rest = resolve_asset(skill_root, sub, rest)

            is_shared = (sub == "assets" and rest.startswith(SHARED_PREFIX))
            if is_shared:
                shared_refs.add(f"assets/{rest}")
                if shared_mode == "skip":
                    # Don't copy, don't rewrite. Leave HTML ref as skill-relative.
                    # Output won't be portable on its own, but the slide-library
                    # ingest path (and iteration-mode authoring) doesn't need it
                    # to be — it resolves shared/* against its own pool.
                    shared_skipped += 1
                    return m.group(0)
                if shared_mode == "link":
                    # Lazy-create the single shared symlink; rewrite ref to
                    # local-looking path. The symlink resolves files at request
                    # time — no per-file copy, no disk growth.
                    ensure_shared_symlink(local_assets, skill_root)
                    return f'{prefix}assets/{rest}'

            target = local_assets / rest if sub == "assets" else local_assets / sub / rest
            if not target.resolve().is_relative_to(out_dir.resolve()):
                print(f"  [WARN] skipping out-of-output asset ref (path traversal?): {m.group(0)}")
                return m.group(0)
            referenced.add(str(target.relative_to(out_dir)))
            if origin.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists() or target.stat().st_size != origin.stat().st_size:
                    shutil.copy2(origin, target)
                    bytes_copied += origin.stat().st_size
                    files_copied.add(str(target.relative_to(out_dir)))
                if target.suffix == ".css":
                    css_origins[str(target.resolve())] = origin.resolve()
                # New ref: prefix + assets/rest (or assets/<sub>/rest)
                if sub == "assets":
                    return f'{prefix}assets/{rest}'
                else:
                    return f'{prefix}assets/{sub}/{rest}'
            else:
                # Origin missing — leave reference unchanged so author notices
                print(f"  [WARN] missing asset: {origin}")
                missing_sources.add(str(target.relative_to(out_dir)))
                return m.group(0)

        def replace_input(m):
            nonlocal bytes_copied
            rest = m.group(2)
            target = local_input / rest
            if not target.resolve().is_relative_to(out_dir.resolve()):
                print(f"  [WARN] skipping out-of-output input ref (path traversal?): {m.group(0)}")
                return m.group(0)
            referenced.add(str(target.relative_to(out_dir)))
            # Try canonical runs/<ts>/input/ first, then fall back to other
            # likely locations (covers legacy decks that put input/ inside
            # output/ instead of at the run root, AND output-deckjson/ siblings
            # that need to find input/ via runs/<ts>/output/input/).
            candidates = [
                input_root / rest,                          # canonical
                out_dir.parent / "input" / rest,            # sibling-of-out_dir
                out_dir.parent / "output" / "input" / rest, # cross-sibling via output/
                run_root / "output" / "input" / rest,       # run-root → output/input/
            ]
            for candidate in candidates:
                if candidate.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if not target.exists() or target.stat().st_size != candidate.stat().st_size:
                        shutil.copy2(candidate, target)
                        bytes_copied += candidate.stat().st_size
                        files_copied.add(str(target.relative_to(out_dir)))
                    return f'{prefix}input/{rest}'
            print(f"  [WARN] missing input: {input_root / rest}")
            missing_sources.add(str(target.relative_to(out_dir)))
            return m.group(0)

        src = RX_SKILL.sub(replace_skill, src)
        src = RX_INPUT.sub(replace_input, src)

        # `./<rel-path>` deck-local refs — for cases where the deck author
        # dropped a PNG / prototype-html dir / asset directly into `output/`
        # (not into input/ or assets/shared/). When rendering into a sibling
        # dir like _preview/ or output-deckjson/, those need to be linked.
        def link_deck_local(m):
            rel = m.group(1).split('?')[0]
            # Find source: try sibling-of-out_dir first, then cross-sibling
            # via runs/<ts>/output/ (for output-deckjson/ rendering away from
            # the canonical output/ where the deck-local PNGs / prototypes live).
            src_candidates = [out_dir.parent / rel, out_dir.parent / "output" / rel]
            src_path = next((p for p in src_candidates if p.exists()), None)
            if src_path is None:
                return m.group(0)
            dst_path = out_dir / rel
            # Track so the end-of-run prune doesn't delete it.
            referenced.add(rel)
            # already in place (e.g. shared/ symlink)
            if dst_path.exists() or dst_path.is_symlink():
                return m.group(0)
            # symlink the FILE (or directory) directly
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(src_path.resolve(), dst_path)
            return m.group(0)

        re.sub(r"""(?:url\(|src=)['"]?\./([^'")\s?#]+)""", link_deck_local, src)

        # Process already-local refs (second+ runs OR pre-reorg legacy outputs):
        #  - track for prune so existing files aren't deleted
        #  - apply legacy redirect (rewriting both HTML AND moving files in
        #    place) so an output produced before the assets/shared/ reorg can
        #    be upgraded by simply re-running this script
        #  - self-heal: if the canonical target is missing, copy from skill
        def replace_local_asset(m):
            """Rewrite an already-local `assets/<path>` ref. If `<path>` is the
            legacy pre-shared/ form, also `shutil.move` the file in place.

            Idempotency across regex matches AND across HTMLs in the same run:
            the substitution return value is computed from `new_rest` (derived
            from the regex's `rest` string), NOT from filesystem state. So
            once HTML 1 has moved the legacy file to its canonical shared/
            location, HTML 2 still sees `assets/clientlogo/foo.png` in its
            text and the regex still matches and rewrites to
            `assets/shared/clientlogo/foo.png`. The move itself is skipped on
            HTML 2's call (`old_target.exists() AND not new_target.exists()`
            both fail) but the rewrite proceeds. Net effect: file moved once,
            every HTML correctly rewritten."""
            nonlocal bytes_copied
            head = m.group(1)
            # Use the per-file depth-derived `prefix` (loop scope), NOT the
            # source ref's `m.group(1)`: an inside-skill run (output under
            # skills/feishu-deck-h5/runs/) emits `../../../assets/foo` whose
            # prefix ESCAPES output/. Preserving it left the localized copy
            # orphaned and the ref pointing out of the deck → 404 after
            # move/zip/publish. The loop `prefix` is the correct climb from this
            # HTML file's dir to output/assets/ regardless of the source form.
            rest = m.group(3)

            # Compute canonical rest via legacy redirects (mirrors
            # resolve_asset but for already-local paths). If rest is the
            # legacy form, new_rest gets a shared/ prefix.
            new_rest = rest
            if not rest.startswith(SHARED_PREFIX):
                for old, new in LEGACY_DIR_REDIRECTS.items():
                    if rest.startswith(old):
                        new_rest = new + rest[len(old):]
                        break
                else:
                    # Top-level legacy filename (zoom.png / 飞书标识_*.png /
                    # 茶百道.jpg etc.) — look it up by basename in skill's
                    # shared/ tree.
                    if "/" not in rest:
                        shared_root = skill_root / "assets" / "shared"
                        if shared_root.is_dir():
                            matches = list(shared_root.rglob(rest))
                            if len(matches) == 1:
                                new_rest = str(matches[0].relative_to(skill_root / "assets"))

            # Shared refs are handled before the resolve+escape check below,
            # because in link mode `output/assets/shared` is a symlink whose
            # .resolve() escapes out_dir, which would otherwise short-circuit
            # the rewrite path. In link/skip mode no file motion is needed
            # (canonical file lives under the symlink target / under the skill).
            if new_rest.startswith(SHARED_PREFIX):
                shared_refs.add(f"assets/{new_rest}")
                if shared_mode == "skip":
                    return f"{head}{prefix}assets/{new_rest}"
                if shared_mode == "link":
                    ensure_shared_symlink(local_assets, skill_root)
                    return f"{head}{prefix}assets/{new_rest}"
                # copy mode falls through

            old_target = (out_dir / "assets" / rest).resolve()
            new_target = (out_dir / "assets" / new_rest).resolve()
            if not new_target.is_relative_to(out_dir):
                return m.group(0)

            # If we redirected, migrate the file in place (legacy → shared/).
            if new_rest != rest and old_target.exists() and not new_target.exists():
                new_target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(old_target), str(new_target))

            referenced.add(str(new_target.relative_to(out_dir)))
            if not new_target.exists():
                origin = skill_root / "assets" / new_rest
                if origin.exists():
                    new_target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(origin, new_target)
                    bytes_copied += origin.stat().st_size
                    files_copied.add(str(new_target.relative_to(out_dir)))
                else:
                    # 引用了 assets/<...> 但 output/ 和 skill 里都没有源文件（典型：
                    # 从别的 deck 克隆过来、却没带上对应封面/图）。以前这里静默放过，
                    # 文件被写进 manifest 却不在包里，直到上传才报错——左移到打包暴露。
                    print(f"  [WARN] missing asset: {new_target}")
                    missing_sources.add(str(new_target.relative_to(out_dir)))

            return f"{head}{prefix}assets/{new_rest}"

        src = RX_LOCAL_ASSET.sub(replace_local_asset, src)
        for m in RX_LOCAL_INPUT.finditer(src):
            rest = m.group(2)
            target = (out_dir / "input" / rest).resolve()
            if not target.is_relative_to(out_dir):
                continue
            referenced.add(str(target.relative_to(out_dir)))
            if not target.exists():
                origin = input_root / rest if input_root.exists() else None
                if origin is not None and origin.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(origin, target)
                    bytes_copied += origin.stat().st_size
                    files_copied.add(str(target.relative_to(out_dir)))
                else:
                    print(f"  [WARN] missing input: {target}")
                    missing_sources.add(str(target.relative_to(out_dir)))

        if src != original:
            html_path.write_text(src, encoding="utf-8")
            htmls_patched += 1
            print(f"  patched  {html_path.relative_to(out_dir)}")

    # Pass 2: scan copied CSS files for internal url() refs (e.g.
    # feishu-deck.css uses url("lark-logo.png") with no ../ prefix). These
    # would-be-broken refs need their target files alongside the CSS.
    # We resolve each ref relative to the CSS file's original skill location
    # first. This matters for CSS copied from non-assets trees such as
    # deck-json/templates: `../../assets/foo` is correct in the skill tree but
    # would become `output/assets/assets/foo` after the CSS is bundled.
    rx_css_url = re.compile(r'url\(["\']?([^"\')\s]+)["\']?\)')
    css_files = []
    for dirpath, _dirnames, filenames in os.walk(local_assets, followlinks=False):
        for name in filenames:
            if name.endswith(".css"):
                css_files.append(Path(dirpath) / name)

    def infer_css_origin(css_path: Path) -> Path | None:
        """Infer a copied CSS file's original skill path on second+ runs."""
        try:
            rel = css_path.relative_to(local_assets)
        except ValueError:
            return None
        parts = rel.parts
        candidates = []
        if len(parts) >= 2 and parts[0] == "deck-json" and parts[1] == "templates":
            candidates.append(skill_root / "deck-json" / "templates" / Path(*parts[2:]))
        if parts and parts[0] in ("examples", "templates"):
            candidates.append(skill_root / parts[0] / Path(*parts[1:]))
        candidates.append(skill_root / "assets" / rel)
        return next((p.resolve() for p in candidates if p.exists()), None)

    def local_target_for_skill_origin(origin: Path) -> Path | None:
        """Map a resolved skill-tree asset back into output/assets/."""
        asset_root = (skill_root / "assets").resolve()
        deck_json_templates = (skill_root / "deck-json" / "templates").resolve()
        templates_root = (skill_root / "templates").resolve()
        examples_root = (skill_root / "examples").resolve()
        if origin.is_relative_to(asset_root):
            return local_assets / origin.relative_to(asset_root)
        if origin.is_relative_to(deck_json_templates):
            return local_assets / "deck-json" / "templates" / origin.relative_to(deck_json_templates)
        if origin.is_relative_to(templates_root):
            return local_assets / "templates" / origin.relative_to(templates_root)
        if origin.is_relative_to(examples_root):
            return local_assets / "examples" / origin.relative_to(examples_root)
        return None

    for css_path in css_files:
        css_dir = css_path.parent
        css_src = css_path.read_text(encoding="utf-8")
        css_origin = css_origins.get(str(css_path.resolve())) or infer_css_origin(css_path)

        def replace_css_url(m):
            nonlocal bytes_copied
            ref = m.group(1)
            # Skip data: URIs, absolute URLs, SVG fragment ids (#…), and bare punctuation
            if ref.startswith(("data:", "http:", "https:", "//", "#", "%23")):
                return m.group(0)
            if ref in ("...", ""):
                return m.group(0)
            if "/" not in ref and "." not in ref:
                return m.group(0)       # not a file path
            # Resolve target relative to CSS location
            target = (css_dir / ref).resolve()
            if target.is_relative_to(out_dir) and target.exists():
                referenced.add(str(target.relative_to(out_dir)))
                return m.group(0)

            # Find the source: assume CSS lives at output/assets/* and the
            # corresponding file lives at skill_root/assets/<ref-relative>.
            origin = None
            if css_origin:
                origin_candidate = (css_origin.parent / ref).resolve()
                if origin_candidate.exists():
                    origin = origin_candidate
                    target = local_target_for_skill_origin(origin) or target
            if origin is None and target.is_relative_to(local_assets):
                rel_in_assets = target.relative_to(local_assets)
                origin_candidate = (skill_root / "assets" / rel_in_assets).resolve()
                if origin_candidate.exists():
                    origin = origin_candidate

            if origin is None:
                if target.is_relative_to(out_dir):
                    print(f"  [WARN] CSS-referenced asset not found in skill: {target}")
                    if not target.exists():
                        missing_sources.add(str(target.relative_to(out_dir)))
                return m.group(0)

            if not target.is_relative_to(out_dir):
                return m.group(0)
            new_ref = os.path.relpath(target, css_dir).replace(os.sep, "/")
            if new_ref.startswith("../"):
                # Library ZIP gate rejects any packaged reference that climbs
                # with ../. Keep non-assets CSS self-contained by placing its
                # transitive asset beside the copied CSS.
                target = css_dir / origin.name
                new_ref = origin.name
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists() or target.stat().st_size != origin.stat().st_size:
                shutil.copy2(origin, target)
                bytes_copied += origin.stat().st_size
                files_copied.add(str(target.relative_to(out_dir)))
            referenced.add(str(target.relative_to(out_dir)))
            if new_ref != ref:
                return f'url("{new_ref}")'
            return m.group(0)

        rewritten_css = rx_css_url.sub(replace_css_url, css_src)
        if rewritten_css != css_src:
            css_path.write_text(rewritten_css, encoding="utf-8")

    # Prune: remove files in output/assets/ and output/input/ that are no
    # longer referenced (e.g. left over from previous runs). Uses os.walk
    # with followlinks=False so we never descend into the output/assets/shared
    # symlink (link mode) — those files belong to the canonical pool and
    # must not be deleted by per-run housekeeping.
    pruned = 0
    pruned_bytes = 0
    for root_dir in [local_assets, local_input]:
        if not root_dir.exists():
            continue
        for dirpath, _dirnames, filenames in os.walk(root_dir, followlinks=False):
            for name in filenames:
                f = Path(dirpath) / name
                rel = str(f.relative_to(out_dir))
                if rel not in referenced:
                    pruned += 1
                    pruned_bytes += f.stat().st_size
                    f.unlink()
        # remove empty subdirs left over after prune (skip symlinked dirs)
        for dirpath, _dirnames, _filenames in os.walk(root_dir, topdown=False, followlinks=False):
            d = Path(dirpath)
            if d == root_dir or d.is_symlink():
                continue
            if not any(d.iterdir()):
                d.rmdir()

    # Emit assets-manifest.yaml — classifies every referenced file as
    # shared / framework / deck-local so downstream tools (slide library
    # ingest) can dedupe shared-pool files against their own copy.
    # `shared` comes from shared_refs (always tracked, regardless of mode);
    # `framework` and `deck-local` come from `referenced` (files in output/).
    shared_files = sorted(shared_refs)
    framework_files, deck_local_files = [], []
    for rel in sorted(referenced):
        if rel.startswith("input/"):
            deck_local_files.append(rel)
        elif rel.startswith(f"assets/{SHARED_PREFIX}"):
            continue  # captured via shared_refs
        else:
            framework_files.append(rel)

    manifest_lines = ["# Generated by copy-assets.py — do not edit by hand.",
                      "# Paths are relative to this output/ folder.",
                      f"# shared-mode: {shared_mode}",
                      "# Classification:",
                      "#   shared      — library-grade reusable content (clientlogo, digital-employee,",
                      "#                  third-party-logos, feishu-products). The slide library should",
                      "#                  dedupe these against its own assets/shared/ pool. With",
                      "#                  --shared=skip, these files are NOT in this output/; HTML refs",
                      "#                  remain skill-relative until a downstream consumer rewrites them.",
                      "#   framework   — feishu-deck CSS/JS + lark brand kit. Every deck self-contains.",
                      "#   deck-local  — deck-unique inputs (covers, custom photos). Stay deck-local.",
                      ""]
    for label, paths in (("shared", shared_files),
                         ("framework", framework_files),
                         ("deck-local", deck_local_files)):
        if paths:
            manifest_lines.append(f"{label}:")
            for p in paths:
                manifest_lines.append(f"  - {p}")
        else:
            manifest_lines.append(f"{label}: []")
    manifest_path = out_dir / "assets-manifest.yaml"
    manifest_path.write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")

    print()
    print(f"Done [shared-mode={shared_mode}]. {htmls_patched} HTML(s) patched · {len(files_copied)} unique asset(s) copied · {bytes_copied / 1024:.1f} KB copied")
    if pruned:
        print(f"      {pruned} stale file(s) pruned · {pruned_bytes / 1024:.1f} KB freed")
    if shared_skipped:
        print(f"      {shared_skipped} shared/* ref(s) left as skill-relative (not copied)")
    print(f"      manifest: {len(shared_files)} shared / {len(framework_files)} framework / {len(deck_local_files)} deck-local → {manifest_path.relative_to(out_dir.parent)}")
    if shared_mode == "copy":
        print(f"Output is now self-contained — you can move {out_dir} anywhere and the deck still runs.")
    elif shared_mode == "link":
        shared_link = local_assets / "shared"
        if shared_link.is_symlink():
            print(f"Output uses a symlink for shared/ ({shared_link} → {os.readlink(shared_link)}).")
            print(f"zip / Finder-compress / IM-upload follow symlinks and embed real files for the recipient.")
        else:
            print(f"Output had no shared/* references — no symlink created.")
    else:
        print(f"Output runs only while next to the skill folder (shared/* refs are skill-relative). Use --shared=copy before zipping/sending.")

    # ── 打包结论：把“引用了但找不到源文件”的资源汇总成醒目结尾，左移到打包阶段 ──
    # （以前这些只在循环里零散 [WARN] 一行、容易淹没，且文件照样写进 manifest，
    #   结果漏到素材网上传才被资源检查拦下。现在打包时就一次性告诉作者。）
    if missing_sources:
        real_missing = sorted(p for p in missing_sources if not _is_font_ref(p))
        font_missing = sorted(p for p in missing_sources if _is_font_ref(p))
        if real_missing:
            print()
            print(f"  ❌ {len(real_missing)} 个被引用的资源找不到源文件 —— 不补齐这些，打包上传素材网会被资源检查拦下：")
            for p in real_missing:
                print(f"       - {p}")
            print(f"     修法：把对应文件放到 output/ 里该路径下（常见于从别的 deck 克隆却没带上封面/配图），")
            print(f"           或在 deck.json / CSS 里去掉这些引用，然后重跑本脚本。")
        if font_missing:
            print()
            print(f"  ⚠️ {len(font_missing)} 个字体未找到，将回退系统字体（不影响上传，可忽略）：")
            for p in font_missing:
                print(f"       - {p}")

if __name__ == "__main__":
    main()
