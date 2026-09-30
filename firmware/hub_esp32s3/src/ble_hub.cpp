#include "ble_hub.h"

#include <NimBLEDevice.h>

#include "config.h"

extern "C" {
#include "rk_ble.h"
#include "rk_codec.h"
}

namespace {
TagLive g_lives[MAX_TAGS];
rk_ble_rx_t g_rx;
volatile bool g_live_seen = false;
const char *g_cur_addr = nullptr;
bool g_rx_error = false;

TagLive *live_slot(const char *addr) {
    TagLive *free_slot = nullptr, *oldest = &g_lives[0];
    for (auto &l : g_lives) {
        if (l.valid && strcmp(l.addr, addr) == 0) return &l;
        if (!l.valid && !free_slot) free_slot = &l;
        if (l.at_s < oldest->at_s) oldest = &l;
    }
    return free_slot ? free_slot : oldest;
}

void on_notify(NimBLERemoteCharacteristic *, uint8_t *data, size_t len, bool) {
    if (len == 7 && data[0] == RK_BLE_LIVE) { // cleartext live reading: steers the flap/fan only
        TagLive *l = live_slot(g_cur_addr ? g_cur_addr : "?");
        l->valid = true;
        strncpy(l->addr, g_cur_addr ? g_cur_addr : "?", sizeof l->addr - 1);
        l->temp_x100 = (int16_t)(data[1] | (data[2] << 8));
        l->rh_x100 = (uint16_t)(data[3] | (data[4] << 8));
        l->eth_x10 = (uint16_t)(data[5] | (data[6] << 8));
        l->at_s = millis() / 1000;
        g_live_seen = true;
        return;
    }
    if (rk_ble_rx_feed(&g_rx, data, len) != RK_OK) g_rx_error = true;
}

// Accept only well-formed frames: known type, exact length, current version. Bytes are otherwise untouched.
bool frame_ok(const uint8_t *f, size_t len) {
    if (len < RK_HEADER_LEN || f[0] != RK_VERSION) return false;
    return rk_frame_len(f[1]) == len;
}

int serve_tag(const NimBLEAdvertisedDevice *dev, rk_ring_t *ring, uint32_t epoch, const char *pair_shipment, int *paired) {
    NimBLEClient *cl = NimBLEDevice::createClient();
    cl->setConnectTimeout(5000);
    int stored = 0;
    static char addr[20];
    strncpy(addr, dev->getAddress().toString().c_str(), sizeof addr - 1);
    g_cur_addr = addr;
    if (cl->connect(dev)) {
        NimBLERemoteService *svc = cl->getService(RK_SERVICE_UUID);
        NimBLERemoteCharacteristic *fr = svc ? svc->getCharacteristic(RK_CHAR_FRAMES) : nullptr;
        NimBLERemoteCharacteristic *ack = svc ? svc->getCharacteristic(RK_CHAR_ACK) : nullptr;
        NimBLERemoteCharacteristic *pr = svc ? svc->getCharacteristic(RK_CHAR_PAIR) : nullptr;
        if (fr && ack && fr->subscribe(true, on_notify)) {
            rk_ble_rx_init(&g_rx);
            g_live_seen = g_rx_error = false;
            if (pair_shipment && pr) { // must precede the ACK: the tag reads the pairing write right after the ACK arrives
                uint8_t msg[21] = {0x20};
                strncpy((char *)msg + 1, pair_shipment, 16);
                for (int i = 0; i < 4; i++) msg[17 + i] = (uint8_t)(epoch >> (8 * i));
                if (pr->writeValue(msg, sizeof msg, true)) (*paired)++;
            }
            uint32_t t0 = millis(), live_at = 0;
            while (cl->isConnected() && !g_rx.complete && !g_rx_error && millis() - t0 < 4500) {
                if (g_live_seen && !live_at) live_at = millis();
                if (live_at && millis() - live_at > 1500) break; // live reading only: the tag had nothing to send
                delay(20);
            }
            if (g_rx.complete && !g_rx_error && cl->isConnected()) {
                int n = 0;
                bool all_ok = true;
                for (int i = 0; i < g_rx.n; i++) {
                    if (!frame_ok(g_rx.frames[i], g_rx.lens[i]) || rk_ring_push(ring, g_rx.frames[i], g_rx.lens[i]) != RK_OK) {
                        all_ok = false; // do NOT ack a batch we could not fully store: the tag keeps its copies
                        break;
                    }
                    n++;
                }
                stored = n;
                if (all_ok) {
                    uint8_t msg[13];
                    size_t ml = rk_ble_pack_ack(msg, g_rx.first_seq, g_rx.last_seq, epoch);
                    ack->writeValue(msg, ml, true);
                }
            }
        }
        cl->disconnect();
    }
    NimBLEDevice::deleteClient(cl);
    g_cur_addr = nullptr;
    return stored;
}
} // namespace

namespace {
ble_cmd_cb g_cmd_cb = nullptr;
NimBLEAdvertisedDevice g_pending;
volatile bool g_have_pending = false;

class ScanCb : public NimBLEScanCallbacks {
    void onResult(const NimBLEAdvertisedDevice *d) override {
        if (!g_have_pending && d->isAdvertisingService(NimBLEUUID(RK_SERVICE_UUID))) {
            g_pending = *d;
            g_have_pending = true;
            NimBLEDevice::getScan()->stop(); // connect now: the tag advertises for only a few seconds
        }
    }
};

class CmdCb : public NimBLECharacteristicCallbacks {
    void onWrite(NimBLECharacteristic *c, NimBLEConnInfo &) override {
        NimBLEAttValue v = c->getValue();
        if (g_cmd_cb && v.size() > 0 && v.size() < 256) g_cmd_cb((const char *)v.data(), v.size());
    }
};
} // namespace

void ble_hub_begin(ble_cmd_cb on_cmd) {
    g_cmd_cb = on_cmd;
    NimBLEDevice::init("RKS-HUB");
    NimBLEDevice::setMTU(247);
    NimBLEDevice::setPower(ESP_PWR_LVL_P3);
    NimBLEServer *server = NimBLEDevice::createServer();
    NimBLEService *svc = server->createService(RK_HUB_SERVICE_UUID);
    NimBLECharacteristic *ch = svc->createCharacteristic(RK_HUB_CMD_CHAR, NIMBLE_PROPERTY::WRITE);
    ch->setCallbacks(new CmdCb());
    svc->start();
    NimBLEAdvertising *adv = NimBLEDevice::getAdvertising();
    adv->addServiceUUID(RK_HUB_SERVICE_UUID);
    adv->start();
    NimBLEScan *scan = NimBLEDevice::getScan();
    scan->setScanCallbacks(new ScanCb(), false);
    scan->setActiveScan(true);
    scan->setInterval(100);
    scan->setWindow(99);
}

BleHubResult ble_hub_service(rk_ring_t *ring, uint32_t window_ms, uint32_t epoch, const char *pair_shipment, ble_idle_cb idle) {
    BleHubResult out;
    NimBLEScan *scan = NimBLEDevice::getScan();
    const uint32_t t0 = millis();
    while (millis() - t0 < window_ms) {
        if (!scan->isScanning() && !g_have_pending) scan->start(window_ms - (millis() - t0), false, true);
        if (g_have_pending) {
            scan->stop();
            out.tags_seen++;
            int paired = 0;
            int n = serve_tag(&g_pending, ring, epoch, (pair_shipment && !out.paired) ? pair_shipment : nullptr, &paired);
            out.sessions++;
            out.frames_stored += n;
            out.paired += paired;
            g_have_pending = false;
        }
        if (idle) idle();
        delay(20);
    }
    scan->stop();
    return out;
}

const TagLive *ble_hub_lives(int *n) {
    *n = MAX_TAGS;
    return g_lives;
}
