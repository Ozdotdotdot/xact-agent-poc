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
Convert stated units: "a hundred and five inches" -> 8.75 ft. "twelve by twelve" -> length 12, width 12.
List every room the caller says got wet, even ones with no details.

Return JSON only:
{
  "cause": {"value": "...", "quote": "..."},
  "water_source_category": {"value": 1|2|3|null, "reason": "IICRC S500: 1=clean supply line, 2=grey (dishwasher/washer discharge), 3=black (sewage/flood)", "quote": "..."},
  "date_of_loss": {"value": "...", "quote": "..."},
  "hours_before_mitigation": {"value": number|null, "quote": "..."},
  "reported_water_depth_in": {"value": number|null, "quote": "...", "room": "lowercase name or null if whole job"},
  "rooms": [
    {"room": "lowercase name", "length_ft": number|null, "width_ft": number|null,
     "area_sqft": number|null, "dims_quote": "...|null",
     "affected_wall_lengths_ft": [number], "wall_lengths_quote": "...|null",
     "flooring": "...|null", "flooring_quote": "...|null",
     "reported_water_depth_in": number|null, "depth_quote": "...|null",
     "ceiling_height_ft": number|null}
  ],
  "contents_affected": [{"item": "...", "quote": "..."}],
  "unverified_areas": [{"area": "lowercase name, e.g. 'bedroom closet'", "quote": "..."}]
}
"unverified_areas" = places the caller says MIGHT be wet but did not check. Not general hedging like
"I think" or "maybe six hours"."""

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
    job_depth = facts.get("reported_water_depth_in") or {}
    depth_gaps: list[tuple[str, float]] = []
    by_room: dict[str, list[dict]] = {}
    for s in surfaces:
        by_room.setdefault(norm(s["room"]), []).append(s)

    for room in sorted(set(by_room) | set(t_rooms)):
        tr = t_rooms.get(room, {})
        surfs = by_room.get(room, [])
        photos = sorted({p for s in surfs for p in s["photos"]})
        if not surfs:
            flag(room, "photos of this room",
                 "Caller says it got wet but no photo shows it. Nothing is billed without evidence.")
            continue
        # A caller can name a room that matches a model's guessed photo label ("office") without the photos
        # being of that room. Flooring is a cheap physical cross-check.
        said = (tr.get("flooring") or "").lower()
        seen = {m.lower() for s in surfs if s["surface"] == "floor" for m in s["materials"]}
        if said and seen and not any(m in said or said in m for m in seen):
            flag(room, "confirm these photos are this room",
                 f"Caller says the {room} floor is {said}; photos assigned to it show {', '.join(sorted(seen))}. "
                 f"The photos may be of a different room.", photos)

        unsure = [s for s in surfs if s["ambiguous"] and s["surface"] == "wall"]
        if unsure:
            flag(room, "confirm wet-wall count",
                 f"{len(unsure)} of {sum(s['surface'] == 'wall' for s in surfs)} wall groupings are uncertain "
                 f"(similar-looking walls or close-ups without context). Wall count drives drywall quantity.",
                 sorted({p for s in unsure for p in s["photos"]}))
        for s in surfs:
            for c in s["conflicts"]:
                flag(room, f"resolve conflict on {s['key']}", c, s["photos"])

        L, W, A = tr.get("length_ft"), tr.get("width_ft"), tr.get("area_sqft")
        area = A or (L * W if L and W else None)
        area_src = f"transcript: \"{tr.get('dims_quote')}\"" if area else None

        walls = [s for s in surfs if s["surface"] == "wall" and s["water_line_in"] is not None]
        if walls:
            wl = max(s["water_line_in"] for s in walls)
            wl_src = [f"{e['in']}in via {e['ref']}" for s in walls for e in s["water_line_estimates"]][:4]
            reported, depth_quote = tr.get("reported_water_depth_in"), tr.get("depth_quote")
            if reported is None and job_depth.get("value") is not None and norm(job_depth.get("room")) in ("unknown", room):
                if abs(job_depth["value"] - wl) > 4:
                    depth_gaps.append((room, wl))
            elif reported is not None and abs(reported - wl) > 4:
                flag(room, "confirm water line height",
                     f"Caller said ~{reported}in (\"{depth_quote}\"), photos show a ~{wl}in water line. "
                     f"Wicking climbs above standing water; tech should confirm with a meter.", photos)
            cut = flood_cut_ft(wl)
            stated = tr.get("affected_wall_lengths_ft") or []
            if len(stated) >= len(walls):
                wall_lf, basis = sum(stated[:len(walls)]), f"wall length(s) {stated[:len(walls)]}ft from call"
                lf_src = [f"transcript: \"{tr.get('wall_lengths_quote')}\""]
                provisional = False
            elif area:
                side = math.sqrt(area)
                wall_lf, basis = len(walls) * side, f"PROVISIONAL: {len(walls)} wall(s) x {side:.1f}ft (sqrt of {area} SF)"
                lf_src, provisional = [area_src], True
                flag(room, "measure affected wall lengths",
                     f"{len(walls)} wet wall(s) seen in photos but lengths unknown; drywall/baseboard quantities "
                     f"assume a square room ({side:.1f}ft walls).", photos)
            else:
                wall_lf = None
                flag(room, "room dimensions or wall lengths",
                     "Not stated on the call and not measurable from photos. Drywall, baseboard and "
                     "antimicrobial for this room are held until measured.", photos)
            if wall_lf:
                src = lf_src + wl_src + [f"photos: {', '.join(s['photos'][0] for s in walls)}"]
                note = f"{basis}; water line ~{wl}in -> {cut}ft flood cut"
                item(room, "WTR DRYW", wall_lf * cut, src, note)
                item(room, "WTR BASE", wall_lf, src, basis)
                item(room, "WTR ANTI", wall_lf * cut, src, "same area as drywall removal")
                item(room, "WTR AIRM", (math.ceil(wall_lf / 14) + 1) * DRY_DAYS, src,
                     f"IICRC rule of thumb: 1 per room + 1 per 14 LF wet wall, {DRY_DAYS} days")
                if provisional:
                    for i in items[-4:]:
                        i["provisional"] = True
        elif any(s["surface"] == "wall" for s in surfs):
            flag(room, "water line height on walls",
                 "Wall damage visible but no reference object to estimate height.", photos)

        floor = (tr.get("flooring") or " ".join(m for s in surfs if s["surface"] == "floor" for m in s["materials"])).lower()
        # A water line on a wall means water stood on the floor, whether or not the carpet photographs wet.
        floor_damaged = any(s["surface"] == "floor" for s in surfs) or bool(walls)
        if floor_damaged and any(f in floor for f in NON_SALVAGEABLE_FLOORS):
            if area:
                item(room, "WTR FLR", area, [area_src, f"flooring: {floor}"]
                     + [p for s in surfs if s["surface"] == "floor" for p in s["photos"]])
            else:
                flag(room, "room area (SF)", f"Wet {floor or 'flooring'} must come out but room area is unknown.", photos)
        elif floor_damaged and not floor.strip():
            flag(room, "flooring material", "Floor damage visible but material unclear.", photos)

        if area:
            item(room, "WTR DHM", max(1, math.ceil(area / 500)) * DRY_DAYS, [area_src],
                 f"1 large dehu per ~500 SF, {DRY_DAYS} days")

    cat = (facts.get("water_source_category") or {}).get("value")
    if cat is None:
        flag("job", "water category (1/2/3)", "Source not clear from call. Changes PPE and what is salvageable.")
    elif cat == 3:
        item("job", "WTR CAT3", 1, [f"transcript: \"{facts['water_source_category'].get('quote')}\""])

    if depth_gaps:
        flag("job", "confirm water line height",
             f"Caller said ~{job_depth['value']}in (\"{job_depth.get('quote')}\"), photos show water lines of "
             + ", ".join(f"~{wl}in in the {r}" for r, wl in depth_gaps)
             + ". Wicking climbs above standing water; tech should confirm with a moisture meter.")
    for u in facts.get("unverified_areas", []):
        flag(norm(u.get("area")), "moisture reading + photos",
             f"Caller hasn't checked it: \"{u.get('quote')}\". Not billed until there's evidence.")

    return {"line_items": items, "review_queue": review,
            "estimate_total": round(sum(i["total"] for i in items), 2)}


async def extract_facts(client: Client, model: str, transcript: str) -> dict:
    return await client.json_call("0-transcript", model, SYSTEM, transcript, max_tokens=4000)
