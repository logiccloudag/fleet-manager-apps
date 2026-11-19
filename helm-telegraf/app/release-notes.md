# Release Notes

## 1.0.0

- Initial release. Telegraf 1.40.3 from the official image `docker.io/library/telegraf:1.40.3-alpine` (MIT), copied to `ghcr.io/logiccloudag/margo-images/telegraf:1.40.3-alpine` with the same multi-arch digest and pulled by digest.
- Helm profile: telegraf-restricted 0.1.0, a small chart in `helm-telegraf/chart`. Runs under Pod Security `restricted` (non-root UID 10001, seccomp `RuntimeDefault`, no privilege escalation, all capabilities dropped, read-only root file system). Renders only a ConfigMap, a Service and a Deployment.
- Compose profile: package `oci://ghcr.io/logiccloudag/margo-compose/telegraf` 1.0.0 with the same image and settings.
- Collects Telegraf's own metrics and, by default, the host's CPU, memory and system metrics. Serves everything for Prometheus on port 9273 (`/metrics`, also the health probe).
- Optional MQTT input (for example from the Eclipse Mosquitto app) and optional InfluxDB 2 output (for example to the InfluxDB app). Credentials come from an existing Secret (Kubernetes) or from parameters (compose).
