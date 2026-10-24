"""ElevenLabs Agents "custom LLM" endpoint. ElevenLabs calls POST /v1/chat/completions with an
OpenAI-style body and expects SSE back. We forward the company's live conversation to its frontier
model THROUGH Mubit (unchanged behaviour = shadow mode), stripping ElevenLabs-only fields, and tag
the call with a session id so Mubit groups it. Sub-tasks run after the call, off the voice path."""
from __future__ import annotations

import json
import os
import time
import uuid

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from .config import get_settings

router = APIRouter()
BUFFER = os.environ.get("SHADOWCALL_BUFFER_WORDS", "")  # e.g. "One moment... " (ElevenLabs buffer-word trick)


def clean_body(body: dict, model: str) -> tuple[dict, str]:
    extra = body.pop("elevenlabs_extra_body", None) or {}
    if "user_id" in body:
        body["user"] = body.pop("user_id")
    session = str(extra.get("conversation_id") or extra.get("UUID") or body.get("user") or uuid.uuid4())
    body["model"] = model
    body["stream"] = True
    body.setdefault("metadata", {})["session_id"] = session
    return body, session


def _chunk(text: str, model: str) -> str:
    return "data: " + json.dumps({"id": "chatcmpl-mock", "object": "chat.completion.chunk", "created": int(time.time()),
                                  "model": model, "choices": [{"index": 0, "delta": {"content": text},
                                                               "finish_reason": None}]}) + "\n\n"


@router.post("/v1/chat/completions")
async def chat_completions(request: Request):
    s = get_settings()
    if s.elevenlabs_secret:
        auth = request.headers.get("authorization", "")
        if auth != f"Bearer {s.elevenlabs_secret}":
            raise HTTPException(401, "bad secret")
    body, session = clean_body(await request.json(), s.teacher_model)

    if not s.live:
        async def mock_stream():
            if BUFFER:
                yield _chunk(BUFFER, "mock")
            for w in ["Thanks, ", "let me ", "check the diary ", "for you."]:
                yield _chunk(w, "mock")
            yield "data: [DONE]\n\n"
        return StreamingResponse(mock_stream(), media_type="text/event-stream")

    if not s.mubit_api_key:
        raise HTTPException(500, "MUBIT_API_KEY not set")

    async def relay():
        if BUFFER:
            yield _chunk(BUFFER, s.teacher_model).encode()
        async with httpx.AsyncClient(timeout=60) as client:
            async with client.stream("POST", f"{s.teacher_base_url.rstrip('/')}/chat/completions", json=body,
                                     headers={"Authorization": f"Bearer {s.mubit_api_key}"}) as r:
                async for chunk in r.aiter_bytes():
                    yield chunk
    return StreamingResponse(relay(), media_type="text/event-stream")


def transcript_from_post_call(payload: dict) -> tuple[str, list]:
    """ElevenLabs post-call webhook -> (conversation_id, [{role, text}])."""
    data = payload.get("data", payload)
    turns = []
    for t in data.get("transcript", []) or []:
        msg = t.get("message")
        if msg:
            turns.append({"role": "agent" if t.get("role") == "agent" else "caller", "text": msg})
    return str(data.get("conversation_id", uuid.uuid4())), turns
