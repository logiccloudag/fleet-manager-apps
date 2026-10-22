#!/usr/bin/env bash
# Installs the pinned CI tools (linux amd64) into <dir> and checks each
# download against its pinned SHA-256. Used by the GitHub Actions workflows.
#
# Usage: scripts/ci/install-tools.sh <dir>
set -euo pipefail

DIR="${1:?usage: install-tools.sh <dir>}"
mkdir -p "$DIR"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

HELM_VERSION=v3.22.0
HELM_SHA256=1e4ab49e429626cf6c6958d914248b78c9730803c2751b87627e171dc800e7bb
KIND_VERSION=v0.33.0
KIND_SHA256=aee6151561422756b764a4ae28e7f44cda5af5a9eead3cc9985112b1de8d8e0d
CRANE_VERSION=v0.22.1
CRANE_SHA256=0ab7a1d6932a213aed964ce97666c3077fe691c8606413674a8b3e0b9ec4cda0
ORAS_VERSION=1.3.4
ORAS_SHA256=f27adb935022d94df8dc77719c322dda592c78a0d57a6f7dcdd8d900b248c454
KUBECONFORM_VERSION=v0.8.0
KUBECONFORM_SHA256=9bc2bffbf71f261128533edaf912153948b7ff238f9a531ae6d34466ec287883

# fetch <url> <sha256> <file>: downloads with retries and checks the digest.
fetch() {
  curl -fsSL --retry 5 --retry-all-errors -o "$TMP/$3" "$1" || {
    echo "ERROR: download of $1 failed" >&2
    exit 1
  }
  echo "$2  $TMP/$3" | sha256sum -c --quiet - || {
    echo "ERROR: $1 does not match its pinned sha256 $2" >&2
    exit 1
  }
}

fetch "https://get.helm.sh/helm-$HELM_VERSION-linux-amd64.tar.gz" "$HELM_SHA256" helm.tgz
tar -xzf "$TMP/helm.tgz" -C "$TMP" linux-amd64/helm
install -m 0755 "$TMP/linux-amd64/helm" "$DIR/helm"

fetch "https://github.com/kubernetes-sigs/kind/releases/download/$KIND_VERSION/kind-linux-amd64" "$KIND_SHA256" kind
install -m 0755 "$TMP/kind" "$DIR/kind"

fetch "https://github.com/google/go-containerregistry/releases/download/$CRANE_VERSION/go-containerregistry_Linux_x86_64.tar.gz" "$CRANE_SHA256" crane.tgz
tar -xzf "$TMP/crane.tgz" -C "$TMP" crane
install -m 0755 "$TMP/crane" "$DIR/crane"

fetch "https://github.com/oras-project/oras/releases/download/v$ORAS_VERSION/oras_${ORAS_VERSION}_linux_amd64.tar.gz" "$ORAS_SHA256" oras.tgz
tar -xzf "$TMP/oras.tgz" -C "$TMP" oras
install -m 0755 "$TMP/oras" "$DIR/oras"

fetch "https://github.com/yannh/kubeconform/releases/download/$KUBECONFORM_VERSION/kubeconform-linux-amd64.tar.gz" "$KUBECONFORM_SHA256" kubeconform.tgz
tar -xzf "$TMP/kubeconform.tgz" -C "$TMP" kubeconform
install -m 0755 "$TMP/kubeconform" "$DIR/kubeconform"

"$DIR/helm" version --short
"$DIR/kind" version
echo "crane $("$DIR/crane" version)"
"$DIR/oras" version | sed -n 1p
echo "kubeconform $("$DIR/kubeconform" -v)"
echo "installed the CI tools in $DIR"
