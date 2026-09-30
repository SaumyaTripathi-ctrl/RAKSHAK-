/*
 * Crash-safe ring buffer of encrypted frames over a slot-addressed block device (LittleFS file, flash
 * partition, or RAM in the host tests).
 *
 *  - Frames are stored exactly as sent (already AES-256-GCM encrypted); flash encryption is a second layer.
 *  - Each slot carries magic, length and CRC-16, so a torn write (power loss) is detected and ignored.
 *  - Nothing is held only in RAM: `rk_ring_init` rebuilds head/tail by scanning the slots, ordered by the
 *    frame's own `seq` (cleartext header, offset 20), so a reboot loses nothing that was stored.
 *  - Delete-after-ACK: `rk_ring_ack(first, last)` removes acknowledged frames from the tail.
 *  - When full, the OLDEST frame is overwritten and `dropped` is incremented (reported as an event upstream).
 */
#ifndef RK_RING_H
#define RK_RING_H

#include "rk_spec.h"

#ifdef __cplusplus
extern "C" {
#endif

#define RK_SLOT_SIZE 176u /* magic(2) len(2) frame(<=164) crc(2) + padding */

typedef struct {
    void *ctx;
    uint32_t slots;
    /* Return 0 on success. `buf` is always RK_SLOT_SIZE bytes. */
    int (*read)(void *ctx, uint32_t slot, uint8_t *buf);
    int (*write)(void *ctx, uint32_t slot, const uint8_t *buf);
} rk_blockdev_t;

typedef struct {
    rk_blockdev_t dev;
    uint32_t head;  /* next slot to write */
    uint32_t tail;  /* slot of the oldest unacknowledged frame */
    uint32_t count; /* unacknowledged frames */
    uint32_t dropped;
    uint32_t next_seq_hint; /* seq of the newest stored frame + 1 (informational) */
} rk_ring_t;

uint16_t rk_crc16(const uint8_t *data, size_t len);

/* Scan the device and rebuild state. RK_OK, or RK_ERR_ARG / RK_ERR_CRYPTO (I/O error). */
int rk_ring_init(rk_ring_t *r, const rk_blockdev_t *dev);

/* Append a frame (overwrites the oldest when full). */
int rk_ring_push(rk_ring_t *r, const uint8_t *frame, size_t len);

/* Read the i-th oldest unacknowledged frame (0 = oldest). RK_ERR_ARG if i >= count. */
int rk_ring_peek(rk_ring_t *r, uint32_t i, uint8_t *frame, size_t cap, size_t *len);

/* Remove acknowledged frames with seq in [first_seq, last_seq] from the tail. Returns how many were removed. */
int rk_ring_ack(rk_ring_t *r, uint32_t first_seq, uint32_t last_seq);

#ifdef __cplusplus
}
#endif
#endif
