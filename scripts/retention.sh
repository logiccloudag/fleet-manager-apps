#!/usr/bin/env bash
# Deletes old package versions of the catalog on ghcr.io: for every package
# under margo-charts/, margo-compose/ and margo-images/ of the organisation,
# it keeps
#   - the KEEP newest tagged versions (default 5),
#   - every version with a tag that main still pins (scripts/charts.tsv,
#     scripts/images.tsv, the compose revisions in app/margo.yaml),
#   - every untagged version: the platform manifests of a multi-arch image
#     are untagged children of its index, and deleting one breaks the image.
# Everything else is deleted. Without --delete it only prints the plan.
#
# Usage: scripts/retention.sh [--delete]
#
# Environment:
#   GH_TOKEN  a token that may read and delete the packages (in GitHub
#             Actions the GITHUB_TOKEN, with the repository granted the
#             Admin role on each package)
#   ORG       default logiccloudag
#   KEEP      default 5
set -euo pipefail

# shellcheck source=scripts/lib/charts.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/charts.sh"

DELETE=0
for arg in "$@"; do
  case "$arg" in
    --delete) DELETE=1 ;;
    -h | --help)
      sed -n '2,/^set -euo/p' "$0" | sed -e '$d' -e 's/^# \{0,1\}//'
      exit 0
      ;;
    *) die "unknown argument $arg" ;;
  esac
done

require_tools gh jq python3
[ -n "${GH_TOKEN:-}" ] || die "GH_TOKEN is not set"
ORG="${ORG:-logiccloudag}"
KEEP="${KEEP:-5}"
case "$KEEP" in '' | *[!0-9]*) die "KEEP must be a number, got '$KEEP'" ;; esac
[ "$KEEP" -ge 1 ] || die "KEEP must be at least 1"

# The tags main pins, as "<package>:<tag>" lines.
PINNED="$(
  awk -F '\t' '!/^#/ && NF >= 3 { print "margo-charts/" $2 ":" $3 }' "$CHARTS_TSV"
  awk -F '\t' '!/^#/ && NF >= 3 { print "margo-images/" $1 ":" $3 }' "$IMAGES_TSV"
  for margo in "$REPO_ROOT"/helm-*/app/margo.yaml; do
    python3 -c '
import sys, yaml
d = yaml.safe_load(open(sys.argv[1]))
for p in d.get("deploymentProfiles") or []:
    if p.get("type") == "compose":
        for c in p.get("components") or []:
            print("margo-compose/" + c["properties"]["repository"].rsplit("/", 1)[1] + ":" + c["properties"]["revision"])' "$margo"
  done
)"

PACKAGES="$(gh api --paginate "/orgs/$ORG/packages?package_type=container&per_page=100" --jq '.[].name' \
  | grep -E '^margo-(charts|compose|images)/' || true)"
[ -n "$PACKAGES" ] || die "no margo-charts/, margo-compose/ or margo-images/ package is visible to the token"

DELETED=0
while read -r package; do
  [ -n "$package" ] || continue
  encoded="$(jq -rn --arg p "$package" '$p | @uri')"
  # Tagged versions, newest first: "<id> <tag,tag,...>".
  versions="$(gh api --paginate "/orgs/$ORG/packages/container/$encoded/versions?per_page=100" \
    --jq '.[] | select((.metadata.container.tags | length) > 0) | [.created_at, (.id | tostring), (.metadata.container.tags | join(","))] | @tsv' \
    | sort -r | cut -f 2,3)"
  n=0
  while IFS="$(printf '\t')" read -r id tags; do
    [ -n "$id" ] || continue
    n=$((n + 1))
    keep=""
    [ "$n" -gt "$KEEP" ] || keep="one of the $KEEP newest"
    for tag in ${tags//,/ }; do
      if printf '%s\n' "$PINNED" | grep -qxF "$package:$tag"; then
        keep="pinned on main"
      fi
    done
    if [ -n "$keep" ]; then
      log "$package: keep $tags ($keep)"
    elif [ "$DELETE" = 1 ]; then
      gh api -X DELETE "/orgs/$ORG/packages/container/$encoded/versions/$id" >/dev/null \
        || die "$package: could not delete version $id ($tags); does the repository have the Admin role on the package?"
      log "$package: deleted $tags"
      DELETED=$((DELETED + 1))
    else
      log "$package: would delete $tags (run with --delete)"
    fi
  done <<EOF_VERSIONS
$versions
EOF_VERSIONS
done <<EOF_PACKAGES
$PACKAGES
EOF_PACKAGES
log "done ($DELETED version(s) deleted)"
