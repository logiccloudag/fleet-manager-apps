# Release Notes

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
