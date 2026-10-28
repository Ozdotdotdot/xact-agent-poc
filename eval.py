"""Score the pipeline against truth.json, N runs per transcript, to measure accuracy AND consistency.

uv run eval.py data/claim-001 --runs 3 [--dedupe-model claude-haiku-5-5]
"""
import argparse
import asyncio
import json
import re
from collections import defaultdict
from pathlib import Path
from statistics import median

from xact_poc import xact_mock
from xact_poc.llm import CHEAP, SMART, Client, Ledger
from xact_poc.pipeline import run_claim
from xact_poc.stage3_scope import flood_cut_ft


def canon(room: str, truth_rooms: dict) -> str | None:
    """Map a pipeline room name ('guest bedroom') onto a truth room ('bedroom')."""
    room = (room or "").lower()
    for name, t in truth_rooms.items():
        if name in room or any(a.lower() in room for a in t.get("aka", [])):
            return name
    return None


def score(result: dict, truth: dict, transcript: str) -> dict:
    rooms = truth["rooms"]
    surfaces = result["dedupe"]["surfaces"]
    scope = result["scope"]

    # Photo -> room: a photo counts as correct if every surface it contributed to sits in its true room.
    photo_rooms = defaultdict(set)
    for s in surfaces:
        for p in s["photos"]:
            photo_rooms[p.rsplit(".", 1)[0]].add(canon(s["room"], rooms) or s["room"])
    true_room = {p: r for r, t in rooms.items() for p in t["photos"]}
    placed = {p: rs for p, rs in photo_rooms.items() if p in true_room}
    photo_acc = sum(rs == {true_room[p]} for p, rs in placed.items()) / len(true_room)

    per_room = {}
    for r, t in rooms.items():
        wls = [s["water_line_in"] for s in surfaces
               if canon(s["room"], rooms) == r and s["surface"] == "wall" and s["water_line_in"] is not None]
        wl = max(wls) if wls else None
        lo, hi = t["water_line_in"]
        flr = [i["qty"] for i in scope["line_items"] if i["code"] == "WTR FLR" and canon(i["room"], rooms) == r]
        per_room[r] = {
            "water_line_in": wl,
            "wl_error_in": None if wl is None else round(0 if lo <= wl <= hi else min(abs(wl - lo), abs(wl - hi)), 1),
            "flood_cut_ok": None if wl is None else flood_cut_ft(wl) == truth["flood_cut_ft"][r],
            "wet_walls_true": t.get("wet_walls"),
            "wet_walls": sum(1 for s in surfaces if canon(s["room"], rooms) == r and s["surface"] == "wall"
                             and s["water_line_in"] is not None),
            "floor_sf": flr[0] if flr else None,
            "floor_sf_ok": (flr[0] == t["area_sqft"]) if flr and "area_sqft" in t else None,
        }

    expected = truth["transcripts"][transcript]["expected_flags"]
    text = [f"{q['room']} {q['needs']} {q['why']}".lower() for q in scope["review_queue"]]
    hits = [any(re.search(e["match"], t) and (e["room"] in ("any", "job") or e["room"] in t) for t in text)
            for e in expected]

    return {"photo_room_acc": round(photo_acc, 2), "rooms": per_room,
            "flags_expected": len(expected), "flags_caught": sum(hits),
            "missed": [e for e, h in zip(expected, hits) if not h],
            "review_queue": len(scope["review_queue"]), "line_items": len(scope["line_items"]),
            "total": scope["estimate_total"], "xact_verified": result["write"]["verified"],
            "xact_repairs": sum(len(r["corrupted_removed"]) + r["missing"] for r in result["write"]["rounds"][:1])}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("claim", type=Path)
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--photo-model", default=CHEAP)
    ap.add_argument("--dedupe-model", default=SMART)
    ap.add_argument("--scope-model", default=SMART)
    ap.add_argument("--transcripts", nargs="*")
    ap.add_argument("--tag", default="latest", help="results/eval-<tag>.json")
    args = ap.parse_args()

    truth = json.loads((args.claim / "truth.json").read_text())
    names = args.transcripts or sorted(truth["transcripts"])
    models = {"photo": args.photo_model, "dedupe": args.dedupe_model, "scope": args.scope_model}
    mock = xact_mock.serve()
    out = Path("out") / args.claim.name / "eval"
    out.mkdir(parents=True, exist_ok=True)
    obs_cache = out.parent / f"observations.{args.photo_model}.json"

    rows = []
    for name in names:
        transcript = (args.claim / "transcripts" / f"{name}.txt").read_text()
        for i in range(args.runs):
            ledger = Ledger()
            client = Client(ledger)
            try:
                result = await run_claim(client, args.claim, transcript, models, mock, obs_cache)
            except Exception as e:  # a crashed run is a data point, not a reason to lose the others
                print(f"{name} #{i + 1}: FAILED {e!r:.150}")
                rows.append({"transcript": name, "run": i + 1, "failed": repr(e)[:300], "usd": round(ledger.total(), 4)})
                continue
            finally:
                await client.close()
            s = score(result, truth, name) | {"transcript": name, "run": i + 1, "usd": round(ledger.total(), 4)}
            rows.append(s)
            print(f"{name} #{i + 1}: photos->room {s['photo_room_acc']:.0%}, flags {s['flags_caught']}/{s['flags_expected']}, "
                  f"queue {s['review_queue']}, items {s['line_items']}, ${s['total']:,.0f}, cost ${s['usd']:.4f}")

    Path("results").mkdir(exist_ok=True)
    Path(f"results/eval-{args.tag}.json").write_text(json.dumps({"models": models, "rows": rows}, indent=2))

    failed = [r for r in rows if "failed" in r]
    rows = [r for r in rows if "failed" not in r]
    print(f"\n=== {len(rows)} runs ok, {len(failed)} failed, dedupe={args.dedupe_model}")
    print(f"photo->room accuracy: median {median(r['photo_room_acc'] for r in rows):.0%}, "
          f"range {min(r['photo_room_acc'] for r in rows):.0%}-{max(r['photo_room_acc'] for r in rows):.0%}")
    print(f"expected flags caught: {sum(r['flags_caught'] for r in rows)}/{sum(r['flags_expected'] for r in rows)}")
    print(f"xact read-back verified: {sum(r['xact_verified'] for r in rows)}/{len(rows)} "
          f"(repaired {sum(r['xact_repairs'] for r in rows)} silent write failures)")
    for room in truth["rooms"]:
        rs = [r["rooms"][room] for r in rows]
        wl = [x["water_line_in"] for x in rs if x["water_line_in"] is not None]
        cut = [x["flood_cut_ok"] for x in rs if x["flood_cut_ok"] is not None]
        walls = [x["wet_walls"] for x in rs]
        walls = f"{walls} (true {truth['rooms'][room].get('wet_walls')})"
        print(f"{room:<12} water line {truth['rooms'][room]['water_line_in']} -> est {sorted(wl)}; "
              f"flood cut right {sum(cut)}/{len(cut)}; wet walls per run {walls}")
    print(f"cost per run: median ${median(r['usd'] for r in rows):.4f}")


if __name__ == "__main__":
    asyncio.run(main())
