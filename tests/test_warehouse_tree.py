from tests.conftest import login, make_user
from app.warehouse.models import Gudang, Rak, Stock


def _mgr(client, db):
    make_user(db, "mgr", "manager")
    login(client, "mgr")
    return client.cookies.get("csrf")


def test_explorer_requires_login(client):
    r = client.get("/w", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"].startswith("/login")


def test_staff_can_view_but_not_manage(client, db):
    make_user(db, "st", "staff")
    login(client, "st")
    assert client.get("/w").status_code == 200
    r = client.get("/manage/gudangs", follow_redirects=False)
    assert r.status_code == 403


def test_manager_creates_tree_and_explorer_shows_it(client, db):
    csrf = _mgr(client, db)
    r = client.post("/manage/gudangs", data={"csrf_token": csrf, "name": "Gudang 1"}, follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"].endswith("msg=manage.created")
    g = db.query(Gudang).first()

    # Removed "layout": "horizontal" from payload
    r = client.post("/manage/areas", data={"csrf_token": csrf, "gudang_id": g.id,
        "name": "Area A", "sort_order": 0}, follow_redirects=False)
    assert r.status_code == 302

    from app.warehouse.models import Area
    a = db.query(Area).first()
    r = client.post("/manage/raks", data={"csrf_token": csrf, "area_id": a.id,
        "name": "T1", "sort_order": 1}, follow_redirects=False)
    assert r.status_code == 302

    body = client.get(f"/w/area/{a.id}").text
    assert "T1" in body and "rak-grid" in body  # Removed specific layout check


def test_duplicate_gudang_name_rejected(client, db):
    csrf = _mgr(client, db)
    client.post("/manage/gudangs", data={"csrf_token": csrf, "name": "G1"}, follow_redirects=False)
    r = client.post("/manage/gudangs", data={"csrf_token": csrf, "name": "G1"}, follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"].endswith("msg=manage.name_taken")


def test_archive_blocked_with_stock_then_ok(client, db):
    csrf = _mgr(client, db)
    from app.auth.models import User
    from app.warehouse import services
    actor = db.query(User).first()

    g = services.create_gudang(db, actor, "G1")
    a = services.create_area(db, actor, g.id, "A", 0)  # Removed "vertical"
    rk = services.create_rak(db, actor, a.id, "T1", 1)
    sku = services.create_sku(db, actor, "SKU-A", "SKU A", None)

    db.add(Stock(rak_id=rk.id, sku_id=sku.id, qty_boxes=3))
    db.commit()

    r = client.post(f"/manage/raks/{rk.id}/active", data={"csrf_token": csrf, "is_active": ""}, follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"].endswith("msg=manage.has_stock")

    db.query(Stock).first().qty_boxes = 0
    db.commit()

    r = client.post(f"/manage/raks/{rk.id}/active", data={"csrf_token": csrf, "is_active": ""}, follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"].endswith("msg=manage.archived_ok")
    assert f"/w/rak/{rk.id}" not in client.get(f"/w/area/{a.id}").text


def test_sku_code_immutable(client, db):
    csrf = _mgr(client, db)
    client.post("/manage/skus", data={"csrf_token": csrf, "code": "abc",
                                      "name": "Produk", "description": ""}, follow_redirects=False)
    from app.warehouse.models import Sku
    s = db.query(Sku).first()
    assert s.code == "ABC"
    client.post(f"/manage/skus/{s.id}/update", data={"csrf_token": csrf,
                "name": "Produk Baru", "description": "x"}, follow_redirects=False)
    db.expire_all()
    s = db.query(Sku).first()
    assert s.code == "ABC" and s.name == "Produk Baru"
