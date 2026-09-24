# AI Control Plane — Architecture Analysis & Design

## Step 1–2: Existing project, as I understand it

Your prototype (from the earlier Streamlit + FastAPI/LiteLLM scripts) is:

- A single-process FastAPI app exposing `/v1/chat/completions`.
- A hard-coded `MODEL_REGISTRY` dict mapping friendly names → LiteLLM model strings.
- LiteLLM used directly to call OpenRouter (cloud) and Ollama (local).
- No persistence — no database, no users, no API keys, no usage tracking.
- No auth beyond a single server-side `OPENROUTER_API_KEY` env var.
- A Streamlit UI that talks to LiteLLM directly (not through the backend).

This is a **single-tenant proxy**, not a platform. It has no concept of "customer," no
stored request history, no cost tracking, and no routing intelligence beyond "the
model name the client asked for."

## Step 3: What to keep

- FastAPI as the web framework — good choice, async, OpenAPI docs for free.
- LiteLLM as the unification layer for calling different providers — keep it, it's
  exactly the right abstraction for "one interface, many backends."
- The idea of a model registry — keep the *concept*, but it needs to move from a
  hard-coded dict to a database table with metadata (cost, latency, reliability).
- OpenRouter + Ollama as the first two provider integrations — keep both, they cover
  cloud + local/private, which is the core positioning.

## Step 4: What to replace

- The hard-coded registry → `models` / `providers` / `provider_models` DB tables.
- The single global API key → per-tenant provider credentials, encrypted at rest,
  never returned to the frontend.
- "No auth" → real auth: password + JWT for humans, hashed API keys for
  applications, both scoped to an organization/project.
- "Whatever model the client names" → an intelligent router that can also accept
  `model: "auto"` and pick based on policy/cost/latency/quality.
- Streamlit calling LiteLLM directly → Streamlit (or any frontend) calls *this
  backend's* OpenAI-compatible endpoint. Provider keys never leave the server.
- In-memory Streamlit session state → PostgreSQL for durable records, Redis for
  rate limiting and hot counters.

## Step 5: Target architecture

```
Client (SDK / curl / Playground UI)
   │  Authorization: Bearer <tenant API key>
   ▼
FastAPI Gateway
   │
   ├─ API-key auth middleware  (hash lookup → org/project/permissions)
   ├─ Rate limiter             (Redis: req/min, tokens/min, budget checks)
   ├─ Policy engine            (allowed models/providers, privacy rules)
   ├─ Router                   (rule-based scoring: cost/latency/quality/reliability)
   ├─ Provider adapters        (LiteLLM → OpenRouter, Ollama, ...)
   ├─ Usage + cost recorder    (writes to `requests` table, updates budgets)
   └─ Response (OpenAI-compatible, streamed or not)

Async / on write:
   requests table → background aggregation → dashboard analytics, alerts
```

Everything after "Provider adapters" happens whether the call succeeds or fails, so
cost/latency/error data is captured even on failure — that's what the router and the
optimization advisor (Phase 2) will eventually learn from.

## Step 6: Database schema (Phase 1 subset)

See `backend/app/models/` for the SQLAlchemy source of truth. Summary:

| Table | Purpose |
|---|---|
| `organizations` | Tenant root |
| `users` | Human accounts, hashed passwords |
| `memberships` | user ↔ org, with `role` (owner/admin/developer/analyst/billing/viewer) |
| `projects` | Sub-tenant grouping under an org (their own keys/budgets) |
| `api_keys` | Hashed application keys, scoped to a project, with limits |
| `providers` | Cloud/private provider configs (OpenRouter, Ollama, ...), credentials encrypted |
| `models` | Registry: model id, provider, cost/latency/quality metadata |
| `routing_policies` | Per-project weights/rules for the router |
| `budgets` | Spend caps at org/project/key level, with period + action-on-exceed |
| `requests` | One row per API call: routing decision, tokens, cost, latency, status |
| `feedback` | 👍/👎/rating tied to a request |

Full column-level detail is in the SQLAlchemy models — that's the schema, kept in
one place instead of duplicated in prose.

## Step 7: API surface (Phase 1)

```
POST   /v1/auth/signup
POST   /v1/auth/login
POST   /v1/organizations
POST   /v1/organizations/{org_id}/projects
POST   /v1/projects/{project_id}/api-keys
GET    /v1/projects/{project_id}/api-keys
DELETE /v1/api-keys/{key_id}

GET    /v1/models                       # registry, filtered to what's usable
POST   /v1/chat/completions             # OpenAI-compatible, the core endpoint
GET    /v1/requests                     # usage/history, filterable
GET    /v1/requests/{request_id}        # single request trace
POST   /v1/requests/{request_id}/feedback

GET    /v1/projects/{project_id}/usage  # cost/latency/model-distribution summary
GET    /health
```

Auth: `/v1/auth/*` and management endpoints use JWT (human session). The chat
completions endpoint and usage endpoints accept a project API key
(`Authorization: Bearer sk-live-...`) — that's what a customer's application uses.

## Step 8: MVP roadmap (what I'm building now vs. next)

**Building now (Phase 1, real and runnable):**
auth, orgs, projects, API keys, model registry (DB-backed, seeded with OpenRouter +
Ollama entries), a rule-based router with `auto`/`cost`/`speed`/`quality` modes,
fallback on provider failure, per-request cost + latency logging, Redis rate
limiting, budget checks, a request-trace endpoint, and OpenAPI docs.

**Explicitly deferred (Phase 2/3, not built here):** semantic caching, PII
detection, the Next.js dashboard, Stripe billing, private-deployment tunneling,
the routing copilot, and autonomous optimization. Building those before Phase 1
is stable would be exactly the "fake demo" you told me to avoid — they need real
usage data to be honest about, and this MVP is what generates that data.

I did not build a full Next.js frontend in this pass — that's a multi-day project
on its own. Phase 1 ships a working API + OpenAPI docs + a minimal HTML playground
so you can exercise the whole flow today; the dashboard is next.
