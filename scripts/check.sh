#!/usr/bin/env bash
# Checks every app of the catalog (or the named app directories):
#
#   1. bart validate (FLECS bart, Margo schema, icon, release notes, CPU
#      architectures, compose lints); see README.md "Validation" for the one
#      tolerated failure of a helm-only app.
#   2. fleet-manager's ingest rules (margo-manifest-parser.service.ts) and
#      the rules of this catalog (one helm profile, at most one compose
#      profile, catalog repositories, pins).
#   3. The chart archive: from upstream, checked against the pinned sha256
#      (CHART_SOURCE=upstream, the default), or from the mirror registry
#      (CHART_SOURCE=mirror; a mirrored archive must be byte-identical).
#   4. helm template with the parameter defaults resolved exactly like the
#      kubernetes-agent (every value a string): no cluster-scoped kind, only
#      kinds the agent's Role can create, a static Pod Security "restricted"
#      check, no pod pinned away from a declared CPU architecture, every
#      image a pinned copy in the image registry (scripts/images.tsv).
#      kubeconform -strict when it is installed.
#   6. The compose package (apps with a compose profile): the archive layout
#      of the Margo "Compose Component Registry", the compose file rules,
#      pinned images, every ${VAR} default equal to its parameter, then
#      `docker compose config` with the parameter defaults.
#   7. With --compose: `docker compose up --wait` with the parameter
#      defaults, every container running (and healthy where it has a health
#      check), then `docker compose down -v`.
#   5. With --cluster: on the current kubectl context, in a scratch namespace
#      labelled pod-security.kubernetes.io/enforce=restricted, as a
#      ServiceAccount bound to the kubernetes-agent's baseline Role:
#      `kubectl apply --dry-run=server` (no warning allowed),
#      `helm install --dry-run=server`, then a real `helm install --wait`,
#      every pod Ready, no FailedCreate event, `helm uninstall`.
#
# Usage: scripts/check.sh [--cluster] [--compose] [app-dir...]
#
# Environment (all optional):
#   CHART_SOURCE      upstream (default) or mirror
#   MIRROR_REGISTRY   registry of CHART_SOURCE=mirror
#                     (default oci://ghcr.io/logiccloudag/margo-charts)
#   MIRROR_PLAIN_HTTP 1: pull from MIRROR_REGISTRY over plain HTTP
#   BART_IMAGE        default cr.flecs.tech/flecs/bart:latest
#   CHECK_NAMESPACE   scratch namespace of --cluster (default
#                     fleet-manager-apps-check); created and deleted by the
#                     script, so never name a namespace that holds anything
#   KUBECONFIG        cluster of --cluster (kubectl's usual resolution)
#   WAIT_TIMEOUT      helm --timeout of the real install (default 10m)
#   KEEP_NAMESPACE    1: leave the scratch namespace in place
#   SMOKE_IMAGE_REGISTRY  --compose pulls the images from this registry
#                     instead of IMAGE_REGISTRY (for example a local registry
#                     holding the same digests before they are published)
#   COMPOSE_WAIT_TIMEOUT  seconds of `docker compose up --wait` (default 300)
#
# Requires: docker (with compose), helm (3.14+ or 4), python3 with PyYAML;
# kubectl for --cluster; kubeconform optional.
set -euo pipefail

# shellcheck source=scripts/lib/charts.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/charts.sh"

CLUSTER=0
COMPOSE=0
APPS=()
for arg in "$@"; do
  case "$arg" in
    --cluster) CLUSTER=1 ;;
    --compose) COMPOSE=1 ;;
    -h | --help)
      sed -n '2,/^set -euo/p' "$0" | sed -e '$d' -e 's/^# \{0,1\}//'
      exit 0
      ;;
    -*) die "unknown option $arg" ;;
    *) APPS+=("${arg%/}") ;;
  esac
done

CHART_SOURCE="${CHART_SOURCE:-upstream}"
BART_IMAGE="${BART_IMAGE:-cr.flecs.tech/flecs/bart:latest}"
CHECK_NAMESPACE="${CHECK_NAMESPACE:-fleet-manager-apps-check}"
WAIT_TIMEOUT="${WAIT_TIMEOUT:-10m}"
KEEP_NAMESPACE="${KEEP_NAMESPACE:-0}"
COMPOSE_WAIT_TIMEOUT="${COMPOSE_WAIT_TIMEOUT:-300}"
CHECK_SA="margo-agent-baseline"
PY="$REPO_ROOT/scripts/lib/margo_check.py"
export CHECK_NAMESPACE

case "$CHART_SOURCE" in upstream | mirror) ;; *) die "CHART_SOURCE must be upstream or mirror, got '$CHART_SOURCE'" ;; esac
require_tools docker helm python3
docker compose version >/dev/null 2>&1 || die "docker compose is not available"
python3 -c 'import yaml' 2>/dev/null || die "python3 has no PyYAML (pip install pyyaml)"
[ "$CLUSTER" = 0 ] || require_tools kubectl

WORK="$(mktemp -d)"
RESULTS=()
FAILED=0
NS_CREATED=0

on_exit() {
  local status=$?
  if [ "$NS_CREATED" = 1 ] && [ "$KEEP_NAMESPACE" != 1 ]; then
    log "deleting the scratch namespace $CHECK_NAMESPACE"
    kubectl delete namespace "$CHECK_NAMESPACE" --wait=true --timeout=5m >/dev/null 2>&1 \
      || log "warning: could not delete namespace $CHECK_NAMESPACE; delete it by hand"
  fi
  rm -rf "$WORK"
  exit "$status"
}
trap on_exit EXIT

# stage <app> <name> <command...>: runs one check, records PASS or FAIL.
stage() {
  local app="$1" name="$2"
  shift 2
  echo "== $app: $name"
  if "$@"; then
    RESULTS+=("$app	$name	PASS")
  else
    RESULTS+=("$app	$name	FAIL")
    FAILED=1
  fi
}

# --- stage implementations ------------------------------------------------

check_bart() {
  local dir="$1" out="$WORK/bart.out" app="$WORK/bart-app" rc=0 rules=0
  # bart's bundled schema rejects every configuration.schema validation
  # rule (allowEmpty, minLength, ...): the rules are checked by
  # margo_check.py, and bart validates a copy without them, so its icon,
  # release-notes and architecture checks still run.
  rm -rf "$app" && cp -R "$REPO_ROOT/$dir" "$app"
  python3 "$PY" schema-rules "$REPO_ROOT/$dir/app/margo.yaml" "$app/app/margo.yaml" || rules=1
  docker run --rm -u "$(id -u):$(id -g)" -v "$app:/w" -w /w "$BART_IMAGE" validate >"$out" 2>&1 || rc=$?
  sed 's/^/  bart| /' "$out"
  python3 "$PY" bart "$out" "$rc" "$REPO_ROOT/$dir/app/margo.yaml" && [ "$rules" = 0 ]
}

check_fleet_manager() {
  local dir="$1" chart="$2" version="$3"
  python3 "$PY" fleet-manager "$REPO_ROOT/$dir/app/margo.yaml" "$REPO_ROOT/$dir" "$chart" "$version" \
    "oci://ghcr.io/logiccloudag/margo-charts" "oci://$COMPOSE_REGISTRY"
}

# fetch_chart <chart> <version> <type> <source> <sha>: sets TGZ.
fetch_chart() {
  local out="$WORK/charts"
  if [ "$CHART_SOURCE" = mirror ]; then
    if [ "${MIRROR_PLAIN_HTTP:-0}" = 1 ]; then
      TGZ="$(fetch_mirrored "$1" "$2" "$3" "$5" "$out" --plain-http)" || return 1
    else
      TGZ="$(fetch_mirrored "$1" "$2" "$3" "$5" "$out")" || return 1
    fi
  else
    TGZ="$(fetch_upstream "$1" "$2" "$3" "$4" "$5" "$out")" || return 1
  fi
  echo "  PASS  $(basename "$TGZ") sha256 $(sha256_of "$TGZ")"
}

check_render() {
  local dir="$1" comp
  mkdir -p "$WORK/values"
  comp="$(python3 "$PY" values "$REPO_ROOT/$dir/app/margo.yaml" "$WORK/values")" || return 1
  [ "$(printf '%s\n' "$comp" | wc -l | tr -d ' ')" = 1 ] || {
    echo "  FAIL  expected exactly one helm component, got: $comp"
    return 1
  }
  COMPONENT="$comp"
  VALUES="$WORK/values/$comp.values.yaml"
  echo "  INFO  values of component $comp (the agent's view, every value a string):"
  sed 's/^/        /' "$VALUES"
  helm template "$comp-check" "$TGZ" -n "$CHECK_NAMESPACE" -f "$VALUES" --include-crds >"$WORK/rendered.yaml" 2>"$WORK/template.log" || {
    sed 's/^/  helm| /' "$WORK/template.log"
    echo "  FAIL  helm template failed"
    return 1
  }
  echo "  PASS  helm template"
  python3 "$PY" rendered "$WORK/rendered.yaml" "$REPO_ROOT/$dir/app/margo.yaml" \
    "$IMAGES_TSV" "$IMAGE_REGISTRY" "$dir" || return 1
  if command -v kubeconform >/dev/null 2>&1; then
    kubeconform -strict -summary -ignore-missing-schemas "$WORK/rendered.yaml" | sed 's/^/  kubeconform| /'
    [ "${PIPESTATUS[0]}" = 0 ] || {
      echo "  FAIL  kubeconform -strict"
      return 1
    }
    echo "  PASS  kubeconform -strict (every value has the type the API expects)"
  else
    echo "  SKIP  kubeconform is not installed"
  fi
}

# check_compose <app-dir>: sets COMPOSE_DIR (the extracted package),
# COMPOSE_ENV, COMPOSE_SMOKE and COMPOSE_NAME.
check_compose() {
  local dir="$1" out="$WORK/compose/$1" info
  rm -rf "$out" && mkdir -p "$out"
  info="$(python3 "$PY" compose "$REPO_ROOT/$dir/app/margo.yaml" "$REPO_ROOT/$dir" "$IMAGES_TSV" "$IMAGE_REGISTRY" "$out")" || {
    printf '%s\n' "$info"
    return 1
  }
  printf '%s\n' "$info" | sed '$d'
  info="$(printf '%s\n' "$info" | tail -n 1)"
  COMPOSE_NAME="${info%% *}"
  COMPOSE_ENV="$out/$COMPOSE_NAME.env"
  COMPOSE_SMOKE="$out/$COMPOSE_NAME.smoke.yaml"
  mkdir -p "$out/x"
  tar -xzf "$out/$COMPOSE_NAME.tar.gz" -C "$out/x"
  COMPOSE_DIR="$out/x/$COMPOSE_NAME"
  echo "  INFO  package $COMPOSE_NAME.tar.gz sha256 $(sha256_of "$out/$COMPOSE_NAME.tar.gz") (${info#* })"
  docker compose -p "check-$COMPOSE_NAME" -f "$COMPOSE_DIR/compose.yaml" --env-file "$COMPOSE_ENV" config -q 2>"$out/config.log" || {
    sed 's/^/  compose| /' "$out/config.log"
    echo "  FAIL  docker compose config"
    return 1
  }
  echo "  PASS  docker compose config with the parameter defaults"
}

check_compose_smoke() {
  local project="check-$COMPOSE_NAME" files rc=0 bad
  files=(-f "$COMPOSE_DIR/compose.yaml")
  [ ! -f "$COMPOSE_SMOKE" ] || files+=(-f "$COMPOSE_SMOKE")
  if ! docker compose -p "$project" "${files[@]}" --env-file "$COMPOSE_ENV" up -d --wait \
    --wait-timeout "$COMPOSE_WAIT_TIMEOUT" >"$WORK/up.log" 2>&1; then
    sed 's/^/  compose| /' "$WORK/up.log"
    docker compose -p "$project" "${files[@]}" --env-file "$COMPOSE_ENV" logs --no-color 2>&1 | tail -n 50 | sed 's/^/  logs| /'
    echo "  FAIL  docker compose up --wait"
    rc=1
  else
    docker compose -p "$project" "${files[@]}" --env-file "$COMPOSE_ENV" ps 2>&1 | sed 's/^/  compose| /'
    bad="$(docker compose -p "$project" "${files[@]}" --env-file "$COMPOSE_ENV" ps -a --format '{{.Service}} {{.State}} {{.Health}}' \
      | awk '$2 != "running" || ($3 != "" && $3 != "healthy")')"
    if [ -n "$bad" ]; then
      echo "  FAIL  containers not running or not healthy: $bad"
      rc=1
    else
      echo "  PASS  docker compose up --wait: every container running"
    fi
  fi
  docker compose -p "$project" "${files[@]}" --env-file "$COMPOSE_ENV" down -v --remove-orphans >/dev/null 2>&1 || {
    echo "  FAIL  docker compose down -v"
    rc=1
  }
  [ "$rc" = 0 ] && echo "  PASS  docker compose down -v"
  return "$rc"
}

cluster_setup() {
  if kubectl get namespace "$CHECK_NAMESPACE" >/dev/null 2>&1; then
    die "namespace $CHECK_NAMESPACE already exists; delete it or set CHECK_NAMESPACE to an unused name"
  fi
  kubectl create namespace "$CHECK_NAMESPACE" >/dev/null
  NS_CREATED=1
  kubectl label namespace "$CHECK_NAMESPACE" \
    pod-security.kubernetes.io/enforce=restricted pod-security.kubernetes.io/enforce-version=latest \
    pod-security.kubernetes.io/warn=restricted pod-security.kubernetes.io/warn-version=latest \
    pod-security.kubernetes.io/audit=restricted pod-security.kubernetes.io/audit-version=latest >/dev/null
  # The kubernetes-agent's baseline namespace Role (KA-A-20).
  kubectl apply -n "$CHECK_NAMESPACE" -f - >/dev/null <<YAML
apiVersion: v1
kind: ServiceAccount
metadata:
  name: $CHECK_SA
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: $CHECK_SA
rules:
  - apiGroups: [""]
    resources: [pods]
    verbs: [get, list, watch]
  - apiGroups: [""]
    resources: [services, configmaps, persistentvolumeclaims, serviceaccounts, secrets]
    verbs: [get, list, watch, create, update, patch, delete]
  - apiGroups: [""]
    resources: [events]
    verbs: [create, patch]
  - apiGroups: [""]
    resources: [endpoints]
    verbs: [get, list, watch]
  - apiGroups: [apps]
    resources: [deployments, replicasets, statefulsets, daemonsets]
    verbs: [get, list, watch, create, update, patch, delete]
  - apiGroups: [batch]
    resources: [jobs, cronjobs]
    verbs: [get, list, watch, create, update, patch, delete]
  # Optional rows: workloadPermissions.ingresses (KA-208, on by default)
  # and workloadPermissions.rbac (KA-211, opt-in): the check models an agent
  # with the opt-in, as on the fleet-manager dev environment.
  - apiGroups: [networking.k8s.io]
    resources: [ingresses]
    verbs: [get, list, watch, create, update, patch, delete]
  - apiGroups: [rbac.authorization.k8s.io]
    resources: [roles, rolebindings]
    verbs: [get, list, watch, create, update, patch, delete]
  - apiGroups: [discovery.k8s.io]
    resources: [endpointslices]
    verbs: [get, list, watch]
  - apiGroups: [networking.k8s.io]
    resources: [ingresses/status]
    verbs: [get, update, patch]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: $CHECK_SA
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: $CHECK_SA
subjects:
  - kind: ServiceAccount
    name: $CHECK_SA
    namespace: $CHECK_NAMESPACE
YAML
  AS_USER="system:serviceaccount:$CHECK_NAMESPACE:$CHECK_SA"
  log "scratch namespace $CHECK_NAMESPACE (Pod Security restricted), acting as $AS_USER"
}

check_cluster() {
  local rel="$COMPONENT-check" rc=0 notready failed_events
  # 1. kubectl server-side dry run of the rendered objects: PSA warnings
  #    for workload objects arrive as "Warning:" lines. RoleBindings are
  #    left out: a dry run persists nothing, so the API server's bind check
  #    cannot find a Role of the same render. The real install (step 3)
  #    creates the Role first and checks the RoleBinding as the agent.
  python3 - "$WORK/rendered.yaml" "$WORK/dryrun.yaml" <<'PY'
import sys, yaml
docs = [d for d in yaml.safe_load_all(open(sys.argv[1])) if d and d.get("kind") != "RoleBinding"]
with open(sys.argv[2], "w") as fh:
    yaml.safe_dump_all(docs, fh)
PY
  kubectl apply --dry-run=server -n "$CHECK_NAMESPACE" --as "$AS_USER" -f "$WORK/dryrun.yaml" >"$WORK/kdry.out" 2>&1 || rc=$?
  sed 's/^/  kubectl| /' "$WORK/kdry.out"
  if [ "$rc" != 0 ] || grep -qiE 'warning|podsecurity|forbidden' "$WORK/kdry.out"; then
    echo "  FAIL  kubectl apply --dry-run=server reported an error or a warning"
    return 1
  fi
  if grep -q '^kind: RoleBinding' "$WORK/rendered.yaml"; then
    echo "  PASS  kubectl apply --dry-run=server: no warning, no violation (RoleBindings are checked by the real install)"
  else
    echo "  PASS  kubectl apply --dry-run=server: no warning, no violation"
  fi
  # 2. helm install --dry-run=server (renders against the live cluster).
  helm install "$rel" "$TGZ" -n "$CHECK_NAMESPACE" -f "$VALUES" --kube-as-user "$AS_USER" \
    --dry-run=server >/dev/null 2>"$WORK/hdry.log" || rc=$?
  sed 's/^/  helm| /' "$WORK/hdry.log"
  if [ "$rc" != 0 ] || grep -qiE 'podsecurity|violate|forbidden' "$WORK/hdry.log"; then
    echo "  FAIL  helm install --dry-run=server"
    return 1
  fi
  echo "  PASS  helm install --dry-run=server"
  # 3. Real install, every pod Ready, no FailedCreate, uninstall.
  if ! helm install "$rel" "$TGZ" -n "$CHECK_NAMESPACE" -f "$VALUES" --kube-as-user "$AS_USER" \
    --wait --timeout "$WAIT_TIMEOUT" >/dev/null 2>"$WORK/install.log"; then
    sed 's/^/  helm| /' "$WORK/install.log"
    kubectl get pods,events -n "$CHECK_NAMESPACE" 2>&1 | sed 's/^/  kubectl| /'
    echo "  FAIL  helm install --wait"
    helm uninstall "$rel" -n "$CHECK_NAMESPACE" --wait >/dev/null 2>&1 || true
    return 1
  fi
  sed 's/^/  helm| /' "$WORK/install.log"
  kubectl get pods -n "$CHECK_NAMESPACE" -o wide 2>&1 | sed 's/^/  kubectl| /'
  notready="$(kubectl get pods -n "$CHECK_NAMESPACE" -o json \
    | python3 -c 'import json,sys; print(" ".join(p["metadata"]["name"] for p in json.load(sys.stdin)["items"] if not any(c["type"]=="Ready" and c["status"]=="True" for c in p["status"].get("conditions",[]))))')"
  failed_events="$(kubectl get events -n "$CHECK_NAMESPACE" --field-selector reason=FailedCreate -o name 2>/dev/null | wc -l | tr -d ' ')"
  rc=0
  if [ -n "$notready" ]; then
    echo "  FAIL  pods not Ready: $notready"
    rc=1
  elif [ "$(kubectl get pods -n "$CHECK_NAMESPACE" -o name | wc -l | tr -d ' ')" = 0 ]; then
    echo "  FAIL  the release created no pod"
    rc=1
  else
    echo "  PASS  helm install --wait: every pod Ready"
  fi
  if [ "$failed_events" != 0 ]; then
    kubectl get events -n "$CHECK_NAMESPACE" --field-selector reason=FailedCreate 2>&1 | sed 's/^/  kubectl| /'
    echo "  FAIL  $failed_events FailedCreate events (for example a Pod Security rejection)"
    rc=1
  else
    echo "  PASS  no FailedCreate event"
  fi
  helm uninstall "$rel" -n "$CHECK_NAMESPACE" --kube-as-user "$AS_USER" --wait >/dev/null || {
    echo "  FAIL  helm uninstall"
    rc=1
  }
  kubectl delete pvc --all -n "$CHECK_NAMESPACE" --wait=true >/dev/null 2>&1 || true
  kubectl delete events --all -n "$CHECK_NAMESPACE" >/dev/null 2>&1 || true
  [ "$rc" = 0 ] && echo "  PASS  helm uninstall"
  return "$rc"
}

# --- main ---------------------------------------------------------------------

[ "$CLUSTER" = 0 ] || cluster_setup

ROWS="$(chart_rows ${APPS[@]+"${APPS[@]}"})"
while IFS="$(printf '\t')" read -r app chart version type source sha; do
  [ -n "$app" ] || continue
  [ -f "$REPO_ROOT/$app/app/margo.yaml" ] || die "$app/app/margo.yaml does not exist"
  TGZ=""
  COMPONENT=""
  VALUES=""
  stage "$app" "bart validate" check_bart "$app"
  stage "$app" "fleet-manager rules" check_fleet_manager "$app" "$chart" "$version"
  stage "$app" "chart $chart $version ($CHART_SOURCE)" fetch_chart "$chart" "$version" "$type" "$source" "$sha"
  if [ -n "$TGZ" ]; then
    stage "$app" "helm template: kinds and Pod Security" check_render "$app"
    if [ "$CLUSTER" = 1 ] && [ -n "$VALUES" ]; then
      stage "$app" "cluster: dry run, install, Ready, uninstall" check_cluster
    fi
  fi
  if [ -n "$(python3 "$PY" components "$REPO_ROOT/$app/app/margo.yaml" compose)" ]; then
    COMPOSE_DIR=""
    stage "$app" "compose package" check_compose "$app"
    if [ "$COMPOSE" = 1 ] && [ -n "$COMPOSE_DIR" ]; then
      stage "$app" "compose: up --wait, running, down" check_compose_smoke
    fi
  fi
done <<EOF
$ROWS
EOF

echo
echo "== Summary"
printf '%s\n' "${RESULTS[@]}" | awk -F '\t' '{ printf "  %-6s %-16s %s\n", $3, $1, $2 }'
[ "$FAILED" = 0 ] || die "at least one check failed"
log "all checks passed"
