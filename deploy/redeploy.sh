#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
LOCK_FILE="${LOCK_FILE:-${REPO_DIR}/deploy/.redeploy.lock}"
LOG_FILE="${LOG_FILE:-${REPO_DIR}/deploy/deploy.log}"

mkdir -p "$(dirname "${LOCK_FILE}")"
mkdir -p "$(dirname "${LOG_FILE}")"

exec 9>"${LOCK_FILE}"
if ! flock -n 9; then
  echo "[$(date -Is)] redeploy already running" | tee -a "${LOG_FILE}"
  exit 0
fi

log() {
  echo "[$(date -Is)] $*" | tee -a "${LOG_FILE}"
}

cd "${REPO_DIR}"

log "building and restarting containers from runner workspace"
docker compose up -d --build --remove-orphans
log "redeploy complete"
