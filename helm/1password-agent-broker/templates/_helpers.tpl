{{- define "broker.name" -}}
{{- printf "%s-broker" .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- define "broker.selector" -}}
app.kubernetes.io/name: 1password-agent-broker
app.kubernetes.io/instance: {{ .Release.Name | quote }}
{{- end -}}
{{- define "broker.labels" -}}
{{ include "broker.selector" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service | quote }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | quote }}
{{- end -}}
