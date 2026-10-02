#!/usr/bin/env bash
# Publishes the pinned charts of scripts/charts.tsv to the mirror registry
# (default oci://ghcr.io/logiccloudag/margo-charts), where app/margo.yaml
# points:
#
#   mirror   the upstream .tgz, pulled and checked against its pinned sha256,
#            is pushed unchanged (byte-identical)
#   wrapper  the chart directory of the app is packaged after its dependency
#            was downloaded and checked against its pinned sha256, then pushed
#
# A version that already exists in the registry is never overwritten: an
# identical mirror archive is skipped, any difference is an error (bump the
# version instead). After each push the archive is pulled back and compared.
#
# Usage: scripts/mirror-charts.sh [--dry-run] [app-dir...]
#
# Environment (all optional):
#   MIRROR_REGISTRY    default oci://ghcr.io/logiccloudag/margo-charts
#   MIRROR_PLAIN_HTTP  1: talk to MIRROR_REGISTRY over plain HTTP (a local
#                      test registry)
#
# Before the first push, log in with a token that has write:packages:
#   gh auth refresh -s write:packages,read:packages
#   gh auth token | helm registry login ghcr.io -u <github-user> --password-stdin
# New ghcr.io packages are private; make each one public afterwards (see
# README.md "Publishing").
set -euo pipefail

# shellcheck source=scripts/lib/charts.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/charts.sh"

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

require_tools helm
PLAIN=()
[ "${MIRROR_PLAIN_HTTP:-0}" != 1 ] || PLAIN=(--plain-http)

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# published_digest <chart> <version>: sha256 of the archive in the registry,
# empty when the version does not exist there.
published_digest() {
  local dir="$WORK/existing/$1"
  rm -rf "$dir"
  mkdir -p "$dir"
  if helm pull "$MIRROR_REGISTRY/$1" --version "$2" -d "$dir" ${PLAIN[@]+"${PLAIN[@]}"} >/dev/null 2>&1; then
    sha256_of "$dir/$1-$2.tgz"
  fi
}

# same_chart <a.tgz> <b.tgz>: the two archives have the same Chart.yaml,
# values and templates (a re-packaged wrapper differs only in timestamps).
same_chart() {
  local a="$WORK/cmp-a" b="$WORK/cmp-b"
  rm -rf "$a" "$b"
  mkdir -p "$a" "$b"
  tar -xzf "$1" -C "$a"
  tar -xzf "$2" -C "$b"
  diff -r "$a" "$b" >/dev/null
}

ROWS="$(chart_rows ${APPS[@]+"${APPS[@]}"})"
while IFS="$(printf '\t')" read -r app chart version type source sha; do
  [ -n "$app" ] || continue
  log "$app: $chart $version ($type, $source)"
  tgz="$(fetch_upstream "$chart" "$version" "$type" "$source" "$sha" "$WORK/out")"
  existing="$(published_digest "$chart" "$version")"
  if [ -n "$existing" ]; then
    if [ "$type" = mirror ] && [ "$existing" = "$(sha256_of "$tgz")" ]; then
      log "$app: $MIRROR_REGISTRY/$chart:$version already holds the identical archive; skipped"
      continue
    fi
    if [ "$type" = wrapper ] && same_chart "$tgz" "$WORK/existing/$chart/$chart-$version.tgz"; then
      log "$app: $MIRROR_REGISTRY/$chart:$version already holds the same chart content; skipped"
      continue
    fi
    die "$app: $MIRROR_REGISTRY/$chart:$version exists with different content; bump the version instead of overwriting it"
  fi
  if [ "$DRY_RUN" = 1 ]; then
    log "$app: --dry-run: would push $(basename "$tgz") (sha256 $(sha256_of "$tgz")) to $MIRROR_REGISTRY"
    continue
  fi
  helm push "$tgz" "$MIRROR_REGISTRY" ${PLAIN[@]+"${PLAIN[@]}"} >/dev/null || die "$app: helm push to $MIRROR_REGISTRY failed (logged in with write:packages?)"
  pushed="$(published_digest "$chart" "$version")"
  [ "$pushed" = "$(sha256_of "$tgz")" ] || die "$app: the archive pulled back from $MIRROR_REGISTRY differs from the pushed one"
  log "$app: pushed $MIRROR_REGISTRY/$chart:$version (sha256 $pushed)"
done <<EOF
$ROWS
EOF
log "done"
