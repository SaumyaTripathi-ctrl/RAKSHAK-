"""Application settings (environment variables, prefix ``RAKSHAK_``)."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Public test-vector master key: DEV ONLY. Production must override RAKSHAK_MASTER_KEY_HEX.
DEV_MASTER_KEY_HEX = bytes(range(32)).hex()
DEV_JWT_SECRET = "dev-only-change-me-dev-only-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RAKSHAK_", env_file=".env", extra="ignore")

    env: str = "dev"
    log_level: str = "INFO"
    database_url: str = "sqlite+aiosqlite:///./rakshak.db"
    master_key_hex: str = DEV_MASTER_KEY_HEX
    jwt_secret: str = DEV_JWT_SECRET
    jwt_ttl_minutes: int = 12 * 60
    bcrypt_rounds: int = 12
    auto_create_schema: bool = True  # dev/tests; Docker sets false and runs `alembic upgrade head`
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://localhost:8080"]
    )

    # MQTT (hub -> backend). Disabled by default so unit tests/dev can run without a broker.
    mqtt_enabled: bool = False
    mqtt_host: str = "localhost"
    mqtt_port: int = 8883
    mqtt_username: str = "rakshak-api"
    mqtt_password: str = "dev-api-pass"
    mqtt_ca_file: str | None = None
    mqtt_tls: bool = True
    mqtt_client_id: str = "rakshak-api"

    seed_demo: bool = False

    # Prediction / AI
    predictions_enabled: bool = True
    model_dir: str | None = None  # default: <repo>/ml/artifacts/models (or RAKSHAK_MODEL_DIR)
    ai_commands_enabled: bool = True
    recovery_hold_s: float = 15.0
    weather_enabled: bool = (
        False  # Open-Meteo lookups (rain/wind); off by default so tests/dev need no network
    )
    osrm_enabled: bool = True
    osrm_url: str = "https://router.project-osrm.org"
    facilities_csv: str | None = None

    # Demo / simulator wiring (dev only)
    demo_tools: bool = False  # admin-only DB tamper + restore endpoints for the demo
    simulator_url: str | None = None  # e.g. http://simulator:8100
    simulator_token: str | None = None
    # A hub's offline gap is reported by the hub itself on reconnect (``offline_since``).
    ledger_backend: str = "local"
    ledger_path: str = "./data/ledger.jsonl"
    fabric_bridge_url: str | None = None
    batch_size: int = 50  # records per Merkle batch

    @field_validator("master_key_hex")
    @classmethod
    def _check_master(cls, v: str) -> str:
        if len(v) != 64:
            raise ValueError("master key must be 64 hex chars (32 bytes)")
        bytes.fromhex(v)
        return v.lower()

    @property
    def master_key(self) -> bytes:
        return bytes.fromhex(self.master_key_hex)

    @property
    def using_dev_secrets(self) -> bool:
        return self.master_key_hex == DEV_MASTER_KEY_HEX or self.jwt_secret == DEV_JWT_SECRET


@lru_cache
def get_settings() -> Settings:
    return Settings()
