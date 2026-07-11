#!/usr/bin/env bash
# Update yt-dlp to its latest release: pins the new version in
# backend/requirements.txt, upgrades it live in the running backend
# container (no rebuild needed for this to take effect immediately), and
# rebuilds the image so the pin survives future container recreations.
#
# Usage:
#   ./scripts/update_ytdlp.sh [--no-rebuild]
#
# yt-dlp ships frequent releases to keep up with YouTube's changes (broken
# signature/nsig extraction is the most common failure mode when it goes
# stale); run this whenever video downloads start failing with errors like
# "Requested format is not available" or "Signature extraction failed".

set -euo pipefail

REQUIREMENTS_FILE="backend/requirements.txt"
SKIP_REBUILD=false

for arg in "$@"; do
  case "$arg" in
    --no-rebuild) SKIP_REBUILD=true ;;
    *)
      echo "Unknown argument: $arg" >&2
      echo "Usage: $0 [--no-rebuild]" >&2
      exit 1
      ;;
  esac
done

if [[ ! -f "$REQUIREMENTS_FILE" ]]; then
  echo "Could not find $REQUIREMENTS_FILE (run this from the repo root)." >&2
  exit 1
fi

for bin in docker; do
  if ! command -v "$bin" >/dev/null 2>&1; then
    echo "Required tool not found: $bin" >&2
    exit 1
  fi
done

CURRENT_PIN=$(grep -oP '^yt-dlp\[default\]==\K.*' "$REQUIREMENTS_FILE" || true)
if [[ -z "$CURRENT_PIN" ]]; then
  echo "Could not find a 'yt-dlp[default]==...' line in $REQUIREMENTS_FILE" >&2
  exit 1
fi
echo "Currently pinned version: $CURRENT_PIN"

# Find whichever backend container is actually running (cpu or gpu profile).
CONTAINER=""
for name in workshop-video-search-app-gpu-1 workshop-video-search-app-cpu-1; do
  if docker ps --format '{{.Names}}' | grep -qx "$name"; then
    CONTAINER="$name"
    break
  fi
done

if [[ -z "$CONTAINER" ]]; then
  echo "No running backend container found (looked for app-gpu-1 / app-cpu-1)." >&2
  echo "Start the stack first with ./run.sh, then re-run this script." >&2
  exit 1
fi
echo "Using container: $CONTAINER"

echo "Checking latest yt-dlp release available on PyPI..."
LATEST=$(docker exec "$CONTAINER" pip index versions yt-dlp 2>/dev/null \
  | grep -oP '(?<=LATEST:\s{4})\S+' || true)

if [[ -z "$LATEST" ]]; then
  echo "Could not determine the latest version from PyPI. Aborting." >&2
  exit 1
fi
echo "Latest available version:  $LATEST"

if [[ "$LATEST" == "$CURRENT_PIN" ]]; then
  echo "Already up to date. Nothing to do."
  exit 0
fi

echo
echo "Upgrading yt-dlp $CURRENT_PIN -> $LATEST"
echo

echo "1/3 Installing new version live in $CONTAINER (takes effect immediately, no restart needed)..."
docker exec "$CONTAINER" pip install --upgrade --no-cache-dir "yt-dlp[default]==$LATEST"

echo "2/3 Updating pin in $REQUIREMENTS_FILE..."
sed -i "s/^yt-dlp\[default\]==.*/yt-dlp[default]==$LATEST/" "$REQUIREMENTS_FILE"

if [[ "$SKIP_REBUILD" == true ]]; then
  echo "3/3 Skipping image rebuild (--no-rebuild passed)."
  echo "Note: the live upgrade in step 1 only affects the currently running container;"
  echo "the NEXT time the image is rebuilt from scratch it will revert to the old pin"
  echo "unless you rebuild manually later: docker compose build app-gpu app-cpu"
else
  echo "3/3 Rebuilding image(s) so the pin survives future rebuilds/recreations..."
  docker compose build app-gpu app-cpu 2>&1 | tail -20
fi

echo
INSTALLED=$(docker exec "$CONTAINER" yt-dlp --version)
echo "Done. yt-dlp is now $INSTALLED in $CONTAINER, pinned to $LATEST in $REQUIREMENTS_FILE."
