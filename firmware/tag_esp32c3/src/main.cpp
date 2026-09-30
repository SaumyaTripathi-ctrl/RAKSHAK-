// Rakshak Tag (ESP32-C3): senses, encrypts + hash-chains, stores, hands batches to the hub over BLE, deep-sleeps.
//
//   *** NOT HARDWARE-TESTED. Compiles in CI; the record/crypto/ring/BLE-batch logic it calls is host-tested
//   *** against the Python reference (firmware/common/test). Pin map and timing: config.h.
//
// One wake = one minute: SHT31 + reed every wake, ethylene strip every 5th, BLE offer every 5th.
#include <Arduino.h>
#include <esp_sleep.h>
#include <time.h>

#include "ble_tag.h"
#include "config.h"
#include "sensors.h"
#include "storage.h"

extern "C" {
#include "rk_ble.h"
#include "rk_clock.h"
#include "rk_codec.h"
#include "rk_device.h"
#include "rk_ring.h"
}

// State that must survive deep sleep (RTC memory). Identity, seq and the chain head are in NVS, not here.
RTC_DATA_ATTR static uint32_t wake_count = 0;
RTC_DATA_ATTR static bool lid_latched = false;
RTC_DATA_ATTR static bool low_batt_sent = false;
RTC_DATA_ATTR static float last_eth = 0.0f;
RTC_DATA_ATTR static float last_temp = 0.0f, last_rh = 0.0f;
RTC_DATA_ATTR static bool have_live = false;
RTC_DATA_ATTR static rk_clock_t rclock;

static rk_ring_t ring;
static rk_device_t dev;
static char shipment[RK_ID_LEN + 1] = "UNPAIRED";

static uint32_t mono_now() { return (uint32_t)time(nullptr); } // RTC-backed: keeps counting through deep sleep

static void sleep_now(uint32_t seconds) {
    esp_sleep_enable_timer_wakeup((uint64_t)seconds * 1000000ULL);
    // Reed switch wakes us immediately when the lid opens (needs an external pull-up: GPIO pulls are off in deep sleep).
    esp_deep_sleep_enable_gpio_wakeup(1ULL << PIN_REED, ESP_GPIO_WAKEUP_GPIO_HIGH);
    esp_deep_sleep_start();
}

static void blink(int n) {
    pinMode(PIN_LED, OUTPUT);
    for (int i = 0; i < n; i++) {
        digitalWrite(PIN_LED, HIGH);
        delay(120);
        digitalWrite(PIN_LED, LOW);
        delay(160);
    }
}

// ---- serial provisioning (factory): PROVISION <device_id> <key_epoch> <64-hex-key> ---------------------------
static bool hex_to_bytes(const char *hex, uint8_t *out, size_t n) {
    if (strlen(hex) != n * 2) return false;
    for (size_t i = 0; i < n; i++) {
        unsigned v;
        if (sscanf(hex + 2 * i, "%2x", &v) != 1) return false;
        out[i] = (uint8_t)v;
    }
    return true;
}

static bool provisioning_mode() {
    Serial.println("Rakshak Tag: not provisioned. Send: PROVISION <device_id> <key_epoch> <64-hex-key>  (10 s)");
    uint32_t t0 = millis();
    String line;
    while (millis() - t0 < 10000) {
        while (Serial.available()) {
            char c = (char)Serial.read();
            if (c != '\n' && c != '\r') {
                line += c;
                continue;
            }
            char id[24], key_hex[80];
            unsigned epoch;
            if (sscanf(line.c_str(), "PROVISION %23s %u %79s", id, &epoch, key_hex) == 3) {
                uint8_t key[RK_KEY_LEN];
                rk_kv_t kv = storage_kv();
                if (hex_to_bytes(key_hex, key, RK_KEY_LEN) && epoch <= 0xFFFF && rk_device_provision(&kv, id, (uint16_t)epoch, key) == RK_OK) {
                    Serial.println("provisioned");
                    return true;
                }
                Serial.println("invalid provisioning command");
            }
            line = "";
        }
        delay(20);
    }
    return false;
}

// ---- record emission ------------------------------------------------------------------------------------------
static bool emit_tag_sample(float temp, float rh, float eth, uint8_t batt) {
    int valid;
    rk_tag_sample_t s;
    memset(&s, 0, sizeof s);
    strncpy(s.c.device_id, dev.device_id, RK_ID_LEN);
    strncpy(s.c.shipment_id, shipment, RK_ID_LEN);
    s.c.ts = rk_clock_ts(&rclock, mono_now(), &valid);
    s.temp_x100 = (int16_t)lroundf(temp * 100.0f);
    s.rh_x100 = (uint16_t)lroundf(rh * 100.0f);
    s.ethylene_idx_x10 = (uint16_t)lroundf(constrain(eth, 0.0f, 100.0f) * 10.0f);
    s.flags = (uint8_t)((valid ? RK_TAG_FLAG_TS_VALID : 0) | (lid_latched ? RK_TAG_FLAG_LID_OPEN : 0));
    s.batt_pct = batt;
    uint8_t body[RK_TAG_BODY_LEN], frame[RK_MAX_FRAME_LEN];
    size_t fl;
    if (rk_pack_tag(&s, body) != RK_OK) return false;
    return rk_device_emit(&dev, RK_TYPE_TAG_SAMPLE, body, sizeof body, frame, &fl) == RK_OK;
}

static bool emit_event(uint16_t code, uint16_t arg0, uint16_t arg1, bool force_valid = false) {
    int valid;
    rk_event_t e;
    memset(&e, 0, sizeof e);
    strncpy(e.c.device_id, dev.device_id, RK_ID_LEN);
    strncpy(e.c.shipment_id, shipment, RK_ID_LEN);
    e.c.ts = rk_clock_ts(&rclock, mono_now(), &valid);
    if (force_valid) valid = 1;
    e.event_code = code;
    e.arg0 = arg0;
    e.arg1 = arg1;
    e.flags = (uint8_t)((valid ? RK_TAG_FLAG_TS_VALID : 0) | (lid_latched ? RK_TAG_FLAG_LID_OPEN : 0));
    e.batt_pct = sensors_battery_pct();
    uint8_t body[RK_EVENT_BODY_LEN], frame[RK_MAX_FRAME_LEN];
    size_t fl;
    if (rk_pack_event(&e, body) != RK_OK) return false;
    return rk_device_emit(&dev, RK_TYPE_EVENT, body, sizeof body, frame, &fl) == RK_OK;
}

void setup() {
    Serial.begin(115200);
    const esp_sleep_wakeup_cause_t cause = esp_sleep_get_wakeup_cause();
    const bool cold_boot = cause == ESP_SLEEP_WAKEUP_UNDEFINED;

    if (!storage_begin()) {
        Serial.println("storage init failed: cannot log safely, sleeping");
        blink(5);
        sleep_now(SAMPLE_PERIOD_S);
    }
    sensors_begin();
    rk_blockdev_t bd = storage_blockdev(RING_SLOTS);
    if (rk_ring_init(&ring, &bd) != RK_OK) {
        Serial.println("ring init failed");
        blink(4);
        sleep_now(SAMPLE_PERIOD_S);
    }
    rk_kv_t kv = storage_kv();
    if (rk_device_load(&dev, &kv, &ring) != RK_OK) {
        // The device REFUSES to log if its identity/seq cannot be read (a repeated nonce would break AES-GCM).
        if (!provisioning_mode() || rk_device_load(&dev, &kv, &ring) != RK_OK) {
            blink(3);
            sleep_now(SAMPLE_PERIOD_S);
        }
    }
    storage_get_str("ship", shipment, sizeof shipment);

    if (cold_boot) {
        rk_clock_init(&rclock, mono_now());
        wake_count = 0;
        lid_latched = false;
        low_batt_sent = false;
        emit_event(RK_EVENT_BOOT, 0, 0);
    }

    if (cause == ESP_SLEEP_WAKEUP_GPIO && !lid_latched) {
        lid_latched = true; // latched until the tag is re-paired
        emit_event(RK_EVENT_LID_OPEN, 0, 0);
        blink(2);
    }

    TH th = sensors_read_th();
    if (wake_count % STRIP_EVERY_WAKES == 0) {
        float e = sensors_read_ethylene_index(th.ok ? th.rh_pct : NAN);
        if (!isnan(e)) last_eth = e;
    }
    uint8_t batt = sensors_battery_pct();
    if (th.ok) {
        last_temp = th.temp_c;
        last_rh = th.rh_pct;
        have_live = true;
        if (!emit_tag_sample(th.temp_c, th.rh_pct, last_eth, batt)) Serial.println("record NOT stored");
    } else {
        Serial.println("SHT31 read failed: no record this minute (a gap is reported, never a guess)");
    }
    if (batt < LOW_BATT_PCT && !low_batt_sent) {
        low_batt_sent = true;
        emit_event(RK_EVENT_LOW_BATTERY, batt, 0);
    }

    if (wake_count % BLE_EVERY_WAKES == 0) {
        LiveReading live;
        live.valid = have_live;
        live.temp_x100 = (int16_t)lroundf(last_temp * 100.0f);
        live.rh_x100 = (uint16_t)lroundf(last_rh * 100.0f);
        live.eth_x10 = (uint16_t)lroundf(constrain(last_eth, 0.0f, 100.0f) * 10.0f);
        BleResult r = ble_offer_batch(&ring, BLE_WINDOW_MS, BATCH_MAX_FRAMES, live);
        if (r.paired) {
            storage_put_str("ship", r.shipment_id);
            strncpy(shipment, r.shipment_id, RK_ID_LEN);
            lid_latched = false;
            emit_event(RK_EVENT_PAIRED, 0, 0);
        }
        if (r.epoch > 0) { // time from the hub: set the clock and log the pair so the backend can re-base earlier timestamps
            uint32_t since_boot = rk_clock_sync(&rclock, r.epoch, mono_now());
            emit_event(RK_EVENT_TIME_SYNC, (uint16_t)(since_boot & 0xFFFF), (uint16_t)(since_boot >> 16), true);
        }
        Serial.printf("ble: connected=%d sent=%d acked=%d pending=%u dropped=%u\n", r.connected, r.sent, r.acked, (unsigned)ring.count, (unsigned)ring.dropped);
    }
    wake_count++;
    Serial.flush();
    sleep_now(SAMPLE_PERIOD_S);
}

void loop() {}
