#!/usr/bin/env bash
# Deploy Provenance to Cloud Run (agent + API + console), optionally fronted by Firebase Hosting.
#
#   MODE=offline ./deploy/deploy.sh   # scripted models + demo bundle: public URL with zero model spend
#   MODE=gemini  ./deploy/deploy.sh   # real Gemini + demo bundle, cases in Firestore
#                                     #   Gemini backend follows .env: GOOGLE_GENAI_USE_VERTEXAI=TRUE -> Vertex;
#                                     #   otherwise the AI Studio GOOGLE_API_KEY, stored in Secret Manager
#   MODE=gemini DATA=gcp ./deploy/deploy.sh   # BigQuery / GCS / Firestore
#   SWEEP=1 ...                               # also schedule the nightly staleness sweep
#   EVAL=local ...                            # gemini mode reads /eval from BigQuery by default; this turns it off
#
# Needs: gcloud auth, GOOGLE_CLOUD_PROJECT, and for gemini PROVENANCE_MODEL_FLASH / _PRO (pinned IDs).
# REGION is where Cloud Run runs; MODEL_LOCATION is where Vertex serves the pinned models. Full guide: docs/RUNNING_ON_GEMINI.md
set -euo pipefail

PROJECT="${GOOGLE_CLOUD_PROJECT:?set GOOGLE_CLOUD_PROJECT}"
REGION="${REGION:-us-central1}"                      # Cloud Run region
MODEL_LOCATION="${MODEL_LOCATION:-${GOOGLE_CLOUD_LOCATION:-global}}"  # Vertex model endpoint location (often "global" for newer models)
SERVICE="${SERVICE:-provenance}"
MODE="${MODE:-offline}"
DATA="${DATA:-bundle}"
SA="provenance-run@${PROJECT}.iam.gserviceaccount.com"

gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  aiplatform.googleapis.com firestore.googleapis.com bigquery.googleapis.com storage.googleapis.com \
  --project "$PROJECT"

# One service account is the Cloud Run identity (production adds field-level authz).
if ! gcloud iam service-accounts describe "$SA" --project "$PROJECT" >/dev/null 2>&1; then
  gcloud iam service-accounts create provenance-run --project "$PROJECT" --display-name "Provenance Cloud Run"
fi
for role in roles/aiplatform.user roles/datastore.user roles/bigquery.jobUser roles/bigquery.dataViewer roles/storage.objectViewer; do
  gcloud projects add-iam-policy-binding "$PROJECT" --member "serviceAccount:$SA" --role "$role" --condition None >/dev/null
done

BACKEND=vertex
[[ "${GOOGLE_GENAI_USE_VERTEXAI:-TRUE}" =~ ^(TRUE|true|1)$ ]] || BACKEND=aistudio
VERTEX_FLAG=TRUE; [[ "$BACKEND" == "aistudio" ]] && VERTEX_FLAG=FALSE
ENV="PROVENANCE_MODE=${MODE},PROVENANCE_DATA=${DATA},GOOGLE_CLOUD_PROJECT=${PROJECT},GOOGLE_CLOUD_LOCATION=${MODEL_LOCATION},GOOGLE_GENAI_USE_VERTEXAI=${VERTEX_FLAG}"
SECRETS=()
SCALE=(--max-instances 1)  # the in-memory case store needs a single instance
if [[ "$MODE" == "gemini" || "$DATA" == "gcp" ]]; then
  ENV="${ENV},PROVENANCE_STORE=firestore,PROVENANCE_MODEL_FLASH=${PROVENANCE_MODEL_FLASH:?pin a model},PROVENANCE_MODEL_PRO=${PROVENANCE_MODEL_PRO:?pin a model}"
  SCALE=(--max-instances 5)
  if [[ "$BACKEND" == "aistudio" ]]; then
    # The AI Studio key never goes into a plain env var on the service: it lives in Secret Manager.
    : "${GOOGLE_API_KEY:?set GOOGLE_API_KEY in .env (AI Studio key) or GOOGLE_GENAI_USE_VERTEXAI=TRUE}"
    gcloud services enable secretmanager.googleapis.com --project "$PROJECT"
    if gcloud secrets describe provenance-gemini-key --project "$PROJECT" >/dev/null 2>&1; then
      printf '%s' "$GOOGLE_API_KEY" | gcloud secrets versions add provenance-gemini-key --data-file=- --project "$PROJECT" >/dev/null
    else
      printf '%s' "$GOOGLE_API_KEY" | gcloud secrets create provenance-gemini-key --data-file=- --project "$PROJECT" >/dev/null
    fi
    gcloud secrets add-iam-policy-binding provenance-gemini-key --project "$PROJECT" \
      --member "serviceAccount:$SA" --role roles/secretmanager.secretAccessor >/dev/null
    SECRETS=(--set-secrets "GOOGLE_API_KEY=provenance-gemini-key:latest")
  fi
  # Cases live in Firestore once the service can scale out; create the default database once.
  if ! gcloud firestore databases describe --database="(default)" --project "$PROJECT" >/dev/null 2>&1; then
    gcloud firestore databases create --database="(default)" --location="${FIRESTORE_LOCATION:-nam5}" \
      --type=firestore-native --project "$PROJECT"
  fi
fi
# The eval page reads BigQuery eval_results in gemini mode even when the cases come from the demo bundle.
EVAL="${EVAL:-$([[ "$MODE" == "gemini" ]] && echo bigquery || echo local)}"
if [[ "$EVAL" == "bigquery" && "$DATA" != "gcp" ]]; then
  ENV="${ENV},PROVENANCE_EVAL=bigquery,PROVENANCE_BQ_DATASET=${PROVENANCE_BQ_DATASET:-provenance}"
fi
if [[ "$DATA" == "gcp" ]]; then
  ENV="${ENV},PROVENANCE_BQ_DATASET=${PROVENANCE_BQ_DATASET:-provenance},PROVENANCE_GCS_BUCKET=${PROVENANCE_GCS_BUCKET:?},PROVENANCE_OFAC_ARCHIVED_URI=${PROVENANCE_OFAC_ARCHIVED_URI:?},PROVENANCE_OFAC_LIVE_URI=${PROVENANCE_OFAC_LIVE_URI:?}"
fi

# --no-cpu-throttling: cases run in the background after POST returns.
# --timeout 900: agent turns are long. min-instances stays 0 except for recording and judging (MIN=1).
gcloud run deploy "$SERVICE" --source . --project "$PROJECT" --region "$REGION" \
  --service-account "$SA" --allow-unauthenticated --no-cpu-throttling --timeout 900 \
  --memory 1Gi --min-instances "${MIN:-0}" "${SCALE[@]}" --set-env-vars "$ENV" ${SECRETS[@]+"${SECRETS[@]}"}

URL=$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" --format 'value(status.url)')
echo "Cloud Run: $URL  (mode=$MODE, gemini backend=$BACKEND)"
curl -fsS "$URL/api/health" && echo
# Nightly staleness sweep (opt-in): Cloud Scheduler -> Pub/Sub -> push to /trigger/sweep with an OIDC token.
if [[ "${SWEEP:-0}" == "1" ]]; then
  gcloud services enable cloudscheduler.googleapis.com pubsub.googleapis.com --project "$PROJECT"
  gcloud run services add-iam-policy-binding "$SERVICE" --project "$PROJECT" --region "$REGION" \
    --member "serviceAccount:$SA" --role roles/run.invoker >/dev/null
  gcloud pubsub topics describe provenance-sweep --project "$PROJECT" >/dev/null 2>&1 || \
    gcloud pubsub topics create provenance-sweep --project "$PROJECT"
  gcloud pubsub subscriptions describe provenance-sweep-push --project "$PROJECT" >/dev/null 2>&1 || \
    gcloud pubsub subscriptions create provenance-sweep-push --project "$PROJECT" --topic provenance-sweep \
      --push-endpoint "$URL/trigger/sweep" --push-auth-service-account "$SA" --ack-deadline 600
  gcloud scheduler jobs describe provenance-nightly-sweep --project "$PROJECT" --location "$REGION" >/dev/null 2>&1 || \
    gcloud scheduler jobs create pubsub provenance-nightly-sweep --project "$PROJECT" --location "$REGION" \
      --schedule "17 2 * * *" --time-zone "Asia/Kolkata" --topic provenance-sweep --message-body '{"source":"scheduler"}'
  echo "Sweep: nightly 02:17 IST via Cloud Scheduler -> Pub/Sub -> $URL/trigger/sweep"
fi

echo "Firebase Hosting (optional): firebase use $PROJECT && firebase deploy --only hosting"
