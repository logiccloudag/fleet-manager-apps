# Release Notes

## 1.1.0

- New compose deployment profile (`compose`), package `oci://ghcr.io/logiccloudag/margo-compose/node-red` 1.0.0. The service port (the host port) applies to it. The editor has no login: publish the port only on a trusted network.
- The image now comes from `ghcr.io/logiccloudag/margo-images/node-red:4.1.2`, a copy of `docker.io/nodered/node-red:4.1.2` with the same multi-arch digest, pulled by digest. Devices no longer need a `docker.io` mirror. The chart is unchanged; fixed parameters set the image.

## 1.0.0

Initial release.

- Chart: node-red 0.40.2 from schwarzit (Apache-2.0), mirrored unchanged to
  `oci://ghcr.io/logiccloudag/margo-charts/node-red`.
- Application: Node-RED 4.1.2, image `docker.io/nodered/node-red:4.1.2`.
- Runs under Pod Security `restricted` with the chart's defaults (UID 1000,
  seccomp `RuntimeDefault`, all capabilities dropped).
- Namespace-scoped only: `rbac.enabled=""` (no Role or RoleBinding).
- Flows and installed nodes on a 5Gi PVC of the cluster default
  StorageClass.
- The editor has no login. It is reachable only through the ClusterIP
  Service.
