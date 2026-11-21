import io
from openpyxl import Workbook
from tests.conftest import login, make_user
from app.auth.models import User
from app.warehouse import services
from app.warehouse.models import Sku
from app.warehouse.sku_import import parse_file, validate_against_db, commit_import, generate_template


def _xlsx_bytes(rows):
    wb = Workbook()
    ws = wb.active
    ws.append(["code", "name", "description"])
    for r in rows:
        ws.append(r)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def _csv_bytes(rows):
    # Bulletproof CSV generation using list join to guarantee header is present
    lines = ["code,name,description"]
    for r in rows:
        lines.append(",".join(str(c) for c in r))
    return "\n".join(lines).encode("utf-8")


def test_parse_xlsx_valid(client, db):
    make_user(db, "mgr", "manager")
    login(client, "mgr")
    preview = parse_file(_xlsx_bytes([["SKU-1", "Produk 1", "Desc"]]), "test.xlsx")
    assert preview.file_error is None
    assert len(preview.valid) == 1
    assert preview.valid[0].code == "SKU-1"


def test_parse_csv_valid(client, db):
    make_user(db, "mgr", "manager")
    login(client, "mgr")
    preview = parse_file(_csv_bytes([["SKU-2", "Produk 2", ""]]), "test.csv")
    assert preview.file_error is None
    assert len(preview.valid) == 1
    assert preview.valid[0].code == "SKU-2"


def test_skip_existing_codes(client, db):
    make_user(db, "mgr", "manager")
    login(client, "mgr")
    actor = db.query(User).first()
    services.create_sku(db, actor, "SKU-EXIST", "Existing", None)
    preview = parse_file(_xlsx_bytes([["SKU-EXIST", "Dup", ""], ["SKU-NEW", "New", ""]]), "test.xlsx")
    preview = validate_against_db(db, preview)
    assert len(preview.skipped) == 1 and preview.skipped[0].code == "SKU-EXIST"
    assert len(preview.valid) == 1 and preview.valid[0].code == "SKU-NEW"


def test_reject_intra_file_duplicates(client, db):
    make_user(db, "mgr", "manager")
    login(client, "mgr")
    preview = parse_file(_xlsx_bytes([["DUP", "A", ""], ["DUP", "B", ""]]), "test.xlsx")
    assert preview.file_error and "duplikat" in preview.file_error.lower()


def test_file_size_limit(client, db):
    make_user(db, "mgr", "manager")
    login(client, "mgr")
    preview = parse_file(b"x" * (3 * 1024 * 1024), "big.xlsx")
    assert preview.file_error and "terlalu besar" in preview.file_error.lower()


def test_row_limit(client, db):
    make_user(db, "mgr", "manager")
    login(client, "mgr")
    rows = [[f"SKU-{i}", f"P{i}", ""] for i in range(5001)]
    preview = parse_file(_xlsx_bytes(rows), "many.xlsx")
    assert preview.file_error and "banyak baris" in preview.file_error.lower()


def test_atomic_commit(client, db):
    make_user(db, "mgr", "manager")
    login(client, "mgr")
    actor = db.query(User).first()
    preview = parse_file(_xlsx_bytes([["NEW-1", "A", ""], ["NEW-2", "B", "Desc"]]), "test.xlsx")
    preview = validate_against_db(db, preview)
    count = commit_import(db, preview.valid, actor)
    assert count == 2
    assert db.query(Sku).filter(Sku.code.in_(["NEW-1", "NEW-2"])).count() == 2


def test_template_download(client, db):
    make_user(db, "mgr", "manager")
    login(client, "mgr")
    r = client.get("/manage/skus/import-template")
    assert r.status_code == 200
    assert "sku_import_template.xlsx" in r.headers["content-disposition"]


def test_staff_cannot_import(client, db):
    make_user(db, "st", "staff")
    login(client, "st")
    r = client.get("/manage/skus/import", follow_redirects=False)
    assert r.status_code == 403


def test_two_phase_import_over_http(client, db):
    make_user(db, "mgr", "manager")
    login(client, "mgr")
    csrf = client.cookies.get("csrf")
    r = client.post(
        "/manage/skus/import-preview",
        data={"csrf_token": csrf},
        files={"file": ("import.xlsx", _xlsx_bytes([["HTTP-1", "Produk HTTP", ""]]),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert r.status_code == 200 and "HTTP-1" in r.text
    token = r.text.split('name="import_token" value="')[1].split('"')[0]
    r = client.post("/manage/skus/import-confirm",
                    data={"csrf_token": csrf, "import_token": token},
                    follow_redirects=False)
    assert r.status_code == 302 and "import.success" in r.headers["location"]
    assert db.query(Sku).filter_by(code="HTTP-1").first() is not None


def test_import_confirm_rejects_unknown_token(client, db):
    make_user(db, "mgr", "manager")
    login(client, "mgr")
    r = client.post("/manage/skus/import-confirm",
                    data={"csrf_token": client.cookies.get("csrf"),
                          "import_token": "../../etc/passwd"},
                    follow_redirects=False)
    assert r.status_code == 302 and "import.token_invalid" in r.headers["location"]


def test_multipart_requires_csrf(client, db):
    make_user(db, "mgr", "manager")
    login(client, "mgr")
    r = client.post("/manage/skus/import-preview",
                    files={"file": ("x.csv", b"code,name\nA,B", "text/csv")})
    assert r.status_code == 403
