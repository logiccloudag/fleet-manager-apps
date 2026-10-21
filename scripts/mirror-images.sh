#!/usr/bin/env bash
# Copies the pinned images of scripts/images.tsv to the image registry
# (default ghcr.io/logiccloudag/margo-images), where the charts and compose
# files of the catalog point:
#
#   crane copy <upstream>@<digest> <registry>/<name>:<tag>
#
# The copy keeps the upstream multi-arch index digest, so every reference
# <registry>/<name>:<tag>@<digest> resolves to exactly the pinned content.
# A tag that already exists is never overwritten: the same digest is
# skipped, a different digest is an error. After each copy the digest of the
# new tag is checked.
#
# Usage: scripts/mirror-images.sh [--dry-run] [app-dir...]
#
# Environment (all optional):
#   IMAGE_REGISTRY  default ghcr.io/logiccloudag/margo-images
#   CRANE_INSECURE  1: talk to IMAGE_REGISTRY over plain HTTP (a local test
#                   registry)
#
# Before the first push, log in with a token that has write:packages, for
# example in GitHub Actions:
#   echo "$GITHUB_TOKEN" | crane auth login ghcr.io -u "$GITHUB_ACTOR" --password-stdin
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

require_tools crane
INSECURE=()
[ "${CRANE_INSECURE:-0}" != 1 ] || INSECURE=(--insecure)

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

ROWS="$(image_rows ${APPS[@]+"${APPS[@]}"})"
[ -n "$ROWS" ] || die "no image rows for: ${APPS[*]:-all apps}"
while IFS="$(printf '\t')" read -r name upstream tag digest _apps; do
  [ -n "$name" ] || continue
  case "$digest" in sha256:????????????????????????????????????????????????????????????????) ;; *) die "$name: digest '$digest' in scripts/images.tsv is not a sha256 digest" ;; esac
  src="$upstream@$digest"
  dst="$IMAGE_REGISTRY/$name:$tag"
  existing="$(crane digest ${INSECURE[@]+"${INSECURE[@]}"} "$dst" 2>/dev/null || true)"
  if [ -n "$existing" ]; then
    [ "$existing" = "$digest" ] || die "$name: $dst exists with digest $existing, not the pin $digest; a published tag is never overwritten"
    log "$name: $dst already has $digest; skipped"
    continue
  fi
  if [ "$DRY_RUN" = 1 ]; then
    log "$name: --dry-run: would copy $src to $dst"
    continue
  fi
  if ! crane copy ${INSECURE[@]+"${INSECURE[@]}"} "$src" "$dst" >"$WORK/copy.log" 2>&1; then
    tail -n 20 "$WORK/copy.log" >&2
    die "$name: crane copy $src $dst failed (logged in with write:packages?)"
  fi
  copied="$(crane digest ${INSECURE[@]+"${INSECURE[@]}"} "$dst")" || die "$name: cannot read the digest of $dst after the copy"
  [ "$copied" = "$digest" ] || die "$name: $dst has digest $copied after the copy, not the pin $digest"
  log "$name: copied $src to $dst"
done <<ROWS_EOF
$ROWS
ROWS_EOF
log "done"
