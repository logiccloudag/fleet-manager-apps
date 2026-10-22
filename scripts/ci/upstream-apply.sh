#!/usr/bin/env bash
# Acts on the plan of scripts/upstream-check.py (weekly upstream check,
# FM-1631):
#
#   regenerate  an update within the current major: scripts/upstream-check.py
#               regenerate, copy the new images to the local gate registry,
#               run the full gate (scripts/check.sh --cluster --compose
#               <app>). Green: commit "chore(<id>): upstream <old> → <new>".
#               Red: undo the changes and create an issue with the gate log.
#   issue       a new major version: create an issue
#               (scripts/youtrack-issue.py), one per app and target major.
# An app can have both (FM-1731): the update within the major is applied and
# the major upgrade is left to a human.
#
# Then it pushes the commits to REF and, with PUBLISH=true, dispatches
# publish.yml on REF (a push with GITHUB_TOKEN starts no workflow). Every
# app gets a line in $GITHUB_STEP_SUMMARY: up to date, regenerated, issue
# created or exists (with link), or, with DRY_RUN=true, the planned action.
#
# Usage: scripts/ci/upstream-apply.sh <plan.json>
#
# Environment:
#   DRY_RUN             true: only report the plan (issues: duplicate search)
#   PUBLISH             true: dispatch publish.yml after the push (GH_TOKEN)
#   REF                 branch to push to (default: the current branch)
#   LOCAL_REGISTRY_PORT the gate registry (scripts/ci/gate-setup.sh)
#   YOUTRACK_TOKEN      required, also for a dry run; the job fails without
#   YOUTRACK_TAG        default margo-apps
set -euo pipefail

PLAN="${1:?usage: upstream-apply.sh <plan.json>}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
DRY_RUN="${DRY_RUN:-true}"
PUBLISH="${PUBLISH:-false}"
REF="${REF:-$(git rev-parse --abbrev-ref HEAD)}"
PORT="${LOCAL_REGISTRY_PORT:-5001}"
SUMMARY="${GITHUB_STEP_SUMMARY:-/dev/stdout}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

[ -n "${YOUTRACK_TOKEN:-}" ] || {
  echo "ERROR: YOUTRACK_TOKEN is not set (repository secret YOUTRACK_TOKEN); the upstream check needs it to report" >&2
  exit 1
}

ROWS=()
row() { ROWS+=("| \`$1\` | $2 |"); }

# issue <id> <old> <new> <reason> <details-file> [dedupe-regex]: creates or
# finds the issue.
issue() {
  local id="$1" old="$2" new="$3" reason="$4" details="$5" dedupe="${6:-}" out flag=()
  local summary="fleet-manager-apps: plan $id upgrade $old → $new"
  {
    echo "The weekly upstream check of logiccloudag/fleet-manager-apps (FM-1631) could not update \`$id\` automatically: $reason."
    echo
    echo "Run: ${GITHUB_SERVER_URL:-https://github.com}/${GITHUB_REPOSITORY:-logiccloudag/fleet-manager-apps}/actions/runs/${GITHUB_RUN_ID:-local}"
    echo
    cat "$details"
    echo
    echo "Plan the upgrade by hand (README.md \"Bumping a chart\", \"Bumping an image\"), validate with \`scripts/check.sh --cluster --compose\` and merge to main."
  } >"$WORK/desc.md"
  [ "$DRY_RUN" != true ] || flag=(--dry-run)
  [ -z "$dedupe" ] || flag+=(--dedupe-regex "$dedupe")
  out="$(python3 scripts/youtrack-issue.py ${flag[@]+"${flag[@]}"} "$summary" "$WORK/desc.md")"
  echo "$out"
  case "$out" in
    created*) row "$id" "issue created: [$(echo "$out" | cut -d' ' -f2)](${out##* })" ;;
    exists*) row "$id" "issue exists: [$(echo "$out" | cut -d' ' -f2)](${out##* })" ;;
    *) row "$id" "$out" ;;
  esac
}

components() { # <app>: markdown list of the planned updates within the major
  jq -r --arg a "$1" '.[] | select(.app == $a) | .components[] | select(.bump != "none")
    | "- \(.kind) `\(.name)`: \(.current) → \(.latest) (\(.bump))"' "$PLAN"
}

majors() { # <app>: markdown list of the new major versions
  jq -r --arg a "$1" '.[] | select(.app == $a) | .components[] | select(.major != null)
    | "- \(.kind) `\(.name)`: \(.current) → \(.major) (major)"' "$PLAN"
}

# A missing gate environment is a broken runner, not a red gate: fail the
# job instead of opening a misleading issue.
if [ "$DRY_RUN" != true ] && [ "$(jq '[.[] | select(.regenerate == true)] | length' "$PLAN")" != 0 ]; then
  curl -fsS "http://127.0.0.1:$PORT/v2/" >/dev/null 2>&1 || {
    echo "ERROR: the gate registry on port $PORT is not running (scripts/ci/gate-setup.sh)" >&2
    exit 1
  }
  kubectl get nodes >/dev/null 2>&1 || {
    echo "ERROR: no kind cluster for the gate (scripts/ci/gate-setup.sh)" >&2
    exit 1
  }
fi

COMMITS=0
for app in $(jq -r '.[].app' "$PLAN"); do
  id="$(jq -r --arg a "$app" '.[] | select(.app == $a) | .id' "$PLAN")"
  regen="$(jq -r --arg a "$app" '.[] | select(.app == $a) | .regenerate' "$PLAN")"
  major="$(jq -r --arg a "$app" '.[] | select(.app == $a) | .issue' "$PLAN")"
  echo "== $app: regenerate=$regen issue=$major"
  [ "$regen" = true ] || [ "$major" = true ] || row "$id" "up to date"
  if [ "$regen" = true ]; then
    first="$(jq -r --arg a "$app" '[.[] | select(.app == $a) | .components[] | select(.bump != "none")][0] | "\(.current) \(.latest)"' "$PLAN")"
    old="${first% *}"
    new="${first#* }"
    if [ "$DRY_RUN" = true ]; then
      row "$id" "dry run: would regenerate $old → $new and run the gate"
      components "$app"
    else
      log="$WORK/$app.log"
      ok=1
      subject="$(python3 scripts/upstream-check.py regenerate "$PLAN" "$app" 2>"$log" | tail -n 1)" || ok=0
      if [ "$ok" = 1 ]; then
        IMAGE_REGISTRY="localhost:$PORT/logiccloudag/margo-images" CRANE_INSECURE=1 \
          scripts/mirror-images.sh "$app" >>"$log" 2>&1 || ok=0
      fi
      if [ "$ok" = 1 ]; then
        SMOKE_IMAGE_REGISTRY="localhost:$PORT/logiccloudag/margo-images" \
          scripts/check.sh --cluster --compose "$app" >>"$log" 2>&1 || ok=0
      fi
      if [ "$ok" = 1 ]; then
        git add -A -- README.md scripts/charts.tsv scripts/images.tsv "$app"
        {
          echo "$subject"
          echo
          components "$app"
          echo
          echo "Regenerated by the weekly upstream check (FM-1631). Gate passed:"
          echo "scripts/check.sh --cluster --compose $app."
        } | git commit -q -F -
        COMMITS=$((COMMITS + 1))
        row "$id" "regenerated: $old → $new ($(git rev-parse --short HEAD))"
        echo "gate passed; committed $(git rev-parse --short HEAD)"
      else
        echo "gate failed; undoing the changes of $app"
        sed 's/^/  | /' "$log" | tail -n 60
        git checkout -q -- .
        git clean -fdq -- "$app"
        {
          components "$app"
          echo
          echo "The regeneration or the gate failed. Last lines of the log:"
          echo
          echo '```text'
          tail -n 60 "$log"
          echo '```'
        } >"$WORK/details.md"
        issue "$id" "$old" "$new" "the regeneration or the gate failed" "$WORK/details.md"
      fi
    fi
  fi
  if [ "$major" = true ]; then
    first="$(jq -r --arg a "$app" '[.[] | select(.app == $a) | .components[] | select(.major != null)][0] | "\(.current) \(.major)"' "$PLAN")"
    old="${first% *}"
    new="${first#* }"
    target_major="$(python3 -c 'import re, sys; print(re.match(r"^[^0-9]*([0-9]+)", sys.argv[1]).group(1))' "$new")"
    majors "$app" >"$WORK/details.md"
    issue "$id" "$old" "$new" "a major upstream version" "$WORK/details.md" \
      "^fleet-manager-apps: plan $id upgrade .* → [^0-9]*$target_major\."
  fi
done

if [ "$COMMITS" -gt 0 ]; then
  git push origin "HEAD:$REF"
  echo "pushed $COMMITS commit(s) to $REF"
  if [ "$PUBLISH" = true ]; then
    gh workflow run publish.yml --ref "$REF"
    echo "dispatched publish.yml on $REF"
  fi
fi

{
  if [ "$DRY_RUN" = true ]; then echo "## Upstream check (dry run)"; else echo "## Upstream check"; fi
  echo
  echo "| App | Result |"
  echo "| --- | --- |"
  printf '%s\n' "${ROWS[@]}"
  if [ "$COMMITS" -gt 0 ]; then
    echo
    echo "Pushed $COMMITS commit(s) to \`$REF\`; publish dispatched: $PUBLISH."
  fi
} >>"$SUMMARY"
