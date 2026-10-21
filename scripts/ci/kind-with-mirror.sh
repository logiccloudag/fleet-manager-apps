#!/usr/bin/env bash
# Creates a kind cluster whose nodes pull ghcr.io images from a local
# registry first (containerd hosts.toml), so the --cluster smoke test pulls
# the exact ghcr.io/logiccloudag/margo-images/<name>:<tag>@<digest>
# references before they are published. The local registry is
# `crane registry serve` on the runner, filled by scripts/mirror-images.sh
# with the same digests.
#
# Usage: scripts/ci/kind-with-mirror.sh <registry-port> <kind-node-image>
set -euo pipefail

PORT="${1:?usage: kind-with-mirror.sh <registry-port> <kind-node-image>}"
NODE_IMAGE="${2:?usage: kind-with-mirror.sh <registry-port> <kind-node-image>}"

kind create cluster --name check --image "$NODE_IMAGE" --wait 180s
# The runner, seen from the kind nodes: the IPv4 gateway of the kind network.
GATEWAY="$(docker network inspect kind | jq -r '[.[0].IPAM.Config[].Gateway | select(test("^[0-9.]+$"))][0] // empty')"
[ -n "$GATEWAY" ] || {
  echo "ERROR: no IPv4 gateway on the docker network kind" >&2
  exit 1
}
for node in $(kind get nodes --name check); do
  docker exec "$node" mkdir -p /etc/containerd/certs.d/ghcr.io
  printf 'server = "https://ghcr.io"\n\n[host."http://%s:%s"]\n  capabilities = ["pull", "resolve"]\n' "$GATEWAY" "$PORT" \
    | docker exec -i "$node" cp /dev/stdin /etc/containerd/certs.d/ghcr.io/hosts.toml
done
kubectl wait --for=condition=Ready nodes --all --timeout=180s
echo "kind cluster check: ghcr.io pulls go to http://$GATEWAY:$PORT first"
