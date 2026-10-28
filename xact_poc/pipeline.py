"""The four stages wired together, shared by run.py (one claim, verbose) and eval.py (many runs, scored)."""
from pathlib import Path

from . import stage1_photos, stage2_dedupe, stage3_scope, stage4_write
from .llm import Client


async def run_claim(client: Client, claim: Path, transcript: str, models: dict, mock_base: str,
                    obs_cache: Path, log=lambda *_: None) -> dict:
    log(f"[0] transcript -> cited facts ({models['scope']})")
    facts = await stage3_scope.extract_facts(client, models["scope"], transcript)
    rooms = [r["room"].lower() for r in facts.get("rooms", [])]
    log(f"    rooms on the call: {rooms}")

    # Photo observations don't depend on the transcript, so they're cached per claim + model.
    log(f"[1] photos -> observations ({models['photo']})")
    obs = await stage1_photos.run(client, models["photo"], claim / "photos", obs_cache)
    log(f"    {len(obs)} photos, {sum(len(o.get('surfaces', [])) for o in obs)} surface observations")

    log(f"[2] dedupe ({models['dedupe']})")
    dd = await stage2_dedupe.run(client, models["dedupe"], obs, rooms)
    log(f"    {dd['raw_observations']} damaged-surface observations -> {dd['unique_surfaces']} unique surfaces")

    log("[3] scope: cited facts + surfaces -> line items (code, no model)")
    scope = {"facts": facts, **stage3_scope.build(facts, dd["surfaces"])}
    log(f"    {len(scope['line_items'])} line items, {len(scope['review_queue'])} flagged for a human, "
        f"${scope['estimate_total']:,.2f}")

    log("[4] write to mock Xact + read back")
    write = stage4_write.run(mock_base, claim.name, scope["line_items"])
    for r in write["rounds"]:
        log(f"    round {r['round']}: wrote {r['written']}, verified {r['verified']}, "
            f"corrupted {len(r['corrupted_removed'])}, missing {r['missing']}")
    log(f"    verified: {write['verified']}")
    return {"observations": obs, "dedupe": dd, "scope": scope, "write": write}
