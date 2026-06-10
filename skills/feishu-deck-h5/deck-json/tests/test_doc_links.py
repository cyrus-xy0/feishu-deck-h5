"""F-264 doc-rot back-stop — two anti-drift guards for the skill's prose docs.

A literal-minded model (Codex etc.) trusts the docs verbatim. Two failure modes
that fed it bad info, now fenced:

(a) **doc-link rot** — a reference doc names an in-repo file (`assets/…`,
    `deck-json/…`, `../../references/…`) that a later refactor deleted/renamed,
    leaving a dead pointer. We scan every reference doc + subskill SKILL.md +
    the root SKILL.md for *concrete, repo-anchored* path references and assert
    the target exists. Placeholders (`<ts>`, `output/…`, globs, `foo.png`
    examples) and a small calibrated exemption set are excluded so the scan
    is signal, not noise.

    Concurrency note: this scan also covers files another session owns
    (root `SKILL.md`, `references/motion-system.md`). Any breakage found THERE
    is reported via xfail (see `test_motion_files_doc_links_xfail`) — NOT
    failed and NOT fixed here. The owning session resolves those. The
    must-stay-green assertion (`test_no_dead_doc_links`) covers only the
    non-motion docs.

(b) **type-ladder doc-sync** — the live engine ladder is the 4-tier
    `{16,24,28,48}` (derived from feishu-deck.css `--fs-*`; mirrored by
    audits.js `VIS_TIER` / `_FS_TOKEN_FALLBACK`). The retired static validator
    taught a 17-rung ladder `{10,11,12,13,14,18,22,28,38,44,52,56,64,88,100,
    132,160}` and called 24/48 errors. Assert that stale ladder literal can't
    creep back into validator-rules.md / editing-discipline.md, and that the
    real 4-tier set is present. Mirrors the doc-sync style of
    test_check_only_gate / test_type_tokens_ssot.
"""
import re
import sys
import pathlib

import pytest

SKILL_ROOT = pathlib.Path(__file__).resolve().parents[2]   # …/skills/feishu-deck-h5
ASSETS = SKILL_ROOT / "assets"
REFS = SKILL_ROOT / "references"

# Files another session owns right now (a "magic move" motion feature). We scan
# them for reporting, but never fail/fix on their breakage — see module docstring.
MOTION_FILES = {"SKILL.md", "references/motion-system.md"}

# ---------------------------------------------------------------------------
# (a) doc-link scan
# ---------------------------------------------------------------------------

# real file suffixes we resolve (illustrative `.lead`/`.tail`/etc. won't match)
_EXT = (".md", ".py", ".js", ".css", ".json", ".yaml", ".yml",
        ".html", ".sh", ".png", ".jpg", ".jpeg", ".svg")

# a backtick-wrapped token …
_TOK = re.compile(r"`([^`\n]+?)`")
# … is a placeholder (skip) if it carries any of these meta chars
_PLACEHOLDER = re.compile(r"[<>*{}~…\s]|\.\.\.")
# … is repo-anchored (consider) only if it starts with one of these prefixes
_PREFIX = re.compile(
    r"^(?:(?:\.\./)+|\./|assets/|deck-json/|references/|subskills/|templates/|log-tool/)"
)
# runtime-artifact roots that are never committed skill files (examples in docs)
_ARTIFACT_PREFIX = re.compile(r"^(?:\.\./)*(?:runs|output|examples|input|log)/")

# Calibrated exemptions: tokens that are deliberately illustrative or describe
# back-compat / not-yet-built paths (verified 2026-06-10). Keep this list TIGHT
# and documented — every entry is a known non-reference, not a hidden dead link.
_EXEMPT_BASENAME = re.compile(r"(?:^|/)(?:foo|zoom|飞书标识_AI_Color)\.\w+$")
_EXEMPT_EXACT = {
    "assets/dom-ops.py",   # editing-discipline.md: "may be added later"
}


def _doc_files():
    files = sorted(REFS.glob("*.md"))
    files += sorted(SKILL_ROOT.glob("subskills/*/SKILL.md"))
    root_skill = SKILL_ROOT / "SKILL.md"
    if root_skill.exists():
        files.append(root_skill)
    return files


def _candidate_refs(text):
    """Yield concrete, repo-anchored path tokens worth resolving."""
    for m in _TOK.finditer(text):
        tok = m.group(1).strip()
        if not tok.endswith(_EXT):
            continue
        if _PLACEHOLDER.search(tok):
            continue
        if not _PREFIX.match(tok):
            continue
        if _ARTIFACT_PREFIX.match(tok):
            continue
        if _EXEMPT_BASENAME.search(tok):
            continue
        if tok in _EXEMPT_EXACT:
            continue
        yield tok


def _resolve(doc_path, tok):
    """Resolve a token to an absolute path (doc-relative for ../ and ./)."""
    if tok.startswith(("../", "./")):
        return (doc_path.parent / tok).resolve()
    return (SKILL_ROOT / tok).resolve()


def _scan_dead_links():
    """Return {rel_doc: [(tok, resolved_str), …]} for tokens whose target
    is missing, across ALL scanned docs (motion files included)."""
    dead = {}
    for doc in _doc_files():
        rel = doc.relative_to(SKILL_ROOT).as_posix()
        for tok in _candidate_refs(doc.read_text(encoding="utf-8")):
            if not _resolve(doc, tok).exists():
                dead.setdefault(rel, []).append(tok)
    return dead


def test_scan_finds_real_references():
    """Sanity: the scanner actually picks up genuine cross-references (so an
    empty 'no dead links' result means 'all resolved', not 'scanned nothing').
    The `../../…` cross-refs live in subskills/*/SKILL.md (parent is
    subskills/<name>/, so `../../assets` correctly = the skill root)."""
    per_doc = {}
    for doc in _doc_files():
        per_doc[doc.relative_to(SKILL_ROOT).as_posix()] = set(
            _candidate_refs(doc.read_text(encoding="utf-8")))
    val = per_doc.get("subskills/validator/SKILL.md", set())
    # these concrete refs are known to live in the validator subskill + on disk
    assert "../../assets/audits.js" in val
    assert "../../deck-json/validate-deck.py" in val
    # and they resolve (doc-relative — the same way the real scan resolves)
    doc = SKILL_ROOT / "subskills" / "validator" / "SKILL.md"
    for tok in ("../../assets/audits.js", "../../deck-json/validate-deck.py"):
        assert _resolve(doc, tok).exists()


def test_no_dead_doc_links():
    """Every concrete repo-anchored path reference in the NON-motion docs must
    point at a file that exists. Guards against the next refactor leaving a
    dead pointer that misleads a literal-minded model."""
    dead = {f: toks for f, toks in _scan_dead_links().items()
            if f not in MOTION_FILES}
    assert not dead, (
        "dead in-repo doc links (file → missing tokens):\n"
        + "\n".join(f"  {f}: {toks}" for f, toks in sorted(dead.items()))
    )


def test_motion_files_doc_links_xfail():
    """Concurrency carve-out: the motion session owns SKILL.md / motion-system.md.
    If they currently carry a dead link we surface it (xfail) WITHOUT failing the
    suite or touching their files — the owning session fixes it. xpasses today
    (no breakage found 2026-06-10); if it ever xfails, the message names the
    tokens for the coordinator."""
    dead = {f: toks for f, toks in _scan_dead_links().items()
            if f in MOTION_FILES}
    if dead:
        pytest.xfail(
            "pre-existing dead links in motion-session files (NOT ours to fix): "
            + "; ".join(f"{f} -> {toks}" for f, toks in sorted(dead.items()))
        )
    # no breakage → assert clean so the carve-out can't silently hide future rot
    assert dead == {}


# ---------------------------------------------------------------------------
# (b) type-ladder doc-sync
# ---------------------------------------------------------------------------

# the retired 17-rung ladder, as a regex signature (whitespace-tolerant). Its
# leading run 10,11,12,13,14 never appears in the live 4-tier doc, so it's a
# precise fingerprint for the stale ladder leaking back in.
_OLD_LADDER_SIG = re.compile(r"10\s*,\s*11\s*,\s*12\s*,\s*13\s*,\s*14")

_LADDER_DOCS = ("validator-rules.md", "editing-discipline.md")


def _engine_tiers():
    """The 4-tier ladder as the live engine defines it — extracted from
    audits.js (VIS_TIER literal + the --fs-* fallback dict). Both must agree."""
    js = (ASSETS / "audits.js").read_text(encoding="utf-8")
    m = re.search(r"VIS_TIER\s*=\s*new Set\(\[([0-9,\s]+)\]\)", js)
    assert m, "could not locate VIS_TIER literal in audits.js"
    vis = {int(x) for x in m.group(1).split(",") if x.strip()}
    # NOTE: this regex has exactly ONE capturing group, so re.findall returns a
    # list of strings (each the matched number) — do NOT tuple-unpack it.
    fb = {int(v) for v in re.findall(
        r"'--fs-(?:title|sub|body|foot)'\s*:\s*(\d+)", js)}
    assert vis == fb, f"audits.js VIS_TIER {vis} != --fs-* fallback {fb}"
    return vis


def test_engine_ladder_is_four_tier():
    assert _engine_tiers() == {16, 24, 28, 48}


def test_docs_have_no_stale_17_rung_ladder():
    """The pre-migration 17-rung ladder literal must not reappear in the rule
    docs — it taught R06>=14 / R20 on a 17-step set and called 24/48 errors."""
    offenders = []
    for name in _LADDER_DOCS:
        if _OLD_LADDER_SIG.search((REFS / name).read_text(encoding="utf-8")):
            offenders.append(name)
    assert not offenders, (
        f"stale 17-rung type ladder literal found in: {offenders} — "
        "the live ladder is the 4-tier {16,24,28,48} (feishu-deck.css --fs-*)"
    )


def test_docs_state_the_four_tier_ladder():
    """The current 4-tier set must be present in both rule docs, so they
    positively teach the live ladder (not merely lack the old one)."""
    tiers = sorted(_engine_tiers())                       # [16, 24, 28, 48]
    sig = re.compile(
        r"\{\s*" + r"\s*,\s*".join(str(t) for t in tiers) + r"\s*\}"
    )
    for name in _LADDER_DOCS:
        txt = (REFS / name).read_text(encoding="utf-8")
        assert sig.search(txt), (
            f"{name} should state the live 4-tier ladder {{16, 24, 28, 48}}"
        )


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn(); print(f"  ok  {fn.__name__}")
        except Exception:
            failed += 1; print(f"FAIL  {fn.__name__}"); traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
