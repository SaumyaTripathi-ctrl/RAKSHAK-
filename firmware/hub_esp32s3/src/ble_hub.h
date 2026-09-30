// BLE central: scan for tags, pull their batched frames, store them in the hub ring and ACK by seq range.
// The hub never holds tag keys: frames are forwarded byte-for-byte, only the cleartext header is read.
#pragma once
#include <Arduino.h>

extern "C" {
#include "rk_ring.h"
}

struct TagLive {
    bool valid = false;
    char addr[20] = {0};
    int16_t temp_x100 = 0;
    uint16_t rh_x100 = 0;
    uint16_t eth_x10 = 0;
    uint32_t at_s = 0;  // hub monotonic seconds when received
};

struct BleHubResult {
    int tags_seen = 0;
    int sessions = 0;
    int frames_stored = 0;
    int paired = 0;
};

typedef void (*ble_cmd_cb)(const char *json, size_t len);
typedef void (*ble_idle_cb)();

// Starts the central (scanner) AND a small peripheral with a writable command characteristic, so an operator's phone can
// send the same JSON commands as MQTT when the truck has no 4G (RK_HUB_CMD_CHAR, written with a single <=200 B value).
void ble_hub_begin(ble_cmd_cb on_cmd);
// Scan for `window_ms`, servicing each tag the moment it is heard (tags only advertise for a few seconds). `idle` is called
// every ~20 ms while waiting (modem/serial polling). `epoch` (GNSS time, 0 if unknown) is returned in each ACK so tags can
// set their clocks. With `pair_shipment` non-null, the first tag served is paired to that shipment (PAIR write).
BleHubResult ble_hub_service(rk_ring_t *ring, uint32_t window_ms, uint32_t epoch, const char *pair_shipment, ble_idle_cb idle);
const TagLive *ble_hub_lives(int *n);
