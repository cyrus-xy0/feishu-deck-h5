#!/usr/bin/env python3
"""Combine <deck>/sweep/sNN.png into contact-sheet montages for quick scanning.

Usage: montage.py [deck-dir]   (default: current dir; montages written there)
"""
from PIL import Image, ImageDraw
from pathlib import Path
import sys

deck = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
src = deck / "sweep"
shots = sorted(src.glob("s*.png"))
COLS, ROWS = 4, 3            # 12 per sheet
TW, TH = 470, 264           # thumb size
PAD, LBL = 12, 22
cell_w, cell_h = TW + PAD, TH + PAD + LBL
per = COLS * ROWS

sheets = (len(shots) + per - 1) // per
for s in range(sheets):
    sheet = Image.new("RGB", (COLS * cell_w + PAD, ROWS * cell_h + PAD), "#22252b")
    d = ImageDraw.Draw(sheet)
    for i in range(per):
        idx = s * per + i
        if idx >= len(shots):
            break
        r, c = divmod(i, COLS)
        x = PAD + c * cell_w
        y = PAD + r * cell_h
        n = shots[idx].stem[1:]  # "01"
        d.text((x, y), f"slide {int(n)}", fill="#9fb0c8")
        im = Image.open(shots[idx]).convert("RGB").resize((TW, TH))
        sheet.paste(im, (x, y + LBL))
    out = deck / f"montage_{s+1}.png"
    sheet.save(out)
    print("wrote", out)
