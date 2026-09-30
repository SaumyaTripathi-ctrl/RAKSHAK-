"""Scripted end-to-end demo: drives the running stack (docker compose up) through the whole Rakshak story.

    python tools/demo.py                      # ~4-5 real minutes at the default speed
    python tools/demo.py --accel 400          # faster
    python tools/demo.py --restore            # undo the demo database tamper at the end

Story (all devices are SIMULATED): live shipment -> heat -> PCM flap opens -> ethylene rises -> fan on ->
network cut -> logging continues -> reconnect -> backlog syncs, chart gap fills -> risk CRITICAL -> reroute ->
tamper injected -> Verify shows TAMPERED -> public QR page. Exit status is non-zero if a milestone is missing.
"""

from __future__ import annotations

import argparse
import sys
import time

import httpx


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--web", default="http://localhost:8080")
    ap.add_argument("--hub", default="HUB-0001")
    ap.add_argument("--accel", type=float, default=120.0, help="device seconds per real second")
    ap.add_argument("--timeout", type=float, default=900.0)
    ap.add_argument("--restore", action="store_true", help="undo the database tamper at the end")
    a = ap.parse_args()

    http = httpx.Client(base_url=a.api, timeout=30)
    log(f"waiting for the API at {a.api} ...")
    for _ in range(120):
        try:
            if http.get("/health").status_code == 200:
                break
        except httpx.HTTPError:
            pass
        time.sleep(2)
    else:
        log("API did not come up (is `docker compose up` running?)")
        return 2
    h = http.get("/health").json()
    log(f"API up: mqtt={h['mqtt']} prediction={h['prediction']} ledger={h['ledger']}")
    if not h["prediction"]["active"]:
        log("WARNING: no prediction models loaded - risk/AI steps will be missing")

    tok = http.post("/api/auth/login", json={"username": "admin", "password": "admin123"}).json()[
        "access_token"
    ]
    http.headers["Authorization"] = f"Bearer {tok}"

    r = http.post(
        "/api/simulator/runs",
        json={
            "scenario": "demo_full",
            "hub_id": a.hub,
            "accel": a.accel,
            "seed": 1,
            "new_shipment": True,
        },
    )
    if r.status_code >= 400:
        log(f"could not start the simulator run: {r.status_code} {r.text}")
        return 2
    run = r.json()
    sid, run_id = run["shipment_id"], run["id"]
    log(
        f"demo run {run_id} on {a.hub}, shipment {sid} ({run['food_type']}, profile {run['profile']}, SIMULATED)"
    )
    log(f"watch it live: {a.web}/shipments/{sid}     QR page: {a.web}/p/{sid}")

    seen_events: set[int] = set()
    printed_log: set[str] = set()
    milestones = {k: False for k in (
        "flap opened", "ethylene rose", "fan on", "network cut", "backlog synced", "risk WARNING",
        "risk CRITICAL", "reroute recommended", "detour accepted", "tamper detected at ingest",
        "verify TAMPERED", "QR page not verified",
    )}  # fmt: skip
    t0 = time.time()
    state = run
    while time.time() - t0 < a.timeout:
        time.sleep(2)
        state = http.get(f"/api/simulator/runs/{run_id}").json()
        snap = state["snapshot"]
        for ln in state["log"]:
            if ln not in printed_log:
                printed_log.add(ln)
                log(f"  device: {ln}")
        live = http.get(f"/api/shipments/{sid}/live").json()
        risk = live.get("risk") or {}
        hub = live.get("hub") or {}
        log(
            f"T+{snap['elapsed_min']:>5.0f} min  temp {snap['temperature']:5.1f} C  ethylene {snap['ethylene_index']:5.1f}  "
            f"flap {snap['flap']:>3}%  fan {'ON ' if snap['fan'] else 'off'}  net {'up  ' if snap['connected'] else 'DOWN'} "
            f"backlog {snap['backlog']:>4}  risk {risk.get('risk', '-')} {risk.get('level', '')}"
        )
        if snap["flap"] > 0:
            milestones["flap opened"] = True
        if snap["ethylene_index"] > 40:
            milestones["ethylene rose"] = True
        if snap["fan"]:
            milestones["fan on"] = True
        if not snap["connected"]:
            milestones["network cut"] = True
        if (
            milestones["network cut"]
            and snap["connected"]
            and snap["backlog"] == 0
            and (hub.get("backlog") == 0)
        ):
            milestones["backlog synced"] = True
        for ev in http.get("/api/events", params={"shipment_id": sid, "limit": 100}).json()[::-1]:
            if ev["id"] in seen_events:
                continue
            seen_events.add(ev["id"])
            if ev["kind"] in ("LEDGER_ANCHORED", "GAP_FILLED"):
                continue
            log(f"  EVENT {ev['severity'].upper():8} {ev['kind']}: {ev['message']}")
            k = ev["kind"]
            if k == "ALERT_WARNING" and ev["data"].get("source") == "ai":
                milestones["risk WARNING"] = True
            if k == "ALERT_CRITICAL" and ev["data"].get("source") == "ai":
                milestones["risk CRITICAL"] = True
            if k == "REROUTE":
                milestones[
                    "detour accepted" if "accepted" in ev["message"] else "reroute recommended"
                ] = True
            if k in ("TAMPER_BAD_HASH", "MISSING_RECORDS"):
                milestones["tamper detected at ingest"] = True
        if state["state"] in ("finished", "stopped", "error"):
            break

    log(f"run {state['state']}" + (f": {state['error']}" if state.get("error") else ""))
    time.sleep(3)
    v = http.get(f"/api/verify/{sid}").json()
    log(
        f"VERIFY -> {v['status']}  ({v['anchored_records']} of {v['total_records']} records anchored, ledger: {v['ledger']['backend']})"
    )
    for b in v["batches"]:
        if b["problems"]:
            log(f"  batch {b['batch_id']} {b['status']}: {b['problems'][0]}")
    milestones["verify TAMPERED"] = v["status"] == "TAMPERED"
    doc = httpx.get(f"{a.api}/api/public/shipments/{sid}").json()
    milestones["QR page not verified"] = doc["ledger"]["verified"] is False
    log(
        f"QR PAGE -> verified={doc['ledger']['verified']} status={doc['ledger']['status']}  {a.web}/p/{sid}"
    )
    if a.restore:
        log(
            f"restored {http.post('/api/demo/restore', json={'shipment_id': sid}).json()['restored']} tampered record(s)"
        )

    print("\nMilestones")
    for k, ok in milestones.items():
        print(f"  [{'OK ' if ok else 'MISS'}] {k}")
    return 0 if all(milestones.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
