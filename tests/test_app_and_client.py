import json
import re
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from shadowcall.app import create_app
from shadowcall.llm import Call, MubitClient
from shadowcall.voice import clean_body, transcript_from_post_call

ROOT = Path(__file__).resolve().parent.parent


def client(tmp_path):
    from helpers import signed_in
    return signed_in(str(tmp_path / "t.db"))


def test_full_demo_flow(tmp_path):
    c = client(tmp_path)
    assert c.post("/api/train", json={"n": 120}).status_code == 200
    r = c.post("/api/eval", json={"n": 120}).json()
    assert set(r["gate"]) == {"extract", "policy_check", "form_fill", "summary"}
    assert c.post("/api/live", json={"n": 20, "seed": 11}).status_code == 200
    s = c.get("/api/summary").json()
    assert s["mode"] == "mock" and s["pence_per_call"]["calls"] > 0
    p = c.post("/api/policy", json={"version": "v2"}).json()
    switched_before = [t for t, v in s["subtasks"].items() if v["gate"]["state"] == "switched"]
    for t in switched_before:
        assert p["rollbacks"][t]
    assert c.get("/").status_code == 200
    assert isinstance(c.get("/api/disagreements").json(), list)


def test_text_chat_simulator(tmp_path):
    c = client(tmp_path)
    cards = c.get("/api/cards").json()
    r = c.post("/api/chat", json={"card_id": cards[0]["id"]}).json()
    assert len(r["subtasks"]) == 4


def test_elevenlabs_sse_mock(tmp_path):
    c = client(tmp_path)
    r = c.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "hi"}], "stream": True,
                                             "user_id": "u1", "elevenlabs_extra_body": {"conversation_id": "conv1"}})
    assert r.headers["content-type"].startswith("text/event-stream")
    assert r.text.strip().endswith("data: [DONE]")


def test_clean_body_strips_elevenlabs_fields():
    b, sess = clean_body({"messages": [], "user_id": "u", "elevenlabs_extra_body": {"conversation_id": "c9"}}, "m")
    assert "elevenlabs_extra_body" not in b and b["user"] == "u" and sess == "c9"
    assert b["metadata"]["session_id"] == "c9" and b["stream"] is True


def test_post_call_transcript_parse():
    conv, turns = transcript_from_post_call({"data": {"conversation_id": "x", "transcript": [
        {"role": "agent", "message": "Hello"}, {"role": "user", "message": "Book me in"}]}})
    assert conv == "x" and turns[1] == {"role": "caller", "text": "Book me in"}


def test_mubit_client_sends_key_headers_and_session():
    seen = {}

    def handler(req: httpx.Request):
        seen["url"] = str(req.url)
        seen["auth"] = req.headers["authorization"]
        seen["record"] = req.headers["x-middleware-record"]
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, headers={"x-middleware-request-id": "mreq_" + "0" * 32},
                              json={"choices": [{"message": {"content": "{}"}}], "usage": {"prompt_tokens": 5, "completion_tokens": 1}})

    m = MubitClient("https://api.mubit.ai/openai/v1", "gpt-6-luna", "test-key", transport=httpx.MockTransport(handler))
    r = m.complete(Call("teacher", "extract", "sys", "user", session_id="call-1", record="metadata"))
    assert seen["url"] == "https://api.mubit.ai/openai/v1/chat/completions"
    assert seen["auth"] == "Bearer test-key" and seen["record"] == "metadata"
    assert seen["body"]["metadata"] == {"session_id": "call-1"}
    assert r.request_id.startswith("mreq_") and r.tokens_in == 5


def test_mubit_client_requires_key():
    import pytest
    with pytest.raises(RuntimeError):
        MubitClient("https://api.mubit.ai/openai/v1", "m", None)


def test_no_hardcoded_keys():
    """Pure Python (no grep), so it runs the same on Windows. Scans source, docs and config."""
    pat = re.compile(r"(sk-[A-Za-z0-9]{16,}|mbt_[A-Za-z0-9]{8,})")
    skip = {".venv", "__pycache__", ".pytest_cache", ".git", "node_modules", "data"}
    text = {".py", ".md", ".html", ".js", ".css", ".txt", ".toml", ".yaml", ".yml", ".json", ".example", ".cfg", ""}
    hits = []
    for f in ROOT.rglob("*"):
        if f.is_dir() or skip & set(f.relative_to(ROOT).parts) or f.suffix not in text:
            continue
        for n, line in enumerate(f.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            if pat.search(line):
                hits.append(f"{f.relative_to(ROOT)}:{n}")
    assert hits == []


def test_client_retries_429_omits_temperature_and_sends_extra():
    import json as _json
    import httpx
    from shadowcall.llm import Call, MubitClient
    seen, waits = [], []

    def handler(req):
        seen.append(_json.loads(req.content))
        if len(seen) == 1:
            return httpx.Response(429, headers={"retry-after": "1"}, json={"error": {"code": "starter_credit_busy"}})
        return httpx.Response(200, headers={"x-middleware-request-id": "mreq_x"},
                              json={"choices": [{"message": {"content": "{}"}}], "usage": {"prompt_tokens": 3, "completion_tokens": 1}})

    c = MubitClient("https://example.test/v1", "m", "k", transport=httpx.MockTransport(handler),
                    extra={"reasoning_effort": "low"}, send_temperature=False, sleep=waits.append)
    r = c.complete(Call(lane="teacher", subtask="extract", system="s", user="u", session_id="sess", temperature=0.7))
    assert r.request_id == "mreq_x" and len(seen) == 2 and waits
    assert "temperature" not in seen[1] and seen[1]["reasoning_effort"] == "low"
    assert seen[1]["metadata"]["session_id"] == "sess"
