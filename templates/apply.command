#!/usr/bin/env bash
# feishu-deck-h5  ·  one-click text-apply launcher (macOS)
# Double-click this file in Finder to apply edits from texts.md back into
# index.html. The first time you run it, macOS Gatekeeper may ask you to
# right-click → Open instead.

set -e
cd "$(dirname "$0")"

echo "================================================================"
echo "  feishu-deck-h5  ·  apply texts.md → index.html"
echo "================================================================"
echo

# Pick the best Python 3 available
PY=""
for cand in python3 python; do
  if command -v "$cand" >/dev/null 2>&1; then
    if "$cand" -c 'import sys; sys.exit(0 if sys.version_info[0]==3 else 1)' 2>/dev/null; then
      PY="$cand"; break
    fi
  fi
done

if [ -z "$PY" ]; then
  echo "ERROR  Python 3 not found on this Mac."
  echo
  echo "Fix: install Xcode Command Line Tools:"
  echo "    xcode-select --install"
  echo "Then double-click this file again."
  echo
  read -p "Press Enter to close…" _
  exit 1
fi

"$PY" apply-texts.py
echo
echo "Tip: open index.html in your browser and refresh to see changes."
echo
read -p "Press Enter to close…" _
