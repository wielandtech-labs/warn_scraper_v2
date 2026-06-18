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

{{/* The enricher may run a derived PRIVATE image (the D&B Hoovers provider).
     Falls back to the public app image when no provider image is configured. */}}
{{- define "warn-v2.enricherImage" -}}
{{- if .Values.enricher.providerImage -}}
{{- .Values.enricher.providerImage -}}
{{- else -}}
{{- include "warn-v2.image" . -}}
{{- end -}}
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
- name: SITE_BASE_URL
  value: {{ printf "https://%s" .Values.api.ingress.host | quote }}
{{- if .Values.smtp.enabled }}
# Host, username, and password all come from the warn-v2-smtp SealedSecret, to
# match the (working) w_tech website setup whose SMTP auth user/host differ from
# the no-reply@ From address. SMTP_FROM is intentionally unset so the app
# defaults From to SMTP_USERNAME (mirrors Django's DEFAULT_FROM_EMAIL=EMAIL_HOST_USER).
- name: SMTP_HOST
  valueFrom:
    secretKeyRef:
      name: {{ .Values.smtp.secretName }}
      key: {{ .Values.smtp.hostKey }}
- name: SMTP_PORT
  value: {{ .Values.smtp.port | quote }}
- name: SMTP_USERNAME
  valueFrom:
    secretKeyRef:
      name: {{ .Values.smtp.secretName }}
      key: {{ .Values.smtp.usernameKey }}
- name: SMTP_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ .Values.smtp.secretName }}
      key: {{ .Values.smtp.passwordKey }}
{{- end }}
{{- end -}}
