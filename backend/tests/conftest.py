from __future__ import annotations

import asyncio
import hashlib
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


ROOT = Path(__file__).resolve().parents[2]


def _ml_fingerprint() -> str:
    h = hashlib.sha256()
    for f in sorted((ROOT / "ml" / "rakshak_ml").rglob("*")):
        if f.is_file() and f.suffix in (".py", ".json", ".csv") and "__pycache__" not in f.parts:
            h.update(f.read_bytes())
    return h.hexdigest()[:16]


@pytest.fixture(scope="session")
def models_dir() -> str:
    """Quick-trained model pairs (simulated data), cached in .cache and rebuilt when the ML code changes."""
    from rakshak_ml import train

    out = ROOT / ".cache" / "test_models"
    marker = out / "fingerprint.txt"
    fp = _ml_fingerprint()
    if not (
        marker.exists()
        and marker.read_text() == fp
        and (out / "models" / "demo" / "meta.json").exists()
    ):
        rc = train.main(["--out", str(out), "--per-food", "30", "--stride", "6"])
        assert rc == 0
        marker.write_text(fp)
    return str(out / "models")
