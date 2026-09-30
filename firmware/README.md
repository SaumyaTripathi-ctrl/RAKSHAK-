# Rakshak firmware

> **NOT HARDWARE-TESTED.** Both projects compile in CI (PlatformIO, Arduino-ESP32 3.x via the pioarduino platform).
> The pure-C core in `common/` (codec, ring buffer, device identity, edge rules, ethylene calibration, BLE batching,
> command/AT parsers, tag clock) *is* tested on the host against the Python reference (`common/test/run_host_test.sh`,
> with vectors in `common/vectors.json` and `common/edge_vectors.json`). Everything that touches real peripherals
> (I2C sensors, NimBLE, the A7670C modem, servo/fan) has never run on a device.

| Project | MCU | Role |
|---|---|---|
| `tag_esp32c3/` | ESP32-C3 | per crate: SHT31, TCS34725 + colour strip, reed lid switch; seals + chains records, stores them in a flash ring, offers them to the hub over BLE, deep-sleeps |
| `hub_esp32s3/` | ESP32-S3 | per truck: SHT31, MPU6050, reed, A7670C (4G + GNSS), BLE central, SG90 PCM flap, scrubber fan, LED/buzzer; edge rules with no network; MQTT/TLS store-and-forward |
| `common/` | - | record spec (`spec/RECORD_SPEC.md`), portable C, host tests |

Build (from PowerShell on Windows, or any shell): `pio run -d firmware/tag_esp32c3` and `pio run -d firmware/hub_esp32s3`.

## Provisioning (serial, 115200 baud)

Each device gets a 32-byte key derived from a master secret (`docs/PROVISIONING.md`), then:

```
PROVISION <device_id> <key_epoch> <64-hex-key>          # tag and hub
SET host mqtt.example.org | SET hpass <pw> | SET apn internet | SET port 8883 | SET ca <PEM on one line>   # hub
LIMIT 8.0                                               # hub: crop upper temperature limit (C)
PAIR                                                    # hub: pair the next tag that connects to this shipment (or BOOT button)
```

A device whose identity or sequence counter cannot be read **refuses to log** (a repeated AES-GCM nonce would break the
encryption), it blinks/idles until provisioned.

## Design notes

* **Flash ring without a filesystem.** The ring lives raw in the "spiffs" data partition of the default table (LittleFS
  could not be linked under this platform). A 4 KB sector is erased when the head enters it (23 slots per sector, one
  erase per 23 records); ACKed slots are invalidated by writing zeros, which needs no erase.
* **Hub cannot decrypt tag frames** (it holds no tag keys), so each BLE session also carries a *cleartext live reading*
  (`0x03`: temperature, humidity, ethylene index) that drives the flap/fan edge rules only. The sealed, chained frames
  are what reach the ledger. Consequence: edge rules react at the tag's BLE cadence (5 min), not per sample. See D-052.
* **Hub power:** while a truck is moving the hub scans continuously (tags advertise only ~6 s every 5 min). When parked
  (no motion 15 min, SAFE, empty backlog) it light-sleeps between predicted tag windows. Figures in `docs/LIMITATIONS.md`
  are calculations, not measurements.
* **Time:** hub GNSS time is written into pairing and every ACK; tags that lost their clock emit `ts_valid=0` records
  followed by a `TIME_SYNC` event so the backend re-bases them.
* **Unverified:** A7670C AT sequences (`hub_esp32s3/src/modem.cpp`, TLS CA upload via `AT+CCERTDOWN`), NimBLE v2 API
  behaviour with concurrent scan/advertise/connect, servo pulse range, ADC battery curve, ethylene strip calibration
  table (`common/include/rk_ethylene_cal.h` is a **placeholder**: lab calibration against a reference ME3-C2H4 sensor is pending).
* **MPU6050** uses a small own I2C driver at +-2 g; real road shocks need the +-8 g range (TODO).
