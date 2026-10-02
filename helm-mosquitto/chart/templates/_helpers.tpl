{{- define "mosquitto.fullname" -}}
{{- if contains "mosquitto" .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "mosquitto.selectorLabels" -}}
app.kubernetes.io/name: mosquitto
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "mosquitto.labels" -}}
{{ include "mosquitto.selectorLabels" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{- end -}}

{{/* true when a value is true or the string "true" (agent parameters are strings) */}}
{{- define "mosquitto.isTrue" -}}
{{- if eq (toString .) "true" -}}true{{- end -}}
{{- end -}}

{{- define "mosquitto.port" -}}
{{- $port := int .Values.listener.port -}}
{{- if or (lt $port 1024) (gt $port 65535) -}}
{{- fail (printf "listener.port must be between 1024 and 65535 (got %v): the broker runs without capabilities" .Values.listener.port) -}}
{{- end -}}
{{- $port -}}
{{- end -}}

{{- define "mosquitto.image" -}}
{{- if .Values.image.digest -}}
{{- printf "%s:%s@%s" .Values.image.repository .Values.image.tag .Values.image.digest -}}
{{- else -}}
{{- printf "%s:%s" .Values.image.repository .Values.image.tag -}}
{{- end -}}
{{- end -}}
