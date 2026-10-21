#!/usr/bin/env bash
# Publishes the compose package of every app with a compose profile (or of
# the named app directories) to the compose registry (default
# ghcr.io/logiccloudag/margo-compose), where app/margo.yaml points:
#
#   <registry>/<app id>:<revision>
#
# The package is an OCI artifact as defined by the Margo "Compose Component
# Registry" (margo/specification PR #200):
#   artifactType  application/vnd.org.margo.component.compose+json
#   one layer     application/vnd.org.margo.component.compose.tar+gzip, a
#                 .tar.gz of helm-<app>/compose under one top-level directory
#                 named after the component (built deterministically by
#                 scripts/lib/margo_check.py, so the same files always give
#                 the same digest)
#   annotations   org.margo.component.type=compose and
#                 org.margo.component.version=<revision> on the layer and
#                 the manifest, plus org.opencontainers.image.* ones
#
# The package is checked first (scripts/check.sh "compose package"). A
# revision that already exists is never overwritten: the same layer digest
# is skipped, a different one is an error (bump the revision instead).
# After each push the manifest is read back and compared.
#
# Usage: scripts/publish-compose.sh [--dry-run] [app-dir...]
#
# Environment (all optional):
#   COMPOSE_REGISTRY  default ghcr.io/logiccloudag/margo-compose
#   ORAS_PLAIN_HTTP   1: talk to COMPOSE_REGISTRY over plain HTTP (a local
#                     test registry)
#
# Before the first push, log in with a token that has write:packages, for
# example in GitHub Actions:
#   echo "$GITHUB_TOKEN" | oras login ghcr.io -u "$GITHUB_ACTOR" --password-stdin
# New ghcr.io packages are private; make each one public afterwards (see
# README.md "Publishing").
set -euo pipefail

# shellcheck source=scripts/lib/charts.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/charts.sh"

ARTIFACT_TYPE="application/vnd.org.margo.component.compose+json"
LAYER_TYPE="application/vnd.org.margo.component.compose.tar+gzip"

DRY_RUN=0
APPS=()
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    -h | --help)
      sed -n '2,/^set -euo/p' "$0" | sed -e '$d' -e 's/^# \{0,1\}//'
      exit 0
      ;;
    -*) die "unknown option $arg" ;;
    *) APPS+=("${arg%/}") ;;
  esac
done

require_tools oras python3 jq
python3 -c 'import yaml' 2>/dev/null || die "python3 has no PyYAML (pip install pyyaml)"
PLAIN=()
[ "${ORAS_PLAIN_HTTP:-0}" != 1 ] || PLAIN=(--plain-http)
PY="$REPO_ROOT/scripts/lib/margo_check.py"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# layer_digest <ref>: digest of the single layer of <ref>, empty when <ref>
# does not exist.
layer_digest() {
  oras manifest fetch ${PLAIN[@]+"${PLAIN[@]}"} "$1" 2>/dev/null | jq -r '.layers[0].digest // empty' || true
}

ROWS="$(chart_rows ${APPS[@]+"${APPS[@]}"})"
while IFS="$(printf '\t')" read -r app _chart _version _type _source _sha; do
  [ -n "$app" ] || continue
  margo="$REPO_ROOT/$app/app/margo.yaml"
  [ -n "$(python3 "$PY" components "$margo" compose)" ] || {
    log "$app: no compose profile; skipped"
    continue
  }
  out="$WORK/$app"
  mkdir -p "$out"
  if ! python3 "$PY" compose "$margo" "$REPO_ROOT/$app" "$IMAGES_TSV" "$IMAGE_REGISTRY" "$out" >"$out/check.log"; then
    grep FAIL "$out/check.log" >&2 || true
    die "$app: the compose package fails its checks (run scripts/check.sh $app)"
  fi
  read -r component repository revision <<<"$(tail -n 1 "$out/check.log")"
  ref="$COMPOSE_REGISTRY/${repository##*/}:$revision"
  file="$component.tar.gz"
  local_digest="sha256:$(sha256_of "$out/$file")"
  existing="$(layer_digest "$ref")"
  if [ -n "$existing" ]; then
    [ "$existing" = "$local_digest" ] || die "$app: $ref exists with layer $existing, not $local_digest; bump the compose revision instead of overwriting it"
    log "$app: $ref already holds the identical package; skipped"
    continue
  fi
  if [ "$DRY_RUN" = 1 ]; then
    log "$app: --dry-run: would push $file ($local_digest) to $ref"
    continue
  fi
  title="$(python3 -c 'import sys, yaml; print(yaml.safe_load(open(sys.argv[1]))["metadata"]["name"])' "$margo")"
  jq -n --arg file "$file" --arg version "$revision" --arg title "$title" '
    {
      "org.margo.component.type": "compose",
      "org.margo.component.version": $version,
      "org.opencontainers.image.version": $version,
      "org.opencontainers.image.authors": "logiccloud (https://logiccloud.io)",
      "org.opencontainers.image.description": ($title + " compose package for logiccloud orchestrate"),
      "org.opencontainers.image.source": "https://github.com/logiccloudag/fleet-manager-apps"
    } as $a
    | { "$manifest": ($a + { "org.opencontainers.image.title": $title }), ($file): $a }' >"$out/annotations.json"
  (cd "$out" && oras push ${PLAIN[@]+"${PLAIN[@]}"} "$ref" --artifact-type "$ARTIFACT_TYPE" \
    --annotation-file annotations.json "$file:$LAYER_TYPE" >/dev/null) \
    || die "$app: oras push to $ref failed (logged in with write:packages?)"
  manifest="$(oras manifest fetch ${PLAIN[@]+"${PLAIN[@]}"} "$ref")" || die "$app: cannot read back $ref"
  [ "$(jq -r '.artifactType' <<<"$manifest")" = "$ARTIFACT_TYPE" ] || die "$app: $ref has the wrong artifactType"
  [ "$(jq -r '.layers | length' <<<"$manifest")" = 1 ] || die "$app: $ref must have exactly one layer"
  [ "$(jq -r '.layers[0].mediaType' <<<"$manifest")" = "$LAYER_TYPE" ] || die "$app: $ref has the wrong layer media type"
  [ "$(jq -r '.layers[0].digest' <<<"$manifest")" = "$local_digest" ] || die "$app: the layer of $ref differs from the pushed archive"
  [ "$(jq -r '.layers[0].annotations["org.margo.component.version"]' <<<"$manifest")" = "$revision" ] \
    || die "$app: $ref lacks the layer annotation org.margo.component.version=$revision"
  log "$app: pushed $ref (layer $local_digest)"
done <<ROWS_EOF
$ROWS
ROWS_EOF
log "done"
