from tests.conftest import login, make_user


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_anonymous_redirected_to_login(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"].startswith("/login")


def test_login_success_and_logout(client, db):
    make_user(db, "owner1", "owner")
    r = login(client, "owner1")
    assert r.status_code == 302
    assert client.get("/").status_code == 200
    r = client.post("/logout", data={"csrf_token": client.cookies.get("csrf")},
                    follow_redirects=False)
    assert r.status_code == 302
    assert client.get("/", follow_redirects=False).status_code == 302


def test_login_bad_password_records_failure(client, db):
    make_user(db, "owner1", "owner")
    r = login(client, "owner1", password="wrongpass")
    assert r.status_code == 401
    from app.auth.models import FailedLogin
    assert db.query(FailedLogin).count() == 1


def test_inactive_user_cannot_login(client, db):
    make_user(db, "ghost", "staff", is_active=False)
    assert login(client, "ghost").status_code == 401


def test_staff_forbidden_admin_users(client, db):
    make_user(db, "staff1", "staff")
    login(client, "staff1")
    r = client.get("/admin/users", follow_redirects=False)
    assert r.status_code == 403


def test_manager_cannot_manage_users(client, db):
    # PRD §2: Manager permissions are warehouse.* + admin.audit only.
    make_user(db, "mgr", "manager")
    login(client, "mgr")
    assert client.get("/admin/users", follow_redirects=False).status_code == 403
    csrf = client.cookies.get("csrf")
    r = client.post("/admin/users", data={"csrf_token": csrf, "username": "newown",
        "display_name": "N", "password": "password123", "role": "owner"}, follow_redirects=False)
    assert r.status_code == 403
    from app.auth.models import User
    assert db.query(User).filter_by(username="newown").first() is None


def test_manager_can_view_audit(client, db):
    make_user(db, "mgr", "manager")
    login(client, "mgr")
    assert client.get("/admin/audit").status_code == 200


def test_owner_cannot_deactivate_self(client, db):
    make_user(db, "own", "owner")
    login(client, "own")
    from app.auth.models import User
    u = db.query(User).filter_by(username="own").first()
    r = client.post(f"/admin/users/{u.id}/update", data={
        "csrf_token": client.cookies.get("csrf"), "display_name": "Own",
        "role": "owner", "is_active": "on"}, follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"].endswith("msg=users.denied")


def test_owner_can_create_owner_and_manager_scoped(client, db):
    make_user(db, "own", "owner")
    login(client, "own")
    csrf = client.cookies.get("csrf")
    r = client.post("/admin/users", data={"csrf_token": csrf, "username": "own2",
        "display_name": "Second", "password": "password123", "role": "owner"}, follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"].endswith("msg=users.created")


def test_csrf_required_on_post(client, db):
    make_user(db, "own", "owner")
    client.get("/login")
    r = client.post("/login", data={"username": "own", "password": "password123"}, follow_redirects=False)
    assert r.status_code == 403


def test_change_own_password(client, db):
    make_user(db, "own", "owner")
    login(client, "own")
    r = client.post("/profile/password", data={"csrf_token": client.cookies.get("csrf"),
        "current_password": "password123", "new_password": "newpassword99",
        "confirm_password": "newpassword99"}, follow_redirects=False)
    assert r.status_code == 200
    login(client, "own", password="newpassword99")
    assert client.get("/").status_code == 200


def test_bootstrap_refuses_when_owner_exists(client, db):
    make_user(db, "own", "owner")
    from app.core.bootstrap import owner_exists
    assert owner_exists(db) is True


def test_admin_reset_forces_password_change(client, db):
    make_user(db, "own", "owner")
    make_user(db, "mgr", "manager")
    login(client, "own")
    from app.auth.models import User
    target = db.query(User).filter_by(username="mgr").first()
    r = client.post(f"/admin/users/{target.id}/reset-password", data={
        "csrf_token": client.cookies.get("csrf"), "new_password": "temppass99"},
        follow_redirects=False)
    assert r.status_code == 302
    db.expire_all()

    login(client, "mgr", password="temppass99")
    # Everything except profile/logout is redirected until the password changes.
    r = client.get("/w", follow_redirects=False)
    assert r.status_code == 302 and "/profile" in r.headers["location"]
    r = client.post("/profile/password", data={
        "csrf_token": client.cookies.get("csrf"),
        "current_password": "temppass99", "new_password": "permanent99",
        "confirm_password": "permanent99"})
    assert r.status_code == 200
    assert client.get("/w").status_code == 200
