{{- define "telegraf.fullname" -}}
{{- if contains "telegraf" .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "telegraf.selectorLabels" -}}
app.kubernetes.io/name: telegraf
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "telegraf.labels" -}}
{{ include "telegraf.selectorLabels" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{- end -}}

{{/* true when a value is true or the string "true" (agent parameters are strings) */}}
{{- define "telegraf.isTrue" -}}
{{- if eq (toString .) "true" -}}true{{- end -}}
{{- end -}}

{{- define "telegraf.port" -}}
{{- $port := int .Values.prometheus.port -}}
{{- if or (lt $port 1024) (gt $port 65535) -}}
{{- fail (printf "prometheus.port must be between 1024 and 65535 (got %v): telegraf runs without capabilities" .Values.prometheus.port) -}}
{{- end -}}
{{- $port -}}
{{- end -}}

{{/* A TOML string. A value with a double quote or a backslash is refused, so a parameter cannot inject configuration. */}}
{{- define "telegraf.toml" -}}
{{- $v := toString . -}}
{{- if or (contains "\"" $v) (contains "\\" $v) (contains "\n" $v) -}}
{{- fail (printf "the value %q must not contain a double quote, a backslash or a newline" $v) -}}
{{- end -}}
{{- printf "%q" $v -}}
{{- end -}}

{{/* A TOML string array from a comma separated value; empty items are dropped. */}}
{{- define "telegraf.tomlList" -}}
{{- $items := list -}}
{{- range splitList "," (toString .) -}}
{{- $item := trim . -}}
{{- if $item -}}
{{- $items = append $items (include "telegraf.toml" $item) -}}
{{- end -}}
{{- end -}}
[{{ join ", " $items }}]
{{- end -}}

{{- define "telegraf.image" -}}
{{- if .Values.image.digest -}}
{{- printf "%s:%s@%s" .Values.image.repository .Values.image.tag .Values.image.digest -}}
{{- else -}}
{{- printf "%s:%s" .Values.image.repository .Values.image.tag -}}
{{- end -}}
{{- end -}}
