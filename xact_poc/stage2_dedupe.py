"""Stage 2: collapse per-photo observations into unique physical surfaces.

Text-only, so it's cheap. The model only decides *which observations are the same surface*;
code does the merging (median of estimates, union of damage, list of supporting photos),
so a surface seen in 6 photos is scoped once, not 6 times.
"""
import json
from statistics import median

from .llm import Client

SYSTEM = """You are deduplicating observations from many photos of the same water loss.
Several photos often show the same physical surface from different angles.

Input: a list of observations, each with an id like "IMG_0012.jpg#1".
Group the ids that refer to the SAME physical surface (same room, same wall/floor/ceiling).
Use room, locator, material and damage pattern. When unsure whether two are the same, keep them
separate and mark "ambiguous": true. Also merge room names that are clearly the same room.

Return JSON only:
{"surfaces": [{"key": "kitchen/wall/sink-window-wall", "room": "kitchen", "surface": "wall",
               "locator": "...", "obs_ids": ["IMG_0012.jpg#1", ...], "ambiguous": false,
               "why": "one short sentence"}]}
Every input id must appear in exactly one group."""


def flatten(observations: list[dict]) -> dict[str, dict]:
    flat = {}
    for o in observations:
        for i, s in enumerate(o.get("surfaces", [])):
            if s.get("damage") == ["none visible"]:
                continue
            flat[f"{o['photo']}#{i}"] = {**s, "room": o.get("room"), "photo": o["photo"]}
    return flat


def merge(group: dict, flat: dict[str, dict]) -> dict:
    obs = [flat[i] for i in group["obs_ids"] if i in flat]
    wl = [(o["water_line_in"], o["water_line_reference"]) for o in obs
          if o.get("water_line_in") is not None and o.get("water_line_reference")]
    widths = [o["visible_width_ft"] for o in obs if o.get("visible_width_ft") and o.get("width_reference")]
    materials = sorted({o["material"] for o in obs if o.get("material") not in (None, "unknown")})
    return {
        "key": group["key"],
        "room": group["room"],
        "surface": group["surface"],
        "locator": group.get("locator"),
        "materials": materials,
        "damage": sorted({d for o in obs for d in o.get("damage", []) if d != "none visible"}),
        "water_line_in": median(w for w, _ in wl) if wl else None,
        "water_line_estimates": [{"in": w, "ref": r} for w, r in wl],
        "max_visible_width_ft": max(widths) if widths else None,
        "photos": sorted({o["photo"] for o in obs}),
        "confidence": round(sum(o.get("confidence", 0.5) for o in obs) / len(obs), 2) if obs else 0,
        "ambiguous": group.get("ambiguous", False),
        "conflicts": ([f"materials disagree: {materials}"] if len(materials) > 1 else [])
                     + ([f"water line estimates spread {min(w for w, _ in wl)}-{max(w for w, _ in wl)}in"]
                        if wl and max(w for w, _ in wl) - min(w for w, _ in wl) > 6 else []),
    }


async def run(client: Client, model: str, observations: list[dict]) -> dict:
    flat = flatten(observations)
    compact = [{"id": k, "room": v["room"], "surface": v["surface"], "locator": v.get("locator"),
                "material": v.get("material"), "damage": v.get("damage")} for k, v in flat.items()]
    out = await client.json_call("2-dedupe", model, SYSTEM, json.dumps(compact), max_tokens=8000)
    groups = out["surfaces"]

    # Anything the model dropped becomes its own surface instead of silently vanishing.
    seen = {i for g in groups for i in g["obs_ids"]}
    for k in flat.keys() - seen:
        v = flat[k]
        groups.append({"key": f"{v['room']}/{v['surface']}/unassigned-{k}", "room": v["room"],
                       "surface": v["surface"], "locator": v.get("locator"), "obs_ids": [k],
                       "ambiguous": True})

    surfaces = [merge(g, flat) for g in groups]
    return {"raw_observations": len(flat), "unique_surfaces": len(surfaces), "surfaces": surfaces}
