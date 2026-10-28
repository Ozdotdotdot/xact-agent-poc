"""uv run run.py data/claim-001 --transcript 01-prepared [--photo-model claude-haiku-5-5] [--baseline]"""
import argparse
import asyncio
import json
from pathlib import Path

from xact_poc import baseline, report, xact_mock
from xact_poc.llm import CHEAP, FRONTIER, SMART, Client, Ledger
from xact_poc.pipeline import run_claim


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("claim", type=Path)
    ap.add_argument("--transcript", default="01-prepared", help="name in <claim>/transcripts/")
    ap.add_argument("--photo-model", default=CHEAP)
    ap.add_argument("--dedupe-model", default=SMART)
    ap.add_argument("--scope-model", default=SMART)
    ap.add_argument("--baseline", action="store_true", help=f"also run the naive {FRONTIER} baseline")
    ap.add_argument("--xact-fault-rate", type=float, default=0.15,
                    help="share of writes the mock Xact silently drops or corrupts")
    ap.add_argument("--guided", action="store_true",
                    help="simulate guided capture: photos arrive tagged with their room (from truth.json)")
    args = ap.parse_args()

    out = Path("out") / args.claim.name / args.transcript
    out.mkdir(parents=True, exist_ok=True)
    transcript = (args.claim / "transcripts" / f"{args.transcript}.txt").read_text()
    models = {"photo": args.photo_model, "dedupe": args.dedupe_model, "scope": args.scope_model}
    ledger = Ledger()
    client = Client(ledger)

    guided = None
    if args.guided:
        truth = json.loads((args.claim / "truth.json").read_text())
        guided = {r: t["photos"] for r, t in truth["rooms"].items()}
    result = await run_claim(client, args.claim, transcript, models, xact_mock.serve(fault_rate=args.xact_fault_rate),
                             out.parent / f"observations.{args.photo_model}.json", log=print, guided=guided)

    base_result = None
    if args.baseline:
        print(f"[baseline] all photos + transcript -> {FRONTIER}, one call")
        base_result = await baseline.run(client, FRONTIER, transcript, args.claim / "photos")
        print(f"    {len(base_result['line_items'])} line items, "
              f"{base_result['duplicate_room_code_pairs']} duplicate room/code pairs, "
              f"${base_result['estimate_total']:,.2f}")

    await client.close()
    result = {"claim": f"{args.claim.name} / {args.transcript}", "models": models, **result,
              "baseline": base_result, "cost": ledger.summary(), "cost_total": ledger.total()}
    (out / "result.json").write_text(json.dumps(result, indent=2, default=str))
    report.write(result, args.claim, out / "report.html")
    print(f"\ncost: ${ledger.total():.4f}")
    for stage, s in ledger.summary().items():
        print(f"  {stage:<14} {s['model']:<26} {s['calls']:>3} calls  {s['in']:>8} in  {s['out']:>6} out  ${s['usd']:.4f}")
    print(f"report: {out / 'report.html'}")


if __name__ == "__main__":
    asyncio.run(main())
