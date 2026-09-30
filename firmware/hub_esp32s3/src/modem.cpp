#include "modem.h"

#include "config.h"

static HardwareSerial &MS = Serial1;
static modem_cmd_cb g_on_cmd = nullptr;
static bool g_mqtt_up = false;
static int g_pub_result = -1; // -1 pending, 0 fail, 1 acked
static String g_line;

// incoming MQTT message assembly: +CMQTTRXSTART / RXTOPIC / RXPAYLOAD / RXEND
static bool rx_active = false;
static size_t rx_payload_len = 0;
static String rx_payload;
static bool rx_reading_payload = false;

static void handle_line(const String &l) {
    if (l.startsWith("+CMQTTPUB:")) {
        int r = rk_parse_cmqttpub(l.c_str());
        if (r >= 0) g_pub_result = r;
    } else if (l.startsWith("+CMQTTCONNLOST") || l.startsWith("+CMQTTNONET")) {
        g_mqtt_up = false;
    } else if (l.startsWith("+CMQTTRXSTART")) {
        rx_active = true;
        rx_payload = "";
        rx_payload_len = 0;
        rx_reading_payload = false;
    } else if (l.startsWith("+CMQTTRXPAYLOAD:")) {
        int comma = l.indexOf(',');
        rx_payload_len = comma > 0 ? (size_t)l.substring(comma + 1).toInt() : 0;
        rx_reading_payload = rx_payload_len > 0 && rx_payload_len < 512;
    } else if (l.startsWith("+CMQTTRXEND")) {
        if (rx_active && rx_payload.length() && g_on_cmd) g_on_cmd(rx_payload.c_str(), rx_payload.length());
        rx_active = false;
        rx_reading_payload = false;
    } else if (rx_reading_payload) {
        rx_payload += l;
        if (rx_payload.length() >= rx_payload_len) rx_reading_payload = false;
    }
}

// Read for up to `ms`, dispatching URC lines; returns true as soon as `expect` (or `alt`) appears in the collected text.
static bool pump(uint32_t ms, const char *expect = nullptr, const char *alt = nullptr, String *collected = nullptr) {
    uint32_t t0 = millis();
    String all;
    while (millis() - t0 < ms) {
        while (MS.available()) {
            char c = (char)MS.read();
            if (c == '\n') {
                g_line.trim();
                if (g_line.length()) {
                    handle_line(g_line);
                    all += g_line;
                    all += '\n';
                }
                g_line = "";
            } else if (c != '\r') {
                g_line += c;
                if (g_line.length() > 600) g_line = "";
            }
            if (expect && (all.indexOf(expect) >= 0 || g_line.indexOf(expect) >= 0)) {
                if (collected) *collected = all + g_line;
                return true;
            }
            if (alt && (all.indexOf(alt) >= 0)) {
                if (collected) *collected = all;
                return false;
            }
        }
        delay(2);
    }
    if (collected) *collected = all;
    return false;
}

static bool at(const String &cmd, const char *expect = "OK", uint32_t ms = 2000, String *out = nullptr) {
    while (MS.available()) MS.read();
    MS.print(cmd);
    MS.print("\r\n");
    return pump(ms, expect, "ERROR", out);
}

// AT+CMQTTTOPIC-style commands that answer with a '>' prompt, then take raw bytes.
static bool at_data(const String &cmd, const uint8_t *data, size_t len, uint32_t ms = 3000) {
    while (MS.available()) MS.read();
    MS.print(cmd);
    MS.print("\r\n");
    if (!pump(ms, ">")) return false;
    MS.write(data, len);
    return pump(ms, "OK", "ERROR");
}

void modem_begin_uart() {
    MS.begin(MODEM_BAUD, SERIAL_8N1, PIN_MODEM_RX, PIN_MODEM_TX);
    pinMode(PIN_MODEM_PWRKEY, OUTPUT);
    digitalWrite(PIN_MODEM_PWRKEY, LOW);
}

bool modem_power_on() {
    if (at("AT", "OK", 500)) { // already on
        at("ATE0");
        return true;
    }
    digitalWrite(PIN_MODEM_PWRKEY, HIGH); // PWRKEY pulse (A7670C: >= 500 ms low-to-high depending on the board)
    delay(1200);
    digitalWrite(PIN_MODEM_PWRKEY, LOW);
    delay(4000);
    for (int i = 0; i < 10; i++)
        if (at("AT", "OK", 500)) {
            at("ATE0");
            return true;
        }
    return false;
}

bool modem_attach(const char *apn) {
    if (!at("AT+CPIN?", "READY", 3000)) return false;
    at(String("AT+CGDCONT=1,\"IP\",\"") + apn + "\"");
    at("AT+CGATT=1", "OK", 10000);
    for (int i = 0; i < 30; i++) {
        String r;
        if (at("AT+CGREG?", "OK", 1000, &r) && (r.indexOf(",1") >= 0 || r.indexOf(",5") >= 0)) return true;
        delay(1000);
    }
    return false;
}

int modem_csq() {
    String r;
    if (!at("AT+CSQ", "OK", 1000, &r)) return -1;
    int p = r.indexOf("+CSQ:");
    return p < 0 ? -1 : rk_parse_csq(r.substring(p).c_str());
}

bool modem_gnss(rk_gnss_t *out, uint32_t timeout_s) {
    at("AT+CGNSSPWR=1", "READY", 8000); // module prints +CGNSSPWR: READY! when the GNSS engine is up
    uint32_t t0 = millis();
    while (millis() - t0 < timeout_s * 1000UL) {
        String r;
        if (at("AT+CGNSSINFO", "OK", 1500, &r)) {
            int p = r.indexOf("+CGNSSINFO:");
            if (p >= 0) {
                int e = r.indexOf('\n', p);
                String line = r.substring(p, e < 0 ? r.length() : e);
                rk_gnss_t g;
                if (rk_parse_cgnssinfo(line.c_str(), &g) == 0 && g.fix) {
                    *out = g;
                    return true;
                }
            }
        }
        delay(2000);
    }
    return false;
}

bool modem_upload_ca(const char *pem) {
    size_t n = strlen(pem);
    if (!n) return false;
    if (!at(String("AT+CCERTDOWN=\"ca.pem\",") + n, ">", 2000)) return false;
    MS.write((const uint8_t *)pem, n);
    return pump(5000, "OK", "ERROR");
}

bool modem_mqtt_connect(const MqttConfig &c, modem_cmd_cb on_cmd) {
    g_on_cmd = on_cmd;
    g_mqtt_up = false;
    at("AT+CMQTTDISC=0,60", "OK", 3000);
    at("AT+CMQTTREL=0", "OK", 2000);
    at("AT+CMQTTSTOP", "OK", 3000);
    if (!at("AT+CMQTTSTART", "+CMQTTSTART: 0", 8000)) return false;
    if (!at(String("AT+CMQTTACCQ=0,\"") + c.client_id + "\"," + (c.tls ? 1 : 0))) return false;
    if (c.tls) {
        at("AT+CSSLCFG=\"sslversion\",0,4");
        at("AT+CSSLCFG=\"authmode\",0,1");
        at("AT+CSSLCFG=\"cacert\",0,\"ca.pem\"");
        if (!at("AT+CMQTTSSLCFG=0,0")) return false;
    }
    size_t wt = strlen(c.will_topic), wm = strlen(c.will_msg);
    if (!at_data(String("AT+CMQTTWILLTOPIC=0,") + wt, (const uint8_t *)c.will_topic, wt)) return false;
    if (!at_data(String("AT+CMQTTWILLMSG=0,") + wm + ",1", (const uint8_t *)c.will_msg, wm)) return false;
    // clean_session = 0: the broker keeps our subscription and queued QoS 1 commands across 4G drops.
    String conn = String("AT+CMQTTCONNECT=0,\"") + (c.tls ? "tcp://" : "tcp://") + c.host + ":" + c.port + "\",60,0,\"" + c.user + "\",\"" + c.pass + "\"";
    if (!at(conn, "+CMQTTCONNECT: 0,0", 20000)) return false;
    size_t st = strlen(c.sub_topic);
    if (!at_data(String("AT+CMQTTSUBTOPIC=0,") + st + ",1", (const uint8_t *)c.sub_topic, st)) return false;
    if (!at("AT+CMQTTSUB=0", "+CMQTTSUB: 0,0", 8000)) return false;
    g_mqtt_up = true;
    return true;
}

void modem_mqtt_disconnect() {
    at("AT+CMQTTDISC=0,60", "OK", 3000);
    g_mqtt_up = false;
}

bool modem_mqtt_connected() { return g_mqtt_up; }

bool modem_publish(const char *topic, const uint8_t *payload, size_t len, uint8_t qos) {
    if (!g_mqtt_up) return false;
    size_t tl = strlen(topic);
    if (!at_data(String("AT+CMQTTTOPIC=0,") + tl, (const uint8_t *)topic, tl)) return false;
    if (!at_data(String("AT+CMQTTPAYLOAD=0,") + len, payload, len)) return false;
    g_pub_result = -1;
    MS.print(String("AT+CMQTTPUB=0,") + qos + ",60\r\n");
    uint32_t t0 = millis();
    while (millis() - t0 < 15000 && g_pub_result < 0) pump(200);
    if (g_pub_result < 0) g_mqtt_up = false; // no answer: treat the session as dead, the caller reconnects
    return g_pub_result == 1;
}

void modem_poll(uint32_t ms) { pump(ms); }
