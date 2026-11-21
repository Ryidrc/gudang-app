# AGENTS.md — Gudang App (omp Operating Manual)

## 0. How to Use This File
`omp` loads this at startup. Follow it strictly. When a requirement is ambiguous, ask before assuming. Never re-introduce features outside the warehouse scope.

## 1. Project Scope
Local FastAPI warehouse app. One PC, two warehouses. Replaces a legacy ERP.
**Out of scope (do NOT build):** payroll, HR, attendance, sales.

## 2. Hard Constraints
- **ALLOWED:** Python 3.12, FastAPI, Uvicorn, SQLAlchemy 2.0, Alembic, Jinja2, HTMX (vendored), SQLite (WAL), `openpyxl`, `qrcode`, `Pillow`, `APScheduler`, `pytest`, `argon2-cffi`, `itsdangerous`.
- **FORBIDDEN:** Node.js, React/Vue, Docker, pandas, Bootstrap, Tailwind, any external CSS framework, hard deletes.

## 3. Architecture & Layout
```text
app/
  core/           # config, db setup, security, exceptions
  auth/           # models.py, services.py, routes.py, templates/
  warehouse/      # models.py, services.py, routes.py, templates/
  admin/          # models.py, services.py, routes.py, templates/
  templates/      # shared Jinja2 base + partials
  static/         # single app.css, vendored htmx.js, images
  i18n/           # id.json (primary), en.json (fallback)
```
**Rules:** business logic lives only in `services.py`; `routes.py` stays thin (validate → call service → respond); templates display only.

## 4. Coding Standards
### 4.1 Data & Security
- Money = Integer rupiah. Dates = store UTC, display Asia/Jakarta (DD/MM/YYYY).
- Never hard-delete → use `is_active`/`status` or reversal entries.
- Every write logs to `audit_log` (actor, at, entity, entity_id, action, before, after, ip). Auth events count as writes.
- Every save commits in one transaction. CSRF on all state-changing forms. Cookies: `HttpOnly`, `Secure`, `SameSite=Lax`.
- Passwords hashed with `argon2-cffi`; never stored, logged, or returned.

### 4.2 UI & i18n
- All user-facing strings come from `app/i18n/id.json`; no literals in templates.
- Paginate lists >50 rows; every list has an `.xlsx` export button.
- Sidebar `#3c4b64` (260px), body `#f4f6f8`. Cards: white, 4px radius, subtle shadow, hover lift. Stock badges: green <10, yellow 10–50, red >50.

### 4.3 Permissions
- Check server-side on **every** route (hiding UI is not enough). Missing permission → `403` with an Indonesian message.
- Roles: Owner (`*`), Manager (`warehouse.*`, `admin.audit`), Staff (`warehouse.view` + optional `warehouse.record`).

## 5. omp Tool Usage (Workflow)
- **Edits:** prefer `ast_edit` over `edit` for structural, token-efficient patches.
- **Parallel work:** use `task` to fan out independent units (e.g., multiple templates or test files at once).
- **Code intel:** use `lsp` for navigation/rename; trust its diagnostics over grep.
- **Run for real:** use the `bash`/`eval` tool to execute `pytest` and the app locally. **NEVER fabricate output** — paste the actual terminal result.
- **Context:** if the session grows long, run `/compact` to summarize history.
- **Memory:** use `retain`/`recall` to persist project facts across sessions.

## 6. Testing Rules
- Framework: `pytest` + `fastapi.testclient.TestClient`.
- DB: in-memory SQLite (`sqlite:///:memory:`) or isolated temp files.
- Fixtures: `db` (clean session), `client` (TestClient with `get_db` overridden), `make_user`/`login` helpers.
- Each test gets a fresh DB; tables created/dropped per test. Skip APScheduler when `GUDANG_TEST` env var is set.

## 7. Verification Loop
1. Write the code.
2. Run `pytest` via the `bash` tool.
3. If it fails → fix → rerun until green.
4. Only then propose a commit, and show the real `pytest` summary line.
**Rule:** never claim "it passed" without the actual output attached.
