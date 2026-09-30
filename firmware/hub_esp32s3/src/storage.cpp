#include "storage.h"

#include <Preferences.h>
#include <esp_partition.h>

#include "config.h"

static Preferences prefs;
static const esp_partition_t *ring_part = nullptr;
static bool nvs_open = false;

bool storage_begin() {
    // The ring lives in the (otherwise unused) "spiffs" data partition of the default table, accessed raw: no filesystem.
    ring_part = esp_partition_find_first(ESP_PARTITION_TYPE_DATA, ESP_PARTITION_SUBTYPE_DATA_SPIFFS, nullptr);
    if (!ring_part) return false;
    nvs_open = prefs.begin(NVS_NS, false);
    return nvs_open;
}

static int kv_get(void *, const char *key, uint8_t *buf, size_t len) {
    if (!nvs_open || prefs.getBytesLength(key) != len) return -1;
    return prefs.getBytes(key, buf, len) == len ? 0 : -1;
}
static int kv_put(void *, const char *key, const uint8_t *buf, size_t len) {
    if (!nvs_open) return -1;
    return prefs.putBytes(key, buf, len) == len ? 0 : -1;
}
rk_kv_t storage_kv() { return rk_kv_t{nullptr, kv_get, kv_put}; }

// NOR flash: bits only go 1->0 without an erase. The ring writes each slot once per lap, sequentially, so we erase a
// 4 KB sector when the head enters it (23 slots per sector, 1 erase per 23 records). Invalidating an ACKed slot writes
// all-zeros over it, which needs no erase.
static constexpr uint32_t SLOTS_PER_SECTOR = RING_SECTOR / RK_SLOT_SIZE;
static size_t slot_addr(uint32_t slot) { return (size_t)(slot / SLOTS_PER_SECTOR) * RING_SECTOR + (size_t)(slot % SLOTS_PER_SECTOR) * RK_SLOT_SIZE; }

static int slot_read(void *, uint32_t slot, uint8_t *buf) { return esp_partition_read(ring_part, slot_addr(slot), buf, RK_SLOT_SIZE) == ESP_OK ? 0 : -1; }

static int slot_write(void *, uint32_t slot, const uint8_t *buf) {
    bool all_zero = true;
    for (size_t i = 0; i < RK_SLOT_SIZE; i++) {
        if (buf[i]) {
            all_zero = false;
            break;
        }
    }
    if (!all_zero && slot % SLOTS_PER_SECTOR == 0) {
        if (esp_partition_erase_range(ring_part, (size_t)(slot / SLOTS_PER_SECTOR) * RING_SECTOR, RING_SECTOR) != ESP_OK) return -1;
    }
    return esp_partition_write(ring_part, slot_addr(slot), buf, RK_SLOT_SIZE) == ESP_OK ? 0 : -1;
}

rk_blockdev_t storage_blockdev(uint32_t slots) {
    uint32_t fit = (uint32_t)(ring_part->size / RING_SECTOR) * SLOTS_PER_SECTOR;
    if (slots > fit) slots = fit;
    // A fresh (all 0xFF) partition has no valid slot magic, so the ring scan treats every slot as empty.
    return rk_blockdev_t{nullptr, slots, slot_read, slot_write};
}

bool storage_get_str(const char *key, char *out, size_t cap) {
    if (!nvs_open || !prefs.isKey(key)) return false;
    return prefs.getString(key, out, cap) > 0;
}
bool storage_put_str(const char *key, const char *value) { return nvs_open && prefs.putString(key, value) > 0; }
