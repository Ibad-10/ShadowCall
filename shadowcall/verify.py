"""Verifiers. The policy engine and the scenario truth are the authority. Banyan Sapling
(optional) checks free-text claims in the summary against the evidence; without it, a strict
rule-based claim check runs instead."""
from __future__ import annotations

import json
import re

import httpx

from .config import Settings

_TIME = re.compile(r"(?<![\d:])([01]?\d|2[0-3]):([0-5]\d)(?![\d:])(\s?(?:am|pm|a\.m\.|p\.m\.))?", re.I)


def _times(text: str) -> set:
    """Clock times normalised to HH:MM (24h), so "8:00 a.m." matches "08:00"."""
    out = set()
    for m in _TIME.finditer(text or ""):
        h, mi, suf = int(m.group(1)), m.group(2), (m.group(3) or "").lower().replace(".", "").strip()
        if suf == "pm" and h < 12:
            h += 12
        if suf == "am" and h == 12:
            h = 0
        out.add(f"{h:02d}:{mi}")
    return out
_DATE = re.compile(r"\b20\d\d-\d\d-\d\d\b")
_MONEY = re.compile(r"£\s?(\d+)")


def rule_claim_check(summary: str, truth_or_evidence: dict | str) -> bool:
    """Every time, ISO date and £ amount in the summary must appear in the evidence."""
    ev = truth_or_evidence if isinstance(truth_or_evidence, str) else json.dumps(truth_or_evidence)
    if not _times(summary) <= _times(ev):
        return False
    for m in _DATE.finditer(summary or ""):
        if m.group(0) not in ev:
            return False
    for m in _MONEY.finditer(summary or ""):
        if m.group(1) not in ev:
            return False
    return True


class SaplingClient:
    """Calls a Banyan Sapling endpoint. The request/response shape is configurable because the
    hosted API format is not public yet (see needs.md). Falls back to the rule check on error."""

    def __init__(self, url: str, key: str | None = None):
        self.url = url
        self.key = key
        self.http = httpx.Client(timeout=30)

    def check(self, policy: str, evidence: str, claim: str) -> tuple[bool, str]:
        headers = {"Authorization": f"Bearer {self.key}"} if self.key else {}
        r = self.http.post(self.url, json={"policy": policy, "evidence": evidence, "claim": claim}, headers=headers)
        r.raise_for_status()
        j = r.json()
        # Model card labels: supported | violation | insufficient_information | inconsistent_context;
        # `status` is the calibrated result and may be "unsure" (treat as not verified).
        status = str(j.get("status") or j.get("label") or j.get("raw_label") or "").lower()
        return status == "supported", status


def make_claim_checker(s: Settings):
    if s.live and s.banyan_api_url:
        client = SaplingClient(s.banyan_api_url, s.banyan_api_key)

        def check(summary: str, evidence) -> bool:
            ev = evidence if isinstance(evidence, str) else json.dumps(evidence)
            try:
                ok, _ = client.check("Only state facts present in the evidence.", ev, summary)
                return ok and rule_claim_check(summary, ev)
            except Exception:
                return rule_claim_check(summary, ev)
        return check
    return rule_claim_check
