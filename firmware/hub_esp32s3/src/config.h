// Rakshak Hub (ESP32-S3) - pin map, thresholds, timing.   *** NOT HARDWARE-TESTED (compile-tested only) ***
// Thresholds are illustrative starting values (tuned per crop in the pilot); they mirror ml/rakshak_ml/edge.py and are
// checked against edge_vectors.json by the host test in firmware/common/test.
#pragma once

// ---- pins (ESP32-S3-DevKitC-1; change to match your PCB) --------------------------------------------------------
#define PIN_I2C_SDA 8          // SHT31 (0x44) + MPU6050 (0x68)
#define PIN_I2C_SCL 9
#define PIN_REED 4             // lid reed switch to GND (internal pull-up): open circuit = lid open
#define PIN_SERVO 5            // SG90 driving the PCM vent flap
#define PIN_FAN 6              // scrubber fan, low-side MOSFET gate
#define PIN_BUZZER 7           // active buzzer
#define PIN_LED_GREEN 15
#define PIN_LED_BLUE 16
#define PIN_LED_RED 17
#define PIN_PAIR_BTN 0         // BOOT button: press to pair the next tag that connects (60 s window)
#define PIN_BATT_ADC 1         // backup battery through a 1:2 divider
#define BATT_DIVIDER 2.0f
#define PIN_MODEM_RX 18        // ESP32 RX <- A7670C TXD
#define PIN_MODEM_TX 19        // ESP32 TX -> A7670C RXD
#define PIN_MODEM_PWRKEY 21
#define MODEM_BAUD 115200

// ---- timing -----------------------------------------------------------------------------------------------------
#define HUB_PERIOD_S 60               // one hub sample per minute
#define HUB_PARKED_PERIOD_S 300       // ... when parked and SAFE
#define PARK_AFTER_S 900              // no motion for this long => parked
#define MOTION_G_EPS 0.08f            // |accel| deviation from 1 g that counts as motion
#define SHOCK_EVENT_G 2.5f            // peak acceleration that logs a SHOCK event
#define TAG_SESSION_PERIOD_S 300      // tags offer a batch every 5 min (tag config BLE_EVERY_WAKES x SAMPLE_PERIOD_S)
#define TAG_WINDOW_S 25               // parked: scan +- this around the expected tag window
#define LIVE_MAX_AGE_S 900            // a tag's live reading older than this is ignored by the edge rules
#define DRAIN_MAX_PER_CYCLE 40        // records published per loop pass (keeps the loop responsive)
#define STATUS_PERIOD_S 300
#define GNSS_TIMEOUT_S 90

// ---- edge rules (no network needed) -----------------------------------------------------------------------------
#define DEFAULT_UPPER_LIMIT_C 8.0     // crop upper temperature limit; set per shipment via serial `LIMIT <c>` (NVS "ulim")
#define FLAP_T0 0.0                   // dT <= 0 -> 0 %
#define FLAP_T1 1.5                   // dT < 1.5 -> 25 %
#define FLAP_T2 3.0                   // dT < 3 -> 50 %, else 100 %
#define ALERT_DOWNGRADE_EVALS 2       // tier falls only after this many consecutive lower evaluations (hold)
#define LOW_BATT_PCT 15

// ---- storage ---------------------------------------------------------------------------------------------------
#define RING_SECTOR 4096
#define RING_SLOTS 8000               // capped to what the partition holds (~1.4 MB => ~5.5 days of tags + hub records)
#define NVS_NS "rakshak"

// ---- BLE (shared with the tag) ---------------------------------------------------------------------------------
#define RK_SERVICE_UUID "5a1d0000-7261-6b73-6861-6b2d74616721"
#define RK_CHAR_FRAMES "5a1d0001-7261-6b73-6861-6b2d74616721"
#define RK_CHAR_ACK "5a1d0002-7261-6b73-6861-6b2d74616721"
#define RK_CHAR_PAIR "5a1d0003-7261-6b73-6861-6b2d74616721"
#define RK_HUB_SERVICE_UUID "5a1d1000-7261-6b73-6861-6b2d68756221" // hub command service (different from the tag service)
#define RK_HUB_CMD_CHAR "5a1d1001-7261-6b73-6861-6b2d68756221"
#define RK_BLE_LIVE 0x03
#define MAX_TAGS 8

#define FW_VERSION "1.0.0-nohw"
