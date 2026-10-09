# Release Notes

## 1.0.0

Initial release.

- The chart is traefik-restricted 0.1.0, a small logiccloud chart in
  `helm-traefik/chart`, published to
  `oci://ghcr.io/logiccloudag/margo-charts/traefik-restricted`. The upstream
  Traefik chart cannot be used: it ships 25 CRDs, which Helm always installs
  and the kubernetes-agent may never create.
- Application: Traefik v3.7.14, official image
  `docker.io/library/traefik:v3.7.14`, pinned by digest (MIT).
- Serves the Kubernetes Ingresses of the agent's namespace only
  (`disableClusterScopeResources`, no IngressClass object). On a cluster
  shared by several agents, each agent's Traefik routes only its own apps.
- HTTP entry point only. The Service is a NodePort by default
  (`serviceType`, `servicePort`, `webNodePort`).
- Runs under Pod Security `restricted`: UID 65532, seccomp `RuntimeDefault`,
  no privilege escalation, all capabilities dropped, read-only root file
  system. Renders a ServiceAccount, a Role, a RoleBinding, a Service and a
  Deployment.
- **Requires a kubernetes-agent whose Role allows workload RBAC**: the
  opt-in chart value `workloadPermissions.rbac=true` (KA-211, off by
  default). Agents without it, or older ones, fail with `forbidden` on the
  Role.
