# Rakshak

Low-cost, solar-assisted, **offline-first** IoT traceability for rural farm-to-fork transport of fruit,
vegetables and dairy — Smart India Hackathon **SIH26232** (Ministry of Food Processing Industries, Hardware).

**Sense → Predict → Preserve → Secure → Trace.** Crate **Tags** log temperature, humidity and ethylene (colour
strip); a truck **Hub** adds GPS and shock, runs edge rules (adaptive PCM flap, ethylene scrubber fan), keeps
logging with no network, and syncs over MQTT/TLS when 4G returns. Every record is AES-256-GCM encrypted and
SHA-256 hash-chained; the backend verifies chains, predicts spoilage (risk + remaining safe life), reroutes to
the nearest compatible cold store, and anchors a Merkle root per batch on a ledger. A public QR page shows the
verified journey.

> **Status: complete prototype.** Everything simulated is labelled simulated (ML training data, cold-storage
> dataset, device traffic). Firmware is **compile-tested only, not hardware-tested.** Read `docs/LIMITATIONS.md`.
> Evolved from our MedRakshak (SIH26215) prototype.

## Layout

| Path | What |
|---|---|
| `firmware/common/` | C record/crypto library + **normative spec** (`spec/RECORD_SPEC.md`) + test vectors |
| `firmware/tag_esp32c3/`, `firmware/hub_esp32s3/` | PlatformIO projects (Arduino-ESP32 ≥ 3.0) |
| `backend/` | FastAPI app; `backend/rakshak/codec/` is the Python reference codec |
| `ml/` | produce simulator, training, evaluation, model cards |
| `ledger/` | ledger interface, local hash-ledger, optional Hyperledger Fabric |
| `simulator/` | virtual hub + tags publishing real MQTT traffic |
| `frontend/` | React + Vite + TypeScript dashboard |
| `infra/` | Mosquitto (TLS + ACL), Postgres init, dev-cert script |
| `docs/` | `ARCHITECTURE.md`, `API.md`, `PROTOCOL.md`, `DEMO.md`, `DECISIONS.md`, `LIMITATIONS.md`, `PROVISIONING.md` |

## Run (Windows, Docker Desktop)

Requires [Docker Desktop](https://www.docker.com/products/docker-desktop/) (WSL2 backend) running, and
Git for Windows.

```powershell
scripts\up.ps1        # or: docker compose up --build
scripts\test.ps1      # all tests
scripts\demo.ps1      # scripted end-to-end demo
```

Linux/macOS: `make up`, `make test`, `make demo`. Every Makefile target has a `scripts\*.ps1` twin.

## One-command run

`scripts\up.ps1` (Windows) or `docker compose up --build` starts Mosquitto (TLS + ACL), Postgres, the API, the web
dashboard (<http://localhost:8080>, demo-account buttons on the login page) and the simulator with seed data.
Then `scripts\demo.ps1` / `make demo` plays the full story (heat -> flap -> ethylene -> fan -> network cut -> backlog
sync -> CRITICAL -> reroute -> tamper -> Verify says TAMPERED -> QR page); see `docs/DEMO.md`.

## Tests

`scripts\test.ps1` / `make test`: pytest (backend, ML, simulator), host C tests (codec vectors, ring/device, edge rules),
frontend (vitest, tsc, eslint). Firmware builds: `pio run -d firmware/tag_esp32c3` and `-d firmware/hub_esp32s3`.

## Cross-language correctness

The Python and C codecs must produce identical bytes. `tools/gen_vectors.py` writes
`firmware/common/spec/vectors.json` (+ a C header); `backend/tests/test_codec.py` and
`firmware/common/test/test_vectors.c` both verify them, and CI fails if either side drifts.

## License

MIT — see `LICENSE`.
