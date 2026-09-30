// NVS key-value store and a raw-flash slot device for the encrypted ring buffer.
#pragma once

#include <Arduino.h>

extern "C" {
#include "rk_device.h"
#include "rk_ring.h"
}

bool storage_begin();                 // finds the ring partition and opens NVS
rk_kv_t storage_kv();                 // persistent identity / seq / chain head
rk_blockdev_t storage_blockdev(uint32_t slots);

// Small string settings (shipment id) kept next to the identity in NVS.
bool storage_get_str(const char *key, char *out, size_t cap);
bool storage_put_str(const char *key, const char *value);
