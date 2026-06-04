#!/usr/bin/env bash
# QA: full-deck screenshot sweep of a rendered deck, then build montages.
#
# Usage:  bash sweep.sh <deck-dir> [N]
#   <deck-dir>  dir containing index.html (the run.sh output dir)
#   N           number of slides (default 60)
#
# Writes <deck-dir>/sweep/sNN.png and <deck-dir>/montage_*.png.
#
# Robustness notes (hard-won — see FIXLOG):
#   · macOS has no `timeout`; we poll the chrome pid with a manual cap.
#   · EACH shot needs a UNIQUE --user-data-dir, else profile-lock contention
#     makes headless Chrome hang forever.
#   · ⚠️ NEVER `pkill -f "Google Chrome"` — that kills the USER'S OWN browser.
#     Only ever kill THIS shot's tree: the launched pid + processes whose cmdline
#     carries our unique temp --user-data-dir ("$udd"). See FIXLOG F8.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DECK="${1:?usage: sweep.sh <deck-dir> [N]}"
N="${2:-60}"
DECK="$(cd "$DECK" && pwd)"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
URL="file://$DECK/index.html"
mkdir -p "$DECK/sweep"; rm -f "$DECK/sweep"/*.png
shot() {
  local h="$1" out="$DECK/sweep/s$(printf %02d "$h").png"
  local udd; udd="$(mktemp -d)"     # unique → both isolates AND lets us target-kill
  "$CHROME" --headless --disable-gpu --no-first-run --no-default-browser-check \
    --user-data-dir="$udd" --hide-scrollbars --force-device-scale-factor=1 \
    --window-size=1920,1080 --virtual-time-budget=12000 \
    --screenshot="$out" "$URL#${h}" >/dev/null 2>&1 &
  # ⚠️ virtual-time-budget is a CAP, not a fixed wait — a static page screenshots
  # as soon as it goes idle, so light pages stay fast. Image-HEAVY reconstructed
  # slides (PPTX pages carry the original multi-MB embedded blobs — e.g. two 3MB
  # full-bleed JPEGs + a 1MB content PNG on one slide) need the headroom: at the
  # old 2500ms budget Chrome screenshotted BEFORE the blobs decoded, capturing a
  # black frame → good reconstructions were falsely flagged as collapsed pages.
  # 12000ms covers the heaviest pages observed. See FIXLOG F10.
  local cpid=$! i
  for i in $(seq 1 120); do kill -0 $cpid 2>/dev/null || break; sleep 0.5; done
  # kill ONLY this shot's process tree — the launched pid, its children, and
  # any helper whose cmdline carries our unique "$udd". NEVER touch other Chrome.
  kill -9 $cpid 2>/dev/null
  pkill -9 -P $cpid 2>/dev/null
  pkill -9 -f -- "$udd" 2>/dev/null
  rm -rf "$udd"
  [ -s "$out" ] && echo "  ok $h" || echo "  MISS $h"
}
for h in $(seq 1 "$N"); do shot "$h"; done
echo "captured: $(ls "$DECK"/sweep/*.png 2>/dev/null | wc -l | tr -d ' ')/$N"
PY="python3"; [ -x "$HERE/../.venv/bin/python" ] && PY="$HERE/../.venv/bin/python"
"$PY" "$HERE/montage.py" "$DECK"
echo "SWEEP_DONE"
