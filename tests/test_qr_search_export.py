from tests.conftest import login, make_user
from app.warehouse import services
from app.warehouse.models import Gudang, Area, Rak, Sku, Stock
from app.auth.models import User

def _setup_tree(db):
    actor = db.query(User).first()
    g = services.create_gudang(db, actor, "G1")
    a = services.create_area(db, actor, g.id, "A", 0)  # Removed "vertical"
    r1 = services.create_rak(db, actor, a.id, "R1", 1)
    sku = services.create_sku(db, actor, "SKU-TEST", "Produk Test", None)
    services.execute_masuk(db, actor, sku.id, r1.id, 5, "Test")
    return actor, g, a, r1, sku

def test_global_search_finds_stock(client, db):
    make_user(db, "mgr", "manager")
    login(client, "mgr")
    actor, g, a, r1, sku = _setup_tree(db)

    r = client.get("/w/search?q=SKU-TEST")
    assert r.status_code == 200
    assert "Produk Test" in r.text and "G1" in r.text and "5" in r.text

def test_global_search_no_results(client, db):
    make_user(db, "mgr", "manager")
    login(client, "mgr")
    r = client.get("/w/search?q=NOTFOUND")
    assert r.status_code == 200
    assert "Tidak ada hasil" in r.text or "No results" in r.text

def test_qr_image_generation(client, db):
    make_user(db, "mgr", "manager")
    login(client, "mgr")
    actor, g, a, r1, sku = _setup_tree(db)

    r = client.get(f"/w/rak/{r1.id}/qr")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert len(r.content) > 100

def test_qr_sheet_page(client, db):
    make_user(db, "mgr", "manager")
    login(client, "mgr")
    actor, g, a, r1, sku = _setup_tree(db)

    r = client.get(f"/w/area/{a.id}/qr-sheet")
    assert r.status_code == 200
    assert "Lembar Cetak QR" in r.text or "QR Print Sheet" in r.text
    assert "R1" in r.text

def test_xlsx_export_skus(client, db):
    make_user(db, "mgr", "manager")
    login(client, "mgr")
    actor, g, a, r1, sku = _setup_tree(db)

    r = client.get("/manage/skus?export=xlsx")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert "skus_export.xlsx" in r.headers["content-disposition"]
