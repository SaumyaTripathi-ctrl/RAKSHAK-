from __future__ import annotations

import asyncio
import sys
import tempfile
import uuid
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from rakshak.config import Settings
from rakshak.main import create_app

if sys.platform == "win32":  # aiomqtt needs a selector loop
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


_TMP = Path(tempfile.mkdtemp(prefix="rakshak-tests-"))


def make_settings(**kw) -> Settings:
    base = dict(
        database_url="sqlite+aiosqlite:///:memory:",
        seed_demo=True,
        mqtt_enabled=False,
        log_level="WARNING",
        bcrypt_rounds=4,
        ledger_path=str(_TMP / f"ledger-{uuid.uuid4().hex}.jsonl"),
        batch_size=5,
    )
    base.update(kw)
    return Settings(**base)


@pytest_asyncio.fixture
async def app():
    application = create_app(make_settings())
    async with application.router.lifespan_context(application):
        yield application


@pytest_asyncio.fixture
async def client(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def login(
    client: httpx.AsyncClient, username: str, password: str | None = None
) -> dict[str, str]:
    pw = password or f"{username}123"
    r = await client.post("/api/auth/login", json={"username": username, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest_asyncio.fixture
async def admin(client):
    return await login(client, "admin")


@pytest_asyncio.fixture
async def fpo(client):
    return await login(client, "fpo")


@pytest.fixture
def anyio_backend():
    return "asyncio"
