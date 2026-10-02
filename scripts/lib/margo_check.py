#!/usr/bin/env python3
"""Checks of one Margo Helm app, used by scripts/check.sh.

Subcommands (each prints one line per finding and exits 1 on any failure):

  bart <bart-output> <exit-code> <margo.yaml>
      Interprets the output of `bart validate` for a helm-only app.
  fleet-manager <margo.yaml> <app-dir> <chart> <version> <registry>
      The ingest rules of fleet-manager's margo-manifest-parser.service.ts,
      plus the rules of this catalog (helm-only, mirror repository, pins).
  values <margo.yaml> <out-dir>
      Resolves the parameter defaults to Helm values exactly like the
      kubernetes-agent (internal/reconcile/parameters.go) and writes
      <out-dir>/<component>.values.yaml. Prints the component names.
  rendered <manifest.yaml> <margo.yaml>
      Kinds, Pod Security "restricted" and CPU architecture checks of a
      `helm template` output.

Requires Python 3.8+ and PyYAML.
"""

import os
import re
import sys

import yaml

# fleet-manager margo-manifest-parser.service.ts
ID_PATTERN = re.compile(r"^[a-z0-9-]{1,200}$")
COMPONENT_NAME_PATTERN = re.compile(r"^[a-z0-9-]*$")
PARAMETER_KEY_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
OCI_REPOSITORY_PATTERN = re.compile(r"^oci://.+")
SEMVER_REVISION_PATTERN = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
    r"(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$"
)
SEMVER_LOOSE = re.compile(r"^\d+\.\d+\.\d+(-[a-zA-Z0-9.]+)?(\+[a-zA-Z0-9.]+)?$")
# bart's schema for components[].properties.timeout
TIMEOUT_PATTERN = re.compile(r"^\d+m\d+s$")

# kubernetes-agent internal/deploy/helm.go clusterScopedKinds
CLUSTER_SCOPED_KINDS = {
    "CustomResourceDefinition", "ClusterRole", "ClusterRoleBinding",
    "ValidatingWebhookConfiguration", "MutatingWebhookConfiguration",
    "StorageClass", "PriorityClass", "APIService", "Namespace",
}
# Kinds the agent's namespace-scoped Role may create (KA-A-20 baseline,
# kubernetes-agent infrastructure/e2e/ka-a-20-baseline.tsv). Anything else is
# refused by the API server even when it is namespaced (Role, RoleBinding,
# PodDisruptionBudget, NetworkPolicy, Ingress, ServiceMonitor, ...).
AGENT_CREATABLE_KINDS = {
    "Service", "ConfigMap", "PersistentVolumeClaim", "ServiceAccount", "Secret",
    "Deployment", "ReplicaSet", "StatefulSet", "DaemonSet", "Job", "CronJob",
}
# Pod Security "restricted": allowed volume types and capabilities.
RESTRICTED_VOLUME_TYPES = {
    "configMap", "csi", "downwardAPI", "emptyDir", "ephemeral",
    "persistentVolumeClaim", "projected", "secret",
}

failures = 0


def ok(msg):
    print(f"  PASS  {msg}")


def fail(msg):
    global failures
    failures += 1
    print(f"  FAIL  {msg}")


def load_yaml(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def profiles_of(doc):
    profiles = doc.get("deploymentProfiles")
    return profiles if isinstance(profiles, list) else []


# --------------------------------------------------------------------- bart

def cmd_bart(output_path, exit_code, margo_path):
    with open(output_path, encoding="utf-8") as f:
        lines = [line.rstrip("\n") for line in f]
    passed = [line.split("✓", 1)[1].strip() for line in lines if line.strip().startswith("✓")]
    failed = [line.split("✗", 1)[1].strip() for line in lines if line.strip().startswith("✗")]

    if not any(p.startswith("app/margo.yaml") for p in passed):
        fail("bart: the app/margo.yaml schema check did not pass")
    else:
        ok("bart: app/margo.yaml passes bart's Margo schema check")
    for required in ("app icon", "release notes", "cpu architectures"):
        if any(p.startswith(required) for p in passed):
            ok(f"bart: {required}")
        else:
            fail(f"bart: '{required}' did not pass")

    doc = load_yaml(margo_path)
    types = {p.get("type") for p in profiles_of(doc)}
    helm_only = types == {"helm"}

    # The single tolerated failure: bart 0.4.x always reads compose/compose.yaml,
    # which a helm-only app does not have. Every other failure counts.
    missing_compose = re.compile(r"^compose/compose\.yaml - \./compose/compose\.yaml: No such file or directory")
    tolerated = [f for f in failed if helm_only and missing_compose.match(f)]
    other = [f for f in failed if f not in tolerated]
    for f in other:
        fail(f"bart: {f}")
    if exit_code == "0":
        ok("bart validate exited 0")
    elif tolerated and not other:
        ok("bart validate: the only failure is the missing compose/compose.yaml, "
           "which does not apply to a helm-only app")
    elif not other:
        fail(f"bart validate exited {exit_code} without a reported check failure")


# ------------------------------------------------------------ fleet-manager

def cmd_fleet_manager(margo_path, app_dir, chart, version, registry):
    doc = load_yaml(margo_path)
    if not isinstance(doc, dict):
        fail("margo.yaml is not a YAML mapping")
        return

    # Header (validateHeader)
    if doc.get("apiVersion"):
        ok(f"apiVersion present ({doc['apiVersion']})")
    else:
        fail("apiVersion is required")
    if doc.get("kind") == "ApplicationDescription":
        ok("kind is ApplicationDescription")
    else:
        fail(f"kind must be ApplicationDescription (got {doc.get('kind')!r})")
    app_id = doc.get("id")
    if isinstance(app_id, str) and ID_PATTERN.match(app_id):
        ok(f"top-level id {app_id!r} matches ^[a-z0-9-]{{1,200}}$")
    else:
        fail(f"top-level id {app_id!r} must be a string matching ^[a-z0-9-]{{1,200}}$")
    if isinstance(doc.get("metadata"), dict) and "id" in doc["metadata"]:
        fail("metadata.id is the retired format; the id is top-level")

    # Metadata (validateMetadata)
    md = doc.get("metadata") or {}
    for field in ("name", "version", "catalog"):
        if md.get(field):
            ok(f"metadata.{field} present")
        else:
            fail(f"metadata.{field} is required")
    if md.get("version") and not SEMVER_LOOSE.match(str(md["version"])):
        fail(f"metadata.version {md['version']!r} should be SemVer")
    if not md.get("description"):
        fail("metadata.description is recommended by fleet-manager (warning) and required here")
    application = ((md.get("catalog") or {}).get("application")) or {}
    for field in ("icon", "releaseNotes"):
        rel = application.get(field)
        if not rel:
            fail(f"metadata.catalog.application.{field} is required here")
        elif rel.startswith("/") or "://" in rel or ".." in rel.split("/"):
            fail(f"metadata.catalog.application.{field} must be a relative path (got {rel!r})")
        elif not os.path.isfile(os.path.join(app_dir, "app", rel)):
            fail(f"metadata.catalog.application.{field} {rel!r} does not exist in app/")
        else:
            ok(f"metadata.catalog.application.{field} {rel!r} exists")

    # Deployment profiles (parseDeploymentProfiles, evaluateProfileCompliance)
    profiles = profiles_of(doc)
    if not profiles:
        fail("deploymentProfiles must be a non-empty array")
    component_names = set()
    seen_ids = set()
    expected_repository = f"{registry.rstrip('/')}/{chart}"
    for i, profile in enumerate(profiles):
        path = f"deploymentProfiles[{i}]"
        if profile.get("type") != "helm":
            fail(f"{path}.type must be 'helm' (got {profile.get('type')!r}; 'helm.v3' is rejected)")
        else:
            ok(f"{path}.type is helm")
        pid = profile.get("id")
        if not pid or pid in seen_ids:
            fail(f"{path}.id must be present and unique (got {pid!r})")
        seen_ids.add(pid)
        components = profile.get("components") or []
        if not components:
            fail(f"{path}.components must not be empty")
        for j, comp in enumerate(components):
            cpath = f"{path}.components[{j}]"
            name = comp.get("name")
            if not name or not COMPONENT_NAME_PATTERN.match(name) or name in component_names:
                fail(f"{cpath}.name must be unique and match ^[a-z0-9-]*$ (got {name!r})")
            else:
                ok(f"{cpath}.name {name!r}")
            component_names.add(name)
            props = comp.get("properties") or {}
            repository = props.get("repository")
            revision = props.get("revision")
            if not isinstance(repository, str) or not OCI_REPOSITORY_PATTERN.match(repository):
                fail(f"{cpath}.properties.repository must match ^oci://.+ (got {repository!r})")
            elif repository != expected_repository:
                fail(f"{cpath}.properties.repository must be {expected_repository} (got {repository})")
            else:
                ok(f"{cpath}.properties.repository {repository}")
            if not isinstance(revision, str) or not SEMVER_REVISION_PATTERN.match(revision):
                fail(f"{cpath}.properties.revision must be a SemVer 2.0 string without a leading v (got {revision!r})")
            elif revision != version:
                fail(f"{cpath}.properties.revision {revision} differs from the pin {version} in scripts/charts.tsv")
            else:
                ok(f"{cpath}.properties.revision {revision} (SemVer, equals the pin)")
            timeout = props.get("timeout")
            if timeout is not None and not (isinstance(timeout, str) and TIMEOUT_PATTERN.match(timeout)):
                fail(f"{cpath}.properties.timeout must match ^\\d+m\\d+s$ (got {timeout!r})")
            wait = props.get("wait")
            if wait is not None and not isinstance(wait, bool):
                fail(f"{cpath}.properties.wait must be a boolean (got {wait!r})")

    # Parameters (parseParameters, validateParameterTargets, plus the agent's
    # resolution rules so that a parameter cannot be rejected on the device).
    params = doc.get("parameters") or {}
    if not isinstance(params, dict):
        fail("parameters must be a mapping")
        params = {}
    for key, param in params.items():
        ppath = f"parameters.{key}"
        if not PARAMETER_KEY_PATTERN.match(key):
            fail(f"{ppath}: key must match ^[a-zA-Z_][a-zA-Z0-9_]*$")
        if not isinstance(param, dict):
            fail(f"{ppath} must be a mapping")
            continue
        value = param.get("value")
        if not isinstance(value, str):
            # fleet-manager stringifies the value and the agent sets it as a
            # string, so a YAML false would arrive as "false", which Helm
            # treats as true. Quote every value to make that visible.
            fail(f"{ppath}.value must be a quoted string (got {type(value).__name__} {value!r})")
        targets = param.get("targets") or []
        if not targets:
            fail(f"{ppath} has no targets (fleet-manager drops it and never routes the value)")
        for k, target in enumerate(targets):
            pointer = target.get("pointer")
            comps = target.get("components") or []
            if not isinstance(pointer, str) or not pointer or "" in pointer.split("."):
                fail(f"{ppath}.targets[{k}].pointer {pointer!r} must be a dot path without empty segments")
            if not comps:
                fail(f"{ppath}.targets[{k}] names no component")
            for c in comps:
                if c not in component_names:
                    fail(f"{ppath}.targets[{k}] names unknown component {c!r}")
    if params:
        ok(f"{len(params)} parameters, each with a string value and targets")

    # configuration must refer to declared parameters and schemas.
    conf = doc.get("configuration")
    if conf:
        schemas = {s.get("name") for s in conf.get("schema") or []}
        for section in conf.get("sections") or []:
            for setting in section.get("settings") or []:
                if setting.get("parameter") not in params:
                    fail(f"configuration setting {setting.get('name')!r} refers to unknown parameter {setting.get('parameter')!r}")
                if setting.get("schema") not in schemas:
                    fail(f"configuration setting {setting.get('name')!r} refers to unknown schema {setting.get('schema')!r}")
        ok("configuration settings refer to declared parameters and schemas")

    # A parameter resolution must not fail on the device.
    try:
        resolve(doc)
        ok("parameters resolve like the kubernetes-agent (no conflicting pointers)")
    except ValueError as e:
        fail(f"parameter resolution: {e}")


# ------------------------------------------------------------------- values

def set_path(values, segs, value):
    cur = values
    for i, seg in enumerate(segs):
        existing = cur.get(seg)
        if i == len(segs) - 1:
            if existing is None:
                cur[seg] = value
            elif isinstance(existing, str):
                if existing != value:
                    raise ValueError(f"{'.'.join(segs)} is set twice to different values")
            else:
                raise ValueError(f"{'.'.join(segs)} conflicts with another target below it")
            return
        if existing is None:
            cur[seg] = {}
            cur = cur[seg]
        elif isinstance(existing, dict):
            cur = existing
        else:
            raise ValueError(f"{'.'.join(segs[:i + 1])} conflicts with a value another target set")


def resolve(doc):
    """kubernetes-agent resolveParameters: name order, targets in document
    order, every value a string (fleet-manager's String(value); null is "")."""
    components = [c["name"] for p in profiles_of(doc) for c in p.get("components") or []]
    values = {c: {} for c in components}
    params = doc.get("parameters") or {}
    for name in sorted(params):
        param = params[name]
        raw = param.get("value")
        if raw is None:
            continue  # fleet-manager emits nothing without a value
        if isinstance(raw, bool):
            value = "true" if raw else "false"
        else:
            value = str(raw)
        for target in param.get("targets") or []:
            segs = target["pointer"].split(".")
            for comp in target.get("components") or [components[0]]:
                set_path(values[comp], segs, value)
    return values


def cmd_values(margo_path, out_dir):
    doc = load_yaml(margo_path)
    values = resolve(doc)
    for comp, vals in values.items():
        with open(os.path.join(out_dir, f"{comp}.values.yaml"), "w", encoding="utf-8") as f:
            # default_style='"' quotes every scalar: these are strings, as on the agent.
            yaml.safe_dump(vals, f, default_style='"', sort_keys=True)
        print(comp)


# ----------------------------------------------------------------- rendered

def pod_specs(doc):
    kind = doc.get("kind")
    spec = doc.get("spec") or {}
    if kind == "Pod":
        return [spec]
    if kind == "CronJob":
        return [((spec.get("jobTemplate") or {}).get("spec") or {}).get("template", {}).get("spec") or {}]
    template = spec.get("template")
    if isinstance(template, dict) and isinstance(template.get("spec"), dict):
        return [template["spec"]]
    return []


def check_arch(where, pod, archs):
    """A pod must be schedulable on every architecture the app declares."""
    pinned = (pod.get("nodeSelector") or {}).get("kubernetes.io/arch")
    if pinned is not None and archs and set(archs) - {pinned}:
        fail(f"{where}: nodeSelector kubernetes.io/arch={pinned} excludes declared architectures {sorted(set(archs) - {pinned})}")
    terms = ((((pod.get("affinity") or {}).get("nodeAffinity") or {})
              .get("requiredDuringSchedulingIgnoredDuringExecution") or {}).get("nodeSelectorTerms") or [])
    for term in terms:
        for expr in term.get("matchExpressions") or []:
            if expr.get("key") == "kubernetes.io/arch" and expr.get("operator") == "In":
                missing = set(archs) - set(expr.get("values") or [])
                if missing:
                    fail(f"{where}: node affinity on kubernetes.io/arch excludes declared architectures {sorted(missing)}")


def check_pod(where, pod):
    problems = []
    for field in ("hostNetwork", "hostPID", "hostIPC"):
        if pod.get(field):
            problems.append(f"{field} is true")
    psc = pod.get("securityContext") or {}
    for v in pod.get("volumes") or []:
        types = [k for k in v if k != "name"]
        bad = [t for t in types if t not in RESTRICTED_VOLUME_TYPES]
        if bad:
            problems.append(f"volume {v.get('name')!r} uses {bad}")
    containers = (pod.get("initContainers") or []) + (pod.get("containers") or []) + (pod.get("ephemeralContainers") or [])
    for c in containers:
        name = c.get("name")
        sc = c.get("securityContext") or {}
        for p in c.get("ports") or []:
            if p.get("hostPort"):
                problems.append(f"container {name}: hostPort {p['hostPort']}")
        if sc.get("privileged"):
            problems.append(f"container {name}: privileged")
        if sc.get("allowPrivilegeEscalation") is not False:
            problems.append(f"container {name}: allowPrivilegeEscalation is not false")
        caps = sc.get("capabilities") or {}
        if "ALL" not in (caps.get("drop") or []):
            problems.append(f"container {name}: capabilities.drop does not contain ALL")
        added = [a for a in caps.get("add") or [] if a != "NET_BIND_SERVICE"]
        if added:
            problems.append(f"container {name}: adds capabilities {added}")
        non_root = sc.get("runAsNonRoot", psc.get("runAsNonRoot"))
        if non_root is not True:
            problems.append(f"container {name}: runAsNonRoot is not true")
        if sc.get("runAsUser", psc.get("runAsUser")) == 0:
            problems.append(f"container {name}: runAsUser is 0")
        seccomp = (sc.get("seccompProfile") or psc.get("seccompProfile") or {}).get("type")
        if seccomp not in ("RuntimeDefault", "Localhost"):
            problems.append(f"container {name}: seccompProfile is {seccomp!r}, not RuntimeDefault")
        for field, val in (("runAsNonRoot", sc.get("runAsNonRoot")), ("allowPrivilegeEscalation", sc.get("allowPrivilegeEscalation"))):
            if isinstance(val, str):
                problems.append(f"container {name}: {field} is the string {val!r} (the API server rejects it)")
    if problems:
        for p in problems:
            fail(f"{where}: {p}")
    else:
        ok(f"{where}: Pod Security restricted (static check)")


def cmd_rendered(manifest_path, margo_path):
    archs = []
    for profile in profiles_of(load_yaml(margo_path)):
        archs += (((profile.get("requiredResources") or {}).get("cpu") or {}).get("architectures") or [])
    with open(manifest_path, encoding="utf-8") as f:
        docs = [d for d in yaml.safe_load_all(f) if isinstance(d, dict) and d.get("kind")]
    if not docs:
        fail("helm template rendered no objects")
        return
    kinds = sorted({d["kind"] for d in docs})
    print(f"  INFO  rendered kinds: {', '.join(kinds)}")
    for d in docs:
        kind = d["kind"]
        where = f"{kind}/{(d.get('metadata') or {}).get('name')}"
        if kind in CLUSTER_SCOPED_KINDS:
            fail(f"{where}: cluster-scoped kind (the agent refuses the chart)")
        elif kind not in AGENT_CREATABLE_KINDS:
            fail(f"{where}: the agent's namespace-scoped Role cannot create {kind}")
        if (d.get("metadata") or {}).get("namespace") not in (None, os.environ.get("CHECK_NAMESPACE")):
            fail(f"{where}: sets metadata.namespace {d['metadata']['namespace']!r}, not the release namespace")
        for pod in pod_specs(d):
            check_pod(where, pod)
            check_arch(where, pod, archs)
    if not any(d["kind"] in CLUSTER_SCOPED_KINDS for d in docs):
        ok("no cluster-scoped kind")
    if all(d["kind"] in AGENT_CREATABLE_KINDS for d in docs):
        ok("every kind is creatable by the agent's Role")


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    cmd, args = argv[1], argv[2:]
    if cmd == "bart" and len(args) == 3:
        cmd_bart(*args)
    elif cmd == "fleet-manager" and len(args) == 5:
        cmd_fleet_manager(*args)
    elif cmd == "values" and len(args) == 2:
        cmd_values(*args)
    elif cmd == "rendered" and len(args) == 2:
        cmd_rendered(*args)
    else:
        print(__doc__)
        return 2
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
