#!/usr/bin/env bash
# Two jobs sent straight to ComfyUI's API, through the relay and its gateway:
# a mountain landscape (accepted: HTTP 200, job queued) and a brand logo (refused: HTTP 400).
# Usage: COMFYUI_URL=http://comfyui.localhost:8080 ./test/requests.sh   (PYTHON=python on Windows)
set -euo pipefail
COMFYUI_URL="${COMFYUI_URL:-http://comfyui.localhost:8080}"
ORIGIN="${ORIGIN:-$COMFYUI_URL}"   # ComfyUI checks that the Origin header matches its host name
PYTHON="${PYTHON:-python3}"
HERE="$(cd "$(dirname "$0")" && pwd)"
ANSWER="$(mktemp)"

job() {  # the text-to-image workflow of module 1, with this description in node 27
  "$PYTHON" - "$HERE/text-to-image.json" "$1" <<'PY'
import json, random, sys
workflow = json.load(open(sys.argv[1], encoding="utf-8"))
workflow["27"]["inputs"]["text"] = sys.argv[2]
workflow["3"]["inputs"]["seed"] = random.randrange(10**12)
workflow["9"]["inputs"]["filename_prefix"] = "openwebui/test"
print(json.dumps({"prompt": workflow, "client_id": "charter-test"}))
PY
}

send() {
  echo "> $1"
  job "$1" | curl -s -o "$ANSWER" -w "  HTTP %{http_code}\n" -X POST "$COMFYUI_URL/prompt" \
    -H "Content-Type: application/json" -H "Origin: $ORIGIN" --data-binary @-
  echo "  $(head -c 300 "$ANSWER")"
}

send "A mountain landscape at sunrise."                  # expected: HTTP 200, {"prompt_id": ...}
send "The Coca-Cola logo on a can, product photo."       # expected: HTTP 400, refused by the charter
