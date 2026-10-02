# Release Notes

## 1.0.0

Initial release.

- Chart: grafana 13.2.7 from grafana-community (Apache-2.0), mirrored
  unchanged to `oci://ghcr.io/logiccloudag/margo-charts/grafana`.
- Application: Grafana 13.2.3, image `docker.io/grafana/grafana:13.2.3-distroless`.
- Runs under Pod Security `restricted`: the chart's defaults (UID 472,
  seccomp `RuntimeDefault`, all capabilities dropped, read-only root file
  system) plus `initChownData.enabled=""` (no root init container).
- Namespace-scoped only: `rbac.create=""` (no Role, RoleBinding or
  ClusterRole) and no `helm test` resources.
- Data on a 5Gi PVC of the cluster default StorageClass.
