"""A stand-in for Xactimate. There is no public write API, so real integrations go through
ESX import, a partner integration, or driving the UI, and all of those can fail silently.
This mock reproduces that: it accepts writes and sometimes quietly corrupts them.
"""
import random
import threading
import time
import uuid

import httpx
import uvicorn
from fastapi import FastAPI

app = FastAPI(title="Mock Xact")
DB: dict[str, dict] = {}
FAULT_RATE = 0.15
rng = random.Random()


@app.post("/estimates")
def create_estimate(body: dict):
    eid = uuid.uuid4().hex[:8]
    DB[eid] = {"id": eid, "claim": body.get("claim"), "rooms": {}, "lines": {}}
    return DB[eid]


@app.post("/estimates/{eid}/lines")
def add_line(eid: str, line: dict):
    lid = uuid.uuid4().hex[:8]
    r = rng.random()
    if r < FAULT_RATE / 3:
        return {"id": lid, "status": "ok"}  # silently dropped: 200 OK, never stored
    stored = dict(line)
    if r < FAULT_RATE * 2 / 3:
        stored["qty"] = float(int(stored["qty"]))  # truncated decimals, like a bad UI field
    elif r < FAULT_RATE:
        stored["room"] = "Main Level"  # landed in the default room
    DB[eid]["lines"][lid] = {"id": lid, **stored}
    return {"id": lid, "status": "ok"}


@app.delete("/estimates/{eid}/lines/{lid}")
def delete_line(eid: str, lid: str):
    DB[eid]["lines"].pop(lid, None)
    return {"status": "ok"}


@app.get("/estimates/{eid}")
def get_estimate(eid: str):
    return DB[eid]


def serve(port: int = 0, fault_rate: float | None = None) -> str:
    global FAULT_RATE
    if fault_rate is not None:
        FAULT_RATE = fault_rate
    if not port:  # pick a free port so parallel runs don't share (and lose) one mock
        import socket
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    for _ in range(50):
        try:
            httpx.get(f"{base}/docs")
            return base
        except httpx.ConnectError:
            time.sleep(0.1)
    raise RuntimeError("mock Xact did not start")
