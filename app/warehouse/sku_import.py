"""SKU bulk import: parse, validate, preview, commit."""
from __future__ import annotations

import csv
import io
import re
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from openpyxl import Workbook, load_workbook
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.core.config import DATA_DIR
from app.warehouse.models import Sku

MAX_ROWS = 5000
MAX_BYTES = 2 * 1024 * 1024  # 2 MB
IMPORT_DIR = DATA_DIR / "imports"
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{20,64}$")
_TOKEN_TTL = 3600


@dataclass
class ImportRow:
    row_num: int
    code: str
    name: str
    description: str
    status: str = "valid"  # valid | skip | invalid
    error: Optional[str] = None


@dataclass
class ImportPreview:
    valid: List[ImportRow] = field(default_factory=list)
    skipped: List[ImportRow] = field(default_factory=list)
    invalid: List[ImportRow] = field(default_factory=list)
    file_error: Optional[str] = None


def parse_file(content: bytes, filename: str) -> ImportPreview:
    if len(content) > MAX_BYTES:
        return ImportPreview(file_error=f"File terlalu besar (maks {MAX_BYTES // 1024} KB)")

    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    try:
        if ext == "xlsx":
            rows = _parse_xlsx(content)
        elif ext == "csv":
            rows = _parse_csv(content)
        else:
            return ImportPreview(file_error="Format tidak didukung. Gunakan .xlsx atau .csv")
    except Exception as e:
        return ImportPreview(file_error=f"Gagal membaca file: {e}")

    if len(rows) > MAX_ROWS:
        return ImportPreview(file_error=f"Terlalu banyak baris (maks {MAX_ROWS})")

    codes = [r.code for r in rows]
    dupes = sorted({c for c in codes if codes.count(c) > 1})
    if dupes:
        return ImportPreview(file_error=f"Kode duplikat dalam file: {', '.join(dupes[:10])}")

    return ImportPreview(valid=rows)


def _parse_xlsx(content: bytes) -> List[ImportRow]:
    wb = load_workbook(filename=io.BytesIO(content), read_only=True, data_only=True)
    ws = wb.active
    it = ws.iter_rows(values_only=True)
    header = next(it, None)
    if header is None:
        wb.close()
        return []

    header = [str(h).strip().lower() if h is not None else "" for h in header]
    if "code" not in header or "name" not in header:
        wb.close()
        raise ValueError(f"Kolom wajib tidak ditemukan. Ditemukan: {header}. Butuh: 'code' dan 'name'")

    code_idx = header.index("code")
    name_idx = header.index("name")
    desc_idx = header.index("description") if "description" in header else None

    rows = []
    for i, row in enumerate(it, start=2):
        if row is None or all(c is None for c in row):
            continue
        code = str(row[code_idx]).strip().upper() if row[code_idx] is not None else ""
        name = str(row[name_idx]).strip() if row[name_idx] is not None else ""
        desc = str(row[desc_idx]).strip() if desc_idx is not None and row[desc_idx] is not None else ""
        rows.append(ImportRow(row_num=i, code=code, name=name, description=desc))
    wb.close()
    return rows


def _parse_csv(content: bytes) -> List[ImportRow]:
    text = content.decode("utf-8-sig")
    # Explicitly set delimiter to comma and handle newlines safely
    reader = csv.DictReader(io.StringIO(text), delimiter=',')
    if not reader.fieldnames:
        return []

    fieldnames = [f.strip().lower() for f in reader.fieldnames]

    # Explicit check to prevent set logic quirks and give clear errors
    if "code" not in fieldnames or "name" not in fieldnames:
        raise ValueError(f"Kolom wajib tidak ditemukan. Ditemukan: {fieldnames}. Butuh: 'code' dan 'name'")

    rows = []
    for i, row in enumerate(reader, start=2):
        code = str(row.get("code", "")).strip().upper()
        name = str(row.get("name", "")).strip()
        desc = str(row.get("description", "")).strip()
        rows.append(ImportRow(row_num=i, code=code, name=name, description=desc))
    return rows


def validate_against_db(db: DbSession, preview: ImportPreview) -> ImportPreview:
    if preview.file_error:
        return preview

    existing = {c.upper() for c in db.scalars(select(Sku.code)).all()}
    valid, skipped, invalid = [], [], []

    for row in preview.valid:
        if not row.code:
            row.status, row.error = "invalid", "Kode kosong"
            invalid.append(row)
        elif not row.name:
            row.status, row.error = "invalid", "Nama kosong"
            invalid.append(row)
        elif len(row.code) > 64:
            row.status, row.error = "invalid", "Kode terlalu panjang (maks 64)"
            invalid.append(row)
        elif row.code in existing:
            row.status, row.error = "skip", "Sudah ada"
            skipped.append(row)
        else:
            valid.append(row)

    return ImportPreview(valid=valid, skipped=skipped, invalid=invalid)


def commit_import(db: DbSession, rows: List[ImportRow], actor) -> int:
    from app.core.models import write_audit
    count = 0
    try:
        for row in rows:
            if row.status != "valid":
                continue
            db.add(Sku(code=row.code, name=row.name, description=row.description or None))
            count += 1
        write_audit(db, actor, "sku.import", "sku", None, after={"created": count})
        db.commit()
    except Exception:
        db.rollback()
        raise
    return count


# ---------- two-phase upload staging ----------

def _cleanup_old() -> None:
    IMPORT_DIR.mkdir(parents=True, exist_ok=True)
    cutoff = time.time() - _TOKEN_TTL
    for f in IMPORT_DIR.iterdir():
        try:
            if f.is_file() and f.stat().st_mtime < cutoff:
                f.unlink()
        except OSError:
            pass


def stash_upload(content: bytes, filename: str) -> str:
    """Persist an uploaded file under an unguessable token for the confirm step."""
    _cleanup_old()
    token = secrets.token_urlsafe(24)
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    if ext not in ("xlsx", "csv"):
        ext = "bin"
    (IMPORT_DIR / f"{token}.{ext}").write_bytes(content)
    return token


def load_upload(token: str | None) -> tuple[bytes, str] | None:
    if not token or not _TOKEN_RE.match(token):
        return None
    for f in IMPORT_DIR.glob(f"{token}.*"):
        if f.is_file():
            return f.read_bytes(), f.name
    return None


def discard_upload(token: str | None) -> None:
    if not token or not _TOKEN_RE.match(token):
        return
    for f in IMPORT_DIR.glob(f"{token}.*"):
        try:
            f.unlink()
        except OSError:
            pass


def generate_template() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "SKU Import"
    ws.append(["code", "name", "description"])
    ws.append(["SKU-001", "Contoh Produk", "Deskripsi opsional"])
    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    return out.getvalue()
