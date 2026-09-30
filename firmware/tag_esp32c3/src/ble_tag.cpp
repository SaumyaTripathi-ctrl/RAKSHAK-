#include "ble_tag.h"

#include <NimBLEDevice.h>

#include "config.h"

extern "C" {
#include "rk_ble.h"
#include "rk_codec.h"
}

namespace {
volatile bool g_connected = false;
volatile bool g_ack = false;
volatile bool g_pair = false;
uint32_t g_ack_first = 0, g_ack_last = 0, g_ack_epoch = 0;
char g_ship[17] = {0};
uint32_t g_pair_epoch = 0;

class ServerCb : public NimBLEServerCallbacks {
    void onConnect(NimBLEServer *, NimBLEConnInfo &) override { g_connected = true; }
    void onDisconnect(NimBLEServer *, NimBLEConnInfo &, int) override { g_connected = false; }
};

class AckCb : public NimBLECharacteristicCallbacks {
    void onWrite(NimBLECharacteristic *c, NimBLEConnInfo &) override {
        NimBLEAttValue v = c->getValue();
        if (rk_ble_parse_ack(v.data(), v.size(), &g_ack_first, &g_ack_last, &g_ack_epoch) == RK_OK) g_ack = true;
    }
};

class PairCb : public NimBLECharacteristicCallbacks {
    void onWrite(NimBLECharacteristic *c, NimBLEConnInfo &) override {
        NimBLEAttValue v = c->getValue();
        if (v.size() == 21 && v.data()[0] == 0x20) {
            memcpy(g_ship, v.data() + 1, 16);
            g_ship[16] = '\0';
            g_pair_epoch = (uint32_t)v.data()[17] | ((uint32_t)v.data()[18] << 8) | ((uint32_t)v.data()[19] << 16) | ((uint32_t)v.data()[20] << 24);
            g_pair = true;
        }
    }
};

bool notify_frames(NimBLECharacteristic *ch, rk_ring_t *ring, int max_frames, uint32_t *first, uint32_t *last, int *count) {
    uint8_t frame[RK_MAX_FRAME_LEN];
    static uint8_t frag[8][RK_BLE_MAX_NOTIFY];
    size_t frag_len[8];
    *count = 0;
    const size_t payload = RK_BLE_MAX_NOTIFY; // MTU 247 was requested; fragmentation handles a smaller one
    for (uint32_t i = 0; i < ring->count && *count < max_frames; i++) {
        size_t len;
        if (rk_ring_peek(ring, i, frame, sizeof frame, &len) != RK_OK) break;
        uint32_t seq = (uint32_t)frame[20] | ((uint32_t)frame[21] << 8) | ((uint32_t)frame[22] << 16) | ((uint32_t)frame[23] << 24);
        int nf = rk_ble_fragment(frame, len, (uint8_t)*count, payload, frag, frag_len, 8);
        if (nf < 0) break;
        for (int k = 0; k < nf; k++) {
            ch->setValue(frag[k], frag_len[k]);
            if (!ch->notify()) return false;
            delay(8); // let the stack drain
        }
        if (*count == 0) *first = seq;
        *last = seq;
        (*count)++;
    }
    return *count > 0;
}
} // namespace

BleResult ble_offer_batch(rk_ring_t *ring, uint32_t window_ms, int max_frames, const LiveReading &live) {
    BleResult res;
    g_connected = g_ack = g_pair = false;

    NimBLEDevice::init("RKS-TAG");
    NimBLEDevice::setMTU(BLE_MTU);
    NimBLEDevice::setPower(ESP_PWR_LVL_N0);
    NimBLEServer *server = NimBLEDevice::createServer();
    server->setCallbacks(new ServerCb());
    NimBLEService *svc = server->createService(RK_SERVICE_UUID);
    NimBLECharacteristic *frames = svc->createCharacteristic(RK_CHAR_FRAMES, NIMBLE_PROPERTY::NOTIFY);
    NimBLECharacteristic *ack = svc->createCharacteristic(RK_CHAR_ACK, NIMBLE_PROPERTY::WRITE);
    NimBLECharacteristic *pair = svc->createCharacteristic(RK_CHAR_PAIR, NIMBLE_PROPERTY::WRITE);
    ack->setCallbacks(new AckCb());
    pair->setCallbacks(new PairCb());
    svc->start();
    NimBLEAdvertising *adv = NimBLEDevice::getAdvertising();
    adv->addServiceUUID(RK_SERVICE_UUID);
    adv->start();

    uint32_t t0 = millis();
    while (!g_connected && millis() - t0 < window_ms) delay(20);
    res.connected = g_connected;
    if (g_connected) {
        delay(400); // let the hub discover services, subscribe and (optionally) negotiate the MTU
        if (live.valid) {
            uint8_t lm[7] = {0x03, (uint8_t)live.temp_x100, (uint8_t)((uint16_t)live.temp_x100 >> 8), (uint8_t)live.rh_x100, (uint8_t)(live.rh_x100 >> 8), (uint8_t)live.eth_x10, (uint8_t)(live.eth_x10 >> 8)};
            frames->setValue(lm, sizeof lm);
            frames->notify();
            delay(8);
        }
        uint32_t first = 0, last = 0;
        int count = 0;
        if (ring->count > 0 && notify_frames(frames, ring, max_frames, &first, &last, &count)) {
            uint8_t end[16];
            size_t n = rk_ble_pack_end(end, (uint16_t)count, first, last);
            frames->setValue(end, n);
            frames->notify();
            res.sent = count;
            uint32_t t1 = millis();
            while (!g_ack && g_connected && millis() - t1 < 3000) delay(20);
            if (g_ack && g_ack_first == first && g_ack_last >= last) { // the ACK must cover what we sent
                rk_ring_ack(ring, g_ack_first, g_ack_last);            // delete ONLY after the hub's ACK
                res.acked = true;
                res.epoch = g_ack_epoch;
            }
        } else {
            // nothing to send: still wait briefly for a pairing write / time from the hub
            delay(800);
        }
        if (g_pair) {
            res.paired = true;
            memcpy(res.shipment_id, g_ship, sizeof g_ship);
            res.epoch = g_pair_epoch;
        }
    }
    NimBLEDevice::deinit(true);
    return res;
}
