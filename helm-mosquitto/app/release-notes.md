# Release Notes

## 1.0.0

Initial release.

- Chart: mosquitto 18.10.0 from TrueCharts (AGPL-3.0), mirrored unchanged to
  `oci://ghcr.io/logiccloudag/margo-charts/mosquitto`. The chart requires
  Kubernetes 1.33 or later.
- Application: Eclipse Mosquitto 2.0.22, official image
  `docker.io/library/eclipse-mosquitto:2.0.22` (pinned by digest in the chart).
- Runs under Pod Security `restricted` with the chart's defaults (UID 568,
  seccomp `RuntimeDefault`, all capabilities dropped, read-only root file
  system).
- Schedules on amd64 and arm64: `podOptions.nodeSelector=""` removes the
  chart library's default `kubernetes.io/arch: amd64` selector.
- MQTT on port 1883 (Service `<release>`). Anonymous access: the chart has no
  user or password values.
- Message store on a 1Gi PVC and extra configuration on a 100Mi PVC of the
  cluster default StorageClass (the chart's default for both is 100Gi).
