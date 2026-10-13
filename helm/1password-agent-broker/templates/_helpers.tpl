{{- define "broker.name" -}}
{{- printf "%s-broker" .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- /* Keep selectors independent of chart and image versions so upgrades retain workload membership. */ -}}
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
