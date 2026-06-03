#!/usr/bin/env bash
# upload_to_url.sh — EXAMPLE uploader (presigned PUT). Adapt to your own host.
# This sample targets a Magic-Pen-style /api/tos/sign endpoint; the host comes
# from $MAGIC_BASE_URL (no hardcoded internal address).
#   MAGIC_BASE_URL=https://your-host ./upload_to_url.sh <local-file> <object-key>
# stdout: public URL on success; exit 1 on failure.
set -eo pipefail
FILE="$1"; KEY="$2"
BASE="${MAGIC_BASE_URL:?set MAGIC_BASE_URL to your image host base}"
NAME=$(basename "$FILE"); EXT=$(echo "${NAME##*.}" | tr '[:upper:]' '[:lower:]')
case "$EXT" in
  mp4) CT=video/mp4;; mov) CT=video/quicktime;; webm) CT=video/webm;; gif) CT=image/gif;;
  png) CT=image/png;; jpg|jpeg) CT=image/jpeg;; woff2) CT=font/woff2;; svg) CT=image/svg+xml;;
  *) CT=application/octet-stream;;
esac
SIGN=$(curl -sS -X POST "$BASE/api/tos/sign" -H 'Content-Type: application/json' \
  -d "{\"filename\":\"$NAME\",\"contentType\":\"$CT\",\"key\":\"$KEY\"}")
URL=$(echo "$SIGN" | python3 -c 'import sys,json;print(json.load(sys.stdin)["data"]["signed_url"])')
PUB=$(echo "$SIGN" | python3 -c 'import sys,json;print(json.load(sys.stdin)["data"]["url"])')
[ -z "$URL" ] && { echo "sign failed: $SIGN" >&2; exit 1; }
curl -sS --fail -X PUT -H "Content-Type: $CT" --data-binary "@$FILE" --max-time 1200 "$URL" >/dev/null
echo "$PUB"
