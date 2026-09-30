# Device simulator

A **virtual Rakshak hub + crate tags** that speak the real wire protocol, so the whole system runs end to end with
no hardware. **Everything it produces is simulated and labelled as such** (`"simulated": true` in its API).

What is real:

* the record format, AES-256-GCM encryption and SHA-256 hash chain (it imports the production codec, `rakshak.codec`);
* per-device HKDF keys (`key_epoch`), persisted `seq` (like NVS), store-and-forward queue, oldest-first burst sync;
* MQTT over TLS with a persistent session, QoS 1 and a **last-will** (the broker announces the hub as offline when its
  socket dies, exactly like a dropped 4G link);
* the hub's no-network edge rules (`rakshak_ml.edge`): PCM flap 0/25/50/100 % by temperature deviation, scrubber fan by
  ethylene trend, LED/buzzer tiers with a latching alarm, and the command semantics the firmware implements.

What is simulated: the physics (`rakshak_ml/sim.py`: thermal lag, PCM cooling that depletes, ripening, ethylene, shocks),
the route, the batteries, and the people.

## Scenarios

| Name | What happens |
|---|---|
| `normal_trip` | pre-cooled mango, steady in-band trip; risk stays SAFE; hand-overs FARM → TRANSPORT → COLD_STORAGE → RETAIL |
| `heat_excursion` | heat wave: the hub opens the flap with no network needed; risk climbs to WARNING |
| `banana_ripening` | mixed load raises ethylene; fan switches on; the index falls when the source is gone |
| `rural_no_network` | 4G drops for 60 min: sensing and actions continue, records queue, burst-sync on return |
| `tamper` | lid opened, a record edited (bad hash), a record deleted (gap), then a DB row edited → Verify says TAMPERED |
| `critical_reroute` | no cooling on a hot day → CRITICAL → the AI finds a compatible cold store and the truck follows the detour |
| `demo_full` | all of the above in one scripted run (`tools/demo.py`, `make demo`) |

Default profile is `demo` (physics and the matching *demo* model pair time-compressed 24×); `accel` (device seconds per
real second, default 60) sets the pace. Time acceleration changes only how fast ticks are issued.

## Control API (port 8100, internal; the backend proxies it for admins under `/api/simulator/*`)

```
GET  /scenarios                       scenarios + available injections
GET  /state                           all runs, with a live snapshot and the device log
POST /runs {scenario, hub_id?, accel?, profile?, food_type?, new_shipment?}
POST /runs/{id}/inject {action, params}   heat | ethylene | shock | spike | lid_open | lid_close | reboot_tag |
                                          ble_drop | ble_restore | network_cut | network_restore | tamper_forge |
                                          tamper_delete | tamper_db | follow_reroute | anchor | handover | speed
POST /runs/{id}/pause | /resume       DELETE /runs/{id}       POST /stop-all
```

Optional `X-Sim-Token` header (`SIM_TOKEN`). One run per hub; starting another on the same hub replaces it.

## Tamper injections

* `tamper_forge` – a compromised device sends an edited record with a stale hash → `TAMPER_BAD_HASH`.
* `tamper_delete` – a record is produced but never uploaded → `MISSING_RECORDS`.
* `tamper_db` – edits a database row through the backend's **demo tools** (`RAKSHAK_DEMO_TOOLS=true`, admin only) so
  `GET /api/verify/{id}` flips to TAMPERED. `POST /api/demo/restore` undoes it.

## Running

Inside `docker compose up` it autoplays scenarios on the seeded trucks (`SIM_AUTOSTART`, `SIM_LOOP`). Standalone:

```bash
pip install ./ml ./backend ./simulator
RAKSHAK_API_URL=http://localhost:8000 MQTT_CA_FILE=infra/certs/out/ca.crt python -m rakshak_sim
```

Tests: `pytest simulator/sim_tests` (truck, offline queue, edge rules, commands, tamper, clock, control API) and
`pytest backend/tests/test_simulator_e2e.py` (the full demo narrative through the real backend pipeline).
