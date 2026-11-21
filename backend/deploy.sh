#!/usr/bin/env bash
# Deploy Nordic Atlas multi-agent backend to Google Cloud Run with uniform GCP labels
# and a dedicated least-privilege IAM service account for clean auditing & billing tracking.
set -euo pipefail

PROJECT_ID="${GCP_PROJECT_ID:?Set GCP_PROJECT_ID (your Cloud project linked to AI Ultra credits)}"
REGION="${GCP_REGION:-us-west1}"
SERVICE_NAME="${CLOUD_RUN_SERVICE:-nordic-atlas-agents}"
SA_NAME="${CLOUD_RUN_SA_NAME:-nordic-atlas-runner}"
APP_ENV="${APP_ENV:-prod}"

GOOGLE_CLIENT_ID="${GOOGLE_CLIENT_ID:?Set GOOGLE_CLIENT_ID (Web OAuth Client ID from Google Cloud Console)}"
GEMINI_API_KEY="${GEMINI_API_KEY:?Set GEMINI_API_KEY (from Google AI Studio linked to your AI Ultra credits)}"
GITHUB_TOKEN="${GITHUB_TOKEN:?Set GITHUB_TOKEN (fine-grained PAT with Contents Read/Write on gfinley/adventure-advisor)}"
ALLOWED_EMAILS="${ALLOWED_EMAILS:-matthewgfinley@gmail.com}"
GEMINI_RESEARCH_MODEL="${GEMINI_RESEARCH_MODEL:-gemini-3.8-flash}"
GEMINI_SYNTH_MODEL="${GEMINI_SYNTH_MODEL:-gemini-3.8-flash}"

# Uniform GCP label taxonomy applied to Cloud Run, Secret Manager, and Artifact Registry
# (Propagates into Cloud Billing cost breakdowns & Cloud Asset Inventory)
GCP_LABELS="app=nordic-atlas,component=adventure-advisor-agents,env=${APP_ENV},owner=gfinley,cost-center=personal-travel-ai,managed-by=deploy-sh,repo=adventure-advisor"

echo "==> [1/5] Enabling required Google Cloud APIs in project: ${PROJECT_ID}"
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  logging.googleapis.com \
  --project="${PROJECT_ID}"

echo "==> [2/5] Ensuring dedicated least-privilege Service Account: ${SA_NAME}"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
if ! gcloud iam service-accounts describe "${SA_EMAIL}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud iam service-accounts create "${SA_NAME}" \
    --project="${PROJECT_ID}" \
    --display-name="Nordic Atlas Cloud Run Agent Runner" \
    --description="Dedicated least-privilege runtime SA for nordic-atlas-agents (secretAccessor on 2 secrets only)"
fi

ensure_secret() {
  local name="$1"
  local value="$2"
  local purpose="$3"
  if ! gcloud secrets describe "${name}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
    gcloud secrets create "${name}" \
      --replication-policy="automatic" \
      --labels="${GCP_LABELS},secret-purpose=${purpose}" \
      --project="${PROJECT_ID}"
  else
    gcloud secrets update "${name}" \
      --update-labels="${GCP_LABELS},secret-purpose=${purpose}" \
      --project="${PROJECT_ID}" >/dev/null
  fi
  printf "%s" "${value}" | gcloud secrets versions add "${name}" --data-file=- --project="${PROJECT_ID}" >/dev/null
}

echo "==> [3/5] Storing & labeling secrets in Google Secret Manager"
ensure_secret "nordic-atlas-gemini-key" "${GEMINI_API_KEY}" "gemini-api"
ensure_secret "nordic-atlas-github-token" "${GITHUB_TOKEN}" "github-repo-sync"

# Bind least-privilege access ONLY to these exact 2 secrets (not project-wide)
for secret_name in "nordic-atlas-gemini-key" "nordic-atlas-github-token"; do
  gcloud secrets add-iam-policy-binding "${secret_name}" \
    --project="${PROJECT_ID}" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="roles/secretmanager.secretAccessor" >/dev/null
done

echo "==> [4/5] Deploying labeled Cloud Run service (${SERVICE_NAME}) in ${REGION}..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

gcloud run deploy "${SERVICE_NAME}" \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --source="${SCRIPT_DIR}" \
  --service-account="${SA_EMAIL}" \
  --labels="${GCP_LABELS}" \
  --allow-unauthenticated \
  --min-instances=0 \
  --max-instances=2 \
  --timeout=180 \
  --memory=512Mi \
  --set-env-vars="APP_ENV=${APP_ENV},GOOGLE_CLIENT_ID=${GOOGLE_CLIENT_ID},ALLOWED_EMAILS=${ALLOWED_EMAILS},GITHUB_REPO=gfinley/adventure-advisor,GITHUB_BRANCH=main,CORS_ORIGINS=https://gfinley.github.io,GEMINI_RESEARCH_MODEL=${GEMINI_RESEARCH_MODEL},GEMINI_SYNTH_MODEL=${GEMINI_SYNTH_MODEL}" \
  --set-secrets="GEMINI_API_KEY=nordic-atlas-gemini-key:latest,GITHUB_TOKEN=nordic-atlas-github-token:latest"

echo "==> [5/5] Tagging Cloud Run Artifact Registry repository (best-effort)"
if gcloud artifacts repositories describe "cloud-run-source-deploy" --location="${REGION}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud artifacts repositories update "cloud-run-source-deploy" \
    --location="${REGION}" \
    --project="${PROJECT_ID}" \
    --update-labels="${GCP_LABELS}" >/dev/null || true
fi

SERVICE_URL="$(gcloud run services describe "${SERVICE_NAME}" --project="${PROJECT_ID}" --region="${REGION}" --format='value(status.url)')"
echo ""
echo "=================================================================="
echo "Deployed & tagged cleanly in GCP!"
echo "  Project:         ${PROJECT_ID}"
echo "  Cloud Run URL:   ${SERVICE_URL}"
echo "  Runtime SA:      ${SA_EMAIL}"
echo "  Applied Labels:  ${GCP_LABELS}"
echo ""
echo "Audit anytime:     ./audit_and_cleanup.sh audit"
echo "Cloud Logging:     jsonPayload.app=\"nordic-atlas\""
echo "=================================================================="
