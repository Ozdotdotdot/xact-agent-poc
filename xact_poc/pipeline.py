"""The pipeline stages wired together, shared by run.py (one claim, verbose) and eval.py (many runs, scored)."""
from pathlib import Path

from . import stage1_photos, stage2_dedupe, stage3_scope, stage4_write
from .llm import Client


async def run_claim(client: Client, claim: Path, transcript: str, models: dict, mock_base: str,
                    obs_cache: Path, log=lambda *_: None, guided: dict[str, list[str]] | None = None) -> dict:
    """guided: room -> photo stems, as a guided capture app would record them. Rooms are matched to the
    call's room names, since the app builds its room list from the call."""
    log(f"[1] read the call -> facts, each with a quote ({models['scope']})")
    facts = await stage3_scope.extract_facts(client, models["scope"], transcript)
    rooms = {r["room"].lower(): {k: v for k, v in r.items() if k != "room" and v not in (None, [], "")}
             for r in facts.get("rooms", [])}
    log(f"    rooms on the call: {list(rooms)}")

    # Photo observations don't depend on the transcript, so they're cached per claim + model.
    log(f"[2] describe each photo ({models['photo']}, one call per photo)")
    obs = await stage1_photos.run(client, models["photo"], claim / "photos", obs_cache)
    log(f"    {len(obs)} photos, {sum(len(o.get('surfaces', [])) for o in obs)} surface observations")

    tags = None
    if guided:
        tags = {}
        for capture_room, stems in guided.items():
            name = next((r for r in rooms if capture_room in r or r in capture_room), capture_room)
            tags.update({f"{s}.jpg": name for s in stems})

    if tags:
        log(f"[3] sort photos into rooms: skipped, photos arrived tagged with {sorted(set(tags.values()))}")
    else:
        log(f"[3] sort photos into rooms ({models['dedupe']})")
    log(f"[4] count wet walls per room ({models['dedupe']}, one call per room)")
    dd = await stage2_dedupe.run(client, models["dedupe"], obs, rooms, claim / "photos", room_tags=tags)
    log(f"    {dd['raw_observations']} surface observations -> {dd['unique_surfaces']} unique surfaces")
    for r, v in dd["rooms"].items():
        log(f"    {r}: {len(v['photos'])} photos, {v['wet_walls']} wet walls")

    log("[5] compute the estimate (code, no model)")
    scope = {"facts": facts, **stage3_scope.build(facts, dd["surfaces"])}
    log(f"    {len(scope['line_items'])} line items, {len(scope['review_queue'])} flagged for a human, "
        f"${scope['estimate_total']:,.2f}")
    for li in scope["line_items"]:
        log(f"      {li['room']:<12} {li['code']:<9} {li['qty']:>6g} {li['unit']:<3} ${li['total']:>8,.2f}  {li['desc']}")
    for q in scope["review_queue"]:
        log(f"      ? {q['room']}: {q['needs']}")

    log("[6] write to Xact (mock), read it back, repair")
    write = stage4_write.run(mock_base, claim.name, scope["line_items"])
    for r in write["rounds"]:
        log(f"    round {r['round']}: wrote {r['written']}, verified {r['verified']}, "
            f"corrupted {len(r['corrupted_removed'])}, missing {r['missing']}")
    log(f"    verified: {write['verified']}")
    return {"observations": obs, "dedupe": dd, "scope": scope, "write": write}
