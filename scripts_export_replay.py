"""Rebuild data/live_replay.json from the live run's database (gitignored). Refuses to write if a key
value or anything that looks like an auth header is in the output."""
from pathlib import Path

from shadowcall import replay

if __name__ == "__main__":
    d = Path("data")
    print(replay.export(str(d / "live_run.db"), [str(d / "cards_v1_s7.jsonl"), str(d / "cards_v1_s31_heldout_redflag.jsonl")],
                        d / "live_replay.json", d / "live_results.json"))
