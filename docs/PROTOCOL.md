# MQTT contract (hub <-> backend)

Broker: Mosquitto, TLS (8883), per-device credentials, ACL. A hub's MQTT username is its hub id; the ACL limits it to
its own prefix. The backend uses the `rakshak-api` service account. Sessions are persistent (`clean_session=false`,
QoS 1) so messages queue across 4G drops in both directions.

| Topic | Direction | Payload | QoS |
|---|---|---|---|
| `rakshak/{hub_id}/telemetry` | hub -> backend | **exactly one frame** (tag, hub or event record; 154/164 bytes; see `firmware/common/spec/RECORD_SPEC.md`). Tag frames are forwarded unchanged: the hub never holds tag keys | 1 |
| `rakshak/{hub_id}/events` | hub -> backend | JSON, not hash-chained: `status` and `cmd_ack` (below) | 1 |
| `rakshak/{hub_id}/cmd` | backend -> hub | JSON command (below) | 1 |

The hub also registers a **last-will** on `rakshak/{hub_id}/events`: `{"type":"status","online":false}`. The broker
publishes it when the hub's connection dies without a DISCONNECT, which is how the backend learns "offline" without the
hub saying anything.

## events: hub -> backend

```json
{"type":"status","online":true,"fw":"1.0.0","batt":92,"backlog":240,"ts":1791003600,
 "offline_since":1791000600,"led":"blue","buzzer_latched":false,"flap":50,"fan":true}
```

* `ts` is the hub's clock (epoch seconds). `offline_since` (optional) is when 4G was lost, in device time.
* `backlog` = records still queued on the hub. While it is > 0 the backend treats samples as **historical**: it records
  alerts/risk but does not steer the hub or compute a detour for an old excursion.
* On reconnect the hub sends a `status` **before** the burst, then drains oldest-first (removing each record only
  after PUBACK) and sends a final `status` with `backlog: 0`.

```json
{"type":"cmd_ack","id":"<command id>","ok":true}
```

## cmd: backend -> hub

```json
{"id":"7d1c...","cmd":"FLAP_SET","arg":50,"source":"ai","ts":1791003601}
```

| `cmd` | Effect on the hub (edge rules keep running with no network) |
|---|---|
| `FLAP_SET 0\|25\|50\|100` | sets a **floor**: edge rules may open the flap further but never below it; `FLAP_SET 0` clears the floor |
| `FAN_ON` / `FAN_OFF` | `FAN_ON` forces the scrubber fan on; `FAN_OFF` releases it back to the edge rule (ethylene trend) |
| `ALERT_WARNING` / `ALERT_CRITICAL` / `ALERT_CLEAR` | sets the AI tier of the LED (green/blue/red); `ALERT_CRITICAL` latches the buzzer |
| `ACK_ALERT` | silences the latched buzzer (sent after a user acknowledges the alert) |

`source` is `ai` or `user:<name>`. Unknown commands are acknowledged with `ok:false`. Commands sent while the hub is
offline are delivered on reconnect (persistent session) and acknowledged then.

## BLE: tag -> hub (not exposed to the backend)

MTU >= 247; frames are batched; the hub ACKs by `(first_seq, last_seq)` read from the cleartext header; a tag deletes
a record only after the ACK. The ACK carries GNSS time; a tag that lost its clock writes `ts_valid=0` records and then a
`TIME_SYNC` event (epoch + monotonic seconds) so the backend can re-base the earlier timestamps.
