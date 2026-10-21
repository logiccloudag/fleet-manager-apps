#!/usr/bin/env bash
# Checks without credentials that every pinned image, chart and compose
# package of the catalog is published and public, as a device pulls it:
#
#   images    crane digest <image-registry>/<name>:<tag> equals the pin
#   charts    helm pull <chart-registry>/<chart> --version <version>
#   compose   oras manifest fetch <compose-registry>/<app id>:<revision>
#
# A new ghcr.io package is private until a human makes it public (README.md
# "Publishing"); this script then names every package that still fails.
#
# Usage: scripts/verify-public.sh [app-dir...]
set -euo pipefail

# shellcheck source=scripts/lib/charts.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/charts.sh"

APPS=()
for arg in "$@"; do
  case "$arg" in
    -h | --help)
      sed -n '2,/^set -euo/p' "$0" | sed -e '$d' -e 's/^# \{0,1\}//'
      exit 0
      ;;
    -*) die "unknown option $arg" ;;
    *) APPS+=("${arg%/}") ;;
  esac
done

require_tools crane helm oras python3
PY="$REPO_ROOT/scripts/lib/margo_check.py"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
# Anonymous: empty credential stores for every tool.
export DOCKER_CONFIG="$WORK/docker" HELM_REGISTRY_CONFIG="$WORK/helm-registry.json"
mkdir -p "$DOCKER_CONFIG" "$WORK/charts"
echo '{}' >"$DOCKER_CONFIG/config.json"
ORAS_ANON=(--registry-config "$WORK/oras.json")
echo '{}' >"$WORK/oras.json"

MISSING=()
while IFS="$(printf '\t')" read -r name _upstream tag digest _apps; do
  [ -n "$name" ] || continue
  got="$(crane digest "$IMAGE_REGISTRY/$name:$tag" 2>/dev/null || true)"
  if [ "$got" = "$digest" ]; then
    log "image $IMAGE_REGISTRY/$name:$tag: public, $digest"
  else
    MISSING+=("image $IMAGE_REGISTRY/$name:$tag (got '${got:-no access}', want $digest)")
  fi
done <<EOF_IMAGES
$(image_rows ${APPS[@]+"${APPS[@]}"})
EOF_IMAGES

while IFS="$(printf '\t')" read -r app chart version _type _source _sha; do
  [ -n "$app" ] || continue
  if helm pull "$MIRROR_REGISTRY/$chart" --version "$version" -d "$WORK/charts" >/dev/null 2>&1; then
    log "chart $MIRROR_REGISTRY/$chart $version: public"
  else
    MISSING+=("chart $MIRROR_REGISTRY/$chart $version")
  fi
  if [ -n "$(python3 "$PY" components "$REPO_ROOT/$app/app/margo.yaml" compose)" ]; then
    read -r repository revision <<<"$(python3 -c '
import sys, yaml
d = yaml.safe_load(open(sys.argv[1]))
c = [c for p in d["deploymentProfiles"] if p["type"] == "compose" for c in p["components"]][0]
print(c["properties"]["repository"], c["properties"]["revision"])' "$REPO_ROOT/$app/app/margo.yaml")"
    ref="$COMPOSE_REGISTRY/${repository##*/}:$revision"
    if oras manifest fetch "${ORAS_ANON[@]}" "$ref" >/dev/null 2>&1; then
      log "compose $ref: public"
    else
      MISSING+=("compose $ref")
    fi
  fi
done <<EOF_CHARTS
$(chart_rows ${APPS[@]+"${APPS[@]}"})
EOF_CHARTS

if [ "${#MISSING[@]}" -gt 0 ]; then
  for item in "${MISSING[@]}"; do
    log "not pullable without credentials: $item"
  done
  die "${#MISSING[@]} package(s) are missing or private; make new ghcr.io packages public (README.md \"Publishing\")"
fi
log "every image, chart and compose package is public"
