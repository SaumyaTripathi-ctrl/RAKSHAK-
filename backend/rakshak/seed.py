"""Idempotent demo seed data. Everything here is DEMO content, labelled as such.

Passwords are DEV-ONLY and documented in the README; seeding is only enabled with RAKSHAK_SEED_DEMO=true.
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from .config import Settings
from .db.base import Database
from .db.models import Device, Role, Shipment, User
from .security import hash_password

log = logging.getLogger("rakshak.seed")

DEMO_USERS = [
    # username, password, role, full name, organisation, language
    ("admin", "admin123", Role.ADMIN, "Asha Admin", "Rakshak Ops", "en"),
    ("fpo", "fpo123", Role.FPO, "Ramesh Patil", "Konkan Hapus FPO (demo)", "hi"),
    ("driver", "driver123", Role.DRIVER, "Sunil Jadhav", "Sahyadri Transport (demo)", "hi"),
    ("exporter", "exporter123", Role.EXPORTER, "Meera Shah", "Fresh Exports Ltd (demo)", "en"),
]

DEMO_HUBS = ["HUB-0001", "HUB-0002", "HUB-0003"]
DEMO_TAGS = {  # tag -> hub
    "TAG-0001": "HUB-0001",
    "TAG-0002": "HUB-0001",
    "TAG-0003": "HUB-0001",
    "TAG-0004": "HUB-0002",
    "TAG-0005": "HUB-0002",
    "TAG-0006": "HUB-0002",
    "TAG-0007": "HUB-0003",
    "TAG-0008": "HUB-0003",
    "TAG-0009": "HUB-0003",
}

# Demo routes: real town names with approximate coordinates; the shipments themselves are simulated.
DEMO_SHIPMENTS = [
    dict(
        id="RKS-26-000001",
        food_type="mango",
        variety="Alphonso (Hapus)",
        weight_kg=1200,
        grade="A",
        origin_name="Ratnagiri (demo)",
        origin_lat=16.9902,
        origin_lon=73.3120,
        dest_name="Pune market yard (demo)",
        dest_lat=18.5204,
        dest_lon=73.8567,
        hub_id="HUB-0001",
    ),
    dict(
        id="RKS-26-000002",
        food_type="banana",
        variety="Grand Naine",
        weight_kg=2000,
        grade="A",
        origin_name="Jalgaon (demo)",
        origin_lat=21.0077,
        origin_lon=75.5626,
        dest_name="Nashik pack-house (demo)",
        dest_lat=19.9975,
        dest_lon=73.7898,
        hub_id="HUB-0002",
    ),
    dict(
        id="RKS-26-000003",
        food_type="milk",
        variety="Cow milk, chilled",
        weight_kg=3000,
        grade="",
        origin_name="Anand (demo)",
        origin_lat=22.5645,
        origin_lon=72.9289,
        dest_name="Ahmedabad dairy (demo)",
        dest_lat=23.0225,
        dest_lon=72.5714,
        hub_id="HUB-0003",
    ),
]


async def seed_demo(db: Database, settings: Settings) -> None:
    async with db.session_factory() as s:
        for username, password, role, name, org, lang in DEMO_USERS:
            if (
                await s.execute(select(User).where(User.username == username))
            ).scalar_one_or_none() is None:
                s.add(
                    User(
                        username=username,
                        password_hash=hash_password(password, settings.bcrypt_rounds),
                        role=role.value,
                        full_name=name,
                        organisation=org,
                        language=lang,
                    )
                )
        for hub in DEMO_HUBS:
            if await s.get(Device, hub) is None:
                s.add(Device(id=hub, kind="hub", name=f"Rakshak Hub {hub[-4:]}"))
        for tag, hub in DEMO_TAGS.items():
            if await s.get(Device, tag) is None:
                s.add(Device(id=tag, kind="tag", name=f"Rakshak Tag {tag[-4:]}", hub_id=hub))
        await s.flush()
        for sh in DEMO_SHIPMENTS:
            if await s.get(Shipment, sh["id"]) is None:
                s.add(Shipment(created_by="fpo", **sh))
                hub = await s.get(Device, sh["hub_id"])
                hub.shipment_id = sh["id"]  # type: ignore[union-attr]
                for tag, tag_hub in DEMO_TAGS.items():
                    if tag_hub == sh["hub_id"]:
                        (await s.get(Device, tag)).shipment_id = sh["id"]  # type: ignore[union-attr]
        await s.commit()
    log.info("demo seed applied")
