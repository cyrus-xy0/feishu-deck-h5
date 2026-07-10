# deck.zip Runtime Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every `feishu-deck-h5` library package pass the same missing, empty, escape, manifest, and nested dependency checks that `feishu-slide-library` enforces before publication.

**Architecture:** Add one dependency-free closure scanner to `feishu-deck-h5` and wire both packaging and ZIP inspection to it. Extend the library's existing asset checks to traverse JavaScript and reject zero-byte files before confirmation, with publication as a final fail-closed boundary.

**Tech Stack:** Python 3.9+, Bash, pytest/unittest, GitHub Actions, existing `feishu-slide-library` ingest scripts.

---

### Task 1: Lock the upstream closure contract with failing tests

**Files:**
- Modify: `skills/feishu-deck-h5/deck-json/tests/test_package_deliverable.py`
- Modify: `skills/feishu-deck-h5/deck-json/tests/test_check_only_gate.py`

- [ ] **Step 1: Add package failures for nested and empty assets**

Add tests that create package roots containing:

```python
child.write_text('<script type="module" src="app.js"></script>', encoding="utf-8")
(assets / "empty.png").write_bytes(b"")
```

Assert `package-ingest.sh` returns non-zero, reports `LOCAL_REF_MISSING` or
`LOCAL_ASSET_EMPTY`, and leaves no `deck.zip`.

- [ ] **Step 2: Add ZIP inspector failures for JS and manifest drift**

Add ZIP fixtures for `import "./missing-module.js"`, a manifest-only missing
path, and a zero-byte path. Assert `CO.inspect_zip_package()` returns the stable
issue code in `errors`.

- [ ] **Step 3: Run the tests and confirm failure**

Run:

```bash
python3 -m pytest \
  skills/feishu-deck-h5/deck-json/tests/test_package_deliverable.py \
  skills/feishu-deck-h5/deck-json/tests/test_check_only_gate.py -q
```

Expected: new tests fail because the current scanner is shallow and accepts
zero-byte files.

### Task 2: Implement and wire the upstream closure validator

**Files:**
- Create: `skills/feishu-deck-h5/assets/ingest-asset-closure.py`
- Modify: `skills/feishu-deck-h5/assets/package-ingest.sh`
- Modify: `skills/feishu-deck-h5/assets/check-only.py`
- Modify: `skills/feishu-deck-h5/schema/ingestion-manifest.schema.json`

- [ ] **Step 1: Implement a dependency-free graph scanner**

Define these public interfaces:

```python
@dataclass(frozen=True)
class ClosureIssue:
    code: str
    required_by: str
    reference: str

@dataclass(frozen=True)
class ClosureReport:
    issues: tuple[ClosureIssue, ...]
    reachable_files: tuple[str, ...]
    manifest_files: tuple[str, ...]
    total_bytes: int
    digest_sha256: str

def inspect_package(package_root: Path, primary_html: Path, manifest_path: Path) -> ClosureReport:
    return ClosureScanner(package_root, primary_html, manifest_path).inspect()
```

The CLI prints JSON with the report and exits `1` when `issues` is non-empty.

- [ ] **Step 2: Make direct packaging fail closed**

After `materialize-remote-images.py`, call:

```bash
python3 "$SCRIPT_DIR/ingest-asset-closure.py" \
  "$OUT_DIR" --primary-html index.html \
  --manifest assets-manifest.yaml \
  --report "$OUT_DIR/.asset-closure.json"
```

Delete any pre-existing `deck.zip` before the check so a failed rerun cannot
leave a stale successful package.

- [ ] **Step 3: Reuse the scanner from ZIP inspection**

Load `ingest-asset-closure.py` through `importlib.util`, call
`inspect_package()` after extraction, and convert each issue to:

```python
f"{issue.code} {issue.required_by} -> {issue.reference}"
```

Remove the old primary-HTML-only asset scan from the decision path.

- [ ] **Step 4: Record closure evidence in the package manifest**

Read `.asset-closure.json` and add:

```json
"asset_closure": {
  "status": "verified",
  "reachable_file_count": 0,
  "manifest_file_count": 0,
  "total_bytes": 0,
  "digest_sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
}
```

Do not include the temporary `.asset-closure.json` file in `deck.zip`.

- [ ] **Step 5: Make the schema accept both lifecycle phases**

Change the schema to `oneOf` a package-manifest object requiring
`package_type/deck_id/primary_html/asset_closure` and the existing importer
result requiring `task_id/source/viewer_sync/library_ingest/skipped`.

- [ ] **Step 6: Run the focused upstream tests**

Run the Task 1 command. Expected: all tests pass.

### Task 3: Lock the downstream pre-confirm contract with failing tests

**Files:**
- Modify: `tests/test_skill_ingest_runtime.py`
- Modify: `tests/test_published_media.py`

- [ ] **Step 1: Add pre-confirm asset failures**

Add ZIP tests for a zero-byte referenced image, zero-byte manifest asset, and an
iframe child whose module imports `./missing-module.js`. Assert hard findings:

```python
assert any(f.code == "empty-asset-reference" and f.is_hard for f in findings)
assert any(f.code == "missing-nested-asset-reference" and f.is_hard for f in findings)
```

- [ ] **Step 2: Add publication defense tests**

Add tests that call `publish_runtime_assets()` with empty and missing JS
dependencies. Assert `RuntimeError` contains `LOCAL_ASSET_EMPTY` or
`LOCAL_REF_MISSING` and no upload occurs.

- [ ] **Step 3: Run the tests and confirm failure**

Run:

```bash
python3 -m pytest tests/test_skill_ingest_runtime.py tests/test_published_media.py -q
```

Expected: new tests fail under the current existence-only pre-confirm checks.

### Task 4: Implement downstream early rejection and defense in depth

**Files:**
- Modify: `skills/feishu-slide-library/assets/bot_ingest_mvp/asset_checks.py`
- Modify: `skills/feishu-slide-library/assets/bot_ingest_mvp/published_media.py`

- [ ] **Step 1: Add JavaScript to the asset vocabulary**

Add `.js`, `.mjs`, and `.cjs` to `ASSET_PATH_EXTENSIONS` and define
`JAVASCRIPT_EXTENSIONS`. Add static import/export/dynamic-import and
`new URL("path", import.meta.url)` extractors.

- [ ] **Step 2: Traverse JavaScript in nested validation**

Let `enqueue()` accept HTML, CSS, and JS extensions. Make
`extract_references_from_file()` return JavaScript references for JS files.

- [ ] **Step 3: Reject existing zero-byte files explicitly**

After an existing candidate is resolved, append a hard
`empty-asset-reference` or `empty-nested-asset-reference` finding when
`candidate.stat().st_size == 0`. Apply equivalent logic to manifest paths while
preserving the missing-font fallback.

- [ ] **Step 4: Make publication fail on unresolved closure**

Replace `collect_runtime_assets()` inside `publish_runtime_assets()` with
`build_runtime_asset_graph()`. If `graph.unresolved` is non-empty, raise one
`RuntimeError` containing sorted code/required-by/reference lines; otherwise
upload `graph.items`.

- [ ] **Step 5: Run the focused downstream tests**

Run the Task 3 command. Expected: all tests pass.

### Task 5: Add the cross-repository contract gate and run full verification

**Files:**
- Create: `scripts/check-library-package-contract.py`
- Modify: `skills/feishu-deck-h5/deck-json/tests/test_package_deliverable.py`

- [ ] **Step 1: Add a positive contract fixture runner**

The script creates a complete nested package, runs `package-ingest.sh`, then
invokes the checked-out library's `ingest-package.py --resource-checks-only
--no-deck-h5-gate`. It exits non-zero unless `ready_for_confirm` is true and
`blocking_issues` is empty.

- [ ] **Step 2: Confirm the cross-repository authentication boundary**

Check whether `SLIDE_LIBRARY_SYNC_TOKEN` exists and whether the existing private
cross-repository dispatch workflow has a successful run. If the secret is not
configured, do not add a guaranteed-failing workflow. Keep the script as a
mandatory local pre-merge gate and rely on the two repositories' independent CI
suites for the mirrored contract tests.

- [ ] **Step 3: Run targeted and complete local regression**

Run:

```bash
python3 -m pytest skills/feishu-deck-h5/deck-json/tests/test_package_deliverable.py \
  skills/feishu-deck-h5/deck-json/tests/test_check_only_gate.py \
  skills/feishu-deck-h5/tests/test_importer_ingest.py -q
python3 -m pytest tests/test_published_media.py tests/test_runtime_asset_publication.py \
  tests/test_asset_integrity.py tests/test_skill_ingest_runtime.py -q
python3 scripts/check-library-package-contract.py \
  --library-root ../feishu-slide-library
```

Expected: all commands exit `0`, the positive package is accepted, and the
negative fixtures are blocked upstream.

### Task 6: Publish, merge, sync, and verify production

**Files:**
- No additional source files unless CI review requires a focused correction.

- [ ] **Step 1: Commit each repository intentionally**

Use separate commits for library hardening and deck packaging/CI. Confirm
`git diff --check` and clean status after each commit.

- [ ] **Step 2: Push branches and open PRs**

Open the library PR first, then the deck PR. Include the cross-contract failure
evidence and exact test commands in both descriptions.

- [ ] **Step 3: Wait for required checks and merge**

Merge the library PR first. Rebase or refresh the deck contract workflow against
the merged library `main`, wait for green checks, then merge the deck PR.

- [ ] **Step 4: Wait for slide-library Cloudflare sync**

Confirm the merge commit's Workers build succeeds and the live viewer responds.
If the build fails, inspect the first-party workflow/Cloudflare logs and fix only
the failing scope.

- [ ] **Step 5: Sync the installed skill and run final smoke**

Update `/Users/bytedance/.codex/skills/feishu-deck-h5` from merged cloud `main`,
verify `materialize-remote-images.py` and the new closure scanner are present,
generate a fresh `deck.zip`, and run it through merged library `ingest-package.py`.

Expected final state: the installed skill, cloud deck repository, cloud library
repository, and production library ingest contract all agree.
