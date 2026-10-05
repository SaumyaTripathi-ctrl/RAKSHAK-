"""Read models: live state, timelines and the public provenance document."""

from __future__ import annotations

from statistics import mean

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Device, Event, Handover, OfflineSegment, Record, Shipment
from .ingest import event_to_dict

MAX_POINTS = 1500


def rec_time(r: Record) -> int:
    return r.time_utc if r.time_utc is not None else int(r.received_at.timestamp())


def _downsample(rows: list, limit: int) -> list:
    if len(rows) <= limit:
        return rows
    step = len(rows) / limit
    return [rows[int(i * step)] for i in range(limit)] + [rows[-1]]


async def _latest_sample(
    session: AsyncSession, device_id: str, shipment_id: str | None = None
) -> Record | None:
    """Newest hub/tag sample of a device, scoped to one shipment (a hub is reused across trips)."""
    q = select(Record).where(Record.device_id == device_id, Record.rtype.in_((1, 2)))
    if shipment_id is not None:
        q = q.where(Record.shipment_id == shipment_id)
    return (await session.execute(q.order_by(Record.seq.desc()).limit(1))).scalar_one_or_none()


def device_dict(d: Device) -> dict:
    return {
        "device_id": d.id,
        "kind": d.kind,
        "name": d.name,
        "hub_id": d.hub_id,
        "battery_pct": d.battery_pct,
        "firmware_version": d.firmware_version,
        "last_seen_at": d.last_seen_at.isoformat() if d.last_seen_at else None,
        "online": d.online,
        "backlog": d.backlog,
        "offline_since": d.offline_since,
    }


async def shipment_devices(session: AsyncSession, shipment: Shipment) -> list[Device]:
    """Devices that reported for this shipment, plus (while it is open) the ones currently bound to it.

    A finished shipment must keep showing *its* devices and history even after the hub and tags were
    re-bound to the next trip.
    """
    ids = set(
        (
            await session.execute(
                select(Record.device_id).where(Record.shipment_id == shipment.id).distinct()
            )
        ).scalars()
    )
    if shipment.status != "DELIVERED":
        ids |= set(
            (
                await session.execute(select(Device.id).where(Device.shipment_id == shipment.id))
            ).scalars()
        )
        if shipment.hub_id:
            ids.add(shipment.hub_id)
    if not ids:
        return []
    q = select(Device).where(Device.id.in_(ids)).order_by(Device.id)
    return list((await session.execute(q)).scalars())


async def shipment_live(session: AsyncSession, shipment: Shipment) -> dict:
    devices = await shipment_devices(session, shipment)
    hub_dev = next((d for d in devices if d.kind == "hub"), None)
    hub = None
    if hub_dev is not None:
        r = await _latest_sample(session, hub_dev.id, shipment.id)
        hub = {
            **device_dict(hub_dev),
            "time_utc": rec_time(r) if r else None,
            "temp_c": r.temp_c if r else None,
            "rh_pct": r.rh_pct if r else None,
            "shock_g": r.shock_g if r else None,
            "lat": r.lat if r else None,
            "lon": r.lon if r else None,
            "flap_pct": r.flap_pct if r else None,
            "fan_on": r.fan_on if r else None,
            "alert_level": r.alert_level if r else None,
        }
        if r is not None and r.lat is None:  # last sample had no GPS fix: fall back to last known
            last_fix = (
                await session.execute(
                    select(Record)
                    .where(
                        Record.device_id == hub_dev.id,
                        Record.shipment_id == shipment.id,
                        Record.lat.is_not(None),
                    )
                    .order_by(Record.seq.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if last_fix:
                hub["lat"], hub["lon"] = last_fix.lat, last_fix.lon
    tags = []
    for d in devices:
        if d.kind != "tag":
            continue
        r = await _latest_sample(session, d.id, shipment.id)
        tags.append(
            {
                **device_dict(d),
                "time_utc": rec_time(r) if r else None,
                "temp_c": r.temp_c if r else None,
                "rh_pct": r.rh_pct if r else None,
                "ethylene_idx": r.ethylene_idx if r else None,
                "lid_open": r.lid_open if r else None,
            }
        )
    temps = [t["temp_c"] for t in tags if t["temp_c"] is not None]
    rhs = [t["rh_pct"] for t in tags if t["rh_pct"] is not None]
    eths = [t["ethylene_idx"] for t in tags if t["ethylene_idx"] is not None]
    aggregates = {
        "temp_c": mean(temps) if temps else (hub or {}).get("temp_c"),
        "temp_max_c": max(temps) if temps else None,
        "rh_pct": mean(rhs) if rhs else (hub or {}).get("rh_pct"),
        "ethylene_idx": max(eths) if eths else None,
        "lid_open": any(t["lid_open"] for t in tags),
    }
    return {
        "shipment_id": shipment.id,
        "hub": hub,
        "tags": tags,
        "aggregates": aggregates,
        "sync": {
            "online": hub_dev.online if hub_dev else None,
            "backlog": hub_dev.backlog if hub_dev else 0,
            "offline_since": hub_dev.offline_since if hub_dev else None,
        },
        "risk": None,  # filled by the prediction service (Phase 4)
    }


async def shipment_timeline(
    session: AsyncSession,
    shipment_id: str,
    *,
    since: int | None = None,
    include_events: bool = True,
) -> dict:
    q = select(Record).where(Record.shipment_id == shipment_id, Record.rtype.in_((1, 2)))
    rows = list((await session.execute(q.order_by(Record.seq))).scalars())
    pts = [(rec_time(r), r) for r in rows]
    pts.sort(key=lambda x: x[0])
    if since is not None:
        pts = [p for p in pts if p[0] >= since]

    hub_rows = _downsample([p for p in pts if p[1].rtype == 2], MAX_POINTS)
    hub = [
        {
            "t": t,
            "temp_c": r.temp_c,
            "rh_pct": r.rh_pct,
            "shock_g": r.shock_g,
            "flap_pct": r.flap_pct,
            "fan_on": r.fan_on,
            "batt_pct": r.batt_pct,
            "alert_level": r.alert_level,
            "estimated": r.time_estimated,
        }
        for t, r in hub_rows
    ]
    gps = [
        {"t": t, "lat": r.lat, "lon": r.lon}
        for t, r in _downsample(
            [p for p in pts if p[1].rtype == 2 and p[1].lat is not None], MAX_POINTS
        )
    ]
    tags: dict[str, list[dict]] = {}
    by_tag: dict[str, list] = {}
    for t, r in pts:
        if r.rtype == 1:
            by_tag.setdefault(r.device_id, []).append((t, r))
    for dev, items in by_tag.items():
        tags[dev] = [
            {
                "t": t,
                "temp_c": r.temp_c,
                "rh_pct": r.rh_pct,
                "ethylene_idx": r.ethylene_idx,
                "lid_open": r.lid_open,
                "estimated": r.time_estimated,
            }
            for t, r in _downsample(items, MAX_POINTS)
        ]
    segs = list(
        (
            await session.execute(
                select(OfflineSegment)
                .where(OfflineSegment.shipment_id == shipment_id)
                .order_by(OfflineSegment.start_ts)
            )
        ).scalars()
    )
    out = {
        "shipment_id": shipment_id,
        "hub": hub,
        "tags": tags,
        "gps": gps,
        "offline_segments": [
            {"start": s.start_ts, "end": s.end_ts, "backlog_at_end": s.backlog_at_end} for s in segs
        ],
    }
    if include_events:
        ev = list(
            (
                await session.execute(
                    select(Event)
                    .where(Event.shipment_id == shipment_id)
                    .order_by(Event.id.desc())
                    .limit(200)
                )
            ).scalars()
        )
        out["events"] = [event_to_dict(e) for e in ev]
    return out


def handover_public(h: Handover) -> dict:
    """Public view of a hand-over: organisation and role, never usernames or keys."""
    return {
        "stage": h.stage,
        "organisation": h.organisation,
        "role": h.actor_role,
        "location": h.location,
        "lat": h.lat,
        "lon": h.lon,
        "at": h.created_at.isoformat(),
        "anchored": h.ledger_ref is not None,
    }


async def public_provenance(session: AsyncSession, shipment: Shipment) -> dict:
    tl = await shipment_timeline(session, shipment.id, include_events=False)
    handovers = list(
        (
            await session.execute(
                select(Handover).where(Handover.shipment_id == shipment.id).order_by(Handover.id)
            )
        ).scalars()
    )
    ev_rows = list(
        (await session.execute(select(Event).where(Event.shipment_id == shipment.id))).scalars()
    )
    alerts: dict[str, int] = {}
    for e in ev_rows:
        if e.severity in ("warning", "critical"):
            alerts[e.kind] = alerts.get(e.kind, 0) + 1
    tag_points = [p for series in tl["tags"].values() for p in series if p["temp_c"] is not None]
    # Average across tags on a common time grid (bucketed by minute) for a compact chart.
    buckets: dict[int, list[dict]] = {}
    for p in tag_points:
        buckets.setdefault(p["t"] // 60 * 60, []).append(p)
    chart = [
        {
            "t": t,
            "temp_c": round(mean(x["temp_c"] for x in pts), 2),
            "rh_pct": round(mean(x["rh_pct"] for x in pts if x["rh_pct"] is not None), 1)
            if any(x["rh_pct"] is not None for x in pts)
            else None,
            "ethylene_idx": round(max((x["ethylene_idx"] or 0) for x in pts), 1),
        }
        for t, pts in sorted(buckets.items())
    ]
    chart = _downsample(chart, 300)
    temps = [p["temp_c"] for p in tag_points]
    return {
        "shipment_id": shipment.id,
        "food_type": shipment.food_type,
        "variety": shipment.variety,
        "weight_kg": shipment.weight_kg,
        "grade": shipment.grade,
        "origin": {
            "name": shipment.origin_name,
            "lat": shipment.origin_lat,
            "lon": shipment.origin_lon,
        },
        "destination": {
            "name": shipment.dest_name,
            "lat": shipment.dest_lat,
            "lon": shipment.dest_lon,
        },
        "status": shipment.status,
        "created_at": shipment.created_at.isoformat(),
        "journey": [handover_public(h) for h in handovers],
        "route": [{"lat": g["lat"], "lon": g["lon"]} for g in tl["gps"]],
        "chart": chart,
        "offline_segments": tl["offline_segments"],
        "summary": {
            "records": len(tag_points),
            "temp_min_c": min(temps) if temps else None,
            "temp_max_c": max(temps) if temps else None,
            "temp_avg_c": round(mean(temps), 2) if temps else None,
            "alerts": alerts,
            "tamper_events": sum(v for k, v in alerts.items() if k.startswith("TAMPER")),
        },
        "ledger": {"verified": None, "note": "ledger verification not available"},
    }
