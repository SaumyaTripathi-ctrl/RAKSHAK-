#include "rk_ring.h"

#include <string.h>

#define MAGIC 0xA55Au
#define HDR 4u /* magic + len */

uint16_t rk_crc16(const uint8_t *data, size_t len) { /* CRC-16/CCITT-FALSE */
    uint16_t crc = 0xFFFF;
    for (size_t i = 0; i < len; i++) {
        crc ^= (uint16_t)data[i] << 8;
        for (int b = 0; b < 8; b++) crc = (crc & 0x8000) ? (uint16_t)((crc << 1) ^ 0x1021) : (uint16_t)(crc << 1);
    }
    return crc;
}

static uint32_t seq_of(const uint8_t *frame) {
    return (uint32_t)frame[20] | ((uint32_t)frame[21] << 8) | ((uint32_t)frame[22] << 16) | ((uint32_t)frame[23] << 24);
}

/* Returns frame length if the slot holds a valid frame, else 0. */
static size_t slot_frame(const uint8_t *slot, const uint8_t **frame) {
    uint16_t magic = (uint16_t)(slot[0] | (slot[1] << 8));
    uint16_t len = (uint16_t)(slot[2] | (slot[3] << 8));
    if (magic != MAGIC || len < RK_HEADER_LEN || len > RK_MAX_FRAME_LEN) return 0;
    uint16_t crc = (uint16_t)(slot[HDR + len] | (slot[HDR + len + 1] << 8));
    if (crc != rk_crc16(slot + HDR, len)) return 0;
    *frame = slot + HDR;
    return len;
}

static int read_slot(rk_ring_t *r, uint32_t slot, uint8_t *buf) { return r->dev.read(r->dev.ctx, slot, buf); }

int rk_ring_init(rk_ring_t *r, const rk_blockdev_t *dev) {
    if (!r || !dev || !dev->read || !dev->write || dev->slots < 2) return RK_ERR_ARG;
    memset(r, 0, sizeof *r);
    r->dev = *dev;

    /* Collect valid slots and find the oldest/newest by seq. Wrap-around of seq (u32) is not handled: the
     * device would have to emit 4 billion records first (at one per second: 136 years). */
    uint8_t buf[RK_SLOT_SIZE];
    int have = 0;
    uint32_t min_seq = 0, max_seq = 0, min_slot = 0, max_slot = 0, valid = 0;
    for (uint32_t s = 0; s < dev->slots; s++) {
        if (read_slot(r, s, buf) != 0) return RK_ERR_CRYPTO;
        const uint8_t *frame;
        if (!slot_frame(buf, &frame)) continue;
        uint32_t q = seq_of(frame);
        valid++;
        if (!have || q < min_seq) { min_seq = q; min_slot = s; }
        if (!have || q > max_seq) { max_seq = q; max_slot = s; }
        have = 1;
    }
    if (!have) return RK_OK; /* empty */
    r->tail = min_slot;
    r->head = (max_slot + 1) % dev->slots;
    r->count = valid;
    r->next_seq_hint = max_seq + 1;
    return RK_OK;
}

int rk_ring_push(rk_ring_t *r, const uint8_t *frame, size_t len) {
    if (!r || !frame || len < RK_HEADER_LEN || len > RK_MAX_FRAME_LEN) return RK_ERR_ARG;
    uint8_t buf[RK_SLOT_SIZE];
    memset(buf, 0, sizeof buf);
    buf[0] = (uint8_t)(MAGIC & 0xFF);
    buf[1] = (uint8_t)(MAGIC >> 8);
    buf[2] = (uint8_t)(len & 0xFF);
    buf[3] = (uint8_t)(len >> 8);
    memcpy(buf + HDR, frame, len);
    uint16_t crc = rk_crc16(frame, len);
    buf[HDR + len] = (uint8_t)(crc & 0xFF);
    buf[HDR + len + 1] = (uint8_t)(crc >> 8);

    if (r->count == r->dev.slots) { /* full: the oldest goes (and the loss is counted, never silent) */
        r->tail = (r->tail + 1) % r->dev.slots;
        r->count--;
        r->dropped++;
    }
    if (r->dev.write(r->dev.ctx, r->head, buf) != 0) return RK_ERR_CRYPTO;
    r->head = (r->head + 1) % r->dev.slots;
    r->count++;
    r->next_seq_hint = seq_of(frame) + 1;
    return RK_OK;
}

int rk_ring_peek(rk_ring_t *r, uint32_t i, uint8_t *frame, size_t cap, size_t *len) {
    if (!r || !frame || !len || i >= r->count) return RK_ERR_ARG;
    uint8_t buf[RK_SLOT_SIZE];
    if (read_slot(r, (r->tail + i) % r->dev.slots, buf) != 0) return RK_ERR_CRYPTO;
    const uint8_t *f;
    size_t n = slot_frame(buf, &f);
    if (!n) return RK_ERR_FORMAT;
    if (n > cap) return RK_ERR_SIZE;
    memcpy(frame, f, n);
    *len = n;
    return RK_OK;
}

int rk_ring_ack(rk_ring_t *r, uint32_t first_seq, uint32_t last_seq) {
    if (!r || first_seq > last_seq) return RK_ERR_ARG;
    int removed = 0;
    uint8_t buf[RK_SLOT_SIZE];
    while (r->count > 0) {
        if (read_slot(r, r->tail, buf) != 0) return RK_ERR_CRYPTO;
        const uint8_t *f;
        if (!slot_frame(buf, &f)) { /* a torn slot at the tail is garbage: drop it */
            r->tail = (r->tail + 1) % r->dev.slots;
            r->count--;
            continue;
        }
        uint32_t q = seq_of(f);
        if (q < first_seq || q > last_seq) break; /* only a contiguous acknowledged prefix is deleted */
        /* Invalidate the slot so a rescan after reboot does not resurrect it. */
        memset(buf, 0, sizeof buf);
        if (r->dev.write(r->dev.ctx, r->tail, buf) != 0) return RK_ERR_CRYPTO;
        r->tail = (r->tail + 1) % r->dev.slots;
        r->count--;
        removed++;
    }
    return removed;
}
