#pragma once
#include <Arduino.h>

extern "C" {
#include "rk_ring.h"
}

// Latest reading sent in the clear (message 0x03) so the hub's edge rules can steer the flap/fan without holding tag keys.
// It drives actuators only: the sealed, chained frames are what reaches the ledger.
struct LiveReading {
    int16_t temp_x100 = 0;
    uint16_t rh_x100 = 0;
    uint16_t eth_x10 = 0;
    bool valid = false;
};

struct BleResult {
    bool connected = false;
    int sent = 0;
    bool acked = false;
    uint32_t epoch = 0;          // hub time from the ACK (0 if none)
    bool paired = false;
    char shipment_id[17] = {0};  // set when the hub wrote a pairing message
};

// Advertise for `window_ms`; if the hub connects, send up to `max_frames` from the ring and wait for the ACK.
// Records are removed from the ring ONLY after a valid ACK covering them.
BleResult ble_offer_batch(rk_ring_t *ring, uint32_t window_ms, int max_frames, const LiveReading &live);
