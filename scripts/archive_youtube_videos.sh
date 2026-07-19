#!/usr/bin/env bash
# archive_youtube_videos.sh
#
# Self-contained CLI for the automated YouTube video archival system.
#
# This script:
#   1. VERIFY   - Check whether a specific YouTube URL (or the whole library)
#                has been successfully archived to archive.org.
#   2. FOLLOW-UP - If a prior archival attempt FAILED and the initial request was
#                submitted more than 24 hours ago, automatically re-submit a
#                follow-up archival request.
#   3. TRACK     - Maintain a persistent JSON tracking store that records the
#                state of every (re)submitted request and lets you poll progress.
#
# It mirrors the WebApp's "Retry" logic (frontend VideoLibrary.handleRetry ->
# api.retryVideo -> POST /library/videos/{id}/retry; backend retry_video in
# routes/library.py:303): fetch state -> guard on a failure condition ->
# re-submit ("re-enqueue") -> poll until done -> per-item attempt cap so the
# loop always terminates. Here the "task" is an Archive.org upload/derive
# instead of video processing, and the trigger condition is
# "failed AND older than 24h" (per requirements) rather than "failed now".
#
# It reads the library directly from the same on-disk store the backend uses
# (backend/data/video_library.json; see backend/app/services/video_library.py
# LIBRARY_FILE) so it works even though the planned backend archiving service
# is not yet implemented. Local video files live in backend/data/videos/
# (VIDEOS_DIR), bind-mounted to the host, so deleting them frees host disk.
#
# Upload backends (used in priority order):
#   - `internetarchive` Python library (preferred; pip install internetarchive)
#   - `ia` command-line tool (falls back to it if the lib is missing)
# The archive source is the ORIGINAL YouTube video, re-downloaded locally via
# `yt-dlp` (pip install yt-dlp) into ARCHIVE_DOWNLOAD_DIR before upload — the
# internetarchive lib cannot fetch a remote URL itself. The processed local
# file in backend/data/videos/ is NOT uploaded. The transient download is
# removed after a successful upload.
# Verification uses the public archive.org metadata/tasks/download APIs via curl,
# so NO upload backend is required just to check status.
#
# IMPORTANT (safety): this script NEVER deletes local video files or mutates
# the library DB by default. Deletion + DB-update (writing archive_url) only
# happens when you pass --delete-local AND the archive is verified live.
#
# Usage:
#   ./scripts/archive_youtube_videos.sh [command] [options]
#
# Commands:
#   run            Archive every un-archived, completed YouTube video, following
#                  up on any failure older than 24h. (default)
#   verify [url]  Report archival success for a YouTube URL (or whole library
#                  if omitted). Exits 0 if verified, 1 otherwise.
#   status         Print the tracking table and exit.
#   reset <url>   Forget tracking state for a URL (forces a fresh submit).
#
# Options:
#   --url <yturl>        Target a single YouTube URL instead of the library.
#   --dry-run              Show what would happen; submit nothing.
#   --delete-local         Opt-in: delete local file + write archive_url after verify.
#   --collection <name>   Archive.org collection (default: opensource_movies)
#   --max-retries <n>    Per-video follow-up cap (default: 5)
#   --max-passes <n>     Outer loop cap (default: 30)
#   --poll-interval <s>   Seconds between derive-status polls (default: 30)
#   --poll-timeout <s>    Max seconds to wait for derive per pass (default: 3600)
#   --followup-hours <h>  Age threshold to auto re-submit (default: 24)
#
# Environment:
#   IA_ACCESS_KEY_ID / IA_SECRET_ACCESS_KEY  Archive.org S3 credentials
#             (official names; also auto-loaded from backend/.env, or set
#              legacy IA_S3_ACCESS_KEY / IA_S3_SECRET_KEY for compatibility)
#   IA_CONFIG_FILE                            Path to ia.ini (optional; alt to env)
#   ARCHIVE_LIB         Library JSON path (default backend/data/video_library.json)
#   ARCHIVE_DATA_DIR    Base data dir (default backend/data)
#   INTERNETARCHIVE_PY  Override python interpreter (default: python3)
#   MIN_DELAY_SECONDS / MAX_DELAY_SECONDS  Randomized per-request throttle range
#             (default 2 / 10); sleep a random duration in this range before
#             every archive.org request to avoid rate limiting / IP blocking.

set -euo pipefail

# ---- Paths (match the backend's on-disk layout) ----------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ARCHIVE_DATA_DIR="${ARCHIVE_DATA_DIR:-$PROJECT_ROOT/backend/data}"
ARCHIVE_LIB="${ARCHIVE_LIB:-$ARCHIVE_DATA_DIR/video_library.json}"
VIDEOS_DIR="$ARCHIVE_DATA_DIR/videos"
TRACK_FILE="$ARCHIVE_DATA_DIR/archive_tracking.json"
INTERNETARCHIVE_PY="${INTERNETARCHIVE_PY:-python3}"

# ---- Archive.org credentials ---------------------------------------------
# The internetarchive lib / ia CLI read IA_ACCESS_KEY_ID + IA_SECRET_ACCESS_KEY
# (official names). Backend creds live in backend/.env (already gitignored); we
# source it so host-side runs pick them up automatically. Backward-compat:
# also accept the legacy IA_S3_ACCESS_KEY / IA_S3_SECRET_KEY names.
BACKEND_ENV="$PROJECT_ROOT/backend/.env"
if [[ -f "$BACKEND_ENV" ]]; then
  set -a; . "$BACKEND_ENV"; set +a
fi
if [[ -n "${IA_S3_ACCESS_KEY:-}" && -z "${IA_ACCESS_KEY_ID:-}" ]]; then
  IA_ACCESS_KEY_ID="$IA_S3_ACCESS_KEY"
fi
if [[ -n "${IA_S3_SECRET_KEY:-}" && -z "${IA_SECRET_ACCESS_KEY:-}" ]]; then
  IA_SECRET_ACCESS_KEY="$IA_S3_SECRET_KEY"
fi

# ---- Rate limiting (randomized per-request delay) -------------------------
# Sleep a random duration in [MIN_DELAY_SECONDS, MAX_DELAY_SECONDS] before each
# request to archive.org to avoid rate limiting / IP blocking. Loaded from .env.
MIN_DELAY_SECONDS="${MIN_DELAY_SECONDS:-2}"
MAX_DELAY_SECONDS="${MAX_DELAY_SECONDS:-10}"

# ---- Tunables -------------------------------------------------------------
COLLECTION="${COLLECTION:-opensource_movies}"
MAX_RETRIES="${MAX_RETRIES:-5}"
MAX_PASSES="${MAX_PASSES:-30}"
POLL_INTERVAL="${POLL_INTERVAL:-30}"
POLL_TIMEOUT="${POLL_TIMEOUT:-3600}"
FOLLOWUP_HOURS="${FOLLOWUP_HOURS:-24}"
COMMAND="run"
TARGET_URL=""
DRY_RUN=0
DELETE_LOCAL=0

for bin in curl jq; do
  if ! command -v "$bin" >/dev/null 2>&1; then
    echo "Required tool not found: $bin" >&2
    exit 1
  fi
done

# ---- Argument parsing ------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    run|verify|status|reset) COMMAND="$1"; shift ;;
    --url)        TARGET_URL="$2"; shift 2 ;;
    --dry-run)    DRY_RUN=1; shift ;;
    --delete-local) DELETE_LOCAL=1; shift ;;
    --collection)  COLLECTION="$2"; shift 2 ;;
    --max-retries) MAX_RETRIES="$2"; shift 2 ;;
    --max-passes)  MAX_PASSES="$2"; shift 2 ;;
    --poll-interval) POLL_INTERVAL="$2"; shift 2 ;;
    --poll-timeout) POLL_TIMEOUT="$2"; shift 2 ;;
    --followup-hours) FOLLOWUP_HOURS="$2"; shift 2 ;;
    -h|--help)
      grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

log()  { echo "[archive] $*"; }
info() { echo "          $*"; }

# ---- Tracking store helpers (jq-backed, mirrors backend JSON persistence) ----
init_track() {
  if [[ ! -f "$TRACK_FILE" ]]; then
    echo '{}' > "$TRACK_FILE"
  fi
}
# get_track <id> -> tracking object (or empty {})
get_track() {
  jq -c --arg id "$1" '.[$id] // {}' "$TRACK_FILE"
}
# set_track <id> <json-object>
set_track() {
  local id="$1" obj="$2"
  local tmp
  tmp="$(mktemp)"
  jq --arg id "$1" --argjson obj "$obj" '.[$id] = $obj' "$TRACK_FILE" > "$tmp"
  mv "$tmp" "$TRACK_FILE"
}

# ---- Identifier / URL helpers ---------------------------------------------
sanitize_id() {
  # IA identifiers: ^[a-zA-Z0-9_.-]+$ ; prefix with namespace, lowercase.
  echo "wvs-${1,,}" | tr -c 'a-z0-9_.' '-' | sed 's/-\+/-/g'
}
now_iso() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }
# random_delay — sleep a random number of seconds in [MIN_DELAY_SECONDS,
# MAX_DELAY_SECONDS] before each request to archive.org (anti rate-limit / IP ban).
random_delay() {
  local min="${MIN_DELAY_SECONDS:-2}" max="${MAX_DELAY_SECONDS:-10}"
  # Ensure integral, ordered bounds.
  min=$(( min < 0 ? 0 : min ))
  max=$(( max < min ? min : max ))
  # awk srand() needs a bounded seed; derive one from the high-res clock + an
  # incrementing counter so consecutive calls actually differ (srand with the
  # default epoch-second seed repeats inside a tight loop).
  RANDOM_DELAY_N=${RANDOM_DELAY_N:-0}
  RANDOM_DELAY_N=$(( RANDOM_DELAY_N + 1 ))
  local ns; ns=$(date +%s%N 2>/dev/null || date +%s)
  local seed; seed=$(( (ns % 1000000000) * 31 + RANDOM_DELAY_N * 2654435761 ))
  local span=$(( (max - min) * 1000000 + 1 ))
  local usec; usec=$(awk -v s="$span" -v seed="$seed" 'BEGIN{srand(seed); print int(rand()*s)}')
  local total; total=$(awk -v b="$min" -v u="$usec" 'BEGIN{printf "%.6f", b + u/1000000}')
  info "  throttling: sleeping ${total}s before next archive.org request."
  sleep "$total"
}
# hours_since <iso> -> integer hours (0 if unparseable)
hours_since() {
  local then
  then=$(date -u -d "${1:-1970-01-01T00:00:00Z}" +%s 2>/dev/null || echo 0)
  local now; now=$(date -u +%s)
  echo $(( (now - then) / 3600 ))
}

# Resolve a YouTube URL to a library video id (matches by youtube_url).
lib_id_for_url() {
  jq -r --arg u "$1" '
    .videos | to_entries[]
    | select(.value.youtube_url == $u)
    | .key' "$ARCHIVE_LIB" | head -1
}

# ---- Archive.org ingestion backends ----------------------------------------
# Pick a backend command; echoes one of: python | ia | none
detect_backend() {
  if "$INTERNETARCHIVE_PY" -c "import internetarchive" >/dev/null 2>&1; then
    echo "python"
  elif command -v ia >/dev/null 2>&1; then
    echo "ia"
  else
    echo "none"
  fi
}

# ---- YouTube download (localization before upload) ------------------------
# The internetarchive lib CANNOT fetch a remote URL — `files` must be a local
# path / fileobj / dir. So we download the original YouTube source locally with
# yt-dlp (same approach as backend/app/services/transcription.py:165), then
# upload that real file. The downloaded copy is a transient working file.
ARCHIVE_DOWNLOAD_DIR="${ARCHIVE_DOWNLOAD_DIR:-$ARCHIVE_DATA_DIR/archive_tmp}"
# yt-dlp format: <=720p, prefer H.264/VP9, exclude AV1 (mirrors the backend).
YTDLP_FORMAT='bestvideo[height<=720][vcodec^=avc]+bestaudio/bestvideo[height<=720][vcodec^=vp9]+bestaudio/bestvideo[height<=720][vcodec!=av01]+bestaudio/best[height<=720]/best'

# download_youtube <yt_url> <id> -> echoes resolved local file path, exits 1 on failure
download_youtube() {
  local yt="$1" id="$2"
  mkdir -p "$ARCHIVE_DOWNLOAD_DIR"
  # Output template fixes the filename we expect; yt-dlp appends the real ext.
  local template="$ARCHIVE_DOWNLOAD_DIR/${id}.%(ext)s"
  if ! command -v yt-dlp >/dev/null 2>&1; then
    info "  ERROR: yt-dlp not found. Install with: pip install yt-dlp"
    return 1
  fi
  info "  downloading YouTube source via yt-dlp..."
  if ! yt-dlp -f "$YTDLP_FORMAT" -o "$template" "$yt" >/dev/null 2>&1; then
    info "  ERROR: yt-dlp failed to download $yt"
    return 1
  fi
  # Resolve the actual file (extension may differ from .mp4).
  local resolved
  resolved="$(ls -1 "$ARCHIVE_DOWNLOAD_DIR/${id}".* 2>/dev/null | head -1)"
  if [[ -z "$resolved" || ! -f "$resolved" ]]; then
    info "  ERROR: downloaded file not found at $ARCHIVE_DOWNLOAD_DIR/${id}.*"
    return 1
  fi
  echo "$resolved"
}

# do_upload <id> <identifier> <title> <youtube_url>
# Downloads the YouTube source locally, then uploads that real file path.
# Returns 0 on success, non-zero on failure. Sets UPLOAD_OK.
do_upload() {
  local id="$1" identifier="$2" title="$3" yt="$4"
  local backend; backend="$(detect_backend)"
  local rc=1

  # 1) Localize the source: download the YouTube video to a working file.
  local local_file
  if ! local_file="$(download_youtube "$yt" "$id")"; then
    UPLOAD_OK=1
    return 1
  fi
  info "  source localized: $local_file"

  if [[ "$backend" == "python" ]]; then
    info "  uploading to archive.org via internetarchive (python)..."
    IA_LOCAL="$local_file" "$INTERNETARCHIVE_PY" - "$identifier" "$title" "$COLLECTION" "$yt" <<'PY' || rc=$?
import os, sys
from internetarchive import upload
ident = sys.argv[1]; title = sys.argv[2]; coll = sys.argv[3]; yt = sys.argv[4]
fp = os.environ["IA_LOCAL"]
md = {
    "title": title,
    "mediatype": "movies",
    "collection": coll,
    "subject": ["workshop-video-search", "youtube-archive"],
    "original_url": yt,
    "source": "workshop-video-search",
}
r = upload(ident, files=[fp], metadata=md,
           access_key=os.environ.get("IA_ACCESS_KEY_ID"),
           secret_key=os.environ.get("IA_SECRET_ACCESS_KEY"),
           queue_derive=True, verify=True, retries=5, retries_sleep=5)
ok = bool(r) and all(getattr(x, "status_code", 0) == 200 for x in r)
sys.exit(0 if ok else 1)
PY
    UPLOAD_OK=$rc
  elif [[ "$backend" == "ia" ]]; then
    info "  uploading to archive.org via ia cli..."
    ia upload "$identifier" "$local_file" \
      --metadata="title:${title}" \
      --metadata="mediatype:movies" \
      --metadata="collection:${COLLECTION}" \
      --metadata="original_url:${yt}" \
      --metadata="source:workshop-video-search" \
      -H "x-archive-queue-derive:1" >/dev/null 2>&1
    UPLOAD_OK=$?
  else
    info "  ERROR: no archive backend. Install with: pip install internetarchive"
    UPLOAD_OK=1
  fi

  # 2) Clean up the transient working copy (the source of truth stays on YouTube).
  [[ -f "$local_file" ]] && rm -f "$local_file"
  return $UPLOAD_OK
}

# ---- Verification (no upload backend needed) ------------------------------
archive_file_name() {
  # Archive.org keeps the uploaded filename; we stored it in tracking.
  jq -r --arg id "$1" '.[$id].file // empty' "$TRACK_FILE"
}
# verify_live <identifier> <file> -> 0 if download URL returns HTTP 200
verify_live() {
  local identifier="$1" file="$2"
  [[ -z "$file" ]] && return 1
  local code
  code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 30 \
    "https://archive.org/download/${identifier}/${file}")
  [[ "$code" == "200" ]]
}
# poll_derive <identifier> -> echoes one of: pending | derived | error
poll_derive() {
  local identifier="$1"
  local tasks
  tasks=$(curl -s --max-time 30 "https://archive.org/metadata/${identifier}/tasks" 2>/dev/null || echo '{"tasks":[]}')
  # A task row has "task" (name) and "status" (queued/running/complete/error).
  echo "$tasks" | jq -r '
    (.tasks // [])
    | map(.status // "")
    | if any(. == "error") then "error"
      elif any(. == "complete") and (all(. != "running") and all(. != "queued")) then "derived"
      else "pending" end' 2>/dev/null || echo "pending"
}

# ---- Submit / follow-up (the retry analog) ------------------------------
# submit <id> — performs the upload and records tracking state.
submit() {
  local id="$1"
  local vid; vid="$(jq -r --arg id "$id" '.videos[$id].id // empty' "$ARCHIVE_LIB")"
  [[ -z "$vid" ]] && { info "  video $id not found in library; skipping"; return 1; }
  local yt title identifier file attempts
  yt="$(jq -r --arg id "$id" '.videos[$id].youtube_url // empty' "$ARCHIVE_LIB")"
  title="$(jq -r --arg id "$id" '.videos[$id].title // empty' "$ARCHIVE_LIB")"
  identifier="$(sanitize_id "$id")"

  # The archive source is the YouTube URL: do_upload downloads the original
  # YouTube video locally (via yt-dlp) and uploads that real file. The
  # internetarchive lib cannot fetch a remote URL itself, so localizing the
  # source before upload is required. We record the original local library
  # filename (best-effort) for tracking/verification only.
  local filepath
  filepath="$(jq -r --arg id "$id" '.videos[$id].file_path // empty' "$ARCHIVE_LIB")"
  file="$(basename "$filepath" 2>/dev/null || echo "original.mp4")"

  [[ -z "$yt" ]] && { info "  no youtube_url for $id; cannot archive"; return 1; }

  local cur; cur="$(get_track "$id" | jq -r '.attempts // 0')"
  cur=$((cur + 1))

  if (( cur > MAX_RETRIES )); then
    info "  giving up on $id after $cur attempts (exceeds max $MAX_RETRIES)."
    set_track "$id" "$(get_track "$id" | jq -c \
      --arg s "failed" --arg t "$(now_iso)" \
      '. + {state:"failed", last_attempt_at:$t}')"
    return 1
  fi

  if (( DRY_RUN )); then
    info "  [dry-run] would submit follow-up #$cur for $id -> ia item '$identifier'"
    return 0
  fi

  info "  submitting archival attempt #$cur for $id (ia item: $identifier)..."
  IA_COLLECTION="$COLLECTION" do_upload "$id" "$identifier" "$title" "$yt"
  local rc=$?

  if (( rc == 0 )); then
    set_track "$id" "$(jq -nc \
      --arg id "$id" --arg ident "$identifier" --arg file "$file" \
      --arg yt "$yt" --arg t "$(now_iso)" --argjson a "$cur" \
      '{id:$id, identifier:$ident, file:$file, youtube_url:$yt,
        state:"uploaded", submitted_at:$t, last_attempt_at:$t, attempts:$a}')"
    info "  upload accepted; deriving on archive.org..."
  else
    set_track "$id" "$(get_track "$id" | jq -c \
      --arg s "failed" --arg t "$(now_iso)" --argjson a "$cur" \
      '. + {state:"failed", last_attempt_at:$t, attempts:$a}')"
    info "  upload failed (attempt $cur)."
  fi
  return $rc
}

# Wait for derive to finish; transitions uploaded->derived/error in tracking.
wait_derive() {
  local id="$1"
  local identifier; identifier="$(get_track "$id" | jq -r '.identifier // empty')"
  [[ -z "$identifier" ]] && return 0
  local waited=0
  while (( waited < POLL_TIMEOUT )); do
    local st; st="$(poll_derive "$identifier")"
    if [[ "$st" == "derived" ]]; then
      set_track "$id" "$(get_track "$id" | jq -c --arg t "$(now_iso)" \
        '. + {state:"derived", derived_at:$t}')"
      return 0
    elif [[ "$st" == "error" ]]; then
      set_track "$id" "$(get_track "$id" | jq -c --arg t "$(now_iso)" \
        '. + {state:"failed", last_attempt_at:$t}')"
      return 1
    fi
    sleep "$POLL_INTERVAL"
    waited=$((waited + POLL_INTERVAL))
  done
  log "  derive not confirmed within ${POLL_TIMEOUT}s for $id; will re-check next pass."
  return 0
}

# Finalize: verify live + optional local deletion + DB-update (archive_url).
finalize() {
  local id="$1"
  local identifier file
  identifier="$(get_track "$id" | jq -r '.identifier // empty')"
  file="$(get_track "$id" | jq -r '.file // empty')"
  [[ -z "$identifier" || -z "$file" ]] && return 0

  if verify_live "$identifier" "$file"; then
    set_track "$id" "$(get_track "$id" | jq -c --arg u "https://archive.org/details/${identifier}" --arg t "$(now_iso)" \
      '. + {state:"verified", archive_url:$u, verified_at:$t}')"
    info "  VERIFIED live: https://archive.org/details/${identifier}"
    if (( DELETE_LOCAL )); then
      local fp; fp="$(jq -r --arg id "$id" '.videos[$id].file_path // empty' "$ARCHIVE_LIB")"
      if [[ -f "$ARCHIVE_DATA_DIR/$fp" ]]; then
        rm -f "$ARCHIVE_DATA_DIR/$fp"
        info "  deleted local file $fp (host volume freed)"
      fi
      # Write archive_url into the library DB (the DB-update step).
      local tmp; tmp="$(mktemp)"
      jq --arg id "$id" --arg u "https://archive.org/details/${identifier}" \
        '.videos[$id].archive_url = $u' "$ARCHIVE_LIB" > "$tmp"
      mv "$tmp" "$ARCHIVE_LIB"
      info "  wrote archive_url into library DB"
    fi
    return 0
  else
    set_track "$id" "$(get_track "$id" | jq -c --arg t "$(now_iso)" \
      '. + {state:"failed", last_attempt_at:$t}')"
    info "  verify FAILED: download URL not reachable for $identifier/$file"
    return 1
  fi
}

# ---- Single-target verify (Requirement 1) -------------------------------
verify_one() {
  local id="$1"
  local identifier file state
  identifier="$(get_track "$id" | jq -r '.identifier // empty')"
  state="$(get_track "$id" | jq -r '.state // "none"')"
  if [[ "$state" == "verified" ]]; then
    file="$(get_track "$id" | jq -r '.file // empty')"
    if verify_live "$identifier" "$file"; then
      info "$id ($identifier): ARCHIVED & live -> https://archive.org/details/${identifier}"
      return 0
    fi
  fi
  info "$id: NOT verified (tracking state='$state'). Needs (re)submission."
  return 1
}

# ---- Command: status -----------------------------------------------------
cmd_status() {
  log "Tracking store: $TRACK_FILE"
  jq -r '
    to_entries[] | .value
    | "\(.state)\t\(.id)\t\(.identifier // "-")\tattempts=\(.attempts // 0)\tsubmitted=\(.submitted_at // "-")"
    ' "$TRACK_FILE" 2>/dev/null \
    | column -t -s $'\t' \
    || echo "(no tracking entries yet)"
}

# ---- Command: reset ------------------------------------------------------
cmd_reset() {
  local url="$1"
  local id; id="$(lib_id_for_url "$url")"
  [[ -z "$id" ]] && { echo "URL not found in library: $url" >&2; exit 1; }
  jq --arg id "$id" 'del(.[$id])' "$TRACK_FILE" > "$(mktemp)" && \
    jq --arg id "$id" 'del(.[$id])' "$TRACK_FILE" > "$TRACK_FILE.tmp" && mv "$TRACK_FILE.tmp" "$TRACK_FILE"
  log "Reset tracking for $id ($url)."
}

# ---- Command: verify (Requirement 1) -----------------------------------
cmd_verify() {
  init_track
  if [[ -n "$TARGET_URL" ]]; then
    local id; id="$(lib_id_for_url "$TARGET_URL")"
    [[ -z "$id" ]] && { echo "URL not found in library: $TARGET_URL" >&2; exit 1; }
    verify_one "$id"
    exit $?
  fi
  # Whole library summary.
  local ok=0 need=0
  while IFS= read -r id; do
    [[ -z "$id" ]] && continue
    if verify_one "$id"; then ok=$((ok+1)); else need=$((need+1)); fi
  done < <(jq -r '.videos | keys[]' "$ARCHIVE_LIB")
  log "Verified: $ok   Needs archival: $need"
  [[ "$need" -eq 0 ]]
}

# ---- Command: run (Requirements 2 & 3) --------------------------------
cmd_run() {
  init_track
  local pass=0
  # Build the candidate id list (single URL or all youtube+completed).
  local ids=()
  if [[ -n "$TARGET_URL" ]]; then
    local tid; tid="$(lib_id_for_url "$TARGET_URL")"
    [[ -z "$tid" ]] && { echo "URL not found in library: $TARGET_URL" >&2; exit 1; }
    ids=("$tid")
  else
    while IFS= read -r id; do
      [[ -z "$id" ]] && continue
      ids+=("$id")
    done < <(jq -r '.videos | to_entries[]
      | select(.value.source=="youtube" and .value.status=="completed")
      | .key' "$ARCHIVE_LIB")
  fi

  while (( pass < MAX_PASSES )); do
    pass=$((pass + 1))
    log "Pass $pass/$MAX_PASSES — evaluating ${#ids[@]} candidate video(s)..."

    local pending=0 verified=0
    for id in "${ids[@]}"; do
      local state; state="$(get_track "$id" | jq -r '.state // "none"')"
      local submitted; submitted="$(get_track "$id" | jq -r '.submitted_at // empty')"
      local age=0
      [[ -n "$submitted" ]] && age="$(hours_since "$submitted")"

      case "$state" in
        verified)
          verified=$((verified + 1))
          ;;
        none)
          # Never attempted -> initial archival request.
          info "$id: no archival attempt yet -> submitting."
          random_delay
          submit "$id" || true
          pending=$((pending + 1))
          ;;
        uploaded)
          # Upload accepted, derive in progress -> transition.
          wait_derive "$id" && finalize "$id" || true
          ;;
        derived)
          finalize "$id" || true
          ;;
        failed)
          # Requirement 2: auto follow-up only if initial request >24h old.
          if (( age > FOLLOWUP_HOURS )); then
            info "$id: failed and ${age}h old (>${FOLLOWUP_HOURS}h) -> follow-up request."
            random_delay
            submit "$id" || true
            pending=$((pending + 1))
          else
            info "$id: failed but only ${age}h old (<${FOLLOWUP_HOURS}h); waiting before follow-up."
          fi
          ;;
        *)
          # Any other (shouldn't happen) -> leave alone.
          ;;
      esac
    done

    log "Pass $pass done — verified=$verified pending/active=${#ids[@]}."
    # Terminal condition: everything verified.
    if (( verified == ${#ids[@]} )); then
      log "All ${#ids[@]} target video(s) archived & verified. Done."
      return 0
    fi
    # Otherwise let derive progress; bounded sleep then re-loop.
    sleep "$POLL_INTERVAL"
  done

  log "Reached pass limit ($MAX_PASSES). Remaining non-verified:"
  for id in "${ids[@]}"; do
    local st; st="$(get_track "$id" | jq -r '.state // "none"')"
    [[ "$st" != "verified" ]] && info "$id -> $st"
  done
  return 1
}

# ---- Dispatch ------------------------------------------------------------
init_track
case "$COMMAND" in
  status)  cmd_status ;;
  reset)   [[ -n "$TARGET_URL" ]] && cmd_reset "$TARGET_URL" || { echo "reset requires --url <yturl>" >&2; exit 2; } ;;
  verify)  cmd_verify ;;
  run)     cmd_run ;;
esac
