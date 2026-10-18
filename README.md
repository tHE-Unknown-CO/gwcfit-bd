# PulseFit Enterprise Backend

FastAPI backend for a multi-tenant gym management SaaS. Each tenant is a gym, and every gym-owned table is scoped by `gym_id`.

## Architecture

```text
app/
  api/              Versioned FastAPI routers
  auth/             JWT and bcrypt helpers
  core/             Settings and security headers
  database/         SQLAlchemy session and metadata
  dependencies/     Auth, tenant, and permission dependencies
  middleware/       Request IDs/logging, body limits, metrics, and rate limiting
  models/           SQLAlchemy ORM models
  permissions/      RBAC permission matrix
  repositories/     Tenant-aware data access
  schemas/          Pydantic request/response models
  services/         Business logic
  tests/            Unit tests
```

## Local API Run

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
alembic upgrade head
uvicorn app.main:app --reload
```

Open `http://localhost:8000/docs`.

Liveness is available at `GET /health`. `GET /ready` verifies database connectivity and returns `503` when the API cannot serve database-backed traffic.

## Docker Run

```bash
copy backend\.env.example backend\.env
docker compose up --build
```

The API is available at `http://localhost:8000`, and Nginx proxies it at `http://localhost:8080/api/v1`.

## Tenant Isolation Pattern

Tenant-scoped routes never accept `gym_id` from the client. They derive it from the authenticated JWT user via `get_current_gym_id`, then use `TenantRepository`, which adds `WHERE gym_id = current_user.gym_id` to reads and writes.

Super admins are intentionally blocked from tenant CRUD endpoints unless a platform-level route is created for that use case.

## API Security Contract

- All application routes use `/api/v1`; bearer JWTs validate signature, expiry, issuer, audience, type, and unique token ID.
- API errors include a stable `error.code`, safe message, and `requestId`. The legacy top-level `detail` field remains during the v1 compatibility window.
- JSON request bodies are limited by `MAX_REQUEST_BODY_BYTES`; unsupported body content types return `415`.
- Sensitive auth routes and public inquiry creation use stricter per-IP limits than ordinary routes.
- Private API responses use `Cache-Control: no-store`; security headers and response compression are applied centrally.
- Invitation and account-recovery credentials are stored as one-way hashes, expire, and are invalidated after use.

The in-process limiter protects a single development/API process. Multi-instance production deployments must enforce a shared limit at Redis, the ingress, or an API gateway. See `docs/API_SECURITY_ARCHITECTURE.md` for the audit and rollout details.
