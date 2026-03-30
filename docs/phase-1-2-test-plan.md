# Phase 1 & 2 — Test Plan

---

## Prerequisites

1. Start the stack: `cd docker && docker compose up -d`
2. Wait for PostgreSQL healthcheck to pass
3. Install CLI: `cd /project-root && uv pip install -e .`
4. Copy `.env.example` to `.env` and fill in values (defaults work for local dev)

---

## Phase 1: Foundation Tests

### T1.1 — Health Check
```
GET http://localhost:8000/health
```
Expected: `{"status": "ok"}` with 200

### T1.2 — Unauthenticated Request Rejected
```
GET http://localhost:8000/api/v1/auth/whoami
(no X-API-Key header)
```
Expected: 422 (missing header) or 401

### T1.3 — Init (First Run)
```
POST http://localhost:8000/api/v1/auth/init
Body: {"email": "admin@test.com", "name": "Admin"}
```
Expected: 200, response contains `api_key` string and `user` object with role=admin

### T1.4 — Init (Already Initialized)
```
POST http://localhost:8000/api/v1/auth/init
Body: {"email": "admin2@test.com", "name": "Admin2"}
```
Expected: 400 `"System already initialized"`

### T1.5 — Whoami
```
GET http://localhost:8000/api/v1/auth/whoami
Header: X-API-Key: <key from T1.3>
```
Expected: 200, returns user info (email, name, role=admin)

### T1.6 — Login
```
POST http://localhost:8000/api/v1/auth/login
Body: {"api_key": "<key from T1.3>"}
```
Expected: 200, returns same user info

### T1.7 — Invalid API Key
```
GET http://localhost:8000/api/v1/auth/whoami
Header: X-API-Key: invalid-key-here
```
Expected: 401 `"Invalid API key"`

### T1.8 — CLI Init
```bash
observal init
# Enter: http://localhost:8000, admin@test.com, Admin
```
Expected: Prints success, creates ~/.observal/config.json with server_url and api_key
Note: Server must be freshly started (no existing users) for this to work

### T1.9 — CLI Whoami
```bash
observal whoami
```
Expected: Prints admin name, email, role

### T1.10 — CLI Login
```bash
observal login
# Enter: http://localhost:8000, <api_key>
```
Expected: Prints "Logged in as ..."

---

## Phase 2: MCP Registry Tests

### Setup
Use the admin API key from Phase 1 tests. All Phase 2 requests need `X-API-Key` header.

### T2.1 — Analyze Repo (Valid FastMCP)
```
POST http://localhost:8000/api/v1/mcps/analyze
Header: X-API-Key: <admin_key>
Body: {"git_url": "<url to a repo containing FastMCP server>"}
```
Expected: 200, returns `{name, description, version, tools: [...]}`

### T2.2 — Analyze Repo (Invalid / No FastMCP)
```
POST http://localhost:8000/api/v1/mcps/analyze
Body: {"git_url": "https://github.com/some/non-mcp-repo.git"}
```
Expected: 200, returns `{name: "", description: "", version: "0.1.0", tools: []}`

### T2.3 — Analyze Repo (Bad URL)
```
POST http://localhost:8000/api/v1/mcps/analyze
Body: {"git_url": "https://github.com/nonexistent/repo.git"}
```
Expected: 200, returns empty metadata (graceful failure)

### T2.4 — Submit MCP (Valid)
```
POST http://localhost:8000/api/v1/mcps/submit
Body: {
  "git_url": "https://github.com/example/fastmcp-server.git",
  "name": "test-mcp",
  "version": "1.0.0",
  "description": "<100+ character description here — must be at least 100 characters long to pass validation, so make it descriptive>",
  "category": "utilities",
  "owner": "Platform Team",
  "supported_ides": ["cursor", "kiro"],
  "changelog": "Initial release"
}
```
Expected: 200, returns listing with status=pending, id is UUID

### T2.5 — Submit MCP (Description Too Short)
```
POST http://localhost:8000/api/v1/mcps/submit
Body: { ...same as above but description: "Too short" }
```
Expected: 422 validation error (min_length=100)

### T2.6 — List MCPs (Empty — Nothing Approved Yet)
```
GET http://localhost:8000/api/v1/mcps
```
Expected: 200, empty array `[]` (listing from T2.4 is still pending)

### T2.7 — Review List (Admin)
```
GET http://localhost:8000/api/v1/review
Header: X-API-Key: <admin_key>
```
Expected: 200, array containing the pending listing from T2.4

### T2.8 — Review Show
```
GET http://localhost:8000/api/v1/review/<listing_id>
```
Expected: 200, full listing details including validation_results array

### T2.9 — Approve Listing
```
POST http://localhost:8000/api/v1/review/<listing_id>/approve
```
Expected: 200, listing status changes to "approved"

### T2.10 — List MCPs (After Approval)
```
GET http://localhost:8000/api/v1/mcps
```
Expected: 200, array containing the now-approved listing

### T2.11 — List MCPs with Search
```
GET http://localhost:8000/api/v1/mcps?search=test
```
Expected: 200, returns listings matching "test" in name or description

### T2.12 — List MCPs with Category Filter
```
GET http://localhost:8000/api/v1/mcps?category=utilities
```
Expected: 200, returns listings in "utilities" category

### T2.13 — Show MCP Detail
```
GET http://localhost:8000/api/v1/mcps/<listing_id>
```
Expected: 200, full listing with custom_fields and validation_results

### T2.14 — Install MCP (Cursor)
```
POST http://localhost:8000/api/v1/mcps/<listing_id>/install
Body: {"ide": "cursor"}
```
Expected: 200, returns config_snippet with `{"mcpServers": {"test-mcp": {"command": "python", "args": ["-m", "test-mcp"], "env": {}}}}`

### T2.15 — Install MCP (Claude Code)
```
POST http://localhost:8000/api/v1/mcps/<listing_id>/install
Body: {"ide": "claude-code"}
```
Expected: 200, returns `{"command": "claude mcp add test-mcp -- python -m test-mcp", "type": "shell_command"}`

### T2.16 — Install MCP (Kiro)
```
Body: {"ide": "kiro"}
```
Expected: Same structure as cursor (mcpServers JSON with python command)

### T2.17 — Install MCP (Gemini CLI)
```
Body: {"ide": "gemini-cli"}
```
Expected: mcpServers JSON without `env` key

### T2.18 — Reject Listing
Submit a second MCP, then:
```
POST http://localhost:8000/api/v1/review/<new_listing_id>/reject
Body: {"reason": "Description is misleading"}
```
Expected: 200, status=rejected, rejection_reason="Description is misleading"

### T2.19 — Non-Admin Cannot Review
Create a non-admin user (requires direct DB insert or a future user-creation endpoint), then:
```
GET http://localhost:8000/api/v1/review
Header: X-API-Key: <non_admin_key>
```
Expected: 403 `"Admin access required"`

### T2.20 — Install Unapproved Listing
```
POST http://localhost:8000/api/v1/mcps/<pending_listing_id>/install
Body: {"ide": "cursor"}
```
Expected: 404 `"Approved listing not found"`

---

## CLI Integration Tests (Phase 2)

### T2.CLI.1 — Submit via CLI
```bash
observal submit https://github.com/example/fastmcp-server.git
# Fill in prompts interactively
```
Expected: Prints "Submitted! ID: <uuid> — Status: pending"

### T2.CLI.2 — Submit with Bad Repo (Graceful Failure)
```bash
observal submit https://github.com/nonexistent/repo.git
```
Expected: Prints "[yellow]Could not analyze repo..." warning, then prompts for manual input

### T2.CLI.3 — List via CLI
```bash
observal list
observal list --category utilities
observal list --search test
```
Expected: Rich table with columns: ID, Name, Version, Category, Owner

### T2.CLI.4 — Show via CLI
```bash
observal show <listing_id>
```
Expected: Prints name, version, category, owner, description, IDEs, setup, git URL

### T2.CLI.5 — Install via CLI
```bash
observal install <listing_id> --ide cursor
```
Expected: Prints config snippet JSON

### T2.CLI.6 — Review Flow via CLI
```bash
observal review list
observal review show <id>
observal review approve <id>
# or
observal review reject <id> --reason "Needs better docs"
```
Expected: Each command prints appropriate output

### T2.CLI.7 — Connection Error Handling
```bash
# Stop the server first
observal whoami
```
Expected: Prints "Connection failed. Is the server running?" (not a stack trace)

---

## Edge Cases to Verify

| Case | Expected |
|---|---|
| Submit with empty `supported_ides` array | Should succeed (field defaults to `[]`) |
| Submit with `custom_fields` | Should create McpCustomField records |
| Multiple installs of same MCP | Each creates a new McpDownload record |
| Approve an already-approved listing | Should succeed (idempotent) |
| Reject an already-rejected listing | Should succeed (idempotent) |
| Very long description (10k+ chars) | Should succeed (Text column, no max) |
| Unicode in name/description | Should succeed (PostgreSQL handles UTF-8) |
| Concurrent submissions | Should not conflict (UUIDs are unique) |
