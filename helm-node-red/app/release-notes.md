# Release Notes

## 1.2.2

- Compose package 1.0.1: the image is referenced by tag only (`ghcr.io/logiccloudag/margo-images/node-red:4.1.2`), without `@sha256:` digest. The FLECS device agent rejected the `tag@digest` form with Docker error 400 "invalid reference format", which also aborted the other deployments on the device. The image and its digest are unchanged; the tag is immutable in `ghcr.io/logiccloudag/margo-images`.

## 1.2.1

- The catalog names the vendor, OpenJS Foundation, instead of logiccloud, which only packages the app.
- New license file `license.txt`: the upstream license text, Apache-2.0 (Node-RED).
- No change to the chart or images.

## 1.2.0

- Margo rc3 ApplicationDescription (apiVersion v1, deviceConstraints); no change to the chart or images.

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
