"""Stage 4: write line items, read the estimate back, diff, and repair until it matches.

A 200 OK proves nothing. Only the read-back does.
"""
import httpx

FIELDS = ("room", "code", "qty", "unit")


def sig(line: dict) -> tuple:
    return tuple(line[f] for f in FIELDS)


def run(base: str, claim_id: str, line_items: list[dict], max_rounds: int = 4) -> dict:
    http = httpx.Client(base_url=base)
    eid = http.post("/estimates", json={"claim": claim_id}).json()["id"]
    log = []
    pending = list(line_items)

    for rnd in range(1, max_rounds + 1):
        for li in pending:
            http.post(f"/estimates/{eid}/lines", json={f: li[f] for f in FIELDS})

        stored = http.get(f"/estimates/{eid}").json()["lines"]
        stored_sigs = {}
        wrong = []
        for lid, line in stored.items():
            if sig(line) in {sig(li) for li in line_items}:
                stored_sigs[sig(line)] = lid
            else:
                wrong.append(line)
        # Remove corrupted lines so the retry doesn't leave a bad copy behind.
        for line in wrong:
            http.delete(f"/estimates/{eid}/lines/{line['id']}")
        missing = [li for li in line_items if sig(li) not in stored_sigs]
        log.append({"round": rnd, "written": len(pending), "verified": len(stored_sigs),
                    "corrupted_removed": [{f: w[f] for f in FIELDS} for w in wrong],
                    "missing": len(missing)})
        if not missing:
            break
        pending = missing

    final = http.get(f"/estimates/{eid}").json()["lines"]
    ok = sorted(sig(l) for l in final.values()) == sorted(sig(li) for li in line_items)
    return {"estimate_id": eid, "verified": ok, "rounds": log}
