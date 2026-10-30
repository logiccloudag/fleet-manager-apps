# fleet-manager-apps

A catalog of Margo applications for fleet-manager. Each app is a Margo
Margo rc3 `ApplicationDescription` (`apiVersion: v1`) with a Helm profile, which devices running the
[kubernetes-agent](https://logiccloud.youtrack.cloud/projects/KA) install.
Grafana, InfluxDB, Mosquitto and Node-RED also have a compose profile for
devices that run Docker Compose (see "Compose profile").

fleet-manager reads this repository as a **Git registry**: in the UI open
`/<tenant>/repositories/git-registries` (NBI `POST /api/v1/registries/git`).
The sync imports every `*.yaml` file that is a Margo rc3 `ApplicationDescription`:
`apiVersion: v1`, no `kind`, with `deploymentProfiles`. fleet-manager rejects
an rc2 file (`kind: ApplicationDescription`) with `RC2_NOT_SUPPORTED`.
The file name does not matter. fleet-manager never pulls a chart or a
compose package: the device pulls it from the OCI reference in the
description.

Every package and image is public on ghcr.io and published from `main` by
GitHub Actions (see "Publishing"). The design is ADR FM-A-202.

## Layout

```text
helm-<app>/
  app/margo.yaml          the ApplicationDescription (bart layout)
  app/icon.png            catalog icon (256 px)
  app/release-notes.md    catalog release notes
  compose/compose.yaml    the compose package (four apps; bart layout)
helm-influxdb/chart/      the influxdb2-restricted wrapper chart (see below)
helm-mosquitto/chart/     the mosquitto-restricted chart (see below)
helm-traefik/chart/       the traefik-restricted chart (see below)
scripts/charts.tsv        pinned chart per app: name, version, source, sha256
scripts/images.tsv        pinned image: name, upstream, tag, digest, apps
scripts/check.sh          all checks (bart, fleet-manager rules, render,
                          compose, cluster, compose smoke)
scripts/mirror-images.sh  copies the pinned images to margo-images
scripts/mirror-charts.sh  publishes the pinned charts to margo-charts
scripts/publish-compose.sh  publishes the compose packages to margo-compose
scripts/verify-public.sh  checks that everything pulls without credentials
scripts/retention.sh      deletes old package versions
scripts/upstream-check.py finds newer upstream versions, regenerates an app
scripts/youtrack-issue.py opens the issue of a major bump or a red gate
scripts/tests/            unit tests of the upstream check
scripts/lib/              helpers of the scripts
scripts/ci/               tool installer and kind setup of the workflows
.github/workflows/        check, publish, retention, upstream-check
```

Each app has its own directory. Each description has one `helm` deployment
profile (`id: kubernetes`) with one component, whose chart lives at
`oci://ghcr.io/logiccloudag/margo-charts/<chart>` (public, no credentials).
`revision` is the chart version. An app with a compose profile
(`id: compose`) has one more component, `<app>-compose`, whose package lives
at `oci://ghcr.io/logiccloudag/margo-compose/<app>`; its `revision` is the
compose package version.

Every image is a copy of the official upstream image at
`ghcr.io/logiccloudag/margo-images/<name>:<tag>`, made by `crane copy`, which
keeps the upstream multi-arch index digest. Charts and compose files
reference it as `<name>:<tag>@<digest>`. `scripts/images.tsv` pins it.

## Apps

| App (`id`) | Chart in `margo-charts` | Upstream chart | Chart license | Application and image | Type |
| --- | --- | --- | --- | --- | --- |
| `grafana` | `grafana` 13.7.0 | `oci://ghcr.io/grafana-community/helm-charts/grafana` 13.7.0 | Apache-2.0 | Grafana 13.2.4, copy of `docker.io/grafana/grafana:13.2.4-distroless` (AGPL-3.0) | mirror |
| `influxdb` | `influxdb2-restricted` 0.2.0 | `influxdb2` 2.1.2 from `https://helm.influxdata.com` (a dependency) | MIT | InfluxDB 2.9.1, copy of `docker.io/library/influxdb:2.9.1-alpine` (MIT) | wrapper |
| `mosquitto` | `mosquitto-restricted` 0.2.0 | none: the chart is in `helm-mosquitto/chart` | this repository | Eclipse Mosquitto 2.1.2, copy of `docker.io/library/eclipse-mosquitto:2.1.2-alpine` (EPL-2.0/EDL-1.0) | local |
| `node-red` | `node-red` 0.40.2 | `oci://ghcr.io/schwarzit/charts/node-red` 0.40.2 | Apache-2.0 | Node-RED 4.1.2, copy of `docker.io/nodered/node-red:4.1.2` (Apache-2.0) | mirror |
| `traefik` | `traefik-restricted` 0.2.1 | none: the chart is in `helm-traefik/chart` | this repository | Traefik v3.7.16, copy of `docker.io/library/traefik:v3.7.16` (MIT) | local |

The compose package of `grafana`, `influxdb`, `mosquitto` and `node-red` is
version 1.0.0. Traefik has no compose profile: it is a Kubernetes ingress
controller.

A mirror chart cannot be changed, so its image is set by fixed parameters
(Grafana: `image.registry`, `image.repository`, `image.tag`, `image.sha`;
Node-RED has no digest field, so `image.tag` is `<tag>@<digest>`). The
wrapper and local charts set it in their `values.yaml`.

- **mirror**: `scripts/mirror-charts.sh` pushes the upstream `.tgz`
  unchanged. Its SHA-256 is pinned in `scripts/charts.tsv`.
- **wrapper**: the chart is packaged from `helm-<app>/chart`. It contains
  the upstream chart unchanged as a dependency, whose `.tgz` SHA-256 is pinned.
- **local**: the chart is packaged from `helm-<app>/chart` and has no
  dependency.

Every image is an official upstream image. No Bitnami chart or image is used.

### Why these charts

- **Grafana.** The `grafana` chart in `grafana/helm-charts` is deprecated.
  It moved to `grafana-community/helm-charts`, a verified publisher.
- **Node-RED.** The schwarzit chart is restricted-compliant by default.
- **Mosquitto.** No official chart exists. The community charts we checked
  (HelmForge 1.5.0, k8sonlab 2.7.3, alekc 0.3.0, bdclark 0.6.1) render no
  security context, and a string parameter cannot add one (see
  "kubernetes-agent constraints"). TrueCharts 18.10.0 is restricted, but it
  is AGPL-3.0, needs Kubernetes 1.33 and allows anonymous access. The
  `mosquitto-restricted` chart in `helm-mosquitto/chart` therefore runs the
  official image itself:
  - it renders a ConfigMap, a Service, an optional PVC and a Deployment;
  - it has fixed Pod Security `restricted` settings (UID 1883, read-only root
    file system);
  - it works on Kubernetes 1.21 and later (`kubeVersion: ">=1.21.0-0"`);
  - anonymous access is off by default;
  - it reads every value string-safely, so `"false"` works.

  To let clients in, create a password file and a Secret in the agent's
  namespace, and set the parameter `authExistingSecret` to its name. A
  non-root init container copies the file into a memory-backed volume, owned
  by the broker's user with mode 0600: mosquitto 2.1 cannot read the
  symlinked key of a Secret volume. A changed Secret takes effect on the next
  pod start.

  ```sh
  docker run --rm --entrypoint sh docker.io/library/eclipse-mosquitto:2.1.2-alpine \
    -c 'mosquitto_passwd -c -b /tmp/passwd <user> <password> >/dev/null 2>&1; cat /tmp/passwd' >passwd
  kubectl -n <agent-namespace> create secret generic mosquitto-users --from-file=passwd=passwd
  ```

- **Traefik.** The upstream chart (`oci://ghcr.io/traefik/helm/traefik`)
  ships 25 CRDs in `crds/`. Helm installs them whatever the values say, and
  the agent may never create a CRD. Its `rbac.namespaced` mode is otherwise
  close to what the agent allows. The `traefik-restricted` chart in
  `helm-traefik/chart` therefore runs the official image itself:
  - it renders a ServiceAccount, a Role, a RoleBinding, a Service and a
    Deployment;
  - Traefik serves the Kubernetes Ingresses of its own namespace only
    (`--providers.kubernetesingress.namespaces`, `disableClusterScopeResources`,
    no IngressClass object), so on a cluster shared by several agents each
    agent's Traefik routes only its own apps;
  - its Role uses only rules the agent holds (`networking.k8s.io`, not
    `extensions`): a Role can never grant more than the agent has;
  - HTTP only, Service type NodePort by default (`serviceType`,
    `webNodePort`);
  - fixed Pod Security `restricted` settings (UID 65532, read-only root file
    system).

  It needs a kubernetes-agent installed with the opt-in
  `workloadPermissions.rbac=true` (KA-211). To reach an app through it, enable
  the app's Ingress (for logiccloud Control: `ingressEnabled: "true"`) and
  open `http://<node address>:<Traefik node port>/`.

- **InfluxDB: why it is wrapped.** We found no maintained, restricted-compliant
  InfluxDB 2 chart.
  - The official `influxdb2` chart renders no `runAsNonRoot`, no seccomp
    profile and no capability drop.
  - The official `influxdb3-core` chart (InfluxDB 3) sets `runAsNonRoot`, but
    no seccomp profile and no capability drop, through the same `toYaml` map.
  - The restricted QuenchWorks chart always renders a NetworkPolicy and a
    PodDisruptionBudget, which the agent's Role cannot create. Its
    `values.schema.json` rejects string values, and QuenchWorks is a very new
    publisher that ships its own rebuilt images.

  The wrapper keeps the official chart unchanged and sets the typed values in
  its own `values.yaml`:
  - the security context;
  - `pdb.create: false`;
  - the 2.9.1 image (the upstream default is 2.7.4).

## Compose profile

The package format is the "Compose Component Registry" of the Margo
specification (pre-draft, margo/specification PR #200, the same document
fleet-manager follows for `repository` and `revision`, ADR-0010-1):

- an OCI artifact with `artifactType`
  `application/vnd.org.margo.component.compose+json`;
- one layer, `application/vnd.org.margo.component.compose.tar+gzip`: a
  `.tar.gz` of `helm-<app>/compose/` under one top-level directory named
  after the component, holding `compose.yaml`;
- the layer annotations `org.margo.component.type=compose` and
  `org.margo.component.version=<revision>`, plus
  `org.opencontainers.image.*`. The layer title is the archive file name,
  which `oras pull` needs.

`scripts/publish-compose.sh` builds the archive deterministically (sorted
entries, owner 0, mtime 0), so the same files always give the same digest.
Never use `docker compose publish`: the spec forbids its format.

Rules of this catalog for `compose.yaml` (`scripts/check.sh` enforces them):

- images only, each `ghcr.io/logiccloudag/margo-images/<name>:<tag>@<digest>`
  pinned in `scripts/images.tsv`;
- no bind mounts, no secrets, no `build`, no host network, PID or IPC, no
  devices, no top-level `name` (the device names the project);
- `cap_drop: [ALL]` and `no-new-privileges:true` on every service, no
  `cap_add`; each service runs as the image's non-root user.

**Parameters.** A target of the `<app>-compose` component names an
environment variable (Margo `Target.pointer` for compose). The spec does not
say whether the device sets that variable in the container environment or
uses it for `${VAR}` interpolation in `compose.yaml` (recorded on FM-1630).
So every variable is written `${VAR:-<parameter value>}`, and where the
container reads it, the environment entry has the same name:
`FOO: ${FOO:-default}`. Both readings then give the same result. Host port
variables (`GRAFANA_PORT`, ...) only work through interpolation.
`scripts/check.sh` fails on a `${VAR}` without a compose target, on a target
that `compose.yaml` does not use, and on a default that differs from the
parameter value. Parameters without a compose target (sizes, resources,
the fixed ones) apply to the Helm profile only; settings that apply to one
profile only say so in their name.

Per app:

- **Grafana.** An empty administrator password means Grafana's default
  `admin`, which Grafana asks to change at the first login.
- **InfluxDB.** Runs as UID 1000. The `DOCKER_INFLUXDB_INIT_*` values apply
  on the first start with an empty volume only. An empty administrator
  password is generated then and stored, readable only by the influxdb user,
  in `/etc/influxdb2/generated-admin-password`; it is never logged.
- **Mosquitto.** Runs as UID 1883 with a read-only root file system. The
  configuration is written at start from the variables. A compose package
  carries no Secret, so the compose-only settings user name and password
  create a password file with one user in memory.
- **Node-RED.** The image's health check gates `docker compose up --wait`.
  The editor has no login: publish its port only on a trusted network.

## kubernetes-agent constraints

Every app here must meet these constraints. `scripts/check.sh` enforces
constraints 1 to 7; `--cluster` also exercises 8 on the test cluster.

1. **OCI charts only.** `repository: oci://...` and `revision` is SemVer with
   no leading `v`. The profile `type` is `helm` (fleet-manager rejects
   `helm.v3`). The top-level `id` matches `^[a-z0-9-]{1,200}$`.
2. **Parameters are strings.** fleet-manager sends `String(value)` for each
   declared parameter that has `targets`. The agent sets it at the dot path
   `targets[].pointer`, like `helm --set-string`. Consequences:
   - Typed values cannot be set through a parameter. This covers
     `runAsNonRoot: "true"` and `runAsUser: "1000"`, which the API server
     rejects, and lists such as `capabilities.drop`. They must be chart
     defaults, or wrapper values.
   - Helm treats every non-empty string as true. `"false"` therefore
     switches nothing off. To switch off a chart boolean that defaults to true,
     the parameter value must be the empty string `""` (for example
     `rbac.create: ""`). A parameter without targets never reaches the agent.
   - A chart with a typed `values.schema.json` rejects a string where it wants
     a number or a boolean.
   - Quote every `value` in `margo.yaml`. `scripts/check.sh` fails on an
     unquoted boolean or number.
3. **No cluster-scoped kinds.** The agent refuses a chart that renders a
   CustomResourceDefinition, ClusterRole, ClusterRoleBinding, a webhook
   configuration, StorageClass, PriorityClass, APIService or Namespace
   (`internal/deploy/helm.go`).
4. **Only kinds the agent's Role can create.** The baseline Role (KA-A-20)
   allows Service, ConfigMap, PersistentVolumeClaim, ServiceAccount, Secret,
   Deployment, ReplicaSet, StatefulSet, DaemonSet, Job and CronJob, and by
   default also Ingress (`workloadPermissions.ingresses`, KA-208). Role and
   RoleBinding need an agent installed with the opt-in
   `workloadPermissions.rbac=true` (KA-211; the fleet-manager dev
   environment sets it), and a Role may only grant rules the agent holds
   itself (Kubernetes RBAC escalation prevention; the agent has no
   `escalate` or `bind`). A chart that renders a PodDisruptionBudget,
   NetworkPolicy or ServiceMonitor, or a Role with rules the agent lacks,
   fails with `forbidden`. Apps that bring a Role (Traefik) say so in their
   description.
5. **Pod Security `restricted`.** The agent's namespaces enforce it. Every
   container must have:
   - `runAsNonRoot`;
   - seccomp `RuntimeDefault`;
   - `allowPrivilegeEscalation: false`;
   - all capabilities dropped.

   In addition, the pod must not use hostPath, hostNetwork or hostPort, and
   must not run root init containers (for example Grafana's
   `init-chown-data`).
6. **One namespace.** The agent installs into its own namespace, and only
   there. **The deployment target namespace in fleet-manager must equal the
   agent's namespace**, or the agent rejects the deployment
   (`internal/reconcile/verifier.go`). The wizard's default (the tenant slug)
   is wrong for every agent. The agent namespaces are
   `kubernetes-agent-dev`, `agent-k3s`, `agent-talos` and `agent-microshift`.
   Apps that talk to each other (for example Grafana to InfluxDB) do so
   inside that namespace.
7. **Storage and scheduling.** PVCs use the cluster's default StorageClass.
   Each volume size is a parameter. No pod may be pinned away from an
   architecture listed in `deviceConstraints.capacityRequirements.cpu.architectures` (amd64 and
   arm64 here).
8. **Images.** The device must be able to pull the images. They are public
   copies on `ghcr.io/logiccloudag/margo-images`, pulled by digest, so no
   `docker.io` mirror and no credentials are needed.

Release names are `<component>-<hash>`, set by the agent. Removing a
deployment uninstalls the release. The InfluxDB data PVC survives the
uninstall, because the upstream chart marks it `helm.sh/resource-policy: keep`:
delete it by hand when the data is no longer needed. The fixed
parameters (for example `rbacCreate`, `initChownDataEnabled` and
`persistenceEnabled`) keep a chart inside these constraints. They are
documented in each `margo.yaml` and are not listed in `configuration`, so
the fleet-manager UI does not offer them. Do not override them.

## Known issues

- **Grafana needs a kubernetes-agent with KA-201** (commit `7acc947` on main).
  Older agents render the pre-apply guard
  with Helm's default Kubernetes v1.20.0, and reject every chart whose
  `kubeVersion` excludes 1.20. Grafana declares `^1.25.0-0`.
- **Grafana does not run on MicroShift 4.8** (Kubernetes 1.21): its chart
  requires 1.25. InfluxDB, Mosquitto and Node-RED do.

## Validation

Run all checks:

```sh
scripts/check.sh                       # every app
scripts/check.sh helm-grafana          # one app
scripts/check.sh --cluster             # plus the cluster stage (see below)
scripts/check.sh --compose             # plus the compose smoke test (see below)
CHART_SOURCE=mirror scripts/check.sh   # check the published charts instead of upstream
```

Requirements: `docker` with `docker compose`, `helm` (3.14+ or 4), `python3`
with PyYAML; `kubectl` for `--cluster`; `kubeconform` (optional,
recommended). The `check` workflow runs everything on a kind cluster.

The script prints every finding and a summary table. It exits non-zero
on any failure. The stages for each app are:

1. **bart validate.** The script runs FLECS bart
   (`BART_IMAGE`, default `cr.flecs.tech/flecs/bart:latest`; CI pins it by
   digest) unchanged against the app directory:
   - the Margo JSON Schema check of `app/margo.yaml`;
   - icon, release notes and CPU architectures;
   - the compose lints of `compose/compose.yaml`.

   bart always reads `compose/compose.yaml`, also for a `type: helm`
   profile. A helm-only app (Traefik) therefore always gets exactly one bart
   failure: `compose/compose.yaml - ./compose/compose.yaml: No such file or
   directory`. The script tolerates that one failure, and only when every
   profile is `helm`. Any other failure, including the schema check, fails
   the stage. No stub `compose.yaml` is committed: it would make bart's
   compose lints pass vacuously.

   bart's lint "parameters -> compose ${env}" ignores `Target.components`:
   it expects every pointer of every profile in `compose.yaml`, also the
   Helm value paths of targets that name only the helm component. An app
   with both profiles therefore always gets this failure. The script
   tolerates it only when every pointer it lists belongs to a target that
   names helm components only; a listed compose pointer, or any other
   pointer, fails the stage. The compose targets are checked by the
   "compose package" stage.

   bart's bundled Margo JSON Schema types the items of
   `configuration.schema` as the base `Schema` (`name`, `dataType`), not as
   its subtypes, so it rejects every validation rule there, including
   `allowEmpty` (Margo PR #212). fleet-manager needs `allowEmpty: true` to
   show a setting with an empty default as optional (for example Traefik's
   `webNodePort`). The script therefore checks those rules itself against
   the subtypes of bart's own schema (`TextValidationSchema`,
   `NumericIntegerValidationSchema`, ...), and bart validates a copy of
   `margo.yaml` without them, so its icon, release-notes and architecture
   checks still run.

   Temporary (FM-1839): the pinned bart bundles the Margo rc2 schema, not
   rc3. The same copy is therefore also rewritten into the rc2 shape: it
   gets `kind: ApplicationDescription`, the rc2 `apiVersion`
   `margo/v1alpha1` and `requiredResources` (from
   `deviceConstraints.capacityRequirements`). bart's icon, release-notes
   and architecture checks still run. The rc3 document itself is checked
   by the "fleet-manager rules" stage. Remove the rewrite when a mirrored
   bart supports rc3. To see bart's own output on the rc3 file (its schema
   check fails there by design):

   ```sh
   docker run --rm -u "$(id -u):$(id -g)" -v "$PWD/helm-grafana:/w" -w /w cr.flecs.tech/flecs/bart:latest validate
   ```

2. **fleet-manager rules.** These are the ingest rules of
   `margo-manifest-parser.service.ts`:
   - `apiVersion: v1`, no `kind`, top-level `id`, `metadata.name`, `version`
     and `catalog`;
   - `deviceConstraints` (capacity patterns, selector operators, JSON Pointer
     keys); `requiredResources` is an error;
   - profile `type: helm` or `compose`, `oci://` repository, SemVer
     revision;
   - parameter keys, and parameters with targets.

   This catalog adds its own rules:
   - exactly one helm profile and at most one compose profile, with one
     component each;
   - the helm repository is `oci://ghcr.io/logiccloudag/margo-charts/<chart>`
     and its revision equals the pin;
   - the compose repository is `oci://ghcr.io/logiccloudag/margo-compose/<id>`;
   - a helm target `pointer` is a dot path, a compose target `pointer` an
     environment variable name;
   - every value is a quoted string;
   - icon and release notes exist;
   - the parameters resolve without a conflict.
3. **Chart.** By default the upstream archive is checked against its pinned
   SHA-256. With `CHART_SOURCE=mirror`, the chart is pulled from the mirror
   registry and must be byte-identical.
4. **Render.**
   1. The parameter defaults are resolved exactly like the agent: name order,
      every value a string.
   2. `helm template --include-crds` renders the chart with those values.
   3. The render must contain no cluster-scoped kind, and only kinds the
      agent's Role can create.
   4. A static Pod Security `restricted` check runs on every pod template, and
      no pod may be pinned away from a declared CPU architecture.
   5. Every container image is a pinned copy,
      `ghcr.io/logiccloudag/margo-images/<name>:<tag>@<digest>` of a row of
      `scripts/images.tsv` for the app.
   6. `kubeconform -strict` runs, which catches a string where the API
      expects a number or a boolean.
5. **Cluster (`--cluster`).** The stage runs on the current `kubectl` context
   (`KUBECONFIG`):
   1. It creates a scratch namespace (`CHECK_NAMESPACE`, default
      `fleet-manager-apps-check`). The namespace is labelled
      `pod-security.kubernetes.io/enforce|warn|audit=restricted`.
   2. It acts as a ServiceAccount bound to the agent's baseline Role.
   3. It runs `kubectl apply --dry-run=server`, where no warning is allowed.
   4. It runs `helm install --dry-run=server`.
   5. It runs a real `helm install --wait`. Every pod must be Ready and no
      `FailedCreate` event is allowed.
   6. It runs `helm uninstall`.
   7. It deletes the namespace at the end.

   Never point `CHECK_NAMESPACE` at a namespace in use: the script refuses an
   existing namespace.

   The `check` workflow points the kind nodes' `ghcr.io` pulls at a local
   registry that `scripts/mirror-images.sh` fills with the same digests
   (`scripts/ci/kind-with-mirror.sh`), so the stage pulls the exact
   references before they are published.
6. **Compose package** (apps with a compose profile). The package is built
   as for publishing and checked: the archive layout (one top-level
   directory, `compose.yaml`, no links, no absolute or `../` paths, no
   setuid bits), the rules and parameters of "Compose profile", and
   `docker compose config` with the parameter defaults.
7. **Compose smoke (`--compose`).** `docker compose up --wait` with the
   parameter defaults (`COMPOSE_WAIT_TIMEOUT`, default 300 s). Every
   container must be running, and healthy where it has a health check. Then
   `docker compose down -v`. `SMOKE_IMAGE_REGISTRY` pulls the images from
   another registry with the same digests (the workflow's local registry).

## Bumping a chart

1. Pick the new upstream version. Check its release notes, license and
   image for changes.
2. Download it, and record its SHA-256 in `scripts/charts.tsv`:

   ```sh
   helm pull oci://ghcr.io/grafana-community/helm-charts/grafana --version <v>
   shasum -a 256 grafana-<v>.tgz
   ```

3. Edit the app:
   1. In `scripts/charts.tsv`, set `version` and `sha256`.
   2. In `app/margo.yaml`, set `revision` to the same version. Bump
      `metadata.version` (minor for a chart bump, patch for a parameter or
      text change). Re-check every pointer against the new chart's
      `values.yaml`.
   3. In `app/release-notes.md`, add a section for the new `metadata.version`.

   For the InfluxDB wrapper, the steps differ:
   1. Change the dependency version in `helm-influxdb/chart/Chart.yaml`.
   2. Run `helm dependency update helm-influxdb/chart` and commit
      `Chart.lock`.
   3. Bump the wrapper's own `version`.
   4. Put the dependency's SHA-256 and the wrapper version in
      `scripts/charts.tsv`.
4. Validate with `scripts/check.sh <app>`, and with `scripts/check.sh
   --cluster --compose <app>` on a test cluster (the `check` workflow runs
   both on every pull request).
5. Merge to `main`: the `publish` workflow publishes the chart. A published
   version is never overwritten: a change needs a new version.

## Bumping an image

1. Pick the new upstream tag and read its multi-arch index digest:
   `crane digest docker.io/<upstream>:<tag>`.
2. In `scripts/images.tsv`, set `tag` and `digest`.
3. Change every reference to `ghcr.io/logiccloudag/margo-images/<name>:<tag>@<digest>`:
   - a mirror chart: the fixed image parameters in `app/margo.yaml`;
   - a wrapper or local chart: `values.yaml`, and bump the chart `version`
     (in `Chart.yaml`, `scripts/charts.tsv` and `revision`);
   - `compose/compose.yaml`, and bump the compose `revision`.
4. Bump `metadata.version` and add release notes. `scripts/check.sh` fails
   on any reference that does not match `scripts/images.tsv`.

## Changing a compose package

Any change under `helm-<app>/compose/` needs a new compose `revision` in
`app/margo.yaml` (minor for a feature, patch for a fix), a new
`metadata.version` and release notes. Publishing a changed package under an
existing revision fails.

## Weekly upstream check

The `upstream-check` workflow (Mondays 05:00 UTC, FM-1631) looks for newer
stable upstream versions of every pin:

| Pin | Upstream source |
| --- | --- |
| mirror chart (Grafana, Node-RED) | the chart's OCI tags |
| wrapper chart (InfluxDB) | its dependency in the Helm repository index |
| image, `track` `tags` (InfluxDB, Mosquitto, Traefik) | the newest upstream tag of the same shape: same prefix and suffix (`2.9.1-alpine`, `v3.7.14`), no `rc`, `alpha`, `beta`, `dev` or nightly tags |
| image, `track` `chart` (Grafana, Node-RED) | the `appVersion` of the new mirror chart, with the tag's prefix and suffix |

Per pin, `scripts/upstream-check.py plan` records two versions: the
newest within the current major version (the update target) and, when
there is one, the newest major version. An app can get both actions
(FM-1731):

- **An update within the current major** (patch or minor):
  `scripts/upstream-check.py regenerate` rewrites the app. That covers the
  pins, every image reference, the chart version of a wrapper or local
  chart, the revisions, the compose revision when an image changed,
  `metadata.version`, the release notes and the README table. The full gate
  (`scripts/check.sh --cluster --compose <app>`) then runs with the new
  images in a local registry. Green: a commit `chore(<id>): upstream <old>
  → <new>` is pushed, and `publish.yml` is dispatched (a push with the
  `GITHUB_TOKEN` starts no workflow). Red: the changes are undone and an
  issue is opened with the gate log.
- **A new major version:** it is never applied automatically.
  `scripts/youtrack-issue.py` opens a Task in YouTrack project FM. Its
  summary is `fleet-manager-apps: plan <id> upgrade <old> → <new>`, its
  description holds the plan, it is tagged `margo-apps` and it goes on the
  current sprint. One issue per app and target major: while an issue that
  is not Done matches `plan <id> upgrade … → <major>.`, no second one is
  opened, even though the old version in the summary moves with the updates
  within the current major.

  For example, Grafana's chart 13.2.7 gets 13.7.0 automatically, and 14.0.1
  waits in an issue.

An image that follows its chart (`track` `chart`) stays inside the
chart's major as well. If the chart's new `appVersion` would be a new image
major, neither is updated, and the major goes to the issue.

The run summary lists, per app: up to date, regenerated, or issue created
or existing (with link).

By hand, from the Actions tab, `workflow_dispatch` takes these inputs:

- `dry_run`: on by default. It reports the plan and runs the duplicate
  search only.
- `publish`;
- `issue_tag`: a test tag for a forced test;
- `apps`: a subset of the apps.

Locally:

```sh
scripts/upstream-check.py plan /tmp/plan.json        # needs crane and helm
python3 -m unittest discover -s scripts/tests -v     # version arithmetic
```

**Once, by a human:** create the repository secret `YOUTRACK_TOKEN`, a
permanent YouTrack token that may create issues in project FM, tag them and
add them to the board. Without it the workflow fails; it does not skip.

## Publishing

The `publish` workflow (`.github/workflows/publish.yml`) runs on every push
to `main`. It runs the `check` workflow first, then, with the built-in
`GITHUB_TOKEN` (`packages: write`):

1. `scripts/mirror-images.sh` copies the pinned images to
   `ghcr.io/logiccloudag/margo-images`;
2. `scripts/mirror-charts.sh` publishes the pinned charts to
   `oci://ghcr.io/logiccloudag/margo-charts`;
3. `scripts/publish-compose.sh` publishes the compose packages to
   `ghcr.io/logiccloudag/margo-compose`;
4. `scripts/verify-public.sh` pulls everything without credentials.

Each script skips a version that already exists with the same content and
fails (`ERROR:`) when it exists with different content. Each has
`--dry-run`. A mirror chart is pushed byte-identical, an image keeps its
upstream digest, and a compose archive is built deterministically, so a
rerun publishes nothing new.

**Once, by a human (an organisation owner):**

1. The `margo-charts/*` packages were first pushed by hand, so the
   workflow's token cannot write to them. For each one, open the package
   settings, "Manage Actions access", add `fleet-manager-apps` with the role
   **Admin** (Admin also lets `retention` delete old versions). Packages
   that the workflow creates are linked to the repository automatically.
2. New ghcr.io packages are private. After the first run, for each new
   `margo-images/*`, `margo-charts/*` and `margo-compose/*` package, open
   `https://github.com/orgs/logiccloudag/packages/container/<package>/settings`
   (the name with `/` encoded as `%2F`), go to "Danger Zone", choose
   "Change visibility" and select **Public**. Until then `verify-public`
   fails and lists the private packages; rerun it afterwards.

**Retention.** The `retention` workflow (weekly, or by hand with `delete`)
runs `scripts/retention.sh`. It keeps the 5 newest tagged versions of each
package, every version that `main` pins, and every untagged version (the
platform manifests of a multi-arch image are untagged children of its
index). Without `--delete` the script prints its plan only.

**By hand.** The scripts also run locally. Log in with a token that has
`write:packages`:

```sh
gh auth refresh -s write:packages,read:packages
gh auth token | crane auth login ghcr.io -u <github-user> --password-stdin
gh auth token | helm registry login ghcr.io -u <github-user> --password-stdin
gh auth token | oras login ghcr.io -u <github-user> --password-stdin
scripts/mirror-images.sh --dry-run && scripts/mirror-images.sh
scripts/mirror-charts.sh --dry-run && scripts/mirror-charts.sh
scripts/publish-compose.sh --dry-run && scripts/publish-compose.sh
```

For a local test registry, `crane registry serve --address 127.0.0.1:5001`
works with `IMAGE_REGISTRY`, `MIRROR_REGISTRY` and `COMPOSE_REGISTRY` set to
it, plus `CRANE_INSECURE=1`, `MIRROR_PLAIN_HTTP=1` and `ORAS_PLAIN_HTTP=1`.
