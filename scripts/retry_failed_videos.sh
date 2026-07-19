#!/usr/bin/env bash
# retry_failed_videos.sh
#
# Automate retrying failed video-processing tasks in the Library WebApp.
#
# The script iterates through every video in the library one at a time, checks
# each video's status, and triggers a retry for any video that is in a "failed"
# state. It repeats this loop (re-checking the whole library and waiting for the
# background processing queue to drain) until every video has reached a
# "completed"/Ready state, or until a configured attempt/pass limit is hit.
#
# It mirrors the WebApp GUI's retry behaviour:
#   - GUI button -> retryVideo(id) -> POST /library/videos/{id}/retry (see
#     frontend/src/components/VideoLibrary.tsx and frontend/src/services/api.ts)
#   - Backend only re-queues a video when its status is "failed" or "pending"
#     (backend/app/routes/library.py -> retry_video), so we only retry those.
#
# Usage:
#   ./scripts/retry_failed_videos.sh [api_base_url]
#
# Environment overrides:
#   API_BASE              Base URL of the backend (default http://localhost:9091)
#   MAX_PASSES            Max outer-loop passes before giving up (default 30)
#   MAX_RETRIES_PER_VIDEO Max retry attempts per video before marking it stuck
#                         (default 5)
#   POLL_INTERVAL         Seconds between queue-status polls (default 5)
#   POLL_TIMEOUT          Max seconds to wait for the queue to drain per pass
#                         (default 600)
#   RETRY_PENDING         If set to 1, also re-trigger videos stuck in "pending"
#                         (default 0)
#   API_TIMEOUT           Per-request curl timeout in seconds (default 30)

set -euo pipefail

API_BASE="${1:-${API_BASE:-http://localhost:9091}}"
MAX_PASSES="${MAX_PASSES:-30}"
MAX_RETRIES_PER_VIDEO="${MAX_RETRIES_PER_VIDEO:-5}"
POLL_INTERVAL="${POLL_INTERVAL:-5}"
POLL_TIMEOUT="${POLL_TIMEOUT:-600}"
RETRY_PENDING="${RETRY_PENDING:-0}"
API_TIMEOUT="${API_TIMEOUT:-30}"

for bin in curl jq; do
  if ! command -v "$bin" >/dev/null 2>&1; then
    echo "Required tool not found: $bin" >&2
    exit 1
  fi
done

# Per-video retry counter, persisted in an associative array keyed by video id.
declare -A retry_count=()
# Videos we have given up on (exceeded MAX_RETRIES_PER_VIDEO).
declare -A given_up=()

log()  { echo "[retry] $*"; }
info() { echo "        $*"; }

# GET /library/videos -> emit one JSON object per video on stdout.
fetch_videos() {
  curl -s --max-time "$API_TIMEOUT" "$API_BASE/library/videos" \
    | jq -c '.videos[]?'
}

# GET /library/status -> { queueLength, processing[] }
fetch_status() {
  curl -s --max-time "$API_TIMEOUT" "$API_BASE/library/status"
}

# Trigger a retry for one video id. Returns 0 on success, non-zero otherwise.
trigger_retry() {
  local id="$1"
  local http_code
  http_code=$(curl -s --max-time "$API_TIMEOUT" -o /tmp/retry_resp.json -w "%{http_code}" \
    -X POST "$API_BASE/library/videos/$id/retry")
  if [[ "$http_code" =~ ^2 ]]; then
    return 0
  fi
  echo "$(cat /tmp/retry_resp.json 2>/dev/null)"
  return 1
}

# Wait until the background processing queue has fully drained (no queued and no
# in-progress videos). Bounded by POLL_TIMEOUT seconds.
wait_for_queue_drain() {
  local waited=0
  while (( waited < POLL_TIMEOUT )); do
    local status_json qlen proc_count
    status_json=$(fetch_status)
    qlen=$(echo "$status_json" | jq -r '.queueLength // 0')
    proc_count=$(echo "$status_json" | jq -r '(.processing | length) // 0')
    if (( qlen == 0 && proc_count == 0 )); then
      return 0
    fi
    sleep "$POLL_INTERVAL"
    waited=$((waited + POLL_INTERVAL))
  done
  log "Warning: queue did not fully drain within ${POLL_TIMEOUT}s; continuing anyway."
  return 0
}

# ---- Main loop: retry until every video is completed (Ready) -----------------
total_videos=0
pass=0

while (( pass < MAX_PASSES )); do
  pass=$((pass + 1))
  log "Pass $pass/$MAX_PASSES — fetching library status..."

  # Reset per-pass counters.
  declare -a failed_now=()
  declare -a pending_now=()
  declare -a completed_now=()
  declare -a processing_now=()
  video_count=0

  while IFS= read -r v; do
    [[ -z "$v" ]] && continue
    vid=$(echo "$v" | jq -r '.id')
    vstatus=$(echo "$v" | jq -r '.status')
    vtitle=$(echo "$v" | jq -r '.title // ""')
    video_count=$((video_count + 1))

    case "$vstatus" in
      failed)
        failed_now+=("$vid|$vtitle")
        ;;
      pending)
        pending_now+=("$vid|$vtitle")
        ;;
      processing)
        processing_now+=("$vid|$vtitle")
        ;;
      completed)
        completed_now+=("$vid")
        ;;
      *)
        info "Unknown status '$vstatus' for $vid ($vtitle) — skipping"
        ;;
    esac
  done < <(fetch_videos)

  total_videos=$video_count

  completed_count=${#completed_now[@]}
  failed_count=${#failed_now[@]}
  pending_count=${#pending_now[@]}
  processing_count=${#processing_now[@]}

  log "Library: $video_count video(s) — completed=$completed_count failed=$failed_count pending=$pending_count processing=$processing_count"

  # Terminal condition: every video is completed/Ready.
  if (( failed_count == 0 && pending_count == 0 && processing_count == 0 )); then
    if (( video_count == 0 )); then
      log "Library is empty. Nothing to do."
    else
      log "All $video_count video(s) are Ready. Done."
    fi
    exit 0
  fi

  # Iterate failed videos one at a time and trigger a retry on each.
  for entry in "${failed_now[@]:-}"; do
    [[ -z "$entry" ]] && continue
    vid="${entry%%|*}"
    vtitle="${entry#*|}"

    if [[ -n "${given_up[$vid]:-}" ]]; then
      info "Skipping $vid ($vtitle): already exceeded max retries"
      continue
    fi

    cur=${retry_count[$vid]:-0}
    cur=$((cur + 1))
    retry_count[$vid]=$cur

    if (( cur > MAX_RETRIES_PER_VIDEO )); then
      given_up[$vid]=1
      log "Giving up on $vid ($vtitle) after $cur attempts (exceeds max of $MAX_RETRIES_PER_VIDEO)."
      info "Skipping further retries for $vid ($vtitle)."
      continue
    fi

    info "Retrying [$cur/${MAX_RETRIES_PER_VIDEO}] $vid ($vtitle)..."
    if trigger_retry "$vid"; then
      info "  re-queued successfully"
    else
      info "  retry request failed: $(cat /tmp/retry_resp.json 2>/dev/null)"
    fi
  done

  # Optionally also re-trigger videos stuck in "pending" (never started).
  if [[ "$RETRY_PENDING" == "1" ]]; then
    for entry in "${pending_now[@]:-}"; do
      [[ -z "$entry" ]] && continue
      vid="${entry%%|*}"
      vtitle="${entry#*|}"
      if [[ -n "${given_up[$vid]:-}" ]]; then
        continue
      fi
      cur=${retry_count[$vid]:-0}
      cur=$((cur + 1))
      retry_count[$vid]=$cur

      if (( cur > MAX_RETRIES_PER_VIDEO )); then
        given_up[$vid]=1
        log "Giving up on $vid ($vtitle) after $cur attempts (exceeds max of $MAX_RETRIES_PER_VIDEO)."
        info "Skipping further retries for $vid ($vtitle)."
        continue
      fi

      info "Re-triggering pending [$cur/${MAX_RETRIES_PER_VIDEO}] $vid ($vtitle)..."
      if trigger_retry "$vid"; then
        info "  re-queued successfully"
      else
        info "  retry request failed: $(cat /tmp/retry_resp.json 2>/dev/null)"
      fi
    done
  fi

  # Wait for the background queue to make progress before the next pass.
  log "Waiting for the processing queue to drain before re-checking..."
  wait_for_queue_drain
done

# ---- If we exit the loop without all-Ready, report and fail -----------------
log "Reached pass limit ($MAX_PASSES) without all videos becoming Ready."
stuck=$(curl -s --max-time "$API_TIMEOUT" "$API_BASE/library/videos" \
  | jq -c '[.videos[]? | select(.status == "failed" or .status == "pending" or .status == "processing")]')
log "Remaining non-Ready videos:"
echo "$stuck" | jq -r '.[] | "  - \(.status)  \(.id)  \(.title // "")"'
exit 1
