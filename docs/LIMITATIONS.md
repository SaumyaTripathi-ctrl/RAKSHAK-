# Limitations - read before relying on any number here

Rakshak is a hackathon prototype. Be honest about what is real and what is not.

| Area | Status |
|---|---|
| **ML training data** | **Simulated.** Models are trained on `rakshak_ml`'s produce simulator (thermal lag, PCM depletion, ripening, ethylene, shocks). Reported R²/MAE measure fit to the *simulator*, not to real spoilage. No real shipment data was used. See `ml/artifacts/MODEL_CARD.md`. |
| **Food bands** (temperature/ethylene limits, shelf life) | Placeholders from general postharvest knowledge, marked TODO-verify in `ml/rakshak_ml/data/food_bands.json`. Validate with food scientists before any real use. |
| **Cold-storage dataset** | **Synthetic** (163 generated facilities, `cold_storage_synthetic.csv`). Not real locations or capacities. Routing via public OSRM when online, Haversine fallback otherwise. |
| **Ethylene strip** | The colour-strip -> index calibration table (`firmware/common/include/rk_ethylene_cal.h`) is a **placeholder**. Lab calibration against a reference sensor (e.g. ME3-C2H4) is pending. Strip response also depends on humidity and temperature. |
| **Device traffic in the demo** | **Simulated** (virtual hubs/tags use the real codec and real MQTT, but no hardware). |
| **Firmware** | Compile-tested only, **not hardware-tested**. Codec/ring/edge rules/parsers are host-tested against the Python reference. A7670C AT sequences, NimBLE behaviour, servo range, ADC curves are unverified. |
| **Power figures** | Any battery-life number is a *calculation* from datasheet currents and duty cycles, not a measurement. Hub scans BLE continuously while moving (tags advertise ~6 s per 5 min), so it needs vehicle power or a large pack; parked mode light-sleeps. |
| **Device security** | ESP32 has no secure element. Keys sit in NVS (enable flash encryption + secure boot for production). Extracting a key lets an attacker forge that device's records. The ledger proves *no later alteration*, not that a sensor was honest. |
| **BLE** | Tag->hub link is not bonded/encrypted; the cleartext live reading (D-052) could be spoofed to mis-steer the flap/fan. Frames themselves are sealed. |
| **Ledger** | Default is a local hash-linked JSONL ledger (single party, tamper-evident, not distributed). The Hyperledger Fabric path (Go chaincode + Node bridge) is experimental and was unit-tested but **never run on a live multi-org network**. |
| **Signatures** | Hand-over entries are signed server-side (Ed25519) on behalf of parties; not end-user signatures. |
| **Ethylene recovery** | Capturing/recycling scrubbed ethylene is future scope; the fan only removes/dilutes it. |
| **Time** | Tag clocks drift without the hub; re-basing assumes a linear device clock between `TIME_SYNC` events. |
| **Scale** | Tested with a handful of simulated hubs, not thousands. |
