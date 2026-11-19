# Release Notes

## 1.5.0

- New setting `allowEmbedding` (section Sharing): `[security] allow_embedding` in `grafana.ini`, set through Grafana's environment override `GF_SECURITY_ALLOW_EMBEDDING`. `true` lets other web pages show Grafana in an iframe; `false` (the default, as in Grafana) keeps browsers from embedding it. An embedded dashboard still needs a login, or a public dashboard (`publicDashboards`).
- Compose package 1.3.0. The chart is unchanged.

## 1.4.0

- New setting `publicDashboards` (section Sharing): `[public_dashboards] enabled` in `grafana.ini`, set through Grafana's environment override `GF_PUBLIC_DASHBOARDS_ENABLED`. `true` (the default, as in Grafana) allows sharing a dashboard through a public link without login; `false` switches public dashboards off, and existing public links stop working.
- Compose package 1.2.0. The chart is unchanged.

## 1.3.2

- Compose package 1.1.1: the image is referenced by tag only (`ghcr.io/logiccloudag/margo-images/grafana:13.2.4-distroless`), without `@sha256:` digest. The FLECS device agent rejected the `tag@digest` form with Docker error 400 "invalid reference format", which also aborted the other deployments on the device. The image and its digest are unchanged; the tag is immutable in `ghcr.io/logiccloudag/margo-images`.

## 1.3.1

- The catalog names the vendor, Grafana Labs, instead of logiccloud, which only packages the app.
- New license file `license.txt`: the upstream license text, AGPL-3.0 (Grafana).
- No change to the chart or images.

## 1.3.0

- Margo rc3 ApplicationDescription (apiVersion v1, deviceConstraints); no change to the chart or images.

## 1.2.0

- Chart: grafana 13.2.7 → 13.7.0 (unchanged mirror).
- Image: `ghcr.io/logiccloudag/margo-images/grafana:13.2.4-distroless`, a copy of `docker.io/grafana/grafana:13.2.4-distroless` (13.2.3-distroless before).
- Compose package 1.1.0 with the new image.
- Automatic update by the weekly upstream check (FM-1631).

## 1.1.0

- New compose deployment profile (`compose`), package `oci://ghcr.io/logiccloudag/margo-compose/grafana` 1.0.0. The settings administrator user, administrator password and service port (the host port) apply to it. An empty administrator password means Grafana's default `admin`, which Grafana asks to change at the first login.
- The image now comes from `ghcr.io/logiccloudag/margo-images/grafana:13.2.3-distroless`, a copy of `docker.io/grafana/grafana:13.2.3-distroless` with the same multi-arch digest, pulled by digest. Devices no longer need a `docker.io` mirror. The chart is unchanged; fixed parameters set the image.

## 1.0.2

- `adminPassword` and `adminExistingSecret` may now be left empty (an empty password lets the chart generate one; an empty Secret name uses the password). fleet-manager showed them as required. The chart is unchanged.

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
