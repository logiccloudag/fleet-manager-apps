# Release Notes

## 1.0.1

- Documents the cluster requirement: **Kubernetes 1.25 or later**. The
  chart declares `kubeVersion: ^1.25.0-0`, so the device agent refuses the
  install on older clusters, for example MicroShift 4.8 (Kubernetes 1.21),
  with "chart requires kubeVersion ... incompatible with Kubernetes v1.21.x".
  Margo has no field for a minimum Kubernetes version, so fleet-manager
  still offers the app for such devices. The kubernetes-agent needs 0.25.4
  or later (KA-201) to evaluate the constraint against the real cluster.
- No chart or parameter change (chart grafana 13.2.7).

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
