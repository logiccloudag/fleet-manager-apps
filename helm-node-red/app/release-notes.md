# Release Notes

## 1.2.0-openshift.1

- The chart is now node-red-restricted 0.1.0-openshift.1, a wrapper around the unchanged schwarzit node-red chart 0.40.2 (`helm-node-red/chart`). It removes the chart's fixed `runAsUser`, `runAsGroup` and `fsGroup` (1000), which OpenShift's restricted SCC rejects. OpenShift assigns these IDs from the namespace's UID range. Every Helm parameter pointer now starts with `node-red.`.

- OpenShift only: the images of InfluxDB, Mosquitto, Node-RED and Traefik do not declare a numeric non-root user, so without OpenShift's UID assignment the pod fails `runAsNonRoot` on other Kubernetes distributions. Use the `main` catalog there.

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
