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
NODES="$(kind get nodes --name check)"
[ -n "$NODES" ] || {
  echo "ERROR: kind created no node" >&2
  exit 1
}
# The runner, seen from the kind nodes: the IPv4 default gateway inside a
# node (the gateway of the docker network kind). Docker's IPAM output is not
# used, because an IPv6 entry there may have no gateway.
first="$(printf '%s\n' "$NODES" | sed -n 1p)"
GATEWAY="$(docker exec "$first" ip -4 route show default | awk '{ print $3; exit }')"
case "$GATEWAY" in
  *.*.*.*) ;;
  *)
    echo "ERROR: no IPv4 default gateway in kind node $first (got '$GATEWAY')" >&2
    exit 1
    ;;
esac
for node in $NODES; do
  docker exec "$node" mkdir -p /etc/containerd/certs.d/ghcr.io
  printf 'server = "https://ghcr.io"\n\n[host."http://%s:%s"]\n  capabilities = ["pull", "resolve"]\n' "$GATEWAY" "$PORT" \
    | docker exec -i "$node" cp /dev/stdin /etc/containerd/certs.d/ghcr.io/hosts.toml
done
kubectl wait --for=condition=Ready nodes --all --timeout=180s
echo "kind cluster check: ghcr.io pulls go to http://$GATEWAY:$PORT first"
