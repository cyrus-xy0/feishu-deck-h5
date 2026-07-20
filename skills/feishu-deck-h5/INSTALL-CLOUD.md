# Cloud and container installation

This file covers Codex/Mira/container/readonly-mount installations. The
machine-owned dependency source is `references/dependency-policy.yaml`; do not
maintain a second prose-only dependency matrix.

## Requirements

All profiles require:

- Bash
- Python 3.10 or newer
- a writable persistent directory, or a writable bootstrap destination

Generation, editing, PPTX conversion, publishing, and library import also require
Playwright plus a working Chromium launch. Installing only the Python package is
not sufficient:

```bash
python3 -m pip install playwright
python3 -m playwright install chromium
# Debian/Ubuntu containers also need Chromium shared libraries:
playwright install-deps chromium
```

Linux screenshot/visual validation needs a CJK font:

```bash
apt-get install -y fonts-noto-cjk
```

Optional workflows may additionally require PyYAML/BeautifulSoup. The profile
checker reports only dependencies required by the requested capability.

## Capability profiles

Run preflight with the profile you intend to use:

```bash
bash assets/preflight.sh --profile core
bash assets/preflight.sh --profile generate
bash assets/preflight.sh --profile edit
bash assets/preflight.sh --profile pptx
bash assets/preflight.sh --profile template
bash assets/preflight.sh --profile publish
bash assets/preflight.sh --profile miaoda-publish
bash assets/preflight.sh --profile import
```

Machine callers can request a final JSON status:

```bash
bash assets/preflight.sh --profile generate --json
```

Profiles are defined in `references/dependency-policy.yaml` and checked by
`assets/check-profile.py`:

- `core`: static repository/DeckJSON tooling; no browser promise.
- `generate`: renderer/validator plus a successful Chromium launch.
- `edit`: generation requirements plus Editor.
- `pptx`: generation requirements plus sibling `pptx-to-deck`, a probed Python
  runtime with `python-pptx` + `lxml`, and `assets/build_pptx.py`.
- `template`: Template Pack schemas/runtime plus sibling `pptx-to-deck`, the
  same probed Python runtime, and `assets/extract_template.py`; extraction itself
  does not require Chromium.
- `publish`: publisher, Node uploader, and Chromium self-check.
- `miaoda-publish`: independent Miaoda HTML apps plus the shared navigation app;
  requires `lark-cli`.
- `import`: importer, `gh`, and Chromium quality gate.

A missing capability returns non-zero. PPTX parsing must not report success when
the sibling backend is absent.

## Readonly mounts

`preflight.sh` mirrors a readonly skill into
`${FS_DECK_WORKSPACE:-$PWD/.feishu-deck-h5-workspace}` using rsync or Python.
When it prints `PREFLIGHT BOOTSTRAPPED`:

1. `cd` to the printed writable workspace.
2. Run the same profile again there.
3. Continue only after `PREFLIGHT OK`.

The mirror intentionally excludes `runs/`, VCS data, caches, backups, and
virtualenvs. For `pptx`/`template`, an adjacent packaged `pptx-to-deck` sibling
is also copied beside the writable controller workspace; preflight prints the
exact bootstrap command. If the source package did not contain that sibling,
the profile still fails rather than claiming conversion succeeded.

## Lean packages

Build the skill package with:

```bash
bash assets/package-skill.sh --verify
```

The archive contains both active sibling directories, `feishu-deck-h5/` and
`pptx-to-deck/`, so extracting it directly into the harness skill root makes the
PPTX backend discoverable without repository access. It deliberately excludes
machine-specific virtualenvs: run `pptx-to-deck/assets/bootstrap.sh` on the
target, then run the `pptx` profile. Native Keynote conversion is retired;
request `.pptx` or `.pdf`.

## Post-install verification

Use both checks:

```bash
bash assets/check-mira.sh
bash assets/preflight.sh --profile generate
```

`check-mira.sh` checks package shape and lightweight syntax. Profile preflight is
the authoritative capability check and launches Chromium when the profile needs
visual validation.

For CJK verification on Linux:

```bash
fc-list :lang=zh | head
```

## Exit codes

- `0`: capability is ready, or a readonly copy was bootstrapped and must be
  rechecked from its new location.
- `1`: required skill files are missing.
- `2`: readonly skill cannot be mirrored.
- `3`: ephemeral output-only directory.
- `4`: Python/runtime syntax prerequisite failure.
- `5`: requested profile dependency is unavailable.
- `64`: invalid preflight arguments.

## Environment variables

- `FS_DECK_WORKSPACE`: writable mirror destination for readonly mounts.
- `FS_DECK_NOCACHE=1`: refresh the cross-clone diagnostic scan.

UTF-8 text I/O is explicit in the Python tools, but containers should still use
`LANG=C.UTF-8` so shell output and browser/font behavior remain predictable.
