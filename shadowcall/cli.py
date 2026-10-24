"""Command line: python -m shadowcall.cli <command>"""
from __future__ import annotations

import argparse
import os
import json
from pathlib import Path

from . import evalh, gate, synth
from .config import ROOT, get_settings
from .store import Store
from .subtasks import SUBTASKS
from .verify import make_claim_checker

DATA = ROOT / "data"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="shadowcall")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gen", help="generate synthetic call cards")
    g.add_argument("--n", type=int, default=120)
    g.add_argument("--seed", type=int, default=7)
    g.add_argument("--policy", default="v1")
    g.add_argument("--out", default=None)
    t = sub.add_parser("train", help="send training calls (teacher, verified keeping) through Mubit")
    t.add_argument("--cards", required=True)
    t.add_argument("--limit", type=int, default=None)
    t.add_argument("--project", choices=["verified", "raw"], default="verified",
                   help="raw = learning-off arm: every frontier reply kept, into the MUBIT_API_KEY_RAW project")
    e = sub.add_parser("eval", help="held-out eval of all arms")
    e.add_argument("--cards", required=True)
    e.add_argument("--promote", action="store_true")
    e.add_argument("--lane", default=None, help="lane to promote (default: adapter if callable, else shadow)")
    lv = sub.add_parser("live", help="run calls in shadow mode, serving per the gate")
    lv.add_argument("--cards", required=True)
    lv.add_argument("--limit", type=int, default=None)
    it = sub.add_parser("import-tryouts", help="score adapter replies copied from Mubit Try models")
    it.add_argument("--cards", required=True)
    it.add_argument("--file", required=True)
    sub.add_parser("status", help="gate state and counts")
    sub.add_parser("serve", help="dashboard + ElevenLabs custom-LLM endpoint")
    a = ap.parse_args(argv)

    s = get_settings()
    if a.cmd == "gen":
        out = a.out or str(DATA / f"cards_{a.policy}_s{a.seed}.jsonl")
        cards = synth.generate(a.n, a.seed, a.policy)
        synth.save(cards, out)
        n_h = sum(c.split == "heldout" for c in cards)
        print(f"wrote {len(cards)} cards ({n_h} held-out) to {out}")
        return
    store = Store(s.db_path)
    if a.cmd == "serve":
        import uvicorn
        uvicorn.run("shadowcall.app:app", host=os.environ.get("HOST", "0.0.0.0"), port=int(os.environ.get("PORT", "8013")),
                    proxy_headers=True)
        return
    if a.cmd == "status":
        for st in SUBTASKS:
            kept = store.query("SELECT COUNT(*) n FROM runs WHERE subtask=? AND kept=1", st)[0]["n"]
            print(st, store.gate_state(st)["state"], f"kept={kept}")
        return
    cards = synth.load(a.cards)
    if a.cmd == "train" and a.project == "raw":
        if s.live:
            if not s.mubit_api_key_raw:
                raise SystemExit("MUBIT_API_KEY_RAW is not set")
            s.mubit_api_key = s.mubit_api_key_raw
        s.verified_keep = False
    p = evalh.make_pipeline(s, store, make_claim_checker(s))
    if a.cmd == "train":
        todo = [c for c in cards if c.split == "train"][: a.limit]
        for i, c in enumerate(todo, 1):
            p.run_call(c, "train")
            print(f"[{i}/{len(todo)}] {c.id}")
    elif a.cmd == "eval":
        rep = evalh.run_eval(s, store, cards, make_claim_checker(s))
        evalh.save(rep, str(DATA))
        print(evalh.to_markdown(rep))
        if a.promote:
            pv = cards[0].policy_version
            lane = a.lane or evalh.serving_lane(s)
            for st in SUBTASKS:
                d = gate.try_promote(store, s, st, pv, f"{lane}-{pv}", lane)
                print(st, "PROMOTED" if d.promote else "stays in shadow", "-", d.reason)
    elif a.cmd == "import-tryouts":
        print(json.dumps(evalh.import_tryouts(store, cards, a.file, make_claim_checker(s)), indent=2))
    elif a.cmd == "live":
        for c in cards[: a.limit]:
            out = p.run_call(c, "live", chain=True)
            print(c.id, [(x.subtask, x.served_by, x.passed) for x in out.subtasks])


if __name__ == "__main__":
    main()
