#!/usr/bin/env python3
"""Checks of one Margo app (a Helm profile and an optional compose profile),
used by scripts/check.sh and scripts/publish-compose.sh.

Subcommands (each prints one line per finding and exits 1 on any failure):

  bart <bart-output> <exit-code> <margo.yaml>
      Interprets the output of `bart validate` for a helm-only app.
  schema-rules <margo.yaml> <out-margo.yaml>
      Checks the validation rules of configuration.schema (allowEmpty,
      minLength, ...) against the Margo validation-schema subtypes and
      writes a copy without them for bart (see cmd_schema_rules).
  fleet-manager <margo.yaml> <app-dir> <chart> <version> <chart-registry> <compose-registry>
      The ingest rules of fleet-manager's margo-manifest-parser.service.ts,
      plus the rules of this catalog (one helm profile, at most one compose
      profile, catalog repositories, pins).
  components <margo.yaml> <type>
      Prints the component names of the profiles of that type.
  values <margo.yaml> <out-dir>
      Resolves the parameter defaults to Helm values exactly like the
      kubernetes-agent (internal/reconcile/parameters.go) and writes
      <out-dir>/<component>.values.yaml. Prints the component names.
  rendered <manifest.yaml> <margo.yaml> <images.tsv> <image-registry> <app-dir-name>
      Kinds, Pod Security "restricted", CPU architecture and image checks of
      a `helm template` output.
  compose <margo.yaml> <app-dir> <images.tsv> <image-registry> <out-dir>
      Builds the compose package of the compose profile as a deterministic
      <out-dir>/<component>.tar.gz and checks it: the archive layout of the
      Margo "Compose Component Registry", the compose file rules of this
      catalog, the images, and that every ${VAR} matches a compose target
      whose parameter value equals its default. Writes
      <out-dir>/<component>.env (the parameter defaults) and, when
      SMOKE_IMAGE_REGISTRY is set, <out-dir>/<component>.smoke.yaml (a
      compose override that pulls the images from there). Prints
      "<component> <repository> <revision>". Prints nothing for an app
      without a compose profile.

Requires Python 3.8+ and PyYAML.
"""

import gzip
import io
import os
import re
import sys
import tarfile

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
# A compose target pointer is an environment variable name.
ENV_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# ${VAR}, ${VAR:-default}, ${VAR-default}, ${VAR:?msg}, ${VAR?msg}; $${ is an
# escaped dollar sign and not a variable.
COMPOSE_VARIABLE = re.compile(r"(?<!\$)\$\{([A-Za-z_][A-Za-z0-9_]*)(?:(:?[-?+])([^}]*))?\}")
COMPOSE_BARE_VARIABLE = re.compile(r"(?<!\$)\$([A-Za-z_][A-Za-z0-9_]*)")
PROFILE_TYPES = ("helm", "compose")

# kubernetes-agent internal/deploy/helm.go clusterScopedKinds
CLUSTER_SCOPED_KINDS = {
    "CustomResourceDefinition", "ClusterRole", "ClusterRoleBinding",
    "ValidatingWebhookConfiguration", "MutatingWebhookConfiguration",
    "StorageClass", "PriorityClass", "APIService", "Namespace",
}
# Kinds the agent's namespace-scoped Role may create (KA-A-20 baseline,
# kubernetes-agent infrastructure/e2e/ka-a-20-baseline.tsv), including the
# optional rows Ingress (workloadPermissions.ingresses, KA-208, on by
# default) and Role/RoleBinding (workloadPermissions.rbac, KA-211, opt-in;
# an app that renders one must say so in its description). Anything else is
# refused by the API server even when it is namespaced (PodDisruptionBudget,
# NetworkPolicy, ServiceMonitor, ...). A Role may only grant rules the agent
# holds itself; the --cluster stage proves that with the agent's Role.
AGENT_CREATABLE_KINDS = {
    "Service", "ConfigMap", "PersistentVolumeClaim", "ServiceAccount", "Secret",
    "Deployment", "ReplicaSet", "StatefulSet", "DaemonSet", "Job", "CronJob",
    "Ingress", "Role", "RoleBinding",
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


# ------------------------------------------------------- schema rules

# The validation-schema subtypes of bart's own Margo JSON Schema
# (TextValidationSchema, BooleanValidationSchema, ...): the rule keys each
# allows besides name and dataType, and their JSON types.
SCHEMA_RULES = {
    "text": {"allowEmpty": bool, "minLength": int, "maxLength": int, "regexMatch": str},
    "boolean": {"allowEmpty": bool},
    "integer": {"allowEmpty": bool, "minValue": int, "maxValue": int},
    "double": {"allowEmpty": bool, "minValue": (int, float), "maxValue": (int, float),
               "minPrecision": int, "maxPrecision": int},
    "select": {"allowEmpty": bool, "multiselect": bool, "options": list},
}


def schema_subtypes(entry):
    """The subtypes a configuration.schema entry may be, by its dataType."""
    data_type = str(entry.get("dataType", ""))
    if "options" in entry or data_type.startswith("array["):
        return ["select"]
    return {"string": ["text", "select"], "boolean": ["boolean"], "integer": ["integer"],
            "double": ["double"]}.get(data_type, [])


def cmd_schema_rules(margo_path, out_path):
    """bart's bundled Margo JSON Schema types configuration.schema items as
    the base Schema (name and dataType, additionalProperties false), never
    as one of its subtypes, so it rejects every validation rule, including
    allowEmpty (Margo PR #212), which fleet-manager needs to show an
    optional setting. bart then skips the icon, release-notes and
    architecture checks too. So the rules are checked here against the
    subtypes of bart's own schema, and bart validates a copy without them."""
    doc = load_yaml(margo_path)
    schema = ((doc.get("configuration") or {}).get("schema")) or []
    stripped = 0
    for entry in schema:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        rules = {k: v for k, v in entry.items() if k not in ("name", "dataType")}
        if not rules:
            continue
        subtypes = schema_subtypes(entry)
        allowed = {}
        for sub in subtypes:
            allowed.update(SCHEMA_RULES[sub])
        bad = [k for k, v in rules.items()
               if k not in allowed or not isinstance(v, allowed[k]) or (allowed[k] is int and isinstance(v, bool))]
        if not subtypes:
            fail(f"configuration.schema '{name}': dataType {entry.get('dataType')!r} has no validation rules")
        elif bad:
            fail(f"configuration.schema '{name}': rule(s) {', '.join(sorted(bad))} not valid for "
                 f"{'/'.join(subtypes)} (allowed: {', '.join(sorted(allowed))})")
        else:
            ok(f"configuration.schema '{name}': rules {', '.join(sorted(rules))} valid for {'/'.join(subtypes)}")
        for k in rules:
            del entry[k]
        stripped += 1
    with open(out_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(doc, f, sort_keys=False, allow_unicode=True)
    if stripped:
        print(f"  INFO  bart validates a copy without the rules of {stripped} schema entr"
              f"{'y' if stripped == 1 else 'ies'} (its bundled schema lacks the subtypes)")


# ------------------------------------------------------------ fleet-manager

def cmd_fleet_manager(margo_path, app_dir, chart, version, registry, compose_registry):
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
    expected_compose_repository = f"{compose_registry.rstrip('/')}/{doc.get('id')}"
    types = [p.get("type") for p in profiles]
    if types.count("helm") != 1:
        fail(f"expected exactly one helm profile, got {types.count('helm')}")
    if types.count("compose") > 1:
        fail(f"expected at most one compose profile, got {types.count('compose')}")
    component_types = {}
    for i, profile in enumerate(profiles):
        path = f"deploymentProfiles[{i}]"
        ptype = profile.get("type")
        if ptype not in PROFILE_TYPES:
            fail(f"{path}.type must be 'helm' or 'compose' (got {ptype!r}; 'helm.v3' is rejected)")
        else:
            ok(f"{path}.type is {ptype}")
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
            component_types[name] = ptype
            props = comp.get("properties") or {}
            repository = props.get("repository")
            revision = props.get("revision")
            want = expected_compose_repository if ptype == "compose" else expected_repository
            if not isinstance(repository, str) or not OCI_REPOSITORY_PATTERN.match(repository):
                fail(f"{cpath}.properties.repository must match ^oci://.+ (got {repository!r})")
            elif repository != want:
                fail(f"{cpath}.properties.repository must be {want} (got {repository})")
            else:
                ok(f"{cpath}.properties.repository {repository}")
            if not isinstance(revision, str) or not SEMVER_REVISION_PATTERN.match(revision):
                fail(f"{cpath}.properties.revision must be a SemVer 2.0 string without a leading v (got {revision!r})")
            elif ptype == "helm" and revision != version:
                fail(f"{cpath}.properties.revision {revision} differs from the pin {version} in scripts/charts.tsv")
            elif ptype == "helm":
                ok(f"{cpath}.properties.revision {revision} (SemVer, equals the pin)")
            else:
                ok(f"{cpath}.properties.revision {revision} (SemVer; the compose package version)")
            if ptype == "compose" and len(components) != 1:
                fail(f"{path}: a compose profile of this catalog has exactly one component")
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
            if not comps:
                fail(f"{ppath}.targets[{k}] names no component")
            kinds = {component_types.get(c) for c in comps}
            for c in comps:
                if c not in component_names:
                    fail(f"{ppath}.targets[{k}] names unknown component {c!r}")
            if len(kinds) > 1:
                fail(f"{ppath}.targets[{k}] mixes helm and compose components (one target per profile type)")
            if kinds == {"compose"}:
                if not isinstance(pointer, str) or not ENV_NAME_PATTERN.match(pointer):
                    fail(f"{ppath}.targets[{k}].pointer {pointer!r} must be an environment variable name for a compose component")
            elif not isinstance(pointer, str) or not pointer or "" in pointer.split("."):
                fail(f"{ppath}.targets[{k}].pointer {pointer!r} must be a dot path without empty segments")
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


def components_of(doc, ptype):
    return [c["name"] for p in profiles_of(doc) if p.get("type") == ptype for c in p.get("components") or []]


def cmd_components(margo_path, ptype):
    for name in components_of(load_yaml(margo_path), ptype):
        print(name)


def cmd_values(margo_path, out_dir):
    doc = load_yaml(margo_path)
    values = resolve(doc)
    helm = set(components_of(doc, "helm"))
    for comp, vals in values.items():
        if comp not in helm:
            continue
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


def load_images(images_tsv, app_dir_name):
    """The pinned image references of an app: {reference: row}."""
    refs = {}
    with open(images_tsv, encoding="utf-8") as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            cols = line.rstrip("\n").split("\t")
            if len(cols) < 5:
                continue
            name, upstream, tag, digest, apps = cols[:5]
            if app_dir_name in apps.split(","):
                refs[(name, tag, digest)] = upstream
    return refs


def check_images(where, images, refs, registry):
    """Every image is <registry>/<name>:<tag>@<digest> of a pin of the app."""
    allowed = {f"{registry}/{n}:{t}@{d}" for (n, t, d) in refs}
    for image in images:
        if image in allowed:
            ok(f"{where}: image {image} (pinned in scripts/images.tsv)")
        else:
            fail(f"{where}: image {image!r} is not <{registry}/name:tag@digest> of a row of scripts/images.tsv for this app")


def cmd_rendered(manifest_path, margo_path, images_tsv=None, registry=None, app_dir_name=None):
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
            if images_tsv:
                containers = (pod.get("initContainers") or []) + (pod.get("containers") or [])
                check_images(where, [c.get("image") for c in containers],
                             load_images(images_tsv, app_dir_name), registry)
    if not any(d["kind"] in CLUSTER_SCOPED_KINDS for d in docs):
        ok("no cluster-scoped kind")
    if all(d["kind"] in AGENT_CREATABLE_KINDS for d in docs):
        ok("every kind is creatable by the agent's Role")


# ------------------------------------------------------------------ compose

def build_archive(src_dir, top, out_path):
    """A deterministic .tar.gz of src_dir under the single top-level directory
    `top`: sorted entries, owner 0/0, mtime 0, modes 0755/0644, no gzip
    name or time, so the same files always give the same OCI digest."""
    entries = []
    for root, dirs, files in os.walk(src_dir):
        dirs.sort()
        for name in sorted(dirs + files):
            full = os.path.join(root, name)
            rel = os.path.relpath(full, src_dir)
            if os.path.islink(full):
                raise ValueError(f"{rel} is a symbolic link (not allowed in a compose package)")
            entries.append((rel, full))
    entries.sort()
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.USTAR_FORMAT) as tar:
        def add(name, full):
            info = tarfile.TarInfo(name)
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mtime = 0
            if full is None or os.path.isdir(full):
                info.type = tarfile.DIRTYPE
                info.mode = 0o755
                tar.addfile(info)
            else:
                with open(full, "rb") as fh:
                    data = fh.read()
                info.size = len(data)
                info.mode = 0o644
                tar.addfile(info, io.BytesIO(data))
        add(top, None)
        for rel, full in entries:
            add(f"{top}/{rel}", full)
    with open(out_path, "wb") as out:
        with gzip.GzipFile(filename="", mode="wb", fileobj=out, mtime=0) as gz:
            gz.write(raw.getvalue())


def check_archive(path, top):
    """The layout rules of the Margo "Compose Component Registry"."""
    with tarfile.open(path, mode="r:gz") as tar:
        members = tar.getmembers()
    tops = {m.name.split("/", 1)[0] for m in members}
    if len(tops) != 1:
        fail(f"archive: expected exactly one top-level directory, got {sorted(tops)}")
    elif tops != {top}:
        fail(f"archive: the top-level directory should be the component name {top!r} (got {sorted(tops)})")
    else:
        ok(f"archive: one top-level directory {top}/")
    names = {m.name for m in members}
    if f"{top}/compose.yaml" in names:
        ok(f"archive: {top}/compose.yaml")
    else:
        fail(f"archive: {top}/compose.yaml is missing (compose.yml and docker-compose.* are not valid)")
    for m in members:
        parts = m.name.split("/")
        if m.name.startswith("/") or ".." in parts:
            fail(f"archive: {m.name}: absolute path or ../")
        if m.issym() or m.islnk():
            fail(f"archive: {m.name}: links are not allowed")
        if not (m.isdir() or m.isfile()):
            fail(f"archive: {m.name}: only files and directories are allowed")
        if m.mode & 0o7000:
            fail(f"archive: {m.name}: setuid, setgid or sticky bit")


def compose_rules(compose, refs, registry):
    """The compose file rules of this catalog."""
    services = compose.get("services") or {}
    if not services:
        fail("compose.yaml: no services")
    images = []
    for svc_name, svc in services.items():
        where = f"compose.yaml: service {svc_name}"
        if "build" in svc:
            fail(f"{where}: build is not allowed (images only)")
        images.append(svc.get("image"))
        if svc.get("privileged"):
            fail(f"{where}: privileged")
        if svc.get("cap_add"):
            fail(f"{where}: cap_add {svc['cap_add']}")
        if "ALL" not in (svc.get("cap_drop") or []):
            fail(f"{where}: cap_drop does not contain ALL")
        if "no-new-privileges:true" not in (svc.get("security_opt") or []):
            fail(f"{where}: security_opt does not contain no-new-privileges:true")
        for field in ("network_mode", "pid", "ipc", "userns_mode"):
            if str(svc.get(field, "")).startswith("host"):
                fail(f"{where}: {field} host")
        if svc.get("devices"):
            fail(f"{where}: devices are not allowed")
        for v in svc.get("volumes") or []:
            source = v.get("source", "") if isinstance(v, dict) else str(v).split(":", 1)[0]
            vtype = v.get("type") if isinstance(v, dict) else None
            if vtype == "bind" or source.startswith(("/", ".", "~", "$")):
                fail(f"{where}: bind mount {v!r} (a compose package must not use bind mounts)")
        for secret in svc.get("secrets") or []:
            fail(f"{where}: secrets are not allowed in a compose package ({secret!r})")
        check_images(where, [svc.get("image")], refs, registry)
    for secret_name, secret in (compose.get("secrets") or {}).items():
        if isinstance(secret, dict) and "file" in secret:
            fail(f"compose.yaml: file-source secret {secret_name!r} is not allowed")
    if "name" in compose:
        fail("compose.yaml: top-level name is not allowed (the device names the project)")
    return images


def cmd_compose(margo_path, app_dir, images_tsv, registry, out_dir):
    doc = load_yaml(margo_path)
    comps = [(p, c) for p in profiles_of(doc) if p.get("type") == "compose" for c in p.get("components") or []]
    if not comps:
        return
    if len(comps) != 1:
        fail(f"expected one compose component, got {len(comps)}")
        return
    _, comp = comps[0]
    name = comp.get("name")
    props = comp.get("properties") or {}
    src = os.path.join(app_dir, "compose")
    compose_file = os.path.join(src, "compose.yaml")
    if not os.path.isfile(compose_file):
        fail(f"{os.path.basename(app_dir)}/compose/compose.yaml does not exist")
        return
    archive = os.path.join(out_dir, f"{name}.tar.gz")
    try:
        build_archive(src, name, archive)
    except ValueError as e:
        fail(f"archive: {e}")
        return
    check_archive(archive, name)

    with open(compose_file, encoding="utf-8") as f:
        text = f.read()
    compose = yaml.safe_load(text) or {}
    compose_rules(compose, load_images(images_tsv, os.path.basename(os.path.normpath(app_dir))), registry)

    # Variables against compose targets. Comment lines are not compose
    # content, so they are left out.
    body = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    params = doc.get("parameters") or {}
    targets = {}
    for key, param in params.items():
        for target in param.get("targets") or []:
            if name in (target.get("components") or []):
                targets[target.get("pointer")] = (key, "" if param.get("value") is None else str(param.get("value")))
    used = {}
    for m in COMPOSE_VARIABLE.finditer(body):
        var, op, default = m.group(1), m.group(2), m.group(3)
        used.setdefault(var, []).append((op, default))
    for m in COMPOSE_BARE_VARIABLE.finditer(body):
        fail(f"compose.yaml: ${m.group(1)} without braces; write ${{{m.group(1)}:-default}}")
    for var, uses in sorted(used.items()):
        if var not in targets:
            fail(f"compose.yaml: ${{{var}}} has no compose target in app/margo.yaml (escape a shell variable as $${{{var}}})")
            continue
        key, value = targets[var]
        bad = [(op, d) for op, d in uses if op != ":-" or (d or "") != value]
        if bad:
            fail(f"compose.yaml: ${{{var}}} must be written ${{{var}:-{value}}} (the value of parameter {key}); found {bad}")
        else:
            ok(f"compose.yaml: ${{{var}:-{value}}} equals parameter {key}")
    for var, (key, _) in sorted(targets.items()):
        if var not in used:
            fail(f"parameter {key}: compose target {var} is not used in compose.yaml")

    with open(os.path.join(out_dir, f"{name}.env"), "w", encoding="utf-8") as f:
        for var, (_, value) in sorted(targets.items()):
            if "\n" in value or "'" in value:
                fail(f"parameter for {var}: a default with a newline or a single quote cannot be written to an env file")
                continue
            f.write(f"{var}='{value}'\n")
    smoke = os.environ.get("SMOKE_IMAGE_REGISTRY")
    if smoke:
        override = {"services": {}}
        for svc_name, svc in (compose.get("services") or {}).items():
            image = str(svc.get("image", ""))
            if image.startswith(registry + "/"):
                override["services"][svc_name] = {"image": smoke.rstrip("/") + image[len(registry):]}
        with open(os.path.join(out_dir, f"{name}.smoke.yaml"), "w", encoding="utf-8") as f:
            yaml.safe_dump(override, f, sort_keys=True)
    print(f"{name} {props.get('repository')} {props.get('revision')}")


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    cmd, args = argv[1], argv[2:]
    if cmd == "bart" and len(args) == 3:
        cmd_bart(*args)
    elif cmd == "schema-rules" and len(args) == 2:
        cmd_schema_rules(*args)
    elif cmd == "fleet-manager" and len(args) == 6:
        cmd_fleet_manager(*args)
    elif cmd == "components" and len(args) == 2:
        cmd_components(*args)
    elif cmd == "values" and len(args) == 2:
        cmd_values(*args)
    elif cmd == "rendered" and len(args) in (2, 5):
        cmd_rendered(*args)
    elif cmd == "compose" and len(args) == 5:
        cmd_compose(*args)
    else:
        print(__doc__)
        return 2
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
