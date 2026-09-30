#include "rk_device.h"

#include <string.h>

static int get_u32(const rk_kv_t *kv, const char *k, uint32_t *out) {
    uint8_t b[4];
    if (kv->get(kv->ctx, k, b, 4) != 0) return -1;
    *out = (uint32_t)b[0] | ((uint32_t)b[1] << 8) | ((uint32_t)b[2] << 16) | ((uint32_t)b[3] << 24);
    return 0;
}

static int put_u32(const rk_kv_t *kv, const char *k, uint32_t v) {
    uint8_t b[4] = {(uint8_t)v, (uint8_t)(v >> 8), (uint8_t)(v >> 16), (uint8_t)(v >> 24)};
    return kv->put(kv->ctx, k, b, 4);
}

int rk_device_provision(const rk_kv_t *kv, const char *device_id, uint16_t key_epoch, const uint8_t key[RK_KEY_LEN]) {
    if (!kv || !device_id || !key) return RK_ERR_ARG;
    size_t n = strlen(device_id);
    if (n == 0 || n > RK_ID_LEN) return RK_ERR_ARG;
    uint8_t idbuf[RK_ID_LEN];
    memset(idbuf, 0, sizeof idbuf);
    memcpy(idbuf, device_id, n);
    uint32_t existing_seq;
    int first_time = get_u32(kv, "seq", &existing_seq) != 0;
    if (kv->put(kv->ctx, "id", idbuf, sizeof idbuf) != 0) return RK_ERR_STORAGE;
    if (put_u32(kv, "epoch", key_epoch) != 0) return RK_ERR_STORAGE;
    if (kv->put(kv->ctx, "key", key, RK_KEY_LEN) != 0) return RK_ERR_STORAGE;
    if (first_time) {
        uint8_t zero[RK_HASH_LEN] = {0};
        if (put_u32(kv, "seq", 0) != 0 || kv->put(kv->ctx, "prev", zero, RK_HASH_LEN) != 0) return RK_ERR_STORAGE;
    }
    return RK_OK;
}

int rk_device_load(rk_device_t *d, const rk_kv_t *kv, rk_ring_t *ring) {
    if (!d || !kv || !kv->get || !kv->put) return RK_ERR_ARG;
    memset(d, 0, sizeof *d);
    d->kv = *kv;
    d->ring = ring;
    uint8_t idbuf[RK_ID_LEN];
    uint32_t epoch;
    if (kv->get(kv->ctx, "id", idbuf, sizeof idbuf) != 0 || get_u32(kv, "epoch", &epoch) != 0 ||
        kv->get(kv->ctx, "key", d->key, RK_KEY_LEN) != 0 || get_u32(kv, "seq", &d->seq) != 0 ||
        kv->get(kv->ctx, "prev", d->prev_hash, RK_HASH_LEN) != 0)
        return RK_ERR_STORAGE;
    memcpy(d->device_id, idbuf, RK_ID_LEN);
    d->device_id[RK_ID_LEN] = '\0';
    d->key_epoch = (uint16_t)epoch;
    /* The ring may hold frames newer than the persisted seq if power failed between the two writes: never
     * go backwards. (Only the seq hint matters; the frames themselves are authoritative.) */
    if (ring && ring->count > 0 && ring->next_seq_hint > d->seq) d->seq = ring->next_seq_hint;
    return RK_OK;
}

int rk_device_emit(rk_device_t *d, uint8_t type, const uint8_t *body, size_t body_len, uint8_t *frame_out, size_t *frame_len) {
    if (!d || !body || !frame_out || !frame_len) return RK_ERR_ARG;
    if (body_len < RK_COMMON_LEN || body_len > RK_MAX_BODY_LEN || body[0] != RK_VERSION || body[1] != type) return RK_ERR_ARG;
    uint32_t seq = d->seq;
    /* 1. persist seq+1 BEFORE using seq. On failure nothing is encrypted. */
    if (put_u32(&d->kv, "seq", seq + 1) != 0) return RK_ERR_STORAGE;
    d->seq = seq + 1;
    /* 2. stamp the assigned seq and our id into the body (so body and frame header can never disagree), then
     *    encrypt + chain */
    uint8_t stamped[RK_MAX_BODY_LEN];
    memcpy(stamped, body, body_len);
    memset(stamped + 2, 0, RK_ID_LEN);
    memcpy(stamped + 2, d->device_id, strlen(d->device_id));
    stamped[34] = (uint8_t)seq;
    stamped[35] = (uint8_t)(seq >> 8);
    stamped[36] = (uint8_t)(seq >> 16);
    stamped[37] = (uint8_t)(seq >> 24);
    uint8_t hash[RK_HASH_LEN];
    size_t len = 0;
    int rc = rk_frame_encode(type, d->device_id, d->key_epoch, seq, d->key, stamped, body_len, d->prev_hash, frame_out,
                             RK_MAX_FRAME_LEN, &len, hash);
    if (rc != RK_OK) return rc;
    /* 3. persist the chain head, then the frame itself */
    if (d->kv.put(d->kv.ctx, "prev", hash, RK_HASH_LEN) != 0) return RK_ERR_STORAGE;
    memcpy(d->prev_hash, hash, RK_HASH_LEN);
    if (d->ring) {
        rc = rk_ring_push(d->ring, frame_out, len);
        if (rc != RK_OK) return rc;
    }
    *frame_len = len;
    return RK_OK;
}
