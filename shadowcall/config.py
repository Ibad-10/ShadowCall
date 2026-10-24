"""All settings come from environment variables. Never hardcode keys."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _json(name: str, default: dict) -> dict:
    import json
    v = os.environ.get(name)
    return json.loads(v) if v else dict(default)


def _bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    # "mock" runs fully offline. "live" calls Mubit's gateway.
    mode: str = field(default_factory=lambda: os.environ.get("SHADOWCALL_MODE", "mock"))
    mubit_api_key: str | None = field(default_factory=lambda: os.environ.get("MUBIT_API_KEY"))
    # Second Mubit project for the "learning off" arm: fed every frontier reply, unverified.
    mubit_api_key_raw: str | None = field(default_factory=lambda: os.environ.get("MUBIT_API_KEY_RAW"))
    # Frontier ("teacher", the company's existing model) via Mubit's OpenAI route.
    teacher_base_url: str = field(default_factory=lambda: os.environ.get(
        "MUBIT_TEACHER_BASE_URL", "https://api.mubit.ai/openai/v1"))
    teacher_model: str = field(default_factory=lambda: os.environ.get("TEACHER_MODEL", "gpt-6-sol"))
    # Shadow lane: an open model, still through Mubit (compat route), e.g. groq/together.
    shadow_base_url: str = field(default_factory=lambda: os.environ.get(
        "MUBIT_SHADOW_BASE_URL", "https://api.mubit.ai/compat/groq/v1"))
    shadow_model: str = field(default_factory=lambda: os.environ.get("SHADOW_MODEL", "openai/gpt-oss-20b"))
    # Extra JSON body per lane (e.g. reasoning effort). Not part of Mubit's task identity.
    teacher_extra: dict = field(default_factory=lambda: _json("TEACHER_EXTRA_BODY", {"reasoning_effort": "low"}))
    shadow_extra: dict = field(default_factory=lambda: _json("SHADOW_EXTRA_BODY", {"reasoning_effort": "low"}))
    # OpenAI reasoning models reject non-default temperature; resamples then vary by seed only.
    teacher_send_temperature: bool = field(default_factory=lambda: _bool("TEACHER_SEND_TEMPERATURE", False))
    shadow_send_temperature: bool = field(default_factory=lambda: _bool("SHADOW_SEND_TEMPERATURE", True))
    # OpenAI rejects `metadata` unless `store` is on, and Groq rejects it outright, so both lanes omit it by default. Mubit then
    # derives the session from instructions + first user message, i.e. one session per card per sub-task.
    teacher_send_session: bool = field(default_factory=lambda: _bool("TEACHER_SEND_SESSION_METADATA", False))
    shadow_send_session: bool = field(default_factory=lambda: _bool("SHADOW_SEND_SESSION_METADATA", False))
    # Teacher resamples for corrections. Reasoning models ignore temperature, so a resample asks the
    # frontier to think harder instead (reasoning effort isn't part of Mubit's task identity).
    teacher_resample_efforts: list = field(default_factory=lambda: os.environ.get(
        "TEACHER_RESAMPLE_EFFORTS", "medium,high,high").split(","))
    max_completion_tokens: int = field(default_factory=lambda: int(os.environ.get("SHADOWCALL_MAX_TOKENS", "1500")))
    # Label shown when the shadow lane is a closed starter model standing in for an open one.
    shadow_label: str = field(default_factory=lambda: os.environ.get("SHADOW_LABEL", "open model (gpt-oss-20b, Groq via Mubit)"))
    # Optional: if Mubit staff expose adapter serving, put the base URL/model/header here.
    adapter_base_url: str | None = field(default_factory=lambda: os.environ.get("MUBIT_ADAPTER_BASE_URL"))
    adapter_model: str | None = field(default_factory=lambda: os.environ.get("MUBIT_ADAPTER_MODEL"))
    # Banyan Sapling verifier endpoint (self-hosted or Mubit-hosted). Optional.
    banyan_api_url: str | None = field(default_factory=lambda: os.environ.get("BANYAN_API_URL"))
    banyan_api_key: str | None = field(default_factory=lambda: os.environ.get("BANYAN_API_KEY"))
    # Keep only verified teacher replies as Mubit kept examples (probe, then replay).
    verified_keep: bool = field(default_factory=lambda: _bool("SHADOWCALL_VERIFIED_KEEP", True))
    # Corrections. "turn": when a probe fails, show the frontier its own reply plus the verifier's
    # findings (the policy engine's or call card's values) in a second user turn of the same task,
    # verify the answer, and keep that correction conversation. "off": skip straight to resamples.
    correction_mode: str = field(default_factory=lambda: os.environ.get("SHADOWCALL_CORRECTION", "turn"))
    # Plain resamples after a failed correction turn. Live runs showed 0 of 27 resamples fixing
    # anything (the frontier repeats itself), so the default is none.
    max_resamples: int = field(default_factory=lambda: int(os.environ.get("SHADOWCALL_MAX_RESAMPLES", "0")))
    # Safety cap: at most this many record=full keeps per sub-task in this database (0 = no cap).
    # Mubit starts training by itself at 25 kept examples, so live tests set a small cap.
    keep_cap: int = field(default_factory=lambda: int(os.environ.get("SHADOWCALL_KEEP_CAP", "0")))
    db_path: str = field(default_factory=lambda: os.environ.get("SHADOWCALL_DB", str(ROOT / "data" / "shadowcall.db")))
    # Promotion gate thresholds (held-out, verifier-scored).
    gate_min_heldout: int = field(default_factory=lambda: int(os.environ.get("GATE_MIN_HELDOUT", "20")))
    gate_margin: float = field(default_factory=lambda: float(os.environ.get("GATE_MARGIN", "0.0")))
    gate_rollback_window: int = field(default_factory=lambda: int(os.environ.get("GATE_ROLLBACK_WINDOW", "10")))
    gate_rollback_floor: float = field(default_factory=lambda: float(os.environ.get("GATE_ROLLBACK_FLOOR", "0.8")))
    # Prices in pence per 1M tokens (input, output). Defaults: gpt-6-sol $2/$10 (OpenAI pricing page),
    # gpt-oss-20b $0.075/$0.30 (Groq models page), both read 24 Oct 2026, at an assumed 75p per US$.
    teacher_price_in: float = field(default_factory=lambda: float(os.environ.get("TEACHER_PENCE_PER_MTOK_IN", "150")))
    teacher_price_out: float = field(default_factory=lambda: float(os.environ.get("TEACHER_PENCE_PER_MTOK_OUT", "750")))
    shadow_price_in: float = field(default_factory=lambda: float(os.environ.get("SHADOW_PENCE_PER_MTOK_IN", "5.6")))
    shadow_price_out: float = field(default_factory=lambda: float(os.environ.get("SHADOW_PENCE_PER_MTOK_OUT", "22.5")))
    # After a sub-task is switched, the frontier still answers this share of calls as an audit.
    audit_rate: float = field(default_factory=lambda: float(os.environ.get("SHADOWCALL_AUDIT_RATE", "0.2")))
    elevenlabs_secret: str | None = field(default_factory=lambda: os.environ.get("SHADOWCALL_ELEVENLABS_SECRET"))

    @property
    def live(self) -> bool:
        return self.mode == "live"

    @property
    def replay(self) -> bool:
        """Replay: show the recorded live run from data/live_replay.json. Offline, read-only, no keys."""
        return self.mode == "replay"


def get_settings() -> Settings:
    return Settings()
