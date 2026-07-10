# deck.zip Runtime Closure Design

## Goal

Make `feishu-deck-h5` library-mode packages fail closed before upload, using the
same runtime asset expectations as `feishu-slide-library`. A generated
`deck.zip` must not pass locally and then fail because a nested asset is missing,
empty, outside the package, or declared only in a stale manifest.

## Current state

`feishu-deck-h5` already produces the correct top-level package shape, copies
shared assets, materializes remote images, rejects unsafe ZIP members, promotes a
safe redirect target, and runs HTML plus ZIP gates. The remaining gap is depth:
the ZIP gate scans the primary HTML and directly linked CSS, while the library
follows nested HTML/CSS/JavaScript dependencies and its publication workflow
also rejects zero-byte runtime files.

The installed local skill bundle is older than cloud `main`; it does not yet
contain `materialize-remote-images.py`. Cloud changes therefore need a final
skill-bundle sync after both repositories are merged.

## Selected approach

Use a small, dependency-free closure validator in `feishu-deck-h5`, then harden
the existing library validator at the same boundary.

The alternatives considered were:

1. Run `feishu-slide-library` directly from every deck package. This guarantees
   parity but makes deck generation depend on a second repository and its Python
   environment.
2. Copy the whole library ingest stack into `feishu-deck-h5`. This is too large
   and would create a second ingest implementation.
3. Keep a focused closure scanner in the deck skill and add cross-repository
   contract tests. This preserves offline packaging and keeps responsibilities
   small. This is the selected approach.

## Architecture

### Upstream package closure

Create `skills/feishu-deck-h5/assets/ingest-asset-closure.py` as the single
source for package-local closure validation. It starts at `index.html` and:

- extracts local references from HTML attributes, inline styles, style blocks,
  CSS `url()` and `@import`, JavaScript static imports, dynamic imports, exports,
  and `new URL("path", import.meta.url)`;
- recursively traverses existing HTML, CSS, JS, MJS, and CJS files;
- rejects references that escape the package, resolve to missing files, or
  resolve to zero-byte files;
- validates every path declared by `assets-manifest.yaml` with the same
  existence, containment, and non-empty rules;
- ignores anchors, data/blob URLs, mail/tel links, and remote URLs already
  governed by the existing remote-image and iframe policies;
- emits stable issue codes and a compact closure summary.

`package-ingest.sh` will run the closure validator after remote-image
materialization and before writing `deck.zip`. Direct callers therefore receive
the same protection as `finalize.sh library` callers. `check-only.py` will call
the same validator after safe ZIP extraction, replacing its shallower asset
reference pass.

The package `ingestion-manifest.json` will retain its current required fields and
gain an `asset_closure` summary containing status, reachable file count,
manifest file count, total bytes, and a deterministic digest. The JSON schema
will accept both the pre-upload package manifest and the post-ingest importer
manifest to resolve the current filename/schema ambiguity.

### Downstream ingest hardening

Extend `feishu-slide-library` asset checks so the pre-confirm gate:

- rejects zero-byte top-level, nested, and manifest-declared assets;
- traverses JavaScript module references in addition to HTML and CSS;
- treats `.js`, `.mjs`, and `.cjs` as asset references when they are missing;
- makes runtime publication fail if an unresolved closure issue somehow bypasses
  the pre-confirm gate.

The existing missing-font fallback remains unchanged. Missing fonts continue to
fall back to system fonts, while a present-but-empty referenced file is treated
as corrupt.

## Error handling

Both repositories use stable machine-readable issue codes and include the
referencing file plus original reference in messages. Packaging exits non-zero
and does not leave a new `deck.zip` after a closure failure. Library ingest sets
`ready_for_confirm=false`; publication raises before writing an incomplete
runtime manifest.

## Testing

The upstream tests cover:

- nested iframe child with a missing script;
- nested CSS missing image;
- missing JS module import;
- zero-byte directly referenced file;
- stale manifest-only missing/empty file;
- safe complete nested package;
- package manifest closure summary;
- existing redirect, path-safety, metadata, and remote-image behavior.

The downstream tests cover the same failure classes at pre-confirm and runtime
publication boundaries. A cross-repository test generates `deck.zip` with
cloud `feishu-deck-h5` and runs the current library resource gate against it.
Both repositories are private and the existing cross-repository Actions secret
is not configured, so this test is a mandatory pre-merge local gate. Each
repository's ordinary CI still runs its own mirrored contract tests. This avoids
introducing a permanently failing workflow or silently weakening the check.

## Delivery and rollout

1. Merge the library hardening PR first so the downstream contract is final.
2. Merge the deck packaging PR with cross-repository CI green.
3. Wait for both repository checks and the slide-library Workers build.
4. Sync the cloud `feishu-deck-h5` skill into the local installed skill bundle.
5. Generate a fresh package with the installed skill and run the live library
   resource gate as the final smoke test.

No existing deck content or library assets are rewritten by this change.
