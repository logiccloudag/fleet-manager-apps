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
