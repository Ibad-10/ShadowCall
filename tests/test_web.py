"""The web app: accounts, sessions, CSRF, pages, encoding and the console APIs."""
import builtins
import io
import pathlib
import re

import pytest
from fastapi.testclient import TestClient

from helpers import EMAIL, PASSWORD, signed_in
from shadowcall.app import STATIC, create_app

PAGES = ["landing.html", "login.html", "signup.html", "app.html"]
MOJIBAKE = re.compile("Â|â€|â†|Ã")


@pytest.fixture
def app(tmp_path):
    return create_app(str(tmp_path / "t.db"))


# -- auth ------------------------------------------------------------------------------------------
def test_signup_login_logout_cycle(app):
    c = TestClient(app)
    r = c.post("/api/auth/signup", json={"email": "New@Example.com", "password": "a long passphrase", "name": "N"})
    assert r.status_code == 201 and r.json()["user"]["email"] == "new@example.com"
    assert "httponly" in r.headers["set-cookie"].lower() and "samesite=lax" in r.headers["set-cookie"].lower()
    me = c.get("/api/auth/me").json()
    assert me["user"]["email"] == "new@example.com" and me["csrf"]
    assert c.get("/api/summary").status_code == 200
    assert c.post("/api/auth/logout", headers={"X-CSRF-Token": me["csrf"]}).status_code == 200
    assert c.get("/api/summary").status_code == 401
    assert c.post("/api/auth/login", json={"email": "new@example.com", "password": "a long passphrase"}).status_code == 200


def test_wrong_password_and_unknown_user_are_401_with_same_message(app):
    app.state.auth.create_user(EMAIL, PASSWORD)
    c = TestClient(app)
    a = c.post("/api/auth/login", json={"email": EMAIL, "password": "not the password"})
    b = c.post("/api/auth/login", json={"email": "nobody@example.com", "password": "whatever123"})
    assert a.status_code == b.status_code == 401 and a.json() == b.json()


def test_api_and_console_need_a_session(app):
    c = TestClient(app)
    assert c.get("/api/summary").status_code == 401
    r = c.get("/app/calls", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login?next=/app/calls"
    for public in ("/", "/login", "/signup", "/healthz", "/api/public/metrics", "/favicon.svg", "/static/css/base.css"):
        assert c.get(public).status_code == 200, public


def test_writes_need_csrf_and_same_origin(tmp_path):
    c = signed_in(str(tmp_path / "t.db"))
    token = c.headers.pop("X-CSRF-Token")
    assert c.post("/api/policy", json={"version": "v2"}).status_code == 403
    assert c.post("/api/policy", json={"version": "v2"}, headers={"X-CSRF-Token": "wrong"}).status_code == 403
    assert c.post("/api/policy", json={"version": "v2"}, headers={"X-CSRF-Token": token,
                                                                  "Origin": "https://evil.example"}).status_code == 403
    assert c.post("/api/policy", json={"version": "v2"}, headers={"X-CSRF-Token": token}).status_code == 200


def test_login_rejects_form_posts(app):
    app.state.auth.create_user(EMAIL, PASSWORD)
    r = TestClient(app).post("/api/auth/login", data={"email": EMAIL, "password": PASSWORD})
    assert r.status_code in (415, 422)


def test_passwords_are_argon2_hashes(app):
    app.state.auth.create_user(EMAIL, PASSWORD)
    row = app.state.st.store.query("SELECT pw_hash FROM users WHERE email=?", EMAIL)[0]
    assert row["pw_hash"].startswith("$argon2id$") and PASSWORD not in row["pw_hash"]
    tok = app.state.st.store.query("SELECT token_hash FROM sessions")
    assert tok == []  # no sessions until someone signs in


def test_session_token_stored_hashed(app):
    app.state.auth.create_user(EMAIL, PASSWORD)
    c = TestClient(app)
    c.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
    cookie = c.cookies.get("sc_session")
    stored = [r["token_hash"] for r in app.state.st.store.query("SELECT token_hash FROM sessions")]
    assert cookie and cookie not in stored and len(stored[0]) == 64


def test_short_password_and_bad_email_refused(app):
    c = TestClient(app)
    assert c.post("/api/auth/signup", json={"email": "a@b.co", "password": "short"}).status_code == 400
    assert c.post("/api/auth/signup", json={"email": "not-an-email", "password": "long enough pass"}).status_code == 400


def test_duplicate_signup_is_409(app):
    c = TestClient(app)
    body = {"email": "dup@example.com", "password": "long enough pass"}
    assert c.post("/api/auth/signup", json=body).status_code == 201
    assert TestClient(app).post("/api/auth/signup", json=body).status_code == 409


def test_demo_account_comes_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DEMO_USER", "demo@shadowcall.test")
    monkeypatch.setenv("DEMO_PASSWORD", "demo-pass-from-env")
    app = create_app(str(tmp_path / "t.db"))
    c = TestClient(app)
    r = c.post("/api/auth/login", json={"email": "demo@shadowcall.test", "password": "demo-pass-from-env"})
    assert r.status_code == 200 and c.get("/api/auth/me").json()["user"]["demo"] is True
    # changing the env password rotates the stored hash on the next start
    monkeypatch.setenv("DEMO_PASSWORD", "rotated-pass-123")
    app2 = create_app(str(tmp_path / "t.db"))
    c2 = TestClient(app2)
    assert c2.post("/api/auth/login", json={"email": "demo@shadowcall.test", "password": "demo-pass-from-env"}).status_code == 401
    assert c2.post("/api/auth/login", json={"email": "demo@shadowcall.test", "password": "rotated-pass-123"}).status_code == 200


def test_no_demo_account_without_env(tmp_path, monkeypatch):
    monkeypatch.delenv("DEMO_USER", raising=False)
    monkeypatch.delenv("DEMO_PASSWORD", raising=False)
    app = create_app(str(tmp_path / "t.db"))
    assert app.state.st.store.query("SELECT COUNT(*) n FROM users")[0]["n"] == 0


def test_closed_signup(tmp_path, monkeypatch):
    monkeypatch.setenv("SHADOWCALL_SIGNUP", "false")
    c = TestClient(create_app(str(tmp_path / "t.db")))
    assert c.post("/api/auth/signup", json={"email": "x@example.com", "password": "long enough pass"}).status_code == 403


def test_login_throttle(app):
    app.state.auth.create_user(EMAIL, PASSWORD)
    c = TestClient(app)
    codes = [c.post("/api/auth/login", json={"email": EMAIL, "password": "nope nope nope"}).status_code for _ in range(9)]
    assert codes[:8] == [401] * 8 and codes[8] == 429
    assert c.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD}).status_code == 429


def test_auth_off_keeps_old_behaviour(tmp_path):
    c = TestClient(create_app(str(tmp_path / "t.db"), auth_enabled=False))
    assert c.get("/api/summary").status_code == 200
    assert c.post("/api/policy", json={"version": "v2"}).status_code == 200
    assert c.get("/login", follow_redirects=False).headers["location"] == "/app"


def test_elevenlabs_routes_skip_session_auth(app):
    c = TestClient(app)
    r = c.post("/webhook/elevenlabs/post-call", json={"data": {"conversation_id": "c1", "transcript": []}})
    assert r.status_code != 401


def test_cookie_secure_behind_https_proxy(app):
    app.state.auth.create_user(EMAIL, PASSWORD)
    c = TestClient(app)
    plain = c.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
    proxied = c.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD}, headers={"x-forwarded-proto": "https"})
    assert "secure" not in plain.headers["set-cookie"].lower()
    assert "secure" in proxied.headers["set-cookie"].lower()


# -- pages, encoding, headers ---------------------------------------------------------------------
@pytest.mark.parametrize("path", ["/", "/login", "/signup"])
def test_pages_are_utf8_and_secured(app, path):
    r = TestClient(app).get(path)
    assert r.headers["content-type"] == "text/html; charset=utf-8"
    assert '<meta charset="utf-8">' in r.text[:200]
    assert not MOJIBAKE.search(r.text)
    assert "script-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-frame-options"] == "DENY" and r.headers["x-content-type-options"] == "nosniff"


def test_console_page_is_utf8(tmp_path):
    r = signed_in(str(tmp_path / "t.db")).get("/app/policy")
    assert r.headers["content-type"] == "text/html; charset=utf-8" and '<meta charset="utf-8">' in r.text


@pytest.mark.parametrize("name", PAGES)
def test_templates_have_charset_and_no_inline_script(name):
    html = (STATIC / name).read_text(encoding="utf-8")
    assert html.lower().startswith("<!doctype html>")
    assert '<meta charset="utf-8">' in html[:120]
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html), "inline scripts break the CSP"
    assert not re.search(r"\son[a-z]+=\"", html), "inline handlers break the CSP"


def test_static_types_are_pinned(app):
    c = TestClient(app)
    assert c.get("/static/js/app.js").headers["content-type"].startswith("text/javascript")
    assert c.get("/static/css/app.css").headers["content-type"].startswith("text/css")
    assert c.get("/static/fonts/plex-sans.woff2").headers["content-type"] == "font/woff2"


def test_pages_survive_a_cp1252_default(monkeypatch, tmp_path):
    """Windows' default text encoding is cp1252. Simulate it: every read_text/open that forgets
    encoding= decodes as cp1252. Pages and policy text must still come out right."""
    real_read_text, real_open = pathlib.Path.read_text, builtins.open

    def read_text(self, encoding=None, errors=None, **kw):
        return real_read_text(self, encoding=encoding or "cp1252", errors=errors or "replace")

    def fake_open(file, mode="r", buffering=-1, encoding=None, *a, **kw):
        if "b" not in mode and encoding is None:
            encoding = "cp1252"
            kw.setdefault("errors", "replace")
        return real_open(file, mode, buffering, encoding, *a, **kw)

    monkeypatch.setattr(pathlib.Path, "read_text", read_text)
    monkeypatch.setattr(builtins, "open", fake_open)
    import importlib
    from shadowcall.policy import engine
    importlib.reload(engine)
    try:
        assert "£" in engine.POLICIES["v2"].text and not MOJIBAKE.search(engine.POLICIES["v2"].text)
        c = TestClient(create_app(str(tmp_path / "t.db")))
        for path in ("/", "/login"):
            assert not MOJIBAKE.search(c.get(path).text)
    finally:
        monkeypatch.undo()
        importlib.reload(engine)


# -- console APIs ---------------------------------------------------------------------------------
@pytest.fixture
def busy(tmp_path):
    c = signed_in(str(tmp_path / "t.db"))
    c.post("/api/train", json={"n": 60})
    c.post("/api/eval", json={"n": 60})
    c.post("/api/live", json={"n": 6, "seed": 3})
    return c


def test_calls_list_and_detail(busy):
    data = busy.get("/api/calls?limit=5").json()
    assert data["total"] > 5 and len(data["rows"]) == 5
    row = data["rows"][0]
    assert {"id", "split", "teacher_runs", "small_runs", "phases", "tags"} <= set(row)
    d = busy.get(f"/api/calls/{row['id']}").json()
    assert d["transcript"] and set(d["subtasks"]) == {"extract", "policy_check", "form_fill", "summary"}
    some = next(v for v in d["subtasks"].values() if v["frontier"])
    assert {"output", "passed", "wrong", "served"} <= set(some["frontier"])
    assert busy.get("/api/calls/nope").status_code == 404
    assert busy.get("/api/calls?phase=live").json()["total"] >= 1
    assert busy.get(f"/api/calls?q={row['id']}").json()["total"] == 1


def test_policy_diff_and_eval_report(busy):
    p = busy.get("/api/policy").json()
    assert p["active"] == "v1" and {"add", "del"} <= {d["op"] for d in p["diff"]}
    rep = busy.get("/api/eval/report").json()
    assert rep["subtasks"]["extract"]["teacher"]["accuracy"] is not None


def test_fast_refresh_in_mock_mode(busy):
    r = busy.post("/api/refresh", json={"version": "v2", "n": 60}).json()
    assert r["policy"] == "v2" and r["trained_calls"] > 0 and set(r["gate"]) == {"extract", "policy_check", "form_fill", "summary"}
    assert busy.get("/api/policy").json()["active"] == "v2"


def test_settings_show_presence_never_values(tmp_path, monkeypatch):
    secret = "elevenlabs-test-value-should-not-leak"
    monkeypatch.setenv("ELEVENLABS_API_KEY", secret)
    c = signed_in(str(tmp_path / "t.db"))
    r = c.get("/api/settings")
    assert r.json()["keys"]["ELEVENLABS_API_KEY"] is True
    assert secret not in r.text


def test_public_metrics_have_no_call_content(busy):
    m = TestClient(busy.app).get("/api/public/metrics").json()
    assert set(m) == {"mode", "calls", "switched", "subtasks", "frontier_pass_rate", "pence_frontier", "pence_served"}


def test_feed_returns_newest_calls_and_a_cursor(tmp_path):
    c = signed_in(tmp_path / "f.db")
    empty = c.get("/api/feed").json()
    assert empty == {"cursor": 0, "rows": []}
    assert c.post("/api/train", json={"n": 6, "seed": 3}).status_code == 200
    first = c.get("/api/feed?limit=3").json()
    assert first["cursor"] > 0 and 0 < len(first["rows"]) <= 3
    r = first["rows"][0]
    assert {"id", "cursor", "ts", "frontier_runs", "frontier_passed", "small_runs", "small_passed", "kept"} <= set(r)
    assert [x["cursor"] for x in first["rows"]] == sorted((x["cursor"] for x in first["rows"]), reverse=True)
    assert c.get(f"/api/feed?after={first['cursor']}").json()["rows"] == []


def test_feed_needs_sign_in(tmp_path):
    from fastapi.testclient import TestClient
    from shadowcall.app import create_app
    anon = TestClient(create_app(str(tmp_path / "a.db")))
    assert anon.get("/api/feed").status_code == 401


def test_console_guide_route_serves_the_app_shell(tmp_path):
    c = signed_in(tmp_path / "g.db")
    r = c.get("/app/guide")
    assert r.status_code == 200 and r.headers["content-type"] == "text/html; charset=utf-8"
    assert 'data-route="guide"' in r.text and "data-tour-start" in r.text


def test_landing_explains_the_idea_in_plain_words(tmp_path):
    c = TestClient(create_app(str(tmp_path / "l.db")))
    r = c.get("/")
    assert r.status_code == 200 and "charset=utf-8" in r.headers["content-type"]
    html = r.text
    for bit in ("data-demo", "data-flow-root", 'id="faq"', "Six steps on every call", "data-live-label"):
        assert bit in html
    assert not re.search(r"<script(?![^>]*\bsrc=)", html), "no inline scripts"
    assert not re.search(r"\son[a-z]+=", html), "no inline handlers"


def test_guide_module_and_styles_are_served(tmp_path):
    c = TestClient(create_app(str(tmp_path / "g.db")))
    js = c.get("/static/js/guide.js")
    assert js.status_code == 200 and "startTour" in js.text and "prefers-reduced-motion" in js.text
    css = c.get("/static/css/console-guide.css")
    assert css.status_code == 200 and ".switch" in css.text
