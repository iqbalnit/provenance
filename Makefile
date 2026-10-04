# Local development shortcuts. Run from the repo root (e.g. ~/Project_Provenance).
# Targets that talk to Google Cloud load .env first; .env is gitignored and never exported here.
SHELL := /bin/bash
LOAD_ENV := set -a; [ -f .env ] && . ./.env; set +a;
PORT ?= 8080

help:             ## list targets (default)
	@grep -E '^[a-z-]+:.*## ' Makefile | sed 's/:.*## /\t/'

.PHONY: help setup test dev dev-gemini smoke eval eval-gemini deploy-offline deploy-gemini

setup:            ## install deps; create .env from the example if missing
	uv sync --extra gcp
	@[ -f .env ] || (cp .env.example .env && echo "created .env: fill in project, model location and pinned model IDs")

test:             ## run the test suite (no cloud needed)
	uv run pytest

dev:              ## console on scripted models + demo bundle, http://localhost:$(PORT)
	PROVENANCE_MODE=offline uv run uvicorn provenance.service.app:app --reload --port $(PORT)

dev-gemini:       ## console on real Gemini (needs .env and gcloud application-default login)
	$(LOAD_ENV) PROVENANCE_MODE=gemini uv run uvicorn provenance.service.app:app --reload --port $(PORT)

smoke:            ## 7-check first-run test for Gemini; paste the output back if anything fails
	$(LOAD_ENV) uv run python -m provenance.smoke

eval:             ## all eval arms on scripted models (plumbing check only)
	PROVENANCE_MODE=offline uv run python -m provenance.eval.arms --all --split demo

eval-gemini:      ## all eval arms on Gemini over the demo split
	$(LOAD_ENV) PROVENANCE_MODE=gemini uv run python -m provenance.eval.arms --all --split demo

deploy-offline:   ## public Cloud Run URL with no model spend
	$(LOAD_ENV) MODE=offline ./deploy/deploy.sh

deploy-gemini:    ## Cloud Run on real Gemini, cases in Firestore
	$(LOAD_ENV) MODE=gemini MODEL_LOCATION=$${GOOGLE_CLOUD_LOCATION:-global} ./deploy/deploy.sh
