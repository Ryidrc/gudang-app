# Gudang App

Lightweight, self-hosted warehouse management for two warehouses on one PC
(FastAPI + SQLite + Jinja2/HTMX). Replaces the legacy ERP for warehouse operations only.

## Requirements

- Python 3.12+ (x64 on Windows)
- No Node.js, Docker, or external CSS framework
- SQLite runs in WAL mode via `data/app.db`

## First run (Linux / macOS)

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m app.core.prestart     # writes config.toml with a random secret_key
alembic upgrade head            # creates the schema
python -m app.core.bootstrap    # creates the first Owner (interactive)
./scripts/run.sh                # prestart + migrate + uvicorn on 0.0.0.0:8000
```

Open <http://localhost:8000> and log in.

## First run (Windows)

1. Install Python 3.12 x64 (check *Add to PATH*).
2. Double-click `GudangApp.bat` (creates `.venv`, installs deps, migrates, starts the server).
3. In a second terminal, create the first Owner:
   ```bat
   .venv\Scripts\activate
   python -m app.core.bootstrap
   ```
4. Open <http://localhost:8000>. Other PCs on the LAN use `http://<server-ip>:8000`.
5. Auto-start: put a shortcut to `GudangApp.bat` in `shell:startup`.
6. Updates: run `scripts\update.bat` (stop → `git pull` → `pip install` → `alembic upgrade` → restart).

## Configuration

- `config.toml` — bootstrap only (host/port, cookie `Secure` flag, secret key). Created on first run; never commit it.
- Runtime settings live in the DB and are edited under **Admin → Settings**: QR base URL, daily backup time, retention days.
- Set `qr_base_url` to the LAN URL (e.g. `http://192.168.1.50:8000`) before printing QR sheets.
- `data/` (live DB + backups) and `config.toml` are gitignored and survive updates.

### Cookies over plain HTTP

`config.toml` ships with `cookie_secure = false` because LAN deployments usually run plain HTTP.
Set it to `true` only when the app is served behind HTTPS; otherwise browsers drop the session cookie.

## Roles

| Role | Permissions |
| :--- | :--- |
| Owner | everything, user management, settings, backups |
| Manager | `warehouse.*`, `admin.audit` |
| Staff | `warehouse.view` (+ `warehouse.record` when enabled per user) |

All checks are server-side; direct stock execution requires `warehouse.manage`, while Staff submit
requests that a Manager/Owner approves. Approvals auto-reject if stock ran out.

## Operations

- Backups: **Admin → Backups → Run now**, plus a daily job at the configured WIB time. Files land in `data/backups/`.
- Restore: stop the app, copy the chosen `gudang_*.db` over `data/app.db` (delete `data/app.db-wal` / `-shm` first), start again.
- Audit: **Admin → Audit** (paginated, exportable).
- Every list view has an `.xlsx` export; lists paginate above 50 rows.
- SKU bulk import: **Kelola SKU → Import**, upload `.xlsx`/`.csv` (≤5,000 rows, ≤2 MB),
  preview valid/skipped/rejected rows, then commit atomically. Codes are immutable; existing codes are skipped.

## Tests

```bash
GUDANG_TEST=1 .venv/bin/python -m pytest -q
```

Tests use an isolated SQLite file per test and never touch `data/app.db`. APScheduler is disabled under `GUDANG_TEST=1`.

## Layout

```text
app/
  core/        config, DB, security, i18n, pagination, backup, scheduler
  auth/        users, sessions, login, profile
  warehouse/   tree, SKUs, stock engine, requests, QR, import/export
  admin/       dashboard, users, settings, backups, audit
  templates/   shared base + partials
  static/      app.css + vendored htmx
  i18n/        id.json (primary), en.json
migrations/    Alembic revisions
scripts/       run.sh, update.bat
tests/         pytest suite
```
