# Business Library

This directory is the local P2 business slide library. It is deliberately
separate from the design kit:

- `slides/`: approved reusable business slides.
- `candidates/`: GTM-marked slides waiting for maintainer review.
- `thumbnails/`: required preview images for library cards.

Run the gate:

```bash
python3 server/slide_library.py validate
```

Search:

```bash
python3 server/slide_library.py search --industry 消费零售 --product 飞书
```

Mark a generated slide as worth reusing:

```bash
python3 server/slide_library.py mark-reuse \
  --task-id <task-id> \
  --slide-key <slide-key> \
  --industry 消费零售 \
  --product 飞书Base \
  --customer-stage 首访 \
  --deck-type 客户pitch \
  --tag 值得复用
```
