# fleet-manager-apps

A catalog of Margo applications for fleet-manager. Each app is a Helm-based
Margo `ApplicationDescription`. Devices running the
[kubernetes-agent](https://logiccloud.youtrack.cloud/projects/KA) install the apps.

fleet-manager reads this repository as a **Git registry**: in the UI open
`/<tenant>/repositories/git-registries` (NBI `POST /api/v1/registries/git`).
The sync imports every `*.yaml` file whose `kind` is `ApplicationDescription`.
The file name does not matter. fleet-manager never pulls a chart: the agent
on the device pulls it from the OCI reference in the description.

## Layout

```text
helm-<app>/
  app/margo.yaml          the ApplicationDescription (bart layout)
  app/icon.png            catalog icon (256 px)
  app/release-notes.md    catalog release notes
helm-influxdb/chart/      the influxdb2-restricted wrapper chart (see below)
scripts/charts.tsv        pinned chart per app: name, version, source, sha256
scripts/check.sh          all checks (bart, fleet-manager rules, render, cluster)
scripts/mirror-charts.sh  publishes the pinned charts to the mirror registry
scripts/lib/              helpers of the two scripts
```

Each app has its own directory. Each description has one `helm` deployment
profile with one component, whose chart lives at
`oci://ghcr.io/logiccloudag/margo-charts/<chart>` (public, no credentials).
`revision` is the chart version.

## Apps

| App (`id`) | Chart in `margo-charts` | Upstream chart | Chart license | Application and image | Type |
| --- | --- | --- | --- | --- | --- |
| `grafana` | `grafana` 13.2.7 | `oci://ghcr.io/grafana-community/helm-charts/grafana` 13.2.7 | Apache-2.0 | Grafana 13.2.3, `docker.io/grafana/grafana:13.2.3-distroless` (AGPL-3.0) | mirror |
| `influxdb` | `influxdb2-restricted` 0.1.0 | `influxdb2` 2.1.2 from `https://helm.influxdata.com` (a dependency) | MIT | InfluxDB 2.9.1, `docker.io/library/influxdb:2.9.1-alpine` (MIT) | wrapper |
| `mosquitto` | `mosquitto` 18.10.0 | `oci://oci.trueforge.org/truecharts/mosquitto` 18.10.0 | AGPL-3.0 | Eclipse Mosquitto 2.0.22, `docker.io/library/eclipse-mosquitto:2.0.22` (EPL-2.0/EDL-1.0), digest-pinned | mirror |
| `node-red` | `node-red` 0.40.2 | `oci://ghcr.io/schwarzit/charts/node-red` 0.40.2 | Apache-2.0 | Node-RED 4.1.2, `docker.io/nodered/node-red:4.1.2` (Apache-2.0) | mirror |

- **mirror**: `scripts/mirror-charts.sh` pushes the upstream `.tgz`
  unchanged. Its SHA-256 is pinned in `scripts/charts.tsv`.
- **wrapper**: the chart is packaged from `helm-<app>/chart`. It contains
  the upstream chart unchanged as a dependency, whose `.tgz` SHA-256 is pinned.

Every image is an official upstream image. No Bitnami chart or image is used.

### Why these charts

- **Grafana.** The `grafana` chart in `grafana/helm-charts` is deprecated.
  It moved to `grafana-community/helm-charts`, a verified publisher.
- **Node-RED.** The schwarzit chart is restricted-compliant by default.
- **Mosquitto.** No official chart exists. The community charts we checked
  render no security context, and a string parameter cannot add one (see
  "kubernetes-agent constraints"). Those charts were HelmForge 1.5.0, k8sonlab
  2.7.3, alekc 0.3.0 and bdclark 0.6.1. TrueCharts (trueforge-org/truecharts,
  about 1,350 stars) is the only large-community chart that is restricted by
  default and uses the official image. Three caveats:
  - its license is AGPL-3.0: unchanged redistribution is permitted with the
    license and a source reference (the chart's `sources`), but confirm that
    a copyleft chart is acceptable before you use it outside test fleets;
  - it requires Kubernetes 1.33 or later (`kubeVersion: '>=1.33.0-0'`);
  - its common library pins pods to `kubernetes.io/arch: amd64`, which the
    fixed parameter `podNodeSelector: ""` removes.
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
   Deployment, ReplicaSet, StatefulSet, DaemonSet, Job and CronJob. A chart
   that renders a Role, RoleBinding, PodDisruptionBudget, NetworkPolicy,
   Ingress or ServiceMonitor fails with `forbidden`.
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
   architecture listed in `requiredResources.cpu.architectures` (amd64 and
   arm64 here).
8. **Images.** The device must be able to pull the images. On clusters whose
   `docker.io` mirror is the logiccloud ACR (`logiccloud.azurecr.io/mirror/docker.io/...`),
   the images above must be imported into that mirror first.

Release names are `<component>-<hash>`, set by the agent. Removing a
deployment uninstalls the release. The InfluxDB data PVC survives the
uninstall, because the upstream chart marks it `helm.sh/resource-policy: keep`:
delete it by hand when the data is no longer needed. The fixed
parameters (for example `rbacCreate`, `initChownDataEnabled` and
`persistenceEnabled`) keep a chart inside these constraints. They are
documented in each `margo.yaml` and are not listed in `configuration`, so
the fleet-manager UI does not offer them. Do not override them.

## Known issues

- **kubernetes-agent 0.25.3 (main 46c46dc) rejects Grafana and mosquitto.** The
  agent's pre-apply cluster-scope guard (`renderManifest` in
  `internal/deploy/helm.go`) renders the chart client-only with Helm's default
  capabilities, which report Kubernetes v1.20.0. A chart whose `kubeVersion`
  excludes 1.20 therefore fails with `chart requires kubeVersion: ... which is
  incompatible with Kubernetes v1.20.0`, before the real install would run
  against the cluster's version. Affected here:
  - Grafana (`^1.25.0-0`);
  - mosquitto (`>=1.33.0-0`).

  InfluxDB and Node-RED declare no `kubeVersion` and install. The fix is
  to set `install.KubeVersion` and `install.APIVersions` from the cluster's
  capabilities in the guard render.

## Validation

Run all checks:

```sh
scripts/check.sh                       # every app
scripts/check.sh helm-grafana          # one app
scripts/check.sh --cluster             # plus the cluster stage (see below)
CHART_SOURCE=mirror scripts/check.sh   # check the published charts instead of upstream
```

Requirements: `docker`, `helm` (3.14+ or 4), `python3` with PyYAML; `kubectl`
for `--cluster`; `kubeconform` (optional, recommended).

The script prints every finding and a summary table. It exits non-zero
on any failure. The stages for each app are:

1. **bart validate.** The script runs FLECS bart
   (`cr.flecs.tech/flecs/bart:latest`) unchanged against the app directory:
   - the Margo JSON Schema check of `app/margo.yaml`;
   - icon, release notes and CPU architectures.

   bart 0.4.x always reads `compose/compose.yaml`, also for a `type: helm`
   profile. It has no option to skip that, and `package` and `push` are
   compose-only. A helm-only app therefore always gets exactly one bart
   failure: `compose/compose.yaml - ./compose/compose.yaml: No such file or
   directory`. The script tolerates that one failure, and only when every
   profile is `helm`. Any other failure, including the schema check, fails
   the stage. No stub `compose.yaml` is committed: it would make bart's
   compose lints pass vacuously. To see bart's own output:

   ```sh
   docker run --rm -u "$(id -u):$(id -g)" -v "$PWD/helm-grafana:/w" -w /w cr.flecs.tech/flecs/bart:latest validate
   ```

2. **fleet-manager rules.** These are the ingest rules of
   `margo-manifest-parser.service.ts`:
   - top-level `id`, `kind`, `metadata.name`, `version` and `catalog`;
   - profile `type: helm`, `oci://` repository, SemVer revision;
   - parameter keys, and parameters with targets.

   This catalog adds its own rules:
   - the repository is `oci://ghcr.io/logiccloudag/margo-charts/<chart>`;
   - the revision equals the pin;
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
   5. `kubeconform -strict` runs, which catches a string where the API
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
4. Validate with `scripts/check.sh <app>` and with `scripts/check.sh --cluster
   <app>` on a test cluster.
5. Publish with `scripts/mirror-charts.sh <app>` (see below), then commit.
   A published version is never overwritten: a change needs a new version.

## Publishing

`scripts/mirror-charts.sh [--dry-run] [app...]` pulls each pinned chart and
checks its SHA-256. It then pushes the chart to `MIRROR_REGISTRY`
(default `oci://ghcr.io/logiccloudag/margo-charts`) and pulls it back to
compare. A mirror chart is pushed byte-identical. A version that already
exists is skipped when its content is identical, and is an error otherwise.

1. Grant the scope and log in:

   ```sh
   gh auth refresh -s write:packages,read:packages
   gh auth token | helm registry login ghcr.io -u <github-user> --password-stdin
   ```

2. Run `scripts/mirror-charts.sh --dry-run`, then `scripts/mirror-charts.sh`.
3. New ghcr.io packages are private. For each package, open
   `https://github.com/orgs/logiccloudag/packages/container/margo-charts%2F<chart>/settings`,
   go to "Danger Zone", choose "Change visibility" and select **Public**.
4. Log out (`helm registry logout ghcr.io`). Verify each package anonymously:

   ```sh
   helm pull oci://ghcr.io/logiccloudag/margo-charts/grafana --version 13.2.7
   CHART_SOURCE=mirror scripts/check.sh
   ```
