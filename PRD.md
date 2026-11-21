# PRD: Gudang App (Warehouse Management System)

## 1. Project Overview
**Gudang App** is a lightweight, self-hosted warehouse management system designed for a small-to-medium enterprise operating two warehouses on a single local PC. It replaces a bloated legacy ERP by focusing strictly on core warehouse operations, inventory tracking, and role-based access control. 

**Out of Scope:** Payroll, HR, attendance, and sales features from the legacy system are explicitly excluded.

## 2. User Roles & Permissions
Strict server-side permission checks are enforced. Missing permissions return a `403 Forbidden` response.

| Role | Permissions | Capabilities |
| :--- | :--- | :--- |
| **Owner** | `*` (All) | Full system access, user management, settings, backups, audit logs. |
| **Manager** | `warehouse.*`, `admin.audit` | Manage locations/SKUs, approve/reject stock requests, view audit logs. |
| **Staff** | `warehouse.view`, `warehouse.record` | View inventory, propose stock changes (requests). Cannot execute directly. |

## 3. Functional Requirements

### 3.1 Authentication & Security
- **Session Management:** Signed, `HttpOnly`, `Secure`, `SameSite=Lax` cookies. Unlimited lifetime until explicit logout, password change, deactivation, or admin revocation.
- **Password Handling:** Hashed via `argon2-cffi`. Never stored in plaintext, logged, or returned in API responses.
- **Admin Reset:** Admin sets a temporary password; user is forced to change it on next login; all prior sessions are invalidated.
- **Security:** CSRF protection on all state-changing forms. Failed logins are logged to the audit trail.

### 3.2 Warehouse Structure
- **Hierarchy:** Gudang (Warehouse) → Area → Rak (Rack).
- **Operations:** CRUD and archive (soft delete). 
- **Rule:** Cannot archive a location if it contains active stock > 0.
- **UI:** Drill-down explorer (`/w` → `/w/gudang/{id}` → `/w/area/{id}` → `/w/rak/{id}`).

### 3.3 SKU Management
- **Catalog:** Manage SKUs with immutable codes, names, and descriptions.
- **Bulk Import:** Two-phase `.xlsx`/`.csv` upload (Parse/Validate → Preview → Atomic Commit). Max 5,000 rows / 2MB. Skips existing codes, rejects intra-file duplicates.
- **Export:** Every list view includes an "Export to .xlsx" button.

### 3.4 Stock Operations
- **Actions:** Masuk (In), Pindah (Move), Adjust, Keluar (Out).
- **Rules:** "Keluar" and "Pindah" require a reason. Stock cannot drop below zero. Direct execution requires `warehouse.manage`.
- **Ledger:** Every change creates a `StockEvent` and updates the `Stock` ledger atomically.

### 3.5 Request Workflow
- **Proposal:** Staff propose stock changes, landing in `/w/requests` as `pending`.
- **Approval:** Managers/Owners approve or reject. Approval executes the stock change atomically.
- **Auto-Reject:** Requests auto-reject if insufficient stock exists at the time of approval.
- **UI:** Sidebar badge shows pending count; dashboard toast alerts managers.

### 3.6 QR Codes
- **Generation:** Generate QR code images for individual Raks (`/w/rak/{id}/qr`).
- **Printing:** Generate printable QR sheets for entire Areas (`/w/area/{id}/qr-sheet`).

### 3.7 Administration
- **Users:** Create, update roles, reset passwords, revoke sessions. Owners can create Owners/Managers; Managers cannot escalate privileges.
- **Settings:** DB-stored settings (QR base URL, backup schedule, retention days).
- **Backups:** Manual trigger and scheduled daily backups (APScheduler) to a `backups/` directory.
- **Audit Log:** Read-only, paginated, exportable view of all system events.

## 4. Non-Functional Requirements

### 4.1 Tech Stack
- **Backend:** Python 3.12+, FastAPI, Uvicorn
- **Database:** SQLite (WAL mode, strict pragmas), SQLAlchemy 2.0, Alembic
- **Frontend:** Jinja2 templates, HTMX (vendored), single `app.css` file
- **Utilities:** `openpyxl`, `qrcode`, `Pillow`, `APScheduler`, `pytest`

### 4.2 UI/UX Design System
- **Layout:** Fixed dark sidebar (260px, `#3c4b64`), light gray body (`#f4f6f8`), white top header.
- **Styling:** Minimal, one accent color, **no external CSS frameworks** (no Bootstrap/Tailwind).
- **Responsive:** Mobile (<768px) sidebar collapses to an off-canvas drawer.
- **Interactions:** Toast notifications (auto-dismiss 4s), color-coded stock badges, hover lift effects on cards.

### 4.3 Data Integrity
- **No Hard Deletes:** Use `is_active` boolean or reversal entries.
- **Audit Trail:** Every write operation logs to `audit_log` (actor, timestamp, entity, action, before/after state).
- **Transactions:** Every save commits in a single transaction.

## 5. Deployment Strategy (Windows Target)
- **Prerequisites:** Python 3.12 x64, Git.
- **Execution:** `GudangApp.bat` running `uvicorn app.main:app --host 0.0.0.0 --port 8000`.
- **Auto-start:** Shortcut in `shell:startup`.
- **Auto-update:** `scripts/update.bat` (stops app → `git pull` → `pip install` → `alembic upgrade` → restarts app).
- **Safety:** `data/` and `config.toml` are gitignored to protect live DB and secrets during pulls.
