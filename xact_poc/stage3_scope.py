"""Stage 3: transcript facts + photo surfaces -> line items, with provenance and a review queue.

The LLM's job is narrow: pull facts out of the transcript, each with a verbatim quote.
Code owns the numbers: quantities are computed from cited facts, and a line item whose
inputs are missing or contradictory is not guessed. It goes to the human review queue.
"""
import json
import math

from .llm import Client

SYSTEM = """You extract facts from a phone call between a water-mitigation company and a homeowner.
Only report what is said. Every fact needs a verbatim quote from the transcript; if a fact is not
stated, use null. Do not convert vague statements into precise numbers ("pretty big room" -> null).

Return JSON only:
{
  "cause": {"value": "...", "quote": "..."},
  "water_source_category": {"value": 1|2|3|null, "reason": "IICRC S500: 1=clean supply line, 2=grey (dishwasher/washer discharge), 3=black (sewage/flood)", "quote": "..."},
  "date_of_loss": {"value": "...", "quote": "..."},
  "hours_before_mitigation": {"value": number|null, "quote": "..."},
  "rooms": [
    {"room": "lowercase name", "length_ft": number|null, "width_ft": number|null, "dims_quote": "...|null",
     "flooring": "...|null", "flooring_quote": "...|null",
     "reported_water_depth_in": number|null, "depth_quote": "...|null",
     "ceiling_height_ft": number|null}
  ],
  "contents_affected": [{"item": "...", "quote": "..."}],
  "homeowner_uncertainties": ["things the homeowner said they were unsure about, quoted"]
}"""

# Illustrative codes modeled on Xactimate's WTR category. NOT the real price list.
PRICE_LIST = {
    "WTR DRYW": ("Tear out wet drywall, cleanup, bag for disposal", "SF", 1.85),
    "WTR BASE": ("Tear out baseboard", "LF", 0.95),
    "WTR FLR":  ("Tear out wet non-salvageable flooring, bag", "SF", 1.40),
    "WTR ANTI": ("Apply antimicrobial agent to affected surfaces", "SF", 0.35),
    "WTR AIRM": ("Air mover (per 24 hr period)", "DA", 29.00),
    "WTR DHM":  ("Dehumidifier - large (per 24 hr period)", "DA", 75.00),
    "WTR CAT3": ("Category 3 water: additional PPE and decontamination", "EA", 145.00),
}
DRY_DAYS = 3  # typical; real jobs use moisture readings to decide
NON_SALVAGEABLE_FLOORS = ("carpet", "laminate", "lvp", "vinyl", "pad")


def flood_cut_ft(water_line_in: float) -> int:
    """Standard practice: cut 12in+ above the wick line, at 2ft or 4ft for clean seams."""
    need = water_line_in + 12
    return 2 if need <= 24 else 4 if need <= 48 else 8


def norm(room: str | None) -> str:
    return (room or "unknown").strip().lower()


def build(facts: dict, surfaces: list[dict]) -> dict:
    items, review = [], []

    def item(room, code, qty, sources, note=""):
        desc, unit, price = PRICE_LIST[code]
        items.append({"room": room, "code": code, "desc": desc, "unit": unit,
                      "qty": round(qty, 2), "unit_price": price, "total": round(qty * price, 2),
                      "sources": sources, "note": note})

    def flag(room, what, why, sources=()):
        review.append({"room": room, "needs": what, "why": why, "sources": list(sources)})

    t_rooms = {norm(r["room"]): r for r in facts.get("rooms", [])}
    by_room: dict[str, list[dict]] = {}
    for s in surfaces:
        by_room.setdefault(norm(s["room"]), []).append(s)

    for room in sorted(set(by_room) | set(t_rooms)):
        tr = t_rooms.get(room, {})
        surfs = by_room.get(room, [])
        photos = sorted({p for s in surfs for p in s["photos"]})
        if not surfs:
            flag(room, "photos of this room", "Homeowner mentioned it but no photo shows it.",
                 [f"transcript: \"{tr.get('dims_quote') or tr.get('depth_quote') or ''}\""])
            continue
        for s in surfs:
            if s["ambiguous"]:
                flag(room, "confirm surface is not a duplicate", s.get("locator") or s["key"], s["photos"])
            for c in s["conflicts"]:
                flag(room, f"resolve conflict on {s['key']}", c, s["photos"])

        L, W = tr.get("length_ft"), tr.get("width_ft")
        dims_src = f"transcript: \"{tr.get('dims_quote')}\"" if L and W else None
        if not dims_src:
            flag(room, "room dimensions (L x W)",
                 "Not stated on the call and not measurable from photos. Needs a tape measure or sketch.",
                 photos)

        walls = [s for s in surfs if s["surface"] == "wall" and s["water_line_in"] is not None]
        if walls:
            wl = max(s["water_line_in"] for s in walls)
            wl_src = [f"{e['in']}in via {e['ref']}" for s in walls for e in s["water_line_estimates"]]
            reported = tr.get("reported_water_depth_in")
            if reported is not None and abs(reported - wl) > 4:
                flag(room, "water line height",
                     f"Homeowner said ~{reported}in (\"{tr.get('depth_quote')}\"), photos show a ~{wl}in "
                     f"wick line. Wicking often climbs above standing depth; tech should confirm with a meter.",
                     photos)
            cut = flood_cut_ft(wl)
            if dims_src:
                # Affected walls only. Without a sketch, assume each affected wall is the longer room side.
                wall_lf = min(len(walls) * max(L, W), 2 * (L + W))
                note = f"{len(walls)} affected wall(s) x {max(L, W)}ft (longest side), cut at {cut}ft"
                src = [dims_src] + wl_src + [f"photos: {', '.join(s['photos'][0] for s in walls)}"]
                item(room, "WTR DRYW", wall_lf * cut, src, note)
                item(room, "WTR BASE", wall_lf, src, note)
                item(room, "WTR ANTI", wall_lf * cut, src, "same area as drywall removal")
                item(room, "WTR AIRM", (math.ceil(wall_lf / 14) + 1) * DRY_DAYS, src,
                     f"IICRC rule of thumb: 1 per room + 1 per 14 LF wet wall, {DRY_DAYS} days")
        elif any(s["surface"] == "wall" for s in surfs):
            flag(room, "water line height on walls",
                 "Wall damage visible but no reference object to estimate height.", photos)

        floor = (tr.get("flooring") or " ".join(m for s in surfs if s["surface"] == "floor" for m in s["materials"])).lower()
        floor_damaged = any(s["surface"] == "floor" for s in surfs)
        if floor_damaged and any(f in floor for f in NON_SALVAGEABLE_FLOORS):
            if dims_src:
                item(room, "WTR FLR", L * W, [dims_src, f"flooring: {floor}"]
                     + [p for s in surfs if s["surface"] == "floor" for p in s["photos"]])
            # without dims the room is already flagged above
        elif floor_damaged and not floor.strip():
            flag(room, "flooring material", "Floor damage visible but material unclear.", photos)

        if dims_src:
            item(room, "WTR DHM", max(1, math.ceil(L * W / 500)) * DRY_DAYS, [dims_src],
                 f"1 large dehu per ~500 SF, {DRY_DAYS} days")

    cat = (facts.get("water_source_category") or {}).get("value")
    if cat is None:
        flag("job", "water category (1/2/3)", "Source not clear from call. Changes PPE and what is salvageable.")
    elif cat == 3:
        item("job", "WTR CAT3", 1, [f"transcript: \"{facts['water_source_category'].get('quote')}\""])

    for u in facts.get("homeowner_uncertainties", []):
        flag("job", "follow up with homeowner", u)

    return {"line_items": items, "review_queue": review,
            "estimate_total": round(sum(i["total"] for i in items), 2)}


async def run(client: Client, model: str, transcript: str, surfaces: list[dict]) -> dict:
    facts = await client.json_call("3-transcript", model, SYSTEM, transcript, max_tokens=3000)
    return {"facts": facts, **build(facts, surfaces)}
