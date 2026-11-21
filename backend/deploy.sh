#!/usr/bin/env bash
# Deploy Nordic Atlas multi-agent backend to Google Cloud Run (scales to 0 when idle).
# Covered by Google AI Ultra monthly Google Cloud / Developer Program credits!
set -euo pipefail

PROJECT_ID="${GCP_PROJECT_ID:?Set GCP_PROJECT_ID (your Cloud project linked to AI Ultra credits)}"
REGION="${GCP_REGION:-us-west1}"
SERVICE_NAME="${CLOUD_RUN_SERVICE:-nordic-atlas-agents}"
GOOGLE_CLIENT_ID="${GOOGLE_CLIENT_ID:?Set GOOGLE_CLIENT_ID (Web OAuth Client ID from Google Cloud Console)}"
GEMINI_API_KEY="${GEMINI_API_KEY:?Set GEMINI_API_KEY (from Google AI Studio linked to your AI Ultra credits)}"
GITHUB_TOKEN="${GITHUB_TOKEN:?Set GITHUB_TOKEN (fine-grained PAT with Contents Read/Write on gfinley/adventure-advisor)}"
ALLOWED_EMAILS="${ALLOWED_EMAILS:-matthewgfinley@gmail.com}"
GEMINI_RESEARCH_MODEL="${GEMINI_RESEARCH_MODEL:-gemini-3.8-flash}"
GEMINI_SYNTH_MODEL="${GEMINI_SYNTH_MODEL:-gemini-3.8-flash}"

echo "==> Enabling required Google Cloud APIs in project: ${PROJECT_ID}"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com secretmanager.googleapis.com \
  --project="${PROJECT_ID}"

ensure_secret() {
  local name="$1"
  local value="$2"
  if ! gcloud secrets describe "${name}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
    gcloud secrets create "${name}" --replication-policy="automatic" --project="${PROJECT_ID}"
  fi
  printf "%s" "${value}" | gcloud secrets versions add "${name}" --data-file=- --project="${PROJECT_ID}" >/dev/null
}

echo "==> Storing GEMINI_API_KEY and GITHUB_TOKEN in Google Secret Manager"
ensure_secret "nordic-atlas-gemini-key" "${GEMINI_API_KEY}"
ensure_secret "nordic-atlas-github-token" "${GITHUB_TOKEN}"

PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')"
RUNTIME_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

for secret_name in "nordic-atlas-gemini-key" "nordic-atlas-github-token"; do
  gcloud secrets add-iam-policy-binding "${secret_name}" \
    --project="${PROJECT_ID}" \
    --member="serviceAccount:${RUNTIME_SA}" \
    --role="roles/secretmanager.secretAccessor" >/dev/null
done

echo "==> Deploying ${SERVICE_NAME} to Cloud Run (${REGION})..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

gcloud run deploy "${SERVICE_NAME}" \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --source="${SCRIPT_DIR}" \
  --allow-unauthenticated \
  --min-instances=0 \
  --max-instances=2 \
  --timeout=180 \
  --memory=512Mi \
  --set-env-vars="GOOGLE_CLIENT_ID=${GOOGLE_CLIENT_ID},ALLOWED_EMAILS=${ALLOWED_EMAILS},GITHUB_REPO=gfinley/adventure-advisor,GITHUB_BRANCH=main,CORS_ORIGINS=https://gfinley.github.io,GEMINI_RESEARCH_MODEL=${GEMINI_RESEARCH_MODEL},GEMINI_SYNTH_MODEL=${GEMINI_SYNTH_MODEL}" \
  --set-secrets="GEMINI_API_KEY=nordic-atlas-gemini-key:latest,GITHUB_TOKEN=nordic-atlas-github-token:latest"

SERVICE_URL="$(gcloud run services describe "${SERVICE_NAME}" --project="${PROJECT_ID}" --region="${REGION}" --format='value(status.url)')"
echo ""
echo "=================================================================="
echo "Deployed successfully!"
echo "Cloud Run URL: ${SERVICE_URL}"
echo ""
echo "Next step: Paste BACKEND_URL and GOOGLE_CLIENT_ID into config.js"
echo "(or click 'Connect Backend' inside https://gfinley.github.io/adventure-advisor/)"
echo "=================================================================="
