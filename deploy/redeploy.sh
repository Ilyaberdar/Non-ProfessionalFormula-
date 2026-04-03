#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
LOCK_FILE="${LOCK_FILE:-${REPO_DIR}/deploy/.redeploy.lock}"
PERSISTENT_APP_DIR="${PERSISTENT_APP_DIR:-/home/quant-intelligence/Desktop/github/Non-ProfessionalFormula-}"
ENV_FILE="${ENV_FILE:-${PERSISTENT_APP_DIR}/.env}"
LOGS_DIR="${LOGS_DIR:-${PERSISTENT_APP_DIR}/logs}"
LOG_FILE="${LOG_FILE:-${PERSISTENT_APP_DIR}/deploy/deploy.log}"

if [[ ! -f "${ENV_FILE}" && -f "${PERSISTENT_APP_DIR}/env" ]]; then
  ENV_FILE="${PERSISTENT_APP_DIR}/env"
fi

mkdir -p "$(dirname "${LOCK_FILE}")"
mkdir -p "$(dirname "${LOG_FILE}")"
mkdir -p "${LOGS_DIR}"

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
