#!/usr/bin/env bash
set -euo pipefail

DEFAULT_BACKEND_URL="https://animalitos-ufry.onrender.com"
BACKEND_URL="${BACKEND_URL:-$DEFAULT_BACKEND_URL}"
BACKEND_URL="${BACKEND_URL%/}"
WARMUP_ATTEMPTS="${WARMUP_ATTEMPTS:-6}"
WARMUP_WAIT_SECONDS="${WARMUP_WAIT_SECONDS:-15}"
RECOVERY_ATTEMPTS="${RECOVERY_ATTEMPTS:-18}"
RECOVERY_WAIT_SECONDS="${RECOVERY_WAIT_SECONDS:-20}"

ping_backend() {
  curl --fail-with-body --silent --show-error \
    --retry 2 --retry-delay 8 --retry-all-errors --max-time 25 \
    "${BACKEND_URL}/ping" > /dev/null
}

wait_for_backend() {
  local attempts="$1"
  local wait_seconds="$2"
  local phase="$3"
  local attempt

  for attempt in $(seq 1 "${attempts}"); do
    echo "Checking backend at ${BACKEND_URL}/ping (${phase} ${attempt}/${attempts})..."
    if ping_backend; then
      echo "Backend reachable during ${phase}."
      return 0
    fi
    if [ "${attempt}" -lt "${attempts}" ]; then
      sleep "${wait_seconds}"
    fi
  done

  return 1
}

if wait_for_backend "${WARMUP_ATTEMPTS}" "${WARMUP_WAIT_SECONDS}" "warmup"; then
  exit 0
fi

if [ -n "${RENDER_DEPLOY_HOOK_URL:-}" ]; then
  echo "Backend still unavailable after warmup. Triggering Render deploy hook..."
  curl --fail-with-body --silent --show-error \
    --retry 2 --retry-delay 10 --retry-all-errors --max-time 30 \
    -X POST "${RENDER_DEPLOY_HOOK_URL}" > /dev/null

  if wait_for_backend "${RECOVERY_ATTEMPTS}" "${RECOVERY_WAIT_SECONDS}" "recovery"; then
    echo "Backend recovered after redeploy."
    exit 0
  fi

  echo "Backend did not recover after deploy hook retries." >&2
  exit 1
fi

echo "Backend still unavailable after warmup and no deploy hook is configured." >&2
exit 1
