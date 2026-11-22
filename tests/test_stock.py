from tests.conftest import login, make_user
from app.warehouse import services
from app.warehouse.models import Gudang, Area, Rak, Sku, Stock, StockRequest, StockEvent
from app.auth.models import User

def _setup_tree(db):
    actor = db.query(User).first()
    g = services.create_gudang(db, actor, "G1")
    a = services.create_area(db, actor, g.id, "A", 0)  # Removed "vertical"
    r1 = services.create_rak(db, actor, a.id, "R1", 1)
    r2 = services.create_rak(db, actor, a.id, "R2", 2)
    sku = services.create_sku(db, actor, "SKU-1", "Produk 1", None)
    return actor, g, a, r1, r2, sku

def test_masuk_and_history(client, db):
    make_user(db, "mgr", "manager")
    login(client, "mgr")
    actor, g, a, r1, r2, sku = _setup_tree(db)
    services.execute_masuk(db, actor, sku.id, r1.id, 10, "Beli baru")
    stock = db.query(Stock).filter_by(rak_id=r1.id, sku_id=sku.id).first()
    assert stock.qty_boxes == 10 and stock.is_active is True
    ev = db.query(StockEvent).filter_by(sku_id=sku.id, type="in").first()
    assert ev.qty == 10 and ev.to_rak_id == r1.id

def test_pindah(client, db):
    make_user(db, "mgr", "manager")
    login(client, "mgr")
    actor, g, a, r1, r2, sku = _setup_tree(db)
    services.execute_masuk(db, actor, sku.id, r1.id, 10, "Awal")
    services.execute_pindah(db, actor, sku.id, r1.id, r2.id, 4, "Pindah sebagian")
    assert db.query(Stock).filter_by(rak_id=r1.id, sku_id=sku.id).first().qty_boxes == 6
    assert db.query(Stock).filter_by(rak_id=r2.id, sku_id=sku.id).first().qty_boxes == 4

def test_keluar_requires_reason(client, db):
    make_user(db, "mgr", "manager")
    login(client, "mgr")
    actor, g, a, r1, r2, sku = _setup_tree(db)
    services.execute_masuk(db, actor, sku.id, r1.id, 5, "Awal")
    try:
        services.execute_keluar(db, actor, sku.id, r1.id, 2, None)
        assert False
    except ValueError as e: assert "reason_required" in str(e)

def test_adjust_to_zero_archives(client, db):
    make_user(db, "mgr", "manager")
    login(client, "mgr")
    actor, g, a, r1, r2, sku = _setup_tree(db)
    services.execute_masuk(db, actor, sku.id, r1.id, 5, "Awal")
    services.execute_adjust(db, actor, sku.id, r1.id, 0, "Opname: hilang")
    stock = db.query(Stock).filter_by(rak_id=r1.id, sku_id=sku.id).first()
    assert stock.qty_boxes == 0 and stock.is_active is False

def test_request_flow(client, db):
    make_user(db, "st", "staff", can_record=True)
    make_user(db, "mgr", "manager")
    login(client, "st")
    actor_st = db.query(User).filter_by(username="st").first()
    actor, g, a, r1, r2, sku = _setup_tree(db)
    services.execute_masuk(db, actor, sku.id, r1.id, 10, "Awal")

    req = services.create_stock_request(db, actor_st, "move", sku.id, r1.id, r2.id, 3, "Test pindah")
    assert req.status == "pending"
    assert db.query(Stock).filter_by(rak_id=r1.id, sku_id=sku.id).first().qty_boxes == 10

    login(client, "mgr")
    actor_mgr = db.query(User).filter_by(username="mgr").first()
    services.approve_stock_request(db, actor_mgr, req.id)

    assert db.get(StockRequest, req.id).status == "approved"
    assert db.query(Stock).filter_by(rak_id=r1.id, sku_id=sku.id).first().qty_boxes == 7
    assert db.query(Stock).filter_by(rak_id=r2.id, sku_id=sku.id).first().qty_boxes == 3

def test_request_auto_reject_on_insufficient_stock(client, db):
    make_user(db, "st", "staff", can_record=True)
    make_user(db, "mgr", "manager")
    login(client, "st")
    actor_st = db.query(User).filter_by(username="st").first()
    actor, g, a, r1, r2, sku = _setup_tree(db)
    services.execute_masuk(db, actor, sku.id, r1.id, 2, "Awal")

    req = services.create_stock_request(db, actor_st, "move", sku.id, r1.id, r2.id, 5, "Test > stok")
    login(client, "mgr")
    actor_mgr = db.query(User).filter_by(username="mgr").first()

    try:
        services.approve_stock_request(db, actor_mgr, req.id)
        assert False
    except ValueError as e: assert "insufficient_stock_at_approval" in str(e)

    assert db.get(StockRequest, req.id).status == "rejected"

def test_requests_page_renders(client, db):
    make_user(db, "mgr", "manager")
    login(client, "mgr")
    assert client.get("/w/requests").status_code == 200

def test_request_submit_via_http(client, db):
    make_user(db, "st", "staff", can_record=True)
    login(client, "st")
    actor, g, a, r1, r2, sku = _setup_tree(db)
    csrf = client.cookies.get("csrf")
    r = client.post("/w/stock/request", data={"csrf_token": csrf, "type": "move",
        "sku_id": sku.id, "from_rak_id": r1.id, "to_rak_id": r2.id, "qty": 2,
        "reason": "tes"}, follow_redirects=False)
    assert r.status_code == 302 and "request.created" in r.headers["location"]
    from app.warehouse.models import StockRequest
    req = db.query(StockRequest).first()
    assert req is not None and req.status == "pending"


def _batch_post(client, **fields):
    csrf = client.cookies.get("csrf")
    return client.post("/manage/stock/batch", data={"csrf_token": csrf, **fields},
                       follow_redirects=False)


def test_batch_stock_page_permissions(client, db):
    make_user(db, "st", "staff")
    make_user(db, "mgr", "manager")
    login(client, "st")
    assert client.get("/manage/stock").status_code == 403
    login(client, "mgr")
    r = client.get("/manage/stock")
    assert r.status_code == 200 and "Ubah Stok Massal" in r.text


def test_batch_adjust_multiple_skus_and_raks(client, db):
    make_user(db, "mgr", "manager")
    login(client, "mgr")
    actor, g, a, r1, r2, sku = _setup_tree(db)
    sku2 = services.create_sku(db, actor, "SKU-2", "Produk 2", None)
    services.execute_masuk(db, actor, sku.id, r1.id, 5, "Awal")
    services.execute_masuk(db, actor, sku.id, r2.id, 2, "Awal")
    services.execute_masuk(db, actor, sku2.id, r1.id, 1, "Awal")

    r = _batch_post(client, mode="adjust", sel=f"{sku.id},{sku2.id}",
                    **{f"qty_{sku.id}_{r1.id}": "8",
                       f"qty_{sku.id}_{r2.id}": "0",
                       f"qty_{sku2.id}_{r1.id}": "3"},
                    reason="Stock opname")
    assert r.status_code == 302 and "msg=stock.executed" in r.headers["location"]
    assert db.query(Stock).filter_by(rak_id=r1.id, sku_id=sku.id).first().qty_boxes == 8
    zero = db.query(Stock).filter_by(rak_id=r2.id, sku_id=sku.id).first()
    assert zero.qty_boxes == 0 and zero.is_active is False
    assert db.query(Stock).filter_by(rak_id=r1.id, sku_id=sku2.id).first().qty_boxes == 3
    deltas = [e.qty for e in db.query(StockEvent).filter_by(type="adjust").all()]
    assert sorted(deltas) == [-2, 2, 3]


def test_batch_add_new_placements(client, db):
    make_user(db, "mgr", "manager")
    login(client, "mgr")
    actor, g, a, r1, r2, sku = _setup_tree(db)
    services.execute_masuk(db, actor, sku.id, r1.id, 2, "Awal")

    r = _batch_post(client, mode="in", sel=str(sku.id),
                    **{f"qty_{sku.id}_{r1.id}": "1",
                       f"new_rak_{sku.id}": str(r2.id),
                       f"new_qty_{sku.id}": "4"},
                    reason="Batch tambah")
    assert r.status_code == 302 and "msg=stock.executed" in r.headers["location"]
    assert db.query(Stock).filter_by(rak_id=r1.id, sku_id=sku.id).first().qty_boxes == 3
    assert db.query(Stock).filter_by(rak_id=r2.id, sku_id=sku.id).first().qty_boxes == 4
    events = db.query(StockEvent).filter_by(type="in", reason="Batch tambah").all()
    assert sorted(e.qty for e in events) == [1, 4]


def test_batch_out_is_atomic_and_requires_reason(client, db):
    make_user(db, "mgr", "manager")
    login(client, "mgr")
    actor, g, a, r1, r2, sku = _setup_tree(db)
    services.execute_masuk(db, actor, sku.id, r1.id, 5, "Awal")

    r = _batch_post(client, mode="out", sel=str(sku.id),
                    **{f"qty_{sku.id}_{r1.id}": "2"})
    assert r.status_code == 302 and "msg=stock.error.reason_required" in r.headers["location"]
    assert db.query(Stock).filter_by(rak_id=r1.id, sku_id=sku.id).first().qty_boxes == 5

    r = _batch_post(client, mode="out", sel=str(sku.id),
                    **{f"qty_{sku.id}_{r1.id}": "2",
                       f"qty_{sku.id}_{r2.id}": "1"},
                    reason="Rusak")
    assert r.status_code == 302 and "msg=stock.error.insufficient_stock" in r.headers["location"]
    assert db.query(Stock).filter_by(rak_id=r1.id, sku_id=sku.id).first().qty_boxes == 5
    assert db.query(Stock).filter_by(rak_id=r2.id, sku_id=sku.id).first() is None

    r = _batch_post(client, mode="out", sel=str(sku.id),
                    **{f"qty_{sku.id}_{r1.id}": "2"}, reason="Rusak")
    assert r.status_code == 302 and "msg=stock.executed" in r.headers["location"]
    assert db.query(Stock).filter_by(rak_id=r1.id, sku_id=sku.id).first().qty_boxes == 3


def test_batch_page_shows_all_placements_and_exports(client, db):
    make_user(db, "mgr", "manager")
    login(client, "mgr")
    actor, g, a, r1, r2, sku = _setup_tree(db)
    services.execute_masuk(db, actor, sku.id, r1.id, 5, "Awal")
    services.execute_masuk(db, actor, sku.id, r2.id, 2, "Awal")

    r = client.get(f"/manage/stock?sku={sku.id}")
    assert r.status_code == 200
    for text in ("SKU-1", "R1", "R2", ">5<", ">2<",
                 f'name="qty_{sku.id}_{r1.id}"', f'name="qty_{sku.id}_{r2.id}"',
                 f'name="new_rak_{sku.id}"'):
        assert text in r.text

    r = client.get(f"/manage/stock?export=xlsx&sku={sku.id}")
    assert r.status_code == 200 and "spreadsheetml" in r.headers["content-type"]
