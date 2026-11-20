{{- define "traefik.fullname" -}}
{{- if contains "traefik" .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "traefik.selectorLabels" -}}
app.kubernetes.io/name: traefik
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "traefik.labels" -}}
{{ include "traefik.selectorLabels" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{- end -}}

{{- define "traefik.image" -}}
{{- if .Values.image.digest -}}
{{- printf "%s:%s@%s" .Values.image.repository .Values.image.tag .Values.image.digest -}}
{{- else -}}
{{- printf "%s:%s" .Values.image.repository .Values.image.tag -}}
{{- end -}}
{{- end -}}

{{/* The node port as an int, or empty. Fails outside the NodePort range. */}}
{{- define "traefik.nodePort" -}}
{{- if .Values.service.nodePort -}}
{{- $port := int .Values.service.nodePort -}}
{{- if or (lt $port 30000) (gt $port 32767) -}}
{{- fail (printf "service.nodePort must be between 30000 and 32767 (got %v)" .Values.service.nodePort) -}}
{{- end -}}
{{- $port -}}
{{- end -}}
{{- end -}}

{{/*
Pod securityContext. The official traefik image runs as root (no USER), so
runAsNonRoot needs a UID from somewhere:
- OpenShift (API group security.openshift.io/v1 present): no runAsUser or
  runAsGroup. The restricted SCC assigns them from the namespace's UID range
  and rejects fixed IDs.
- Any other cluster: runAsUser and runAsGroup 65532, as nothing assigns them.
`openshift` ("auto", "true", "false") overrides the detection. Keys of
podSecurityContext win over these defaults.
*/}}
{{- define "traefik.podSecurityContext" -}}
{{- $mode := toString (.Values.openshift | default "auto") | lower -}}
{{- if not (has $mode (list "auto" "true" "false")) -}}
{{- fail (printf "openshift must be auto, true or false, not %q" $mode) -}}
{{- end -}}
{{- $openshift := eq $mode "true" -}}
{{- if eq $mode "auto" -}}
{{- $openshift = .Capabilities.APIVersions.Has "security.openshift.io/v1" -}}
{{- end -}}
{{- $ctx := dict "runAsNonRoot" true "seccompProfile" (dict "type" "RuntimeDefault") -}}
{{- if not $openshift -}}
{{- $_ := set $ctx "runAsUser" 65532 -}}
{{- $_ := set $ctx "runAsGroup" 65532 -}}
{{- end -}}
{{- toYaml (mergeOverwrite $ctx (deepCopy (.Values.podSecurityContext | default dict))) -}}
{{- end -}}
