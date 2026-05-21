{{/* Common name helpers */}}
{{- define "warn-v2.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "warn-v2.fullname" -}}
{{- printf "%s-%s" .Release.Name (include "warn-v2.name" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "warn-v2.labels" -}}
app.kubernetes.io/name: {{ include "warn-v2.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{- end -}}

{{- define "warn-v2.image" -}}
{{- printf "%s:%s" .Values.image.repository (default .Chart.AppVersion .Values.image.tag) -}}
{{- end -}}

{{- define "warn-v2.envSecrets" -}}
- name: DATABASE_URL
  valueFrom:
    secretKeyRef:
      name: {{ .Values.database.secretName }}
      key: {{ .Values.database.secretKey }}
- name: ANTHROPIC_API_KEY
  valueFrom:
    secretKeyRef:
      name: {{ .Values.anthropic.secretName }}
      key: {{ .Values.anthropic.secretKey }}
- name: GITHUB_TOKEN
  valueFrom:
    secretKeyRef:
      name: {{ .Values.github.secretName }}
      key: {{ .Values.github.secretKey }}
- name: SNAPSHOT_DIR
  value: /var/snapshots
{{- end -}}
