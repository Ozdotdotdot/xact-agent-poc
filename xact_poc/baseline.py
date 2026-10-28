"""Naive baseline: every photo + the transcript in one frontier-model call, 'write the estimate'.
This is what most people build first. It exists here to be measured against.
"""
from pathlib import Path

from .llm import Client, image_block
from .stage1_photos import PHOTO_EXTS
from .stage3_scope import PRICE_LIST

SYSTEM = f"""You are a water-mitigation estimator. From the call transcript and the photos, produce the
mitigation estimate as line items using ONLY these codes:
{chr(10).join(f'{c}: {d} ({u})' for c, (d, u, _) in PRICE_LIST.items())}

Return JSON only: {{"line_items": [{{"room": "...", "code": "...", "qty": number, "unit": "...", "basis": "..."}}]}}"""


async def run(client: Client, model: str, transcript: str, photo_dir: Path) -> dict:
    photos = sorted(p for p in photo_dir.iterdir() if p.suffix.lower() in PHOTO_EXTS)
    content = []
    for p in photos:
        content += [{"type": "text", "text": f"Photo {p.name}:"}, image_block(p)]
    content.append({"type": "text", "text": f"Call transcript:\n{transcript}"})
    out = await client.json_call("baseline", model, SYSTEM, content, max_tokens=6000)
    items = out["line_items"]
    for li in items:
        _, _, price = PRICE_LIST.get(li["code"], ("", "", 0))
        li["total"] = round(li["qty"] * price, 2)
    keys = [(li["room"].lower(), li["code"]) for li in items]
    return {"line_items": items, "estimate_total": round(sum(li["total"] for li in items), 2),
            "duplicate_room_code_pairs": len(keys) - len(set(keys)),
            "review_queue": []}  # the baseline never says "I don't know"
