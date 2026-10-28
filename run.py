"""uv run run.py data/claim-001 [--photo-model claude-haiku-5-5] [--baseline]"""
import argparse
import asyncio
import json
from pathlib import Path

from xact_poc import baseline, report, stage1_photos, stage2_dedupe, stage3_scope, stage4_write, xact_mock
from xact_poc.llm import CHEAP, FRONTIER, SMART, Client, Ledger


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("claim", type=Path)
    ap.add_argument("--photo-model", default=CHEAP)
    ap.add_argument("--dedupe-model", default=CHEAP)
    ap.add_argument("--scope-model", default=SMART)
    ap.add_argument("--baseline", action="store_true", help=f"also run the naive {FRONTIER} baseline")
    args = ap.parse_args()

    out = Path("out") / args.claim.name
    out.mkdir(parents=True, exist_ok=True)
    transcript = (args.claim / "transcript.txt").read_text()
    ledger = Ledger()
    client = Client(ledger)

    print(f"[1] photos -> observations ({args.photo_model})")
    obs = await stage1_photos.run(client, args.photo_model, args.claim / "photos",
                                  out / f"observations.{args.photo_model}.json")
    print(f"    {len(obs)} photos, {sum(len(o.get('surfaces', [])) for o in obs)} surface observations")

    print(f"[2] dedupe ({args.dedupe_model})")
    dd = await stage2_dedupe.run(client, args.dedupe_model, obs)
    print(f"    {dd['raw_observations']} damaged-surface observations -> {dd['unique_surfaces']} unique surfaces")

    print(f"[3] transcript + scope ({args.scope_model})")
    scope = await stage3_scope.run(client, args.scope_model, transcript, dd["surfaces"])
    print(f"    {len(scope['line_items'])} line items, {len(scope['review_queue'])} flagged for a human, "
          f"${scope['estimate_total']:,.2f}")

    print("[4] write to mock Xact + read back")
    base = xact_mock.serve()
    write = stage4_write.run(base, args.claim.name, scope["line_items"])
    for r in write["rounds"]:
        print(f"    round {r['round']}: wrote {r['written']}, verified {r['verified']}, "
              f"corrupted {len(r['corrupted_removed'])}, missing {r['missing']}")
    print(f"    verified: {write['verified']}")

    base_result = None
    if args.baseline:
        print(f"[baseline] all photos + transcript -> {FRONTIER}, one call")
        base_result = await baseline.run(client, FRONTIER, transcript, args.claim / "photos")
        print(f"    {len(base_result['line_items'])} line items, "
              f"{base_result['duplicate_room_code_pairs']} duplicate room/code pairs, "
              f"${base_result['estimate_total']:,.2f}")

    await client.close()
    result = {"claim": args.claim.name, "models": vars(args) | {"claim": str(args.claim)},
              "observations": obs, "dedupe": dd, "scope": scope, "write": write,
              "baseline": base_result, "cost": ledger.summary(), "cost_total": ledger.total()}
    (out / "result.json").write_text(json.dumps(result, indent=2, default=str))
    report.write(result, args.claim, out / "report.html")
    print(f"\ncost: ${ledger.total():.4f}")
    for stage, s in ledger.summary().items():
        print(f"  {stage:<14} {s['model']:<26} {s['calls']:>3} calls  {s['in']:>8} in  {s['out']:>6} out  ${s['usd']:.4f}")
    print(f"report: {out / 'report.html'}")


if __name__ == "__main__":
    asyncio.run(main())
