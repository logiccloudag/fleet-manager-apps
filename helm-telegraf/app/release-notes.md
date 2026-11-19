# Release Notes

## 1.1.0

- More host metrics, as in the usual Raspberry Pi monitoring setup with InfluxDB and Grafana. `systemMetrics` now also collects swap, kernel, process, disk and disk I/O metrics. The new `networkMetrics` (on by default) collects network interface and connection metrics. The new `temperatureMetrics` (off by default) reads the temperature sensors, for example the SoC.
- Compose profile: two new parameters give read-only host access, both off by default.
  - `networkMode` `host` uses the host's network. Telegraf then reports the host's interfaces and host name, reaches InfluxDB on the same device at `http://127.0.0.1:8086`, and listens on `prometheusPort` of the host.
  - `hostRoot` `/` mounts the host's root file system read-only at `/hostfs`, so Telegraf reports the host's file systems and processes (`HOST_PROC` and the other `HOST_*` variables).
  - Telegraf still runs as UID 10001, without capabilities and with a read-only root file system.
- Kubernetes profile: no host access, because Pod Security `restricted` forbids `hostNetwork` and `hostPath`. CPU, memory, kernel and disk I/O figures are the node's anyway; file systems, processes and network are the pod's.
- The InfluxDB organization and bucket default to `influxdata` and `default`, the values that the InfluxDB app creates. Set `influxdbUrl` and the token to write to it. Telegraf refuses to start when the URL is set and the organization or bucket is empty.
- Chart telegraf-restricted 0.2.0, compose package 1.1.0.

## 1.0.1

- Compose package 1.0.1: the image is referenced by tag only (`ghcr.io/logiccloudag/margo-images/telegraf:1.40.3-alpine`), without `@sha256:` digest. The FLECS device agent rejected the `tag@digest` form with Docker error 400 "invalid reference format", which also aborted the other deployments on the device. The image and its digest are unchanged; the tag is immutable in `ghcr.io/logiccloudag/margo-images`.

## 1.0.0

- Initial release. Telegraf 1.40.3 from the official image `docker.io/library/telegraf:1.40.3-alpine` (MIT), copied to `ghcr.io/logiccloudag/margo-images/telegraf:1.40.3-alpine` with the same multi-arch digest and pulled by digest.
- Helm profile: telegraf-restricted 0.1.0, a small chart in `helm-telegraf/chart`. Runs under Pod Security `restricted` (non-root UID 10001, seccomp `RuntimeDefault`, no privilege escalation, all capabilities dropped, read-only root file system). Renders only a ConfigMap, a Service and a Deployment.
- Compose profile: package `oci://ghcr.io/logiccloudag/margo-compose/telegraf` 1.0.0 with the same image and settings.
- Collects Telegraf's own metrics and, by default, the host's CPU, memory and system metrics. Serves everything for Prometheus on port 9273 (`/metrics`, also the health probe).
- Optional MQTT input (for example from the Eclipse Mosquitto app) and optional InfluxDB 2 output (for example to the InfluxDB app). Credentials come from an existing Secret (Kubernetes) or from parameters (compose).
