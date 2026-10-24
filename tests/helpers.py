"""Test helpers: a TestClient that is signed in, with the CSRF header set, like the browser app."""
from fastapi.testclient import TestClient

from shadowcall.app import create_app

EMAIL, PASSWORD = "tester@example.com", "correct horse battery"


def signed_in(db_path: str, **kw) -> TestClient:
    app = create_app(db_path, **kw)
    c = TestClient(app)
    app.state.auth.create_user(EMAIL, PASSWORD, "Tester")
    r = c.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert r.status_code == 200, r.text
    c.headers["X-CSRF-Token"] = c.get("/api/auth/me").json()["csrf"]
    return c
