# API reference

Interactive OpenAPI: `http://localhost:8000/docs`. All `/api/*` routes except `/api/auth/login` and `/api/public/*`
need `Authorization: Bearer <jwt>` (demo accounts are seeded; see `.env.example`). One WebSocket (`/ws`) pushes events
that the frontend patches into its query cache.

| Method & path | Purpose |
|---|---|
| `GET /health` | liveness + MQTT / prediction / ledger status |
| `POST /api/auth/login`, `GET /api/auth/me` | JWT login, current user |
| `GET /api/public/shipments/{id}` | **unauthenticated** QR provenance page data (no device IDs, no raw records) |
| `GET/POST /api/shipments`, `GET /api/shipments/{id}` | list / create / read |
| `GET /api/shipments/{id}/live` | latest readings, flap/fan state, alert tier |
| `GET /api/shipments/{id}/timeline` | samples with gap/historical markers |
| `POST /api/shipments/{id}/bind`, `/close` | bind hub + tags; close shipment |
| `GET /api/shipments/{id}/custody`, `POST .../handover` | custody chain (signed, hash-linked) |
| `GET /api/shipments/{id}/risk` | spoilage risk + remaining safe life + explanation |
| `GET /api/shipments/{id}/reroute`, `POST .../reroute/accept` | detour to nearest compatible cold store |
| `PUT /api/shipments/{id}/model-profile` | choose `real` or time-compressed `demo` model |
| `GET /api/food-types`, `GET /api/facilities` | food bands; **synthetic** cold-storage dataset |
| `GET/POST /api/devices`, `GET /api/devices/{id}` | registry; POST returns the provisioning secret once |
| `POST /api/devices/{id}/rotate-key` | bump `key_epoch`, new key |
| `POST /api/devices/{hub}/cmd` | send `FLAP_SET/FAN_ON/FAN_OFF/ALERT_*/ACK_ALERT` |
| `GET /api/events`, `POST /api/events/{id}/ack` | alerts/events feed, acknowledge |
| `GET /api/fleet/overview` | KPIs and map markers |
| `GET /api/verify/{shipment}` | full recompute: chains, Merkle roots vs ledger, body vs columns |
| `POST /api/shipments/{id}/anchor` | anchor pending batches now |
| `GET /api/ledger/status`, `/entries`, `/proof/{device}/{seq}` | ledger state, entries, Merkle inclusion proof |
| `GET /api/simulator/scenarios`, `/state`; `POST /runs`, `/runs/{id}/inject\|pause\|resume`, `DELETE /runs/{id}`, `POST /stop-all` | drive the **simulated** devices |
| `GET /api/demo/status`; `POST /api/demo/tamper`, `/restore` | demo-only DB tamper tools (`RAKSHAK_DEMO_TOOLS=1`) |
