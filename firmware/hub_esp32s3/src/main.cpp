// Rakshak Hub (ESP32-S3): crate controller + gateway.
//
//   *** NOT HARDWARE-TESTED. Compiles in CI; the codec/ring/edge-rule/command-parser logic it calls is host-tested
//   *** against the Python reference (firmware/common/test). Modem AT sequences are unverified (see modem.h).
//
// Every cycle (60 s in transit):
//   1. sample hub SHT31 / MPU6050 shock / reed / battery / GNSS            -> sealed HUB_SAMPLE frame in the ring
//   2. edge rules, NO network needed: PCM flap from crate temperature, scrubber fan from the ethylene trend, LED tiers,
//      latching buzzer                                                     (AI commands only raise floors / force states)
//   3. BLE: scan, pull tag batches, store them in the same ring, ACK       (hub never holds tag keys)
//   4. 4G: reconnect if needed, publish status, drain the ring oldest-first, removing each frame only after PUBACK
#include <Arduino.h>
#include <esp_sleep.h>
#include <sys/time.h>
#include <time.h>

#include "actuators.h"
#include "ble_hub.h"
#include "config.h"
#include "modem.h"
#include "sensors.h"
#include "storage.h"

extern "C" {
#include "rk_ble.h"
#include "rk_clock.h"
#include "rk_cmd.h"
#include "rk_codec.h"
#include "rk_device.h"
#include "rk_edge.h"
#include "rk_ring.h"
}

// ---- state ----------------------------------------------------------------------------------------------------
static rk_ring_t ring;
static rk_device_t dev;
static rk_clock_t rclock;
static rk_fan_t fan;
static char shipment[RK_ID_LEN + 1] = "UNPAIRED";
static char mqtt_host[64] = "", mqtt_pass[64] = "", apn[32] = "internet", ca_pem[2200] = "";
static uint16_t mqtt_port = 8883;
static double upper_limit_c = DEFAULT_UPPER_LIMIT_C;

static int flap_floor = 0;   // from FLAP_SET (AI): edge rules may open further, never below it
static int flap_pct = 0;
static int fan_forced = -1;  // -1 edge rule, 0/1 forced by FAN_OFF/FAN_ON
static bool fan_on = false;
static int ai_tier = 0;      // ALERT_WARNING / ALERT_CRITICAL / ALERT_CLEAR
static int tier = 0, lower_evals = 0;
static bool buzzer_latched = false, buzzer_acked = false;

static bool lid_was_open = false, low_batt_sent = false;
static uint32_t last_motion_s = 0, last_status_s = 0, last_gnss_s = 0, last_uplink_try_s = 0, last_fan_eval_at = 0;
static uint32_t offline_since_epoch = 0;
static uint32_t pair_until_s = 0;
static bool parked = false;
static uint32_t next_scan_at_ms = 0;
static double last_lat = 0, last_lon = 0;
static uint32_t last_fix_s = 0;
static bool uplink_ok = false;

// ---- pending commands (queued from MQTT / BLE callbacks, applied + acked from the main loop) ------------------
struct PendingCmd {
    char json[256];
    size_t len = 0;
    bool used = false;
};
static PendingCmd pending[4];
static portMUX_TYPE pending_mux = portMUX_INITIALIZER_UNLOCKED;

static void enqueue_cmd(const char *json, size_t len) {
    if (len == 0 || len >= sizeof pending[0].json) return;
    portENTER_CRITICAL(&pending_mux);
    for (auto &p : pending) {
        if (!p.used) {
            memcpy(p.json, json, len);
            p.json[len] = '\0';
            p.len = len;
            p.used = true;
            break;
        }
    }
    portEXIT_CRITICAL(&pending_mux);
}

static uint32_t mono_s() { return millis() / 1000; }
static uint32_t epoch_now() {
    time_t t = time(nullptr);
    return rclock.synced ? (uint32_t)t : 0;
}

// ---- records ----------------------------------------------------------------------------------------------------
static bool emit_event(uint16_t code, uint16_t arg0, uint16_t arg1) {
    int valid;
    rk_event_t e;
    memset(&e, 0, sizeof e);
    strncpy(e.c.device_id, dev.device_id, RK_ID_LEN);
    strncpy(e.c.shipment_id, shipment, RK_ID_LEN);
    e.c.ts = rk_clock_ts(&rclock, mono_s(), &valid);
    e.event_code = code;
    e.arg0 = arg0;
    e.arg1 = arg1;
    e.flags = (uint8_t)((valid ? RK_HUB_FLAG_TS_VALID : 0) | (sensors_lid_open() ? RK_HUB_FLAG_LID_OPEN : 0));
    e.batt_pct = sensors_battery_pct();
    uint8_t body[RK_EVENT_BODY_LEN], frame[RK_MAX_FRAME_LEN];
    size_t fl;
    if (rk_pack_event(&e, body) != RK_OK) return false;
    return rk_device_emit(&dev, RK_TYPE_EVENT, body, sizeof body, frame, &fl) == RK_OK;
}

static bool emit_hub_sample(const HubTH &th, float shock_g, bool lid_open, uint8_t batt) {
    int valid;
    rk_hub_sample_t s;
    memset(&s, 0, sizeof s);
    strncpy(s.c.device_id, dev.device_id, RK_ID_LEN);
    strncpy(s.c.shipment_id, shipment, RK_ID_LEN);
    s.c.ts = rk_clock_ts(&rclock, mono_s(), &valid);
    s.temp_x100 = (int16_t)lroundf(th.temp_c * 100.0f);
    s.rh_x100 = (uint16_t)lroundf(th.rh_pct * 100.0f);
    s.shock_g_x100 = (uint16_t)lroundf(constrain(shock_g, 0.0f, 600.0f) * 100.0f);
    const bool gps_fresh = last_fix_s && mono_s() - last_fix_s < 600;
    if (gps_fresh) {
        s.lat_e6 = (int32_t)lround(last_lat * 1e6);
        s.lon_e6 = (int32_t)lround(last_lon * 1e6);
    }
    s.flags = (uint8_t)((lid_open ? RK_HUB_FLAG_LID_OPEN : 0) | (valid ? RK_HUB_FLAG_TS_VALID : 0) | (gps_fresh ? RK_HUB_FLAG_GPS_VALID : 0) | (fan_on ? RK_HUB_FLAG_FAN_ON : 0));
    s.flap_pct = (uint8_t)flap_pct;
    s.batt_pct = batt;
    s.alert_level = (uint8_t)tier;
    uint8_t body[RK_HUB_BODY_LEN], frame[RK_MAX_FRAME_LEN];
    size_t fl;
    if (rk_pack_hub(&s, body) != RK_OK) return false;
    return rk_device_emit(&dev, RK_TYPE_HUB_SAMPLE, body, sizeof body, frame, &fl) == RK_OK;
}

// ---- topics + status ------------------------------------------------------------------------------------------
static String topic(const char *leaf) { return String("rakshak/") + dev.device_id + "/" + leaf; }

static void publish_json(const String &json) {
    String t = topic("events");
    modem_publish(t.c_str(), (const uint8_t *)json.c_str(), json.length(), 1);
}

static void publish_status(bool online) {
    const char *led = tier >= 2 ? "red" : tier == 1 ? "blue" : "green";
    String j = String("{\"type\":\"status\",\"online\":") + (online ? "true" : "false") + ",\"fw\":\"" FW_VERSION "\",\"batt\":" + sensors_battery_pct() + ",\"backlog\":" + (unsigned)ring.count + ",\"ts\":" + epoch_now();
    if (offline_since_epoch) j += String(",\"offline_since\":") + offline_since_epoch;
    j += String(",\"led\":\"") + led + "\",\"buzzer_latched\":" + (buzzer_latched ? "true" : "false") + ",\"flap\":" + flap_pct + ",\"fan\":" + (fan_on ? "true" : "false") + "}";
    publish_json(j);
    last_status_s = mono_s();
}

// ---- commands ---------------------------------------------------------------------------------------------------
static void apply_command(const rk_cmd_t &c, bool *ok) {
    *ok = true;
    switch (c.kind) {
    case RK_CMD_FLAP_SET: flap_floor = c.arg; break; // 0 clears the floor
    case RK_CMD_FAN_ON: fan_forced = 1; break;
    case RK_CMD_FAN_OFF: fan_forced = -1; break;     // release back to the edge rule
    case RK_CMD_ALERT_WARNING: ai_tier = 1; break;
    case RK_CMD_ALERT_CRITICAL: ai_tier = 2; break;
    case RK_CMD_ALERT_CLEAR: ai_tier = 0; break;
    case RK_CMD_ACK_ALERT:
        buzzer_latched = false;
        buzzer_acked = true;
        break;
    default: *ok = false; break;
    }
}

static void process_commands() {
    for (auto &p : pending) {
        char json[256];
        size_t len = 0;
        portENTER_CRITICAL(&pending_mux);
        if (p.used) {
            memcpy(json, p.json, p.len + 1);
            len = p.len;
            p.used = false;
        }
        portEXIT_CRITICAL(&pending_mux);
        if (!len) continue;
        rk_cmd_t c;
        if (rk_cmd_parse(json, len, &c) != 0) continue; // not a usable command: ignore (nothing to ack)
        bool ok;
        apply_command(c, &ok);
        Serial.printf("cmd %s kind=%d ok=%d\n", c.id, (int)c.kind, ok);
        char ack[128];
        if (rk_cmd_ack_json(ack, sizeof ack, c.id, ok) && modem_mqtt_connected()) publish_json(String(ack));
    }
}

static void idle_poll();
static void serial_commands();

// ---- sampling + edge rules ---------------------------------------------------------------------------------------
struct CrateView {
    bool have = false;
    double temp = 0;
    double eth = 0;
    uint32_t newest_at = 0;
};

static CrateView crate_from_tags() {
    CrateView v;
    int n;
    const TagLive *lives = ble_hub_lives(&n);
    const uint32_t now = mono_s();
    for (int i = 0; i < n; i++) {
        if (!lives[i].valid || now - lives[i].at_s > LIVE_MAX_AGE_S) continue;
        double t = lives[i].temp_x100 / 100.0, e = lives[i].eth_x10 / 10.0;
        if (!v.have || t > v.temp) v.temp = t; // the warmest crate decides
        if (!v.have || e > v.eth) v.eth = e;
        if (lives[i].at_s > v.newest_at) v.newest_at = lives[i].at_s;
        v.have = true;
    }
    return v;
}

static void run_edge_rules(const HubTH &th) {
    CrateView cv = crate_from_tags();
    const double crate_t = cv.have ? cv.temp : (th.ok ? th.temp_c : upper_limit_c);

    const int edge_flap = rk_flap_for_deviation(crate_t, upper_limit_c, FLAP_T0, FLAP_T1, FLAP_T2);
    flap_pct = max(edge_flap, flap_floor);
    flap_set(flap_pct);

    if (cv.have && cv.newest_at != last_fan_eval_at) { // the fan rule runs on NEW strip readings only
        last_fan_eval_at = cv.newest_at;
        rk_fan_update(&fan, mono_s() / 60.0, cv.eth);
    }
    fan_on = fan_forced < 0 ? fan.fan_on != 0 : fan_forced == 1;
    fan_set(fan_on);

    int edge_tier = rk_edge_alert_level(crate_t, upper_limit_c);
    int want = max(edge_tier, ai_tier);
    if (want >= tier) {
        tier = want;
        lower_evals = 0;
    } else if (++lower_evals >= ALERT_DOWNGRADE_EVALS) { // immediate escalation, held de-escalation
        tier = want;
        lower_evals = 0;
    }
    if (tier >= 2) {
        if (!buzzer_acked) buzzer_latched = true;
    } else {
        buzzer_acked = false; // re-arms for the next CRITICAL
    }
    indicate(tier, buzzer_latched);
}

static void update_gnss_and_time() {
    if (!uplink_ok && !modem_power_on()) return;
    rk_gnss_t g;
    if (modem_gnss(&g, GNSS_TIMEOUT_S)) {
        last_lat = g.lat;
        last_lon = g.lon;
        last_fix_s = mono_s();
        if (g.epoch) {
            struct timeval tv = {(time_t)g.epoch, 0};
            settimeofday(&tv, nullptr);
            rk_clock_sync(&rclock, g.epoch, mono_s());
        }
    }
    last_gnss_s = mono_s();
}

// ---- uplink -----------------------------------------------------------------------------------------------------
static bool uplink_connect() {
    if (!mqtt_host[0]) return false;
    if (!modem_power_on() || !modem_attach(apn)) return false;
    if (ca_pem[0]) modem_upload_ca(ca_pem);
    String willt = topic("events"), subt = topic("cmd");
    static const char will[] = "{\"type\":\"status\",\"online\":false}";
    MqttConfig mc = {mqtt_host, mqtt_port, dev.device_id, dev.device_id, mqtt_pass, willt.c_str(), will, subt.c_str(), true};
    return modem_mqtt_connect(mc, enqueue_cmd);
}

static void uplink_cycle() {
    if (!modem_mqtt_connected()) {
        if (uplink_ok) { // just lost it
            uplink_ok = false;
            offline_since_epoch = epoch_now();
        }
        if (last_uplink_try_s && mono_s() - last_uplink_try_s < 60) return;
        last_uplink_try_s = mono_s();
        if (!uplink_connect()) return;
        uplink_ok = true;
        publish_status(true); // status BEFORE the burst so the backend knows the gap/offline window
    }
    uint8_t frame[RK_MAX_FRAME_LEN];
    int sent = 0;
    String t = topic("telemetry");
    while (ring.count > 0 && sent < DRAIN_MAX_PER_CYCLE && modem_mqtt_connected()) {
        size_t len;
        if (rk_ring_peek(&ring, 0, frame, sizeof frame, &len) != RK_OK) break;
        uint32_t seq = (uint32_t)frame[20] | ((uint32_t)frame[21] << 8) | ((uint32_t)frame[22] << 16) | ((uint32_t)frame[23] << 24);
        if (!modem_publish(t.c_str(), frame, len, 1)) break; // keep it: retried next cycle
        rk_ring_ack(&ring, seq, seq);                       // removed only after PUBACK
        sent++;
        idle_poll();
    }
    if (sent && ring.count == 0) {
        offline_since_epoch = 0;
        publish_status(true); // final status with backlog 0
    } else if (mono_s() - last_status_s >= STATUS_PERIOD_S) {
        publish_status(true);
    }
}

// ---- serial provisioning / debug console --------------------------------------------------------------------------
static bool hex_to_bytes(const char *hex, uint8_t *out, size_t n) {
    if (strlen(hex) != n * 2) return false;
    for (size_t i = 0; i < n; i++) {
        unsigned v;
        if (sscanf(hex + 2 * i, "%2x", &v) != 1) return false;
        out[i] = (uint8_t)v;
    }
    return true;
}

static void load_settings() {
    storage_get_str("ship", shipment, sizeof shipment);
    storage_get_str("host", mqtt_host, sizeof mqtt_host);
    storage_get_str("hpass", mqtt_pass, sizeof mqtt_pass);
    storage_get_str("apn", apn, sizeof apn);
    storage_get_str("ca", ca_pem, sizeof ca_pem);
    char buf[16];
    if (storage_get_str("port", buf, sizeof buf)) mqtt_port = (uint16_t)atoi(buf);
    if (storage_get_str("ulim", buf, sizeof buf)) upper_limit_c = atof(buf);
}

// PROVISION <id> <epoch> <64hex> | SET host|port|hpass|apn|ulim|ship|ca <value> | LIMIT <c> | PAIR | CMD <json> | STATUS
static void serial_line(const String &line) {
    char a[24], b[80];
    unsigned epoch;
    if (sscanf(line.c_str(), "PROVISION %23s %u %79s", a, &epoch, b) == 3) {
        uint8_t key[RK_KEY_LEN];
        rk_kv_t kv = storage_kv();
        if (hex_to_bytes(b, key, RK_KEY_LEN) && epoch <= 0xFFFF && rk_device_provision(&kv, a, (uint16_t)epoch, key) == RK_OK) {
            Serial.println("provisioned; rebooting");
            delay(200);
            ESP.restart();
        }
        Serial.println("invalid PROVISION");
    } else if (line.startsWith("SET ")) {
        int sp = line.indexOf(' ', 4);
        if (sp > 0) {
            String k = line.substring(4, sp), v = line.substring(sp + 1);
            v.trim();
            storage_put_str(k.c_str(), v.c_str());
            load_settings();
            Serial.println("ok");
        }
    } else if (line.startsWith("LIMIT ")) {
        storage_put_str("ulim", line.substring(6).c_str());
        load_settings();
        Serial.printf("upper limit %.1f C\n", upper_limit_c);
    } else if (line == "PAIR") {
        pair_until_s = mono_s() + 60;
        Serial.println("pairing window open for 60 s");
    } else if (line.startsWith("CMD ")) {
        enqueue_cmd(line.c_str() + 4, line.length() - 4);
    } else if (line == "STATUS") {
        Serial.printf("ship=%s flap=%d fan=%d tier=%d latched=%d backlog=%u uplink=%d\n", shipment, flap_pct, fan_on, tier, buzzer_latched, (unsigned)ring.count, modem_mqtt_connected());
    }
}

static void serial_commands() {
    static String line;
    while (Serial.available()) {
        char c = (char)Serial.read();
        if (c == '\n' || c == '\r') {
            line.trim();
            if (line.length()) serial_line(line);
            line = "";
        } else if (line.length() < 2400) {
            line += c;
        }
    }
}

static void idle_poll() {
    modem_poll(0);
    serial_commands();
    if (digitalRead(PIN_PAIR_BTN) == LOW) pair_until_s = mono_s() + 60;
    process_commands();
}

// ---- setup / loop ------------------------------------------------------------------------------------------------
void setup() {
    Serial.begin(115200);
    pinMode(PIN_PAIR_BTN, INPUT_PULLUP);
    actuators_begin();
    indicate(1, false); // blue while booting
    if (!storage_begin()) {
        Serial.println("storage init failed: cannot log safely");
        indicate(2, false);
        while (true) delay(1000);
    }
    sensors_begin();
    rk_blockdev_t bd = storage_blockdev(RING_SLOTS);
    if (rk_ring_init(&ring, &bd) != RK_OK) {
        Serial.println("ring init failed");
        indicate(2, false);
        while (true) delay(1000);
    }
    rk_kv_t kv = storage_kv();
    while (rk_device_load(&dev, &kv, &ring) != RK_OK) { // REFUSES to log until identity/seq are readable
        Serial.println("not provisioned: send PROVISION <device_id> <key_epoch> <64-hex-key>");
        for (int i = 0; i < 100; i++) {
            serial_commands();
            delay(100);
        }
    }
    load_settings();
    rk_clock_init(&rclock, mono_s());
    rk_fan_init(&fan);
    modem_begin_uart();
    ble_hub_begin(enqueue_cmd);
    last_motion_s = mono_s();
    emit_event(RK_EVENT_BOOT, 0, 0);
    Serial.printf("hub %s up, shipment %s, upper limit %.1f C, ring %u/%u\n", dev.device_id, shipment, upper_limit_c, (unsigned)ring.count, (unsigned)ring.dev.slots);
}

void loop() {
    const uint32_t cycle_start = mono_s();
    if (last_gnss_s == 0 || cycle_start - last_gnss_s > 300) update_gnss_and_time();

    // ---- sample ----
    HubTH th = sensors_read_th();
    float shock = sensors_shock_peak_g();
    bool lid = sensors_lid_open();
    uint8_t batt = sensors_battery_pct();
    if (fabsf(shock - 1.0f) > MOTION_G_EPS) {
        last_motion_s = mono_s();
        parked = false;
    }
    if (shock >= SHOCK_EVENT_G) emit_event(RK_EVENT_SHOCK, (uint16_t)lroundf(shock * 100.0f), 0);
    if (lid && !lid_was_open) emit_event(RK_EVENT_LID_OPEN, 0, 0);
    lid_was_open = lid;
    if (batt < LOW_BATT_PCT && !low_batt_sent) {
        low_batt_sent = true;
        emit_event(RK_EVENT_LOW_BATTERY, batt, 0);
    }

    run_edge_rules(th);
    if (th.ok) emit_hub_sample(th, shock, lid, batt);
    else Serial.println("SHT31 read failed: no hub sample this cycle");

    // ---- BLE: pull tag batches (scan the rest of the cycle while moving; a short rendezvous when parked) ----
    parked = (mono_s() - last_motion_s > PARK_AFTER_S) && tier == 0 && ring.count == 0 && !buzzer_latched;
    const bool pairing = pair_until_s && mono_s() < pair_until_s;
    if (!pairing) pair_until_s = 0;
    const uint32_t spent_ms = (mono_s() - cycle_start) * 1000;
    const uint32_t window_ms = parked ? (uint32_t)TAG_WINDOW_S * 2000 : (uint32_t)HUB_PERIOD_S * 1000 - min<uint32_t>(spent_ms, HUB_PERIOD_S * 1000 - 5000);
    BleHubResult br = ble_hub_service(&ring, window_ms, epoch_now(), pairing ? shipment : nullptr, idle_poll);
    if (br.paired) {
        pair_until_s = 0;
        emit_event(RK_EVENT_PAIRED, 0, 0);
    }
    if (br.sessions) next_scan_at_ms = millis() + (TAG_SESSION_PERIOD_S - TAG_WINDOW_S) * 1000UL;
    if (br.frames_stored) Serial.printf("ble: %d tag frames stored, backlog %u\n", br.frames_stored, (unsigned)ring.count);

    // ---- 4G ----
    uplink_cycle();
    process_commands();

    // ---- parked: light sleep until the next expected tag window (modem keeps the MQTT session) ----
    if (parked) {
        const int32_t period_ms = HUB_PARKED_PERIOD_S * 1000L;
        int32_t sleep_ms = next_scan_at_ms ? (int32_t)(next_scan_at_ms - millis()) : period_ms;
        sleep_ms = constrain(sleep_ms, 1000, period_ms);
        Serial.printf("parked: light sleep %d s (BLE command path paused)\n", (int)(sleep_ms / 1000));
        Serial.flush();
        esp_sleep_enable_timer_wakeup((uint64_t)sleep_ms * 1000ULL);
        esp_sleep_enable_ext0_wakeup((gpio_num_t)PIN_REED, 1); // lid opened: wake at once
        esp_light_sleep_start();
        last_motion_s = mono_s() - PARK_AFTER_S + 120; // a fresh awake stretch after waking
    }
}
