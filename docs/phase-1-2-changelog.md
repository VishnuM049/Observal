# Phase 1 & 2 — Implementation Changelog

**Date:** March 30, 2026
**Status:** Complete — ready for Phase 3

---

## What Was Built

### Phase 1: Foundation

**Server stack (Docker Compose):**
- FastAPI backend on port 8000
- PostgreSQL 16 on port 5432
- ClickHouse on port 8123 (schema stub only — telemetry tables come in Phase 4)
- All services on `observal-net` bridge network

**Auth model:**
- API key only. No passwords, no SSO/SAML (deferred to post-v1).
- Keys generated as `secrets.token_hex(32)`, stored as SHA-256 hash.
- `X-API-Key` header on all authenticated requests.
- Three roles in DB: admin, developer, user. Enforced via `_require_admin()` check in review routes and `require_role` decorator in deps.

**Database:**
- Tables auto-created on startup via FastAPI lifespan event (`Base.metadata.create_all`).
- No Alembic migrations wired yet — tables are created directly from models. Wire Alembic before Phase 3 if schema changes need to be tracked.

**CLI:**
- Package: `observal_cli/` (underscore, not hyphen — Python import requirement).
- Entry point: `pyproject.toml` at project root, `observal = "observal_cli.main:app"`.
- Package manager: `uv` (not pip). Install CLI with `uv pip install -e .`.
- Config stored at `~/.observal/config.json` (server_url + api_key).

### Phase 2: MCP Registry

**Submission flow:**
1. `observal submit <GIT_URL>` → CLI calls `POST /api/v1/mcps/analyze` to pre-fill metadata
2. User fills in name, version, category, description, owner, IDEs, setup instructions, changelog
3. CLI calls `POST /api/v1/mcps/submit` → creates listing with status=pending
4. Server runs 2-stage validation inline (clone & inspect, manifest validation)
5. Admin reviews via `observal review list/approve/reject`

**Validation pipeline (v1 — 2 automated stages + approval gate):**
- Stage 1 (clone_and_inspect): Git clone, scan .py files for `FastMCP(` or `@mcp.server` regex
- Stage 2 (manifest_validation): AST parse entry point, extract tools, check descriptions ≥20 chars, check typed params, check server description ≥100 chars
- Stage 3 (approval gate): Admin approve/reject via review endpoints

**Config generation:**
- `POST /api/v1/mcps/{id}/install` with `{"ide": "cursor"}` returns IDE-specific config snippet
- Supported IDEs: `cursor`, `vscode`, `kiro`, `gemini-cli`, `claude-code`
- claude-code returns a shell command (`claude mcp add ...`), others return JSON config
- Download count tracked per install

---

## Key Decisions Made

| Decision | Rationale |
|---|---|
| No Alembic migrations yet | Tables auto-create on startup. Wire before Phase 3 when schema stabilizes. |
| Validation runs inline (not async) | Simpler for v1. If repos are large/slow to clone, move to background task in Phase 4 when we add Celery/APScheduler. |
| `/analyze` is a separate endpoint from `/submit` | CLI needs pre-fill data before prompting the user. Analyze clones + inspects without creating a listing. |
| `rejection_reason` stored on McpListing directly | Simple. No separate rejection history table needed for v1. |
| pyproject.toml at project root | Required for `pip install -e .` to find the `observal_cli` package. |

---

## File Map

```
observal-server/
├── main.py                          # FastAPI app, lifespan, CORS, routers
├── config.py                        # pydantic-settings (DATABASE_URL, CLICKHOUSE_URL, SECRET_KEY)
├── database.py                      # SQLAlchemy async engine + session
├── models/
│   ├── base.py                      # DeclarativeBase
│   ├── user.py                      # User model + UserRole enum
│   ├── enterprise_config.py         # Key-value enterprise settings
│   ├── mcp.py                       # McpListing, McpCustomField, McpDownload, McpValidationResult
│   └── __init__.py                  # Exports all models
├── schemas/
│   ├── auth.py                      # InitRequest, LoginRequest, UserResponse, InitResponse
│   └── mcp.py                       # Submit, Listing, Summary, Install, Analyze, Review schemas
├── api/
│   ├── deps.py                      # get_db, get_current_user, require_role
│   └── routes/
│       ├── auth.py                  # /api/v1/auth/init, login, whoami
│       ├── mcp.py                   # /api/v1/mcps/analyze, submit, list, show, install
│       └── review.py               # /api/v1/review list, show, approve, reject
├── services/
│   ├── mcp_validator.py             # 2-stage validation + analyze_repo()
│   └── config_generator.py          # IDE config snippet generator
├── migrations/versions/             # Empty — Alembic not wired yet
└── requirements.txt

observal_cli/
├── __init__.py
├── main.py                          # Typer CLI app (all commands)
├── client.py                        # httpx wrapper with auth
├── config.py                        # ~/.observal/config.json load/save
└── requirements.txt

docker/
├── docker-compose.yml               # API + PostgreSQL + ClickHouse
├── Dockerfile.api                   # Python 3.12 slim
└── nginx.conf                       # Reverse proxy (for Phase 5+)

.env.example                         # Template for environment variables
pyproject.toml                       # CLI package entry point
```

---

## What's Next: Phase 3 (Agent Registry)

Before starting Phase 3, consider:

1. **Wire Alembic** — Phase 3 adds new tables (agents, agent_mcp_links, agent_goal_templates, agent_goal_sections, agent_downloads). Good time to set up proper migrations.
2. **Agent model** — Agents are config objects (NOT git repos). New CLI command: `observal agent create` (interactive). New routes under `/api/v1/agents/`.
3. **Agent config generator** — Generates rules files + MCP configs bundled together per IDE. Extends the existing `config_generator.py`.
4. **Reuse patterns** — The review flow, listing/show/install pattern, and download tracking from Phase 2 can be reused almost directly for agents.

Phase 4 (Hooks & Telemetry) depends on Phase 3 being done, and also needs:
- ClickHouse table creation (telemetry schema)
- Collector library (`observal-collector` package)
- Hook scripts per IDE
- Update config generators to inject hook configs
