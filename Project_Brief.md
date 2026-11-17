# Project Brief: StockSense — AI-assisted inventory system on Google Cloud

## 1. About me and the goal of this project
- I'm a software developer (~3 years, full-stack/backend): Python (FastAPI), Node.js, Next.js/React, Docker, PostgreSQL.
- I've finished Google Cloud learning courses: Cloud Fundamentals: Core Infrastructure, Essential Infrastructure: Foundation, Essential Infrastructure: Core Services, and Getting Started with GKE. I've also learned basic kubectl and CI/CD with GitHub Actions.
- I'm NOT doing a certification. The goal of this project is:
  1. Practice the Google Cloud services I learned, hands-on (especially IAM and networking)
  2. Build a portfolio project I can explain in job interviews
  3. Practice Python testing (pytest) at a basic level
  4. Bridge toward my next learning path (agentic AI on Google Cloud)
- The app can be SMALL. The main purpose is to show a practical, well-designed Google Cloud setup.

## 2. What the app does (use case)
Small shops receive supplier invoices (PDF or photo) and type items into their stock list by hand. StockSense automates this:
1. The shop owner adds products with a low-stock limit
2. Sales reduce stock
3. When stock falls below the limit, the owner gets an email alert
4. The owner uploads a supplier invoice; AI (Gemini) reads it and stock is increased automatically
5. Items the AI can't match to a product are marked "needs review"

Example user: Nimal, owner of a small grocery shop in Colombo (single user, no complex roles). He uses the FastAPI /docs page or Postman (a small web UI is optional later).

### User flow
1. Add products: Rice 5kg (RICE-5, stock 20, alert below 5), Sugar 1kg, Dhal 500g
2. Record a sale: POST /stock/out {sku: RICE-5, qty: 16} → Rice 20 → 4
3. 4 < 5 → API publishes a "LowStock" event → Cloud Run function → email "Rice 5kg is low: 4 left"
4. Supplier invoice arrives (Rice ×20, Sugar ×25, Coconut oil ×10). Nimal requests a signed upload URL and uploads the file directly to Cloud Storage
5. Upload triggers an event → worker → Gemini extracts items → worker matches them to products → Rice 4 → 24, Sugar 30 → 55; Coconut oil → "needs review"
6. Nimal checks GET /invoices/{id} → status "processed", matched items, and items needing review

### MVP endpoints (api-service)
- POST /products, GET /products
- POST /stock/out (record a sale)
- POST /invoices/upload-url (returns a signed URL)
- GET /invoices, GET /invoices/{id}
- GET /health
Simple authentication for MVP: an API key header (stored in Secret Manager).

### Draft data model (Postgres)
- products (id, sku, name, qty, low_stock_threshold, created_at)
- stock_movements (id, product_id, change, reason: sale | invoice | adjustment, invoice_id nullable, created_at)
- invoices (id, gcs_path, status: uploaded | processing | processed | failed, created_at, processed_at)
- invoice_items (id, invoice_id, raw_name, qty, matched_product_id nullable, status: matched | needs_review)

## 3. Architecture
- api-service (Cloud Run, FastAPI): handles user requests; talks to Cloud SQL (private IP) and Cloud Storage (signed URLs); publishes "LowStock" to Pub/Sub
- Cloud Storage "invoices" bucket: new file → Pub/Sub notification
- worker-service (Cloud Run, FastAPI): receives Pub/Sub push messages; downloads the invoice; calls Gemini (Vertex AI) to extract items; updates stock in Cloud SQL; publishes "LowStock" if needed
- notifier (Cloud Run function): subscribed to "LowStock"; sends the email
- bastion VM (e2-micro, no external IP): admin access to the private Cloud SQL with psql; SSH only through IAP; Cloud NAT for updates
- Everywhere: dedicated service accounts, Secret Manager, labels, Cloud Monitoring/Logging/Trace
- Pipeline: GitHub Actions (Workload Identity Federation) → Artifact Registry → Cloud Run
- Infrastructure: Terraform (basic)

Design decisions:
- NOT full microservices: two services split by workload type (fast user requests vs slow background processing). The API is a modular monolith (routers per feature).
- Both services share one Cloud SQL database on purpose, for simplicity and cost.
- Cloud Run instead of Kubernetes (scale to zero, less to manage). GKE is an optional stretch.

## 4. Google Cloud setup and services

### Projects and accounts
- Two projects: stocksense-dev-<suffix> and stocksense-prod-<suffix>
- No organization (personal Gmail accounts), so everything is at project level
- Two Google accounts to practice IAM:
  - Admin account: Billing Account Administrator, Owner of both projects
  - Developer account: specific roles in dev (e.g. Cloud Run Developer, Cloud SQL Client/Admin for dev, Logs Viewer, Service Account User on dev service accounts); Viewer + Logs Viewer only in prod
  - Test permissions by trying forbidden actions from the developer account
- Region: asia-south1 (Mumbai) for most resources; check Gemini/Vertex AI region availability

### Services and what each practices
- Cloud Run: api-service and worker-service
- Cloud Run functions: low-stock email notifier
- Cloud SQL for PostgreSQL: smallest tier, private IP
- Cloud Storage: invoices bucket, signed URL uploads, lifecycle rule (move old invoices to Nearline/Coldline), Soft Delete
- Pub/Sub: topics "invoice-uploaded" (Cloud Storage notification) and "low-stock"; push subscription to worker (authenticated with a service account)
- Vertex AI (Gemini): invoice extraction, authenticated via the worker's service account (no API keys)
- Secret Manager: DB password, app API key, email provider key
- Artifact Registry: Docker images
- VPC (custom mode): subnet in asia-south1, Cloud SQL private IP, Cloud Run Direct VPC egress, firewall rules, Cloud NAT, Private Google Access
- Compute Engine: bastion VM (e2-micro), no external IP, IAP TCP forwarding for SSH, OS Login, Ops Agent installed, custom service account
- IAM:
  - one service account per component (api, worker, notifier, bastion, CI/CD) with minimal roles; no key files
  - grant roles on specific resources where possible (e.g. one secret, one bucket)
  - one custom role (e.g. read-only stock operator)
  - one deny policy (e.g. block deleting the prod Cloud SQL instance)
- Cloud Monitoring: uptime check on /health, alert policy (errors/latency), dashboard
- Cloud Logging: structured JSON logs, log-based metric, log sink to Cloud Storage
- Error Reporting and Cloud Trace (OpenTelemetry in FastAPI)
- Billing: budget + alerts per project and overall; billing export to BigQuery with a sample cost query
- Labels on all resources: app=stocksense, env=dev|prod, component=api|worker|notifier|bastion

### Optional stretch (costs money; try then delete)
- External Application Load Balancer + Cloud DNS custom domain + Cloud CDN in front of Cloud Run
- Run the worker on GKE Autopilot for a few days to practice kubectl
- Memorystore to cache the product list

### Deliberately skipped (explain in README)
- Spanner, Bigtable, AlloyDB (overkill and expensive for this scale)
- Filestore (no shared file system needed)
- Organization policies and folders (require an organization/domain)

## 5. Application tech stack
- Python 3.12, FastAPI, Uvicorn
- SQLAlchemy 2.0 + Alembic (migrations)
- Pydantic v2 + pydantic-settings (config from environment variables)
- Cloud SQL connection via the Cloud SQL Python Connector or private IP
- google-cloud-storage, google-cloud-pubsub, Vertex AI / Gemini SDK, httpx
- pytest + FastAPI TestClient; mocks for Gemini and Cloud Storage
- ruff (lint/format), pre-commit, Makefile
- Docker: one multi-stage Dockerfile per service; docker-compose for local dev (Postgres + api + worker)
- OpenTelemetry for tracing

### Repository structure
stocksense/
  services/api/      (app/: main.py, routers/, models.py, schemas.py, db.py, config.py; tests/; alembic/; Dockerfile; requirements.txt)
  services/worker/   (app/, tests/, Dockerfile, requirements.txt)
  functions/notifier/
  terraform/
  .github/workflows/
  docker-compose.yml
  .env.example
  Makefile
  README.md

### Development practices to cover
Must-have:
- settings from environment variables (same code locally, in Docker, on Cloud Run)
- Alembic migrations
- Pydantic validation for input/output
- /health endpoint
- structured JSON logging
- clear error handling (400/404/409)
- API key authentication
- .env.example; no secrets in Git
Worker-specific (good interview topics):
- idempotency: Pub/Sub may deliver the same message more than once; never process an invoice twice
- timeouts and retries for Gemini calls
- validate Gemini output with Pydantic; never trust AI output blindly
Nice-to-have:
- pagination on list endpoints, ruff + pre-commit, Makefile commands

### Testing plan (basic level, I'm still learning)
1. Unit tests: small functions (e.g. is_low_stock)
2. API tests with TestClient (e.g. create product → 201 → list contains it)
3. Tests with mocks: fake Gemini/Cloud Storage responses (e.g. 3 extracted items → stock updated correctly)
- Tests use a separate test Postgres (Docker), never real data
- Tests run in CI; failing tests block deployment
- Goal: a few good tests per feature, not 100% coverage

## 6. CI/CD (GitHub Actions)
- Authenticate to Google Cloud with Workload Identity Federation (no service account key files)
- On pull request: ruff + pytest
- On merge to main: test → build images → push to Artifact Registry → deploy to dev
- Deploy to prod: manual approval or a release tag
- Dedicated CI/CD service account with minimal roles

## 7. Terraform (basic)
I'm learning Terraform basics. Use it for a small, clear part of the infrastructure:
service accounts and IAM bindings, buckets, Pub/Sub topics/subscriptions, Artifact Registry, and Cloud Run services. Keep it simple.

## 8. Build phases
1. Core API: FastAPI + Postgres locally (Docker Compose), products and stock endpoints, first tests. Then GCP setup (projects, accounts, VPC, Cloud SQL private IP) and deploy to Cloud Run. Done when: live URL works from Postman.
2. CI/CD: GitHub Actions with WIF, dev → prod. Done when: a push deploys automatically.
3. Files + events: signed URL upload, bucket → Pub/Sub → worker. Done when: an upload triggers the worker.
4. AI extraction: Gemini reads invoices and updates stock, with idempotency. Done when: upload a PDF → stock changes.
5. Alerts + observability: low-stock email, uptime check, alerts, dashboard, logs, trace, bastion VM with IAP. Done when: I get a low-stock email and can see everything in monitoring.
6. Terraform + README: infrastructure as code, architecture diagram, design decisions, costs. Done when: someone can understand the project in 5 minutes.

## 9. Cost guardrails
- Budget alerts on both projects before creating anything
- Cloud SQL is the main always-on cost: smallest tier, stop it when not working
- Delete optional stretch resources (load balancer, GKE) after trying them
- Use free tier and new-account credits where possible

## 10. How I want you to help
- Go one phase at a time, and wait for my confirmation before moving on
- Explain WHY for each step, in simple terms, connecting it to the Google Cloud concepts I learned
- For every command (gcloud, kubectl, docker, terraform), explain what it does and its important flags
- Point out security best practices and common mistakes
- Keep code clean but simple; I'm practicing, not building production software
- Let's start with Phase 1: the local FastAPI + Postgres setup with Docker Compose, the database models, and the first endpoints and tests.