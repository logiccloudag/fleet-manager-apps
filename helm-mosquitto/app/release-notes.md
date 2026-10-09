# Release Notes

## 2.0.1

- `authExistingSecret` may now be left empty (no password file). fleet-manager showed it as required. The chart is unchanged.

## 2.0.0

- The chart is now mosquitto-restricted 0.1.0, a small logiccloud chart in
  `helm-mosquitto/chart`, published to
  `oci://ghcr.io/logiccloudag/margo-charts/mosquitto-restricted`. It replaces
  the TrueCharts chart (AGPL-3.0, Kubernetes 1.33 or later).
- Application: Eclipse Mosquitto 2.1.2, official image
  `docker.io/library/eclipse-mosquitto:2.1.2-alpine`, pinned by digest
  (EPL-2.0/EDL-1.0).
- Works on Kubernetes 1.21 and later, including MicroShift.
- **Anonymous access is disabled by default.** Clients authenticate against a
  `mosquitto_passwd` password file in an existing Secret
  (`authExistingSecret`, key `authPasswordFileKey`). A non-root init
  container copies it into a memory-backed volume, owned by the broker's user
  with mode 0600, because mosquitto 2.1 cannot read a Secret volume's
  symlinked key. A changed Secret takes effect on the next pod start.
- Runs under Pod Security `restricted`: UID 1883, seccomp `RuntimeDefault`,
  no privilege escalation, all capabilities dropped, read-only root file
  system. Renders only a ConfigMap, a Service, a PVC and a Deployment.
- Parameters: listener port, Service port and type, persistence on or off,
  volume size, resources.

## 1.0.0

Initial release (TrueCharts mosquitto 18.10.0).
