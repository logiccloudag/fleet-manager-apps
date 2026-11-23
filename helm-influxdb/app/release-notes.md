# Release Notes

## 1.4.0

- Image: `ghcr.io/logiccloudag/margo-images/influxdb:2.10.1-alpine`, a copy of `docker.io/library/influxdb:2.10.1-alpine` (2.9.1-alpine before).
- Compose package 1.2.0 with the new image.
- Automatic update by the weekly upstream check (FM-1631).

## 1.3.0

- New setting `v1Databases` (section InfluxQL): InfluxDB 1.x (v1) databases mapped to buckets (DBRP mappings), for InfluxQL clients such as a Grafana data source with query language InfluxQL, and dashboards written in InfluxQL, that expect a database name other than the bucket's. InfluxDB already maps every bucket to the database of the same name (virtual mappings), so the bucket `telegraf` is the database `telegraf` without an entry. Comma separated entries `bucket:database`, for example `default:telegraf`; empty by default. A missing bucket is created with the initial bucket's retention.
- The mappings are added on every install and upgrade (Kubernetes: a Job of the chart with the operator token) and after every start (compose: in the background). Existing mappings are kept, so this also works for an existing installation; removing an entry does not delete its mapping.
- Chart influxdb2-restricted 0.4.0, compose package 1.1.0.

## 1.2.2

- Compose package 1.0.1: the image is referenced by tag only (`ghcr.io/logiccloudag/margo-images/influxdb:2.9.1-alpine`), without `@sha256:` digest. The FLECS device agent rejected the `tag@digest` form with Docker error 400 "invalid reference format", which also aborted the other deployments on the device. The image and its digest are unchanged; the tag is immutable in `ghcr.io/logiccloudag/margo-images`.

## 1.2.1

- The catalog names the vendor, InfluxData, instead of logiccloud, which only packages the app.
- New license file `license.txt`: the upstream license text, MIT (InfluxDB).
- No change to the chart or images.

## 1.2.0

- Margo rc3 ApplicationDescription (apiVersion v1, deviceConstraints); no change to the chart or images.

## 1.1.0

- New compose deployment profile (`compose`), package `oci://ghcr.io/logiccloudag/margo-compose/influxdb` 1.0.0. The initial setup settings and the service port (the host port) apply to it. An empty administrator password is generated at the first start and stored in `/etc/influxdb2/generated-admin-password` in the container.
- The image now comes from `ghcr.io/logiccloudag/margo-images/influxdb:2.9.1-alpine`, a copy of `docker.io/library/influxdb:2.9.1-alpine` with the same multi-arch digest, pulled by digest. Devices no longer need a `docker.io` mirror. Chart: influxdb2-restricted 0.2.0.

## 1.0.1

- `adminPassword`, `adminToken` and `adminExistingSecret` may now be left empty: the chart then generates a random password and operator token, and an empty Secret name keeps the generated Secret. fleet-manager showed them as required. The chart is unchanged.

## 1.0.0

Initial release.

- Chart: influxdb2-restricted 0.1.0, a logiccloud wrapper in
  `helm-influxdb/chart`, published to
  `oci://ghcr.io/logiccloudag/margo-charts/influxdb2-restricted`. It vendors
  the unchanged upstream chart influxdb2 2.1.2 from influxdata (MIT) as a
  dependency.
- Application: InfluxDB 2.9.1, official image `docker.io/library/influxdb:2.9.1-alpine`
  (the upstream chart's default is 2.7.4).
- Runs under Pod Security `restricted`: UID/GID 1000, seccomp
  `RuntimeDefault`, no privilege escalation, all capabilities dropped (wrapper
  values). No PodDisruptionBudget.
- Web UI and HTTP API on port 8086. The administrator password and the
  operator token are generated when left empty and kept in the Secret
  `<release>-influxdb2-auth`.
- Data on an 8Gi PVC of the cluster default StorageClass. The upstream chart
  keeps the PVC when the release is uninstalled
  (`helm.sh/resource-policy: keep`).
