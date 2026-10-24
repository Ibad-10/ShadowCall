"""Pence per call. Prices are per million tokens and come from env (set them from the
provider price pages before quoting any number)."""
from __future__ import annotations

from .config import Settings


def pence(s: Settings, lane: str, tokens_in: int, tokens_out: int) -> float:
    if lane == "teacher":
        return (tokens_in * s.teacher_price_in + tokens_out * s.teacher_price_out) / 1_000_000
    return (tokens_in * s.shadow_price_in + tokens_out * s.shadow_price_out) / 1_000_000
