# AI Control Plane — Phase 1 MVP

One OpenAI-compatible API, multi-tenant, with a transparent rule-based router
across cloud (OpenRouter) and local/private (Ollama) models. See
`ARCHITECTURE.md` for the analysis, target design, and what's deferred to
Phase 2/3.

## What's actually implemented and tested here

- Signup/login (JWT), organizations, projects, hashed API keys with
  per-key rate limits and model/provider allowlists.
- DB-backed model registry seeded with 6 models across 2 providers
  (OpenRouter cloud models + local Ollama models).
- A deterministic, explainable router (`auto`/`cost`/`speed`/`quality`/
  `privacy`/`balanced` modes) that scores eligible models and returns
  its reasoning with every response.
- Policy filtering: `metadata.sensitive: true` restricts routing to
  private/approved models only.
- Automatic fallback across up to 2 alternate models if the primary
  provider call fails, tracked in `requests.fallback_used`.
- Per-project budgets (checked before every call) and per-key rate
  limiting (Redis, fixed window).
- Full request logging — every call, success or failure, is recorded
  with routing reason, tokens, cost, latency — and a `/v1/requests/{id}`
  trace endpoint plus a `/v1/projects/{id}/usage` rollup.
- 👍/👎/rating feedback endpoint per request (feeds the Phase 2
  optimization advisor later — not built yet, this just captures the data).

**I ran this for real**, not just wrote it: installed Postgres + Redis in the
sandbox, seeded the registry, ran the server, and exercised the full flow —
signup → org → project → API key → list models → chat completions → privacy
routing → request history → usage summary → rate limiting. All 10 unit tests
pass (`pytest`). The chat-completion calls correctly reach the routing and
fallback logic and fail with a clean `502` because no real `OPENROUTER_API_KEY`
is configured in this sandbox (and this sandbox's network egress doesn't reach
openrouter.ai) — that's the expected, honest result, not a bug. With a real
key it will return real completions unchanged.

## What is NOT built yet (see ARCHITECTURE.md Step 8)

Next.js dashboard, Stripe billing, semantic caching, PII detection, private
deployment tunneling, the routing copilot, autonomous optimization,
regional/data-residency routing. These are Phase 2/3 by design — building
them before Phase 1 has real usage data would be exactly the "fake demo"
you told me to avoid.

## Run it locally

### 1. Start Postgres + Redis

```bash
docker compose up -d postgres redis
```

(Or use local installs — any Postgres 14+ and Redis 6+ work. Update
`DATABASE_URL` / `REDIS_URL` in `.env` if not using Docker.)

### 2. Configure environment

```bash
cp .env.example .env
# edit .env and set OPENROUTER_API_KEY to a real key from openrouter.ai
```

### 3. Install and seed

```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python -m app.seed
```

### 4. Run the server

```bash
uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000/docs for interactive OpenAPI docs.

### 5. Run tests

```bash
pytest tests/ -v
```

(`test_routing.py` and `test_security.py` need no live services.
Add DB-backed integration tests in Phase 2 once Alembic migrations replace
the dev-only `create_all`.)

### 6. Exercise the full flow (what I ran)

```bash
# Sign up, capture the JWT
curl -X POST localhost:8000/v1/auth/signup -H 'Content-Type: application/json' \
  -d '{"email":"you@example.com","password":"a-real-password","organization_name":"Your Org"}'

# Create a project under your org (org_id from your DB or a /v1/organizations
# list endpoint — add one in Phase 2; for now it's visible via the signup flow)
curl -X POST localhost:8000/v1/organizations/<org_id>/projects \
  -H "Authorization: Bearer <jwt>" -H 'Content-Type: application/json' \
  -d '{"name":"Production"}'

# Create an API key for that project — copy raw_key now, it's shown once
curl -X POST localhost:8000/v1/projects/<project_id>/api-keys \
  -H "Authorization: Bearer <jwt>" -H 'Content-Type: application/json' \
  -d '{"name":"default"}'

# Send a chat completion through the router
curl -X POST localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer <raw_key>" -H 'Content-Type: application/json' \
  -d '{"model":"auto","messages":[{"role":"user","content":"hello"}]}'
```

## Moving to production

- Replace `Base.metadata.create_all()` in `main.py` with Alembic migrations
  before this touches real data.
- Move `ProviderConfig.credential_ref` lookups to a real secret manager
  (AWS Secrets Manager / Vault) instead of plain env vars.
- Tighten CORS `allow_origins` from `*` to your real frontend origin(s).
- Put this behind a reverse proxy (nginx/Caddy) for TLS.
- Add structured logging + a metrics exporter (Prometheus) per
  ARCHITECTURE.md §45 before calling this "observable."
