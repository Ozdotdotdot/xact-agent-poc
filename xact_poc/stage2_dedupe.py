"""Stage 2: per-photo observations -> rooms -> unique wet walls.

Hierarchical, so no call ever sees all 40 photos:
  2a  photo -> room   text-only. Uses Stage 1 summaries, capture-time gaps (people shoot one room at a time)
                      and water line height (water settles at one level per room).
  2b  room -> walls   ONE vision call per room on a labeled thumbnail grid of just that room's photos.
                      Matching "left wall" in one photo to "back wall" in another from text alone is
                      unreliable; seeing every angle of one room at once is not.
  2c  code merges     water line per wall (tape-measure readings beat reference-object estimates),
                      floors, conflicts, ambiguity.
"""
import asyncio
import base64
import io
import json
from datetime import datetime
from pathlib import Path
from statistics import median

from PIL import Image, ImageDraw, ImageFont, ImageOps

from .llm import Client

ROOMS_SYSTEM = """You are sorting photos from one water-loss claim into rooms.

You get the rooms named on the phone call WITH what the caller said about each (size, flooring, which
walls got wet), and for each photo: capture time, seconds since the previous
photo, the photo reviewer's room guess and evidence, a description, and water line heights seen.

Evidence, strongest first:
1. Distinctive contents and features (a bed, a specific couch through a doorway, a stair rail).
2. Capture sequence: people photograph one room at a time. A gap of minutes usually means a new room;
   consecutive photos seconds apart are usually the same room.
3. Water line height: water settles at one level per room, so similar heights suggest the same room.
4. What the caller said: "only one wall got wet" means that room's photos show a single taped wall.
The reviewer's room guess is the WEAKEST signal. It often calls an empty room "office" or "bedroom".
Do not assign photos to a room just because the caller named it; a caller can name rooms that were
never photographed.

If two rooms look alike and nothing above tells them apart, still pick the likelier one, but give those
photos confidence below 0.5 and say so in "why". A wrong confident label is worse than an honest unsure one.

Return JSON only:
{"assignments": [{"photo": "IMG_0001.jpg", "room": "<a known room, or 'unlisted: <name>'>",
                  "confidence": 0.0-1.0, "why": "under 15 words"}]}"""

WALLS_SYSTEM = """These photos are all of ONE room ({room}) after a water loss. The technician marked the
water line on each wet wall with a horizontal strip of masking/painter's tape.

Count the DISTINCT physical walls that have tape. The same wall appears in several photos from different
angles; use doors, outlets, switches, pictures, windows and corners to match them. A tape strip that turns
a corner is two walls. Close-ups (e.g. a tape measure against the wall) belong to whichever wall they
match; if you cannot tell, list them under "unmatched".
Also list any photo that does not look like it is from this room.

Return JSON only:
{{"walls": [{{"wall": "short name, e.g. 'wall with closet door and thermostat'", "photos": ["IMG_..."],
             "confidence": 0.0-1.0}}],
 "unmatched": ["IMG_..."], "not_this_room": ["IMG_..."], "notes": "under 25 words"}}"""


def capture_times(photo_dir: Path) -> dict[str, datetime]:
    out = {}
    for p in photo_dir.iterdir():
        try:
            t = Image.open(p).getexif().get_ifd(0x8769).get(36867)
            out[p.name] = datetime.strptime(t, "%Y:%m:%d %H:%M:%S")
        except Exception:
            pass
    return out


def grid(photo_dir: Path, photos: list[str], cell: int = 360) -> dict:
    cols = 3 if len(photos) > 4 else 2
    rows = (len(photos) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cell, rows * (cell + 28)), "white")
    d = ImageDraw.Draw(sheet)
    font = ImageFont.load_default(size=22)
    for i, name in enumerate(photos):
        im = ImageOps.exif_transpose(Image.open(photo_dir / name)).convert("RGB")
        im.thumbnail((cell, cell))
        x, y = (i % cols) * cell, (i // cols) * (cell + 28)
        sheet.paste(im, (x, y + 28))
        d.text((x + 4, y + 2), name, fill="black", font=font)
    sheet.thumbnail((1568, 1568))
    buf = io.BytesIO()
    sheet.save(buf, "JPEG", quality=85)
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                        "data": base64.b64encode(buf.getvalue()).decode()}}


def wall_obs(o: dict) -> list[dict]:
    return [s for s in o.get("surfaces", []) if s.get("surface") == "wall"]


def water_line(obs: list[dict]) -> tuple[float | None, list[dict]]:
    """Prefer readings taken against a tape measure; fall back to the median of reference-object estimates."""
    est = [{"in": s["water_line_in"], "ref": s["water_line_reference"]}
           for o in obs for s in wall_obs(o)
           if s.get("water_line_in") is not None and s.get("water_line_reference")]
    measured = [e for e in est if "tape measure" in e["ref"].lower()]
    use = measured or est
    return (median(e["in"] for e in use) if use else None), use


async def assign_rooms(client: Client, model: str, observations: list[dict], known_rooms: dict[str, dict],
                       times: dict[str, datetime]) -> dict[str, dict]:
    ordered = sorted(observations, key=lambda o: (times.get(o["photo"], datetime.max), o["photo"]))
    rows, prev = [], None
    for o in ordered:
        t = times.get(o["photo"])
        rows.append({"photo": o["photo"], "time": t.strftime("%H:%M:%S") if t else None,
                     "gap_s": int((t - prev).total_seconds()) if t and prev else None,
                     "room_guess": o.get("room"), "room_evidence": o.get("room_evidence"), "view": o.get("view"),
                     "water_lines_in": [s["water_line_in"] for s in wall_obs(o) if s.get("water_line_in") is not None]})
        prev = t or prev
    prompt = f"KNOWN ROOMS: {json.dumps(known_rooms)}\n\nPHOTOS IN CAPTURE ORDER:\n{json.dumps(rows)}"
    out = await client.json_call("3-rooms", model, ROOMS_SYSTEM, prompt, max_tokens=4000)
    return {a["photo"]: a for a in out["assignments"]}


async def walls_for_room(client: Client, model: str, room: str, photos: list[str], photo_dir: Path) -> dict:
    content = [grid(photo_dir, photos), {"type": "text", "text": f"Photos: {', '.join(photos)}"}]
    return await client.json_call("4-walls", model, WALLS_SYSTEM.format(room=room), content, max_tokens=3000)


async def run(client: Client, model: str, observations: list[dict], known_rooms: dict[str, dict],
              photo_dir: Path, room_tags: dict[str, str] | None = None) -> dict:
    """known_rooms: room name -> what the caller said about it (quotes, sizes, flooring).
    room_tags: photo -> room recorded at capture time (guided capture). When present, 2a is skipped:
    each room's photos go straight to that room's wall call."""
    obs_by_photo = {o["photo"]: o for o in observations if "error" not in o}
    if room_tags:
        assign = {p: {"photo": p, "room": r, "confidence": 1.0, "why": "tagged at capture"}
                  for p, r in room_tags.items() if p in obs_by_photo}
    else:
        assign = await assign_rooms(client, model, list(obs_by_photo.values()), known_rooms, capture_times(photo_dir))

    by_room: dict[str, list[str]] = {}
    for photo, a in assign.items():
        if photo in obs_by_photo:
            by_room.setdefault(a["room"].lower(), []).append(photo)
    wet = {r: sorted(ps) for r, ps in by_room.items()
           if any(s.get("water_line_in") is not None for p in ps for s in wall_obs(obs_by_photo[p]))}
    wall_maps = dict(zip(wet, await asyncio.gather(
        *(walls_for_room(client, model, r, ps, photo_dir) for r, ps in wet.items()))))

    surfaces = []
    for room, photos in by_room.items():
        low_conf = [p for p in photos if assign[p].get("confidence", 1) < 0.6]
        if len(low_conf) * 2 >= len(photos):
            surfaces.append({"key": f"{room}/note/sorting", "room": room, "surface": "note",
                             "locator": "room sorting", "materials": [], "damage": [], "water_line_in": None,
                             "water_line_estimates": [], "photos": low_conf, "confidence": 0, "ambiguous": True,
                             "conflicts": [f"Unsure these {len(low_conf)} photos are the {room}: "
                                           f"{assign[low_conf[0]].get('why', '')}. A room tag at capture removes this."]})
        wm = wall_maps.get(room, {"walls": [], "unmatched": [], "not_this_room": []})
        n_walls = len(wm["walls"])
        for w in wm["walls"]:
            ps = [p for p in w["photos"] if p in obs_by_photo]
            wl, used = water_line([obs_by_photo[p] for p in ps])
            if wl is None:  # wall identified but no photo of it had an anchor; borrow the room's level
                wl, used = water_line([obs_by_photo[p] for p in photos])
            mats = sorted({s.get("material") for p in ps for s in wall_obs(obs_by_photo[p])
                           if s.get("material") not in (None, "unknown", "trim", "baseboard")})
            surfaces.append({
                "key": f"{room}/wall/{w['wall']}", "room": room, "surface": "wall", "locator": w["wall"],
                "materials": mats,
                "damage": sorted({d for p in ps for s in wall_obs(obs_by_photo[p]) for d in s.get("damage", [])
                                  if d != "none visible"}),
                "water_line_in": wl, "water_line_estimates": used, "photos": sorted(ps),
                "confidence": w.get("confidence", 0.5),
                "ambiguous": w.get("confidence", 1) < 0.6 or bool(set(ps) & set(low_conf)),
                "conflicts": [f"materials disagree: {mats}"] if len(mats) > 1 else [],
            })
        for p in wm.get("not_this_room", []):
            surfaces.append({"key": f"{room}/note/{p}", "room": room, "surface": "note",
                             "locator": f"{p} may not be from the {room}", "materials": [], "damage": [],
                             "water_line_in": None, "water_line_estimates": [], "photos": [p],
                             "confidence": 0, "ambiguous": True, "conflicts": [f"{p} may not be from the {room}"]})
        floor_ps = [p for p in photos if any(s.get("surface") == "floor" and s.get("damage") not in (None, [], ["none visible"])
                                             for s in obs_by_photo[p].get("surfaces", []))]
        if floor_ps:
            mats = sorted({s.get("material") for p in floor_ps for s in obs_by_photo[p]["surfaces"]
                           if s.get("surface") == "floor" and s.get("material") not in (None, "unknown")})
            surfaces.append({"key": f"{room}/floor", "room": room, "surface": "floor", "locator": "floor",
                             "materials": mats, "damage": ["water"], "water_line_in": None,
                             "water_line_estimates": [], "photos": floor_ps, "confidence": 0.7,
                             "ambiguous": False, "conflicts": []})

    return {"rooms": {r: {"photos": ps, "wet_walls": len(wall_maps.get(r, {}).get("walls", [])),
                          "unmatched": wall_maps.get(r, {}).get("unmatched", [])} for r, ps in by_room.items()},
            "assignments": assign,
            "raw_observations": sum(len(o.get("surfaces", [])) for o in obs_by_photo.values()),
            "unique_surfaces": len([s for s in surfaces if s["surface"] != "note"]),
            "surfaces": surfaces}
