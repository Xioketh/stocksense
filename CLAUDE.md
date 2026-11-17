# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

Greenfield. The repo currently contains only `Project_Brief.md`, which is the source of truth for scope, architecture, and build phases. Read it before starting work. Update this file (especially **Commands**) as real code, Makefile targets, and configs are added. Do not document commands that don't exist yet.

## Working with the user

- The user is a developer (~3 yrs, Python/FastAPI, Node, Docker, Postgres) **practicing Google Cloud**. The project is a learning and portfolio piece, not production software.
- Work **one build phase at a time** (see Project_Brief.md §8) and wait for the user's confirmation before moving to the next phase.
- Explain *why* for each step and connect it to GCP concepts (IAM, VPC, Cloud Run, Pub/Sub, etc.).
- For every gcloud / docker / terraform / kubectl command, explain what it does and its important flags.
- Call out security best practices and common mistakes. Keep code clean but simple.
- The user also follows the project in a separate Claude chat, so keep explanations self-contained.
- Platform is Windows (PowerShell primary; Git Bash available).

## Planned architecture (big picture)

Two Cloud Run services, split by **workload type** rather than by domain (this is a deliberate design choice, not microservices):

- **services/api**: FastAPI modular monolith (one router per feature: products, stock, invoices, health). Handles user requests, API-key auth (key in Secret Manager), issues signed GCS upload URLs, and publishes `low-stock` events to Pub/Sub.
- **services/worker**: FastAPI app that receives **Pub/Sub push** messages (authenticated with a service account) from the `invoice-uploaded` topic, which is fed by a GCS bucket notification. It downloads the invoice, calls Gemini (Vertex AI, using its service account rather than API keys), matches extracted items to products, updates stock, and publishes `low-stock` if needed.
- **functions/notifier**: Cloud Run function subscribed to `low-stock` that sends the email.
- Both services **share one Cloud SQL Postgres database** (private IP) on purpose, for simplicity and cost.

Invoice flow: `POST /invoices/upload-url` → client uploads directly to GCS → bucket notification → Pub/Sub → worker → Gemini → `invoice_items` (matched / needs_review) plus `stock_movements` → invoice status `processed`.

Data model (Postgres, via SQLAlchemy 2.0 + Alembic): `products`, `stock_movements` (reason: sale | invoice | adjustment; every qty change is recorded here), `invoices` (uploaded | processing | processed | failed), `invoice_items`.

### Worker invariants

- **Idempotency**: Pub/Sub can redeliver messages. An invoice must never be processed twice. Guard this using the invoice status / DB state.
- Gemini calls need timeouts and retries. Validate Gemini output with Pydantic before using it.
- AI items that can't be matched become `needs_review`. They are never auto-created as products.

## Tech conventions

- Python 3.12, FastAPI, SQLAlchemy 2.0, Alembic, Pydantic v2 + pydantic-settings. All config comes from env vars, so the same code runs locally, in Docker, and on Cloud Run. Provide `.env.example`.
- Structured JSON logging. Explicit 400/404/409 errors. OpenTelemetry for Cloud Trace.
- ruff (lint and format), pre-commit, Makefile.
- One multi-stage Dockerfile per service. docker-compose runs Postgres + api + worker for local development.
- Tests: pytest + FastAPI TestClient against a **separate test Postgres in Docker**. Mock Gemini and Cloud Storage. Aim for a few good tests per feature, not full coverage.

## GCP conventions

- Projects: `stocksense-dev-<suffix>`, `stocksense-prod-<suffix>`. Region `asia-south1` (check Vertex AI/Gemini model availability there).
- One service account per component (api, worker, notifier, bastion, CI/CD) with minimal roles, granted on specific resources where possible. **No service account key files.** CI uses Workload Identity Federation.
- Labels on every resource: `app=stocksense`, `env=dev|prod`, `component=api|worker|notifier|bastion`.
- Cloud SQL is private-IP only. Admin access goes through a bastion VM (no external IP, IAP SSH, OS Login).
- Terraform covers a deliberately small scope: service accounts/IAM, buckets, Pub/Sub, Artifact Registry, Cloud Run.
- Cost: set budget alerts before creating resources. Stop Cloud SQL when idle. Delete stretch resources (LB, GKE) after trying them.

## Commands

_None yet. Add build, run, lint, test, and single-test commands here as they are created (e.g. Makefile targets, `docker compose` usage, `pytest path::test_name`)._
