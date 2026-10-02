#!/usr/bin/env bash
# Shared helpers of scripts/check.sh and scripts/mirror-charts.sh: reading the
# pin table scripts/charts.tsv and producing a verified chart archive.
# Sourced, not executed. Written for bash 3.2 (macOS /bin/bash).

# The variables below are used by the sourcing scripts.
# shellcheck disable=SC2034
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CHARTS_TSV="$REPO_ROOT/scripts/charts.tsv"
# The registry the catalog points at. Overridable for a test registry.
MIRROR_REGISTRY="${MIRROR_REGISTRY:-oci://ghcr.io/logiccloudag/margo-charts}"

log() { echo "[$(basename "$0")] $*" >&2; }
die() {
  echo "[$(basename "$0")] error: $*" >&2
  exit 1
}

require_tools() {
  local tool
  for tool in "$@"; do
    command -v "$tool" >/dev/null 2>&1 || die "$tool is not installed or not on PATH"
  done
}

sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

# chart_rows [app...]: the pin rows (tab separated) of the named apps, or of
# all apps. Fails for an app that has no row.
chart_rows() {
  local app found
  if [ "$#" -eq 0 ]; then
    grep -v '^#' "$CHARTS_TSV" | grep -v '^[[:space:]]*$'
    return 0
  fi
  for app in "$@"; do
    app="${app%/}"
    found="$(awk -F '\t' -v a="$app" '$1 == a' "$CHARTS_TSV")"
    [ -n "$found" ] || die "no row for app '$app' in $CHARTS_TSV"
    printf '%s\n' "$found"
  done
}

# verify_sha <file> <expected>: fails unless the file has the pinned digest.
verify_sha() {
  local actual
  actual="$(sha256_of "$1")"
  [ "$actual" = "$2" ] || die "$(basename "$1"): sha256 $actual does not match the pin $2 in scripts/charts.tsv"
}

# fetch_upstream <chart> <version> <type> <source> <sha256> <out-dir>:
# writes <out-dir>/<chart>-<version>.tgz from the upstream source and prints
# its path. A mirror chart is the upstream archive itself, checked against
# its pinned digest. A wrapper chart is packaged from its directory after its
# dependency was downloaded and checked against the pinned digest. A local
# chart (no dependency, sha256 "-") is linted and packaged from its directory.
fetch_upstream() {
  local chart="$1" version="$2" type="$3" source="$4" sha="$5" out="$6"
  local tmp tgz deps
  tmp="$(mktemp -d)"
  case "$type" in
    mirror)
      case "$source" in
        oci://*) helm pull "$source" --version "$version" -d "$tmp" >/dev/null 2>"$tmp/pull.log" ;;
        *#*) helm pull "${source##*#}" --repo "${source%#*}" --version "$version" -d "$tmp" >/dev/null 2>"$tmp/pull.log" ;;
        *) die "$chart: unsupported source '$source' (use oci://... or <https repo>#<chart>)" ;;
      esac || {
        cat "$tmp/pull.log" >&2
        die "$chart: helm pull of $source $version failed"
      }
      tgz="$tmp/$chart-$version.tgz"
      [ -f "$tgz" ] || die "$chart: helm pull did not produce $chart-$version.tgz (is the chart name in scripts/charts.tsv right?)"
      verify_sha "$tgz" "$sha"
      ;;
    wrapper)
      cp -R "$REPO_ROOT/$source" "$tmp/src"
      rm -rf "$tmp/src/charts"
      # helm dependency build needs a repository definition for every https
      # dependency; register them in a throwaway configuration so the
      # user's own Helm repositories are neither used nor changed.
      local repo n=0
      export HELM_REPOSITORY_CONFIG="$tmp/repositories.yaml" HELM_REPOSITORY_CACHE="$tmp/repository-cache"
      while read -r repo; do
        n=$((n + 1))
        helm repo add "dep$n" "$repo" >/dev/null || die "$chart: helm repo add $repo failed"
      done <<REPOS
$(awk '$1 == "repository:" && $2 ~ /^https:\/\// { print $2 }' "$tmp/src/Chart.yaml")
REPOS
      helm dependency build "$tmp/src" >"$tmp/dep.log" 2>&1 || {
        cat "$tmp/dep.log" >&2
        die "$chart: helm dependency build of $source failed"
      }
      deps="$(find "$tmp/src/charts" -name '*.tgz' | wc -l | tr -d ' ')"
      [ "$deps" = 1 ] || die "$chart: expected exactly one dependency archive, found $deps"
      verify_sha "$(find "$tmp/src/charts" -name '*.tgz')" "$sha"
      helm package "$tmp/src" -d "$tmp" >/dev/null || die "$chart: helm package of $source failed"
      tgz="$tmp/$chart-$version.tgz"
      [ -f "$tgz" ] || die "$chart: the chart in $source is not $chart $version (check Chart.yaml against scripts/charts.tsv)"
      ;;
    local)
      cp -R "$REPO_ROOT/$source" "$tmp/src"
      [ ! -d "$tmp/src/charts" ] || die "$chart: a local chart has no dependencies (use type wrapper)"
      helm lint --strict "$tmp/src" >"$tmp/lint.log" 2>&1 || {
        cat "$tmp/lint.log" >&2
        die "$chart: helm lint --strict of $source failed"
      }
      helm package "$tmp/src" -d "$tmp" >/dev/null || die "$chart: helm package of $source failed"
      tgz="$tmp/$chart-$version.tgz"
      [ -f "$tgz" ] || die "$chart: the chart in $source is not $chart $version (check Chart.yaml against scripts/charts.tsv)"
      ;;
    *) die "$chart: unknown type '$type' in scripts/charts.tsv" ;;
  esac
  mkdir -p "$out"
  mv "$tgz" "$out/"
  rm -rf "$tmp"
  echo "$out/$chart-$version.tgz"
}

# fetch_mirrored <chart> <version> <type> <sha256> <out-dir> [helm flags]:
# pulls <chart> <version> from $MIRROR_REGISTRY, prints its path. For a mirror
# chart the archive must be byte-identical to the pinned upstream archive.
fetch_mirrored() {
  local chart="$1" version="$2" type="$3" sha="$4" out="$5"
  shift 5
  mkdir -p "$out"
  helm pull "$MIRROR_REGISTRY/$chart" --version "$version" -d "$out" "$@" >/dev/null \
    || die "$chart: helm pull of $MIRROR_REGISTRY/$chart $version failed (is it published?)"
  [ "$type" != mirror ] || verify_sha "$out/$chart-$version.tgz" "$sha"
  echo "$out/$chart-$version.tgz"
}
