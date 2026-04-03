#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${REPO_DIR:-$(cd -- "${SCRIPT_DIR}/.." && pwd)}"
DEPLOY_BRANCH="${DEPLOY_BRANCH:-main}"
LOCK_FILE="${LOCK_FILE:-${REPO_DIR}/deploy/.deploy.lock}"
LOG_FILE="${LOG_FILE:-${REPO_DIR}/deploy/deploy.log}"

mkdir -p "$(dirname "${LOCK_FILE}")"
mkdir -p "$(dirname "${LOG_FILE}")"

exec 9>"${LOCK_FILE}"
if ! flock -n 9; then
  echo "[$(date -Is)] deploy already running" | tee -a "${LOG_FILE}"
  exit 0
fi

log() {
  echo "[$(date -Is)] $*" | tee -a "${LOG_FILE}"
}

cd "${REPO_DIR}"

if ! git diff --quiet || ! git diff --cached --quiet; then
  log "working tree is dirty; aborting deploy"
  exit 1
fi

log "fetching origin/${DEPLOY_BRANCH}"
git fetch origin "${DEPLOY_BRANCH}"

CURRENT_COMMIT="$(git rev-parse HEAD)"
REMOTE_COMMIT="$(git rev-parse "origin/${DEPLOY_BRANCH}")"

if [[ "${CURRENT_COMMIT}" != "${REMOTE_COMMIT}" ]]; then
  log "updating repository to origin/${DEPLOY_BRANCH}"
  git checkout "${DEPLOY_BRANCH}"
  git pull --ff-only origin "${DEPLOY_BRANCH}"
else
  log "repository already up to date"
fi

log "building and restarting containers"
docker compose up -d --build --remove-orphans

log "deploy complete on commit $(git rev-parse --short HEAD)"
