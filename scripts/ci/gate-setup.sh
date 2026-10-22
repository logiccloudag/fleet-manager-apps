#!/usr/bin/env bash
# Prepares the runner for the full gate (scripts/check.sh --cluster
# --compose): a local registry (`crane registry serve`) that holds the pinned
# images with their digests, and a kind cluster whose nodes pull ghcr.io
# images from it (scripts/ci/kind-with-mirror.sh). Used by the check and
# upstream-check workflows.
#
# Usage: scripts/ci/gate-setup.sh <registry-port> <kind-node-image>
set -euo pipefail

PORT="${1:?usage: gate-setup.sh <registry-port> <kind-node-image>}"
NODE_IMAGE="${2:?usage: gate-setup.sh <registry-port> <kind-node-image>}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG="${RUNNER_TEMP:-/tmp}/registry.log"

nohup crane registry serve --address "0.0.0.0:$PORT" >"$LOG" 2>&1 &
for _ in $(seq 1 30); do
  curl -fsS "http://127.0.0.1:$PORT/v2/" >/dev/null 2>&1 && break
  sleep 1
done
curl -fsS "http://127.0.0.1:$PORT/v2/" >/dev/null || {
  echo "ERROR: the local registry did not start" >&2
  exit 1
}
IMAGE_REGISTRY="localhost:$PORT/logiccloudag/margo-images" CRANE_INSECURE=1 "$DIR/../mirror-images.sh"
"$DIR/kind-with-mirror.sh" "$PORT" "$NODE_IMAGE"
echo "gate ready: registry localhost:$PORT, kind cluster check"
