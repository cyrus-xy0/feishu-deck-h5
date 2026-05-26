# Product H5 Evals

This folder contains product-level evals for the outline -> DeckJSON -> H5
loop. The goal is to catch regressions that a single demo cannot reveal:

- different industries and user entry points
- content quality and claim discipline
- strict HTML validator compliance
- post-H5 pitch rehearsal JSON / markdown output
- browser-rendered screenshots for visual sanity

Run the full local eval with Chrome screenshots. The eval reads Feishu Base as
the source of truth and refreshes local cache copies during rendering:

```bash
python3 evals/run-product-h5-evals.py
```

Run the CI-safe version without browser screenshots:

```bash
python3 evals/run-product-h5-evals.py --skip-screenshots
```

Run the P0 generator wrapper contract check:

```bash
python3 evals/run-generator-contract.py
```

Run the Feishu Bot MVP contract check:

```bash
python3 evals/run-feishu-bot-contract.py
```

Run the P2 slide library contract check:

```bash
python3 evals/run-slide-library-contract.py
```

The script writes ignored artifacts to `runs/product-evals/<run-id>/`:

- `input/outline.json`
- `output/deck.json`
- `output/index.html`
- `output/pitch-rehearsal.json`
- `output/PITCH_REHEARSAL.md`
- `screenshots/slide-*.png` for first / middle / last slide
- `EVAL_REPORT.md`

The generator contract eval creates a real wrapper task under `runs/`, asserts
the fixed handoff artifacts plus an editable zip that contains runtime assets,
then applies a lightweight edit and verifies the generated `v001` task plus the
status/edit HTML pages.

The bot contract simulates a natural Feishu brief, verifies the 3-5 question
follow-up behavior, then answers the missing fields and asserts the bot returns
status, preview, edit, and download links for a succeeded generator task.

The slide library contract verifies the local Business Library gate, search
results with thumbnail/insert suggestions, and the "mark worth reusing" flow
that creates a review candidate from a generated task.

## Current 5 Rounds

| Round | Input Theme | Entry |
|---|---|---|
| 01 | 连锁门店执行 AI agent | 飞书 bot |
| 02 | 制造质量异常本地 agent | local-agent |
| 03 | 投研材料本地 agent | local-agent |
| 04 | 校园招聘飞书 bot | 飞书 bot |
| 05 | SaaS 客服知识 agent | 飞书 bot |

## Improvements Found In First Runs

- Screenshot capture needed `Path.as_uri()` instead of manual file URL quoting.
- Chrome headless writes screenshots but may not exit quickly on macOS, so the
  eval uses browser flags, a timeout, and first / middle / last slide sampling.
- zh-only strict mode correctly rejected Latin-only architecture subtitles
  such as `WORKFLOW` and `TRIAGE`; eval data now uses Chinese subtitles instead
  of weakening R-LANG.
