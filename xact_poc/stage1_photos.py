"""Stage 1: one cheap vision call per photo -> structured observations.

No single call ever sees all 40 photos, so per-call context stays ~1.5k tokens.
Measurements are only accepted with a named reference object (outlet, door, baseboard...),
otherwise they come back null and become a gap for the review queue.
"""
import asyncio
import json
from pathlib import Path

from .llm import Client, image_block

PHOTO_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".webp"}

SYSTEM = """You are a water-mitigation field technician reviewing ONE photo from a residential water loss.
Report only what is visible. Never guess a number you cannot anchor.
Field convention: the technician marks the measured water/wick line on each wet wall with a strip of
masking or painter's tape. A horizontal tape strip along the lower wall IS the water line; report its
height (top edge of the tape) and the damage as "water line". Walls without tape are treated as dry.
Keep every string field under 25 words.

Return JSON only:
{
  "room": "kitchen | dining room | hallway | ... (best guess, lowercase)",
  "room_evidence": "what in the photo tells you the room",
  "view": "short description of what the photo shows and from where",
  "surfaces": [
    {
      "surface": "wall | floor | ceiling | cabinet | baseboard | trim | other",
      "locator": "how to tell this surface apart from others in the room, e.g. 'wall with window over sink', 'wall behind fridge'",
      "material": "drywall | plaster | tile | LVP | hardwood | carpet | laminate | cabinet box | unknown",
      "damage": ["water line", "staining", "swelling", "delamination", "mold-like growth", "cupping", "standing water", "none visible"],
      "water_line_in": number or null,
      "water_line_reference": "object used to estimate the height, with its assumed size, e.g. 'outlet center ~14in AFF', or null",
      "visible_width_ft": number or null,
      "width_reference": "e.g. 'standard 36in door', or null",
      "confidence": 0.0-1.0
    }
  ],
  "equipment_visible": ["air mover", "dehumidifier", ...],
  "measurement_aids_visible": ["tape measure", "moisture meter reading: 32%", ...],
  "photo_quality": "good | blurry | dark | partial"
}

Reference sizes you may use: outlet box center 12-16in above floor; standard door 80in tall, 30-36in wide;
baseboard 3-5in; base cabinet 34.5in tall without counter, 36in with; upper cabinet bottom ~54in AFF.
If a measuring tape or meter is visible, prefer its reading."""


async def extract_photo(client: Client, model: str, path: Path) -> dict:
    obs = await client.json_call(
        "1-photos", model, SYSTEM,
        [image_block(path), {"type": "text", "text": f"Photo id: {path.name}"}],
        max_tokens=4000,
    )
    obs["photo"] = path.name
    return obs


async def run(client: Client, model: str, photo_dir: Path, cache: Path) -> list[dict]:
    """Results are cached per model so re-running later stages is free."""
    if cache.exists():
        return json.loads(cache.read_text())
    photos = sorted(p for p in photo_dir.iterdir() if p.suffix.lower() in PHOTO_EXTS)
    results = await asyncio.gather(*(extract_photo(client, model, p) for p in photos),
                                   return_exceptions=True)
    obs = []
    for p, r in zip(photos, results):
        if isinstance(r, Exception):
            obs.append({"photo": p.name, "error": repr(r)})
        else:
            obs.append(r)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(obs, indent=2))
    return obs
