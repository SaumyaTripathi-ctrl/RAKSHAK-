# Demo script (about 5 minutes)

Everything on screen is **simulated** (devices, training data, facilities) and labelled so in the UI.

```powershell
scripts\up.ps1          # starts mosquitto, postgres, api, web, simulator with seed data
scripts\demo.ps1        # scripted run: drives the API, prints a milestone checklist (exit code != 0 if one is missing)
```

Linux/macOS: `make up`, `make demo`. Open <http://localhost:8080>, log in with a demo-account button (Admin), and open the
shipment the script prints. `python tools/demo.py --accel 120` is the default speed; `--restore` undoes the tamper.

| # | What happens | Where to look |
|---|---|---|
| 1 | Live mango shipment, tags + hub reporting, ledger anchoring batches | Fleet map, Shipment detail (temperature, humidity, ethylene) |
| 2 | **Heat injected** -> crate temperature rises, PCM **flap opens** (25/50/100 %) by edge rule | Detail: flap indicator; Alerts |
| 3 | **Ethylene rises** -> **scrubber fan on** | Detail: fan indicator |
| 4 | **Network cut** -> hub keeps logging and applying edge rules (offline band on the chart) | Detail: "offline" segment |
| 5 | **Reconnect** -> backlog drains oldest-first, chart gap fills | Detail: backlog -> 0, "gap filled" events |
| 6 | Risk **WARNING -> CRITICAL**, remaining safe life falls, buzzer latches until acknowledged | Risk gauge, Alerts |
| 7 | **Reroute** recommended to nearest compatible (synthetic) cold store; driver accepts | Detail: reroute card + map |
| 8 | **Tamper**: a stored reading is edited in the database | Ingest flags / Verify page |
| 9 | **Verify** -> `TAMPERED` (batch + record named; displayed temp differs from the signed body) | Verify page |
| 10 | **QR page** shows the journey, custody timeline and "not verified" | `/p/<shipment>` |

Simulator Control page (`/simulator`) lets you start scenarios (`normal_trip`, `heat_excursion`, `banana_ripening`,
`rural_no_network`, `tamper`, `critical_reroute`, `demo_full`) and inject heat/ethylene/outage manually.
