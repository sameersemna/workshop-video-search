#!/usr/bin/env bash
# Bulk-add YouTube videos to the library from a CSV file.
#
# Usage:
#   ./scripts/bulk_add_youtube.sh [csv_file] [api_base_url]
#
# CSV format: one YouTube URL per line in the first column. Playlist URLs
# (containing "list=" or "/playlist?") are automatically expanded into their
# individual video URLs via yt-dlp. Lines starting with # are ignored. A
# header row (e.g. "url") is skipped automatically.
#
# The backend does NOT support playlist URLs directly (it will try to download
# the whole playlist into a single video's file path and fail) so this script
# expands them client-side before submitting.
#
# Videos already present in the library (matched by YouTube video ID, not
# raw URL, so query-string differences like &list=... or &t=42s don't cause
# false negatives/positives) are skipped automatically.
#
# Defaults:
#   csv_file      = scripts/videos.csv
#   api_base_url  = http://localhost:9091

set -euo pipefail

CSV_FILE="${1:-scripts/videos.csv}"
API_BASE="${2:-http://localhost:9091}"
DOCKER_CONTAINER="${DOCKER_CONTAINER:-workshop-video-search-app-gpu-1}"

if [[ ! -f "$CSV_FILE" ]]; then
  echo "CSV file not found: $CSV_FILE" >&2
  exit 1
fi

for bin in curl jq; do
  if ! command -v "$bin" >/dev/null 2>&1; then
    echo "Required tool not found: $bin" >&2
    exit 1
  fi
done

# Resolve a yt-dlp invocation: prefer a local binary, fall back to the
# backend's docker container (which already has it installed).
YTDLP_CMD=()
if command -v yt-dlp >/dev/null 2>&1; then
  YTDLP_CMD=(yt-dlp)
elif command -v docker >/dev/null 2>&1 && docker exec "$DOCKER_CONTAINER" true >/dev/null 2>&1; then
  YTDLP_CMD=(docker exec "$DOCKER_CONTAINER" yt-dlp)
else
  echo "Warning: yt-dlp not found locally and Docker container '$DOCKER_CONTAINER' is not reachable." >&2
  echo "Playlist URLs will be skipped. Set DOCKER_CONTAINER=<name> if your container has a different name." >&2
fi

# Extract the 11-char YouTube video ID from any URL shape (watch, youtu.be,
# shorts, embed, with or without extra query params) so duplicates and
# already-added videos are recognized regardless of URL formatting.
extract_video_id() {
  local url="$1"
  local id=""
  id=$(echo "$url" | grep -oP '(?<=[?&]v=)[A-Za-z0-9_-]{11}' | head -1) || true
  if [[ -z "$id" ]]; then
    id=$(echo "$url" | grep -oP '(?<=youtu\.be/)[A-Za-z0-9_-]{11}' | head -1) || true
  fi
  if [[ -z "$id" ]]; then
    id=$(echo "$url" | grep -oP '(?<=/shorts/)[A-Za-z0-9_-]{11}' | head -1) || true
  fi
  if [[ -z "$id" ]]; then
    id=$(echo "$url" | grep -oP '(?<=/embed/)[A-Za-z0-9_-]{11}' | head -1) || true
  fi
  echo "$id"
}

is_playlist_url() {
  local url="$1"
  [[ "$url" == *"list="* || "$url" == *"/playlist?"* ]]
}

echo "Cleaning up pre-existing failed entries..."
failed_entries=$(curl -s "$API_BASE/library/videos" | jq -c '.videos[] | select(.status == "failed")')
cleaned=0
if [[ -n "$failed_entries" ]]; then
  while IFS= read -r entry; do
    [[ -z "$entry" ]] && continue
    fid=$(echo "$entry" | jq -r '.id')
    ftitle=$(echo "$entry" | jq -r '.title')
    echo "  Removing failed entry: $ftitle ($fid)"
    curl -s -o /dev/null -X DELETE "$API_BASE/library/videos/$fid"
    cleaned=$((cleaned + 1))
  done <<< "$failed_entries"
fi
echo "Removed $cleaned failed entr$([ "$cleaned" -eq 1 ] && echo y || echo ies)."

echo "Fetching existing library to avoid duplicates..."
existing_ids_raw=$(curl -s "$API_BASE/library/videos" | jq -r '.videos[].youtubeUrl // empty')
declare -A existing_ids=()
while IFS= read -r u; do
  [[ -z "$u" ]] && continue
  vid=$(extract_video_id "$u")
  [[ -n "$vid" ]] && existing_ids["$vid"]=1
done <<< "$existing_ids_raw"
echo "Found ${#existing_ids[@]} existing video(s) already in the library."

declare -A seen_this_run=()
added=0
skipped_duplicate=0
skipped_unresolvable=0
skipped_playlist_no_ytdlp=0
failed=0

add_video() {
  local url="$1"
  local vid
  vid=$(extract_video_id "$url")

  if [[ -z "$vid" ]]; then
    echo "  ! Could not parse a video ID from: $url (skipping)"
    skipped_unresolvable=$((skipped_unresolvable + 1))
    return
  fi

  if [[ -n "${existing_ids[$vid]:-}" ]]; then
    echo "  - Already in library, skipping: $url"
    skipped_duplicate=$((skipped_duplicate + 1))
    return
  fi

  if [[ -n "${seen_this_run[$vid]:-}" ]]; then
    echo "  - Duplicate within this run, skipping: $url"
    skipped_duplicate=$((skipped_duplicate + 1))
    return
  fi
  seen_this_run["$vid"]=1

  local canonical_url="https://www.youtube.com/watch?v=$vid"
  echo "  Adding: $canonical_url"
  local http_status
  http_status=$(curl -s -o /tmp/bulk_add_response.json -w "%{http_code}" \
    -X POST "$API_BASE/library/videos/youtube" \
    -H "Content-Type: application/json" \
    -d "$(jq -n --arg url "$canonical_url" '{url: $url}')")

  if [[ "$http_status" == "200" || "$http_status" == "201" ]]; then
    echo "    ok"
    existing_ids["$vid"]=1
    added=$((added + 1))
  else
    echo "    failed (HTTP $http_status): $(cat /tmp/bulk_add_response.json)"
    failed=$((failed + 1))
  fi

  # Be polite to the backend (each add shells out to yt-dlp for the title).
  sleep 1
}

expand_playlist() {
  local url="$1"

  if [[ ${#YTDLP_CMD[@]} -eq 0 ]]; then
    echo "  ! Skipping playlist (no yt-dlp available): $url"
    skipped_playlist_no_ytdlp=$((skipped_playlist_no_ytdlp + 1))
    return
  fi

  echo "  Expanding playlist: $url"
  local ids
  if ! ids=$("${YTDLP_CMD[@]}" --flat-playlist --print id "$url" 2>/tmp/bulk_add_ytdlp_err.log); then
    echo "  ! Failed to expand playlist (yt-dlp error): $(cat /tmp/bulk_add_ytdlp_err.log)"
    failed=$((failed + 1))
    return
  fi

  if [[ -z "$ids" ]]; then
    echo "  ! Playlist expanded to 0 videos (private/empty/unavailable?): $url"
    return
  fi

  local count
  count=$(echo "$ids" | wc -l)
  echo "  Found $count video(s) in playlist."

  while IFS= read -r vid; do
    [[ -z "$vid" ]] && continue
    add_video "https://www.youtube.com/watch?v=$vid"
  done <<< "$ids"
}

while IFS=, read -r url _rest || [[ -n "$url" ]]; do
  # Strip Windows line endings and surrounding whitespace.
  url="$(echo "$url" | tr -d '\r' | xargs || true)"

  [[ -z "$url" || "$url" == \#* ]] && continue
  [[ "$url" == "url" || "$url" == "URL" ]] && continue
  [[ ! "$url" =~ ^https?:// ]] && continue

  echo "Processing: $url"
  if is_playlist_url "$url"; then
    expand_playlist "$url"
  else
    add_video "$url"
  fi
done < "$CSV_FILE"

echo
echo "==================== Summary ===================="
echo "Cleaned up (pre-existing failed): $cleaned"
echo "Added:                          $added"
echo "Skipped (already in library):   $skipped_duplicate"
echo "Skipped (unparseable URL):      $skipped_unresolvable"
echo "Skipped (playlist, no yt-dlp):  $skipped_playlist_no_ytdlp"
echo "Failed:                         $failed"
echo "==================================================="
echo "Check progress with: curl -s $API_BASE/library/status"
