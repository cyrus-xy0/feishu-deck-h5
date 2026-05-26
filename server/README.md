# Generator Wrapper

`server/generator.py` is the P0 productized wrapper around the skills. It turns
a request into a task directory under `runs/`, runs the renderer and validator,
and emits the fixed handoff contract:

- `deck.json`
- `index.html`
- `texts.md`
- `FEEDBACK.md`
- `assets-manifest.yaml`
- editable `.zip`
- `task.json`
- `validator-report.md`

## CLI

Create a task from a business brief:

```bash
python3 server/generator.py create --request server/examples/brief-request.json
```

Create from an existing DeckJSON source:

```bash
python3 server/generator.py create \
  --deck-json skills/feishu-deck-h5/deck-json/examples/sample-deck.json
```

Read status:

```bash
python3 server/generator.py status <task-id>
```

Regenerate from the original request:

```bash
python3 server/generator.py regenerate <task-id>
```

## HTTP

Run the local wrapper service:

```bash
python3 server/generator.py serve --host 127.0.0.1 --port 8765
```

Endpoints:

- `POST /decks` with JSON body `{ "brief": ... }`, `{ "outline": ..., "deck_json": ... }`, or `{ "deck_json": ... }`
- `GET /decks/{id}`
- `POST /decks/{id}/regenerate`
- `GET /decks/{id}/files/index.html`
- `GET /decks/{id}/files/<editable-zip>.zip`

The current brief planner is deterministic and conservative. It creates a
valid first draft and records missing information in `outline.json` and
`FEEDBACK.md`; richer GTM questioning and recipe selection should layer on top
of this wrapper rather than bypass it. Feishu Base access is mandatory for
knowledge and shared assets. Local `assets/shared/` and `.base-cache/knowledge/`
are cache copies only; use `LARK_LIBRARY_AS=bot` for Feishu bot workers and the
default user identity for local agent runs.
