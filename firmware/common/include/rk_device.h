/*
 * Device identity and record emission (shared by tag and hub).
 *
 * Rules enforced here (see firmware/common/spec/RECORD_SPEC.md):
 *   - `seq` is persisted BEFORE a record is encrypted and never reused; if persisted state cannot be read or
 *     written, the device REFUSES to encrypt (RK_ERR_STORAGE) - a repeated (key, nonce) pair would break GCM.
 *   - The hash chain head (`prev_hash`) is persisted after every record.
 *   - Re-provisioning bumps `key_epoch`; `seq` and the chain continue.
 */
#ifndef RK_DEVICE_H
#define RK_DEVICE_H

#include "rk_codec.h"
#include "rk_ring.h"

#ifdef __cplusplus
extern "C" {
#endif

#define RK_ERR_STORAGE (-6)

/* Key-value persistence (NVS on the ESP32). All functions return 0 on success. */
typedef struct {
    void *ctx;
    int (*get)(void *ctx, const char *key, uint8_t *buf, size_t len); /* exactly `len` bytes or failure */
    int (*put)(void *ctx, const char *key, const uint8_t *buf, size_t len);
} rk_kv_t;

typedef struct {
    rk_kv_t kv;
    rk_ring_t *ring;
    char device_id[RK_ID_LEN + 1];
    uint16_t key_epoch;
    uint8_t key[RK_KEY_LEN];
    uint32_t seq;
    uint8_t prev_hash[RK_HASH_LEN];
} rk_device_t;

/* Write id/epoch/key into storage (factory provisioning). `seq`/chain are NOT reset when re-provisioning an
 * already provisioned device; they start at 0 / genesis for a new one. */
int rk_device_provision(const rk_kv_t *kv, const char *device_id, uint16_t key_epoch, const uint8_t key[RK_KEY_LEN]);

/* Load identity + seq + chain head. RK_ERR_STORAGE if any of it cannot be read. */
int rk_device_load(rk_device_t *d, const rk_kv_t *kv, rk_ring_t *ring);

/* Persist seq, encrypt `body` into a frame, chain it, persist the chain head, store the frame in the ring. */
int rk_device_emit(rk_device_t *d, uint8_t type, const uint8_t *body, size_t body_len, uint8_t *frame_out, size_t *frame_len);

#ifdef __cplusplus
}
#endif
#endif
