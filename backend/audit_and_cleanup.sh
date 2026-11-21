#!/usr/bin/env bash
# Audit all GCP resources tagged app=nordic-atlas or cleanly tear down the stack.
set -euo pipefail

ACTION="${1:-audit}"
PROJECT_ID="${GCP_PROJECT_ID:?Set GCP_PROJECT_ID}"
REGION="${GCP_REGION:-us-west1}"
SERVICE_NAME="${CLOUD_RUN_SERVICE:-nordic-atlas-agents}"
SA_NAME="${CLOUD_RUN_SA_NAME:-nordic-atlas-runner}"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

case "${ACTION}" in
  audit)
    echo "================================================================"
    echo "Nordic Atlas GCP Resource & Audit Inventory (Project: ${PROJECT_ID})"
    echo "================================================================"

    echo ""
    echo "--- 1. Cloud Run Services (label: app=nordic-atlas) ---"
    gcloud run services list \
      --project="${PROJECT_ID}" \
      --filter="metadata.labels.app=nordic-atlas" \
      --format="table(metadata.name,region,status.url,metadata.labels)"

    echo ""
    echo "--- 2. Secret Manager Secrets (label: app=nordic-atlas) ---"
    gcloud secrets list \
      --project="${PROJECT_ID}" \
      --filter="labels.app=nordic-atlas" \
      --format="table(name,createTime,labels)"

    echo ""
    echo "--- 3. Dedicated Least-Privilege Service Account ---"
    gcloud iam service-accounts list \
      --project="${PROJECT_ID}" \
      --filter="email=${SA_EMAIL}" \
      --format="table(email,displayName,disabled)"

    echo ""
    echo "--- 4. Artifact Registry Repositories (label: app=nordic-atlas) ---"
    gcloud artifacts repositories list \
      --project="${PROJECT_ID}" \
      --filter="labels.app=nordic-atlas" \
      --format="table(name,format,location,labels)"

    echo ""
    echo "--- 5. Recent Structured Audit Events (Last 15) ---"
    gcloud logging read 'jsonPayload.app="nordic-atlas"' \
      --project="${PROJECT_ID}" \
      --limit=15 \
      --format="table(timestamp,severity,jsonPayload.event,jsonPayload.email,jsonPayload.adventureId,jsonPayload.commitSha,jsonPayload.elapsedSec)"
    ;;

  destroy)
    echo "WARNING: This will delete the Cloud Run service, both Secret Manager secrets,"
    echo "and the dedicated service account (${SA_EMAIL}) in project ${PROJECT_ID}."
    read -r -p "Type 'DELETE NORDIC ATLAS' to confirm: " confirm
    if [[ "${confirm}" != "DELETE NORDIC ATLAS" ]]; then
      echo "Aborted."
      exit 1
    fi

    echo "==> Deleting Cloud Run service: ${SERVICE_NAME}"
    gcloud run services delete "${SERVICE_NAME}" --region="${REGION}" --project="${PROJECT_ID}" --quiet || true

    for secret_name in "nordic-atlas-gemini-key" "nordic-atlas-github-token" "nordic-atlas-vault-passphrase"; do
      echo "==> Deleting secret: ${secret_name}"
      gcloud secrets delete "${secret_name}" --project="${PROJECT_ID}" --quiet || true
    done

    echo "==> Deleting dedicated service account: ${SA_EMAIL}"
    gcloud iam service-accounts delete "${SA_EMAIL}" --project="${PROJECT_ID}" --quiet || true

    echo "Clean teardown complete."
    ;;

  *)
    echo "Usage: $0 [audit|destroy]"
    exit 1
    ;;
esac
