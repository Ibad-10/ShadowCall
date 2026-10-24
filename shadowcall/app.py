"""FastAPI app: the ShadowCall web app (landing, sign-in, console), its JSON API, the text-chat
simulator, ElevenLabs endpoints and demo controls."""
from __future__ import annotations

import difflib
import json
import mimetypes
import os
from dataclasses import replace
from pathlib import Path
from urllib.parse import quote, urlparse

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import evalh, gate, synth
from .auth import COOKIE, SESSION_DAYS, Auth, AuthError
from .config import ROOT, _bool, get_settings
from .pipeline import Pipeline
from .store import Store
from .subtasks import SUBTASKS
from .verify import make_claim_checker
from .voice import router as voice_router, transcript_from_post_call

HERE = Path(__file__).resolve().parent
STATIC = HERE / "static"

# Windows reads MIME types from the registry, where .js is often text/plain; browsers then refuse
# to run ES modules. Pin the types the app ships.
for _ext, _type in ((".js", "text/javascript"), (".mjs", "text/javascript"), (".css", "text/css"),
                    (".svg", "image/svg+xml"), (".woff2", "font/woff2"), (".json", "application/json")):
    mimetypes.add_type(_type, _ext)

UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}
# Reachable without a session. /v1 and /webhook are called by ElevenLabs (they check their own secret).
PUBLIC_PREFIXES = ("/static/", "/api/auth/", "/api/public/", "/v1/", "/webhook/")
PUBLIC_PAGES = {"/", "/login", "/signup", "/healthz", "/favicon.svg", "/favicon.ico"}
SERVER_TO_SERVER = ("/v1/", "/webhook/")


def page(name: str) -> HTMLResponse:
    """Templates are UTF-8 on every OS (Windows would otherwise decode them as cp1252)."""
    return HTMLResponse((STATIC / name).read_text(encoding="utf-8"), media_type="text/html; charset=utf-8",
                        headers={"Cache-Control": "no-store"})


class N(BaseModel):
    n: int = 60
    seed: int = 7
    policy: str | None = None


class Pol(BaseModel):
    version: str


class Fix(BaseModel):
    fixed: dict | None = None  # the person's edited reply; omit to approve the engine's repair as is
    by: str = "staff"


class Creds(BaseModel):
    email: str
    password: str
    name: str | None = None


class Refresh(BaseModel):
    version: str = "v2"
    n: int = 120
    seed: int = 21
    confirm_live: bool = False


class Chat(BaseModel):
    card_id: str
    caller_lines: list[str] | None = None


def replay_report(st: "State") -> dict:
    """The Evaluation page's report, built from the real held-out calls (no adapter arms were run)."""
    from statistics import median
    from .costs import pence
    out = {"mode": "replay", "n_heldout": 0, "subtasks": {}}
    for t in SUBTASKS:
        arms = {}
        for lane, arm in (("teacher", "teacher"), ("shadow", "shadow")):
            rows = st.store.query("SELECT * FROM runs WHERE phase='eval' AND split='heldout' AND subtask=? AND lane=?", t, lane)
            red = st.store.query("SELECT passed FROM runs WHERE phase LIKE 'eval%' AND split='heldout' AND subtask=? AND "
                                 "lane=? AND tags LIKE '%red_flag%'", t, lane)
            if not rows:
                arms[arm] = {"available": False}
                continue
            arms[arm] = {"available": True, "n": len(rows), "accuracy": sum(r["passed"] for r in rows) / len(rows),
                         "red_flag_n": len(red),
                         "red_flag_accuracy": (sum(r["passed"] for r in red) / len(red)) if red else None,
                         "pence_per_call": median(pence(st.s, lane, r["tokens_in"], r["tokens_out"]) for r in rows),
                         "latency_ms": median(r["latency_ms"] for r in rows)}
            out["n_heldout"] = max(out["n_heldout"], len(rows))
        arms["adapter_raw"] = arms["adapter_verified"] = {"available": False, "note": "not run in the live test"}
        out["subtasks"][t] = arms
    return out


class State:
    def __init__(self, db_path: str | None = None):
        self.s = get_settings()
        if db_path:
            self.s.db_path = db_path
        elif self.s.replay and not os.environ.get("SHADOWCALL_DB"):
            self.s.db_path = str(ROOT / "data" / "replay.db")  # never overwrite a mock or live database
        self.store = Store(self.s.db_path)
        self.store.execute("CREATE TABLE IF NOT EXISTS cards (id TEXT PRIMARY KEY, body TEXT)")
        self.last_report: dict | None = None
        self.policy = "v1"
        self.cards: dict[str, list] = {}
        self.demo_card: str | None = None
        self.claims = make_claim_checker(self.s)
        self.replay: dict | None = None
        self.clock = None
        if self.s.replay:
            from . import replay
            data = replay.read()
            self.replay = {"label": replay.label(data), "window": data["window"], "live_results": data.get("live_results"),
                           "loaded": replay.load(self.store, self.s, data)}
            self.clock = replay.Clock(self.store, float(os.environ.get("SHADOWCALL_REPLAY_SPEED", "30")))
            self.last_report = replay_report(self)

    def pipeline(self) -> Pipeline:
        return evalh.make_pipeline(self.s, self.store, self.claims)

    def pool(self, policy: str, seed: int, n: int) -> list:
        key = f"{policy}-{seed}-{n}"
        if key not in self.cards:
            self.cards[key] = synth.generate(n, seed, policy)
            with self.store.lock:
                self.store.db.executemany("INSERT OR IGNORE INTO cards (id, body) VALUES (?, ?)",
                                          [(c.id, json.dumps(c.to_dict())) for c in self.cards[key]])
                self.store.db.commit()
        return self.cards[key]

    def find_card(self, card_id: str):
        for pool in self.cards.values():
            for c in pool:
                if c.id == card_id:
                    return c
        base = card_id.split("@", 1)[0]  # voice calls are stored as <card>@<conversation>
        rows = self.store.query("SELECT body FROM cards WHERE id=?", base)
        return synth.Scenario(**json.loads(rows[0]["body"])) if rows else None


def create_app(db_path: str | None = None, auth_enabled: bool | None = None) -> FastAPI:
    app = FastAPI(title="ShadowCall", docs_url=None, redoc_url=None, openapi_url=None)
    st = State(db_path)
    app.state.st = st
    auth = Auth(st.store, enabled=_bool("SHADOWCALL_AUTH", True) if auth_enabled is None else auth_enabled,
                signup_open=_bool("SHADOWCALL_SIGNUP", True))
    auth.seed_demo()
    app.state.auth = auth
    force_secure = os.environ.get("SHADOWCALL_COOKIE_SECURE", "auto").lower()
    app.include_router(voice_router)
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    def is_https(request: Request) -> bool:
        if force_secure in ("1", "true", "yes", "on"):
            return True
        if force_secure in ("0", "false", "no", "off"):
            return False
        proto = request.headers.get("x-forwarded-proto", request.url.scheme)
        return proto.split(",")[0].strip() == "https"

    @app.middleware("http")
    async def guard(request: Request, call_next):
        path, method = request.url.path, request.method
        request.state.session = auth.session(request.cookies.get(COOKIE))
        if method in UNSAFE and not path.startswith(SERVER_TO_SERVER):
            origin = request.headers.get("origin")
            if origin and urlparse(origin).netloc != request.headers.get("host", ""):
                return JSONResponse({"detail": "Cross-site request refused."}, 403)
        public = path in PUBLIC_PAGES or path.startswith(PUBLIC_PREFIXES)
        if auth.enabled and not public:
            sess = request.state.session
            if sess is None:
                if path.startswith("/api/"):
                    return JSONResponse({"detail": "Sign in to continue."}, 401)
                return RedirectResponse("/login?next=" + quote(path), 303)
            if method in UNSAFE and not auth.csrf_ok(sess, request.headers.get("x-csrf-token")):
                return JSONResponse({"detail": "Missing or stale CSRF token. Reload the page."}, 403)
        resp = await call_next(request)
        h = resp.headers
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("Referrer-Policy", "same-origin")
        h.setdefault("X-Frame-Options", "DENY")
        if h.get("content-type", "").startswith("text/html"):
            h.setdefault("Content-Security-Policy",
                         "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                         "img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; "
                         "base-uri 'self'; form-action 'self'")
        return resp

    # -- pages ----------------------------------------------------------------------------------
    @app.get("/", response_class=HTMLResponse)
    def landing():
        return page("landing.html")

    @app.get("/login", response_class=HTMLResponse)
    def login_page(request: Request):
        if request.state.session or not auth.enabled:
            return RedirectResponse("/app", 303)
        return page("login.html")

    @app.get("/signup", response_class=HTMLResponse)
    def signup_page(request: Request):
        if request.state.session or not auth.enabled:
            return RedirectResponse("/app", 303)
        return page("signup.html")

    @app.get("/app", response_class=HTMLResponse)
    @app.get("/app/{rest:path}", response_class=HTMLResponse)
    def console(rest: str = ""):
        return page("app.html")

    @app.get("/favicon.svg", include_in_schema=False)
    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        return FileResponse(STATIC / "favicon.svg", media_type="image/svg+xml")

    @app.get("/healthz")
    def healthz():
        return {"ok": True, "mode": st.s.mode}

    def read_only():
        if st.s.replay:
            raise HTTPException(409, "Replay mode is read-only: it shows the real live run and makes no new calls.")

    # -- auth -----------------------------------------------------------------------------------
    def _set_cookie(resp, request: Request, token: str):
        resp.set_cookie(COOKIE, token, max_age=SESSION_DAYS * 86400, httponly=True, samesite="lax",
                        secure=is_https(request), path="/")

    def _json_only(request: Request):
        # A cross-site HTML form can't send application/json without a CORS preflight.
        if not request.headers.get("content-type", "").startswith("application/json"):
            raise HTTPException(415, "Send JSON.")

    @app.post("/api/auth/login")
    def login(b: Creds, request: Request):
        _json_only(request)
        try:
            token, sess = auth.login(b.email, b.password, request.client.host if request.client else "")
        except AuthError as e:
            raise HTTPException(e.status, e.message)
        resp = JSONResponse({"user": {"email": sess.user.email, "name": sess.user.name}, "csrf": sess.csrf})
        _set_cookie(resp, request, token)
        return resp

    @app.post("/api/auth/signup")
    def signup(b: Creds, request: Request):
        _json_only(request)
        if not auth.signup_open:
            raise HTTPException(403, "Sign-up is closed on this server. Ask the owner for an account.")
        try:
            auth.create_user(b.email, b.password, b.name)
            token, sess = auth.login(b.email, b.password, request.client.host if request.client else "")
        except AuthError as e:
            raise HTTPException(e.status, e.message)
        resp = JSONResponse({"user": {"email": sess.user.email, "name": sess.user.name}, "csrf": sess.csrf}, 201)
        _set_cookie(resp, request, token)
        return resp

    @app.post("/api/auth/logout")
    def logout(request: Request):
        sess = request.state.session
        if sess and not auth.csrf_ok(sess, request.headers.get("x-csrf-token")):
            raise HTTPException(403, "Missing or stale CSRF token.")
        auth.logout(request.cookies.get(COOKIE))
        resp = JSONResponse({"ok": True})
        resp.delete_cookie(COOKIE, path="/")
        return resp

    @app.get("/api/auth/me")
    def me(request: Request):
        sess = request.state.session
        return {"auth": auth.enabled, "signup": auth.signup_open,
                "user": {"email": sess.user.email, "name": sess.user.name, "demo": sess.user.is_demo} if sess else None,
                "csrf": sess.csrf if sess else None}

    @app.get("/api/summary")
    def summary():
        q = st.store.query
        out = {"mode": st.s.mode, "policy": st.policy, "subtasks": {}, "gate_events": q(
            "SELECT * FROM gate_events ORDER BY id DESC LIMIT 12")}
        for t in SUBTASKS:
            g = st.store.gate_state(t)
            kept = q("SELECT COUNT(*) n FROM runs WHERE subtask=? AND kept=1 AND policy_version=?", t, st.policy)[0]["n"]
            corr = q("SELECT status, COUNT(*) n FROM corrections WHERE subtask=? AND policy_version=? GROUP BY status",
                     t, st.policy)
            dis = q("SELECT who_right, COUNT(*) n FROM disagreements WHERE subtask=? AND policy_version=? GROUP BY who_right",
                    t, st.policy)
            held = q("SELECT lane, AVG(passed) acc, COUNT(*) n FROM runs WHERE subtask=? AND phase='eval' AND "
                     "policy_version=? GROUP BY lane", t, st.policy)
            live = q("SELECT lane, served, AVG(passed) acc, COUNT(*) n, AVG(latency_ms) lat FROM runs WHERE subtask=? "
                     "AND phase='live' AND policy_version=? GROUP BY lane, served", t, st.policy)
            out["subtasks"][t] = {"gate": g, "kept": kept, "corrections": corr, "disagreements": dis,
                                  "heldout": held, "live": live}
        # Pence per call. all_frontier: what the four sub-tasks cost on the frontier (mean teacher cost
        # per sub-task). as_served: what live calls actually spent (small model + frontier audits).
        from .costs import pence
        all_frontier = 0.0
        for t in SUBTASKS:
            r = q("SELECT AVG(tokens_in) ti, AVG(tokens_out) tout FROM runs WHERE lane='teacher' AND subtask=?", t)[0]
            if r["ti"] is not None:
                all_frontier += pence(st.s, "teacher", r["ti"], r["tout"])
        spent, calls = 0.0, set()
        for r in q("SELECT scenario_id, lane, tokens_in, tokens_out FROM runs WHERE phase='live' AND "
                   "record='metadata' AND policy_version=?", st.policy):
            calls.add(r["scenario_id"])
            spent += pence(st.s, "teacher" if r["lane"] == "teacher" else "shadow", r["tokens_in"], r["tokens_out"])
        n = max(len(calls), 1)
        out["pence_per_call"] = {"all_frontier": round(all_frontier, 4), "as_served": round(spent / n, 4) if calls else None,
                                 "calls": len(calls), "note": "token prices from env; set them before quoting"}
        if st.replay:
            out["replay"] = replay_summary(out)
            out["pence_per_call"].update(as_served=out["replay"]["pence_served"], all_frontier=out["replay"]["pence_frontier"],
                                         basis="projected from real held-out calls")
        return out

    def replay_summary(sm: dict) -> dict:
        """Cost and speed of one whole call from the real held-out test: every job on the big model,
        against the jobs the gate switched on the small model (plus the audit share on the big one)."""
        from statistics import median
        from .costs import pence
        rep_ = st.last_report or {"subtasks": {}}
        fr = sv = lat_fr = lat_sv = 0.0
        for t, arms in rep_["subtasks"].items():
            a, b = arms["teacher"], arms["shadow"]
            if not a.get("available"):
                continue
            switched = sm["subtasks"][t]["gate"]["state"] == "switched"
            fr += a["pence_per_call"]
            lat_fr += a["latency_ms"]
            sv += (b["pence_per_call"] + st.s.audit_rate * a["pence_per_call"]) if switched else a["pence_per_call"]
            lat_sv += b["latency_ms"] if switched else a["latency_ms"]
        q = st.store.query
        n_rf = q("SELECT COUNT(DISTINCT scenario_id) n FROM runs WHERE phase='eval_redflag'")[0]["n"]
        n_ev = q("SELECT COUNT(DISTINCT scenario_id) n FROM runs WHERE phase='eval'")[0]["n"]
        agree = q("SELECT SUM(CASE WHEN t.passed=s.passed THEN 1 ELSE 0 END) a, COUNT(*) n FROM runs t JOIN runs s ON "
                  "t.scenario_id=s.scenario_id AND t.subtask=s.subtask AND t.phase=s.phase AND s.lane='shadow' "
                  "WHERE t.lane='teacher' AND t.phase='eval'")[0]
        return {"label": st.replay["label"], "window": st.replay["window"], "heldout_calls": n_ev, "redflag_calls": n_rf,
                "pence_frontier": round(fr, 4), "pence_served": round(sv, 4),
                "latency_ms_frontier": round(lat_fr), "latency_ms_served": round(lat_sv),
                "agree": agree["a"] or 0, "pairs": agree["n"],
                "spend_usd": (st.replay.get("live_results") or {}).get("spend_usd_estimate")}

    @app.get("/api/disagreements")
    def disagreements(limit: int = 30):
        rows = st.store.query("SELECT * FROM disagreements ORDER BY id DESC LIMIT ?", limit)
        for r in rows:
            for k in ("teacher", "shadow", "truth", "tags"):
                r[k] = json.loads(r[k]) if r[k] else None
        return rows

    @app.get("/api/corrections")
    def corrections(limit: int = 30):
        return st.store.query("SELECT * FROM corrections ORDER BY id DESC LIMIT ?", limit)

    @app.post("/api/corrections/{cid}/approve")
    def approve_fix(cid: int, b: Fix):
        """Human fix: a person approves (or edits) the deterministic repair. It becomes local gold for
        held-out scoring, the gate and the export below. Mubit has no API that accepts a corrected
        reply, so nothing is sent to Mubit here."""
        rows = st.store.query("SELECT * FROM corrections WHERE id=?", cid)
        if not rows:
            raise HTTPException(404, "no such correction")
        fixed = b.fixed if b.fixed is not None else json.loads(rows[0]["fixed"] or "null")
        if fixed is None:
            raise HTTPException(400, "nothing to approve: send the corrected reply as `fixed`")
        st.store.update("corrections", cid, fixed=fixed, status="human_fixed", source=f"person ({b.by})")
        return st.store.query("SELECT * FROM corrections WHERE id=?", cid)[0]

    @app.get("/api/corrections/export")
    def export_fixes():
        """Corrected pairs as chat-format JSONL rows (instructions, request, corrected reply), for a
        future adapter or another trainer. Only verified or person-approved fixes are exported."""
        from .subtasks import INSTRUCTIONS
        rows = st.store.query("SELECT * FROM corrections WHERE status IN ('kept_correction_turn', "
                              "'kept_verified_resample', 'human_fixed') AND request IS NOT NULL ORDER BY id")
        return [{"subtask": r["subtask"], "policy_version": r["policy_version"], "status": r["status"],
                 "source": r["source"], "messages": [
                     {"role": "system", "content": INSTRUCTIONS[r["subtask"]]},
                     {"role": "user", "content": r["request"]},
                     {"role": "assistant", "content": r["fixed"]}]} for r in rows]

    @app.post("/api/train")
    def train(b: N):
        read_only()
        pol = b.policy or st.policy
        p = st.pipeline()
        cards = [c for c in st.pool(pol, b.seed, b.n) if c.split == "train"]
        for c in cards:
            p.run_call(c, "train")
        return {"trained_calls": len(cards), "policy": pol}

    @app.post("/api/eval")
    def run_eval(b: N):
        read_only()
        pol = b.policy or st.policy
        rep = evalh.run_eval(st.s, st.store, st.pool(pol, b.seed, b.n), st.claims)
        decisions = {}
        for t in SUBTASKS:
            lane = evalh.serving_lane(st.s)
            d = gate.try_promote(st.store, st.s, t, pol, f"{lane}-{pol}-{len(st.store.query('SELECT id FROM gate_events'))}",
                                 lane)
            decisions[t] = d.__dict__
        st.last_report = rep
        return {"report": rep, "gate": decisions}

    @app.post("/api/live")
    def live(b: N):
        read_only()
        pol = b.policy or st.policy
        p = st.pipeline()
        res = []
        for c in st.pool(pol, b.seed, b.n):
            o = p.run_call(c, "live", chain=True)
            res.append({"id": c.id, "subtasks": [(x.subtask, x.served_by, x.passed) for x in o.subtasks]})
        return {"calls": len(res), "sample": res[:5]}

    @app.post("/api/policy")
    def set_policy(b: Pol):
        read_only()
        if b.version not in ("v1", "v2"):
            raise HTTPException(400, "v1 or v2")
        st.policy = b.version
        rolled = {t: gate.check_rollback(st.store, st.s, t, b.version) for t in SUBTASKS}
        return {"policy": st.policy, "rollbacks": rolled}

    @app.post("/api/gate/{subtask}/{action}")
    def gate_action(subtask: str, action: str):
        if subtask not in SUBTASKS or action not in ("rollback", "shadow"):
            raise HTTPException(400, "unknown")
        g = st.store.gate_state(subtask)
        st.store.set_gate(subtask, "rolled_back" if action == "rollback" else "shadow", g["version"], st.policy,
                          "manual " + action)
        return st.store.gate_state(subtask)

    # -- console read APIs ----------------------------------------------------------------------
    @app.get("/api/public/metrics")
    def public_metrics():
        """Aggregate numbers for the landing page. No call content."""
        q = st.store.query
        sm = summary()
        calls = q("SELECT COUNT(DISTINCT scenario_id) n FROM runs")[0]["n"]
        verified = q("SELECT AVG(passed) a FROM runs WHERE lane='teacher'")[0]["a"]
        switched = sum(1 for v in sm["subtasks"].values() if v["gate"]["state"] == "switched")
        return {"mode": st.s.mode, "calls": calls, "switched": switched, "subtasks": len(SUBTASKS),
                "frontier_pass_rate": round(verified, 3) if verified is not None else None,
                "pence_frontier": sm["pence_per_call"]["all_frontier"], "pence_served": sm["pence_per_call"]["as_served"]}

    @app.get("/api/calls")
    def list_calls(limit: int = 50, offset: int = 0, q: str | None = None, phase: str | None = None):
        where, args = [], []
        if q:
            where.append("scenario_id LIKE ?")
            args.append(f"%{q}%")
        if phase:
            where.append("phase = ?")
            args.append(phase)
        w = ("WHERE " + " AND ".join(where)) if where else ""
        rows = st.store.query(
            f"SELECT scenario_id id, MAX(ts) ts, MIN(split) split, MIN(policy_version) policy, "
            f"GROUP_CONCAT(DISTINCT phase) phases, MIN(tags) tags, "
            f"SUM(CASE WHEN lane='teacher' THEN 1 ELSE 0 END) teacher_runs, "
            f"SUM(CASE WHEN lane='teacher' THEN passed ELSE 0 END) teacher_passed, "
            f"SUM(CASE WHEN lane!='teacher' THEN 1 ELSE 0 END) small_runs, "
            f"SUM(CASE WHEN lane!='teacher' THEN passed ELSE 0 END) small_passed, "
            f"SUM(served) served_small, SUM(kept) kept FROM runs {w} GROUP BY scenario_id "
            f"ORDER BY MAX(id) DESC LIMIT ? OFFSET ?", *args, limit, offset)
        total = st.store.query(f"SELECT COUNT(DISTINCT scenario_id) n FROM runs {w}", *args)[0]["n"]
        for r in rows:
            r["tags"] = json.loads(r["tags"]) if r["tags"] else []
            r["phases"] = (r["phases"] or "").split(",")
        return {"total": total, "rows": rows}

    @app.get("/api/feed")
    def feed(after: int = 0, limit: int = 12):
        """Newest calls first, for the console's live feed. `after` is the last run id the page saw."""
        limit = max(1, min(limit, 50))
        if st.clock:
            return replay_feed(after, limit)
        rows = st.store.query(
            "SELECT scenario_id id, MAX(id) cursor, MAX(ts) ts, MIN(split) split, MAX(phase) phase, "
            "SUM(CASE WHEN lane='teacher' THEN 1 ELSE 0 END) frontier_runs, "
            "SUM(CASE WHEN lane='teacher' THEN passed ELSE 0 END) frontier_passed, "
            "SUM(CASE WHEN lane!='teacher' THEN 1 ELSE 0 END) small_runs, "
            "SUM(CASE WHEN lane!='teacher' THEN passed ELSE 0 END) small_passed, "
            "SUM(served) served_small, SUM(kept) kept FROM runs GROUP BY scenario_id HAVING MAX(id) > ? "
            "ORDER BY MAX(id) DESC LIMIT ?", after, limit)
        top = st.store.query("SELECT COALESCE(MAX(id), 0) n FROM runs")[0]["n"]
        return {"cursor": top, "rows": rows}

    def replay_feed(after: int, limit: int):
        """Replay: the real calls come back in their real order, sped up and looping. The cursor counts
        loops so it only goes up, and the page needs nothing special."""
        loop, vt = st.clock.position()
        big = 10 ** 7
        base = loop * big
        since = after - base if after >= base else 0
        rows = st.store.query(
            "SELECT scenario_id id, MAX(id) cursor, MAX(ts) ts, MIN(split) split, MAX(phase) phase, "
            "SUM(CASE WHEN lane='teacher' THEN 1 ELSE 0 END) frontier_runs, "
            "SUM(CASE WHEN lane='teacher' THEN passed ELSE 0 END) frontier_passed, "
            "SUM(CASE WHEN lane!='teacher' THEN 1 ELSE 0 END) small_runs, "
            "SUM(CASE WHEN lane!='teacher' THEN passed ELSE 0 END) small_passed, "
            "SUM(served) served_small, SUM(kept) kept FROM runs WHERE ts <= ? GROUP BY scenario_id HAVING MAX(id) > ? "
            "ORDER BY MAX(id) DESC LIMIT ?", vt, since, limit)
        if not rows and after == 0:  # first look at the very start of a loop: show how the run ended
            rows = st.store.query(
                "SELECT scenario_id id, MAX(id) cursor, MAX(ts) ts, MIN(split) split, MAX(phase) phase, "
                "SUM(CASE WHEN lane='teacher' THEN 1 ELSE 0 END) frontier_runs, "
                "SUM(CASE WHEN lane='teacher' THEN passed ELSE 0 END) frontier_passed, "
                "SUM(CASE WHEN lane!='teacher' THEN 1 ELSE 0 END) small_runs, "
                "SUM(CASE WHEN lane!='teacher' THEN passed ELSE 0 END) small_passed, "
                "SUM(served) served_small, SUM(kept) kept FROM runs GROUP BY scenario_id ORDER BY MAX(id) DESC LIMIT ?", limit)
        top = st.store.query("SELECT COALESCE(MAX(id), 0) n FROM runs WHERE ts <= ?", vt)[0]["n"]
        for r in rows:
            r["cursor"] = base + r["cursor"]
        return {"cursor": base + top, "rows": rows, "replay": True, "replay_time": vt}

    @app.get("/api/calls/{call_id}")
    def call_detail(call_id: str):
        from .subtasks import truth_output
        runs = st.store.query("SELECT * FROM runs WHERE scenario_id=? ORDER BY id", call_id)
        if not runs:
            raise HTTPException(404, "No call with that id.")
        card = st.find_card(call_id)
        subs = {}
        for t in SUBTASKS:
            rs = [r for r in runs if r["subtask"] == t]
            def last(pred):
                c = [r for r in rs if pred(r)]
                return c[-1] if c else None
            teacher = last(lambda r: r["lane"] == "teacher" and r["phase"] not in ("keep", "keep_correction", "correct"))
            small = last(lambda r: r["lane"] != "teacher")
            def view(r):
                if r is None:
                    return None
                return {"lane": r["lane"], "phase": r["phase"], "output": json.loads(r["output"]) if r["output"] else None,
                        "passed": bool(r["passed"]), "wrong": json.loads(r["wrong"] or "[]"), "served": bool(r["served"]),
                        "latency_ms": r["latency_ms"], "request_id": r["request_id"], "record": r["record"],
                        "kept": bool(r["kept"])}
            truth = None
            if card is not None:
                try:
                    truth = truth_output(t, card, None)
                except Exception:  # truth needs upstream for some sub-tasks; leave it out rather than guess
                    truth = None
            subs[t] = {"frontier": view(teacher), "small": view(small), "truth": truth,
                       "corrections": st.store.query("SELECT id, status, source, note FROM corrections WHERE "
                                                     "scenario_id=? AND subtask=? ORDER BY id", call_id, t)}
        r0 = runs[0]
        return {"id": call_id, "split": r0["split"], "policy": r0["policy_version"], "tags": json.loads(r0["tags"] or "[]"),
                "ts": runs[-1]["ts"], "transcript": card.transcript if card else None, "subtasks": subs}

    @app.get("/api/policy")
    def policy_info():
        from .policy.engine import POLICIES
        a, b = POLICIES["v1"].text, POLICIES["v2"].text
        diff = []
        for line in difflib.ndiff(a.splitlines(), b.splitlines()):
            tag = line[:2]
            if tag == "? ":
                continue
            diff.append({"op": {"+ ": "add", "- ": "del"}.get(tag, "same"), "text": line[2:]})
        return {"active": st.policy, "versions": {"v1": a, "v2": b}, "diff": diff}

    @app.post("/api/refresh")
    def fast_refresh(b: Refresh):
        """Policy change, end to end: switch policy (switched sub-tasks roll back), collect examples on
        the new policy, run the held-out eval and let the gate re-promote. In live mode this spends
        money and can push a task past Mubit's 25-example training trigger, so it needs confirm_live."""
        read_only()
        if b.version not in ("v1", "v2"):
            raise HTTPException(400, "v1 or v2")
        if st.s.live and not b.confirm_live:
            raise HTTPException(409, "Live mode: this sends real calls and can start Mubit training. "
                                     "Send confirm_live=true to go ahead.")
        rolled = set_policy(Pol(version=b.version))["rollbacks"]
        trained = train(N(n=b.n, seed=b.seed, policy=b.version))["trained_calls"]
        ev = run_eval(N(n=b.n, seed=b.seed, policy=b.version))
        return {"policy": b.version, "rollbacks": rolled, "trained_calls": trained,
                "gate": {t: {"promote": d["promote"], "reason": d["reason"]} for t, d in ev["gate"].items()}}

    @app.get("/api/eval/report")
    def eval_report():
        return st.last_report or {}

    @app.get("/api/live-results")
    def live_results():
        """Saved results of a live run (scripts_live_run.py report): real Mubit calls, with time and n.
        Shown in every mode, always labelled; never mixed into the mock report."""
        path = Path(os.environ.get("SHADOWCALL_LIVE_RESULTS", str(ROOT / "data" / "live_results.json")))
        if not path.is_file():
            return (st.replay or {}).get("live_results") or {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    @app.get("/api/settings")
    def settings_view(request: Request):
        s_ = st.s
        present = lambda v: bool(v)
        return {
            "mode": s_.mode, "policy": st.policy, "replay": st.replay["label"] if st.replay else None,
            "models": {"frontier": s_.teacher_model, "small": s_.shadow_model, "small_label": s_.shadow_label,
                       "adapter": s_.adapter_model},
            "endpoints": {"frontier": s_.teacher_base_url, "small": s_.shadow_base_url, "adapter": s_.adapter_base_url},
            "keys": {"MUBIT_API_KEY": present(s_.mubit_api_key), "MUBIT_API_KEY_RAW": present(s_.mubit_api_key_raw),
                     "ELEVENLABS_API_KEY": present(os.environ.get("ELEVENLABS_API_KEY")),
                     "SHADOWCALL_ELEVENLABS_SECRET": present(s_.elevenlabs_secret),
                     "BANYAN_API_KEY": present(s_.banyan_api_key)},
            "gate": {"min_heldout": s_.gate_min_heldout, "margin": s_.gate_margin,
                     "rollback_window": s_.gate_rollback_window, "rollback_floor": s_.gate_rollback_floor,
                     "audit_rate": s_.audit_rate},
            "learning": {"verified_keep": s_.verified_keep, "correction_mode": s_.correction_mode,
                         "max_resamples": s_.max_resamples, "keep_cap": s_.keep_cap},
            "prices_pence_per_mtok": {"frontier_in": s_.teacher_price_in, "frontier_out": s_.teacher_price_out,
                                      "small_in": s_.shadow_price_in, "small_out": s_.shadow_price_out},
            "auth": {"enabled": auth.enabled, "signup_open": auth.signup_open, "demo_account": bool(os.environ.get("DEMO_USER"))},
        }

    @app.get("/api/cards")
    def cards(policy: str | None = None, n: int = 12, seed: int = 99):
        return [{"id": c.id, "tags": c.tags, "script": [t["text"] for t in c.transcript if t["role"] == "caller"]}
                for c in st.pool(policy or st.policy, seed, n)]

    @app.post("/api/chat")
    def chat(b: Chat):
        """Text-chat simulator (fallback when voice fails): run a call card, optionally with the
        caller's own words, through both lanes and show what each would do."""
        read_only()
        c = st.find_card(b.card_id)
        if c is None:
            raise HTTPException(404, "card not found; GET /api/cards first")
        if b.caller_lines:
            turns = [c.transcript[0]] + [{"role": "caller", "text": x} for x in b.caller_lines] + [c.transcript[-1]]
            c = replace(c, transcript=turns)
        o = st.pipeline().run_call(c, "live", chain=True)
        return {"card": c.id, "truth": c.truth, "subtasks": [x.__dict__ for x in o.subtasks]}

    @app.post("/api/demo-card/{card_id}")
    def demo_card(card_id: str):
        if st.find_card(card_id) is None:
            raise HTTPException(404, "card not found")
        st.demo_card = card_id
        return {"demo_card": card_id}

    @app.post("/webhook/elevenlabs/post-call")
    def post_call(payload: dict, bg: BackgroundTasks):
        """After a real call, run the sub-tasks on the real transcript against the demo card's truth."""
        if st.s.replay:
            return {"ok": True, "note": "replay mode: webhook ignored, no new calls"}
        conv, turns = transcript_from_post_call(payload)
        c = st.find_card(st.demo_card) if st.demo_card else None
        if c is None:
            return {"ok": True, "note": "no demo card selected; transcript stored only", "turns": len(turns)}
        c = replace(c, transcript=turns or c.transcript, session_id=conv, id=f"{c.id}@{conv}")
        bg.add_task(lambda: st.pipeline().run_call(c, "live", chain=True))
        return {"ok": True, "card": c.id}

    return app


app = create_app()
